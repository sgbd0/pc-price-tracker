@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist logs mkdir logs
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python tracker.py run >> logs\daily.log 2>&1
