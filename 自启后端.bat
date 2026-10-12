@echo off
chcp 936 >nul
title 智己工作站后端(自启)
set "GARDEN=C:\Users\ChenZ\Desktop\智己工作站"
cd /d "%GARDEN%"
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py"
if not defined PYCMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD exit /b 1
"%PYCMD%" "%GARDEN%\kill_old.py"
timeout /t 2 /nobreak >nul
start "智己工作站后端" /min "%PYCMD%" server.py
exit /b 0
