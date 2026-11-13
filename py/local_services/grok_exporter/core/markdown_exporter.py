# -*- coding: utf-8 -*-
"""Markdown 导出。"""
from .conversation_parser import parse_conversation  # noqa: F401  (re-export convenience)


def _filter_messages(messages: list, scope: str) -> list:
    """scope: all / grok / user"""
    if scope == "grok":
        return [m for m in messages if m["sender"] == "assistant"]
    if scope == "user":
        return [m for m in messages if m["sender"] == "human"]
    return list(messages)


def render_conversation_md(session: dict, opts: dict) -> str:
    """单会话 → Markdown 文本。

    opts:
      title, time_meta, sender_label, timestamp, separator (bool)
    """
    lines = []
    if opts.get("title", True):
        lines.append(f"# {session['title']}")
        lines.append("")

    if opts.get("time_meta", True):
        lines.append(f"- 会话ID：{session['id'] or '(缺失)'}")
        lines.append(f"- 创建时间：{session['create_time']}")
        lines.append(f"- 修改时间：{session['modify_time']}")
        lines.append(f"- 消息数量：{len(session['messages'])}")
        lines.append("")

    if opts.get("separator", True):
        lines.append("---")
        lines.append("")

    scope = opts.get("scope", "all")
    filtered = _filter_messages(session["messages"], scope)

    use_sender_label = opts.get("sender_label", True)
    use_timestamp = opts.get("timestamp", True)
    use_separator = opts.get("separator", True)

    for idx, m in enumerate(filtered, 1):
        role = m["role"]
        if use_sender_label:
            heading = f"## {idx}. {role}"
        else:
            heading = f"## {idx}"
        lines.append(heading)
        lines.append("")
        if use_timestamp:
            lines.append(f"> 时间：{m['create_time']}")
            lines.append("")

        content = m["content"]
        if content:
            # 原样保留 Markdown / 代码块 / 列表 / 表格 / 引用 / 换行
            lines.append(content)
        else:
            lines.append("（此消息没有普通文本正文）")
        lines.append("")

        if use_separator:
            lines.append("---")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_merged_md(sessions_with_opts: list, merged_opts: dict) -> str:
    """多个会话拼接为一个 Markdown。merged_opts 不要求索引目录。"""
    blocks = [render_conversation_md(s, {**merged_opts, "_index": i})
              for i, s in enumerate(sessions_with_opts, 1)]
    return "\n\n\n".join(blocks).rstrip() + "\n"
