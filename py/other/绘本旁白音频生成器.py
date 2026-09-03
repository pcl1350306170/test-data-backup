# -*- coding: utf-8 -*-
"""
AI绘本 旁白音频生成器（桌面 GUI / tkinter）
================================================
功能：
  1. 选择 JSON 脚本文件（读取每页 plotContent 字段）
  2. 选择输出目录，自动按 001.wav、002.wav ... 命名保存
  3. 选择生成方案：pyttsx3 / edge-tts / sherpa-onnx / cosyvoice(预留)
  4. 各方案可手动指定所需资源目录（如 sherpa-onnx 模型目录）
  5. 可选"结尾淡出 + 补静音"处理（pydub）
  6. 统一输出 WAV

运行方式：
  python 绘本旁白音频生成器.py

依赖（按需安装，未装的方案会灰显提示）：
  pip install pyttsx3 edge-tts sherpa-onnx pydub
  注：sherpa-onnx 需要额外下载 TTS 模型文件；edge-tts 需要联网。
"""

import json
import os
import sys
import queue
import random
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ---------- 路径与配置 ----------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "绘本旁白音频生成器"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# ---------- 日志（可选依赖） ----------
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()

# ---------- 可选依赖探测 ----------
try:
    import pyttsx3
except Exception:
    pyttsx3 = None

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    import sherpa_onnx
except Exception:
    sherpa_onnx = None

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except Exception:
    AudioSegment = None
    HAS_PYDUB = False

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _ffmpeg_convert(input_path, output_path):
    """用 ffmpeg 将任意格式音频转为 WAV（不弹黑窗）"""
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path,
         "-acodec", "pcm_s16le", output_path],
        capture_output=True, creationflags=_NO_WINDOW)


def _ffmpeg_export_wav(audio_segment, output_path):
    """通过 ffmpeg 管道导出 AudioSegment 为 WAV（不弹黑窗）"""
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "s16le", "-ar", str(audio_segment.frame_rate),
         "-ac", str(audio_segment.channels), "-i", "pipe:0",
         "-acodec", "pcm_s16le", output_path],
        input=audio_segment.raw_data,
        capture_output=True, creationflags=_NO_WINDOW)


def _ffmpeg_load_audio(filepath):
    """通过 ffmpeg 管道加载音频为 AudioSegment（不弹黑窗）"""
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "stream=sample_rate,channels",
         "-of", "csv=p=0:nk=1", filepath],
        capture_output=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW)
    sample_rate, channels = 44100, 1
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


# CosyVoice 就绪判断：worker 脚本存在即视为"可配置"（真正的就绪需填写 conda 与仓库路径）
COSYVOICE_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cosyvoice_worker.py")
# 常用 CosyVoice 音色（SFT 预置）
COSYVOICE_SPK_OPTIONS = ["中文女", "中文男", "英文男", "英文女", "日语男", "韩语女", "粤语女"]


def _cosyvoice_ready():
    return os.path.isfile(COSYVOICE_WORKER)


# ============================================================
# 方案说明与状态
# ============================================================
SCHEMES = {
    "pyttsx3": {
        "label": "pyttsx3（本地·Windows系统语音）",
        "desc": (
            "简介：调用 Windows 系统自带的语音引擎（SAPI），完全离线、零下载。\n"
            "特点：安装简单、无模型资源要求；但音色偏机械，中文女声自然度一般。\n"
            "资源：无需额外资源；音色来自系统“语音”设置。"
        ),
        "need_resource_dir": False,
        "installed": pyttsx3 is not None,
    },
    "edge-tts": {
        "label": "edge-tts（微软在线语音）",
        "desc": (
            "简介：调用微软 Edge 的在线神经网络语音，音质自然、中文女声效果好。\n"
            "特点：免费、音色丰富可选；但必须联网，数据会经过微软服务器。\n"
            "资源：无需本地模型；联网自动拉取音色列表。"
        ),
        "need_resource_dir": False,
        "installed": edge_tts is not None,
    },
    "sherpa-onnx": {
        "label": "sherpa-onnx（开源离线TTS）",
        "desc": (
            "简介：基于 VITS 的开源离线中文 TTS，CPU 可跑，音质中上。\n"
            "特点：真离线、隐私安全；需下载 ONNX 模型文件（几百MB）。\n"
            "资源：需指定模型目录，内含 .onnx、tokens.txt、lexicon.txt 等。"
        ),
        "need_resource_dir": True,
        "installed": sherpa_onnx is not None,
    },
    "cosyvoice": {
        "label": "CosyVoice（阿里开源·离线顶配）",
        "desc": (
            "简介：阿里通义开源的离线大模型 TTS，音质最佳、可零样本复刻音色。\n"
            "特点：需独立 conda 环境(py3.10)+克隆仓库+下载模型；本机通常需 NVIDIA 显卡。\n"
            "资源：模型目录(如 D:\\dev\\sherpa-models\\CosyVoice2-0.5B)；\n"
            "      另需在 GUI 中填写 CosyVoice 仓库路径 与 conda 的 python.exe 路径。\n"
            "音色：预置 中文女/中文男/英文男/英文女 等，选词在下拉框。"
        ),
        "need_resource_dir": True,
        "installed": _cosyvoice_ready,
    },
}

# 音色说明（edge-tts 常用中文音色提示）
EDGE_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# Sherpa-ONNX 音色选项（sid + 描述）
SHERPA_SID_OPTIONS = [
    "0 - 温柔女声，快速，间隔不清",
    "1 - 沉稳男声，快速，间隔不清",
    "2 - 知性女声，快速，间隔不清",
    "3 - 不清晰男声，快速，间隔不清",
    "4 - 空灵男声，快速，间隔不清",
]


# ============================================================
# 各方案的实际生成函数（供 worker 线程调用）
# ============================================================

def _gen_pyttsx3(text: str, out_path: str, voice_name: str, log):
    """pyttsx3：本地系统语音。Windows SAPI 支持保存 wav。"""
    engine = pyttsx3.init()
    if voice_name:
        for v in engine.getProperty("voices"):
            if voice_name.lower() in (v.id or "").lower() or voice_name.lower() in (v.name or "").lower():
                engine.setProperty("voice", v.id)
                break
    engine.setProperty("rate", 160)   # 语速，可调
    engine.setProperty("volume", 1.0)
    # pyttsx3 在 Windows 下 save_to_file 输出 wav；先跑一次初始化驱动
    engine.save_to_file(text, out_path)
    engine.runAndWait()
    log("  [pyttsx3] 已生成: %s" % os.path.basename(out_path))


def _gen_edge_tts(text: str, out_path: str, voice: str, log,
                  retries: int = 3, retry_wait: float = 5.0):
    """edge-tts：在线。先生成 mp3 再用 pydub 转 wav（保持统一 WAV 输出）。
    内置"自动重试 + 递增退避"保险：单次失败不中断，最多重试 retries 次，
    每次等待 retry_wait 秒后重试（逐次递增，避免高频请求触发限流）。
    """
    import asyncio

    # Windows 下 ProactorEventLoop 会闪黑框，切换到 SelectorEventLoop
    # 3.13+ 虽标记弃用但仍需设置，抑制 DeprecationWarning 即可
    if sys.platform == "win32":
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    last_err = None
    for attempt in range(1, retries + 1):
        # 清理可能残留的损坏文件
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        try:
            async def _run():
                communicate = edge_tts.Communicate(text, voice, rate="-5%")
                await communicate.save(out_path)

            asyncio.run(_run())
            # edge-tts 默认输出 mp3，统一转为 wav
            if shutil.which("ffmpeg"):
                _ffmpeg_convert(out_path, out_path)
            elif HAS_PYDUB:
                raw = AudioSegment.from_file(out_path, format="mp3")
                raw.export(out_path, format="wav")
            log("  [edge-tts] 已生成: %s（音色 %s）" % (os.path.basename(out_path), voice))
            return
        except Exception as e:
            last_err = e
            log("  [edge-tts] 第 %d/%d 次尝试失败: %s" % (attempt, retries, e))
            if attempt < retries:
                wait = retry_wait * attempt  # 递增退避：5、10、15...
                log("  等待 %d 秒后重试..." % wait)
                time.sleep(wait)
    raise RuntimeError("edge-tts 连续 %d 次失败，已放弃：%s" % (retries, last_err))


def _gen_sherpa_onnx(text: str, out_path: str, model_dir: str, sid: int, log):
    """sherpa-onnx：离线 VITS。模型目录需含 .onnx / tokens.txt / lexicon.txt / data。"""
    import wave
    import numpy as np

    # 在模型目录中定位必要文件
    model_path = None
    tokens_path = None
    lexicon_path = None
    data_dir = None
    rule_fsts = []
    for f in os.listdir(model_dir):
        fp = os.path.join(model_dir, f)
        if f.lower().endswith(".onnx"):
            # 优先非 int8 版本
            if "int8" not in f.lower():
                model_path = fp
            elif model_path is None:
                model_path = fp
        elif f.lower() == "tokens.txt":
            tokens_path = fp
        elif f.lower() == "lexicon.txt":
            lexicon_path = fp
        elif f.lower() == "espeak-ng-data":
            data_dir = fp
        elif f.lower().endswith(".fst"):
            rule_fsts.append(fp)
    if not model_path or not tokens_path:
        raise RuntimeError("模型目录中未找到 .onnx 和 tokens.txt，请检查目录。")

    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=model_path,
                tokens=tokens_path,
                lexicon=lexicon_path or "",
                data_dir=data_dir or "",
            ),
        ),
        rule_fsts=",".join(rule_fsts),
    )
    tts = sherpa_onnx.OfflineTts(config)
    result = tts.generate(text, sid=int(sid), speed=1.0)
    samples = np.asarray(result.samples, dtype=np.float32)  # 新版返回 list，需转 numpy
    sample_rate = result.sample_rate

    # 写 wav
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes((samples * 32767).astype(np.int16).tobytes())
    log("  [sherpa-onnx] 已生成: %s（sid=%s）" % (os.path.basename(out_path), sid))


def _gen_cosyvoice(text: str, out_path: str, model_dir: str, spk: str,
                   log, repo_dir: str = "", conda_python: str = ""):
    """CosyVoice：通过 subprocess 调用独立 worker（需在 conda 环境内运行）。
    repo_dir  : CosyVoice 仓库根目录（用于设置 PYTHONPATH）
    conda_python: CosyVoice conda 环境中的 python.exe 绝对路径
    """
    import subprocess as _sp

    if not os.path.isfile(COSYVOICE_WORKER):
        raise RuntimeError("找不到 cosyvoice_worker.py，请确认它与本脚本在同一目录。")
    if not model_dir:
        raise RuntimeError("CosyVoice 需要指定模型目录（资源目录）。")

    # 默认 conda python：优先用户填写；否则尝试 conda run
    if conda_python and os.path.isfile(conda_python):
        py_cmd = conda_python
    else:
        py_cmd = "python"

    # 构造 PYTHONPATH：仓库根目录 + third_party/Matcha-TTS
    extra_env = dict(os.environ)
    if repo_dir and os.path.isdir(repo_dir):
        paths = [repo_dir,
                 os.path.join(repo_dir, "third_party", "Matcha-TTS")]
        cur = extra_env.get("PYTHONPATH", "")
        extra_env["PYTHONPATH"] = os.pathsep.join(
            [p for p in paths if p] + ([cur] if cur else []))

    cmd = [py_cmd, COSYVOICE_WORKER,
           "--model_dir", model_dir,
           "--text", text,
           "--output", out_path,
           "--spk", spk]
    log("  [cosyvoice] 调用: %s %s" % (py_cmd, os.path.basename(COSYVOICE_WORKER)))

    try:
        proc = _sp.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600,
                       env=extra_env, creationflags=_NO_WINDOW)
    except _sp.TimeoutExpired:
        raise RuntimeError("CosyVoice 生成超时（>10分钟），可能模型未就绪或显存不足。")
    except FileNotFoundError:
        raise RuntimeError("找不到 Python 解释器：%s，请在参数中填写 CosyVoice conda 的 python.exe 路径。" % py_cmd)

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError("CosyVoice 生成失败：%s" % err[-2000:])

    if not os.path.isfile(out_path):
        raise RuntimeError("CosyVoice 未生成文件，请检查模型路径与音色参数。")
    log("  [cosyvoice] 已生成: %s（音色 %s）" % (os.path.basename(out_path), spk))


GENERATORS = {
    "pyttsx3": _gen_pyttsx3,
    "edge-tts": _gen_edge_tts,
    "sherpa-onnx": _gen_sherpa_onnx,
    "cosyvoice": _gen_cosyvoice,
}


# ============================================================
# 结尾淡出处理
# ============================================================
def apply_fade_out(wav_path, fade_ms=1200, tail_ms=900):
    """末尾淡出 + 补一段静音余韵。优先 ffmpeg 加载避免黑窗。"""
    if not HAS_PYDUB:
        return
    if shutil.which("ffmpeg"):
        audio = _ffmpeg_load_audio(wav_path)
    else:
        audio = AudioSegment.from_wav(wav_path)
    duration = len(audio)
    fade = min(fade_ms, int(duration * 0.3))
    audio = audio.fade_out(fade)
    if tail_ms > 0:
        audio = audio + AudioSegment.silent(duration=tail_ms)
    if shutil.which("ffmpeg"):
        _ffmpeg_export_wav(audio, wav_path)
    else:
        audio.export(wav_path, format="wav")


# ============================================================
# 主程序 / GUI
# ============================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("AI绘本 · 旁白音频生成器")
        root.geometry("760x860")
        root.minsize(680, 780)

        self.msg_queue = queue.Queue()
        self.worker = None
        self.edge_voices = []
        self._pause_event = threading.Event()  # set=运行, clear=暂停
        self._pause_event.set()
        self._stop_event = threading.Event()   # set=停止
        self._gen_mode = "idle"  # idle / gen / test
        self.scheme_var = tk.StringVar(value="edge-tts")
        self.json_var = tk.StringVar()
        self.out_dir_var = tk.StringVar()
        self.resource_dir_var = tk.StringVar()
        self.voice_var = tk.StringVar(value=EDGE_DEFAULT_VOICE)
        self.sid_var = tk.StringVar(value="0")
        self.fade_var = tk.BooleanVar(value=True)
        self.fade_ms_var = tk.StringVar(value="1200")
        self.tail_ms_var = tk.StringVar(value="900")
        self.edge_interval_var = tk.StringVar(value="0.8")  # edge-tts 请求间隔(秒)
        self.edge_retries_var = tk.StringVar(value="3")     # edge-tts 最大重试次数
        self.edge_retry_wait_var = tk.StringVar(value="5")  # edge-tts 重试等待基数(秒)
        self.cosy_model_var = tk.StringVar()                # CosyVoice 模型目录
        self.cosy_repo_var = tk.StringVar()                 # CosyVoice 仓库目录
        self.cosy_python_var = tk.StringVar()               # CosyVoice conda python.exe

        self._build_ui()
        self._load_config()
        self._after_poll()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # 标题
        ttk.Label(self.root, text="AI绘本 旁白音频生成器", font=(
            "Microsoft YaHei UI", 14, "bold")).pack(anchor="w", **pad)

        # 创建标签页容器
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, **pad)

        # ========== 配置标签页 ==========
        config_tab = ttk.Frame(self.notebook)
        self.notebook.add(config_tab, text=" 配置 ")

        # JSON 文件
        frm = ttk.LabelFrame(config_tab, text="1. 脚本文件（JSON）")
        frm.pack(fill="x", **pad)
        ttk.Entry(frm, textvariable=self.json_var).pack(
            side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(frm, text="浏览…", command=self._pick_json).pack(
            side="right", padx=6)

        # 输出目录
        frm = ttk.LabelFrame(config_tab, text="2. 输出目录（WAV 将按 001.wav 命名保存）")
        frm.pack(fill="x", **pad)
        ttk.Entry(frm, textvariable=self.out_dir_var).pack(
            side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(frm, text="浏览…", command=self._pick_out_dir).pack(
            side="right", padx=6)

        # 方案选择
        frm = ttk.LabelFrame(config_tab, text="3. 生成方案")
        frm.pack(fill="x", **pad)
        for key, info in SCHEMES.items():
            status = "（可选用）" if info["installed"] else "（未安装/未实现）"
            ttk.Radiobutton(frm, text=info["label"] + status, value=key,
                            variable=self.scheme_var, command=self._on_scheme_change).pack(anchor="w", padx=8, pady=1)
        self.scheme_desc = ttk.Label(
            frm, text="", wraplength=700, justify="left", foreground="#444")
        self.scheme_desc.pack(anchor="w", padx=8, pady=4)

        # 资源目录 / 音色
        frm = ttk.LabelFrame(config_tab, text="4. 方案参数（资源目录 / 音色）")
        frm.pack(fill="x", **pad)

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=6, pady=2)
        self.resource_label = ttk.Label(row, text="资源目录（模型目录）:")
        self.resource_label.pack(side="left")
        self.resource_entry = ttk.Entry(
            row, textvariable=self.resource_dir_var)
        self.resource_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.resource_btn = ttk.Button(
            row, text="浏览…", command=self._pick_resource_dir)
        self.resource_btn.pack(side="right")

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="音色 / 说话人:").pack(side="left")
        self.voice_combo = ttk.Combobox(
            row, textvariable=self.voice_var, width=38)
        self.voice_combo.pack(side="left", padx=6)
        ttk.Label(row, text="sid:").pack(side="left")
        self.sid_combo = ttk.Combobox(
            row, textvariable=self.sid_var, width=28, state="readonly")
        self.sid_combo["values"] = SHERPA_SID_OPTIONS
        self.sid_combo.pack(side="left", padx=4)

        # CosyVoice 专属配置（模型目录 + 仓库路径 + conda python）
        self.cosy_frame = ttk.LabelFrame(
            config_tab, text="4b. CosyVoice 配置（仅选 CosyVoice 时生效）")
        self.cosy_frame.pack(fill="x", **pad)
        row = ttk.Frame(self.cosy_frame)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="模型目录:").pack(side="left")
        ttk.Entry(row, textvariable=self.cosy_model_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=self._pick_cosy_model).pack(side="right")
        row = ttk.Frame(self.cosy_frame)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="仓库目录:").pack(side="left")
        ttk.Entry(row, textvariable=self.cosy_repo_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=self._pick_cosy_repo).pack(side="right")
        row = ttk.Frame(self.cosy_frame)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="conda python.exe:").pack(side="left")
        ttk.Entry(row, textvariable=self.cosy_python_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=self._pick_cosy_python).pack(side="right")

        # 淡出
        frm = ttk.LabelFrame(config_tab, text="5. 结尾处理")
        frm.pack(fill="x", **pad)
        ttk.Checkbutton(frm, text="结尾淡出 + 补静音余韵（避免戛然而止）",
                        variable=self.fade_var).pack(anchor="w", padx=8, pady=2)
        row = ttk.Frame(frm)
        row.pack(anchor="w", padx=8, pady=2)
        ttk.Label(row, text="淡出时长(ms):").pack(side="left")
        ttk.Entry(row, textvariable=self.fade_ms_var,
                  width=8).pack(side="left", padx=6)
        ttk.Label(row, text="结尾补静音(ms):").pack(side="left")
        ttk.Entry(row, textvariable=self.tail_ms_var,
                  width=8).pack(side="left", padx=6)

        # edge-tts 保险（请求间隔 + 自动重试）
        frm = ttk.LabelFrame(
            config_tab, text="5b. edge-tts 保险（仅在线方案生效：请求间隔 + 自动重试）")
        frm.pack(fill="x", **pad)
        row = ttk.Frame(frm)
        row.pack(anchor="w", padx=8, pady=2)
        ttk.Label(row, text="请求间隔(秒):").pack(side="left")
        ttk.Entry(row, textvariable=self.edge_interval_var,
                  width=6).pack(side="left", padx=6)
        ttk.Label(row, text="最大重试次数:").pack(side="left")
        ttk.Entry(row, textvariable=self.edge_retries_var,
                  width=5).pack(side="left", padx=6)
        ttk.Label(row, text="重试等待基数(秒):").pack(side="left")
        ttk.Entry(row, textvariable=self.edge_retry_wait_var,
                  width=6).pack(side="left", padx=6)
        ttk.Label(
            row, text="重试等待按 1x/2x/3x 递增，避免触发限流", foreground="#888").pack(side="left", padx=6)

        # ========== 日志标签页 ==========
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text=" 日志 ")

        frm = ttk.LabelFrame(log_tab, text="运行日志")
        frm.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(frm, height=20, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both",
                           expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(frm, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

        # ========== 操作按钮（始终显示在底部） ==========
        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(anchor="w", **pad)
        self.start_btn = ttk.Button(
            btn_bar, text="开始生成", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.pause_btn = ttk.Button(
            btn_bar, text="暂停", command=self._pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(
            btn_bar, text="停止", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.test_btn = ttk.Button(
            btn_bar, text="试听测试（随机5条）", command=self._test_run)
        self.test_btn.pack(side="left", padx=(0, 6))

        # 保存日志标签页索引，用于切换
        self.log_tab_index = 1

        # 所有控件创建完毕后再初始化方案状态
        self._on_scheme_change()

        # 启动后异步拉取 edge-tts 音色列表
        threading.Thread(target=self._load_edge_voices, daemon=True).start()

    # ---------- 控制事件 ----------
    def _pause(self):
        """暂停/恢复 切换"""
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_btn.config(text="继续")
            self._log("[暂停] 已暂停")
            logger.info("生成已暂停")
        else:
            self._pause_event.set()
            self.pause_btn.config(text="暂停")
            self._log("[继续] 恢复生成")

    def _stop(self):
        """停止生成"""
        self._stop_event.set()
        self._pause_event.set()  # 若处于暂停状态，先恢复以便 worker 退出
        self._log("[停止] 正在停止...")
        logger.info("用户请求停止")

    def _reset_buttons(self):
        """所有按钮恢复初始状态"""
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled", text="暂停")
        self.stop_btn.config(state="disabled")
        self.test_btn.config(state="normal")
        self._gen_mode = "idle"

    def _switch_to_log_tab(self):
        """切换到日志标签页"""
        if hasattr(self, 'notebook'):
            self.notebook.select(self.log_tab_index)

    def _test_run(self):
        """试听测试：随机选5条生成音频"""
        json_path = self.json_var.get().strip()
        if not json_path or not os.path.isfile(json_path):
            messagebox.showwarning("提示", "请先选择有效的 JSON 脚本文件。")
            return
        scheme = self.scheme_var.get()
        info = SCHEMES[scheme]
        if not info["installed"]:
            messagebox.showwarning("提示", "该方案未安装或未实现。")
            return
        if info["need_resource_dir"]:
            # CosyVoice 使用 cosy_model_var，其他方案使用 resource_dir_var
            if scheme == "cosyvoice":
                if not self.cosy_model_var.get().strip():
                    messagebox.showwarning("提示", "CosyVoice 需要指定模型目录。")
                    return
            elif not self.resource_dir_var.get().strip():
                messagebox.showwarning("提示", "该方案需要指定资源目录。")
                return

        self._save_config()  # 点击测试前保存配置
        self._switch_to_log_tab()  # 自动切换到日志标签页
        self._stop_event.clear()
        self._pause_event.set()
        self._gen_mode = "test"
        self.start_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self._log("=" * 50)
        self._log("试听测试：随机选取最多5条数据...")

        self.worker = threading.Thread(target=self._test_work, daemon=True)
        self.worker.start()

    def _test_work(self):
        """测试生成线程"""
        try:
            json_path = self.json_var.get().strip()
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            texts = []
            for it in items:
                if isinstance(it, dict) and it.get("plotContent"):
                    texts.append(it["plotContent"])
            if not texts:
                self.msg_queue.put(("error", "JSON 中未找到 plotContent 字段。"))
                return

            sample = random.sample(texts, min(5, len(texts)))
            test_dir = os.path.join(
                os.path.dirname(json_path),
                "_test_audio_" + time.strftime("%H%M%S"))
            os.makedirs(test_dir, exist_ok=True)

            scheme = self.scheme_var.get()
            gen = GENERATORS[scheme]
            resource_dir = self.resource_dir_var.get().strip() or None
            voice = self.voice_var.get().strip()
            # sid 格式可能是 "0 - 温柔女声..." 或纯数字 "0"
            sid_raw = self.sid_var.get().strip() or "0"
            sid = sid_raw.split(" - ")[0] if " - " in sid_raw else sid_raw

            generated = []
            for idx, text in enumerate(sample, start=1):
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                name = "test_%03d.wav" % idx
                out_path = os.path.join(test_dir, name)
                self.msg_queue.put(("log", "测试 %d/%d: %s ..." % (idx, len(sample), name)))
                self._dispatch_gen(gen, text, out_path, scheme, resource_dir, voice, sid)
                generated.append(out_path)

            # 尝试播放第一个音频
            if generated and not self._stop_event.is_set():
                self._play_audio(generated[0])

            if self._stop_event.is_set():
                self.msg_queue.put(("stopped", "测试已停止"))
            else:
                self.msg_queue.put(("test_done", "试听完成，共生成 %d 段音频到：\n%s" % (len(generated), test_dir)))
        except Exception as e:
            traceback.print_exc()
            self.msg_queue.put(("error", "测试失败：%s" % e))

    def _dispatch_gen(self, gen, text, out_path, scheme, resource_dir, voice, sid):
        """统一调度各方案生成函数（edge-tts 自动加请求间隔与重试）"""
        if scheme == "edge-tts":
            # 每段之间 sleep，避免高频请求触发微软限流
            interval = float(self.edge_interval_var.get() or 0.8)
            if interval > 0:
                time.sleep(interval)
            try:
                retries = int(self.edge_retries_var.get() or 3)
                retry_wait = float(self.edge_retry_wait_var.get() or 5)
            except ValueError:
                retries, retry_wait = 3, 5
            gen(text, out_path, voice, self._thread_log,
                retries=max(1, retries), retry_wait=max(0.5, retry_wait))
        elif scheme in ("pyttsx3",):
            gen(text, out_path, voice, self._thread_log)
        elif scheme == "sherpa-onnx":
            gen(text, out_path, resource_dir, sid, self._thread_log)
        elif scheme == "cosyvoice":
            # CosyVoice 使用专属的 cosy_model_var 作为模型目录
            cosy_model_dir = self.cosy_model_var.get().strip()
            gen(text, out_path, cosy_model_dir, voice, self._thread_log,
                repo_dir=self.cosy_repo_var.get().strip(),
                conda_python=self.cosy_python_var.get().strip())
        else:
            gen(text, out_path, resource_dir, self._thread_log)

    def _play_audio(self, wav_path):
        """尝试播放音频文件"""
        try:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                if sys.platform == "darwin":
                    cmd = ["afplay", wav_path]
                else:
                    cmd = ["aplay", wav_path]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=_NO_WINDOW)
            self._thread_log("  [播放] %s" % os.path.basename(wav_path))
        except Exception as e:
            self._thread_log("  [提示] 自动播放失败: %s" % e)

    def _pick_json(self):
        p = filedialog.askopenfilename(
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if p:
            self.json_var.set(p)

    def _pick_out_dir(self):
        p = filedialog.askdirectory()
        if p:
            self.out_dir_var.set(p)

    def _pick_resource_dir(self):
        p = filedialog.askdirectory()
        if p:
            self.resource_dir_var.set(p)

    def _pick_cosy_model(self):
        p = filedialog.askdirectory()
        if p:
            self.cosy_model_var.set(p)

    def _pick_cosy_repo(self):
        p = filedialog.askdirectory()
        if p:
            self.cosy_repo_var.set(p)

    def _pick_cosy_python(self):
        p = filedialog.askopenfilename(
            filetypes=[("python.exe", "python.exe"), ("所有文件", "*.*")])
        if p:
            self.cosy_python_var.set(p)

    def _on_scheme_change(self):
        key = self.scheme_var.get()
        info = SCHEMES[key]
        self.scheme_desc.config(text=info["desc"])
        # 资源目录开关（CosyVoice 使用专属的 4b 配置区，此处禁用）
        if info["need_resource_dir"] and key != "cosyvoice":
            self.resource_label.config(state="normal")
            self.resource_entry.config(state="normal")
            self.resource_btn.config(state="normal")
        else:
            self.resource_label.config(state="disabled")
            self.resource_entry.config(state="disabled")
            self.resource_btn.config(state="disabled")

        # 音色/sid 显隐
        if key == "sherpa-onnx":
            self.sid_combo.config(state="readonly")
            self.voice_combo.config(state="disabled")
            self._set_cosy_frame(False)
        elif key == "edge-tts":
            self.sid_combo.config(state="disabled")
            self.voice_combo.config(state="readonly")
            if self.edge_voices:
                self.voice_combo["values"] = self.edge_voices
            self._set_cosy_frame(False)
        elif key == "pyttsx3":
            self.sid_combo.config(state="disabled")
            self.voice_combo.config(state="disabled")
            self._set_cosy_frame(False)
        else:  # cosyvoice
            self.sid_combo.config(state="disabled")
            self.voice_combo.config(state="readonly")
            self.voice_combo["values"] = COSYVOICE_SPK_OPTIONS
            if self.voice_var.get() not in COSYVOICE_SPK_OPTIONS:
                self.voice_var.set("中文女")
            self._set_cosy_frame(True)

    def _set_cosy_frame(self, show):
        """显示/隐藏 CosyVoice 配置区"""
        if hasattr(self, "cosy_frame"):
            if show:
                self.cosy_frame.pack(fill="x", padx=10, pady=4)
            else:
                self.cosy_frame.pack_forget()

    def _load_edge_voices(self):
        try:
            import asyncio
            if sys.platform == "win32":
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            voices = asyncio.run(edge_tts.list_voices())
            zh = [v["ShortName"]
                  for v in voices if v.get("Locale", "").startswith("zh")]
            if not zh:
                zh = [v["ShortName"] for v in voices]
            self.edge_voices = zh
            self.msg_queue.put(("voices", zh))
        except Exception as e:
            self.msg_queue.put(
                ("log", "[提示] edge-tts 音色列表加载失败（若未联网或未安装则忽略）: %s" % e))

    # ---------- 日志 ----------
    def _log(self, s):
        self.log_text.config(state="normal")
        self.log_text.insert("end", s + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _after_poll(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "voices":
                    if self.scheme_var.get() == "edge-tts":
                        self.voice_combo["values"] = payload
                        if self.voice_var.get() not in payload:
                            self.voice_var.set(
                                EDGE_DEFAULT_VOICE if EDGE_DEFAULT_VOICE in payload else payload[0])
                    self._log("[提示] 已加载 %d 个中文音色可选" % len(payload))
                elif kind == "done":
                    self._reset_buttons()
                    self._log(payload)
                    messagebox.showinfo("完成", payload)
                elif kind == "test_done":
                    self._reset_buttons()
                    self._log(payload)
                    messagebox.showinfo("试听完成", payload)
                elif kind == "stopped":
                    self._reset_buttons()
                    self._log("[停止] " + payload)
                elif kind == "error":
                    self._reset_buttons()
                    self._log("[错误] " + payload)
                    messagebox.showerror("出错", payload)
        except queue.Empty:
            pass
        self.root.after(120, self._after_poll)

    # ---------- 执行 ----------
    def _start(self):
        json_path = self.json_var.get().strip()
        out_dir = self.out_dir_var.get().strip()
        scheme = self.scheme_var.get()

        # 校验
        if not json_path or not os.path.isfile(json_path):
            messagebox.showwarning("提示", "请先选择有效的 JSON 脚本文件。")
            return
        if not out_dir:
            messagebox.showwarning("提示", "请先选择输出目录。")
            return
        info = SCHEMES[scheme]
        if not info["installed"]:
            messagebox.showwarning("提示", "该方案未安装或未实现：\n" + info["desc"])
            return
        if info["need_resource_dir"]:
            # CosyVoice 使用 cosy_model_var，其他方案使用 resource_dir_var
            if scheme == "cosyvoice":
                if not self.cosy_model_var.get().strip():
                    messagebox.showwarning("提示", "CosyVoice 需要指定模型目录。")
                    return
            elif not self.resource_dir_var.get().strip():
                messagebox.showwarning("提示", "该方案需要指定资源目录（模型目录）。")
                return
        if scheme == "sherpa-onnx" and not HAS_PYDUB:
            # sherpa 直接写 wav，不需要 pydub；但淡出需要
            pass

        self._stop_event.clear()
        self._pause_event.set()
        self._gen_mode = "gen"

        self._save_config()
        self._switch_to_log_tab()  # 自动切换到日志标签页

        self.start_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.stop_btn.config(state="normal")
        self._log("=" * 50)
        self._log("开始生成：方案=%s" % scheme)

        self.worker = threading.Thread(target=self._work, args=(
            json_path, out_dir, scheme), daemon=True)
        self.worker.start()

    def _work(self, json_path, out_dir, scheme):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            texts = []
            for it in items:
                if isinstance(it, dict) and it.get("plotContent"):
                    texts.append(it["plotContent"])

            if not texts:
                self.msg_queue.put(("error", "JSON 中未找到 plotContent 字段。"))
                return

            os.makedirs(out_dir, exist_ok=True)
            gen = GENERATORS[scheme]
            resource_dir = self.resource_dir_var.get().strip() or None
            voice = self.voice_var.get().strip()
            # sid 格式可能是 "0 - 温柔女声..." 或纯数字 "0"
            sid_raw = self.sid_var.get().strip() or "0"
            sid = sid_raw.split(" - ")[0] if " - " in sid_raw else sid_raw
            fade = self.fade_var.get()
            fade_ms = int(self.fade_ms_var.get() or 1200)
            tail_ms = int(self.tail_ms_var.get() or 900)

            for idx, text in enumerate(texts, start=1):
                # 检查停止
                if self._stop_event.is_set():
                    break
                # 检查暂停（阻塞等待恢复）
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                name = "%03d.wav" % idx
                out_path = os.path.join(out_dir, name)
                self.msg_queue.put(("log", "生成 %s ..." % name))
                self._dispatch_gen(gen, text, out_path, scheme, resource_dir, voice, sid)

                if fade and os.path.exists(out_path):
                    apply_fade_out(out_path, fade_ms, tail_ms)
                    self._thread_log("  [淡出] 已处理 %s" % name)

            if self._stop_event.is_set():
                self.msg_queue.put(("stopped", "生成已停止"))
            else:
                self.msg_queue.put(
                    ("done", "全部完成，共生成 %d 段音频到：\n%s" % (len(texts), out_dir)))
        except NotImplementedError as e:
            self.msg_queue.put(("error", str(e)))
        except Exception as e:
            traceback.print_exc()
            self.msg_queue.put(("error", "生成失败：%s" % e))

    def _thread_log(self, s):
        self.msg_queue.put(("log", s))

    # ---------- 配置持久化 ----------
    def _save_config(self):
        config = {
            "last_json": self.json_var.get(),
            "out_dir": self.out_dir_var.get(),
            "scheme": self.scheme_var.get(),
            "resource_dir": self.resource_dir_var.get(),
            "voice": self.voice_var.get(),
            "sid": self.sid_var.get(),
            "fade": self.fade_var.get(),
            "fade_ms": self.fade_ms_var.get(),
            "tail_ms": self.tail_ms_var.get(),
            "edge_interval": self.edge_interval_var.get(),
            "edge_retries": self.edge_retries_var.get(),
            "edge_retry_wait": self.edge_retry_wait_var.get(),
            "cosy_model": self.cosy_model_var.get(),
            "cosy_repo": self.cosy_repo_var.get(),
            "cosy_python": self.cosy_python_var.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s" % CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s" % e)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("last_json"):
                    self.json_var.set(cfg["last_json"])
                if cfg.get("out_dir"):
                    self.out_dir_var.set(cfg["out_dir"])
                if cfg.get("scheme") and cfg["scheme"] in SCHEMES:
                    self.scheme_var.set(cfg["scheme"])
                if cfg.get("resource_dir"):
                    self.resource_dir_var.set(cfg["resource_dir"])
                if cfg.get("voice"):
                    self.voice_var.set(cfg["voice"])
                if cfg.get("sid"):
                    self.sid_var.set(cfg["sid"])
                if "fade" in cfg:
                    self.fade_var.set(cfg["fade"])
                if cfg.get("fade_ms"):
                    self.fade_ms_var.set(cfg["fade_ms"])
                if cfg.get("tail_ms"):
                    self.tail_ms_var.set(cfg["tail_ms"])
                if cfg.get("edge_interval"):
                    self.edge_interval_var.set(cfg["edge_interval"])
                if cfg.get("edge_retries"):
                    self.edge_retries_var.set(cfg["edge_retries"])
                if cfg.get("edge_retry_wait"):
                    self.edge_retry_wait_var.set(cfg["edge_retry_wait"])
                if cfg.get("cosy_model"):
                    self.cosy_model_var.set(cfg["cosy_model"])
                if cfg.get("cosy_repo"):
                    self.cosy_repo_var.set(cfg["cosy_repo"])
                if cfg.get("cosy_python"):
                    self.cosy_python_var.set(cfg["cosy_python"])
                # 配置加载后刷新方案状态（显示/隐藏 CosyVoice 配置区等）
                self._on_scheme_change()
                logger.info("已加载配置: %s" % CONFIG_PATH)
        except Exception as e:
            logger.error("加载配置失败: %s" % e)


def main_cli():
    """命令行模式：无 GUI，直接生成音频"""
    import argparse
    parser = argparse.ArgumentParser(description="绘本旁白音频生成器（CLI模式）")
    parser.add_argument("--json", required=True, help="JSON 脚本文件路径")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument("--scheme", help="生成方案（默认读取配置）")
    parser.add_argument("--voice", help="音色（edge-tts）")
    parser.add_argument("--sid", help="音色ID（sherpa-onnx）")
    args = parser.parse_args()

    # 读取配置作为默认值
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    scheme = args.scheme or cfg.get("scheme", "edge-tts")
    voice = args.voice or cfg.get("voice", EDGE_DEFAULT_VOICE)
    sid_raw = args.sid or cfg.get("sid", "0")
    sid = sid_raw.split(" - ")[0] if " - " in sid_raw else sid_raw
    resource_dir = cfg.get("resource_dir", "") or None
    fade = cfg.get("fade", True)
    fade_ms = int(cfg.get("fade_ms", 1200) or 1200)
    tail_ms = int(cfg.get("tail_ms", 900) or 900)
    edge_interval = float(cfg.get("edge_interval", 0.8) or 0.8)
    edge_retries = int(cfg.get("edge_retries", 3) or 3)
    edge_retry_wait = float(cfg.get("edge_retry_wait", 5) or 5)

    # 读取 JSON
    print(f"[INFO] 读取 JSON: {args.json}")
    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else [data]
    texts = [it["plotContent"] for it in items if isinstance(it, dict) and it.get("plotContent")]
    if not texts:
        print("[ERROR] JSON 中未找到 plotContent 字段")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)
    gen = GENERATORS.get(scheme)
    if not gen:
        print(f"[ERROR] 未知方案: {scheme}")
        sys.exit(1)

    print(f"[INFO] 方案: {scheme}, 共 {len(texts)} 段文本")
    for idx, text in enumerate(texts, start=1):
        name = "%03d.wav" % idx
        out_path = os.path.join(args.output, name)
        print(f"[INFO] 生成 {name} ...")
        try:
            if scheme == "edge-tts":
                time.sleep(edge_interval)
                gen(text, out_path, voice, lambda s: print(f"  {s}"),
                    retries=edge_retries, retry_wait=edge_retry_wait)
            elif scheme == "pyttsx3":
                gen(text, out_path, voice, lambda s: print(f"  {s}"))
            elif scheme == "sherpa-onnx":
                gen(text, out_path, resource_dir, sid, lambda s: print(f"  {s}"))
            else:
                gen(text, out_path, resource_dir, lambda s: print(f"  {s}"))

            if fade and os.path.exists(out_path):
                apply_fade_out(out_path, fade_ms, tail_ms)
                print(f"  [淡出] 已处理")
        except Exception as e:
            print(f"[ERROR] {name} 生成失败: {e}")
            continue

    print(f"[DONE] 共生成 {len(texts)} 段音频到: {args.output}")


def main():
    # 检查是否有命令行参数（排除脚本名本身）
    if len(sys.argv) > 1 and sys.argv[1] in ("--json", "--output", "-h", "--help"):
        main_cli()
        return

    root = tk.Tk()
    # 主题
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
