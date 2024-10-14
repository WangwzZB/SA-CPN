# 0. Project Reference Links
[SDN-Network Awareness Application](https://github.com/muzixing/ryu/blob/master/ryu/app/network_awareness/README.md)  
[Mininet Official Website](https://mininet.org/download/), [Mininet Applications and Source Code Analysis](https://yeasy.gitbook.io/mininet_book/runtime_and_example/example), [Mininet Chinese Documentation](https://github.com/K9A2/Mininet-Document-In-Chinese?tab=readme-ov-file), [Mininet Github Documentation](https://github.com/mininet/mininet/wiki/Introduction-to-Mininet), [Mininet Python API Reference](https://mininet.org/api/classmininet_1_1node_1_1Node.html), [Mininet Python Third-Party Library Chinese Blog Introduction](https://oublie6.github.io/posts/python/%E7%AC%AC%E4%B8%89%E6%96%B9%E5%BA%93/mininet/mininet%E7%AE%80%E4%BB%8B/), [Mininet Command Explanation](https://developer.baidu.com/article/details/3293139), [Containernet GitHub Repository](https://github.com/containernet/containernet/tree/master), [Containernet Web Page](https://containernet.github.io/), [Building a Multi-Controller Topology with Mininet](https://www.sdnlab.com/12975.html)  
> Note: Only Ubuntu 20.04 supports Mininet 2.3, and versions above 2.3 provide comprehensive support for Python.

# 1. Experiment Environment Introduction
## 1.1 Containernet Introduction
Containernet is a fork of the popular Mininet network emulator, which allows the use of Docker containers as hosts in simulated network topologies. This enables interesting features for building network/cloud emulators and test platforms. Containernet is widely used in research fields, particularly in cloud computing, fog computing, network function virtualization (NFV), and multi-access edge computing (MEC). An example of this is the NFV multi-PoP infrastructure emulator created by the SONATA-NFV project, which is now part of the OpenSource MANO (OSM) project.  
Installation: [Containernet Installation Guide](https://containernet.github.io/#installation)

## 1.2 Ryu Introduction
Ryu is an SDN controller framework developed by NTT in Japan, written in Python. It is modular, well-structured, and highly extensible, gradually replacing earlier frameworks like NOX and POX.
- Ryu supports OpenFlow versions from 1.0 to 1.5, as well as other southbound protocols like Netconf and OF-CONFIG.
- Ryu can be used as a plugin for OpenStack (e.g., Dragonflow).
- Ryu provides rich components for developers to build SDN applications easily.  
Ryu installation: `$pip install ryu`

# 2. System Implementation Introduction
## 2.1 Code Directory Introduction
├─docker: Contains Dockerfiles for related container images
├─locust: Contains files for load testing
├─results
│ └─expr_output: Output data of experiments with different algorithms
│ ├─balance_algo: Simple balancing algorithm
│ ├─cfn_algo: CFN-Dyn algorithm
│ ├─link_algo: Shortest path delay algorithm
│ ├─ot_algo: Optimal transmission algorithm
│ └─qps_weighted_algo: QPS weighted balancing algorithm
├─containernet_expr.py: Builds the Containernet experiment environment and starts the experiment
├─cpn_debug.py: Used for debugging RYU controller code
├─cpn_node_rps.json: Output of user request rate settings for the experiment
├─cpn_routing_algo.py: Implements various CPN algorithms
├─cpn_routing_app.py: Implements the main CPN anycast forwarding and packet handling protocol on the RYU controller
├─network_awareness.py: Responsible for network topology awareness
├─network_delay_detector.py: Implements network link delay detection based on the LLDP protocol
├─network_monitor.py: Calculates available link bandwidth and traffic statistics
├─shortest_forwarding.py: Solves the ARP network storm problem and implements shortest path forwarding
├─setting.py: Contains global settings for the system experiment

## 2.2 Key Code Introduction
### 2.2.1 Containernet Experiment Script
This script is based on Containernet’s network simulation topology and is mainly used for simulating and testing multi-layer network topologies, containerized nodes, and application performance.

#### (1) Topology Description
The code simulates a two-layer switch topology, where the top layer connects to application containers (prime apps), and the bottom layer connects to simulated user nodes. The user nodes communicate with application nodes via CPN Access switches (OVS). The specific structure is as follows:  
- **Layer A**: The top layer switch (Switch A) connects to application containers (prime apps).  
- **Layer B**: The bottom layer switch (Switch B, i.e., the CPN access router) connects to simulated user nodes.  
The links between the switches are fully connected and support configurations for delay, bandwidth, jitter, and packet loss.

#### (2) Main Code Functions
- **SimNetworkSetUp**  
SimNetworkSetUp class is responsible for managing the entire network simulation settings, such as the number of nodes, the computational power of each node, and link parameters (bandwidth, delay, etc.). These configurations are read and set through different variables in the code.  
The `setting` module contains several global configuration variables, such as `CPU_PERIOD` (used to limit container CPU resources) and `CPN_NODE_REQUEST_DURATION_TIME` (request duration).

- **MyExprTopo**  
MyExprTopo is the topology definition class for Mininet/Containernet, inheriting from Topo. It is responsible for building the experimental topology:  
  - Creating `cpnodes`: Uses Docker containers as CPN user nodes, specifying IP addresses, image versions, CPU quotas, etc.  
  - Creating `prime_apps`: Creates Prime computation application containers, also using Docker, with port mapping for external access.  
  - Creating `switchs_layer_A` and `switchs_layer_B`: Two layers of switches connecting application containers and CPN nodes, respectively. Switch DPID (datapath ID) is converted from decimal to hexadecimal using the `decimal_to_hex_16` function to ensure it's a 16-bit ID.  
  - Setting links between switches: Uses the `addLink` function to connect Layer A and Layer B switches, setting network conditions such as bandwidth, delay, jitter, and packet loss for each link.  
  - `print_setup_params`: Prints network link settings for debugging.

- **run_myexpr_topo function**  
This function handles the main logic of the network simulation:  
  - Initializes the Containernet network instance, specifying RemoteController as the controller and setting up switches and links.  
  - Starts the `uwsgi` service inside the application containers (web server) to make the Prime application service responsive.  
  - Configures default routing for CPN nodes.  
  - Disables spanning tree protocol (STP) on switches and sets OpenFlow version to 1.3.  
  - After starting the network, it executes a load test (`get_app_rps`), generates test data, and stores it in a JSON file.  
  - Executes the network test command (`pingAll`) to verify node connectivity.  
  - Uses the `start_cpn_node_request` function to start CPN nodes' request simulation, which mimics user traffic to Prime applications.

- **start_cpn_node_request function**  
This function launches a containerized Locust testing tool for each CPN user node. Locust is a load testing tool that simulates a large number of user requests to applications.  
It runs Locust inside each CPN container using Docker commands and generates traffic based on the configured request rate (`RATIO_INCREMENT_OF_USERS`), simulating user access to the application.

- **write_cpnode_stats_to_json function**  
After the experiment ends, this function copies the test results (e.g., request statistics, logs) from each CPN container to the local system and saves them in a specified folder. The results include load statistics and log files for each CPN node.

- **Other Auxiliary Functions**  
  - `decimal_to_hex_16`: Converts a decimal number to a 16-bit hexadecimal string to ensure proper DPID formatting for switches.  
  - `copy_file_from_container`: Copies files from Docker containers to the local system, making it easier to save experiment results.  
  - `CLI`: Starts the Mininet command-line interface, allowing users to execute various commands in the simulated network, check network status, or perform manual debugging.

- **Overall Experiment Process**  
  - Define the network topology (create nodes, switches, links, etc.).  
  - Start the simulation network, run services on the application nodes, and configure routing for CPN nodes.  
  - Use the Locust load testing tool to simulate CPN nodes sending requests to application nodes.  
  - After the test completes, save the experimental results and use the Mininet command-line interface (CLI) for further manual testing or debugging.  
  - Stop the network simulation and clean up resources.

## 2.2.2 cpn_routing_app:
This application implements a CPN (Compute Power Network) anycast forwarding service based on the RYU controller. The core goal of CPN routing is to forward traffic using the anycast method, especially when multiple application instances are available. It selects an instance from a forwarding queue to handle user requests. Specifically, it includes the following key features:
### (1) CPN Service Forwarding Entry Class (CPNServiceForwardingEntry)
This class defines the structure and behavior of each CPN service forwarding entry.
- service_id: The unique identifier of the service (consisting of the anycast IP and port).
- service_instance_list: A list of IP addresses and ports for each service instance, serving as the target for user requests.
- forwarding_policy: A probabilistic forwarding policy used to determine which instance the request is forwarded to.
- newest_service_instance_id: The currently selected service instance's IP and port.
- forwarding_queue: A queue generated based on the forwarding policy, ensuring traffic distribution among multiple instances according to the policy.
- update_newest_service_instance_id: Updates the service instance ID, using the global forwarding policy to determine the new target.
- rouding_forwarding_policy: Generates an integer-based forwarding queue based on the forwarding policy, ensuring probabilistic forwarding is discrete and compliant.

### (2) CPN Routing Forwarding Application Class (CPNRouting)
This class inherits from `app_manager.RyuApp` and implements the CPN anycast forwarding logic, handling ARP requests and TCP/UDP traffic while forwarding traffic based on policy.
- Initialization  <br>
`__init__`: Initializes multiple services and forwarding strategies, using `NetworkAwareness` and `ShortestForwarding` modules to gather network topology and shortest path information.
- cpn_all_forwarding_table: Stores the forwarding table for each switch, where the dictionary key is the switch ID and the value is a mapping from service ID to forwarding entries.
- service_id_dict: Records the service ID (anycast IP:port) and the corresponding application service instance list.
- switch_maintained_cpn_service: Records the list of CPN services maintained by each switch, ensuring that each switch can periodically update the CPN routing policy.
- cpn_routing_algo: The CPN routing algorithm used to update the global forwarding strategy.
- _init_testing_setting: Initializes the service forwarding table, configuring multiple instances of each service on different switches.
- _cpn_switch_policy_update: Periodically updates the forwarding policy, ensuring that flow tables in the network are promptly updated with new service instances and forwarding strategies.

- ARP Request Handling  <br>
In the `PacketIn` event, if an ARP request is received and the target IP is a CPN anycast IP, the controller generates an ARP reply.
The ARP reply contains a custom MAC address, also used to identify the service request.

- TCP/UDP Traffic Handling  <br>
When receiving a TCP or UDP packet, the controller checks if the destination IP is a CPN anycast IP. If it is:
  - Record the service instance: Add the service to the list of CPN services maintained by the switch.
  - Match the forwarding table: If the forwarding table for the switch has not expired, use the table to forward traffic directly.
  - Update the service instance: Select a service instance based on the probabilistic forwarding policy and forward the packet to that instance.
  - Modify the flow table: Generate two flow table rules:
    - Rule 1: Modify the destination IP to the selected service instance's IP and forward it to that instance.
    - Rule 2: When the service instance returns a packet, modify the source address back to the anycast IP and return it to the original requester.

- Periodic Route Updates  <br>
The controller periodically updates the service forwarding table for each switch via the `_cpn_switch_policy_update` thread, ensuring that traffic is forwarded to different service instances based on the latest policies.

### (3) Flow Table Management
The `add_flow` method is used to install OpenFlow flow tables, supporting custom priorities, timeouts, and flow actions.
When the controller detects that a switch's flow table has expired or been deleted, it handles the corresponding event through the `flow_removed_handler` method to ensure the controller's state is synchronized with the switch.

### (4) Overall Workflow
- ARP Request Handling: When a user device sends an ARP request to obtain the CPN service's anycast IP, the controller generates an ARP reply with a custom MAC address.
- TCP/UDP Request Handling: When a user device sends a TCP/UDP request, the controller selects a service instance based on the policy, forwards the packet to that instance, and updates the flow table.
- Periodic Updates: The controller periodically updates routing policies via a background thread, adjusting the traffic forwarding behavior for each switch to ensure load balancing across service instances.

# 3. Environment Setup Steps
## 3.0 Environment Preparation:
- Install Docker, Containernet, and RYU applications.
- Run the `docker/build.sh` script to generate the container images needed for the experiment.
- Place this code in the `ryu/ryu/app` directory.
- Check `setting.py` for custom configurations.

## 3.1 Start the Ryu CPN Application
```bash
cd ~/ryu/ryu/app/SA-CPN
sudo ryu-manager cpn_routing_app.py --observe-links --k-paths=1  --weight=hop
```
## 3.2 Start the Container Network Environment
```bash
cd ~/ryu/ryu/app/SA-CPN
sudo python3 containernet_expr.py
```

## 3.3 Other Common Commands
- View switch flow tables
`sudo ovs-ofctl dump-flows -O OpenFlow13 switchA1`
- View container resource statistics
`docker stats`
- Enter the docker directory to update the container
`docker build -f Dockerfile`


