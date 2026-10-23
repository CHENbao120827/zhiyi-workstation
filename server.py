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
import os, sys, json, socket, subprocess, threading, time, re, shutil, urllib.request, urllib.parse, hashlib
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

def top_procs(n=8):
    """进程占用 Top：按内存排序（PowerShell Get-Process，标准库实现）"""
    try:
        cmd = ['powershell', '-NoProfile', '-Command',
               'Get-Process -ErrorAction SilentlyContinue | Sort-Object WS -Descending | '
               'Select-Object -First %d Name,WS,CPU | ConvertTo-Json -Compress' % n]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout.strip()
        if not out:
            return []
        d = json.loads(out)
        arr = d if isinstance(d, list) else [d]
        res = []
        for x in arr:
            if not isinstance(x, dict):
                continue
            res.append({'name': str(x.get('Name') or '?'), 'mb': int(round((x.get('WS') or 0) / 1048576)),
                        'cpu': round(float(x.get('CPU') or 0), 1)})
        return res
    except Exception:
        return []

def net_stats():
    """活动网卡累计收发字节（PowerShell Get-NetAdapterStatistics，标准库实现）"""
    try:
        cmd = ['powershell', '-NoProfile', '-Command',
               'Get-NetAdapterStatistics -ErrorAction SilentlyContinue | '
               'Select-Object Name,ReceivedBytes,SentBytes | ConvertTo-Json -Compress']
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout.strip()
        if not out:
            return []
        d = json.loads(out)
        arr = d if isinstance(d, list) else [d]
        return [{'name': str(x.get('Name') or '?'), 'rx': int(x.get('ReceivedBytes') or 0),
                 'tx': int(x.get('SentBytes') or 0)} for x in arr]
    except Exception:
        return []

_netlat_cache = {'t': 0, 'v': None}
def net_lat():
    """外网延迟（ping 阿里公共 DNS，30s 缓存，避免拖慢 2s 轮询）"""
    now = time.time()
    if now - _netlat_cache['t'] < 30 and _netlat_cache['v'] is not None:
        return _netlat_cache['v']
    v = -1
    try:
        out = ps("$r=Test-Connection -ComputerName 223.5.5.5 -Count 2 -ErrorAction SilentlyContinue | "
                 "Select-Object -ExpandProperty ResponseTime; if($r){ [math]::Round(($r | Measure-Object -Average).Average) } else { -1 }")
        v = int(float(out.strip() or -1))
    except Exception:
        v = -1
    _netlat_cache['t'] = now
    _netlat_cache['v'] = v
    return v

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

def _is_local(ip):
    if not ip:
        return False
    ip = ip.split('%')[0]
    if ip in ('127.0.0.1', '::1', '::ffff:127.0.0.1'):
        return True
    return ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.16') or ip.startswith('172.17') or ip.startswith('172.18') or ip.startswith('172.19')

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
def _xml_esc(s0):
    return (s0 or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')

def _sina_rss(kw):
    url = 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=20&page=1'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode('utf-8', 'replace'))
    arr = (d.get('result') or {}).get('data') or []
    # 关键词优先排序：标题含关键词的排前，其余补足（保证实时 + 尽力分类）
    kw0 = (kw or '').strip()
    if kw0:
        hit = [it for it in arr if kw0 in (it.get('title') or '')]
        rest = [it for it in arr if kw0 not in (it.get('title') or '')]
        ordered = (hit + rest)[:20]
    else:
        ordered = arr[:20]
    parts = ['<rss version="2.0"><channel><title>新浪要闻</title>']
    for it in ordered:
        t = _xml_esc((it.get('title') or '').strip())
        u = _xml_esc(it.get('url') or '')
        pd = ''
        try:
            ct = int(it.get('ctime') or 0)
            if ct:
                pd = time.strftime('%a, %d %b %Y %H:%M:%S +0800', time.localtime(ct))
        except Exception:
            pass
        parts.append('<item><title>%s</title><link>%s</link>%s</item>' % (t, u, ('<pubDate>%s</pubDate>' % pd) if pd else ''))
    parts.append('</channel></rss>')
    return ''.join(parts)

def proxy_news(kw):
    now = time.time()
    if kw in _news_cache and now - _news_cache[kw]['t'] < 300:
        return _news_cache[kw]['xml']
    sources = [
        ('bing', 'https://www.bing.com/news/search?q=' + urllib.parse.quote(kw) +
         '&format=rss&setlang=zh-hans&cc=CN'),
        ('bing2', 'https://www.bing.com/news/search?q=' + urllib.parse.quote(kw) +
         '&format=rss&setlang=zh-cn'),
    ]
    last = None
    for name, url in sources:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'})
            with urllib.request.urlopen(req, timeout=7) as r:
                xml = r.read().decode('utf-8', 'replace')
            if '<rss' in xml or '<feed' in xml or '<entry' in xml:
                _news_cache[kw] = {'t': now, 'xml': xml}
                return xml
        except Exception as e:
            last = e
    try:
        xml = _sina_rss(kw)
        _news_cache[kw] = {'t': now, 'xml': xml}
        return xml
    except Exception as e2:
        raise RuntimeError('news fetch failed: ' + str(last) + ' / ' + str(e2))

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
        try:
            if os.path.exists(STATE_FILE):
                import shutil as _sh
                _sh.copy2(STATE_FILE, STATE_FILE + '.bak')
        except Exception:
            pass
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'ts': ts, 'data': data}, f, ensure_ascii=False)
    return ts

def check_token(h):
    tok = h.get('X-Token', '')
    return tok == SYNC_TOKEN

# ---------- HTTP 服务 ----------

def _ps_encoded(cmd):
    import base64
    return base64.b64encode(cmd.encode('utf-16-le')).decode()

def _run_ps(cmd):
    try:
        subprocess.run(['powershell', '-NoProfile', '-EncodedCommand', _ps_encoded(cmd)],
                       timeout=12, capture_output=True)
        return True
    except Exception:
        return False

def _startup_dir():
    ap = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(ap, 'Microsoft\\Windows\\Start Menu\\Programs\\Startup')

def _lnk(kind):
    return os.path.join(_startup_dir(), '智己工作站-后端.lnk' if kind == 'backend' else 'cpolar隧道.lnk')

def autostart_setup(kind, on):
    lnk = _lnk(kind)
    if not on:
        try:
            if os.path.exists(lnk):
                os.remove(lnk)
        except Exception:
            pass
        return not os.path.exists(lnk)
    if kind == 'backend':
        exe = shutil.which('py') or shutil.which('python') or 'py'
        cmd = "$ws=New-Object -ComObject WScript.Shell;$l=$ws.CreateShortcut('%s');$l.TargetPath='%s';$l.Arguments='%s';$l.WorkingDirectory='%s';$l.WindowStyle=7;$l.Save()" % (
            lnk, exe, os.path.join(ROOT, 'server.py'), ROOT)
    else:
        exe = shutil.which('cpolar') or 'cpolar'
        cmd = "$ws=New-Object -ComObject WScript.Shell;$l=$ws.CreateShortcut('%s');$l.TargetPath='%s';$l.Arguments='http -region cn 8600';$l.WorkingDirectory='%s';$l.WindowStyle=7;$l.Save()" % (
            lnk, exe, ROOT)
    return _run_ps(cmd) and os.path.exists(lnk)

def service_status():
    return {'ok': True, 'backend': os.path.exists(_lnk('backend')),
            'cpolar': os.path.exists(_lnk('cpolar')), 'pid': os.getpid()}

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

    def _shutdown_all(self):
        def _do():
            try:
                subprocess.Popen('taskkill /IM msedge.exe /F /T', shell=True)
            except Exception:
                pass
            try:
                ps = "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'server.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
                subprocess.run(['powershell', '-NoProfile', '-EncodedCommand', _ps_encoded(ps)], timeout=15, capture_output=True)
            except Exception:
                pass
            try:
                os._exit(0)
            except Exception:
                pass
        threading.Timer(1.0, _do).start()

    def do_OPTIONS(self):
        self._send(204, '', 'text/plain; charset=utf-8')

    def do_POST(self):
        try:
            u = urllib.parse.urlparse(self.path)
            if u.path == '/api/service':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                ln = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(ln).decode('utf-8', 'replace')
                d = json.loads(body)
                act = d.get('action') or ''
                if act == 'shutdown':
                    self._shutdown_all()
                    self._json(200, {'ok': True, 'msg': '服务已关闭'})
                    return
                if act in ('backend_on', 'backend_off', 'cpolar_on', 'cpolar_off'):
                    kind, on = act.split('_')[0], act.endswith('_on')
                    ok = autostart_setup(kind, on)
                    st = service_status()
                    st['ok'] = ok
                    self._json(200, st)
                    return
                self._json(400, {'ok': False, 'msg': 'bad action'})
                return
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
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                self._json(200, sys_status())
                return
            if route == '/api/procs':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                self._json(200, {'ok': True, 'list': top_procs()})
                return
            if route == '/api/net':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                self._json(200, {'ok': True, 'list': net_stats()})
                return
            if route == '/api/netlat':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                self._json(200, {'ok': True, 'ms': net_lat()})
                return
            if route == '/api/version':
                try:
                    _vh = hashlib.md5(open(os.path.join(ROOT, 'index.html'), 'rb').read()).hexdigest()[:12]
                except Exception:
                    _vh = '0'
                self._send(200, '{"v":"' + _vh + '"}', 'application/json')
            if route == '/api/ping':
                self._json(200, {'ok': True, 'host': socket.gethostname(), 'ip': lan_ips()})
                return
            if route == '/api/state':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                _st0 = load_state()
                _st0['ok'] = True
                self._json(200, _st0)
                return
            if route == '/api/open':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                qs = urllib.parse.parse_qs(u.query)
                key = (qs.get('app') or [''])[0]
                if key == 'custom':
                    path = (qs.get('path') or [''])[0]
                    if not _is_local(self.client_address[0]):
                        self._json(403, {'ok': False, 'msg': '仅本机或局域网可启动自定义程序'})
                        return
                    if not path or not os.path.exists(path):
                        self._json(404, {'ok': False, 'msg': '路径不存在：' + path})
                        return
                    try:
                        os.startfile(path)
                        self._json(200, {'ok': True, 'msg': '已启动 ' + os.path.basename(path)})
                    except Exception as e:
                        self._json(500, {'ok': False, 'msg': '启动失败：' + str(e)})
                    return
                self._json(200, launch_app(key))
                return
            if route == '/api/exist':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                qs = urllib.parse.parse_qs(u.query)
                path = (qs.get('path') or [''])[0]
                if not _is_local(self.client_address[0]):
                    self._json(403, {'ok': False, 'msg': '仅本机或局域网可检查'})
                    return
                self._json(200, {'ok': True, 'exists': bool(path and os.path.exists(path))})
                return
            if route == '/api/service':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                self._json(200, service_status())
                return
            if route == '/api/news':
                if not check_token(self.headers):
                    self._json(401, {'ok': False, 'msg': 'token 无效'})
                    return
                qs = urllib.parse.parse_qs(u.query)
                kw = (qs.get('kw') or [''])[0]
                if not kw:
                    kw = ''
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

def port_in_use(port):
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=8).stdout
        for line in out.splitlines():
            if ':%d ' % port in line and 'LISTENING' in line:
                return True
    except Exception:
        pass
    return False

def main():
    if port_in_use(PORT):
        print('  \u26a0 端口 %d 已被占用（后端可能已在运行），本实例自动退出。' % PORT)
        sys.exit(0)
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
