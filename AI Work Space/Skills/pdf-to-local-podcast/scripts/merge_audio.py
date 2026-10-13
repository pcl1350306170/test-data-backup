# -*- coding: utf-8 -*-
"""按顺序合并播客音频块 -> 单文件 mp3（含块间静音、可选 BGM、响度统一）。

纯 ffmpeg 实现（不依赖 pydub / audioop，适配 Python 3.13+）。

流程：
  1. 按文件名顺序（001.wav、002.wav…）扫描目录中的 wav
  2. （可选）每块先 loudnorm 到目标响度（--skip-per-block 可跳过，仅整体收尾）
  3. 块间插入静音（--gap-ms，默认 400ms），用 ffmpeg concat demuxer 拼接
  4. （可选）BGM 叠加：音量 0-100（默认 30），循环到总时长、尾部淡出
  5. 整体 loudnorm 一遍收尾（默认 -16 LUFS 播客标准）
  6. 导出 mp3，ffprobe 校验时长

用法：
    python merge_audio.py 音频目录 --output 成品.mp3
    python merge_audio.py 音频目录 --output 成品.mp3 --bgm bgm.mp3 --bgm-volume 25
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ffmpeg 路径：优先 PATH，其次已知目录
_FFMPEG_CANDIDATES = ["ffmpeg", r"D:\TOOLS\ffmpeg\bin\ffmpeg.exe"]
_FFPROBE_CANDIDATES = ["ffprobe", r"D:\TOOLS\ffmpeg\bin\ffprobe.exe"]


def _find(candidates):
    for c in candidates:
        if c.startswith(("C:", "D:", "\\", "/")):
            if os.path.isfile(c):
                return c
        else:
            p = shutil.which(c)
            if p:
                return p
    return None


FFMPEG = _find(_FFMPEG_CANDIDATES)
FFPROBE = _find(_FFPROBE_CANDIDATES)


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=_NO_WINDOW)


def probe_duration(path):
    if not FFPROBE:
        return None
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", path])
    try:
        return float(r.stdout.strip())
    except (ValueError, TypeError):
        return None


def loudnorm_file(in_path, out_path, lufs):
    """单遍 loudnorm：目标响度 lufs，峰值 -1.5 dBTP，LRA 11。"""
    af = "loudnorm=I=%s:TP=-1.5:LRA=11" % lufs
    r = _run([FFMPEG, "-y", "-i", in_path, "-af", af,
              "-ar", "44100", "-ac", "2", out_path])
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError("loudnorm 失败: %s" % (r.stderr or "")[-500:])


def main():
    ap = argparse.ArgumentParser(description="合并播客音频块为单文件 mp3")
    ap.add_argument("input_dir", help="包含 001.wav…NNN.wav 的目录")
    ap.add_argument("--output", required=True, help="输出 mp3 路径")
    ap.add_argument("--bgm", help="背景音乐文件（可选）")
    ap.add_argument("--bgm-volume", type=int, default=30,
                    help="BGM 音量 0-100（默认30）")
    ap.add_argument("--lufs", type=float, default=-16.0,
                    help="目标响度 LUFS（默认 -16 播客标准；广播用 -23）")
    ap.add_argument("--gap-ms", type=int, default=400,
                    help="块间插入静音毫秒数（默认400）")
    ap.add_argument("--skip-per-block", action="store_true",
                    help="跳过逐块 loudnorm，仅整体收尾一遍")
    args = ap.parse_args()

    if not FFMPEG:
        print("[ERROR] 找不到 ffmpeg，请安装或放到 PATH")
        return 1

    # 扫描 wav（按编号排序）
    files = []
    for name in os.listdir(args.input_dir):
        if name.lower().endswith(".wav"):
            m = re.match(r"^(\d+)\.wav$", name.lower())
            if m:
                files.append((int(m.group(1)), name))
    files.sort(key=lambda x: x[0])
    if not files:
        print("[ERROR] 目录中没有 001.wav…NNN.wav 格式的音频")
        return 1
    print("[INFO] 找到 %d 个块" % len(files))

    # 逐块 loudnorm（可选）
    work_dir = args.input_dir
    if not args.skip_per_block:
        norm_dir = os.path.join(args.input_dir, "_norm")
        os.makedirs(norm_dir, exist_ok=True)
        for num, name in files:
            out_name = "norm_%s" % name
            out_path = os.path.join(norm_dir, out_name)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                continue
            print("  [loudnorm] %s" % name)
            loudnorm_file(os.path.join(args.input_dir, name), out_path,
                          args.lufs)
        work_dir = norm_dir
        files = [(num, "norm_%s" % name) for num, name in files]

    # 生成块间静音片段
    gap_sec = max(0, args.gap_ms) / 1000.0
    silence_path = os.path.join(work_dir, "_silence.wav")
    r = _run([FFMPEG, "-y", "-f", "lavfi", "-i",
              "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % gap_sec,
              "-c:a", "pcm_s16le", silence_path])
    if r.returncode != 0 or not os.path.isfile(silence_path):
        print("[ERROR] 生成静音片段失败: %s" % (r.stderr or "")[-500:])
        return 1

    # 写 concat 列表（块间插入静音）
    list_path = os.path.join(work_dir, "_concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for i, (num, name) in enumerate(files):
            if i > 0:
                f.write("file '_silence.wav'\n")
            f.write("file '%s'\n" % name)
    print("[INFO] concat 列表：%d 个块 + 静音间隔" % len(files))

    # concat -> 临时 wav
    raw_wav = os.path.splitext(args.output)[0] + "_raw.wav"
    r = _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
              "-c:a", "pcm_s16le", raw_wav])
    if r.returncode != 0 or not os.path.isfile(raw_wav):
        print("[ERROR] concat 拼接失败: %s" % (r.stderr or "")[-800:])
        return 1
    total_dur = probe_duration(raw_wav) or 0.0
    print("[INFO] 拼接完成：%.1f 分钟" % (total_dur / 60.0))

    # BGM 叠加（可选）
    if args.bgm and os.path.isfile(args.bgm) and args.bgm_volume > 0:
        gain_db = -30.0 + (args.bgm_volume / 100.0) * 30.0
        fade_st = max(0.0, total_dur - 2.0)
        af = (
            "[1:a]volume=%fdB,aloop=loop=-1:size=2e9,"
            "atrim=duration=%.3f,afade=t=out:st=%.3f:d=2,"
            "aformat=channel_layouts=stereo,sample_rates=44100[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0[a]"
        ) % (gain_db, total_dur, fade_st)
        mixed = os.path.join(args.input_dir, "_mixed.wav")
        r = _run([FFMPEG, "-y", "-i", raw_wav, "-i", args.bgm,
                  "-filter_complex", af, "-map", "[a]",
                  "-c:a", "pcm_s16le", mixed])
        if r.returncode != 0 or not os.path.isfile(mixed):
            print("[ERROR] BGM 叠加失败: %s" % (r.stderr or "")[-800:])
            return 1
        os.replace(mixed, raw_wav)
        print("[INFO] BGM 已叠加（音量 %d%%）" % args.bgm_volume)

    # 整体 loudnorm 收尾 -> mp3
    print("[loudnorm] 整体收尾 -> %s" % args.output)
    loudnorm_file(raw_wav, args.output, args.lufs)

    # 清理临时文件
    for tmp in [raw_wav, list_path, silence_path]:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass

    dur = probe_duration(args.output)
    if dur is None:
        print("[WARN] 无法探测输出时长")
    else:
        print("[OK] 输出: %s (%.1f分钟 / %.1f秒)" % (args.output, dur / 60, dur))
    print("[DONE] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
