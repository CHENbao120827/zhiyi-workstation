@echo off
chcp 936 >nul
title 安装开机自启 - 智己工作站
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo ============================================
echo   一键安装开机自启（智己工作站）
echo   将创建两个开机启动项：
echo   1. 智己工作站后端 (python server.py)
echo   2. cpolar 隧道 (cpolar http 8600)
echo   以后开机自动运行，无需手动开窗口
echo ============================================

set "PYEXE="
for /f "delims=" %%i in ('where py 2^>nul') do if not defined PYEXE set "PYEXE=%%i"
if not defined PYEXE for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYEXE set "PYEXE=%%i"
if not defined PYEXE (
  echo [错误] 未找到 Python，请先安装 Python 3
  pause
  exit /b 1
)
echo [已找到] Python: %PYEXE%

set "CPOLAR="
for /f "delims=" %%i in ('where cpolar 2^>nul') do if not defined CPOLAR set "CPOLAR=%%i"
if not defined CPOLAR (
  echo [提示] 未找到 cpolar，跳过隧道自启（只装后端自启）
  goto :no_cpolar
)
echo [已找到] cpolar: %CPOLAR%

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$l=$ws.CreateShortcut('%STARTUP%\智己工作站-后端.lnk');$l.TargetPath='%PYEXE%';$l.Arguments='C:\Users\ChenZ\Desktop\智己工作站\server.py';$l.WorkingDirectory='C:\Users\ChenZ\Desktop\智己工作站';$l.WindowStyle=7;$l.Save()"
if %errorlevel%==0 (echo [OK] 后端自启已安装) else (echo [失败] 后端自启安装失败)

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$l=$ws.CreateShortcut('%STARTUP%\cpolar隧道.lnk');$l.TargetPath='%CPOLAR%';$l.Arguments='http -region cn 8600';$l.WorkingDirectory='C:\Users\ChenZ\Desktop\智己工作站';$l.WindowStyle=7;$l.Save()"
if %errorlevel%==0 (echo [OK] cpolar 自启已安装) else (echo [失败] cpolar 自启安装失败)
goto :done

:no_cpolar
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$l=$ws.CreateShortcut('%STARTUP%\智己工作站-后端.lnk');$l.TargetPath='%PYEXE%';$l.Arguments='C:\Users\ChenZ\Desktop\智己工作站\server.py';$l.WorkingDirectory='C:\Users\ChenZ\Desktop\智己工作站';$l.WindowStyle=7;$l.Save()"
if %errorlevel%==0 (echo [OK] 后端自启已安装) else (echo [失败] 后端自启安装失败)

:done
echo.
echo 安装完成！下次开机后会自动启动后端与隧道。
echo 注意：免费版 cpolar 隧道重启后地址可能变化，开机后如地址变了请告诉我更新。
pause
