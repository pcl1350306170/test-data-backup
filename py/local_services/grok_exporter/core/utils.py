# -*- coding: utf-8 -*-
"""通用工具：文件名安全化、时间解析、字符清洗。"""
import re
from datetime import datetime, timezone


# Windows 文件名非法字符
_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(name: str, max_len: int = 80) -> str:
    """过滤 Windows 文件名非法字符，限制长度，空标题回退。"""
    if name is None:
        return "未命名会话"
    cleaned = _INVALID_FS_CHARS.sub("_", str(name)).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "未命名会话"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned


def parse_time(value) -> str:
    """解析 Grok 导出时间字段，支持 MongoDB $date 包装与 ISO 字符串。"""
    try:
        if isinstance(value, dict):
            num = value.get("$date", {}).get("$numberLong") if "$date" in value else None
            if num is not None:
                ms = int(num)
                dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
                return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            # 兼容 {"$date": "2024-...T..Z"} 形态
            raw = value.get("$date")
            if isinstance(raw, str):
                return _iso_or_str(raw)
        if isinstance(value, str):
            return _iso_or_str(value)
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError, TypeError, OSError):
        pass
    return "未知时间"


def _iso_or_str(raw: str) -> str:
    """ISO 字符串转本地时间；失败则原样返回。"""
    if not raw:
        return "未知时间"
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def date_prefix(value) -> str:
    """从时间字段提取 YYYY-MM-DD，失败返回当前 UTC 日期。"""
    txt = parse_time(value)
    if txt and txt != "未知时间" and len(txt) >= 10:
        return txt[:10]
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def normalize_sender(sender) -> str:
    """归一化 sender 字段：strip + lower，缺失返回 'unknown'。"""
    if sender is None:
        return "unknown"
    return str(sender).strip().lower() or "unknown"
