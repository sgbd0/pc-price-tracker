@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist logs mkdir logs
:loop
cloudflared.exe tunnel --url http://127.0.0.1:8787 --logfile logs\tunnel.log --loglevel info
timeout /t 15 /nobreak >nul
goto loop
