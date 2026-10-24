@echo off
chcp 65001 >nul
title 一键上云：电脑配件价格看板
cd /d %~dp0
set "GH=%~dp0tools\bin\gh.exe"

echo ============================================
echo    一键上云（云端自动更新，电脑关机也跑）
echo    全程只需: 在浏览器里登录一次 GitHub
echo ============================================
echo.

echo [1/5] 检查登录状态...
"%GH%" auth status >nul 2>&1
if errorlevel 1 (
    echo.
    echo   即将打开浏览器登录 GitHub，注意:
    echo   1. 先记下本窗口显示的一次性代码
    echo   2. 按回车后会自动打开浏览器
    echo   3. 没有账号就点 Sign up 注册，有邮箱即可，免费
    echo   4. 登录后输入那个代码，点授权
    echo.
    pause
    "%GH%" auth login --hostname github.com --git-protocol https --web
    if errorlevel 1 (
        echo 登录没有完成，重新双击本文件再试一次。
        pause
        exit /b 1
    )
)
"%GH%" auth setup-git >nul 2>&1

echo [2/5] 准备文件...
if not exist .git git init -b main >nul
git config user.name "price-bot"
git config user.email "price-bot@users.noreply.github.com"
git add -A
git diff --cached --quiet || git commit -m "电脑配件价格看板" >nul
git remote remove origin >nul 2>&1

echo [3/5] 创建仓库并推送...
set "GHUSER="
for /f "usebackq delims=" %%i in (`"%GH%" api user --jq login`) do set "GHUSER=%%i"
if "%GHUSER%"=="" (
    echo 没有取到用户名，登录似乎没成功，请重新双击本文件。
    pause
    exit /b 1
)
"%GH%" repo create pc-price-tracker --public --source=. --remote=origin --push >nul 2>&1
if errorlevel 1 (
    git remote add origin https://github.com/%GHUSER%/pc-price-tracker.git
    git push -u origin main
)
if errorlevel 1 (
    echo 推送失败。把本窗口的错误信息截图发给助手即可解决。
    pause
    exit /b 1
)

echo [4/5] 已推送成功，云端开始首次构建...
echo   进度可在这里看: https://github.com/%GHUSER%/pc-price-tracker/actions
start "" "https://github.com/%GHUSER%/pc-price-tracker/actions"

echo [5/5] 等待云端发布完成（首次约3-8分钟，窗口不要关）...
set "PAGE=https://%GHUSER%.github.io/pc-price-tracker/"
for /l %%n in (1,1,60) do (
    curl -sf -o nul -m 10 "%PAGE%" && goto :done
    timeout /t 10 /nobreak >nul
)
echo   等待超时也没关系，几分钟后再打开下面的网址即可。

:done
start "" "%PAGE%"
echo.
echo ============================================
echo   完成！你的永久公开看板:
echo   %PAGE%
echo   以后每天北京时间 09:00 云端自动更新，
echo   电脑关机完全不影响。
echo   云端正常后，可双击 stop_all_local.bat
echo   停掉本机的后台任务。
echo ============================================
pause
