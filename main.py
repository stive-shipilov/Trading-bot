import subprocess
import time

server_process = subprocess.Popen(["python3", "server.py"])
time.sleep(7)

client_run_process = subprocess.Popen(["./TradingBot"])

server_process.wait()
client_run_process.wait()