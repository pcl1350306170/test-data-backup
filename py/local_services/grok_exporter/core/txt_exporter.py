# -*- coding: utf-8 -*-
"""TXT 导出：可读纯文本结构，可选剥离 Markdown 标记。"""
import re


SEP_MAJOR = "=" * 40
SEP_MINOR = "-" * 40

_FENCE = re.compile(r"^\s*```")
_INLINE_CODE = re.compile(r"`[^`]+`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_QUOTE = re.compile(r"^\s{0,3}>\s?")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.DOTALL)
_ITALIC = re.compile(r"(?<![\*_])([*_])(?!\s)(.+?)(?<!\s)\1(?![\*_])", re.DOTALL)
_LIST_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_LIST_ORDER = re.compile(r"^(\s*)(\d+)\.\s+")


def md_to_plain(text: str) -> str:
    """保守地把 Markdown 转纯文本：保留代码块内容、保留语义。"""
    if not text:
        return text
    out_lines = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            out_lines.append("")  # 代码块边界本身在 TXT 里没必要保留
            continue
        if in_fence:
            out_lines.append(line)
            continue

        stripped = line
        stripped = _HEADING.sub("", stripped)
        stripped = _QUOTE.sub("", stripped)
        if _HR.match(stripped):
            out_lines.append("")
            continue
        stripped = _LIST_BULLET.sub(lambda m: m.group(1) + "· ", stripped)
        stripped = _LIST_ORDER.sub(lambda m: f"{m.group(1)}{m.group(2)}. ", stripped)
        stripped = _IMAGE.sub(lambda m: f"[图片: {m.group(1) or '未命名'}]", stripped)
        stripped = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", stripped)
        stripped = _BOLD.sub(lambda m: m.group(2), stripped)
        stripped = _ITALIC.sub(lambda m: m.group(2), stripped)
        out_lines.append(stripped)

    # 收敛 3+ 连续空行为 2
    joined = "\n".join(out_lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def _filter_messages(messages: list, scope: str) -> list:
    if scope == "grok":
        return [m for m in messages if m["sender"] == "assistant"]
    if scope == "user":
        return [m for m in messages if m["sender"] == "human"]
    return list(messages)


def render_conversation_txt(session: dict, opts: dict) -> str:
    """单会话 → TXT。"""
    lines = [SEP_MAJOR, session["title"], SEP_MAJOR, ""]

    if opts.get("time_meta", True):
        lines.append(f"会话 ID：{session['id'] or '(缺失)'}")
        lines.append(f"创建时间：{session['create_time']}")
        lines.append(f"修改时间：{session['modify_time']}")
        lines.append(f"消息数量：{len(session['messages'])}")
        lines.append("")

    scope = opts.get("scope", "all")
    filtered = _filter_messages(session["messages"], scope)
    preserve_md = opts.get("preserve_markdown", False)

    for m in filtered:
        head = f"【{m['role']}】"
        if opts.get("timestamp", True):
            head += m["create_time"]
        lines.append(SEP_MINOR)
        lines.append(head)
        lines.append(SEP_MINOR)
        lines.append("")
        content = m["content"] or "（此消息没有普通文本正文）"
        if not preserve_md:
            content = md_to_plain(content) or "（空）"
        lines.append(content)
        lines.append("")

    lines.append(SEP_MAJOR)
    return "\n".join(lines).rstrip() + "\n"


def render_merged_txt(sessions: list, merged_opts: dict) -> str:
    """多会话拼接为单 TXT。不生成索引。"""
    blocks = [render_conversation_txt(s, merged_opts) for s in sessions]
    return "\n\n".join(blocks).rstrip() + "\n"
