@echo off
title 本地AI小说服务
echo ==========================================
echo   本地AI小说服务 正在启动...
echo   服务地址: http://127.0.0.1:8000
echo   停止服务: 关闭本窗口 (Ctrl+C)
echo ==========================================
rem 检查 Ollama 是否已运行，未运行则自动启动
curl -s --max-time 3 http://127.0.0.1:11434/api/version >nul 2>nul
if errorlevel 1 (
  echo   [自动] Ollama 未运行，正在启动...
  start "" /min "C:\Users\PCL13\AppData\Local\Programs\Ollama\ollama.exe" serve
  timeout /t 6 /nobreak >nul
)
cd /d "D:\CODE\Python\test-data-backup\py\novel_agent"
"D:\dev\python\python.exe" main.py
pause