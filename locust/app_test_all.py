import subprocess
import sys
sys.path.append('..')
import setting
import pandas as pd
from typing import Dict
import time

def get_app_rps()-> Dict[str, float]:
    setup = setting.SimNetworkSetUp()
    commands = []
    # 定义不同的 Locust 命令
    for i in range(setup.numberOfPrimeApps):
        # app_ip = setup.prime_apps_ip_list[i]
        # users 280 180 rate 10 10 run-time 30 20
        command = ['locust', '-f', '/home/wwz/ryu/ryu/app/network_awareness/locust/locust_app_test.py', 
                '--host', f'http://127.0.0.1:800{i}', 
                '--users', '40',
                '--spawn-rate', '10', 
                '--run-time', '15s',
                '--headless',
                '--csv', f'results/app_test_output/primeApp{i+1}',
                '--skip-log']
        commands.append(command)

    # 依次执行每个命令
    for command in commands:
        print(f"Running Locust command: {' '.join(command)}")

        # 使用 subprocess.run() 执行命令
        result = subprocess.run(command, capture_output=True, text=True)

        # 打印输出
        print(result.stdout)
        
        # 打印错误输出（如果有）
        if result.stderr:
            print(f"Error: {result.stderr}")

        # 检查命令执行是否成功
        if result.returncode == 0:
            print(f"Locust command completed successfully for host: {command[5]}")
        else:
            print(f"Locust command failed for host: {command[5]} with return code {result.returncode}")
        # 等待前一个进程完全结束后再启动下一个（可以调整时间）
        time.sleep(30) 

    # 读文件
    app_rps: Dict[str, float] = {}
    for i in range(setup.numberOfPrimeApps):
        stats = pd.read_csv(f'results/app_test_output/primeApp{i+1}_stats.csv')
        app_ip = setup.prime_apps_ip_list[i]
        app_rps[f'primeApp{i+1}'] = stats.loc[1, 'Requests/s']
    # print(app_rps)
    return app_rps



