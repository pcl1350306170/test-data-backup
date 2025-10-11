@echo off
chcp 65001 >nul
title 🐍 Python 脚本启动器
setlocal enabledelayedexpansion

:: 设置 Python 路径和脚本目录
set PYTHON=D:\tools\python\python.exe
set SCRIPT_DIR=E:\www\test\py

:: 菜单
echo ==============================
echo        Python 工具箱
echo ==============================
echo  1. 批量下载图片（multi_image_downloader.py）
echo ==============================
echo  2. 裁剪图片【生成新文件】（crop_logo_recursive.py）
echo ==============================
echo  3. 裁剪并替换原图【单任务】（crop_logo_recursive_replace.py）
echo ==============================
echo  4. 图片裁剪任务并替换原图【批量任务】（crop_logo_advanced.py）
echo ==============================
echo  5. 替换txt文件（text_restore.py）
echo ==============================
echo  6. 从A目录复制X张图片到B目录（random_copy_vertical_images.py）
echo ==============================
echo [Q] 退出
echo ==============================

:menu
set /p choice=请输入要运行的脚本编号（或 Q 退出）：

if /I "%choice%"=="1" (
    echo 正在执行：批量下载图片...
    "%PYTHON%" "%SCRIPT_DIR%\multi_image_downloader.py"
    goto end
)
if /I "%choice%"=="2" (
    echo 正在执行：裁剪图片...
    "%PYTHON%" "%SCRIPT_DIR%\crop_logo_recursive.py"
    goto end
)
if /I "%choice%"=="3" (
    echo 正在执行：裁剪替换图片...
    "%PYTHON%" "%SCRIPT_DIR%\crop_logo_recursive_replace.py"
    goto end
)
if /I "%choice%"=="4" (
    echo 正在执行：高级裁剪任务...
    "%PYTHON%" "%SCRIPT_DIR%\crop_logo_advanced.py"
    goto end
)
if /I "%choice%"=="5" (
    echo 正在执行：替换txt文件...
    "%PYTHON%" "%SCRIPT_DIR%\text_restore.py"
    goto end
)
if /I "%choice%"=="6" (
    echo 正在执行：从A目录复制X张图片到B目录...
    "%PYTHON%" "%SCRIPT_DIR%\random_copy_vertical_images.py"
    goto end
)
if /I "%choice%"=="Q" (
    echo 已退出。
    exit /b
)

echo 无效的选项，请重新输入。
goto menu

:end
echo.
pause
