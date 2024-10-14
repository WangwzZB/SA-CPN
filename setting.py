# Common Setting for Networ awareness module.
from enum import Enum
import numpy as np
import pandas as pd
from typing import Dict, Tuple
import json
# 10 15
DISCOVERY_PERIOD = 20   			# For discovering topology.
# 10 15
MONITOR_PERIOD = 20			 		# For monitoring traffic
# 5
DELAY_DETECTING_PERIOD = 10			# For detecting link delay.

# 60
GENERATE_GRAPH_PIC_PERIOD = 60	 #生成拓扑图片

TOSHOW = False						# For showing information in terminal
	
MAX_CAPACITY = 281474976710655		# Max capacity of link
# 0.05
ECHO_REQUEST_INTERVAL = 0.5        # Delay detector parameters

SWITCH_INTERIOR_BANDWIDTH = 1       # 交换机内部端口互联带宽

SWITCH_INTERIOR_DELAY = 0       # 交换机内部端口互联时延

CPN_SERICE_REQUEST_MAC = 'f0:00:00:00:00:01' # 服务任博MAC地址

# 流表项空闲时间，如值为 10，表示若某条流表在最近 10s 内没有被匹配过则删除
# 30 300
FlowEntry_IDLET_IMEOUT = 600

# 流表项存活时间，如值为 10，则从该流表被安装经过 10s 后无论被使用情况如何，立即被删除
FlowEntry_HARD_TIMOUT = 3600

# CPN策略路由的周期性更新策略
CPN_POCLICY_UPDATE_PERIOD = 4

# Dict[key, value]
# key: 启动最短路径应用时设置的weight
# value: 存储在network graph的边数据中的索引
WEIGHT_MODEL = {'hop': 'weight', 'delay': "delay", "bw": "bw"}

# 应用容器所能占用的主机最大cpu利用率
MAX_CPU_UTIL = 0.65

CPU_PERIOD=100000

# 容器最小CPU周期数量
MIN_CPU_PERIOD_FOR_DOCKER = 2000

CPN_NODE_REQUEST_DURATION_TIME = '240s'

# Prime Number
PRIME_NUMBER = 800

# 减小constant_throughput(1)后提升用户数量的比例
RATIO_INCREMENT_OF_USERS = 10


class CPNRoutingAlgoName(Enum):
    """
    枚举类型定义路由算法名称
    """
    # 简单策略均衡算法
    SIMPLE_POLICY_BALANCE_ALGO = 'balance_algo'
    # 最优传输算法
    OT_POLICY_ALGO = 'ot_algo'
    # CFN动态负载反馈算法
    CFN_DYNAMIC_FEEDBACK_ALGO = 'cfn_algo'
    # 最短链路时延选择算法
    SHORTEST_LINK_DELAY_ALGO = 'link_algo'
    # 按QPS加权策略均衡
    QPS_WEIGHTED_POLICY_ALGO = 'qps_weighted_algo'

# 全局路由算法选择
# global_cpn_routing_algo_choice = CPNRoutingAlgoName.SIMPLE_POLICY_BALANCE_ALGO
# global_cpn_routing_algo_choice = CPNRoutingAlgoName.QPS_WEIGHTED_POLICY_ALGO
# global_cpn_routing_algo_choice = CPNRoutingAlgoName.SHORTEST_LINK_DELAY_ALGO
global_cpn_routing_algo_choice = CPNRoutingAlgoName.OT_POLICY_ALGO
# global_cpn_routing_algo_choice = CPNRoutingAlgoName.CFN_DYNAMIC_FEEDBACK_ALGO


class PathEvaType(Enum):
    """
    枚举类型定义最短路径的评估类型
    """
    # 按跳数计算链路权重
    HOP = 'hop'
    # 按带宽计算链路权重
    BANDWIDTH = 'bw'
    # 按时延计算链路权重
    DELAY = 'delay'
    # 链路的LLDPdelay 即 controller----switchA----switchB-----controller 时延
    LLDPDELAY = 'lldpdelay'


class StatsType(Enum):
    """
    枚举类型定义统计消息的类别
    """
    FLOW = 'flow'
    PORT = 'port'


class SimNetworkSetUp():
    """
    仿真实验的网络设置
    """
    def __init__(self, *args, **kwargs):
        # 设置随机数种子
        self.random_seed = 68
        # rsnp.seed(self.random_seed)
        rsnp = np.random.RandomState(seed=self.random_seed)
        # 设置cpn节点数量
        self.numberOfCPNodes = 6
        # 设置质数应用服务节点数量
        self.numberOfPrimeApps = 4
        # 设置cpn节点的IP地址
        self.cpn_node_ip_list = [f'10.0.0.{j+1}' for j in range(self.numberOfCPNodes)]
        self.prime_apps_ip_list = []
        # 设置应用服务节点的IP地址列表
        for j in range(self.numberOfPrimeApps):
            self.prime_apps_ip_list.append(f'10.0.0.{self.numberOfCPNodes+j+1}')
        # 交换机pid设置
        self.switchA_dpid_list = [i+1 for i in range(self.numberOfPrimeApps)]
        self.switchB_dpid_list = [self.numberOfPrimeApps+i+1 for i in range(self.numberOfCPNodes)]

        # 定义cpn节点与应用服务节点的网络传输质量矩阵
        # 网络链路带宽矩阵设置 单位 Mbps
        self.network_link_bw_state = pd.DataFrame(rsnp.randint(low=10, high=36, size=(self.numberOfCPNodes, self.numberOfPrimeApps)),
                                            # 设置行名称
                                            index = [f"cpNode{i+1}" for i in range(self.numberOfCPNodes)],
                                            # 设置列名称
                                            columns = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)])
        # 计算cpn节点汇总链路带宽
        self.cpnodes_bw_to_switch = np.clip(np.sum(self.network_link_bw_state.to_numpy(), axis=1)+300, a_min=0, a_max=1000)
        # 计算应用服务节点汇总链路带宽
        self.prime_apps_bw_to_switch = np.clip(np.sum(self.network_link_bw_state.to_numpy(), axis=0)+300, a_min=0, a_max=1000)

        # 网络链路时延矩阵设置 单位 ms
        # 1,50   
        self.network_link_delay_state = pd.DataFrame(rsnp.randint(low=10, high=500, size=(self.numberOfCPNodes, self.numberOfPrimeApps)),
                                                # 设置行名称
                                                index = [f"cpNode{i+1}" for i in range(self.numberOfCPNodes)],
                                                # 设置列名称
                                                columns = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)])
        # 网络链路丢包率矩阵设置 单位百分数
        self.network_link_loss_state = pd.DataFrame(rsnp.uniform(low=0.0, high=0.0, size=(self.numberOfCPNodes, self.numberOfPrimeApps)),
                                                # 设置行名称
                                                index = [f"cpNode{i+1}" for i in range(self.numberOfCPNodes)],
                                                # 设置列名称
                                                columns = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)])
        # 网络链路抖动时延设置 单位ms
        self.network_link_jitter_state = pd.DataFrame(rsnp.randint(low=0, high=1, size=(self.numberOfCPNodes, self.numberOfPrimeApps)),
                                                # 设置行名称
                                                index = [f"cpNode{i+1}" for i in range(self.numberOfCPNodes)],
                                                # 设置列名称
                                                columns = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)])

        # 设置cpn节点应用服务请求到达率
        # self.app_request_arrival_rates = pd.DataFrame(rsnp.randint(low=10, high=100, size=self.numberOfCPNodes),
        #                                         # 设置行名称
        #                                         index = [f"cpNode{i+1}" for i in range(self.numberOfCPNodes)])

        # 分配应用服务节点算力资源量
        # 测试并设置应用服务节点处理能力
        temp = rsnp.normal(0, 5, self.numberOfPrimeApps)
        # temp = rsnp.rand(self.numberOfPrimeApps)
        # 将数组中的负数替换为其相反数
        temp[temp < 0] = -temp[temp < 0]

        sum = np.sum(temp)
        temp = (CPU_PERIOD*MAX_CPU_UTIL-self.numberOfPrimeApps*MIN_CPU_PERIOD_FOR_DOCKER)*temp/sum

        self.app_node_capacity = pd.DataFrame(temp+MIN_CPU_PERIOD_FOR_DOCKER,
                                              # 设置行名称
                                              index = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)],
                                              columns = ['capacity'])
        # 设置CPN节点总需求 与 app节点总负载能力的比率
        # 50 140 235 350
        self.cpn_app_ratio = 350/520
        
        # 从 JSON 文件读取字典 获取各个primeApp的 rps负载能力(该数据是上一次的测试的数据,
        # 这就意味着当改变相关数据时候就应该测试一次prime_app_rps)
        temp_prime_app_rps: Dict[str, float] = {}
        with open('/home/wwz/ryu/ryu/app/network_awareness/prime_app_rps.json', 'r') as json_file:
            temp_prime_app_rps: Dict[str, float] = json.load(json_file)
        prime_app_rps_value = np.array(list(temp_prime_app_rps.values()))
        sum_prime_app_rps = np.sum(prime_app_rps_value)
        print(sum_prime_app_rps)

        # 随机设置cpn节点的 RPS
        temp = rsnp.normal(0, 10, self.numberOfCPNodes)
        temp[temp < 0] = -temp[temp < 0]
        # temp = rsnp.rand(self.numberOfCPNodes)
        sum_value = np.sum(temp)
        self.cpn_node_rps = self.cpn_app_ratio*sum_prime_app_rps*temp/sum_value
        print(f'cpn_node_rps{self.cpn_node_rps}')
        cpn_node_rps_dict = {f'cpNode{i+1}': self.cpn_node_rps[i] for i in range(self.numberOfCPNodes)}
        # 将字典保存为 JSON 文件
        with open('/home/wwz/ryu/ryu/app/network_awareness/cpn_node_rps.json', 'w') as json_file:
            json.dump(cpn_node_rps_dict, json_file, indent=4)
        # 设置cpn节点 node capacity
        temp_cpn_node =  (CPU_PERIOD*(1-MAX_CPU_UTIL)-MIN_CPU_PERIOD_FOR_DOCKER*self.numberOfCPNodes)*temp/sum_value
        self.cpn_node_capacity = pd.DataFrame(temp_cpn_node+MIN_CPU_PERIOD_FOR_DOCKER,
                                                # 设置行名称
                                                index = [f"cpNode{j+1}" for j in range(self.numberOfCPNodes)],
                                                columns = ['capacity'])
        # temp = np.array([18716, 10353, 15897, 6414, 8371, 5246])
        # self.app_node_capacity = pd.DataFrame(temp,
        #                                       # 设置行名称
        #                                       index = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)],
        #                                       columns = ['capacity'])
        # 测试并设置应用服务节点处理能力
        self.app_request_handle_capacity = pd.DataFrame(rsnp.randint(low=10, high=100, size=self.numberOfPrimeApps),
                                                # 设置行名称
                                                index = [f"primeApp{j+1}" for j in range(self.numberOfPrimeApps)])
        
        # 测试应用的端口号
        self.prime_app_instance_tcp_port = 8000

        self.service_id_dict: Dict[Tuple[str, int], str] = self.init_service_id_dict()

        # 设置应用请求接口的输入数据量和输出数据量 单位 byte
        self.app_api_data_in = 10
        self.app_api_data_out = 33

        

    def init_service_id_dict(self)-> Dict[Tuple[str, int], str]:
        service_id_dict = {}
        # key: service_id(anycast_ip:port), value: 该IP绑定的应用描述
        service_id_dict[('192.168.255.1', self.prime_app_instance_tcp_port)] = 'prime-app'
        return service_id_dict

    # generate two gaussians as the source and target
    def gaussian(mean=0, std=10, n=100):
        d = (-(np.arange(n) - mean)**2 / (2 * std**2)).exp()
        d /= d.sum()
        return d

    def print_setup_params(self):
        print(f"network_link_bw_state: {self.network_link_bw_state}")
        print(f"cpnodes_bw_to_switch: {self.cpnodes_bw_to_switch}")
        print(f"prime_apps_bw_to_switch: {self.prime_apps_bw_to_switch}")
        print(f"network_link_delay_state: {self.network_link_delay_state}")
        print(f'app_node_capacity{self.app_node_capacity}')
        print(f'cpn_node_capacity{self.cpn_node_capacity}')



