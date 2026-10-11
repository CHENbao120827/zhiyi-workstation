# -*- coding: utf-8 -*-
"""
智己工作站 · 本地后端服务（Python 标准库版，无需安装任何依赖）
功能：
  1. 静态托管本文件夹（http://localhost:8600）
  2. GET /api/sys     系统实时状态（CPU/内存/磁盘/网络/运行时长/进程数）
  3. GET /api/open    ?app=key 启动白名单内的本机应用
  4. GET /api/news    ?kw=关键词 代理 Bing 新闻 RSS（服务端抓取，无跨域限制）
  5. GET /api/apps    白名单应用列表
启动：双击桌面「启动工作台.bat」，或手动运行  python server.py
"""
import os, sys, json, socket, subprocess, threading, time, re, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', 8600))

MIME = {
    '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8', '.md': 'text/markdown; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8',
    '.woff2': 'font/woff2',
}

# ---------- 系统状态（stdlib + PowerShell） ----------
def ps(cmd):
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                           capture_output=True, text=True, timeout=6)
        return (r.stdout or '').strip()
    except Exception:
        return ''

def lan_ips():
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        out.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    if not out:
        try:
            out = [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)
                   if i[0] == socket.AF_INET and not i[4][0].startswith('127.')]
        except Exception:
            pass
    return out

_disk_cache = {'t': 0, 'data': []}
def disk_info():
    global _disk_cache
    now = time.time()
    if now - _disk_cache['t'] < 8 and _disk_cache['data']:
        return _disk_cache['data']
    raw = ps("Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" | "
             "Select-Object DeviceID,@{n='Size';e={[math]::Round($_.Size/1GB)}},"
             "@{n='Free';e={[math]::Round($_.FreeSpace/1GB)}} | ConvertTo-Json -Compress")
    data = []
    try:
        arr = json.loads(raw)
        if isinstance(arr, dict):
            arr = [arr]
        for d in arr:
            if not d or 'DeviceID' not in d:
                continue
            total = float(d.get('Size') or 0)
            free = float(d.get('Free') or 0)
            used = total - free
            data.append({'drive': d['DeviceID'], 'total': total, 'used': used,
                         'free': free, 'pct': int(round(used / total * 100)) if total else 0})
    except Exception:
        data = _disk_cache['data']
    _disk_cache = {'t': now, 'data': data}
    return data

_sys_cache = {'t': 0, 'data': None}
def sys_status():
    # 2 秒缓存：前端每 2s 轮询，避免每次重跑 PowerShell
    now = time.time()
    if now - _sys_cache['t'] < 2 and _sys_cache['data']:
        return _sys_cache['data']
    # 一次 PowerShell 调用拿齐 CPU/内存/进程数/开机时长，大幅提速
    raw = ps("$cpu=(Get-CimInstance Win32_Processor).LoadPercentage;"
             "$o=Get-CimInstance Win32_OperatingSystem;"
             "$t=[math]::Round($o.TotalVisibleMemorySize/1KB);"
             "$f=[math]::Round($o.FreePhysicalMemory/1KB);"
             "$p=(Get-Process).Count;"
             "$u=[int]((Get-Date)-$o.LastBootUpTime).TotalSeconds;"
             "[pscustomobject]@{cpu=$cpu;memT=$t;memF=$f;procs=$p;up=$u}|ConvertTo-Json -Compress")
    cpu, mem_total, mem_free, procs, up_sec = 0, 0, 0, 0, 0
    try:
        j = json.loads(raw)
        cpu = min(100, max(0, int(float(j.get('cpu') or 0))))
        mem_total, mem_free = int(float(j.get('memT') or 0)), int(float(j.get('memF') or 0))
        procs = int(float(j.get('procs') or 0))
        up_sec = max(0, int(float(j.get('up') or 0)))
    except Exception:
        pass
    mem_used = mem_total - mem_free
    d = {
        'cpu': {'pct': cpu, 'cores': os.cpu_count() or 1, 'model': ''},
        'mem': {'total': mem_total * 1048576, 'used': mem_used * 1048576, 'free': mem_free * 1048576,
                'pct': round(mem_used / mem_total * 100) if mem_total else 0},
        'disk': disk_info(),
        'up': {'sec': up_sec, 'text': up_text(up_sec)},
        'procs': procs,
        'host': socket.gethostname(),
        'ip': lan_ips(),
        'platform': sys.platform,
        'python': sys.version.split()[0],
        'time': time.strftime('%Y-%m-%dT%H:%M:%S+08:00', time.localtime()),
    }
    _sys_cache['t'] = now
    _sys_cache['data'] = d
    return d

def up_text(s):
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d > 0:
        return '%d 天 %d 小时' % (d, h)
    if h > 0:
        return '%d 小时 %d 分' % (h, m)
    return '%d 分钟' % m

# ---------- 应用启动（白名单，防注入） ----------
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if not os.path.exists(EDGE):
    EDGE = r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
if not os.path.exists(CHROME):
    CHROME = r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'

APPS = {
    'edge': {'cmd': EDGE, 'name': 'Microsoft Edge'},
    'chrome': {'cmd': CHROME, 'name': 'Chrome'},
    'notepad': {'cmd': r'C:\Windows\System32\notepad.exe', 'name': '记事本'},
    'calc': {'cmd': r'C:\Windows\System32\calc.exe', 'name': '计算器'},
    'mspaint': {'cmd': r'C:\Windows\System32\mspaint.exe', 'name': '画图'},
    'explorer': {'cmd': r'C:\Windows\explorer.exe', 'name': '文件资源管理器'},
    'powershell': {'cmd': r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', 'name': 'PowerShell'},
    'taskmgr': {'cmd': r'C:\Windows\System32\Taskmgr.exe', 'name': '任务管理器'},
    'cmd': {'cmd': r'C:\Windows\System32\cmd.exe', 'name': '命令提示符'},
    'settings': {'cmd': 'ms-settings:', 'name': '系统设置'},
    'control': {'cmd': r'C:\Windows\System32\control.exe', 'name': '控制面板'},
    'mars': {'cmd': r'C:\Users\ChenZ\Desktop\Python小游戏\火星之心.exe', 'name': '火星之心'},
    'space': {'cmd': r'D:\sfs\航天模拟器PC1.5\Spaceflight Simulator\Spaceflight Simulator.exe', 'name': '航天模拟器'},
}

def launch_app(key):
    a = APPS.get(key)
    if not a:
        return {'ok': False, 'msg': '未知应用'}
    cmd = a['cmd']
    if cmd.endswith(':') or cmd.startswith('ms-'):
        try:
            os.startfile(cmd)
            return {'ok': True, 'msg': '已打开 ' + a['name']}
        except Exception as e:
            return {'ok': False, 'msg': '打开失败：' + str(e)}
    if not os.path.exists(cmd):
        return {'ok': False, 'msg': '未找到程序：' + cmd}
    try:
        os.startfile(cmd)
        return {'ok': True, 'msg': '已启动 ' + a['name']}
    except Exception as e:
        return {'ok': False, 'msg': '启动失败：' + str(e)}

# ---------- 新闻代理（服务端抓取，无跨域限制） ----------
_news_cache = {}
def proxy_news(kw):
    now = time.time()
    if kw in _news_cache and now - _news_cache[kw]['t'] < 300:
        return _news_cache[kw]['xml']
    url = ('https://www.bing.com/news/search?q=' + urllib.parse.quote(kw) +
           '&format=rss&setlang=zh-hans&cc=CN')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            xml = r.read().decode('utf-8', 'replace')
    except Exception as e:
        raise RuntimeError('news fetch failed: ' + str(e))
    if '<rss' not in xml:
        raise RuntimeError('bing returned non-rss (html), use allorigins channel')
    _news_cache[kw] = {'t': now, 'xml': xml}
    return xml

# ---------- 云端数据存储（这台电脑 = 服务器，多设备同步） ----------
STATE_FILE = os.path.join(ROOT, 'state.json')
SYNC_TOKEN = os.environ.get('SYNC_TOKEN', 'zhiyi-ws-2026')
_lock = threading.Lock()

def load_state():
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict) and 'data' in d:
            return d
    except Exception:
        pass
    return {'ts': 0, 'data': {}}

def save_state(ts, data):
    with _lock:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'ts': ts, 'data': data}, f, ensure_ascii=False)
    return ts

def check_token(h):
    tok = h.get('X-Token', '')
    return tok == SYNC_TOKEN

# ---------- HTTP 服务 ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        # CORS：允许 GitHub Pages 等任意来源的前端调用本后端
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Token')
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def do_OPTIONS(self):
        self._send(204, '', 'text/plain; charset=utf-8')

    def do_POST(self):
        try:
            u = urllib.parse.urlparse(self.path)
            if u.path != '/api/state':
                self._json(404, {'ok': False, 'msg': 'not found'})
                return
            if not check_token(self.headers):
                self._json(401, {'ok': False, 'msg': 'token 无效'})
                return
            ln = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(ln).decode('utf-8', 'replace')
            d = json.loads(body)
            ts = int(d.get('ts') or time.time() * 1000)
            data = d.get('data')
            if not isinstance(data, dict):
                raise ValueError('bad data')
            save_state(ts, data)
            self._json(200, {'ok': True, 'ts': ts})
        except Exception as e:
            self._json(400, {'ok': False, 'msg': str(e)})

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(self.path)
            route = u.path
            if route == '/api/sys':
                self._json(200, sys_status())
                return
            if route == '/api/ping':
                self._json(200, {'ok': True, 'host': socket.gethostname(), 'ip': lan_ips()})
                return
            if route == '/api/state':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                self._json(200, load_state())
                return
            if route == '/api/open':
                qs = urllib.parse.parse_qs(u.query)
                key = (qs.get('app') or [''])[0]
                self._json(200, launch_app(key))
                return
            if route == '/api/news':
                qs = urllib.parse.parse_qs(u.query)
                kw = (qs.get('kw') or [''])[0]
                if not kw:
                    self._send(400, 'need kw', 'text/plain; charset=utf-8')
                    return
                try:
                    xml = proxy_news(kw)
                    self._send(200, xml, 'application/xml; charset=utf-8')
                except Exception as e:
                    self._json(502, {'ok': False, 'msg': str(e)})
                return
            if route == '/api/apps':
                self._json(200, [{'key': k, 'name': v['name']} for k, v in APPS.items()])
                return
            self._serve_static(route)
        except Exception as e:
            self._send(500, 'server error: ' + str(e), 'text/plain; charset=utf-8')

    def _serve_static(self, route):
        p = route if route != '/' else '/index.html'
        fp = os.path.normpath(os.path.join(ROOT, p.lstrip('/')))
        if not fp.startswith(ROOT):
            self._send(403, 'Forbidden', 'text/plain; charset=utf-8')
            return
        if not os.path.isfile(fp):
            self._send(404, '404 Not Found', 'text/plain; charset=utf-8')
            return
        ext = os.path.splitext(fp)[1].lower()
        ctype = MIME.get(ext, 'application/octet-stream')
        with open(fp, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(data)

def main():
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print('')
    print('  \u2726 智己工作站后端已启动（Python ' + sys.version.split()[0] + '）')
    print('  \u27a1  \u5de5\u4f5c\u53f0\u5730\u5740  http://localhost:%d' % PORT)
    ips = lan_ips()
    if ips:
        print('  \u27a1  \u672c\u673a IP      http://%s:%d' % (ips[0], PORT))
    print('  \u5173\u95ed\u672c\u7a97\u53e3\u5373\u505c\u6b62\u670d\u52a1\uff08\u6d4f\u89c8\u5668\u9875\u9762\u4fdd\u7559\uff0c\u5b9e\u65f6\u76d1\u6d4b\u5c06\u6682\u505c\uff09')
    print('')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
