@echo off
chcp 65001 >nul
echo ========================================
echo   有声绘本视频生成工具 - 依赖检查
echo ========================================
echo.

echo [1/3] 检查 python-vlc...
python -c "import vlc; print('✅ python-vlc 已安装')" 2>nul
if errorlevel 1 (
    echo ❌ python-vlc 未安装
    echo.
    echo 正在安装 python-vlc...
    pip install python-vlc -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo.
        echo ❌ 安装失败，请手动运行: pip install python-vlc
        pause
        exit /b 1
    )
    echo ✅ python-vlc 安装成功
)
echo.
echo ⚠️ 重要提示：还需要安装 VLC 播放器软件！
echo    下载地址: https://www.videolan.org/vlc/
echo.

echo [2/3] 检查 Pillow...
python -c "from PIL import Image; print('✅ Pillow 已安装')" 2>nul
if errorlevel 1 (
    echo ❌ Pillow 未安装
    echo.
    echo 正在安装 Pillow...
    pip install Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo.
        echo ❌ 安装失败，请手动运行: pip install Pillow
        pause
        exit /b 1
    )
    echo ✅ Pillow 安装成功
)
echo.

echo [3/3] 检查 moviepy...
python -c "import moviepy; print('✅ moviepy 版本:', moviepy.__version__)" 2>nul
if errorlevel 1 (
    echo ❌ moviepy 未安装
    echo.
    echo 正在安装 moviepy...
    pip install moviepy -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo.
        echo ❌ 安装失败，请手动运行: pip install moviepy
        pause
        exit /b 1
    )
    echo ✅ moviepy 安装成功
)
echo.

echo ========================================
echo   ✅ 所有依赖检查完成！
echo ========================================
echo.
echo 正在启动有声绘本视频生成工具...
echo.

start pythonw audiobook_video_generator.pyw

echo.
echo 🎉 工具已启动！
echo.
echo 提示：
echo 1. 选择图片文件夹和音频文件
echo 2. 点击 "🎯 交互式编辑" 按钮
echo 3. 边听音频边点击图片标记时间轴
echo 4. 保存后生成视频
echo.
echo ⚠️ 注意：如果提示缺少 VLC，请先安装 VLC 播放器
echo    下载: https://www.videolan.org/vlc/
echo.
pause
