@echo off
chcp 65001 >nul 2>&1
title 本地播客制作系统
echo ========================================
echo   本地播客制作系统 - 启动中...
echo   访问地址: http://localhost:8642
echo   按 Ctrl+C 停止服务
echo ========================================
echo.

cd /d "%~dp0"

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 检查依赖
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] 首次运行，安装依赖...
    pip install -r requirements.txt
    echo.
)

:: 启动服务
python server.py
pause
