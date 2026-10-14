# -*- coding: utf-8 -*-
"""调用本地 CosyVoice worker 逐块生成播客音频。

从现有 generate_audio.py 抽取核心逻辑，支持进度回调和取消检查。
"""
import os
import subprocess
import sys
import time

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

RETRIES = 2
RETRY_WAITS = [10, 30]


def build_env(repo_dir):
    """构造子进程环境变量（含 PYTHONPATH）。"""
    env = dict(os.environ)
    if os.path.isdir(repo_dir):
        paths = [repo_dir, os.path.join(repo_dir, "third_party", "Matcha-TTS")]
        cur = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in paths if p] + ([cur] if cur else [])
        )
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def call_worker(text, out_wav, audio_path, prompt_text,
                conda_python, model_dir, worker_script, repo_dir):
    """调用 CosyVoice worker 生成单块 wav（zero-shot 音色复刻）。

    成功返回 True，失败抛异常。
    """
    for path, label in [
        (worker_script, "worker 脚本"),
        (model_dir, "模型目录"),
        (conda_python, "conda python"),
        (audio_path, "参考音频"),
    ]:
        checker = os.path.isfile if label != "模型目录" else os.path.isdir
        if not checker(path):
            raise RuntimeError("%s 不存在: %s" % (label, path))

    cmd = [
        conda_python, worker_script,
        "--model_dir", model_dir,
        "--text", text,
        "--output", out_wav,
        "--spk", "中文女",
        "--prompt_audio", audio_path,
        "--prompt_text", prompt_text,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=900, env=build_env(repo_dir),
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("CosyVoice 生成超时（>15分钟），可能显存不足")
    except FileNotFoundError:
        raise RuntimeError("找不到 Python 解释器: %s" % conda_python)

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError("CosyVoice 生成失败: %s" % err[-1500:])
    if not (os.path.isfile(out_wav) and os.path.getsize(out_wav) > 0):
        raise RuntimeError("Worker 未产出有效文件")
    return True


def generate_block(block, out_dir, voice_info, params,
                   on_start=None, on_done=None, on_failed=None,
                   check_cancel=None, force=False):
    """生成单个音频块，带重试。

    Args:
        block: {"idx": int, "voice": str, "text": str}
        voice_info: (audio_path, prompt_text)
        params: {"conda_python", "model_dir", "worker_script", "repo_dir"}
        on_start/on_done/on_failed: 进度回调
        check_cancel: 取消检查回调，返回 True 则中止
        force: 强制重生成

    Returns:
        成功返回输出路径，失败返回 None
    """
    idx = block["idx"]
    text = block["text"]
    out_wav = os.path.join(out_dir, "%03d.wav" % idx)

    if os.path.isfile(out_wav) and os.path.getsize(out_wav) > 0 and not force:
        return out_wav

    audio_path, prompt_text = voice_info

    if on_start:
        on_start(idx, block["voice"], text)

    last_err = None
    for attempt in range(RETRIES + 1):
        if check_cancel and check_cancel():
            if on_failed:
                on_failed(idx, "已取消")
            return None
        try:
            call_worker(
                text, out_wav, audio_path, prompt_text,
                params["conda_python"], params["model_dir"],
                params["worker_script"], params["repo_dir"],
            )
            if on_done:
                on_done(idx, out_wav)
            return out_wav
        except Exception as e:
            last_err = e
            if on_failed:
                on_failed(idx, str(e))
            if attempt < RETRIES:
                wait = RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)]
                time.sleep(wait)

    return None
