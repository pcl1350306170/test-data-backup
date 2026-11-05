# WSL 保活：每 5 分钟检查 Ubuntu 是否在运行，不在就拉起常驻客户端
$out = (wsl -l --running 2>&1 | Out-String)
if ($out -notmatch 'Ubuntu') {
    Start-Process wsl.exe -ArgumentList '-e bash -lc "sleep infinity"' -WindowStyle Hidden
}