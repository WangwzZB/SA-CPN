#!/usr/bin/python3
# topology
"""
            prime app1                 prims app2                     prims app3
                |                           |                               |
layer A     switch A1                  switch A2                      swtich A3
                |      -             -      |     -                   -     |
full connected  |       -          -        |        -              -       |               
                | ------------------------- | ---------------  ------------ |
layer B  cpn access B1                cpn access B2                   cpn access B3
                |                           |                               |
          users group 1               users group 1                   users group 1
"""
from time import sleep
from mininet.net import Containernet
from mininet.node import Controller, RemoteController, OVSSwitch, Docker
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.topo import Topo
from setting import SimNetworkSetUp, global_cpn_routing_algo_choice
import setting
from locust.app_test_all import get_app_rps
import subprocess
import json


def decimal_to_hex_16(decimal_number)
    # 将十进制数转换为十六进制并去掉 '0x' 前缀
    hex_str = hex(decimal_number)[2:]
    
    # 将字符串转为大写（可选）
    hex_str = hex_str.upper()
    
    # 使用 zfill 补0，确保长度为16
    hex_str_16 = hex_str.zfill(16)
    
    return hex_str_16

class MyExprTopo( Topo ):
    "Experiment Topology"

    def build( self ):
        # 网络设置类
        self.sim_net_setting = SimNetworkSetUp()
        # 创建cpn节点容器
        self.cpnodes = []
        for i in range(self.sim_net_setting.numberOfCPNodes):
            self.cpnodes.append(
            #   self.addHost(f"cpNode{i+1}", ip=f"10.0.{i+1}.1/24", cls=Docker, dimage="cpn_node")
                # self.addHost(f"cpNode{i+1}", ip=f"10.0.0.{i+1}/24", cls=Docker, dimage="cpn_node")
                self.addHost(   
                    f"cpNode{i+1}",
                    ip=f"10.0.0.{i+1}/24", 
                    cls=Docker, 
                    dimage="cpn_nodev2:800",
                    # 限制cpu利用率
                    cpu_period=setting.CPU_PERIOD,
                    cpu_quota=int(self.sim_net_setting.cpn_node_capacity.loc[f"cpNode{i+1}","capacity"])
                )
            )

        # 创建质数计算应用服务容器
        self.prime_apps = []
        for j in range(self.sim_net_setting.numberOfPrimeApps):
            self.prime_apps.append(
                self.addHost(
                    f"primeApp{j+1}",
                    ip=f"10.0.0.{self.sim_net_setting.numberOfCPNodes+j+1}/24",
                    # ip=f"20.0.{j+1}.1/24",
                    cls=Docker,
                    #  prime_app demo_server
                    dimage="prime_app:latest",
                    # defaultRoute = "via 10.0.1.254",
                    # 限制cpu利用率
                    cpu_period=setting.CPU_PERIOD,
                    cpu_quota=int(self.sim_net_setting.app_node_capacity.loc[f"primeApp{j+1}","capacity"]),
                    # 配置端口映射
                    ports=[8000],
                    port_bindings={8000: int(f'800{j}')},
                )
            )
        self.switchs_layer_A = []
        self.switchs_layer_B = []
        # 创建layer A层交换机
        for j in range(self.sim_net_setting.numberOfPrimeApps):
            # dpid = str('{:016}'.format(j+1))
            dpid = decimal_to_hex_16(self.sim_net_setting.switchA_dpid_list[j])
            switchA = self.addSwitch(f"switchA{j+1}", dpid=dpid)
            self.switchs_layer_A.append(switchA)
            # 将 apps 连接到 layer A层交换机
            self.addLink(switchA, self.prime_apps[j], bw=self.sim_net_setting.prime_apps_bw_to_switch[j])

        for i in range(self.sim_net_setting.numberOfCPNodes):
            # 创建 layer B层交换机 dpid datapath id
            dpid = decimal_to_hex_16(self.sim_net_setting.switchB_dpid_list[i])
            # dpid = str('{:016}'.format(hex(self.sim_net_setting.switchB_dpid_list[i])[2:]))
            switchB = self.addSwitch(f"switchB{i+1}", dpid=dpid)
            self.switchs_layer_B.append(switchB)
            # 设置 layer B层交换机 与 layer A层交换机间的链路参数
            for j in range(self.sim_net_setting.numberOfPrimeApps):
                self.addLink(self.switchs_layer_A[j], switchB, 
                            bw = self.sim_net_setting.network_link_bw_state.iloc[i, j], 
                            delay = str(self.sim_net_setting.network_link_delay_state.iloc[i, j]) + 'ms', 
                            jitter = str(self.sim_net_setting.network_link_jitter_state.iloc[i, j]) + 'ms', 
                            loss = self.sim_net_setting.network_link_loss_state.iloc[i, j],
                            max_queue_size=1000, 
                            use_htb=True)
            self.addLink(self.cpnodes[i], switchB, bw = self.sim_net_setting.cpnodes_bw_to_switch[i])

        # 打印设置的链路参数
        self.sim_net_setting.print_setup_params()

def run_myexpr_topo():

    # 网络设置类
    sim_net_setting = SimNetworkSetUp()
    # 创建拓扑实例
    topo = MyExprTopo()
    # 创建网络并设置网络控制器与链路类型
    c0 = RemoteController('c0', ip='127.0.0.1', port=6633 )
    net = Containernet(topo=topo,
                       controller=c0, 
                       link=TCLink, 
                       switch=OVSSwitch,
                       autoSetMacs=True,
                       waitConnected=True)
    # 启动仿真网络和命令行
    net.start()

    # Start uwsgi server after container is fully setup.
    for node_name in topo.prime_apps :
        prime_app = net.getNodeByName(node_name)
        prime_app.cmd("uwsgi uwsgi.ini")

    # 为cpNode 节点配置默认路由
    for node_name in topo.cpnodes :
        cpnode = net.getNodeByName(node_name)
        # 安装iperf命令
        # switchB.cmd(f'sudo apt install iperf')
        # 添加默认路由
        # sudo ip route add 192.168.255.1 via  0.0.0.0 dev cpNode1-eth0
        for item in sim_net_setting.service_id_dict.keys():
            # cpnode.cmd(f'sudo ip route add {item[0]} via  0.0.0.0 dev {cpnode.name}-eth0')
             cpnode.cmd(f'ip route add {item[0]} via  0.0.0.0 dev {cpnode.name}-eth0')

    # 交换机禁止生成树协议 设置OpenFlow版本
    for switchA_name in topo.switchs_layer_A:
        switchA = net.getNodeByName(switchA_name)
        switchA.cmd(f'ovs-vsctl set Bridge {switchA.name} protocols=OpenFlow13')
        switchA.cmd(f'ovs-vsctl set bridge {switchA.name} stp_enable=false')
        # 安装iperf命令
        # switchA.cmd(f'sudo apt install iperf')


    for switchB_name in topo.switchs_layer_B:
        switchB =  net.getNodeByName(switchB_name)
        switchB.cmd(f'ovs-vsctl set Bridge {switchB.name} protocols=OpenFlow13')
        switchB.cmd(f'ovs-vsctl set bridge {switchB.name} stp_enable=false')
    # 等待相关设置完成
    sleep(20)
    # 测试应用负载能力
    prime_app_rps = get_app_rps()
    # 设置目标应用能够接受的最大请求到达率
    for key in prime_app_rps.keys():
        prime_app_rps[key] -= 2
    
    print(f"prime_app_rps:{prime_app_rps}")
    # # 将字典保存为 JSON 文件
    with open('/home/wwz/ryu/ryu/app/network_awareness/prime_app_rps.json', 'w') as json_file:
        json.dump(prime_app_rps, json_file, indent=4)
    sleep(25)
    # # 执行 pingall 命令
    print("Executing pingall...")
    net.pingAll()
    # 等待pingall命令完成 时间长了改小
    sleep(10)
    # 设置cpn节点开始发送请求
    start_cpn_node_request(sim_net_setting)
    # cpn等待cpn请求结束
    sleep(10)
    # 存储实验数据
    write_cpnode_stats_to_json(sim_net_setting.numberOfCPNodes)
    CLI(net)
    net.stop()

def start_cpn_node_request(setup: SimNetworkSetUp):
    # 保存进程
    numberOfCPNodes = setup.numberOfCPNodes
    processes = []
    containers_name = [f'cpNode{i+1}' for i in range(numberOfCPNodes)]
    # 启动每个容器中的 Locust 测试
    for i in range(numberOfCPNodes):
        container = containers_name[i]
        try:
            locust_command = f'locust -f locust_cpn_test.py --host http://192.168.255.1:8000 \
                   --users {setting.RATIO_INCREMENT_OF_USERS*round(setup.cpn_node_rps[i])} \
                   --spawn-rate {max(setting.RATIO_INCREMENT_OF_USERS*round(setup.cpn_node_rps[i])/2, 1)} \
                   --run-time  {setting.CPN_NODE_REQUEST_DURATION_TIME} --headless --csv output/{container}  --skip-log'
            # 构建 Docker exec 命令
            command = f"docker exec mn.{container} {locust_command}"
            print(f"Starting Locust in container {container}...")
            
            # 启动容器中的 Locust 测试进程
            process = subprocess.Popen(command, shell=True)
            processes.append(process)
        except subprocess.CalledProcessError as e:
            print(f"Failed to start Locust in container {container} with error: {e}")

    # 等待所有进程结束
    for process in processes:
        process.wait()

    print("All Locust tests completed.")

def write_cpnode_stats_to_json(numberOfCPNodes):
    for i in range(numberOfCPNodes):
        copy_file_from_container(container_name=f"mn.cpNode{i+1}",src_path=f'/locust/output/cpNode{i+1}_stats.csv', 
                                    dest_path=f'results/expr_output/{global_cpn_routing_algo_choice.value}/')
        copy_file_from_container(container_name=f"mn.cpNode{i+1}",src_path='/locust/logfile.log',
                                    dest_path=f'results/expr_output/{global_cpn_routing_algo_choice.value}/cpNode{i+1}_logfile.log')


def copy_file_from_container(container_name, src_path, dest_path):
    try:
        # 构建 docker cp 命令
        command = f"docker cp {container_name}:{src_path} {dest_path}"

        # 使用 subprocess 运行命令
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        print(f"File {src_path} from container {container_name} has been copied to {dest_path}")
    
    except subprocess.CalledProcessError as e:
        print(f"Error occurred: {e.stderr.decode()}")


if __name__ == '__main__':
    run_myexpr_topo()


# Allows the file to be imported using `mn --custom <filename> --topo minimal`
topos = {
    'myexpr-topo': MyExprTopo
}

# sudo mn --custom topo.py --topo minimal