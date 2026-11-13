@echo off
chcp 65001 >nul 2>&1
title 病房订单打包 Web 服务
cd /d "%~dp0"
echo ============================================
echo   病房订单打包 Web 服务
echo   http://127.0.0.1:8803
echo ============================================
python server.py
pause
