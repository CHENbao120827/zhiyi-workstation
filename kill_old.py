# -*- coding: utf-8 -*-
# 杀掉所有匹配 server.py 的 python 进程（确保下次启动加载最新代码）
import subprocess
try:
    subprocess.run(['powershell', '-NoProfile', '-Command',
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -match 'server.py'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"],
        capture_output=True, timeout=15)
except Exception:
    pass
