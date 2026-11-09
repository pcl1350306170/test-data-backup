@echo off
chcp 65001 >nul
cd /d %~dp0

set "PY=python"
python -c "import uvicorn, fastapi" >nul 2>&1
if errorlevel 1 (
    py -3 -c "import uvicorn, fastapi" >nul 2>&1
    if errorlevel 1 (
        echo [错误] 未找到可用的 Python（需要 fastapi/uvicorn 依赖）
        echo 请先安装依赖：python -m pip install fastapi uvicorn
        pause
        exit /b 1
    )
    set "PY=py -3"
)

echo ====================================
echo   正在启动 语音速记本 服务...
echo   本机访问: http://127.0.0.1:8010
echo   关闭本窗口即停止服务
echo ====================================
%PY% main.py
pause
