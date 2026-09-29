#!/usr/bin/env python3
"""逐段音频响度标准化（EBU R128，loudnorm 两遍式线性归一）。

用途：AI 播客/有声内容拼接前，把每段音频标准化到统一目标响度（LUFS），
保证拼接成品段与段之间音量平稳、整体响度达标。

用法：
    python normalize_loudness.py file1.wav file2.wav ...
    python normalize_loudness.py seg*.wav --out-dir norm --lufs -16
    python normalize_loudness.py final.mp3 --lufs -16 --peak 1.5

输出：每段生成 norm_<原名>.wav（44.1kHz 立体声），并打印响度报告。
依赖：ffmpeg（默认 D:\\TOOLS\\ffmpeg\\bin\\ffmpeg.exe，可用 --ffmpeg 覆盖）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_FFMPEG = r"D:\TOOLS\ffmpeg\bin\ffmpeg.exe"


def run_ffmpeg(ffmpeg, args):
    cmd = [ffmpeg] + args
    return subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")


def measure(ffmpeg, path):
    """第一遍：测量当前响度，返回 measured_I/TP/LRA/thresh 四项。"""
    proc = run_ffmpeg(ffmpeg, [
        "-i", str(path),
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ])
    out = proc.stderr or ""
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out)
    if not m:
        raise RuntimeError(f"无法解析响度测量结果: {path}\n{out[-800:]}")
    data = json.loads(m.group(0))
    return {
        "measured_I": data["input_i"],
        "measured_TP": data["input_tp"],
        "measured_LRA": data["input_lra"],
        "measured_thresh": data["input_thresh"],
    }


def normalize(ffmpeg, path, out_path, target_lufs, measured, peak, lra):
    """第二遍：用测量值做线性归一，避免单遍 loudnorm 的动态增益误差。"""
    af = (
        f"loudnorm=I={target_lufs}:TP=-{peak}:LRA={lra}"
        f":measured_I={measured['measured_I']}"
        f":measured_TP={measured['measured_TP']}"
        f":measured_LRA={measured['measured_LRA']}"
        f":measured_thresh={measured['measured_thresh']}"
        f":linear=true"
    )
    proc = run_ffmpeg(ffmpeg, [
        "-i", str(path), "-af", af,
        "-ar", "44100", "-ac", "2",
        str(out_path),
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"归一化失败: {path}\n{(proc.stderr or '')[-2000:]}")


def main():
    ap = argparse.ArgumentParser(
        description="逐段音频响度标准化（EBU R128 两遍式 loudnorm）")
    ap.add_argument("files", nargs="+", help="输入音频文件（支持通配符）")
    ap.add_argument("--out-dir", default=None,
                    help="输出目录（默认与输入相同，输出加 norm_ 前缀）")
    ap.add_argument("--lufs", type=float, default=-16.0,
                    help="目标响度 LUFS（默认 -16；广播标准可用 -23）")
    ap.add_argument("--peak", type=float, default=1.5,
                    help="真峰值上限 dBTP（默认 1.5）")
    ap.add_argument("--lra", type=float, default=11.0,
                    help="动态范围上限 LRA（默认 11）")
    ap.add_argument("--ffmpeg", default=DEFAULT_FFMPEG,
                    help=f"ffmpeg 可执行文件路径（默认 {DEFAULT_FFMPEG}）")
    args = ap.parse_args()

    results = []
    out_dir = None
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"[跳过] 文件不存在: {p}")
            continue
        out_dir = Path(args.out_dir) if args.out_dir else p.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"norm_{p.stem}.wav"
        try:
            measured = measure(args.ffmpeg, p)
            before = float(measured["measured_I"])
            normalize(args.ffmpeg, p, out, args.lufs, measured, args.peak, args.lra)
            results.append((p.name, before, args.lufs, out.name))
            print(f"[OK] {p.name}: {before:.1f} LUFS → {args.lufs:.1f} LUFS → {out.name}")
        except Exception as e:
            print(f"[失败] {p.name}: {e}", file=sys.stderr)
            sys.exit(1)

    if results:
        print("\n==== 响度报告 ====")
        print(f"{'文件':<28}{'处理前LUFS':<14}{'处理后LUFS':<14}")
        for name, before, after, _ in results:
            print(f"{name:<28}{before:<14.1f}{after:<14.1f}")
        print(f"\n共处理 {len(results)} 个文件，输出目录: {out_dir}")


if __name__ == "__main__":
    main()
