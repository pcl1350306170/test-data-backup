"""
公共日志模块 - log_utils.py
=============================
所有 py/ 下的脚本均可通过 try/except 优雅引入日志功能。
导入失败时脚本照常运行，不影响任何业务逻辑。

存储结构:
    py/logs/
        2026-07/
            image_cropper_2026-07-21.log
            script_launcher_2026-07-21.log

清理机制:
    - 每次初始化 logger 时自动扫描并删除超过保留天数（默认30天）的日志文件
    - 按月分目录，避免单目录文件过多

用法:
    try:
        from log_utils import get_logger
        logger = get_logger()          # 自动使用脚本名
        # 或 logger = get_logger("my_script")  # 指定名称
    except Exception:
        class _Dummy:
            def info(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def error(self, *a, **kw): pass
            def debug(self, *a, **kw): pass
        logger = _Dummy()
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────── 配置 ────────────────────
LOG_BASE_DIR = Path(__file__).parent / "logs"   # py/logs/
RETENTION_DAYS = 30                              # 日志保留天数
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
# ──────────────────────────────────────────────

# 已创建的 logger 缓存，避免同一脚本重复添加 handler
_logger_cache: dict[str, logging.Logger] = {}


def _get_script_name() -> str:
    """自动从调用栈获取脚本名（不含扩展名）"""
    # 取栈顶第一个不在 log_utils.py 里的帧
    frame = sys._getframe(2)
    filepath = frame.f_globals.get("__file__", None)
    if filepath:
        return Path(filepath).stem
    return "unknown_script"


def _cleanup_old_logs():
    """删除超过 RETENTION_DAYS 的日志文件及空目录"""
    if not LOG_BASE_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    deleted_files = 0
    deleted_dirs = 0

    for month_dir in LOG_BASE_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        for log_file in month_dir.glob("*.log"):
            try:
                # 从文件名解析日期: scriptname_YYYY-MM-DD.log
                date_part = log_file.stem.rsplit("_", 1)[-1]
                file_date = datetime.strptime(date_part, "%Y-%m-%d")
                if file_date < cutoff:
                    log_file.unlink()
                    deleted_files += 1
            except (ValueError, IndexError):
                # 文件名不符合规则，跳过不删
                pass

        # 目录为空则删除
        try:
            if not any(month_dir.iterdir()):
                month_dir.rmdir()
                deleted_dirs += 1
        except OSError:
            pass

    if deleted_files > 0:
        print(f"[log_utils] 已清理 {deleted_files} 个过期日志文件，{deleted_dirs} 个空目录")


def get_logger(name: str | None = None, level: int = logging.DEBUG) -> logging.Logger:
    """
    获取日志记录器。

    参数:
        name:  logger 名称，None 时自动取调用脚本的文件名
        level: 日志级别，默认 DEBUG

    返回:
        logging.Logger 实例（同时输出到文件和控制台）

    异常:
        如果日志目录无法创建，抛出 OSError（调用方用 try/except 捕获即可）
    """
    if name is None:
        name = _get_script_name()

    # 命中缓存直接返回
    if name in _logger_cache:
        return _logger_cache[name]

    # 确保日志目录存在
    today_str = datetime.now().strftime("%Y-%m")
    log_dir = LOG_BASE_DIR / today_str
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志文件: py/logs/2026-07/image_cropper_2026-07-21.log
    day_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{name}_{day_str}.log"

    # 构建 logger
    logger = logging.getLogger(f"script.{name}")
    logger.setLevel(level)
    logger.propagate = False

    # 避免重复添加 handler（多次调用 get_logger 时）
    if not logger.handlers:
        # 文件 handler（UTF-8，追加模式）
        fh = logging.FileHandler(str(log_file), encoding="utf-8", mode="a")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(fh)

        # 控制台 handler（仅 INFO 及以上，.pyw 无控制台时静默忽略）
        try:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.INFO)
            ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
            logger.addHandler(ch)
        except Exception:
            pass  # .pyw 无控制台时忽略

    _logger_cache[name] = logger

    # 每次新建 logger 时触发清理（异步，不阻塞主流程）
    try:
        _cleanup_old_logs()
    except Exception:
        pass  # 清理失败不影响正常使用

    logger.debug(f"── 日志开始: {name} ── 文件: {log_file}")
    return logger
