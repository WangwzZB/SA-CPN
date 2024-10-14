from flask import Flask, request
from time import time
import threading
import os
import psutil
app = Flask(__name__)

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
    start = time()
    limit = request.args.get("limit")
    primes = numberOfPrimesUpTo(limit)
    elapsed = round(time() - start, 2)
    # storeResult(limit, primes, elapsed)
    return f"Found {primes} primes in {elapsed} seconds.\n"


@app.route("/cpu")
def cpu():
    cpu = psutil.cpu_percent(interval=1)
    return f"Cpu rate is {cpu}\n"


if __name__ == "__main__":
    # Enable debug to prevent generic 500 error while testing.
    app.run(host="0.0.0.0", port=80, debug=True)
