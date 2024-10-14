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
import array
import logging
import struct
import copy
import networkx as nx
from operator import attrgetter
from ryu import cfg
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import arp
from ryu.lib import hub

from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link

import numpy as np
from typing import List, Tuple, Dict, Set
import setting

import matplotlib.pyplot as plt
import networkx as nx
import os

CONF = cfg.CONF


class NetworkAwareness(app_manager.RyuApp):
    """
        NetworkAwareness is a Ryu app for discover topology information.
        This App can provide many data services for other App, such as
        link_to_port, access_table, switch_port_table,access_ports,
        interior_ports,topology graph and shorteest paths.
        此类主要完成的是拓扑信息的记录, 并不包含: 链路质量、端口状态、流状态统计
        此类通过接收处理ARP包记录了主机接入表access_table {(sw-dpid,port) :(host-ip, mac)}
    """
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(NetworkAwareness, self).__init__(*args, **kwargs)
        self.topology_api_app = self
        self.name = "awareness"
        # link_to_port 以字典存储交换机之间链路（dpid 对）与 端口对 的映射关系；
        self.link_to_port: Dict[Tuple[int, int], Tuple[int, int]] = {}          # (src_dpid,dst_dpid)->(src_port,dst_port)
        # access_table 以字典存储主机host的接入信息
        self.access_table: Dict[Tuple[int, int], Tuple[str, str]] = {}                # {(sw,port) :(host-ip, mac)}
        # switch_port_table 以字典存储交换机端口列表
        self.switch_port_table: Dict[int, Set[int]] = {}  # dpip->set(port_num)
        # access_ports 以字典存储交换机外部端口列表
        self.access_ports: Dict[int, Set[int]] = {}       # dpid->set(port_num)
        # interior_ports 以字典存储交换机内部端口列表
        self.interior_ports: Dict[int, Set[int]] = {}     # dpid->set(port_num)

        self.graph = nx.DiGraph()
        # pre_graph 上一次获取的图实例
        self.pre_graph = nx.DiGraph()
        # pre_access_table 上一次获取的主机接入信息
        self.pre_access_table:  Dict[Tuple[int, int], List[str]] = {}            # {(sw-dpid,port) :[host1_ip]}
        self.pre_link_to_port: Dict[Tuple[int, int], Tuple[int, int]] = {}       # (src_dpid,dst_dpid)->(src_port,dst_port)

        # 存储最短路径
        # Dict[key, value]
        # key: src(源交换机dpid)
        # value: Dict[dst-dpid, List[path]]
        # path= List[dpid], path是由交换机dpid组成的元素列表例如[0, 1, 2, 3]
        self.shortest_paths: Dict[int, Dict[int, List[List[int]]]] = None

        # Start a green thread to discover network resource.
        self.discover_thread = hub.spawn(self._discover)

        self.draw_picture_thread = hub.spawn(self._draw_network_graph)

        self.weight = setting.WEIGHT_MODEL[CONF.weight]


    def _discover(self):
        i = 0
        while True:
            if setting.TOSHOW:
                self.show_topology()
            if i == 5:
                self.get_topology(None)
                i = 0
            hub.sleep(setting.DISCOVERY_PERIOD)
            i = i + 1

    def _draw_network_graph(self):
        label = True
        while True:
            if setting.TOSHOW:
            # if True:
                # 添加权重标签
                edge_labels = {}
                # print("*****************************************Start drawing pic**************************************************")
                # print(f"self.graph.edges:{self.graph.edges(data=True)}")
                for u, v, data in self.graph.edges(data=True):
                    # print(f"self.weight: {self.weight} , {u}———>{v}, graph data: {data}")
                    if self.weight not in data.keys():
                        label = False
                        break
                    weight_value = data[self.weight]
                    
                    if self.weight == setting.WEIGHT_MODEL['hop']:
                        # edge_labels[(u, v)] = f"({u}->{v}) hop:{weight_value}"  # 将节点和权重标签放在一起显示
                        edge_labels[(u, v)] = f"({u}->{v})"  # 将节点和权重标签放在一起显示
                    elif self.weight == setting.WEIGHT_MODEL['delay']:
                        edge_labels[(u, v)] = f"({u}->{v}) delay:{weight_value}"
                    elif self.weight == setting.WEIGHT_MODEL['bw']:
                        edge_labels[(u, v)] = f"({u}->{v}) bw:{weight_value}"
                    else: break
                if label:
                    # 设置布局
                    pos = nx.spring_layout(self.graph, k=0.5)
                    # 绘制有向图，确保显示边的方向
                    nx.draw(self.graph, pos, with_labels=True, node_size=700, node_color="lightblue", font_size=12, arrows=True)
                    nx.draw_networkx_edge_labels(self.graph, pos, edge_labels=edge_labels, font_color='black', label_pos=0.3)
                    
                    # print(f"edge_labels: {edge_labels}")
                    folder_path  = '/home/wwz/ryu/ryu/app/network_awareness'
                    plt.savefig(os.path.join(folder_path, "graph.png"), dpi=400)
                    plt.close()
                    # plt.savefig('./test.png')
                    # print("*****************************************Saving success!**************************************************")
            else:
                break
            hub.sleep(setting.GENERATE_GRAPH_PIC_PERIOD)


    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
            Initial operation, send miss-table flow entry to datapaths.
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        msg = ev.msg
        self.logger.info("switch:%s connected", datapath.id)

        # install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, dp, p, match, actions, idle_timeout=0, hard_timeout=0):
        ofproto = dp.ofproto
        parser = dp.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]

        mod = parser.OFPFlowMod(datapath=dp, priority=p,
                                idle_timeout=idle_timeout,
                                hard_timeout=hard_timeout,
                                match=match, instructions=inst)
        dp.send_msg(mod)

    def get_host_location(self, host_ip):
        """
            Get host location info:(datapath, port) according to host ip.
        """
        for key in self.access_table.keys():
            if self.access_table[key][0] == host_ip:
                return key
        # self.logger.info("%s location is not found." % host_ip)
        return None

    def get_switches(self):
        return self.switches

    def get_links(self):
        return self.link_to_port


    def get_graph(self, link_list):
        """
            Get Adjacency matrix from link_to_port
        """
        for src in self.switches:
            for dst in self.switches:
                if src == dst:
                    self.graph.add_edge(src, dst, weight=0)
                elif (src, dst) in link_list:
                    self.graph.add_edge(src, dst, weight=1)
        return self.graph

    def create_port_map(self, switch_list):
        """
            Create interior_port table and access_port table. 
        """
        for sw in switch_list:
            dpid = sw.dp.id
            self.switch_port_table.setdefault(dpid, set())
            self.interior_ports.setdefault(dpid, set())
            self.access_ports.setdefault(dpid, set())

            for p in sw.ports:
                self.switch_port_table[dpid].add(p.port_no)

    def create_interior_links(self, link_list):
        """
            Get links`srouce port to dst port  from link_list,
            link_to_port:(src_dpid,dst_dpid)->(src_port,dst_port)
        """
        for link in link_list:
            src = link.src
            dst = link.dst
            self.link_to_port[
                (src.dpid, dst.dpid)] = (src.port_no, dst.port_no)

            # Find the access ports and interiorior ports
            if link.src.dpid in self.switches:
                self.interior_ports[link.src.dpid].add(link.src.port_no)
            if link.dst.dpid in self.switches:
                self.interior_ports[link.dst.dpid].add(link.dst.port_no)

    def create_access_ports(self):
        """
            Get ports without link into access_ports
        """
        for sw in self.switch_port_table:
            all_port_table = self.switch_port_table[sw]
            interior_port = self.interior_ports[sw]
            self.access_ports[sw] = all_port_table - interior_port

    def k_shortest_paths(self, graph, src, dst, weight='weight', k=1):
        """
            Great K shortest paths of src to dst.
        """
        # weight参数定义边属性的名称，该属性值用于计算最短路径
        generator = nx.shortest_simple_paths(graph, source=src,
                                             target=dst, weight=weight)
        shortest_paths = []
        try:
            for path in generator:
                if k <= 0:
                    break
                shortest_paths.append(path)
                k -= 1
            return shortest_paths
        except:
            self.logger.debug("No path between %s and %s" % (src, dst))

    def all_k_shortest_paths(self, graph, weight='weight', k=1):
        """
            Creat all K shortest paths between datapaths.
        """
        _graph = copy.deepcopy(graph)
        paths: Dict[int, Dict[int, List[List[int]]]] = {}

        # Find ksp in graph.
        for src in _graph.nodes():
            paths.setdefault(src, {src: [[src] for i in range(k)]})
            for dst in _graph.nodes():
                if src == dst:
                    continue
                paths[src].setdefault(dst, [])
                paths[src][dst] = self.k_shortest_paths(_graph, src, dst,
                                                        weight=weight, k=k)
        return paths

    # List the event list should be listened.
    events = [event.EventSwitchEnter,
              event.EventSwitchLeave, event.EventPortAdd,
              event.EventPortDelete, event.EventPortModify,
              event.EventLinkAdd, event.EventLinkDelete]

    @set_ev_cls(events)
    def get_topology(self, ev):
        """
            Get topology info and calculate shortest paths.
        """
        switch_list = get_switch(self.topology_api_app, None)
        self.create_port_map(switch_list)
        self.switches = self.switch_port_table.keys()
        links = get_link(self.topology_api_app, None)
        self.create_interior_links(links)
        # 这个access端口根据代码来看 似乎是表示交换机未被使用的端口
        self.create_access_ports()
        # 创建networkx实例
        self.get_graph(self.link_to_port.keys())
        # 计算k条最短路径
        self.shortest_paths = self.all_k_shortest_paths(
            self.graph, weight='weight', k=CONF.k_paths)

    def register_access_info(self, dpid, in_port, ip, mac):
        """
            Register access host info into access table.
        """
        if in_port in self.access_ports[dpid]:
            if (dpid, in_port) in self.access_table:
                if self.access_table[(dpid, in_port)] == (ip, mac):
                    return
                else:
                    self.access_table[(dpid, in_port)] = (ip, mac)
                    return
            else:
                self.access_table.setdefault((dpid, in_port), None)
                self.access_table[(dpid, in_port)] = (ip, mac)
                return

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """
            Hanle the packet in packet, and register the access info.
        """
        msg = ev.msg
        datapath = msg.datapath

        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)

        eth_type = pkt.get_protocols(ethernet.ethernet)[0].ethertype
        arp_pkt = pkt.get_protocol(arp.arp)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if arp_pkt:
            arp_src_ip = arp_pkt.src_ip
            arp_dst_ip = arp_pkt.dst_ip
            mac = arp_pkt.src_mac
            # print(f"arp_pkt_in src_ip:{arp_src_ip} dst_ip{arp_dst_ip} src_mac{mac}" )
            # Record the access info
            self.register_access_info(datapath.id, in_port, arp_src_ip, mac)
        


    def show_topology(self):
        switch_num = len(list(self.graph.nodes()))
        if self.pre_graph != self.graph and setting.TOSHOW:
            print("------------------Topo Adjacency List----------------")
            # 打印带有权重的邻接列表
            for node in self.graph.nodes:
                for neighbor, attrs in self.graph[node].items():
                    print(f"dpid:{node} -> dpid:{neighbor} (weight={attrs['weight']})")
            
            print("------------------Topo Adjacency Matrix--------------")
            print(f"Sorted nodes dpid list: {sorted(self.graph.nodes())}")
            # 生成邻接矩阵
            adj_matrix = nx.to_numpy_array(self.graph, weight='weight', nodelist=sorted(self.graph.nodes()))
            # 打印邻接矩阵
            print(adj_matrix)

            self.pre_graph = copy.deepcopy(self.graph)

        if self.pre_link_to_port != self.link_to_port and setting.TOSHOW:
            print ("---------------------Link Port----------------------")
            print ("switch dpid list:")
            for node in self.graph.nodes():
                print (f"dpid:{node} ", end='')
            print ("\n")
            for i in self.graph.nodes():
                print (f'-*-*-*-*- switch dpid:{i} -*-*-*-*-*-')
                for j in self.graph.nodes():
                    if (i, j) in self.link_to_port.keys():
                        print (f'dpid peer: {(i, j)} ——> port peer:{self.link_to_port[(i, j)]}')
                    else:
                        print (f'dpid peer: {(i, j)} ——> No-link')

            self.pre_link_to_port = copy.deepcopy(self.link_to_port)

        if self.pre_access_table != self.access_table and setting.TOSHOW:
            print ("--------------------Access Host---------------------")
            print ('%10s %12s' % ("switch", "Host"))
            if not self.access_table.keys():
                print ("    NO found host")
            else:
                for tup in self.access_table:
                    print ('%10s %12s' % (str(tup[0]), str(self.access_table[tup])))
            self.pre_access_table = copy.deepcopy(self.access_table)