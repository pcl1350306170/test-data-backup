@echo off
chcp 65001 >nul 2>&1
title CosyVoice TTS Web 服务
cd /d "%~dp0"
echo ============================================
echo   CosyVoice TTS Web 服务
echo   正在启动...
echo ============================================
python server.py
pause
