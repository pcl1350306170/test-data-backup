# -*- coding: utf-8 -*-
"""调用本地 CosyVoice 逐块生成播客音频。

输入：任务清单 JSON（parse_script.py 产物）或播客脚本 .md（内部自动解析）。
输出：out-dir 下 001.wav、002.wav…（块顺序即拼接顺序）。

特性：
- 断点续转：同名非空 wav 已存在则跳过（--force 强制重生成）
- 单块失败自动重试（默认 2 次，间隔 10s/30s），仍失败记录 failed.txt 并继续
- Windows 下不弹黑窗；worker 必须在 cosyvoice conda 环境运行（脚本自动配置）

用法：
    python generate_audio.py 任务清单.json --out-dir 输出目录
    python generate_audio.py 播客脚本.md   --out-dir 输出目录 --force
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voices import resolve_voice  # noqa: E402

# ---------- 本地环境（已确认） ----------
DEFAULT_MODEL_DIR = r"D:\dev\sherpa-models\CosyVoice2-0.5B"
DEFAULT_REPO_DIR = r"D:\dev\sherpa-models\CosyVoice"
DEFAULT_CONDA_PY = r"D:\TOOLS\miniconda3\envs\cosyvoice\python.exe"
# worker 脚本（与 CosyVoice语音合成.py 同目录）
DEFAULT_WORKER = r"D:\CODE\Python\test-data-backup\py\other\cosyvoice_tts_worker.py"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 单块重试参数
RETRIES = 2          # 失败后额外重试次数
RETRY_WAITS = [10, 30]  # 重试间隔（秒）


def build_env():
    env = dict(os.environ)
    if os.path.isdir(DEFAULT_REPO_DIR):
        paths = [DEFAULT_REPO_DIR,
                 os.path.join(DEFAULT_REPO_DIR, "third_party", "Matcha-TTS")]
        cur = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in paths if p] + ([cur] if cur else []))
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def call_worker(text, out_wav, audio_path, prompt_text, log):
    """调用 worker 生成单块 wav（zero-shot 音色复刻）。成功返回 True。"""
    if not os.path.isfile(DEFAULT_WORKER):
        raise RuntimeError("找不到 worker 脚本: %s" % DEFAULT_WORKER)
    if not os.path.isdir(DEFAULT_MODEL_DIR):
        raise RuntimeError("模型目录不存在: %s" % DEFAULT_MODEL_DIR)
    if not os.path.isfile(DEFAULT_CONDA_PY):
        raise RuntimeError("conda python 不存在: %s" % DEFAULT_CONDA_PY)
    if not os.path.isfile(audio_path):
        raise RuntimeError("参考音频不存在: %s" % audio_path)

    cmd = [DEFAULT_CONDA_PY, DEFAULT_WORKER,
           "--model_dir", DEFAULT_MODEL_DIR,
           "--text", text,
           "--output", out_wav,
           "--spk", "中文女",
           "--prompt_audio", audio_path,
           "--prompt_text", prompt_text]
    log("  [worker] zero-shot %s -> %s" % (os.path.basename(audio_path),
                                            os.path.basename(out_wav)))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=900, env=build_env(),
                              creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError("CosyVoice 生成超时（>15分钟），可能模型未就绪或显存不足")
    except FileNotFoundError:
        raise RuntimeError("找不到 Python 解释器: %s" % DEFAULT_CONDA_PY)

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError("CosyVoice 生成失败: %s" % err[-1500:])
    if not (os.path.isfile(out_wav) and os.path.getsize(out_wav) > 0):
        raise RuntimeError("Worker 未产出有效文件")
    return True


def generate_block(block, out_dir, force, log):
    """生成单个块，带重试。成功返回输出路径，失败返回 None。"""
    idx = block["idx"]
    text = block["text"]
    voice = block["voice"]
    out_wav = os.path.join(out_dir, "%03d.wav" % idx)

    if os.path.isfile(out_wav) and os.path.getsize(out_wav) > 0 and not force:
        log("  [跳过] %s 已存在" % os.path.basename(out_wav))
        return out_wav

    pair = resolve_voice(voice)
    if pair is None:
        log("  [错误] 未知音色: %s" % voice)
        return None
    audio_path, prompt_text = pair

    last_err = None
    for attempt in range(RETRIES + 1):
        try:
            call_worker(text, out_wav, audio_path, prompt_text, log)
            log("  [完成] %s (%d字)" % (os.path.basename(out_wav), len(text)))
            return out_wav
        except Exception as e:
            last_err = e
            log("  [失败] 第 %d 次: %s" % (attempt + 1, e))
            if attempt < RETRIES:
                wait = RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)]
                log("  等待 %d 秒后重试..." % wait)
                time.sleep(wait)
    log("  [放弃] %03d.wav 多次失败: %s" % (idx, last_err))
    return None


def main():
    ap = argparse.ArgumentParser(description="本地 CosyVoice 逐块生成播客音频")
    ap.add_argument("input", help="任务清单 .json 或播客脚本 .md")
    ap.add_argument("--out-dir", required=True, help="输出 wav 目录")
    ap.add_argument("--force", action="store_true", help="强制重生成已存在的 wav")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print("[ERROR] 输入文件不存在: %s" % args.input)
        return 1

    # 输入可能是 .md（先解析）或 .json
    if args.input.lower().endswith(".md"):
        from parse_script import parse_script
        info, blocks, warnings = parse_script(args.input)
        for w in warnings:
            print("[WARN] %s" % w)
        print("[INFO] 已从脚本解析 %d 块" % len(blocks))
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
        blocks = data.get("blocks", [])
        info = {"书名": data.get("book", "")}
        if not blocks:
            print("[ERROR] 任务清单中没有 blocks")
            return 1

    os.makedirs(args.out_dir, exist_ok=True)
    total = len(blocks)
    ok = 0
    failed = []
    print("[INFO] 开始生成 %d 块 -> %s" % (total, args.out_dir))
    t0 = time.time()
    for block in blocks:
        out = generate_block(block, args.out_dir, args.force, print)
        if out:
            ok += 1
        else:
            failed.append(block["idx"])
        print("  [进度] %d/%d" % (ok + len(failed), total))

    # 记录失败清单
    if failed:
        failed_path = os.path.join(args.out_dir, "failed.txt")
        with open(failed_path, "w", encoding="utf-8") as f:
            for idx in failed:
                f.write("%03d\n" % idx)
        print("[WARN] %d 块失败，清单: %s" % (len(failed), failed_path))

    elapsed = time.time() - t0
    print("[DONE] 成功 %d/%d，耗时 %.1f 分钟" % (ok, total, elapsed / 60))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
