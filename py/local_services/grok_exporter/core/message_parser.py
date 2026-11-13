# -*- coding: utf-8 -*-
"""消息级解析：sender 归一化、内容提取、时间转换。"""
from .utils import normalize_sender, parse_time


ROLE_LABEL = {
    "human": "用户",
    "assistant": "Grok",
}


def parse_message(response: dict) -> dict:
    """将单条 response 归一化为可读消息字典。"""
    if not isinstance(response, dict):
        return {
            "id": None,
            "parent_id": None,
            "sender": "unknown",
            "role": "未知",
            "content": "",
            "create_time": "未知时间",
            "raw": {},
        }

    sender_raw = response.get("sender")
    sender = normalize_sender(sender_raw)
    role = ROLE_LABEL.get(sender, sender_raw or "unknown")

    content = response.get("message")
    if content is None:
        content = ""
    elif not isinstance(content, str):
        content = str(content)

    return {
        "id": response.get("_id"),
        "parent_id": response.get("parent_response_id"),
        "sender": sender,
        "sender_raw": sender_raw,
        "role": role,
        "content": content,
        "create_time": parse_time(response.get("create_time")),
        "create_time_raw": response.get("create_time"),
        "model": response.get("model", "") or "",
        "raw": response,
    }
