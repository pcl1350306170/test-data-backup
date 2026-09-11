#!/bin/bash
# ============================================================
# mysql_weekly_backup.sh
# 运行环境：WSL 内部（Linux bash）
# 功能：每周自动备份 MySQL 全部数据库（mysqldump + gzip 压缩）
# 保留策略：自动保留最近 5 份，清理更早的备份
# 推荐定时：每周日 02:00（cron）
#
# 安装定时任务（在 WSL 内执行一次）：
#   bash /mnt/d/CODE/Python/test-data-backup/AI\ Work\ Space/WSL/mysql_weekly_backup.sh --install
# 手动执行一次：
#   bash /mnt/d/CODE/Python/test-data-backup/AI\ Work\ Space/WSL/mysql_weekly_backup.sh
# 备份与日志输出位置：/root/mysql-backup/
# ============================================================

MYSQL_USER="dev_user"
MYSQL_PASSWORD="123456"
BACKUP_DIR="/root/mysql-backup"
KEEP_COUNT=5
LOG_FILE="$BACKUP_DIR/backup.log"

# ---------- 安装模式：注册 cron 定时任务（每周日 02:00） ----------
if [ "$1" = "--install" ]; then
    # 先复制到 WSL 内部固定路径，避免 Windows 路径带空格导致 cron 解析失败
    INSTALL_PATH="/usr/local/bin/mysql_weekly_backup.sh"
    cp "$0" "$INSTALL_PATH"
    chmod +x "$INSTALL_PATH"

    CRON_LINE="0 2 * * 0 /bin/bash $INSTALL_PATH >/dev/null 2>&1"
    ( crontab -l 2>/dev/null | grep -v 'mysql_weekly_backup.sh'; echo "$CRON_LINE" ) | crontab -

    echo "已注册 cron 任务：每周日 02:00 执行 $INSTALL_PATH"
    echo "当前 crontab 内容："
    crontab -l
    echo
    echo "注意：cron 仅在 WSL 运行时生效，若 WSL 长期不启动请保持 WSL 随 Windows 启动。"
    exit 0
fi

# ---------- 备份主流程 ----------
mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/mysql-${STAMP}.sql.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始备份 MySQL 全部数据库 ..." >> "$LOG_FILE"

# --all-databases 全库；--single-transaction InnoDB 一致性快照；--routines/--triggers 保留存储过程与触发器
if mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --all-databases --single-transaction --routines --triggers --hex-blob 2>>"$LOG_FILE" | gzip > "$BACKUP_FILE"; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份成功: $BACKUP_FILE (${SIZE})" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份失败，已删除残留文件" >> "$LOG_FILE"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 清理旧备份，只保留最近 KEEP_COUNT 份
ls -1t "$BACKUP_DIR"/mysql-*.sql.gz 2>/dev/null | tail -n +$((KEEP_COUNT+1)) | while IFS= read -r old; do
    rm -f "$old"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理旧备份: $old" >> "$LOG_FILE"
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 本次备份完成" >> "$LOG_FILE"
exit 0
