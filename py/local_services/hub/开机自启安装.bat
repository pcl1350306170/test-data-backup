@echo off
chcp 65001 >nul
rem 在 Windows 启动文件夹创建 Hub 开机自启快捷方式（pythonw 无窗口运行）
cd /d "%~dp0"

for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%P"
if not exist "%PYW%" set "PYW=pythonw.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = [Environment]::GetFolderPath('Startup'); $lk = $ws.CreateShortcut($s + '\LocalServiceHub.lnk'); $lk.TargetPath = '%PYW%'; $lk.Arguments = 'server.py'; $lk.WorkingDirectory = '%~dp0'; $lk.Description = '本地服务大厅 Hub (8700)'; $lk.Save()"

echo.
echo 已创建开机自启快捷方式：启动文件夹 \ LocalServiceHub.lnk
echo   运行方式: %PYW% server.py（无黑窗）
echo 卸载：删除该 .lnk 即可。
pause
