@echo off
chcp 65001 >nul
echo ============================================
echo   生成语音速记本自签证书（有效期 10 年）
echo ============================================
echo.

:: 检测 openssl 是否可用
set "OPENSSL_CMD=openssl"
where openssl >nul 2>&1
if %errorlevel% neq 0 (
    :: 尝试 Git for Windows 内置的 openssl
    if exist "C:\Program Files\Git\usr\bin\openssl.exe" (
        set "OPENSSL_CMD=C:\Program Files\Git\usr\bin\openssl.exe"
    ) else (
        echo [错误] 未找到 openssl，请确保 Git for Windows 已安装
        echo         或手动安装 OpenSSL 并加入 PATH
        pause
        exit /b 1
    )
)

:: 删除旧证书
if exist cert.pem del cert.pem
if exist key.pem del key.pem

:: 生成自签证书（包含 IP 和 localhost）
"%OPENSSL_CMD%" req -x509 -newkey rsa:2048 ^
    -keyout key.pem -out cert.pem ^
    -days 3650 -nodes ^
    -subj "/CN=VoiceNotes" ^
    -addext "subjectAltName=IP:192.168.3.88,IP:127.0.0.1,DNS:localhost"

if %errorlevel% neq 0 (
    echo [错误] 证书生成失败
    pause
    exit /b 1
)

echo.
echo [成功] 证书已生成：
echo   cert.pem （公钥/证书）
echo   key.pem  （私钥）
echo.
echo 现在重启 main.py 即可启用 HTTPS。
echo 手机首次访问 https://192.168.3.88:8010 时需点"继续前往"信任证书。
echo.
pause
