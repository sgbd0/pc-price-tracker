@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo    电脑配件价格日报 - 一键安装
echo ============================================
echo.

if not exist .venv (
    echo [1/4] 创建 Python 虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo 创建虚拟环境失败，请确认已安装 Python 3.10 以上版本。
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

echo [2/4] 安装小模型运行库 llama-cpp-python（约8MB）...
pip install -q llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 (
    pip install -q llama-cpp-python
)
if errorlevel 1 (
    echo [提示] llama-cpp-python 安装失败，工具将以纯规则模式运行，不影响每日更新。
)

echo [3/4] 下载本地小模型 Qwen2.5-0.5B（约400MB，只需下载一次）...
python tracker.py model-setup

echo [4/4] 注册 Windows 计划任务：每天 09:00 自动更新...
schtasks /Create /F /TN "PcPartsPriceDaily" /TR "\"%~dp0run_daily.bat\"" /SC DAILY /ST 09:00

echo.
echo 立即执行一次更新，验证效果...
python tracker.py run
echo.
echo ============================================
echo  安装完成！
echo   - 每天 09:00 自动更新价格
echo   - 报告位置: data\report.html （双击用浏览器打开）
echo   - 取消自动更新: 双击 uninstall_task.bat
echo ============================================
pause
