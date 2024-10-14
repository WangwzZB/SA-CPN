import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from setting import SimNetworkSetUp, CPNRoutingAlgoName
import setting
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict
import json

"""
画实验结束图
"""

# 1. 绘制第一张图：Requests/s 和 Failures/s 对比
def draw_picture1(stats):
    algorithms = list(stats.keys())
    requests = [stats[algo]['Requests/s'] for algo in algorithms]
    failures = [stats[algo]['Failures/s'] for algo in algorithms]

    # 创建图表
    x = range(len(algorithms))
    
    fig, ax1 = plt.subplots()

    # 绘制 Requests/s
    bars = ax1.bar(x, requests, width=0.4, label='Requests/s', color='blue', align='center')
    ax1.set_xlabel('Algorithm')
    ax1.set_ylabel('Requests/s', color='blue')
    ax1.set_xticks(x)
    ax1.set_xticklabels(algorithms)

    # 在柱状图上添加数值标记
    for bar in bars:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2, height, f'{height:.2f}', ha='center', va='bottom', color='blue')

    # 创建另一个Y轴，用于 Failures/s
    ax2 = ax1.twinx()
    lines = ax2.plot(x, failures, color='red', marker='o', label='Failures/s')
    ax2.set_ylabel('Failures/s', color='red')

    # 在折线图上添加数值标记
    for i, v in enumerate(failures):
        ax2.text(x[i], v, f'{v:.2f}', ha='center', va='bottom', color='red')

    plt.title('Algorithm Comparison: Requests/s and Failures/s')
    plt.savefig('/home/wwz/ryu/ryu/app/network_awareness/results/expr_output/comparison_algorithms1.png', dpi=300, bbox_inches='tight')
    plt.show()

# 2. 绘制第二张图：统计数据对比 (Average, Median, Min, Max, P95, P99)
def draw_picture2(stats):
    algorithms = list(stats.keys())
    metrics = stats[algorithms[0]].keys()
    metrics_pic = ['ART', 'MRT', 'Min', 'Max', 'P95', 'P99'] 
    
    # 创建图表
    x = range(len(metrics))
    
    fig, ax = plt.subplots()

    # 遍历每个算法的统计数据，并绘制折线图
    for algo in algorithms:
        values = [stats[algo][metric] for metric in metrics]
        ax.plot(x, values, label=algo, marker='o')
        # 在折线图上为每个点添加数值标记
        for i, v in enumerate(values):
            ax.text(x[i], v, f'{v:.2f}', ha='center', va='bottom')
    ax.set_xlabel('Metrics')
    ax.set_ylabel('Values')
    ax.set_xticks(x)
    ax.set_xticklabels(metrics_pic)
    ax.legend()
    plt.savefig('/home/wwz/ryu/ryu/app/network_awareness/results/expr_output/comparison_algorithms2.png', dpi=300, bbox_inches='tight')
    plt.title('Algorithm Comparison: Detailed Statistics')
    plt.show()

if __name__ == '__main__':
    # 显示数值标签
    setup = SimNetworkSetUp()
    numberOfCPNodes = setup.numberOfCPNodes
    # 需要绘制的算法名称目录
    algo_drawed = [
                    CPNRoutingAlgoName.SIMPLE_POLICY_BALANCE_ALGO.value, 
                   CPNRoutingAlgoName.OT_POLICY_ALGO.value, 
                   CPNRoutingAlgoName.SHORTEST_LINK_DELAY_ALGO.value, 
                   CPNRoutingAlgoName.CFN_DYNAMIC_FEEDBACK_ALGO.value,
                   CPNRoutingAlgoName.QPS_WEIGHTED_POLICY_ALGO.value
                   ]

    # 初始化实验统计数据
    picture1_stats: Dict[str, Dict[str, float]] = {}
    picture2_stats: Dict[str, Dict[str, float]]  = {}

    for name in algo_drawed:
        picture1_stats[name] = {'Requests/s':0, 'Failures/s':0}
        picture2_stats[name] = {'Average Response Time':0, 'Median Response Time':0, 'Min Response Time':0, 'Max Response Time':0, '95%':0, '99%':0}
        

    
    # 遍历目标算法
    for algo in algo_drawed:
        sum_request_count = 0
        total_time = 0
        # 首先遍历节点
        for i in range(numberOfCPNodes):
            # 读取目标算法统计文件
            node_stats = pd.read_csv(f'/home/wwz/ryu/ryu/app/network_awareness/results/expr_output/{algo}/cpNode{i+1}_stats.csv')
            try:
                temp = node_stats.loc[1, 'Request Count']
            except:
                continue
            sum_request_count += temp
            total_time += node_stats.loc[1, 'Request Count']*node_stats.loc[1, 'Average Response Time']
            # 记录汇总数据
            for item in picture1_stats[algo].keys():
                picture1_stats[algo][item] += node_stats.loc[1, item]

            # for item in picture2_stats[algo].keys():
            picture2_stats[algo]['Median Response Time'] += node_stats.loc[1, 'Median Response Time']
            picture2_stats[algo]['Min Response Time'] += node_stats.loc[1, 'Min Response Time']
            picture2_stats[algo]['Max Response Time'] += node_stats.loc[1, 'Max Response Time']
            picture2_stats[algo]['95%'] += node_stats.loc[1, '95%']
            picture2_stats[algo]['99%'] += node_stats.loc[1, '99%']
        
        picture2_stats[algo]['Average Response Time'] = total_time/sum_request_count

    for algo in algo_drawed:
        picture1_stats[algo]['Failures/s'] = picture1_stats[algo]['Failures/s']/numberOfCPNodes

    # 对picture2_stats 取均值
    # 遍历目标算法
    for algo in algo_drawed:
        for item in picture2_stats[algo].keys():
            picture2_stats[algo][item] = picture2_stats[algo][item]/numberOfCPNodes
        picture2_stats[algo]['Average Response Time'] = picture2_stats[algo]['Average Response Time'] * numberOfCPNodes

    print(f"picture1_stats{picture1_stats}")
    print(f"picture2_stats{picture2_stats}")
    # 调用绘图函数
    draw_picture1(picture1_stats)
    draw_picture2(picture2_stats)

