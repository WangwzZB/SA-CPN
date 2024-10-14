# 0.项目参考链接
[SDN-网络感知应用](https://github.com/muzixing/ryu/blob/master/ryu/app/network_awareness/README.md)
[Mininet官网](https://mininet.org/download/)、[Mininet应用与源码刨析](https://yeasy.gitbook.io/mininet_book/runtime_and_example/example)、[Mininet中文文档](https://github.com/K9A2/Mininet-Document-In-Chinese?tab=readme-ov-file)、[Mininet Github文档](https://github.com/mininet/mininet/wiki/Introduction-to-Mininet)、[Mininet Python API 参考文档](https://mininet.org/api/classmininet_1_1node_1_1Node.html)、[Mininet Python第三方库中文博客介绍](https://oublie6.github.io/posts/python/%E7%AC%AC%E4%B8%89%E6%96%B9%E5%BA%93/mininet/mininet%E7%AE%80%E4%BB%8B/)、[Mininet命令详解](https://developer.baidu.com/article/details/3293139)、[containernet github仓库地址](https://github.com/containernet/containernet/tree/master)、[containernet Web页面](https://containernet.github.io/)、 [Mininet搭建多控制器拓扑](https://www.sdnlab.com/12975.html)
> 注意Ubuntu20.04版本才可以安装Mininet2.3 也只有大于2.3版本对Python的支持比较全面
# 1. 实验环境介绍
## 1.1 Containernet 介绍
Containernet 是著名的 Mininet 网络模拟器的分支，允许在模拟的网络拓扑中使用 Docker 容器作为主机。这使得有趣的功能可以构建网络/云模拟器和测试平台。集装箱网络被研究界广泛使用，主要集中在云计算、雾计算、网络功能虚拟化(NFV)和多访问边缘计算(MEC)等领域。这方面的一个例子是由 SONATA-NFV 项目创建的 NFV 多 PoP 基础设施模拟器，它现在是 OpenSource MANO (OSM)项目的一部分。
安装方式：https://containernet.github.io/#installation
## 1.2 Ryu 介绍
Ryu是日本NTT公司推出的SDN控制器框架，它基于Python开发，模块清晰，可扩展性好，逐步取代了早期的NOX和POX。
- Ryu支持OpenFlow 1.0到1.5版本，也支持Netconf，OF-CONIFG等其他南向协议
- Ryu可以作为OpenStack的插件，见Dragonflow
- Ryu提供了丰富的组件，便于开发者构建SDN应用
Ryu 安装方式： $pip install ryu$

# 2. 系统实现介绍
## 2.1 代码目录介绍
├─docker: 存放相关容器镜像的Dockerfile文件 <br>
├─locust: 存放压力测试的相关文件 <br>
├─results <br>
│  └─expr_output: 不同算法实验数据输出 <br>
│      ├─balance_algo 简单均衡算法<br>
│      ├─cfn_algo cfn-dyn算法<br>
│      ├─link_algo 最短路径时延算法<br>
│      ├─ot_algo 最优传输算法<br>
│      └─qps_weighted_algo qps加权均衡算法<br>
├─containernet_expr.py: 构建containernet实验环境，启动实验 <br>
├─cpn_debug.py: 启动此文件用于对RYU控制器代码进行Debug   <br>
├─cpn_node_rps.json: 实验所设置的用户请求达到率输出 <br>
├─cpn_routing_algo.py: 实现CPN多种算法 <br>
├─cpn_routing_app.py: 在RYU控制器上实现的CPN主要服务任播转发相关协议和数据包处理代码 <br>
├─network_awareness.py: 用于进行网络拓扑感知 <br>
├─network_delay_detector.py: 基于LLDP协议实现的网络链路时延感知 <br>
├─network_monitor.py: 用于计算可用链路带宽和流量统计信息 <br>
├─shortest_forwarding.py: 解决ARP网络风暴问题，实现网络最短路径转发 <br>
├─setting.py: 用于系统实验全局设置 <br>

## 2.2 关键代码简介绍
## 2.2.1 containernet_expr
本脚本基于Containernet的网络仿真拓扑，主要用于模拟和测试网络中的多层拓扑结构、容器化节点和应用服务的性能。
### （1） 拓扑结构说明
代码模拟了一个两层的交换机拓扑，顶层连接应用容器（prime apps），底层连接模拟用户节点，用户节点通过CPN Access 交换机（OVS）与应用节点进行通信。具体的结构如下：
Layer A：上层交换机（Switch A），连接应用容器（prime apps）。
Layer B：下层交换机（Switch B, 即cpn access router节点），连接模拟用户节点。
交换机之间的链路是全连接的，支持延迟、带宽、抖动和丢包率的配置。 
### (2) 代码模块的主要功能
- SimNetworkSetUp  <br>
SimNetworkSetUp 类负责管理整个网络仿真的设置，例如节点的数量、各个节点的计算能力、链路参数（带宽、延迟等）。这些配置在代码中通过不同的变量读取和设置。
setting 模块包含一些全局变量的配置，如 CPU_PERIOD（用于限制容器CPU资源）、CPN_NODE_REQUEST_DURATION_TIME（请求持续时间）等。
- MyExprTopo  <br>
MyExprTopo 是Mininet/Containernet的拓扑定义类，继承自 Topo。它负责构建实验拓扑：
创建 cpnodes：使用Docker容器作为CPN 用户节点，指定了IP地址、镜像版本、CPU配额等。
创建 prime_apps：创建Prime计算应用服务容器，同样使用Docker，并通过映射端口支持外部访问。
创建 switchs_layer_A 和 switchs_layer_B：两层交换机，分别连接应用容器和CPN节点。交换机的DPID（数据路径ID）通过 decimal_to_hex_16 函数从十进制转换为十六进制，并确保DPID为16位。
设置交换机之间的链路：使用 addLink 函数连接Layer A和Layer B的交换机，并为每条链路设置带宽、延迟、抖动和丢包率等网络条件。
print_setup_params：打印网络链路的设置信息，便于调试。
- run_myexpr_topo 函数 <br>
该函数是仿真网络的主逻辑：
初始化 Containernet 网络实例，指定使用 RemoteController 作为控制器，连接交换机、设置链路。
启动应用容器中的uwsgi服务（Web服务器），使Prime应用服务能够响应请求。
为CPN节点配置默认路由。
禁用交换机的生成树协议（STP），并设置OpenFlow协议版本为OpenFlow 13。
启动网络后，执行负载测试（get_app_rps），并生成测试数据，存储在JSON文件中。
执行网络测试命令（pingAll）来验证节点之间的连通性。
通过 start_cpn_node_request 函数，启动CPN节点发送请求，仿真访问Prime应用的负载。
- start_cpn_node_request 函数  <br>
该函数为每个CPN 用户节点启动一个容器化的 Locust 测试工具。Locust 是一个负载测试工具，用于模拟大量用户对应用的请求。
通过Docker命令在每个CPN容器中运行Locust，并根据配置的请求到达率（RATIO_INCREMENT_OF_USERS）生成请求，模拟用户访问应用服务的场景。
- write_cpnode_stats_to_json 函数 <br>
在实验结束后，将每个CPN节点的测试结果（例如请求统计、日志）从容器中复制到本地，并保存在指定的文件夹中。结果包括每个CPN节点的负载统计和日志文件。
- 其他辅助功能 <br>
decimal_to_hex_16：用于将十进制数转换为16位的十六进制数，确保交换机DPID的格式正确。
copy_file_from_container：从Docker容器中复制文件到本地，便于保存实验结果。
CLI：启动Mininet命令行接口，可以在网络仿真中执行各种命令，查看网络状态或手动调试。
- **实验的整体流程**  <br>
定义网络拓扑（创建节点、交换机、链路等）。
启动仿真网络，应用节点运行服务，CPN节点配置路由。
通过负载测试工具Locust模拟CPN节点向应用节点发起请求。
测试完成后，保存实验结果，并通过Mininet命令行接口（CLI）进行进一步的手动测试或调试。
停止网络仿真并清理资源。
## 2.2.2 cpn_routing_app:
本应用实现了一个基于RYU控制器的CPN（Compute Power Network）服务任播转发应用。CPN路由的核心目标是通过任播（Anycast）方式来转发流量，特别是当多个应用实例可用时，按照转发队列选择某个实例来处理用户请求。具体来说，包含以下几个关键功能：
### (1) CPN服务转发条目类（CPNServiceForwardingEntry）
该类定义了每个CPN服务转发条目的结构和行为。
service_id：服务的唯一标识（由任播IP和端口组成）。
service_instance_list：每个服务实例的IP和端口，作为用户请求的目标。
forwarding_policy：概率转发策略，用于确定请求被转发到哪个实例。
newest_service_instance_id：当前选择的服务实例IP和端口。
forwading_queue：根据转发策略生成的队列，保证在多个实例间按策略分发流量。
update_newest_service_instance_id：更新服务实例ID，使用全局转发策略确定新目标。
rouding_forwarding_policy：根据转发策略生成整数化的转发队列，确保概率转发是离散化的、符合要求。 
### (2) CPN路由转发应用类（CPNRouting）
该类继承自 app_manager.RyuApp，用于实现CPN 服务任播转发的逻辑，处理ARP请求和TCP/UDP流量，按策略转发流量。
- 初始化  <br>
__init__：初始化多个服务和转发策略，使用 NetworkAwareness 和 ShortestForwarding 模块来获取网络拓扑和最短路径信息。
cpn_all_forwarding_table：存储每个交换机的服务转发表，字典的键是交换机ID，值是服务ID到转发条目的映射。
service_id_dict：记录服务ID（任播IP:端口）和对应的应用服务实例列表。
switch_maintained_cpn_service：记录每个交换机维护的CPN服务列表，确保每个交换机可以定期更新CPN路由策略。
cpn_routing_algo：CPN路由算法，用于更新全局的转发策略。
_init_testing_setting：初始化服务转发表，将每个服务的多个实例配置在不同交换机上。
_cpn_switch_policy_update：定期更新转发策略，确保网络中的流表能够及时反映新的服务实例和转发策略。
- ARP请求处理  <br>
在 PacketIn 事件中，如果接收到的是ARP请求并且目标IP是CPN的任播IP（Anycast IP），控制器会生成ARP回复。
生成的ARP回复包含自定义的MAC地址，也用来标识该服务请求。
- TCP/UDP流量处理  <br>
当接收到TCP或UDP数据包时，控制器会判断目标IP是否是CPN的任播IP，如果是：
记录服务实例：在交换机维护的CPN服务列表中添加该服务。
匹配转发表：如果交换机的服务转发表没有过期，直接使用转发表进行流量转发。
更新服务实例：根据概率转发策略，选取一个服务实例，将数据包转发给该实例。
修改流表：生成两个流表规则：
第一条：将目标IP改写为选定的服务实例的IP，并转发给该实例。
第二条：当服务实例返回数据包时，源地址改写为任播IP，返回给原请求方。
- 周期性路由更新  <br>
控制器通过 _cpn_switch_policy_update 线程定期更新每个交换机上的服务转发表，保证流量能够按照最新的策略转发到不同的服务实例。
### (3) 流表管理
add_flow 方法用于下发OpenFlow流表，支持自定义优先级、超时时间、流表动作等。
当控制器检测到交换机的流表超时或被删除时，会通过 flow_removed_handler 方法处理相应事件，确保控制器的状态与交换机同步。
### (4) 整体工作流程
ARP请求处理：当用户设备发起ARP请求获取CPN服务的任播IP时，控制器生成自定义MAC地址的ARP回复。
TCP/UDP请求处理：当用户设备发起TCP/UDP请求时，控制器根据策略选择一个服务实例，将数据包转发到该实例，并更新流表。
周期性更新：控制器通过后台线程定期更新路由策略，调整每个交换机的流量转发行为，确保服务实例的负载均衡。

# 3.环境启动步骤
## 3.0 环境准备：
- 安装好Docker、Containernet、RYU应用
- 执行docker/build.sh 脚本生成实验所需容器镜像
- 将本代码放置到 ryu/ryu/app目录下
- 查看 setting.py 进行自定义配置
## 3.1 启动ryu cpn 应用
```bash
cd ~/ryu/ryu/app/SA-CPN
sudo ryu-manager cpn_routing_app.py --observe-links --k-paths=1  --weight=hop
```
## 3.2 启动 容器网络环境
```bash
cd ~/ryu/ryu/app/SA-CPN
sudo python3 containernet_expr.py
```
## 3.3 其他常用命令
```bash
# 查看交换机流表
sudo ovs-ofctl dump-flows -O OpenFlow13 switchA1
# 查看容器资源统计情况
docker stats
# 进入docker目录更新容器
docker build -f Dockerfile.cpn.nodev2 -t cpn_nodev2:latest .
# 本地容器镜像库查询
docker images
# 清除 containernet docker残留
sudo mn --clean
```

## 3.4 常用配置修改流程
### 3.4.1 修改 PRIME_NUM
修改 PRIME_NUM 改变 质数计算容器接口返回响应的时间
- 1. setting 文件中修改PRIME_NUM
- 2. docker/locust_cpn_test.py 修改PRIME_NUM 并重新生成镜像 docker build -f Dockerfile.cpn.nodev2 -t cpn_nodev2:PRIME_NUM .
- 3. 考虑是否修改locust/locust_app_test.py 测试参数
- 4. 修改 containernet_expr prime_app节点镜像： cpn_nodev2:PRIME_NUM
### 3.4.2 测试不同算法流程：
- 1. setting 文件中修改全局变量global_cpn_routing_algo_choice 确定算法类型选择
- 2. 初次测试需要把containernet_expr.py 第168行 `prime_app_rps = get_app_rps()`取消注释 第169行注释，因为测试rps比较耗费时间，测一次就够了， 其余相同配置的实验从prime_app_rps.json复制测试数据到169行即可
- 3. 执行cpn_routing.py containernet_expr.py文件
- 4. 实验结束后可执行results/draw_picture_test.py 绘制简易实验图像，输出图像名为 comparison_algorithms1.png comparison_algorithms2.png， ART平均时间、MRT响应时间中位数。


