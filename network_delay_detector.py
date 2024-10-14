# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications. www.muzixing.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# conding=utf-8
from __future__ import division

import logging
from ryu import cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller.controller import Datapath
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.topology.switches import Switches
from ryu.topology.switches import LLDPPacket
from ryu.ofproto import ofproto_v1_0
from ryu.ofproto import ofproto_v1_2
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_4


import networkx as nx
import time
import setting
from setting import StatsType, PathEvaType

from typing import List, Tuple, Dict, Set
from network_awareness import NetworkAwareness
import network_awareness


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class NetworkDelayDetector(app_manager.RyuApp):
    """
        NetworkDelayDetector is a Ryu app for collecting link delay.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        "network_awareness": network_awareness.NetworkAwareness,
    }
    

    def __init__(self, *args, **kwargs):
        super(NetworkDelayDetector, self).__init__(*args, **kwargs)
        self.name = 'delaydetector'
        # Get the active object of swicthes and awareness module.
        # So that this module can use their data.
        self.sw_module: Switches = lookup_service_brick('switches')
        self.awareness: NetworkAwareness = lookup_service_brick('awareness')
        
        # 记录与控制器连接的Datapath dpid——>Datapath class
        self.datapaths: Dict[int, Datapath] = {}

        # 记录Echo时间，即控制器到交换机的时间
        # Dict[key, value]
        # key: dpid
        # value: time(s)
        self.echo_latency: Dict[int, float] = {}

        # 记录LLDP数据报文总时间 即
        # 0. controller 向所有交换机下发流表： 当接收到目的MAC地址为最近相邻交换机的LLDP报文时，不缓存该LLDP报文，全部上传给控制器(switches.py中实现)
        # 1. controller 针对每个交换机端口，生成一个对应的LLDP报文打上controller此时的时间戳(switches.py中实现)
        # 2. controller 下发 PacketOut 消息给该交换机，要求该交换机转发生成的LLDP报文(switches.py中实现)
        # 3. 交换机根据自身的流表把LLDP报文上传给控制器(switches.py中实现)
        # 4. 控制器接收到该报文，报文的帧头部存储了该报文是从哪个交换机收上来的，报文的body部分存储了报文是控制器下发给哪个交换机的(本文件实现)
        # 5. 确定由controller------switchA-------switchB------controller的时间(本文件实现)
        # Dict[key, value]
        # key: Tuple[src-dpid, dst-dpid] 标识链路
        # value: float 存储链路时延
        self.cssc_link_lldp_delay: Dict[Tuple[int, int], float] = {}
        self.measure_thread = hub.spawn(self._detector)

        self._init_switch_interior()

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        """
        此函数与monitor函数重复, 似乎应该删减归类
        """
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not datapath.id in self.datapaths:
                self.logger.debug('Register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('Unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        """
            Handle the echo reply msg, and get the latency of link.
        """
        now_timestamp = time.time()
        try:
            latency = now_timestamp - eval(ev.msg.data)
            self.echo_latency[ev.msg.datapath.id] = latency
        except:
            return

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
            Parsing LLDP packet and get the delay of link.
        """
        recv_timestamp = time.time()
        if not CONF.observe_links:
            return
        msg = ev.msg
        try:
            # 控制器下发LLDP packet-out的目的交换机
            src_dpid, src_port_no = LLDPPacket.lldp_parse(msg.data)
        except LLDPPacket.LLDPUnknownFormat:
            # This handler can receive all the packets which can be
            # not-LLDP packet. Ignore it silently
            return
        
        # 记录向交换机发送LLDP数据报文的源交换机及其发送端口
        dst_dpid = msg.datapath.id
        if msg.datapath.ofproto.OFP_VERSION == ofproto_v1_0.OFP_VERSION:
            dst_port_no = msg.in_port
        elif msg.datapath.ofproto.OFP_VERSION >= ofproto_v1_2.OFP_VERSION:
            dst_port_no = msg.match['in_port']
        else:
            LOG.error('cannot accept LLDP. unsupported version. %x',
                      msg.datapath.ofproto.OFP_VERSION)
            
        # 存储 cssc link时延
        if (src_dpid, dst_dpid) in self.awareness.link_to_port.keys():
            if self.sw_module is None:
                self.sw_module = lookup_service_brick('switches')
            for port in self.sw_module.ports.keys():
                if src_dpid == port.dpid and src_port_no == port.port_no:
                    send_timestamp = self.sw_module.ports[port].timestamp
                    if send_timestamp:
                        delay = max(recv_timestamp - send_timestamp, 0)
                        self.cssc_link_lldp_delay[(src_dpid, dst_dpid)] = delay
                        self._save_lldp_delay(src=src_dpid, dst=dst_dpid, lldpdelay=delay)
        else:
            LOG.debug(f'cannot find link{(src_dpid, dst_dpid)} in network awareness link_to_port dict')

    def _init_switch_interior(self):
        for node in self.awareness.graph.nodes:
            self.self.awareness.graph[node][node][PathEvaType.DELAY] = setting.SWITCH_INTERIOR_DELAY

    def _detector(self):
        """
            Delay detecting functon.
            Send echo request and calculate link delay periodically
        """
        while CONF.weight == 'delay':
            self._send_echo_request()
            self.create_link_delay()
            try:
                self.awareness.shortest_paths = {}
                self.logger.debug("Refresh the shortest_paths")
            except:
                self.awareness = lookup_service_brick('awareness')
            if setting.TOSHOW:
                self.show_delay_statis()
            hub.sleep(setting.DELAY_DETECTING_PERIOD)

    def _send_echo_request(self):
        """
            Seng echo request msg to datapath.
        """
        for datapath in self.datapaths.values():
            parser = datapath.ofproto_parser
            echo_req = parser.OFPEchoRequest(datapath, data=bytes("%.12f" % time.time(), encoding="utf8" ))
            datapath.send_msg(echo_req)
            # Important! Don't send echo request together, Because it will
            # generate a lot of echo reply almost in the same time.
            # which will generate a lot of delay of waiting in queue
            # when processing echo reply in echo_reply_handler.

            hub.sleep(setting.ECHO_REQUEST_INTERVAL)

    def get_delay(self, src, dst):
        """
            Get link delay.
                        Controller
                        |        |
        src echo latency|        |dst echo latency
                        |        |
                   SwitchA-------SwitchB
                        
                    fwd_delay--->
                        <----reply_delay
            delay = (forward delay + reply delay - src datapath's echo latency
        """
        try:
            fwd_delay = self.awareness.graph[src][dst][PathEvaType.LLDPDELAY.value]
            re_delay = self.awareness.graph[dst][src][PathEvaType.LLDPDELAY.value]
            src_latency = self.echo_latency[src]
            dst_latency = self.echo_latency[dst]
            
            delay = (fwd_delay + re_delay - src_latency - dst_latency)/2
            return max(delay, 0)
        except:
            return float('inf')

    def _save_lldp_delay(self, src=0, dst=0, lldpdelay=0):
        try:
            self.awareness.graph[src][dst][PathEvaType.LLDPDELAY.value] = lldpdelay
        except:
            if self.awareness is None:
                self.awareness = lookup_service_brick('awareness')
            return

    def create_link_delay(self):
        """
            Create link delay data, and save it into graph object.
        """
        try:
            for src in self.awareness.graph:
                for dst in self.awareness.graph[src]:
                    if src == dst:
                        self.awareness.graph[src][dst][PathEvaType.DELAY.value] = 0
                        continue
                    delay = self.get_delay(src, dst)
                    self.awareness.graph[src][dst][PathEvaType.DELAY.value] = delay
        except:
            if self.awareness is None:
                self.awareness = lookup_service_brick('awareness')
            return

    # def show_delay_statis(self):
    #     if setting.TOSHOW and self.awareness is not None:
    #         self.logger.info("\n src   dst      delay")
    #         self.logger.info("---------------------------")
    #         for src in self.awareness.graph:
    #             for dst in self.awareness.graph[src]:
    #                 delay = self.awareness.graph[src][dst][PathEvaType.D]
    #                 self.logger.info("%s<-->%s : %s" % (src, dst, delay))

    def show_delay_statis(self):
        if setting.TOSHOW and self.awareness is not None:
            print("\n src   dst      delay")
            print("---------------------------")
            for src in self.awareness.graph:
                for dst in self.awareness.graph[src]:
                    delay = self.awareness.graph[src][dst][PathEvaType.DELAY.value]
                    print("%s<-->%s : %s" % (src, dst, delay))