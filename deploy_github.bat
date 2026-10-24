@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   一键部署到 GitHub（云端自动更新）
echo ============================================
echo.

if not exist .git git init -b main

git config user.name "price-bot" 2>nul
git config user.email "price-bot@users.noreply.github.com" 2>nul

git add -A
git diff --cached --quiet
if errorlevel 1 git commit -m "电脑配件价格看板"
if not errorlevel 1 echo 文件无变化，跳过提交。

set /p REMOTE=请粘贴你的GitHub仓库地址(形如 https://github.com/用户名/仓库名.git):
if "%REMOTE%"=="" (
    echo 未输入地址，已退出。重新运行本文件再试。
    pause
    exit /b 1
)
git remote remove origin 2>nul
git remote add origin %REMOTE%

echo.
echo 开始推送（如弹出浏览器，请登录你的GitHub账号并授权）...
git push -u origin main

if errorlevel 1 (
    echo.
    echo 推送失败。请检查仓库地址是否正确、是否已完成浏览器授权后，重新运行本文件。
) else (
    echo.
    echo 推送成功！接下来：
    echo   1. 打开仓库页面，点 Actions 标签，等待 2-5 分钟变绿
    echo   2. 点 Settings -^> Pages，确认 Source 为 GitHub Actions
    echo   3. Pages 页顶部就是你的公开网址（https://用户名.github.io/仓库名/）
    echo   之后每天北京时间 09:00 云端自动更新，电脑关机也不影响。
)
pause
