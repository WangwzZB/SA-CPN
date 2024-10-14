from flask import Flask, request
from time import time
import threading
import os

app = Flask(__name__)


# # 定义文件路径
# output_file = 'output.txt'

# # 初始化计数器
# if os.path.exists(output_file):
#     with open(output_file, 'r') as f:
#         try:
#             request_count = int(f.read().strip())
#         except ValueError:
#             request_count = 0
# else:
#     request_count = 0

# # 锁对象用于确保多线程下的安全操作
# count_lock = threading.Lock()

# # 后台线程函数：每 20 秒将计数写入文件
# def save_count_to_file():
#     while True:
#         time.sleep(20)  # 每20秒更新一次
#         with count_lock:
#             with open(output_file, 'w') as f:
#                 f.write(str(request_count))

# # 启动后台线程
# threading.Thread(target=save_count_to_file, daemon=True).start()


def numberOfPrimesUpTo(limit):
    """计算limit值以下的质数数量"""
    count = 0
    for i in range(int(limit) + 1):
        if i > 1:
            isPrime = True
            for j in range(2, i):
                if i % j == 0:
                    isPrime = False
                    break
            if isPrime:
                count += 1
    return count


@app.route("/primes")
def default():
    # global request_count
    # with count_lock:
    #     # 每次接收到请求时增加计数
    #     request_count += 1
    start = time()
    limit = request.args.get("limit")
    primes = numberOfPrimesUpTo(limit)
    elapsed = round(time() - start, 2)
    # storeResult(limit, primes, elapsed)
    return f"Found {primes} primes in {elapsed} seconds.\n"

# @app.route("/cpu")
# def default():
#     cpu = psutil.cpu_percent(interval=1)
#     return f"Cpu rate is {cpu}\n"


if __name__ == "__main__":
    # Enable debug to prevent generic 500 error while testing.
    app.run(host="0.0.0.0", port=80, debug=True)
