@echo off
chcp 65001 >nul
cd /d %~dp0
python -c "import uvicorn, fastapi" >nul 2>&1
if errorlevel 1 (
    echo [提示] 当前 Python 缺少 fastapi/uvicorn 依赖，正在自动安装...
    python -m pip install fastapi uvicorn -q
)
echo ====================================
echo   正在启动 语音速记本 服务...
echo   本机访问: http://127.0.0.1:8010
echo   关闭本窗口即停止服务
echo ====================================
python main.py
pause
