# -*- coding: utf-8 -*-
"""解析播客脚本(.md) -> 任务清单(.json)。

播客脚本格式契约见 ../references/script-format.md。
本脚本按契约解析，未知音色名会报错退出（避免生成时漏词）。

用法：
    python parse_script.py 播客脚本.md [--out 任务清单.json]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voices import VOICE_TABLE  # noqa: E402

# 台词块行：[音色名] 台词内容
BLOCK_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.+?)\s*$")
# 段标题：【第N段 标题】
SECTION_RE = re.compile(r"^\s*【.*?】\s*$")
# 信息键值行：键：值（仅头部区）
INFO_RE = re.compile(r"^\s*([^：:]{1,20})[：:]\s*(.+?)\s*$")


def parse_script(md_path):
    """返回 (info_dict, blocks, warnings)
    blocks: [{idx, voice, text}]
    """
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

        # 头部区：仅记录键值信息
        if not in_body:
            m = INFO_RE.match(line)
            if m:
                info[m.group(1)] = m.group(2)
            continue

        # 注释
        if line.startswith("#"):
            continue
        # 段标题：先冲刷当前块（打断跨段同角色合并），再跳过
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
            if voice not in VOICE_TABLE:
                raise ValueError(
                    "第%d行：音色名「%s」不在音色表中（可用：%s）"
                    % (lineno, voice, "、".join(VOICE_TABLE.keys())))
            if pending_voice == voice:
                # 连续同角色合并为一块
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
            hint = "（文件缺少 --- 分隔行：头部信息与台词块序列之间必须有 ---）"
        raise ValueError(
            "脚本中未解析到任何台词块%s，请检查标注格式（[音色名] 台词）" % hint)

    return info, blocks, warnings


def main():
    ap = argparse.ArgumentParser(description="解析播客脚本为任务清单 JSON")
    ap.add_argument("script", help="播客脚本 .md 路径")
    ap.add_argument("--out", help="输出任务清单 .json 路径（默认同目录同名 .json）")
    args = ap.parse_args()

    if not os.path.isfile(args.script):
        print("[ERROR] 脚本文件不存在: %s" % args.script)
        sys.exit(1)

    out_path = args.out or os.path.splitext(args.script)[0] + ".json"

    info, blocks, warnings = parse_script(args.script)

    for w in warnings:
        print("[WARN] %s" % w)

    total_chars = sum(len(b["text"]) for b in blocks)
    # 目标时长可能形如 "30分钟"，提取数字
    dur_raw = info.get("目标时长", "30") or "30"
    dur_m = re.search(r"\d+(?:\.\d+)?", str(dur_raw))
    duration_min = int(float(dur_m.group(0))) if dur_m else 30
    data = {
        "book": info.get("书名", os.path.basename(args.script)),
        "duration_min": duration_min,
        "blocks": blocks,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("[OK] 解析完成：共 %d 个台词块，%d 字" % (len(blocks), total_chars))
    print("[OK] 任务清单已写入: %s" % out_path)
    for b in blocks:
        print("  %03d [%s] %s" % (b["idx"], b["voice"], b["text"][:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
