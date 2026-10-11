/*
 * 智己工作站 · 本地后端服务（Node.js）
 * 功能：
 *   1. 静态托管本文件夹（http://localhost:8600）
 *   2. GET /api/sys     系统实时状态（CPU/内存/磁盘/网络/运行时长/进程数）
 *   3. GET /api/open    ?app=key 启动白名单内的本机应用
 *   4. GET /api/news    ?kw=关键词 代理 Bing 新闻 RSS（前端同源抓取，更稳定）
 * 启动：node server.js   （或双击 启动工作台.bat）
 */
const http=require('http');
const fs=require('fs');
const path=require('path');
const os=require('os');
const {exec}=require('child_process');

const ROOT=__dirname;
const PORT=Number(process.env.PORT||8600);
const MIME={
  '.html':'text/html; charset=utf-8','.htm':'text/html; charset=utf-8',
  '.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8',
  '.json':'application/json; charset=utf-8','.md':'text/markdown; charset=utf-8',
  '.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg',
  '.ico':'image/x-icon','.txt':'text/plain; charset=utf-8','.woff2':'font/woff2'
};

/* ---------- 系统状态 ---------- */
function cpuUsage(){
  return new Promise(function(res){
    const t0=os.cpus();
    setTimeout(function(){
      const t1=os.cpus();
      let idle=0,total=0;
      t0.forEach(function(c,i){
        const a=c.times,b=t1[i].times;
        idle+=b.idle-a.idle;
        total+=(b.user+b.nice+b.sys+b.idle+b.irq)-(a.user+a.nice+a.sys+a.idle+a.irq);
      });
      res(total===0?0:Math.round((1-idle/total)*1000)/10);
    },120);
  });
}
let diskCache={t:0,data:null};
function diskInfo(){
  return new Promise(function(res){
    if(Date.now()-diskCache.t<8000&&diskCache.data){ res(diskCache.data); return; }
    exec('powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk -Filter \\"DriveType=3\\" | Select-Object DeviceID,@{n=\'Size\';e={[math]::Round($_.Size/1GB)}},@{n=\'Free\';e={[math]::Round($_.FreeSpace/1GB)}} | ConvertTo-Json -Compress"',{timeout:5000,windowsHide:true},function(err,stdout){
      if(err||!stdout){ res(diskCache.data||[]); return; }
      try{
        const raw=JSON.parse(stdout.trim());
        const arr=Array.isArray(raw)?raw:[raw];
        const data=arr.filter(function(d){return d&&d.DeviceID;}).map(function(d){
          const total=Number(d.Size)||0,free=Number(d.Free)||0;
          return {drive:d.DeviceID,total:total,used:total-free,free:free,pct:total?Math.round((total-free)/total*100):0};
        });
        diskCache={t:Date.now(),data:data};
        res(data);
      }catch(e){ res(diskCache.data||[]); }
    });
  });
}
function lanIPs(){
  const out=[];
  const ifs=os.networkInterfaces();
  Object.keys(ifs).forEach(function(k){
    (ifs[k]||[]).forEach(function(a){
      if(a.family==='IPv4'&&!a.internal)out.push(a.address);
    });
  });
  return out;
}
function procCount(){
  return new Promise(function(res){
    exec('powershell -NoProfile -Command "(Get-Process).Count"',{timeout:5000,windowsHide:true},function(err,stdout){
      res(err?0:parseInt(stdout.trim(),10)||0);
    });
  });
}
async function sysStatus(){
  const [cpu,disk,procs]=await Promise.all([cpuUsage(),diskInfo(),procCount()]);
  const tm=os.uptime();
  const mem=os.totalmem()-os.freemem();
  return {
    cpu:{pct:cpu,cores:os.cpus().length,model:os.cpus()[0]?os.cpus()[0].model.trim():''},
    mem:{total:os.totalmem(),used:mem,free:os.freemem(),pct:Math.round(mem/os.totalmem()*100)},
    disk:disk,
    up:{sec:tm,text:upText(tm)},
    procs:procs,
    host:os.hostname(),
    ip:lanIPs(),
    platform:process.platform+' '+os.release(),
    node:process.version,
    time:new Date().toISOString()
  };
}
function upText(s){
  const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
  return d>0?(d+' 天 '+h+' 小时'):(h>0?(h+' 小时 '+m+' 分'):(m+' 分钟'));
}

/* ---------- 应用启动（白名单，防注入） ---------- */
const APPS={
  edge:{cmd:'msedge',name:'Microsoft Edge'},
  chrome:{cmd:'chrome',name:'Chrome'},
  notepad:{cmd:'notepad',name:'记事本'},
  calc:{cmd:'calc',name:'计算器'},
  mspaint:{cmd:'mspaint',name:'画图'},
  explorer:{cmd:'explorer',name:'文件资源管理器'},
  powershell:{cmd:'powershell',name:'PowerShell'},
  taskmgr:{cmd:'taskmgr',name:'任务管理器'},
  cmd:{cmd:'cmd',name:'命令提示符'},
  settings:{cmd:'ms-settings:',name:'系统设置'},
  control:{cmd:'control',name:'控制面板'},
  mars:{cmd:'"C:\\Users\\ChenZ\\Desktop\\Python小游戏\\火星之心.exe"',name:'火星之心'},
  space:{cmd:'"D:\\sfs\\航天模拟器PC1.5\\Spaceflight Simulator\\Spaceflight Simulator.exe"',name:'航天模拟器'}
};
function launchApp(key){
  const a=APPS[key];
  if(!a)return {ok:false,msg:'未知应用'};
  exec('start "" '+a.cmd,{shell:'cmd.exe',windowsHide:true},function(e){});
  return {ok:true,msg:'已启动 '+a.name};
}

/* ---------- 新闻代理 ---------- */
let newsCache={};
function proxyNews(kw){
  const key=encodeURIComponent(kw);
  if(newsCache[key]&&Date.now()-newsCache[key].t<5*60*1000){
    return Promise.resolve(newsCache[key].xml);
  }
  const url='https://www.bing.com/news/search?q='+key+'&format=rss&setlang=zh-hans&cc=CN';
  return fetch(url,{headers:{'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}})
    .then(function(r){ if(!r.ok)throw new Error('HTTP '+r.status); return r.text(); })
    .then(function(xml){
      newsCache[key]={t:Date.now(),xml:xml};
      return xml;
    });
}

/* ---------- HTTP 服务 ---------- */
function serveStatic(req,res){
  let p=decodeURIComponent(req.url.split('?')[0]);
  if(p==='/')p='/index.html';
  const fp=path.normalize(path.join(ROOT,p));
  if(!fp.startsWith(ROOT)){ res.writeHead(403); res.end('Forbidden'); return; }
  fs.readFile(fp,function(err,data){
    if(err){ res.writeHead(404,{'Content-Type':'text/plain; charset=utf-8'}); res.end('404 Not Found'); return; }
    res.writeHead(200,{'Content-Type':MIME[path.extname(fp).toLowerCase()]||'application/octet-stream','Cache-Control':'no-cache'});
    res.end(data);
  });
}
const server=http.createServer(async function(req,res){
  const u=req.url||'';
  const route=u.split('?')[0];
  try{
    if(route==='/api/sys'){
      const d=await sysStatus();
      res.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
      res.end(JSON.stringify(d));
      return;
    }
    if(route==='/api/open'){
      const key=new URL(u,'http://x').searchParams.get('app')||'';
      const r=launchApp(key);
      res.writeHead(200,{'Content-Type':'application/json'});
      res.end(JSON.stringify(r));
      return;
    }
    if(route==='/api/news'){
      const kw=new URL(u,'http://x').searchParams.get('kw')||'';
      if(!kw){ res.writeHead(400); res.end('need kw'); return; }
      try{
        const xml=await proxyNews(kw);
        res.writeHead(200,{'Content-Type':'application/xml; charset=utf-8','Cache-Control':'no-store'});
        res.end(xml);
      }catch(e){
        res.writeHead(502,{'Content-Type':'application/json'});
        res.end(JSON.stringify({ok:false,msg:'news fetch failed: '+e.message}));
      }
      return;
    }
    if(route==='/api/apps'){
      res.writeHead(200,{'Content-Type':'application/json; charset=utf-8'});
      res.end(JSON.stringify(Object.keys(APPS).map(function(k){return {key:k,name:APPS[k].name};})));
      return;
    }
    serveStatic(req,res);
  }catch(e){
    res.writeHead(500,{'Content-Type':'text/plain; charset=utf-8'});
    res.end('server error: '+e.message);
  }
});
server.listen(PORT,function(){
  console.log('');
  console.log('  ✦ 智己工作站后端已启动');
  console.log('  ➜  工作台地址  http://localhost:'+PORT);
  console.log('  ➜  本机 IP      http://'+((lanIPs()[0])||'127.0.0.1')+':'+PORT);
  console.log('  关闭本窗口即停止服务（浏览器页面保留，实时监测将暂停）');
  console.log('');
});
server.on('error',function(e){
  if(e.code==='EADDRINUSE'){
    console.log('服务已在运行，直接打开浏览器访问 http://localhost:'+PORT);
    return;
  }
  throw e;
});
