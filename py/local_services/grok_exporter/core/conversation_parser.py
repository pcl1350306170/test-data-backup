# -*- coding: utf-8 -*-
"""会话级解析：从 responses 数组中恢复消息顺序。"""
from .message_parser import parse_message
from .utils import parse_time


def _build_response_map(responses: list) -> dict:
    """_id -> response。重复 ID 时保留首次出现，避免覆盖。"""
    response_map = {}
    for item in responses or []:
        if not isinstance(item, dict):
            continue
        response = item.get("response")
        if not isinstance(response, dict):
            continue
        rid = response.get("_id")
        if rid is None:
            continue
        if rid in response_map:
            # 重复 ID：保留首次，丢弃后续，避免引入随机性
            continue
        response_map[rid] = response
    return response_map


def _walk_leaf_chain(response_map: dict, leaf_id) -> list:
    """从 leaf 沿 parent_response_id 回溯，反转后返回正向消息列表。
    返回 None 表示 leaf 无效，调用方应回退到时间排序。
    """
    if not leaf_id or leaf_id not in response_map:
        return None

    ordered = []
    visited = set()
    current = leaf_id
    while current and current in response_map:
        if current in visited:
            # 循环引用：截断，避免无限循环
            break
        visited.add(current)
        ordered.append(response_map[current])
        current = response_map[current].get("parent_response_id")
    ordered.reverse()
    return ordered


def _sort_by_create_time(response_map: dict) -> list:
    """无 leaf / 父链断裂时的回退策略。"""
    items = list(response_map.values())
    # parse_time 返回 "YYYY-MM-DD HH:MM:SS" 字符串，按字典序即时间序
    # "未知时间" 排到最后
    items.sort(key=lambda r: (parse_time(r.get("create_time")) == "未知时间",
                              parse_time(r.get("create_time"))))
    return items


def parse_conversation(item: dict, index: int) -> dict:
    """解析单个会话块，返回会话元数据 + 有序消息列表。

    输入结构（Grok 导出）：
      {
        "conversation": {...},
        "responses": [{"response": {...}}, ...]
      }
    """
    if not isinstance(item, dict):
        return {
            "index": index,
            "id": "",
            "title": f"会话{index}",
            "create_time": "未知时间",
            "modify_time": "未知时间",
            "summary": "",
            "leaf_response_id": None,
            "messages": [],
            "total_response_count": 0,
            "ordering_strategy": "invalid-item",
        }

    conversation = item.get("conversation") or {}
    responses = item.get("responses") or []

    title = (conversation.get("title") or "").strip() or f"会话{index}"
    leaf_id = conversation.get("leaf_response_id")

    response_map = _build_response_map(responses)

    ordered_raw = _walk_leaf_chain(response_map, leaf_id)
    if ordered_raw is None:
        ordered_raw = _sort_by_create_time(response_map)
        strategy = "create_time_fallback"
    else:
        # leaf 链只能拿到主链；如果 response_map 中还有未访问的，记一下
        strategy = "leaf_chain" if len(ordered_raw) == len(response_map) else "leaf_chain_partial"

    messages = [parse_message(r) for r in ordered_raw]

    return {
        "index": index,
        "id": conversation.get("id", "") or "",
        "title": title,
        "create_time": parse_time(conversation.get("create_time")),
        "modify_time": parse_time(conversation.get("modify_time")),
        "create_time_raw": conversation.get("create_time"),
        "summary": conversation.get("summary") or "",
        "leaf_response_id": leaf_id,
        "messages": messages,
        "total_response_count": len(response_map),
        "ordering_strategy": strategy,
    }


def parse_all(data: dict) -> list:
    """解析顶层 JSON，返回会话列表。"""
    conversations = data.get("conversations") if isinstance(data, dict) else None
    if not isinstance(conversations, list):
        return []
    return [parse_conversation(item, i) for i, item in enumerate(conversations, 1)]


def summarize(sessions: list) -> dict:
    """统计概览：会话数 / 消息数 / 用户消息数 / Grok 消息数。"""
    total_msgs = 0
    human_msgs = 0
    grok_msgs = 0
    for s in sessions:
        for m in s["messages"]:
            total_msgs += 1
            if m["sender"] == "human":
                human_msgs += 1
            elif m["sender"] == "assistant":
                grok_msgs += 1
    return {
        "conversation_count": len(sessions),
        "message_count": total_msgs,
        "human_count": human_msgs,
        "grok_count": grok_msgs,
    }
