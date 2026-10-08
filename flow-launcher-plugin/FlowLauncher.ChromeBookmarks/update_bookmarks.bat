@echo off
chcp 65001 >nul
setlocal

set "PLUGIN_DIR=%~dp0"
set "TARGET=%PLUGIN_DIR%bookmarks.html"

if "%~1"=="" (
    echo 用法：将 Chrome 导出的书签 HTML 文件拖拽到此脚本上
    echo 或者在命令行中运行: update_bookmarks.bat ^<书签文件路径^>
    pause
    exit /b 1
)

copy /y "%~1" "%TARGET%" >nul
echo 书签已更新: %~nx1
echo 目标: %TARGET%
timeout /t 2 >nul
