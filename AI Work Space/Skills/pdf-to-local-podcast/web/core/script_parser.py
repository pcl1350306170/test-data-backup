# -*- coding: utf-8 -*-
"""解析播客脚本(.md) → 任务清单。

从现有 parse_script.py 抽取核心逻辑，供 Web 后端直接调用。
脚本格式契约见 ../references/script-format.md。
"""
import os
import re

from . import voice_manager

# 台词块行：[音色名] 台词内容
BLOCK_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.+?)\s*$")
# 段标题：【第N段 标题】
SECTION_RE = re.compile(r"^\s*【.*?】\s*$")
# 信息键值行
INFO_RE = re.compile(r"^\s*([^：:]{1,20})[：:]\s*(.+?)\s*$")


def parse_script(md_path, voice_names=None):
    """解析播客脚本。

    Args:
        md_path: 脚本 .md 文件路径
        voice_names: 合法音色名集合，None 则用 voice_manager 中全部音色

    Returns:
        (info_dict, blocks, warnings)
        blocks: [{"idx": int, "voice": str, "text": str}]
    """
    if voice_names is None:
        voice_names = set(voice_manager.get_all().keys())

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    info = {}
    blocks = []
    warnings = []
    in_body = False
    pending_voice = None
    pending_text = []

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line == "---":
            in_body = True
            continue

        # 头部区
        if not in_body:
            m = INFO_RE.match(line)
            if m:
                info[m.group(1)] = m.group(2)
            continue

        # 注释
        if line.startswith("#"):
            continue

        # 段标题：冲刷当前块（打断跨段同角色合并）
        if SECTION_RE.match(line):
            if pending_voice is not None:
                blocks.append({
                    "idx": len(blocks) + 1,
                    "voice": pending_voice,
                    "text": "".join(pending_text),
                })
                pending_voice = None
                pending_text = []
            continue

        m = BLOCK_RE.match(line)
        if m:
            voice = m.group(1)
            text = m.group(2)
            if voice not in voice_names:
                raise ValueError(
                    "第%d行：音色名「%s」不在音色表中（可用：%s）"
                    % (lineno, voice, "、".join(sorted(voice_names)))
                )
            if pending_voice == voice:
                pending_text.append(text)
            else:
                if pending_voice is not None:
                    blocks.append({
                        "idx": len(blocks) + 1,
                        "voice": pending_voice,
                        "text": "".join(pending_text),
                    })
                pending_voice = voice
                pending_text = [text]
        else:
            warnings.append("第%d行：无法识别（已跳过）：%s" % (lineno, raw[:60]))

    if pending_voice is not None:
        blocks.append({
            "idx": len(blocks) + 1,
            "voice": pending_voice,
            "text": "".join(pending_text),
        })

    if not blocks:
        hint = ""
        if "---" not in lines:
            hint = "（文件缺少 --- 分隔行）"
        raise ValueError(
            "脚本中未解析到任何台词块%s，请检查标注格式（[音色名] 台词）" % hint
        )

    return info, blocks, warnings


def estimate_duration(blocks):
    """估算成品时长（秒）。

    基于本地 CosyVoice 实测：100 字 ≈ 22 秒（含 400ms 块间静音）。
    公式：成品秒数 ≈ 字数 × 0.212 + 块数 × 0.4
    """
    total_chars = sum(len(b["text"]) for b in blocks)
    num_blocks = len(blocks)
    return total_chars * 0.212 + num_blocks * 0.4


def parse_preview(md_path):
    """预解析：返回摘要信息（块数、字数、预估时长），不校验音色。"""
    voices = voice_manager.get_all()
    try:
        info, blocks, warnings = parse_script(md_path, set(voices.keys()))
    except ValueError:
        # 音色不匹配时也尝试宽松解析
        info, blocks, warnings = _parse_loose(md_path)

    total_chars = sum(len(b["text"]) for b in blocks)
    est_sec = estimate_duration(blocks)
    return {
        "book": info.get("书名", os.path.basename(md_path)),
        "total_chars": total_chars,
        "total_blocks": len(blocks),
        "estimated_sec": round(est_sec, 1),
        "estimated_min": round(est_sec / 60, 1),
        "warnings": warnings,
        "voices_used": list(set(b["voice"] for b in blocks)),
    }


def _parse_loose(md_path):
    """宽松解析：不校验音色名，用于预览。"""
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    info = {}
    blocks = []
    warnings = []
    in_body = False
    pending_voice = None
    pending_text = []

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line == "---":
            in_body = True
            continue
        if not in_body:
            m = INFO_RE.match(line)
            if m:
                info[m.group(1)] = m.group(2)
            continue
        if line.startswith("#"):
            continue
        if SECTION_RE.match(line):
            if pending_voice is not None:
                blocks.append({
                    "idx": len(blocks) + 1,
                    "voice": pending_voice,
                    "text": "".join(pending_text),
                })
                pending_voice = None
                pending_text = []
            continue
        m = BLOCK_RE.match(line)
        if m:
            voice = m.group(1)
            text = m.group(2)
            if pending_voice == voice:
                pending_text.append(text)
            else:
                if pending_voice is not None:
                    blocks.append({
                        "idx": len(blocks) + 1,
                        "voice": pending_voice,
                        "text": "".join(pending_text),
                    })
                pending_voice = voice
                pending_text = [text]
        else:
            warnings.append("第%d行：无法识别（已跳过）" % lineno)

    if pending_voice is not None:
        blocks.append({
            "idx": len(blocks) + 1,
            "voice": pending_voice,
            "text": "".join(pending_text),
        })

    return info, blocks, warnings
