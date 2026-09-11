# ============================================================
# wsl_monthly_backup.ps1
# 运行环境：Windows（PowerShell）
# 功能：每月自动备份整个 WSL 发行版镜像（wsl --export 导出 tar）
# 输出目录：D:\FILES\IMG\AI自定义\WSL
# 保留策略：自动保留最近 2 份，清理更早的备份
# 推荐定时：每月 1 号 03:00（任务计划程序）
#
# 手动执行一次：
#   powershell -ExecutionPolicy Bypass -File "D:\CODE\Python\test-data-backup\AI Work Space\WSL\wsl_monthly_backup.ps1"
# 注册定时任务（每月 1 号 03:00）：
#   powershell -ExecutionPolicy Bypass -File "D:\CODE\Python\test-data-backup\AI Work Space\WSL\wsl_monthly_backup.ps1" -Install
# 说明：整机镜像备份使用 wsl --export，无需 SSH；备份期间 WSL 发行版保持运行也可导出，
#       但为保证数据一致性，建议备份前先手动关闭该发行版（wsl --terminate <发行版名>）。
# ============================================================

param([switch]$Install)

$BackupDir = "D:\FILES\IMG\AI自定义\WSL"
$KeepCount = 2
$LogFile   = Join-Path $BackupDir "backup.log"

# ---------- 安装模式：注册任务计划（每月 1 号 03:00） ----------
if ($Install) {
    $TaskName = "WSL每月整机备份"
    $ScriptPath = $PSCommandPath

    # 删除同名旧任务，避免重复
    schtasks.exe /Delete /TN $TaskName /F 2>$null | Out-Null

    # 注：PowerShell 5.1 的 New-ScheduledTaskTrigger 不支持 -Monthly，改用 schtasks 注册
    $cmdLine = 'schtasks /Create /TN "' + $TaskName + '" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"' + $ScriptPath + '\"" /SC MONTHLY /D 1 /ST 03:00 /F'
    cmd /c $cmdLine
    if ($LASTEXITCODE -ne 0) {
        Write-Host "注册任务计划失败，请手动执行: $cmdLine"
        exit 1
    }

    Write-Host "已注册任务计划: $TaskName（每月 1 号 03:00）"
    exit 0
}

# ---------- 备份主流程 ----------
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

# 获取发行版名称（取第一个非空行）
# 注意：wsl.exe 输出 UTF-16 编码，PowerShell 5.1 按 ANSI 解码时会在每个字符后混入 NUL(\0)，
# 必须清除，否则 wsl.exe --export 无法识别发行版名（直接打印 usage 失败）。
$distro = ((wsl.exe --list --quiet | Where-Object { $_.Trim() -ne "" } | Select-Object -First 1).Trim()) -replace "`0", ""
if (-not $distro) {
    $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 错误：未找到任何 WSL 发行版"
    Add-Content -Path $LogFile -Value $msg
    Write-Host $msg
    exit 1
}

$stamp      = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupFile = Join-Path $BackupDir "wsl-$distro-$stamp.tar"

# 注意：wsl.exe --export 不支持含中文的路径（会直接打印 usage 导致失败），
# 因此先导出到纯 ASCII 临时路径，完成后再移动到目标目录。
$TempDir  = Join-Path $env:TEMP "wsl-backup-tmp"
$TempFile = Join-Path $TempDir "wsl-$distro-$stamp.tar"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

Write-Host "开始导出发行版: $distro -> $TempFile"
Add-Content -Path $LogFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 开始导出: $distro"

wsl.exe --export $distro $TempFile
if ($LASTEXITCODE -ne 0) {
    $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 导出失败: $distro"
    Add-Content -Path $LogFile -Value $msg
    Write-Host $msg
    Remove-Item -Path $TempFile -Force -ErrorAction SilentlyContinue
    exit 1
}

# 移动到最终备份目录（跨盘符移动 = 复制后删除，耗时与磁盘读写相关）
Move-Item -Path $TempFile -Destination $BackupFile -Force
if (-not (Test-Path $BackupFile)) {
    $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 移动备份文件到目标目录失败"
    Add-Content -Path $LogFile -Value $msg
    Write-Host $msg
    exit 1
}

$sizeMB = [math]::Round((Get-Item $BackupFile).Length / 1MB, 1)
$msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 备份成功: $BackupFile (${sizeMB} MB)"
Add-Content -Path $LogFile -Value $msg
Write-Host $msg

# 清理旧备份，只保留最近 $KeepCount 份
Get-ChildItem -Path $BackupDir -Filter "wsl-$distro-*.tar" |
    Sort-Object Name -Descending |
    Select-Object -Skip $KeepCount |
    ForEach-Object {
        Remove-Item -Path $_.FullName -Force
        Add-Content -Path $LogFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 清理旧备份: $($_.Name)"
    }

Write-Host "本次备份完成"
