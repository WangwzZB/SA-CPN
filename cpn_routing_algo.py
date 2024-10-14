#!/usr/bin/env python
# -*- coding: utf-8 -*-
from typing import List, Tuple, Dict, Set
import numpy as np
import setting
from setting import SimNetworkSetUp, CPNRoutingAlgoName
import json
import torch
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import gridspec
import subprocess
# from vlkit.optimal_transport import sinkhorn

"""
保存各种cpn转发策略计算算法
"""
class CPNRoutingAlgo:
    """
    cpn 路由算法类
    setup: 全局设置类
    routing_algo_name: 路由算法名称
    """
    def __init__(self, setup: SimNetworkSetUp, routing_algo_name: CPNRoutingAlgoName = CPNRoutingAlgoName.SIMPLE_POLICY_BALANCE_ALGO):
        # 路由转发策略： 入口节点数量 * 应用数量 二维数组, 数组值为转发概率值
        self.global_forwarding_policy: np.array = None
        self.setup: SimNetworkSetUp = setup
        self.routing_algo_name = routing_algo_name
        # 保存ot 算法参数
        self.prime_app_rps = None
        self.cpn_node_rps = None
        self._init_forwarding_policy()

    def _init_forwarding_policy(self):
        # 统一采用均衡算法进行初始化
        self.simple_policy_balance_algo(update=True)

    def update_forwarding_policy(self):
        forwarding_policy: np.array = None
        # 判断路由策略类型
        if self.routing_algo_name == CPNRoutingAlgoName.SIMPLE_POLICY_BALANCE_ALGO:
            forwarding_policy = self.simple_policy_balance_algo(update=True)
        elif self.routing_algo_name == CPNRoutingAlgoName.OT_POLICY_ALGO:
            forwarding_policy = self.ot_policy_algo(update=True)
        elif self.routing_algo_name == CPNRoutingAlgoName.CFN_DYNAMIC_FEEDBACK_ALGO:
            forwarding_policy = self.cfn_dynamic_feedback_algo(update=True)
        elif self.routing_algo_name == CPNRoutingAlgoName.SHORTEST_LINK_DELAY_ALGO:
            forwarding_policy = self.shortest_link_algo(update=True)
        elif self.routing_algo_name == CPNRoutingAlgoName.QPS_WEIGHTED_POLICY_ALGO:
            forwarding_policy = self.qps_weighted_policy_algo(update=True)
        # print(f'updated forwarding_policy: {forwarding_policy}')
        return forwarding_policy

    def simple_policy_balance_algo(self, update=False)-> np.array:
        """
        update: 本次策略计算是否更新策略值, 如果不更新则会使用旧的路由策略global_forwarding_policy
        """
        if update:
            n_access_node = self.setup.numberOfCPNodes
            n_app_node = self.setup.numberOfPrimeApps
            forwarding_policy = np.zeros(shape=(n_access_node,n_app_node), dtype= float)
            each_access_node_policy = np.ones(shape=n_app_node, dtype = float)/n_app_node
            for i in range(n_access_node):
                forwarding_policy[i] = each_access_node_policy
            self.global_forwarding_policy = forwarding_policy
            return forwarding_policy
        else:
            return self.global_forwarding_policy
    
    def qps_weighted_policy_algo(self, update=False)-> np.array:
        if update:
            prime_app_rps = None
            # 从 JSON 文件读取字典 获取各个primeApp的 rps负载能力
            with open('/home/wwz/ryu/ryu/app/network_awareness/prime_app_rps.json', 'r') as json_file:
                prime_app_rps: Dict[str, float] = json.load(json_file)
            prime_app_rps_value = np.array(list(prime_app_rps.values()))
            line_policy = prime_app_rps_value / np.sum(prime_app_rps_value)
            forwarding_policy = np.vstack([line_policy] * self.setup.numberOfCPNodes)
            self.global_forwarding_policy = forwarding_policy
            return forwarding_policy
        else:
            return self.global_forwarding_policy

    def ot_policy_algo(self, update):
        """
        最优传输算法
        """
        if update:
            forwarding_policy = np.zeros(shape=(self.setup.numberOfCPNodes, self.setup.numberOfPrimeApps), dtype= float)
            prime_app_rps = None
            cpn_node_rps = None
            # 从 JSON 文件读取字典 获取各个primeApp的 rps负载能力
            with open('/home/wwz/ryu/ryu/app/network_awareness/prime_app_rps.json', 'r') as json_file:
                prime_app_rps: Dict[str, float] = json.load(json_file)
            
            # 用户请求到达各个cpNode 的到达率
            # 从 JSON 文件读取字典 获取各个primeApp的 rps负载能力
            with open('/home/wwz/ryu/ryu/app/network_awareness/cpn_node_rps.json', 'r') as json_file:
                cpn_node_rps: Dict[str, float] = json.load(json_file)

            # 如果处理能力和请求到达率 数据和网络设置数据不符合证明这是旧的数据，
            if len(prime_app_rps) != self.setup.numberOfPrimeApps or len(cpn_node_rps) != self.setup.numberOfCPNodes :
                return self.global_forwarding_policy
            # 如果处理能力和请求到达率没有改变则不更新策略
            if prime_app_rps == self.prime_app_rps and cpn_node_rps==self.cpn_node_rps:
                return self.global_forwarding_policy
            self.prime_app_rps = prime_app_rps
            self.cpn_node_rps = cpn_node_rps
            prime_app_rps_value = np.array(list(prime_app_rps.values()))
            cpn_node_rps_value = np.array(list(cpn_node_rps.values()))

            # 判断请求达到量 与 整网应用处理能力的关系
            # 请求达到量 < 整网应用处理能力
            if np.sum(cpn_node_rps_value) < np.sum(prime_app_rps_value):
                # 创建虚拟cpn
                virtual_cpn_rps = np.sum(prime_app_rps_value) -  np.sum(cpn_node_rps_value)
                cpn_node_rps_value = np.append(cpn_node_rps_value, virtual_cpn_rps)

                # 归一化处理能力向量
                prime_app_rps_value = prime_app_rps_value/sum(prime_app_rps_value)
                # 归一化请求达到率向量
                cpn_node_rps_value = cpn_node_rps_value/sum(cpn_node_rps_value)

                # 计算代价矩阵
                network_link_bw_array = self.setup.network_link_bw_state.to_numpy()
                network_link_delay_array = self.setup.network_link_delay_state.to_numpy()
                network_cost_array = (self.setup.app_api_data_in+self.setup.app_api_data_out)/network_link_bw_array + network_link_delay_array
                # 为虚拟cpn添加代价行
                new_row = np.zeros(shape=self.setup.numberOfPrimeApps,dtype=float)
                network_cost_array = np.vstack([network_cost_array, new_row])
                # 代价矩阵归一化
                network_cost_array =  network_cost_array / np.max(network_cost_array)
                # unsqueeze  升维度
                T, u, v = self.sinkhorn(r=torch.from_numpy(cpn_node_rps_value).unsqueeze(dim=0), c=torch.from_numpy(prime_app_rps_value).unsqueeze(dim=0), 
                                        reg=1e-2, M=torch.from_numpy(network_cost_array).unsqueeze(dim=0),num_iters=100)
                result = T.squeeze(dim=0).numpy()
                line_sum = np.sum(result, axis=1)
                # 策略整理
                forwarding_policy = result / line_sum[:, np.newaxis]
                # 去除虚拟cpn的策略 即去除最后一行
                forwarding_policy = forwarding_policy[:-1, :]

            elif np.sum(cpn_node_rps_value) >= np.sum(prime_app_rps_value):
                # 调整分布式部署的应用的处理能力向量
                prime_app_rps_value = (np.sum(cpn_node_rps_value)/np.sum(prime_app_rps_value)) * prime_app_rps_value
                # 归一化处理能力向量
                prime_app_rps_value = prime_app_rps_value/sum(prime_app_rps_value)
                # 归一化请求达到率向量
                cpn_node_rps_value = cpn_node_rps_value/sum(cpn_node_rps_value)
                # 计算代价矩阵
                network_link_bw_array = self.setup.network_link_bw_state.to_numpy()
                network_link_delay_array = self.setup.network_link_delay_state.to_numpy()
                network_cost_array = (self.setup.app_api_data_in+self.setup.app_api_data_out)/network_link_bw_array + network_link_delay_array
                # 代价矩阵归一化
                network_cost_array =  network_cost_array / np.max(network_cost_array)
                T, u, v = self.sinkhorn(r=torch.from_numpy(cpn_node_rps_value).unsqueeze(dim=0), c=torch.from_numpy(prime_app_rps_value).unsqueeze(dim=0), 
                                        reg=1e-2, M=torch.from_numpy(network_cost_array).unsqueeze(dim=0))
                result = T.squeeze(dim=0).numpy()
                line_sum = np.sum(result, axis=1)
                forwarding_policy = result / line_sum[:, np.newaxis]
            self.global_forwarding_policy = forwarding_policy
            print(f"forwarding_policy shape: {forwarding_policy.shape}")
            return forwarding_policy
        else:
            return self.global_forwarding_policy

    def cfn_dynamic_feedback_algo(self, update) -> np.array:
        n_access_node = self.setup.numberOfCPNodes
        n_app_node = self.setup.numberOfPrimeApps
        forwarding_policy = np.zeros(shape=(n_access_node, n_app_node), dtype=float)
        cpu = self.get_cpu_rate()
        cpu = cpu + np.random.rand(n_app_node)
        forwarding_policy[:, np.argmin(cpu)] = 1
        return forwarding_policy

    def shortest_link_algo(self, update):
        """
        按照最短链路时延生成的转发策略
        """
        if update:
            # 获取网络链路时延数组
            temp = self.setup.network_link_delay_state.to_numpy()
            # print(f"network_link_delay_state: {temp}")
            # 复制数组以进行操作
            forwarding_policy = np.zeros_like(temp)
            # 找到每行的最小值的位置
            min_indices = np.argmin(temp, axis=1)
            forwarding_policy[np.arange(temp.shape[0]), min_indices] = 1
            self.global_forwarding_policy = forwarding_policy 
            return forwarding_policy
        else:
            return self.global_forwarding_policy
        
    @staticmethod
    def sinkhorn(r, c, M, reg=1e-3, error_thres=1e-8, num_iters=200):
        # error_thres=1e-5 num_iters=100
        """Batch sinkhorn iteration. See a blog post <https://kaizhao.net/blog/optimal-transport> (in Chinese) for explainations.
        """
        n, d1, d2 = M.shape
        assert r.shape[0] == c.shape[0] == n and \
            r.shape[1] == d1 and c.shape[1] == d2, \
            'r.shape=%s, v=shape=%s, M.shape=%s' % (r.shape, c.shape, M.shape)

        K = (-M / reg).exp()        # (n, d1, d2)
        u = torch.ones_like(r) / d1 # (n, d1)
        v = torch.ones_like(c) / d2 # (n, d2)

        for _ in range(num_iters):
            r0 = u
            # u = r / K \cdot v
            u = r / torch.einsum('ijk,ik->ij', [K, v])
            # v = c / K^T \cdot u
            v = c / torch.einsum('ikj,ik->ij', [K, u])

            err = (u - r0).abs().mean()
            if err.item() < error_thres:
                break
        T = torch.einsum('ij,ik->ijk', [u, v]) * K
        return T, u, v

    @staticmethod
    def get_cpu_rate()-> np.array:
        cpu_stats = []
        # 使用subprocess运行docker stats命令，获取所有容器的CPU使用情况
        cmd = 'docker stats --no-stream --format "{{.Name}}: {{.CPUPerc}}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        # 分割输出按行解析
        stats_output = result.stdout.strip().split('\n')

        # 将每个容器的名称和CPU使用率存储在字典中
        cpu_usage_dict = {}
        for line in stats_output:
            if line:
                # 分割名称和CPU使用率
                name, cpu_usage = line.split(': ')
                if "mn.primeApp" in name:
                    cpu_usage_dict[name] = cpu_usage
        for i in range(len(cpu_usage_dict)):
            name = f"mn.primeApp{i + 1}"
            cpu_stats.append(float(cpu_usage_dict[name].replace("%", "")))
        return cpu_stats
    