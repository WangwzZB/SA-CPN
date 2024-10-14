from locust import HttpUser, task, between, constant_throughput, events, stats
import locust.stats
import logging

# 自定义csv写入频率
locust.stats.CSV_STATS_INTERVAL_SEC = 1 # default is 1 second

# 定义请求成功和失败的钩子函数（可选）
# log_file_path = '/locust/logfile.log'  # 指定日志文件的路径和名称

# logging.basicConfig(filename=log_file_path, level=logging.INFO,

#                     format='%(asctime)s - %(levelname)s - %(message)s')

# @events.request.add_listener
# def log_success(request_type, name, response_time, response_length, response,
#                        context, exception, start_time, url, **kwargs):

#     logging.info(f"Request {name} succeeded in {response_time:.2f}ms")

class PrimeNumberTestUser(HttpUser):
    # 用户之间等待时间 1 到 2 秒
    # wait_time = between(1, 2)
    wait_time = constant_throughput(0.1)
    # 在代码中直接指定主机地址
    # host = "http://192.168.255.1:8000"  

    @task
    def test_primes_endpoint(self):
        # 使用从命令行获取的 limit 值来构造 URL
        # self.client.get(f"/primes?limit={args.limit}")
        self.client.get(f"/primes?limit=800")