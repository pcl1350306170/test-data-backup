# -*- coding: utf-8 -*-
"""JSON 加载：UTF-8 / UTF-8-BOM 自动嗅探，不假定 GBK。"""
import json
from pathlib import Path


class JsonLoadError(Exception):
    """JSON 加载失败的统一异常。"""


def load_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise JsonLoadError(f"文件不存在：{p}")
    if not p.is_file():
        raise JsonLoadError(f"不是有效文件：{p}")

    size = p.stat().st_size
    if size == 0:
        raise JsonLoadError(f"文件为空：{p}")

    raw = p.read_bytes()
    # 优先 UTF-8 BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JsonLoadError(
                f"非 UTF-8 编码，请确认导出文件编码：{exc.reason}"
            ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonLoadError(f"JSON 解析失败（行 {exc.lineno}，列 {exc.colno}）：{exc.msg}") from exc

    if not isinstance(data, dict):
        raise JsonLoadError("顶层结构不是对象，无法识别 Grok 导出格式")
    return data
