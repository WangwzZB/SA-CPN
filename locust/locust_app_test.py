from locust import HttpUser, task, between, constant_throughput, events, stats
import sys
import argparse
import locust.stats
import json
from locust.env import Environment
sys.path.append('..')
import setting

# 自定义csv写入频率
locust.stats.CSV_STATS_INTERVAL_SEC = 1 # default is 1 second

# 使用 argparse 获取命令行参数
# parser = argparse.ArgumentParser()
# parser.add_argument("--limit", type=int, default=100, help="Limit for primes query parameter")
# args = parser.parse_args()

class PrimeNumberTestUser(HttpUser):
    # 用户之间等待时间 1 到 2 秒
    # wait_time = between(1, 2)
    wait_time = constant_throughput(1)
    # 在代码中直接指定主机地址
    # host = "http://192.168.255.1:8000"  

    @task
    def test_primes_endpoint(self):
        # 使用从命令行获取的 limit 值来构造 URL
        # self.client.get(f"/primes?limit={args.limit}")
        self.client.get(f"/primes?limit={setting.PRIME_NUMBER}")
