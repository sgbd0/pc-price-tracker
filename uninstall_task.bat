@echo off
chcp 65001 >nul
schtasks /Delete /F /TN "PcPartsPriceDaily"
echo 已取消每天 09:00 的自动更新任务。（报告仍可用 python tracker.py run 手动更新）
pause
