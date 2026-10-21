# -*- coding: utf-8 -*-
"""合并播客音频块 → 单文件 mp3（含块间静音、可选 BGM、响度统一）。

从现有 merge_audio.py 抽取核心逻辑，纯 ffmpeg 实现。
"""
import os
import re
import shutil
import subprocess
import sys

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

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
    """探测音频文件时长（秒）。"""
    if not FFPROBE:
        return None
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", path])
    try:
        return float(r.stdout.strip())
    except (ValueError, TypeError):
        return None


def loudnorm_file(in_path, out_path, lufs):
    """单遍 loudnorm 归一化。"""
    af = "loudnorm=I=%s:TP=-1.5:LRA=11" % lufs
    r = _run([FFMPEG, "-y", "-i", in_path, "-af", af,
              "-ar", "44100", "-ac", "2", out_path])
    if r.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError("loudnorm 失败: %s" % (r.stderr or "")[-500:])


def merge(input_dir, output_path, bgm_path=None, bgm_volume=30,
          lufs=-16, gap_ms=400, skip_per_block=False,
          on_progress=None):
    """合并音频块为单文件 mp3。

    Args:
        input_dir: 包含 001.wav…NNN.wav 的目录
        output_path: 输出 mp3 路径
        bgm_path: BGM 文件路径（可选）
        bgm_volume: BGM 音量 0-100
        lufs: 目标响度 LUFS
        gap_ms: 块间静音毫秒数
        skip_per_block: 跳过逐块 loudnorm
        on_progress: 进度回调 (current, total, message)

    Returns:
        (output_path, duration_sec)
    """
    if not FFMPEG:
        raise RuntimeError("找不到 ffmpeg")

    # 扫描 wav
    files = []
    for name in os.listdir(input_dir):
        if name.lower().endswith(".wav"):
            m = re.match(r"^(\d+)\.wav$", name.lower())
            if m:
                files.append((int(m.group(1)), name))
    files.sort(key=lambda x: x[0])
    if not files:
        raise RuntimeError("目录中没有 001.wav…NNN.wav 格式的音频")

    total = len(files)
    if on_progress:
        on_progress(0, total, "扫描到 %d 个块" % total)

    # 逐块 loudnorm（可选）
    work_dir = input_dir
    if not skip_per_block:
        norm_dir = os.path.join(input_dir, "_norm")
        os.makedirs(norm_dir, exist_ok=True)
        for i, (num, name) in enumerate(files):
            out_name = "norm_%s" % name
            out_path = os.path.join(norm_dir, out_name)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                continue
            if on_progress:
                on_progress(i + 1, total, "loudnorm %s" % name)
            loudnorm_file(os.path.join(input_dir, name), out_path, lufs)
        work_dir = norm_dir
        files = [(num, "norm_%s" % name) for num, name in files]

    # 生成块间静音
    gap_sec = max(0, gap_ms) / 1000.0
    silence_path = os.path.join(work_dir, "_silence.wav")
    r = _run([FFMPEG, "-y", "-f", "lavfi", "-i",
              "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % gap_sec,
              "-c:a", "pcm_s16le", silence_path])
    if r.returncode != 0 or not os.path.isfile(silence_path):
        raise RuntimeError("生成静音片段失败")

    # 写 concat 列表
    list_path = os.path.join(work_dir, "_concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for i, (num, name) in enumerate(files):
            if i > 0:
                f.write("file '_silence.wav'\n")
            f.write("file '%s'\n" % name)

    # concat → 临时 wav
    raw_wav = os.path.splitext(output_path)[0] + "_raw.wav"
    r = _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
              "-c:a", "pcm_s16le", raw_wav])
    if r.returncode != 0 or not os.path.isfile(raw_wav):
        raise RuntimeError("concat 拼接失败: %s" % (r.stderr or "")[-800:])
    total_dur = probe_duration(raw_wav) or 0.0

    if on_progress:
        on_progress(total, total, "拼接完成 %.1f 分钟" % (total_dur / 60))

    # BGM 叠加（可选）
    if bgm_path and os.path.isfile(bgm_path) and bgm_volume > 0:
        gain_db = -30.0 + (bgm_volume / 100.0) * 30.0
        fade_st = max(0.0, total_dur - 2.0)
        af = (
            "[1:a]volume=%fdB,aloop=loop=-1:size=2e9,"
            "atrim=duration=%.3f,afade=t=out:st=%.3f:d=2,"
            "aformat=channel_layouts=stereo:sample_rates=44100[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0[a]"
        ) % (gain_db, total_dur, fade_st)
        mixed = os.path.join(input_dir, "_mixed.wav")
        r = _run([FFMPEG, "-y", "-i", raw_wav, "-i", bgm_path,
                  "-filter_complex", af, "-map", "[a]",
                  "-c:a", "pcm_s16le", mixed])
        if r.returncode != 0 or not os.path.isfile(mixed):
            raise RuntimeError("BGM 叠加失败: %s" % (r.stderr or "")[-800:])
        os.replace(mixed, raw_wav)

    # 整体 loudnorm 收尾 → mp3
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if on_progress:
        on_progress(total, total, "整体响度归一化...")
    loudnorm_file(raw_wav, output_path, lufs)

    # 清理临时文件
    for tmp in [raw_wav, list_path, silence_path]:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass

    dur = probe_duration(output_path)
    return output_path, dur
