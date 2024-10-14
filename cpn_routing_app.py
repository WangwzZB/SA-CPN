# conding=utf-8
import logging
import struct
import networkx as nx
from operator import attrgetter
from ryu import cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event
from ryu.controller.controller import Datapath
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3, ether, inet, ofproto_v1_3_parser
from ryu.lib.packet import packet, ethernet, ipv4, arp, tcp, udp, icmp, ether_types
from ryu.lib import hub
from ryu.ofproto.ether import ETH_TYPE_ARP
from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link
from typing import List, Tuple, Dict, Set

import network_awareness
import shortest_forwarding
from network_awareness import NetworkAwareness
from shortest_forwarding import ShortestForwarding
import setting
from setting import SimNetworkSetUp, CPNRoutingAlgoName
import cpn_routing_algo
from cpn_routing_algo import CPNRoutingAlgo

import time
import numpy as np
import pandas as pd
import queue
import random

CONF = cfg.CONF

BROADCAST = 'ff:ff:ff:ff:ff:ff'
TARGET_MAC_ADDRESS = '00:00:00:00:00:00'


class CPNServiceForwardingEntry:
    """
    CPN服务条目 一条服务条目保存多个 待选服务实例ip+端口
    cpn_service_id 暂且用 任播地址 表示
    service_id: (anycast-ip:port)
    """
    def __init__(self, dpid: int, service_id: Tuple[str, int], type_of_transport_layer_proto: str = 'TCP', service_instance_list: List = [], forwarding_policy: List = [] , 
                 setup: SimNetworkSetUp = None):
        # 记录本服务路由条目所属的 dpid
        self.dpid = dpid
        # 记录本服务路由条目所属的 service_id
        self.service_id = service_id
        # 本服务路由条目所需的四层协议
        self.type_of_transport_layer_proto: str = type_of_transport_layer_proto
        # 列表元素是 （IP-Port） tuple 元组
        self.service_instance_list: List[Tuple[str, int]] = service_instance_list
        # 转发策略
        self.forwarding_policy: List[float] = forwarding_policy
        # 最新设置的服务转发ID （IP-Port） 
        self.newest_service_instance_id: Tuple[str, int] = ()
        # 标签位记录当前条目是否需要更新 默认需要更新
        self.to_be_delivered_flag = True
        # 记录此条目对应的交换机 Match类
        self.match: ofproto_v1_3_parser.OFPMatch = None
        # 记录此条目对应的交换机 反向条目
        self.match_back: ofproto_v1_3_parser.OFPMatch = None
        # 记录本路由条目上次由于 packet_in消息触发流表下发的时间
        self.updated_by_packet_in_msg_time = None
        # 全局设置类
        self.setup = setup
        # 转发队列
        self.forwading_queue = queue.Queue()

    def set_service_instance_list(self, service_instance_list):
        self.service_instance_list = service_instance_list

    def set_service_instance_list(self, forwarding_policy):
        self.forwarding_policy = forwarding_policy
    
    def update_newest_service_instance_id(self, global_forwarding_policy):
        """
        更新服务路由条目中的服务实例id
        routing_algo: 路由策略名称
        policy_update: 是否重新计算路由策略, 默认不重新计算而是使用旧策略(cpn_routing_algo类实例在初始化的时候会初始化一次路由表, 只有CFN才需要每次更新都计算新得策略)
        """
        # 判断路由策略类型
        policy_line_index  = self.dpid - self.setup.numberOfPrimeApps - 1
        if np.array_equal(global_forwarding_policy[policy_line_index], self.forwarding_policy):
            # 转发策略未更新
            index = self.forwading_queue.get()
            self.forwading_queue.put(index)
        else:
            # 转发策略更新
            self.forwarding_policy = global_forwarding_policy[policy_line_index]
            self.rouding_forwarding_policy(self.forwarding_policy)
            index = self.forwading_queue.get()
            self.forwading_queue.put(index)
        print(f"dpid: {self.dpid} forwading_queue{self.forwading_queue.queue}")
        self.newest_service_instance_id = self.service_instance_list[index]

    def rouding_forwarding_policy(self, forwarding_policy):
        """"
        根据浮点转发策略生成整数转发列表
        forwarding_policy: 本entry的转发策略
        """
        # 创建队列
        q = queue.Queue()
        n_service_instance = len(self.service_instance_list)
        # 整数化转发策略
        rouding_forwarding_policy = np.round(n_service_instance*forwarding_policy)
        # 根据整数化策略生成转发队列
        
        while np.sum(rouding_forwarding_policy) >= 1e-6:
            temp_list = []
            for i in range(n_service_instance):
                if rouding_forwarding_policy[i] >=1 :
                    rouding_forwarding_policy[i] -= 1
                    temp_list.append(i)
            # 打乱temp_list
            random.shuffle(temp_list)
            for item in temp_list:
                q.put(item)
        self.forwading_queue = q
        return q

        
class CPNRouting(app_manager.RyuApp):
    """
        CPN 路由应用, 在靠近用户集群侧的地方放置交换机, 将针对同质化应用的请求, 依概率转发
        客户端：
        - 1. 客户端向AnyCastIP:5000请求服务
        - 2. 由于不知道IP地址对应的MAC地址,所以客户端首先应该发起ARP请求
        - 3. 客户端收到响应报文,记录AnyCastIP------MAC表、
        - 4. 继续发起应用请求向AnyCastIP:5000请求服务
        控制器:
        - 1.交换机将ARP请求上报到控制器<br>
        - 2.控制判断出该ARP请求 的目的IP地址是 AnyCastIP和端口<br>
        - 3.控制器生成ARP Reply报文,设置自定义的MAC地址标识服务类型,要求交换机转发该响应报文
        - 4.交换机收到该请求,没有匹配路由条目,则上报给控制器<br>
        - 5.控制器判断该TCP或UDP请求目的IP地址和目的端口 匹配 已经记录的算力应用, 记录收到该数据包的交换机, 生成两个算力路由条目下发: 
          -- (1) 条目一: 将目的IP地址按概率改写为某个算力实例地址, 并要求交换机继续转发本此收到的数据包
          -- (2) 条目二: 当TCP或UDP请求的目的地址是本交换机直连地址, 且源目的地址 匹配 记录的最新转发算力应用实例, 
            且(该条目优先级最高), 则将该源地址改写为AnyCastIP
    """
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        "network_awareness": network_awareness.NetworkAwareness,
        "shortest_forwarding": shortest_forwarding.ShortestForwarding}
    
    def __init__(self, *args, **kwargs):
        super(CPNRouting, self).__init__(*args, **kwargs)
        self.name = 'cpn_routing'
        self.network_awareness: NetworkAwareness = lookup_service_brick('awareness')
        self.shortest_forwarding: ShortestForwarding = lookup_service_brick('shortest_forwarding')
        # CPNAllForwardingTable
        # key: dpid 第一次以交换机id为键
        # value: Dict[key2, value2] 服务路由条目字典为键值
        # key2: service_id(anycast_ip: port) 服务路由条目字典以服务id为键值
        # value2: CPNForwardingServiceEntry 以服务转发条目类为键值
        self.cpn_all_forwarding_table: Dict[int, Dict[Tuple[str, int], CPNServiceForwardingEntry]] = {}

        # key: service_id(anycast_ip:port), value: 该IP绑定的应用描述
        self.service_id_dict: Dict[Tuple[str, int], str] = {}

        # 记录交换机维护的CPNServiceID 列表 用于定期更新路由条目
        # key: dpid
        # value: Set[service_id]
        self.switch_maintained_cpn_service: Dict[int, Set[Tuple[str, int]]] = {}

        # 网络设置类
        self.sim_net_setting = SimNetworkSetUp()

        # cpn 算法类实例 会首先初始策略
        self.cpn_routing_algo = CPNRoutingAlgo(setup=self.sim_net_setting, routing_algo_name=setting.global_cpn_routing_algo_choice)

        # 初始化实验参数
        self.init_forwarding_table_thread = hub.spawn(self._init_testing_setting)
        # 周期性更新CPN策略
        self.cpn_switch_policy_update_thread = hub.spawn(self._cpn_switch_policy_update)
        # 记录各个目的ip被更新到的次数
        self.record_service_instance_update_times = {item:0 for item in self.sim_net_setting.prime_apps_ip_list}
    
    def _init_testing_setting(self):
        # 等待网络感知模块等进行网络的初始化
        time.sleep(15)
        # 添加任播IP地址 当前只测试一个应用
        if len(self.service_id_dict) == 0:
            self.service_id_dict = self.sim_net_setting.service_id_dict
        flag = True
        while flag:
            if len(self.cpn_all_forwarding_table) == 0 and self.network_awareness.graph.number_of_nodes() > 0:
                # 设置转发表
                switchB_dpid_list = self.sim_net_setting.switchB_dpid_list
                print(f"network_awareness.graph.nodes{self.network_awareness.graph.nodes()}")
                print(f"switchB_dpid_list: {switchB_dpid_list}")
                for dpid in switchB_dpid_list:
                    for service_id in self.service_id_dict.keys():
                        # 实例化CPNServiceForwardingEntry
                        service_instance_list = []
                        for item in self.sim_net_setting.prime_apps_ip_list:
                            service_instance_list.append((item, self.sim_net_setting.prime_app_instance_tcp_port))
                        # 创建服务路由条目，设置算法实例，协议类型，所属服务id等
                        entry=CPNServiceForwardingEntry(dpid=dpid,
                                                        service_id=service_id,
                                                        type_of_transport_layer_proto='TCP', 
                                                        service_instance_list=service_instance_list,
                                                        setup=self.sim_net_setting)
                        entry.update_newest_service_instance_id(self.cpn_routing_algo.global_forwarding_policy)
                        self.cpn_all_forwarding_table[dpid] = {service_id: entry}
                # 初始化switch_maintained_cpn_service
                # for dpid in self.sim_net_setting.switchB_dpid_list:
                #     self.switch_maintained_cpn_service[dpid] = set()
                #     self.switch_maintained_cpn_service[dpid].add(list(self.sim_net_setting.service_id_dict.keys())[0])

                flag = False
            else:
                hub.sleep(20)

    def _cpn_switch_policy_update(self):
        # 等待网络感知模块等进行网络的初始化
        time.sleep(20)
        while True:
            # 遍历维护算力路由的交换机
            if len(self.switch_maintained_cpn_service) == 0:
                hub.sleep(10)
                continue
            # 更新路由策略
            global_forwarding_policy = self.cpn_routing_algo.update_forwarding_policy()
            # print(f"global_forwarding_policy update: {global_forwarding_policy}")
            for dpid in self.switch_maintained_cpn_service.keys():
            # for dpid in list(self.switch_maintained_cpn_service.keys()):
                # 遍历交换机维护的service_id
                # 如果没有维护则返回
                for service_id in self.switch_maintained_cpn_service[dpid]:
                    old_time= self.cpn_all_forwarding_table[dpid][service_id].updated_by_packet_in_msg_time
                    new_time = time.time()
                    # 路由表不断更新的维持时间不超过 路由条目的存续时间
                    # if (new_time - old_time) > setting.FlowEntry_IDLET_IMEOUT:
                    #     continue
                    if self.cpn_all_forwarding_table[dpid][service_id].type_of_transport_layer_proto == 'TCP':
                        # 更新转发地址
                        self.cpn_all_forwarding_table[dpid][service_id].update_newest_service_instance_id(global_forwarding_policy)
                        dst_ip_port = self.cpn_all_forwarding_table[dpid][service_id].newest_service_instance_id
                        self.record_service_instance_update_times[dst_ip_port[0]] +=1
                        # 如果更新的地址一样则不重新下发流表
                        match_back: ofproto_v1_3_parser.OFPMatch = self.cpn_all_forwarding_table[dpid][service_id].match_back
                        if (match_back is None) or (dst_ip_port[0] ==  match_back['ipv4_src']):
                            continue
                        
                        eth_dst = None
                        # 查找目的IP地址的目的MAC地址
                        for ip_mac_item in self.network_awareness.access_table.values():
                            if ip_mac_item[0] == dst_ip_port[0]:
                                eth_dst = ip_mac_item[1]
                        old_match: ofproto_v1_3_parser.OFPMatch = self.cpn_all_forwarding_table[dpid][service_id].match
                        in_port = old_match['in_port']
                        ipv4_src = old_match['ipv4_src']
                        ipv4_dst = old_match['ipv4_dst']
                        tcp_dst = old_match['tcp_dst']
                        output = self.get_output_port(dpid=dpid, inport=in_port, ip_src=ipv4_src, ip_dst=dst_ip_port[0])
                                
                        # 生成action match action_back match_back
                        match = ofproto_v1_3_parser.OFPMatch(in_port=in_port,
                                                eth_type=ether.ETH_TYPE_IP,
                                                ip_proto=inet.IPPROTO_TCP,
                                                ipv4_src=ipv4_src,
                                                ipv4_dst=ipv4_dst,
                                                # tcp_src=pkt_tcp.src_port,
                                                tcp_dst=tcp_dst)
                        actions = [ofproto_v1_3_parser.OFPActionSetField(eth_dst=eth_dst),
                                    ofproto_v1_3_parser.OFPActionSetField(ipv4_dst=dst_ip_port[0]),
                                    ofproto_v1_3_parser.OFPActionSetField(tcp_dst=dst_ip_port[1]),
                                    ofproto_v1_3_parser.OFPActionOutput(output)]
                        match_back = ofproto_v1_3_parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                                    ip_proto=inet.IPPROTO_TCP,
                                                    ipv4_src=dst_ip_port[0],
                                                    ipv4_dst=ipv4_src,
                                                    tcp_src=dst_ip_port[1]
                                                    # tcp_dst=pkt_tcp.src_port
                                                    )
                        actions_back = [ofproto_v1_3_parser.OFPActionSetField(eth_src=setting.CPN_SERICE_REQUEST_MAC),
                                        ofproto_v1_3_parser.OFPActionSetField(ipv4_src=ipv4_dst),
                                        ofproto_v1_3_parser.OFPActionOutput(in_port)]
                    elif self.cpn_all_forwarding_table[dpid][service_id].type_of_transport_layer_proto == 'UDP':
                        # 更新路由策略
                        global_forwarding_policy = self.cpn_routing_algo.update_forwarding_policy()
                        # 更新转发地址
                        self.cpn_all_forwarding_table[dpid][service_id].update_newest_service_instance_id(global_forwarding_policy)
                        dst_ip_port = self.cpn_all_forwarding_table[dpid][service_id].newest_service_instance_id
                        # 如果更新的地址一样则不重新下发流表
                        match_back: ofproto_v1_3_parser.OFPMatch = self.cpn_all_forwarding_table[dpid][service_id].match_back
                        if dst_ip_port[0] ==  match_back['ipv4_src']:
                            continue
                        eth_dst = None
                        # 查找目的IP地址的目的MAC地址
                        for ip_mac_item in self.network_awareness.access_table.values():
                            if ip_mac_item[0] == dst_ip_port[0]:
                                eth_dst = ip_mac_item[1]
                        old_match: ofproto_v1_3_parser.OFPMatch = self.cpn_all_forwarding_table[dpid][service_id].match
                        in_port = old_match['in_port']
                        ipv4_src = old_match['ipv4_src']
                        ipv4_dst = old_match['ipv4_dst']
                        udp_dst = old_match['udp_dst']
                        output = self.get_output_port(dpid=dpid, inport=in_port, ip_src=ipv4_src, ip_dst=dst_ip_port[0])
                        match = ofproto_v1_3_parser.OFPMatch(in_port=in_port,
                                                eth_type=ether.ETH_TYPE_IP,
                                                ip_proto=inet.IPPROTO_UDP,
                                                ipv4_src=ipv4_src,
                                                ipv4_dst=ipv4_dst,
                                                udp_dst=udp_dst)
                        actions = [ofproto_v1_3_parser.OFPActionSetField(eth_dst=eth_dst),
                                    ofproto_v1_3_parser.OFPActionSetField(ipv4_dst=dst_ip_port[0]),
                                    ofproto_v1_3_parser.OFPActionSetField(tcp_dst=dst_ip_port[1]),
                                    ofproto_v1_3_parser.OFPActionOutput(output)]
                        match_back = ofproto_v1_3_parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                                    ip_proto=inet.IPPROTO_UDP,
                                                    ipv4_src=dst_ip_port[0],
                                                    ipv4_dst=ipv4_src,
                                                    udp_src=dst_ip_port[1]
                                                    # tcp_dst=pkt_tcp.src_port
                                                    )
                        actions_back = [ofproto_v1_3_parser.OFPActionSetField(eth_src=setting.CPN_SERICE_REQUEST_MAC),
                                        ofproto_v1_3_parser.OFPActionSetField(ipv4_src=ipv4_dst),
                                        ofproto_v1_3_parser.OFPActionOutput(in_port)]
                    # 发送修改Mod
                    # priority 高于默认优先级 0x8000
                    self.add_flow(self.shortest_forwarding.datapaths[dpid], match=match, actions=actions,
                            idle_timeout=setting.FlowEntry_IDLET_IMEOUT, hard_timeout=setting.FlowEntry_HARD_TIMOUT, priority=0x9000)
                    self.add_flow(self.shortest_forwarding.datapaths[dpid], match=match_back, actions=actions_back,
                            idle_timeout=setting.FlowEntry_IDLET_IMEOUT, hard_timeout=setting.FlowEntry_HARD_TIMOUT, priority=0x9000)
            # 周期性更新策略实现策略路由机制
            hub.sleep(setting.CPN_POCLICY_UPDATE_PERIOD)
            # 打印统计信息
            # print(f"record_service_instance_update_times:{self.record_service_instance_update_times}")

    def add_flow(self, datapath, priority, match, actions, idle_timeout, hard_timeout, 
                 buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath,
                                    idle_timeout=idle_timeout,
                                    hard_timeout = hard_timeout,
                                    buffer_id=buffer_id,
                                    priority=priority,
                                    flags=ofproto.OFPFF_SEND_FLOW_REM,
                                    match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath,
                                    idle_timeout=idle_timeout,
                                    hard_timeout = hard_timeout,
                                    priority=priority,
                                    flags=ofproto.OFPFF_SEND_FLOW_REM,
                                    match=match,
                                    instructions=inst)
        datapath.send_msg(mod)


    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        """
        处理交换机流删除消息
        """
        msg = ev.msg
        dp = msg.datapath
        match: ofproto_v1_3_parser.OFPMatch = msg.match
        if 'ipv4_dst' in match:
            if 'tcp_dst' in match:
                service_id = (str(match['ipv4_dst']), match['tcp_dst'])
                if  dp.id in self.cpn_all_forwarding_table.keys() and \
                    service_id in self.cpn_all_forwarding_table[dp.id].keys() and \
                    isinstance(self.cpn_all_forwarding_table[dp.id][service_id].match, ofproto_v1_3_parser.OFPMatch) and \
                    self.cpn_all_forwarding_table[dp.id][service_id].match['in_port'] == match['in_port'] and \
                    self.cpn_all_forwarding_table[dp.id][service_id].match['eth_type'] == match['eth_type'] and \
                    self.cpn_all_forwarding_table[dp.id][service_id].match['ip_proto'] == match['ip_proto']:

                    self.cpn_all_forwarding_table[dp.id][service_id].to_be_delivered_flag = True
                else:
                    return
            elif 'udp_dst' in match:
                service_id = (str(match['ipv4_dst']), match['udp_dst'])
                if  dp.id in self.cpn_all_forwarding_table.keys() and \
                    service_id in self.cpn_all_forwarding_table[dp.id].keys() and \
                    isinstance(self.cpn_all_forwarding_table[dp.id][service_id].match, ofproto_v1_3_parser.OFPMatch) and \
                    self.cpn_all_forwarding_table[dp.id][service_id].match['in_port'] == match['in_port'] and \
                    self.cpn_all_forwarding_table[dp.id][service_id].match['eth_type'] == match['eth_type'] and \
                    self.cpn_all_forwarding_table[dp.id][service_id].match['ip_proto'] == match['ip_proto']:

                    self.cpn_all_forwarding_table[dp.id][service_id].to_be_delivered_flag = True
                else:
                    return
        else:
            return

        self.logger.debug('OFPFlowRemoved received: '
                            'cookie=%d priority=%d  table_id=%d '
                            'duration_sec=%d duration_nsec=%d '
                            'idle_timeout=%d hard_timeout=%d '
                            'packet_count=%d byte_count=%d match.fields=%s',
                            msg.cookie, msg.priority, msg.table_id,
                            msg.duration_sec, msg.duration_nsec,
                            msg.idle_timeout, msg.hard_timeout,
                            msg.packet_count, msg.byte_count, msg.match)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """
            处理主机向CPN anycast IP 发起的 ARP请求
        """
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        # 解析以太网数据包
        eth_pkt = pkt.get_protocols(ethernet.ethernet)[0]
        eth_type = eth_pkt.ethertype

        # 初始化cpn_ip_list
        cpn_ip_list = [item[0] for item in self.service_id_dict.keys()]
        if eth_type == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocol(arp.arp)
            arp_src_ip = arp_pkt.src_ip
            arp_dst_ip = arp_pkt.dst_ip
            arp_src_mac = arp_pkt.src_mac
            arp_opcode = arp_pkt.opcode
            # 判断arp类型是ARP请求
            if arp_opcode == arp.ARP_REQUEST:
                # 控制判断该ARP请求 的目的IP地址是 AnyCastIP 即是在请求CPN服务
                if  arp_dst_ip in cpn_ip_list:
                    print("------------------------receive arp cpn ip---------------------------")
                    # 3.控制器生成ARP Reply报文,设置自定义的MAC地址标识服务类型,要求交换机转发该响应报文
                    # 3.1 生成报文内容
                    # setting.CPN_SERICE_REQUEST_MAC
                    data = self.generate_arp_reply_data(src_mac=setting.CPN_SERICE_REQUEST_MAC,
                                                        src_ip=arp_dst_ip,
                                                        target_mac=arp_src_mac,
                                                        target_ip=arp_src_ip)
                    # 3.2 要求交换机转发该响应报文
                    self._send_packet_to_port(datapath, in_port, data)
        elif eth_type == ether_types.ETH_TYPE_IP:
            # 解析ip报文
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            
            # 控制判断该IP数据包的目的IP地址是 AnyCastIP 即是在请求CPN服务
            if ip_pkt.dst in cpn_ip_list:
                add_flow_flag = False
                service_id: Tuple[str, int] = None
                match = None
                actions = None
                match_back = None
                actions_back = None
                if ip_pkt.proto == inet.IPPROTO_ICMP: # 判断是ICMP报文
                    icmp_pkt = pkt.get_protocol(icmp.icmp)
                    # 判断接受到的icmp报文是echo request报文
                    if icmp_pkt.type == icmp.ICMP_ECHO_REQUEST:
                        # 发送icmp reply报文
                        data = self.generate_icmp_reply_data(eth_pkt=eth_pkt, ip_pkt=ip_pkt, icmp_quest_pkt=icmp_pkt)
                        self._send_packet_to_port(datapath, in_port, data)
                        # 报文处理结束
                        return
                elif ip_pkt.proto == inet.IPPROTO_TCP:
                    # 判断CPN转发表是否初始化了 如果没有则返回
                    if len(self.cpn_all_forwarding_table) == 0:
                        return
                    # 记录该交换机维护的算力应用列表
                    # 先判断记录是否存在
                    if datapath.id in self.switch_maintained_cpn_service.keys():
                        self.switch_maintained_cpn_service[datapath.id].add((ip_pkt.dst, self.sim_net_setting.prime_app_instance_tcp_port))
                    else:
                        self.switch_maintained_cpn_service[datapath.id] = set()
                        self.switch_maintained_cpn_service[datapath.id].add((ip_pkt.dst, self.sim_net_setting.prime_app_instance_tcp_port))
                    # -- (1) 条目一: 当匹配service_id时候 将目的IP地址按概率改写为某个算力实例地址, 并要求交换机继续转发本此收到的数据包
                    # -- (2) 条目二: 当TCP或UDP请求的目的地址是本交换机直连地址, 且源目的地址 匹配 记录的最新转发算力应用实例, 
                    # 且(该条目优先级最高), 则将该源地址改写为AnyCastIP
                    pkt_tcp = pkt.get_protocol(tcp.tcp)
                    service_id = (ip_pkt.dst, pkt_tcp.dst_port)
                    
                    # 判断service_id 判断是否是否需要更新流表
                    if self.cpn_all_forwarding_table[datapath.id][service_id].type_of_transport_layer_proto == 'TCP' and \
                       self.cpn_all_forwarding_table[datapath.id][service_id].to_be_delivered_flag:
                        match = parser.OFPMatch(in_port=in_port,
                                                eth_type=ether.ETH_TYPE_IP,
                                                ip_proto=inet.IPPROTO_TCP,
                                                ipv4_src=ip_pkt.src,
                                                ipv4_dst=ip_pkt.dst,
                                                # tcp_src=pkt_tcp.src_port,
                                                tcp_dst=pkt_tcp.dst_port)
                        # 更新路由策略
                        global_forwarding_policy = self.cpn_routing_algo.update_forwarding_policy()
                        # 更新转发地址
                        self.cpn_all_forwarding_table[datapath.id][service_id].update_newest_service_instance_id(global_forwarding_policy)
                        dst_ip_port = self.cpn_all_forwarding_table[datapath.id][service_id].newest_service_instance_id
                        self.record_service_instance_update_times[dst_ip_port[0]] +=1
                        eth_dst = None
                        # 查找目的IP地址的目的MAC地址
                        for ip_mac_item in self.network_awareness.access_table.values():
                            if ip_mac_item[0] == dst_ip_port[0]:
                                eth_dst = ip_mac_item[1]
                        output = self.get_output_port(dpid=datapath.id, inport=in_port, ip_src=ip_pkt.src, ip_dst=dst_ip_port[0])
                        actions = [parser.OFPActionSetField(eth_dst=eth_dst),
                                parser.OFPActionSetField(ipv4_dst=dst_ip_port[0]),
                                parser.OFPActionSetField(tcp_dst=dst_ip_port[1]),
                                parser.OFPActionOutput(output)]
                        match_back = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                                    ip_proto=inet.IPPROTO_TCP,
                                                    ipv4_src=dst_ip_port[0],
                                                    ipv4_dst=ip_pkt.src,
                                                    tcp_src=dst_ip_port[1]
                                                    # tcp_dst=pkt_tcp.src_port
                                                    )
                        actions_back = [parser.OFPActionSetField(eth_src=setting.CPN_SERICE_REQUEST_MAC),
                                        parser.OFPActionSetField(ipv4_src=ip_pkt.dst),
                                        parser.OFPActionOutput(in_port)]
                        add_flow_flag = True
                elif ip_pkt.proto == inet.IPPROTO_UDP:
                    # 记录该交换机维护的算力应用列表
                    # 先判断记录是否存在
                    if datapath.id in self.switch_maintained_cpn_service.keys():
                        self.switch_maintained_cpn_service[datapath.id].add((ip_pkt.dst, self.sim_net_setting.prime_app_instance_tcp_port))
                    else:
                        self.switch_maintained_cpn_service[datapath.id] = set()
                        self.switch_maintained_cpn_service[datapath.id].add((ip_pkt.dst, self.sim_net_setting.prime_app_instance_tcp_port))
                    pkt_udp = pkt.get_protocol(udp.udp)
                    service_id = (ip_pkt.dst, pkt_udp.dst_port)
                    if self.cpn_all_forwarding_table[datapath.id][service_id].type_of_transport_layer_proto == 'UDP'and \
                       self.cpn_all_forwarding_table[datapath.id][service_id].to_be_delivered_flag:
                        match = parser.OFPMatch(in_port=in_port,
                                                eth_type=ether.ETH_TYPE_IP,
                                                ip_proto=inet.IPPROTO_UDP,
                                                ipv4_src=pkt_udp.src,
                                                ipv4_dst=pkt_udp.dst,
                                                # udp_src=pkt_udp.src_port,
                                                udp_dst=pkt_udp.dst_port)
                        # 更新路由策略
                        global_forwarding_policy = self.cpn_routing_algo.update_forwarding_policy()
                        # 更新转发地址
                        self.cpn_all_forwarding_table[datapath.id][service_id].update_newest_service_instance_id(global_forwarding_policy)
                        dst_ip_port = self.cpn_all_forwarding_table[datapath.id][service_id].newest_service_instance_id
                        eth_dst = None
                        # 查找目的IP地址的目的MAC地址
                        for ip_mac_item in self.network_awareness.access_table.values():
                            if ip_mac_item[0] == dst_ip_port[0]:
                                eth_dst = ip_mac_item[1]
                        output = self.get_output_port(dpid=datapath.id, inport=in_port, ip_src=ip_pkt.src, ip_dst=dst_ip_port[0])
                        actions = [parser.OFPActionSetField(eth_dst=eth_dst),
                                parser.OFPActionSetField(ipv4_dst=dst_ip_port[0]),
                                parser.OFPActionSetField(udp_dst=dst_ip_port[1]),
                                parser.OFPActionOutput(output)]

                        match_back = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                                    ip_proto=inet.IPPROTO_UDP,
                                                    ipv4_src=dst_ip_port[0],
                                                    ipv4_dst=ip_pkt.src,
                                                    udp_src=dst_ip_port[1]
                                                    # udp_dst=pkt_udp.src_port
                                                    )

                        actions_back = [parser.OFPActionSetField(eth_src=setting.CPN_SERICE_REQUEST_MAC),
                                        parser.OFPActionSetField(ipv4_src=ip_pkt.dst),
                                        parser.OFPActionOutput(in_port)]
                        add_flow_flag = True
                if add_flow_flag:
                    # priority 高于默认优先级 0x8000
                    self.add_flow(datapath, match=match, actions=actions,
                            idle_timeout=setting.FlowEntry_IDLET_IMEOUT, hard_timeout=setting.FlowEntry_HARD_TIMOUT, priority=0x9000)
                    self.add_flow(datapath, match=match_back, actions=actions_back,
                            idle_timeout=setting.FlowEntry_IDLET_IMEOUT, hard_timeout=setting.FlowEntry_HARD_TIMOUT, priority=0x9000)
                    # 更新控制器流表记录 确认流表已经更新 且记录匹配域
                    self.cpn_all_forwarding_table[datapath.id][service_id].to_be_delivered_flag = False
                    self.cpn_all_forwarding_table[datapath.id][service_id].match = match
                    self.cpn_all_forwarding_table[datapath.id][service_id].match_back = match_back
                    self.cpn_all_forwarding_table[datapath.id][service_id].updated_by_packet_in_msg_time = time.time()

                    d = None
                    if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                        d = msg.data

                    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                            in_port=in_port, actions=actions, data=d)
                    datapath.send_msg(out)
            else:
                return
    def _send_packet_to_port(self, datapath, port, data):
        if data is None:
            # Do NOT sent when data is None
            return
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(port=port)]
        # self.logger.info("packet-out %s" % (data,))
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    def generate_arp_reply_data(self, src_ip, src_mac, target_mac, target_ip):
        # Creat an empty Packet instance
        pkt = packet.Packet()

        pkt.add_protocol(ethernet.ethernet(ethertype=ETH_TYPE_ARP,
                                        dst=target_mac,
                                        src=src_mac))

        pkt.add_protocol(arp.arp(opcode=arp.ARP_REPLY,
                                src_mac=src_mac,
                                src_ip=src_ip,
                                dst_mac=target_mac,
                                dst_ip=target_ip))

        # Packet serializing
        pkt.serialize()
        data = pkt.data
        # print 'Built up a arp reply packet:', data
        return data
    
    def generate_icmp_reply_data(self, eth_pkt, ip_pkt, icmp_quest_pkt):
        reply_pkt = packet.Packet()
        # 生成以太网头部
        eth_reply = ethernet.ethernet(
            dst=eth_pkt.src,  # 交换源和目的地址
            src=eth_pkt.dst,
            ethertype=eth_pkt.ethertype
        )
        # 生成IP头部
        ip_reply = ipv4.ipv4(
            dst=ip_pkt.src,  # 交换源和目的IP地址
            src=ip_pkt.dst,
            proto=ip_pkt.proto,
            flags = 2
        )
        # 生成ICMP Echo Reply报文
        icmp_reply = icmp.icmp(
            type_=icmp.ICMP_ECHO_REPLY,
            code=icmp.ICMP_ECHO_REPLY_CODE,
            csum=0,  # 校验和会在打包时自动计算
            data=icmp_quest_pkt.data
        )
        # 将各个协议层打包在一起
        reply_pkt.add_protocol(eth_reply)
        reply_pkt.add_protocol(ip_reply)
        reply_pkt.add_protocol(icmp_reply)
        reply_pkt.serialize()

        return reply_pkt.data

    def send_icmp_reply(self, datapath, eth, ip_pkt, icmp_pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # 生成以太网头部
        eth_reply = ethernet.ethernet(
            dst=eth.src,  # 交换源和目的地址
            src=eth.dst,
            ethertype=eth.ethertype
        )

        # 生成IP头部
        ip_reply = ipv4.ipv4(
            dst=ip_pkt.src,  # 交换源和目的IP地址
            src=ip_pkt.dst,
            proto=ip_pkt.proto
        )

        # 生成ICMP Echo Reply报文
        icmp_reply = icmp.icmp(
            type_=icmp.ICMP_ECHO_REPLY,
            code=icmp.ICMP_ECHO_REPLY_CODE,
            csum=0,  # 校验和会在打包时自动计算
            data=icmp_pkt.data
        )

        # 将各个协议层打包在一起
        reply_pkt = packet.Packet()
        reply_pkt.add_protocol(eth_reply)
        reply_pkt.add_protocol(ip_reply)
        reply_pkt.add_protocol(icmp_reply)
        reply_pkt.serialize()

        # 创建OpenFlow消息并发送给交换机
        actions = [parser.OFPActionOutput(ofproto.OFPP_IN_PORT)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=reply_pkt.data
        )
        datapath.send_msg(out)

    def generate_broadcast_arp_request_data(self, src_mac, src_ip, target_ip):
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ETH_TYPE_ARP,
                                        dst=BROADCAST,
                                        src=src_mac))

        pkt.add_protocol(arp.arp(opcode=arp.ARP_REQUEST,
                                src_mac=src_mac,
                                src_ip=src_ip,
                                dst_mac=TARGET_MAC_ADDRESS,
                                dst_ip=target_ip))
        pkt.serialize()
        data = pkt.data
        # print 'Built up a broadcast arp request packet:', data
        return data
    
    def get_output_port(self, dpid, inport, ip_src, ip_dst):
         # result 返回 Tuple[src_sw_dpid, dst_sw_dpid] 源交换机和目的交换机地址
        result = self.shortest_forwarding.get_sw(dpid, inport, ip_src, ip_dst)
        if result:
            src_sw, dst_sw = result[0], result[1]
            # Path has already calculated, just get it.
            # 返回路径列表 [src-dpid, dpid, ..., dst-dpid]
            path = self.shortest_forwarding.get_path(src_sw, dst_sw, weight=self.shortest_forwarding.weight)
            if (path[0], path[1]) in self.network_awareness.link_to_port:
                return self.network_awareness.link_to_port[(path[0], path[1])][0]
