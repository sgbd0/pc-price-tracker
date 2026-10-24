@echo off
chcp 65001 >nul
echo 正在停止本机的三个后台任务（云端部署成功后运行本文件即可）...
schtasks /Delete /F /TN "PcPartsPriceDaily"
schtasks /Delete /F /TN "PcPartsPriceWeb"
schtasks /Delete /F /TN "PcPartsPriceTunnel"
taskkill /F /IM cloudflared.exe 2>nul
echo.
echo 如果上面提示“拒绝访问”，请右键本文件，选择“以管理员身份运行”。
echo 已停止：每日价格更新、本机看板服务、公网隧道。GitHub 上的云端看板不受影响。
pause
