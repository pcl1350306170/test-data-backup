@echo off
chcp 65001 >nul 2>&1
title 本地服务大厅 Hub
cd /d "%~dp0"
echo ============================================
echo   本地服务大厅 Hub
echo   本机访问: http://127.0.0.1:8700
echo   关闭本窗口即停止 Hub（不影响已启动的服务）
echo ============================================
python server.py
pause
