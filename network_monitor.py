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

from __future__ import division
import copy
from operator import attrgetter
from ryu import cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event
from ryu.controller.controller import Datapath
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.ofproto import ofproto_v1_3_parser
from ryu.ofproto import ofproto_parser
from ryu.lib import hub
from ryu.lib.packet import packet
import setting

from setting import StatsType, PathEvaType

from network_awareness import NetworkAwareness
import network_awareness
from typing import List, Tuple, Dict, Set
import networkx as nx

CONF = cfg.CONF


class NetworkMonitor(app_manager.RyuApp):
    """
        NetworkMonitor is a Ryu app for collecting traffic information.
        还实现了计算并保存所有源交换机和目的交换机间按照最大带宽计算的最优路由
    """
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        "network_awareness": network_awareness.NetworkAwareness,
    }

    def __init__(self, *args, **kwargs):
        super(NetworkMonitor, self).__init__(*args, **kwargs)
        self.name = 'monitor'
        # 记录与控制器连接的Datapath dpid——>Datapath class
        self.datapaths: Dict[int, Datapath] = {}

        # 保存端口统计信息
        # Dict[key, value]
        # key: Tuple[dpid, port_no] 标识唯一端口
        # value: List[Tuple[tx_bytes rx_bytes, rx_errors, duration_sec, duration_nsec]] 存储端口统计信息
        self.port_stats: Dict[Tuple[int, int], List[Tuple[int, int, int, int, int]]] = {}

        # 保存端口速率信息
        # Dict[key, value]
        # key: Tuple[dpid, port_no] 标识唯一端口
        # value: List[float] 存储端口统计信息 speed bytes/s
        self.port_speed: Dict[Tuple[int, int], List[float]] = {}

        # 保存流统计信息 Dict[dpid, Dict[key, value]] 
        # key：Tuple[in_port, ipv4_dst, out_port] 用于标识流
        # value: List[Tuple[packet_count, byte_count, duration_sec, duration_nsec]]用于存储流统计消息列表
        self.flow_stats:  Dict[int, Dict[Tuple[int, str, int], List[Tuple[int, int, int, int]]]]  = {}

        # 保存流速率信息 Dict[dpid, Dict[key, value]] 
        # key：Tuple[in_port, ipv4_dst, out_port] 用于标识流
        # value: List[speed]用于存储流统计消息列表 speed： bytes/s
        self.flow_speed: Dict[int, Dict[Tuple[int, str, int], List[float]]]  = {}


        # 保存所有统计信息 
        # if CONF.weight == 'bw': 
        #   self.stats = {StatsType.FLOW.value ——> Dict[dpid, List[ofproto_v1_3_parser.OFPFlowStats]], 
        #                 StatsType.PORT.value ——> Dict[dpid, List[ofproto_v1_3_parser.OFPPortStats]]}
        #   self.stats[StatsType.FLOW.value][dpid] = body
        self.stats: Dict[str, Dict[int, List[ofproto_parser.MsgBase]]] = {}

        # 保存端口特征信息
        # Dict[key, value]
        # key: dpid
        # value: Dict[port_no, Tuple[config, state, curr_speed]] 
        # value：端口号——>(端口配置标签，端口状态，端口当前速率 curr_speed单位kbps)
        self.port_features: Dict[int, Dict[int, Tuple[str, str, int]]] = {}

        # 保存剩余带宽信息
        # Dict[key, value]
        # key: dpid
        # value: Dict[port_no, curr_bw]    curr_bw: 当前剩余带宽 单位：Mbit/s
        self.free_bandwidth: Dict[int, Dict[int, float]] = {}

        # 导入注册的ryu 应用： NetworkAwareness
        self.awareness: NetworkAwareness = lookup_service_brick('awareness')

        # nx Graph类链路添加带宽属性
        # self.graph[src_dpid][dst_dpid][PathEvaType.BANDWIDTH.value] = bandwidth
        self.graph: nx.Graph = self.awareness.graph

        # 保存原交换机到目的交换机的路径带宽
        # Dict[key, value]
        # key: src-dpid
        # value: Dict[dst-dpid, bw:float]
        self.capabilities: Dict[int, Dict[int, float]] = None

        # 保存所有源交换机和目的交换机间按照最大带宽计算的最优路由
        # Dict[key, value]
        # key: src-dpid
        # value: Dict[dst-dpid, Path]
        # Path: List[dpid]  
        self.best_paths: Dict[int, Dict[int, List[int]]] = None

        # Start to green thread to monitor traffic and calculating
        # free bandwidth of links respectively.
        # 定义两个协程 协程一：周期性请求端口和流的统计信息  协程二：周期性保存带宽信息到self.graph图类
        self.monitor_thread = hub.spawn(self._monitor)
        self.save_freebandwidth_thread = hub.spawn(self._save_bw_graph)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        """
            Record datapath's info
        """
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not datapath.id in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    def _monitor(self):
        """
            Main entry method of monitoring traffic.
        """
        while CONF.weight == 'bw':
            self.stats[StatsType.FLOW.value] = {}
            self.stats[StatsType.PORT.value] = {}
            for dp in self.datapaths.values():
                self.port_features.setdefault(dp.id, {})
                # 请求端口和流的统计信息
                self._request_stats(dp)
                # refresh data.
                self.capabilities = None
                self.best_paths = None
            hub.sleep(setting.MONITOR_PERIOD)
            if self.stats[StatsType.FLOW.value] or self.stats[StatsType.PORT.value]:
                if setting.TOSHOW:
                    self.show_stat(StatsType.FLOW.value)
                    self.show_stat(StatsType.PORT.value)
                    hub.sleep(1)

    def _save_bw_graph(self):
        """
            Save bandwidth data into networkx graph object.
        """
        while CONF.weight == 'bw':
            graph = self.create_bw_graph(self.free_bandwidth)
            # 初始化图属性 设置主机内部连接带宽
            for dpid in self.datapaths.keys():
                self.graph[dpid][dpid][PathEvaType.BANDWIDTH.value] = setting.SWITCH_INTERIOR_BANDWIDTH
            # 赋链路带宽值
            for (src_dpid, dst_dpid) in self.awareness.link_to_port:
                self.graph[src_dpid][dst_dpid][PathEvaType.BANDWIDTH.value] = graph[src_dpid][dst_dpid][PathEvaType.BANDWIDTH.value]
            self.logger.debug("save_freebandwidth")
            hub.sleep(setting.MONITOR_PERIOD)

    def _request_stats(self, datapath: Datapath):
        """
            Sending request msg to datapath
        """
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        if ofproto_v1_3.OFP_VERSION in self.OFP_VERSIONS: 
            parser: ofproto_v1_3_parser = datapath.ofproto_parser
        else:
            parser = datapath.ofproto_parser

        # 发送端口描述请求消息
        req = parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)
        # 发送端口统计信息请求消息
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
        # 发送流统计信息请求消息
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    def get_min_bw_of_links(self, graph, path, min_bw):
        """
            获取链路path的瓶颈带宽, 即每跳链路的带宽的最小值
            Getting bandwidth of path. Actually, the mininum bandwidth
            of links is the bandwith, because it is the neck bottle of path.
        """
        _len = len(path)
        if _len > 1:
            minimal_band_width = min_bw
            for i in range(_len-1):
                pre, curr = path[i], path[i+1]
                if PathEvaType.BANDWIDTH.value in graph[pre][curr]:
                    bw = graph[pre][curr][PathEvaType.BANDWIDTH.value]
                    minimal_band_width = min(bw, minimal_band_width)
                else:
                    continue
            return minimal_band_width
        return min_bw

    def get_best_path_by_bw(self, graph, paths)-> Tuple[Dict[int, Dict[int, float]], Dict[int, Dict[int, List[int]]]] :
        """
            Get best path by comparing paths.
            return: 
            - capabilities 保存原交换机到目的交换机的路径带宽
            # Dict[key, value]
            # key: src-dpid
            # value: Dict[dst-dpid, bw:float]
            - best_paths 保存所有源交换机和目的交换机间按照最大带宽计算的最优路由
            # Dict[key, value]
            # key: src-dpid
            # value: Dict[dst-dpid, Path]
            # Path: List[dpid]  
        """
        capabilities = {}
        best_paths = copy.deepcopy(paths)

        # paths: Dict[key, value]
        # key: src(源交换机dpid)
        # value: Dict[dst-dpid, List[path]]
        # path: List[dpid], path是由交换机dpid组成的元素列表例如[0, 1, 2, 3]
        self.shortest_paths: Dict[int, Dict[int, List[List[int]]]] = None

        for src in paths:
            for dst in paths[src]:
                if src == dst:
                    best_paths[src][src] = [src]
                    capabilities.setdefault(src, {src: setting.MAX_CAPACITY})
                    capabilities[src][src] = setting.MAX_CAPACITY
                    continue
                max_bw_of_paths = 0
                best_path = paths[src][dst][0]
                for path in paths[src][dst]:
                    min_bw = setting.MAX_CAPACITY
                    min_bw = self.get_min_bw_of_links(graph, path, min_bw)
                    if min_bw > max_bw_of_paths:
                        max_bw_of_paths = min_bw
                        best_path = path

                best_paths[src][dst] = best_path
                capabilities.setdefault(src, {dst: max_bw_of_paths})
                capabilities[src][dst] = max_bw_of_paths
        self.capabilities = capabilities
        self.best_paths = best_paths
        return capabilities, best_paths

    def create_bw_graph(self, bw_dict):
        """
            Save bandwidth data into networkx graph object.
        """
        try:
            # 通过awareness应用获取 网络neworkx DiGraph类
            graph = copy.deepcopy(self.graph)
            link_to_port = self.awareness.link_to_port
            for link in link_to_port:
                (src_dpid, dst_dpid) = link
                (src_port, dst_port) = link_to_port[link]
                # 选取链路link 计算可用带宽
                if src_dpid in bw_dict and dst_dpid in bw_dict:
                    # 源端口可用带宽
                    bw_src = bw_dict[src_dpid][src_port]
                    # 目的端口可用带宽
                    bw_dst = bw_dict[dst_dpid][dst_port]
                    # 源端口和目的端口间的带宽
                    bandwidth = min(bw_src, bw_dst)
                    # add key:value of bandwidth into graph.
                    graph[src_dpid][dst_dpid][PathEvaType.BANDWIDTH.value] = bandwidth
                else:
                    graph[src_dpid][dst_dpid][PathEvaType.BANDWIDTH.value] = 0
            return graph
        except:
            self.logger.info("Create bw graph exception")
            # if self.awareness is None:
            #     self.awareness = lookup_service_brick('awareness')
            return None

    def _save_freebandwidth(self, dpid, port_no, speed):
        # Calculate free bandwidth of port and save it.
        port_state = self.port_features.get(dpid).get(port_no)
        if port_state:
            capacity = port_state[2]
            curr_bw = self._get_free_bw(capacity, speed)
            self.free_bandwidth[dpid].setdefault(port_no, None)
            self.free_bandwidth[dpid][port_no] = curr_bw
        else:
            self.logger.info("Fail in getting port state")

    def _save_stats(self, _dict, key, value, length):
        if key not in _dict:
            _dict[key] = []
        _dict[key].append(value)

        if len(_dict[key]) > length:
            _dict[key].pop(0)

    def _get_speed(self, now, pre, period):
        if period:
            return (now - pre) / (period)
        else:
            return 0

    def _get_free_bw(self, capacity, speed):
        # BW:Mbit/s
        return max(capacity/10**3 - speed * 8/10**6, 0)

    def _get_time(self, sec, nsec):
        return sec + nsec / (10 ** 9)

    def _get_period(self, n_sec, n_nsec, p_sec, p_nsec):
        return self._get_time(n_sec, n_nsec) - self._get_time(p_sec, p_nsec)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        """
            Save flow stats reply info into self.flow_stats.
            Calculate flow speed and Save it.
        """
        # python3.8/dist-packages/ryu/ofproto/ofproto_v1 3_parser.py 中定义了中EventOFPFlowStatsReply 消息
        # 该消息的body是List of ``OFPFlowStats`` instance
        # OFPFlowStats 也在ofproto_v1 3_parser中被定义
        body: List[ofproto_v1_3_parser.OFPFlowStats]= ev.msg.body
        dpid: int = ev.msg.datapath.id
        self.stats[StatsType.FLOW.value][dpid] = body
        self.flow_stats.setdefault(dpid, {})
        self.flow_speed.setdefault(dpid, {})
        for stat in sorted([flow for flow in body if flow.priority == 1],
                           key=lambda flow: (flow.match.get('in_port'),
                                             flow.match.get('ipv4_dst'))):
            key = (stat.match['in_port'],  stat.match.get('ipv4_dst'),
                   stat.instructions[0].actions[0].port)
            # duration_sec 时长（秒）
            # duration_nsec 时长（纳秒）
            value = (stat.packet_count, stat.byte_count,
                     stat.duration_sec, stat.duration_nsec)
            # length表示 保存的该流的最大记录数量
            self._save_stats(self.flow_stats[dpid], key, value, length=5)

            # Get flow's speed.
            pre = 0
            period = setting.MONITOR_PERIOD
            tmp = self.flow_stats[dpid][key]
            if len(tmp) > 1:
                # 流key 倒数第二条统计消息记录中的字节数量
                pre = tmp[-2][1]
                period = self._get_period(tmp[-1][2], tmp[-1][3],
                                          tmp[-2][2], tmp[-2][3])

            # （最新统计的流字节量 - 上一次统计的流字节量） 除以统计时间
            speed = self._get_speed(self.flow_stats[dpid][key][-1][1],
                                    pre, period)

            self._save_stats(self.flow_speed[dpid], key, speed, 5)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        """
            Save port's stats info
            Calculate port's speed and save it.
        """
        #body: List of ``OFPPortStats`` instance
        body: List[ofproto_v1_3_parser.OFPPortStats] = ev.msg.body
        dpid = ev.msg.datapath.id
        self.stats[StatsType.PORT.value][dpid] = body
        self.free_bandwidth.setdefault(dpid, {})

        for stat in sorted(body, key=attrgetter('port_no')):
            port_no = stat.port_no
            # EventOFPPortStatsReply 端口必须是非本地端口（因为Reply消息是从交换机产生的，非控制器产生的）
            if port_no != ofproto_v1_3.OFPP_LOCAL:
                key = (dpid, port_no)
                value = (stat.tx_bytes, stat.rx_bytes, stat.rx_errors,
                         stat.duration_sec, stat.duration_nsec)

                self._save_stats(self.port_stats, key, value, 5)

                # Get port speed.
                pre = 0
                period = setting.MONITOR_PERIOD
                tmp = self.port_stats[key]
                if len(tmp) > 1:
                    pre = tmp[-2][0] + tmp[-2][1]
                    period = self._get_period(tmp[-1][3], tmp[-1][4],
                                              tmp[-2][3], tmp[-2][4])

                speed = self._get_speed(
                    self.port_stats[key][-1][0] + self.port_stats[key][-1][1],
                    pre, period)

                self._save_stats(self.port_speed, key, speed, 5)
                self._save_freebandwidth(dpid, port_no, speed)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        """
            Save port description info.
        """
        msg = ev.msg
        # body  List of ``OFPPort`` instance
        body: List[ofproto_v1_3_parser.OFPPort] =  ev.msg.body
        dpid = msg.datapath.id
        ofproto = msg.datapath.ofproto

        config_dict = {ofproto.OFPPC_PORT_DOWN: "Down",
                       ofproto.OFPPC_NO_RECV: "No Recv",
                       ofproto.OFPPC_NO_FWD: "No Farward",
                       ofproto.OFPPC_NO_PACKET_IN: "No Packet-in"}
        # OFPPS_LIVE 有效的快速故障备份组
        state_dict = {ofproto.OFPPS_LINK_DOWN: "Down",
                      ofproto.OFPPS_BLOCKED: "Blocked",
                      ofproto.OFPPS_LIVE: "Live"}

        ports = []
        # hw-addr MAC地址
        for p in body:
            ports.append('port_no=%d hw_addr=%s name=%s config=0x%08x '
                         'state=0x%08x curr=0x%08x advertised=0x%08x '
                         'supported=0x%08x peer=0x%08x curr_speed=%d '
                         'max_speed=%d' %
                         (p.port_no, p.hw_addr,
                          p.name, p.config,
                          p.state, p.curr, p.advertised,
                          p.supported, p.peer, p.curr_speed,
                          p.max_speed))
            # 判断端口的配置标签
            if p.config in config_dict:
                config = config_dict[p.config]
            else:
                config = "up"
            # 判断端口状态
            if p.state in state_dict:
                state = state_dict[p.state]
            else:
                state = "up"

            port_feature = (config, state, p.curr_speed)
            self.port_features[dpid][p.port_no] = port_feature
            print('---------------------------------port curr_speed---------------------------------')
            print(f"dpid: {dpid} port_no:{p.port_no} port_speed: {p.curr_speed}")

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status_handler(self, ev):
        """
            Handle the port status changed event.
            EventOFPPortStatus: 交换机向控制器通告端口状态 传递OFPort类实例(msg.desc)
            以及指示端口发生变化的三种情况: ADD端口增加, DELETE端口删除, MODIFY端口状态更新
            此函数在端口放生变化时打印变化消息
        """
        msg = ev.msg
        reason = msg.reason
        port_no = msg.desc.port_no
        dpid = msg.datapath.id
        ofproto = msg.datapath.ofproto

        reason_dict = {ofproto.OFPPR_ADD: "added",
                       ofproto.OFPPR_DELETE: "deleted",
                       ofproto.OFPPR_MODIFY: "modified", }

        if reason in reason_dict:
            print ("switch%d: port %s %s" % (dpid, reason_dict[reason], port_no))
        else:
            print ("switch%d: Illeagal port state %s %s" % (port_no, reason))

    def show_stat(self, type: StatsType):
        '''
            Show statistics info according to data type.
            type: 'port' 'flow'
        '''
        if setting.TOSHOW is False:
            return

        bodys = self.stats[type]
        if(type == StatsType.FLOW.value):
            print('datapath         ''   in-port        ip-dst      '
                  'out-port packets  bytes  flow-speed(B/s)')
            print('---------------- ''  -------- ----------------- '
                  '-------- -------- -------- -----------')
            for dpid in bodys.keys():
                for stat in sorted(
                    [flow for flow in bodys[dpid] if flow.priority == 1],
                    key=lambda flow: (flow.match.get('in_port'),
                                      flow.match.get('ipv4_dst'))):
                    print('%016x %8x %17s %8x %8d %8d %8.1f' % (
                        dpid,
                        stat.match['in_port'], stat.match['ipv4_dst'],
                        stat.instructions[0].actions[0].port,
                        stat.packet_count, stat.byte_count,
                        abs(self.flow_speed[dpid][
                            (stat.match.get('in_port'),
                            stat.match.get('ipv4_dst'),
                            stat.instructions[0].actions[0].port)][-1])))
            print ('\n')

        if(type == StatsType.PORT.value):
            print('datapath             port   ''rx-pkts  rx-bytes rx-error '
                  'tx-pkts  tx-bytes tx-error  port-speed(B/s)'
                  ' current-capacity(Kbps)  '
                  'port-stat   link-stat')
            print('----------------   -------- ''-------- -------- -------- '
                  '-------- -------- -------- '
                  '----------------  ----------------   '
                  '   -----------    -----------')
            format = '%016x %8x %8d %8d %8d %8d %8d %8d %8.1f %16d %16s %16s'
            for dpid in bodys.keys():
                for stat in sorted(bodys[dpid], key=attrgetter('port_no')):
                    if stat.port_no != ofproto_v1_3.OFPP_LOCAL:
                        print(format % (
                            dpid, stat.port_no,
                            stat.rx_packets, stat.rx_bytes, stat.rx_errors,
                            stat.tx_packets, stat.tx_bytes, stat.tx_errors,
                            abs(self.port_speed[(dpid, stat.port_no)][-1]),
                            self.port_features[dpid][stat.port_no][2],
                            self.port_features[dpid][stat.port_no][0],
                            self.port_features[dpid][stat.port_no][1]))
            print ('\n')

        if CONF.weight == 'bw':
            for u, v, data in self.graph.edges(data=True):
                if CONF.weight not in data.keys():
                    self._save_bw_graph()
                    return
                print(f"{u}——>{v} bw: {data['bw']}")