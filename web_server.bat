@echo off
chcp 65001 >nul
cd /d %~dp0
set PYW=%~dp0.venv\Scripts\pythonw.exe
if not exist "%PYW%" set PYW=pythonw
"%PYW%" webserver.py
