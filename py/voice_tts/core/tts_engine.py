# -*- coding: utf-8 -*-
"""TTS 核心引擎：文本切段、Worker 调用、音频后处理（语速/淡出/格式转换）。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------- pydub 可选依赖 ----------
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception:
    AudioSegment = None
    HAS_PYDUB = False

# subprocess 静默标记（Windows）
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 支持的音频后缀
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


# ============================================================
# 文本切段
# ============================================================
_SENT_ENDS = set("。！？!?\n；;")


def split_text(text: str, max_chars: int = 500) -> list:
    """按 max_chars 软上限切段，尽量在句末标点结束。"""
    if not text:
        return []
    text = text.strip()
    if not text:
        return []
    max_chars = max(50, int(max_chars))
    hard_limit = max_chars * 2
    segments = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in _SENT_ENDS and len(buf) >= max_chars:
            seg = buf.strip()
            if seg:
                segments.append(seg)
            buf = ""
        elif len(buf) >= hard_limit:
            seg = buf.strip()
            if seg:
                segments.append(seg)
            buf = ""
    tail = buf.strip()
    if tail:
        segments.append(tail)
    return segments


# ============================================================
# Worker 调用
# ============================================================
def call_worker(text: str, out_wav: str, cfg: dict) -> bool:
    """通过 subprocess 调用 CosyVoice worker 生成 wav。成功返回 True，失败抛异常。"""
    worker_script = cfg.get("worker_script", "")
    model_dir = cfg.get("model_dir", "")
    repo_dir = cfg.get("repo_dir", "")
    conda_py = cfg.get("conda_python", "")

    if not worker_script or not os.path.isfile(worker_script):
        raise RuntimeError(f"Worker 脚本不存在: {worker_script}")
    if not os.path.isdir(model_dir):
        raise RuntimeError(f"模型目录不存在: {model_dir}")
    if not os.path.isfile(conda_py):
        raise RuntimeError(f"conda python 不存在: {conda_py}")

    # 构造 PYTHONPATH
    env = dict(os.environ)
    if repo_dir and os.path.isdir(repo_dir):
        paths = [repo_dir, os.path.join(repo_dir, "third_party", "Matcha-TTS")]
        cur = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in paths if p] + ([cur] if cur else []))
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [conda_py, worker_script,
           "--model_dir", model_dir,
           "--text", text,
           "--output", out_wav,
           "--spk", cfg.get("spk") or "中文女"]

    style = (cfg.get("style") or "").strip()
    if style:
        cmd += ["--style", style]

    prompt_audio = (cfg.get("prompt_audio") or "").strip()
    prompt_text = (cfg.get("prompt_text") or "").strip()
    if prompt_audio and prompt_text:
        cmd += ["--prompt_audio", prompt_audio, "--prompt_text", prompt_text]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=900, env=env, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError("CosyVoice 生成超时（>15分钟）")
    except FileNotFoundError:
        raise RuntimeError(f"找不到 Python 解释器: {conda_py}")

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError(f"CosyVoice 生成失败: {err[-1500:]}")
    if not os.path.isfile(out_wav):
        raise RuntimeError("Worker 未产出文件")
    return True


# ============================================================
# 音频后处理
# ============================================================
def _ffmpeg_load_audio(filepath):
    """通过 ffmpeg 管道加载音频为 AudioSegment（不弹黑窗）"""
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "stream=sample_rate,channels",
         "-of", "csv=p=0:nk=1", filepath],
        capture_output=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW)
    sample_rate, channels = 22050, 1
    for line in (probe.stdout or "").strip().split("\n"):
        parts = line.strip().split(",")
        if len(parts) >= 2:
            try:
                sample_rate = int(parts[0])
                channels = int(parts[1])
                break
            except (ValueError, IndexError):
                pass
    raw_result = subprocess.run(
        ["ffmpeg", "-y", "-i", filepath,
         "-f", "s16le", "-acodec", "pcm_s16le",
         "-ar", str(sample_rate), "-ac", str(channels), "pipe:1"],
        capture_output=True, creationflags=_NO_WINDOW)
    return AudioSegment(
        data=raw_result.stdout,
        sample_width=2, frame_rate=sample_rate, channels=channels)


def _ffmpeg_export_wav(audio_segment, output_path):
    """通过 ffmpeg 管道导出 AudioSegment 为 WAV（不弹黑窗）"""
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "s16le", "-ar", str(audio_segment.frame_rate),
         "-ac", str(audio_segment.channels), "-i", "pipe:0",
         "-acodec", "pcm_s16le", output_path],
        input=audio_segment.raw_data,
        capture_output=True, creationflags=_NO_WINDOW)


def apply_fade_out(wav_path: str, fade_ms: int = 0, tail_ms: int = 900):
    """末尾淡出 + 补一段静音余韵。"""
    if not HAS_PYDUB or not os.path.isfile(wav_path):
        return
    try:
        if shutil.which("ffmpeg"):
            audio = _ffmpeg_load_audio(wav_path)
        else:
            audio = AudioSegment.from_wav(wav_path)
        duration = len(audio)
        if not isinstance(duration, int) or duration <= 0:
            return
        if fade_ms > 0:
            fade = min(fade_ms, int(duration * 0.3))
            audio = audio.fade_out(fade)
        if tail_ms > 0:
            audio = audio + AudioSegment.silent(duration=tail_ms)
        if shutil.which("ffmpeg"):
            _ffmpeg_export_wav(audio, wav_path)
        else:
            audio.export(wav_path, format="wav")
    except Exception:
        pass


def _build_atempo_filter(speed: float) -> str:
    """atempo 单次范围 0.5~2.0，超出则级联。"""
    filters = []
    remain = float(speed)
    while remain > 2.0:
        filters.append("atempo=2.0")
        remain /= 2.0
    while remain < 0.5:
        filters.append("atempo=0.5")
        remain /= 0.5
    filters.append(f"atempo={remain:.4f}")
    return ",".join(filters)


def apply_speed(wav_path: str, speed: float):
    """用 ffmpeg atempo 调整 wav 语速。"""
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        return
    if abs(speed - 1.0) < 0.01:
        return
    if not shutil.which("ffmpeg"):
        return
    tmp_path = wav_path + ".tmp.wav"
    af = _build_atempo_filter(speed)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-filter:a", af, tmp_path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=_NO_WINDOW)
        if proc.returncode != 0 or not os.path.isfile(tmp_path):
            return
        os.replace(tmp_path, wav_path)
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def wav_to_mp3(wav_path: str, mp3_path: str) -> bool:
    """用 ffmpeg 将 wav 转 mp3。"""
    if not shutil.which("ffmpeg"):
        return False
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path,
             "-codec:a", "libmp3lame", "-qscale:a", "2", mp3_path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=_NO_WINDOW)
        return proc.returncode == 0 and os.path.isfile(mp3_path)
    except Exception:
        return False


# ============================================================
# 工具函数
# ============================================================
def safe_name(s: str) -> str:
    """过滤文件名中的非法字符。"""
    if not s:
        return ""
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in s).strip()


def scan_prompt_audios(tts_dir: str) -> list:
    """扫描参考音频目录，返回 [{name, path}, ...]"""
    audios = []
    if tts_dir and os.path.isdir(tts_dir):
        for f in sorted(os.listdir(tts_dir)):
            fp = os.path.join(tts_dir, f)
            if os.path.isfile(fp) and Path(f).suffix.lower() in AUDIO_EXTS:
                audios.append({"name": Path(f).stem, "path": fp})
    return audios
