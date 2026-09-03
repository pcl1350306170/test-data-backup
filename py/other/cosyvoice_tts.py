# -*- coding: utf-8 -*-
"""
CosyVoice 本地 TTS 生成器（GUI 版）
====================================
运行环境要求：
  1. 主脚本本身运行在任意 Python 3.8+ 环境（无需 CosyVoice 依赖），
     只用到 tkinter（标准库自带）。
  2. 真正的 CosyVoice 推理由本脚本通过 subprocess 拉起独立 worker
     (cosyvoice_tts_worker.py) 完成，worker 必须在 CosyVoice 专用 conda
     环境中执行，默认解释器路径：
         D:\\TOOLS\\miniconda3\\envs\\cosyvoice\\python.exe
  3. 需提前下载模型到指定目录，默认：
         模型: D:\\dev\\sherpa-models\\CosyVoice2-0.5B
         仓库: D:\\dev\\sherpa-models\\CosyVoice
  4. ffmpeg 需在系统 PATH 中（语速调整 + MP3 转换）。

运行方式：
  python cosyvoice_tts.py
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ---------- 路径与常量 ----------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "cosyvoice_tts"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# Worker 脚本（与本脚本同目录）
WORKER_PATH = SCRIPT_DIR / "cosyvoice_tts_worker.py"

# ---------- 默认配置 ----------
DEFAULT_MODEL_DIR = r"D:\dev\sherpa-models\CosyVoice2-0.5B"
DEFAULT_REPO_DIR = r"D:\dev\sherpa-models\CosyVoice"
DEFAULT_CONDA_PY = r"D:\TOOLS\miniconda3\envs\cosyvoice\python.exe"
DEFAULT_SPK = "中文女"
DEFAULT_STYLE = ""
DEFAULT_SPEED = 1.0
DEFAULT_FORMAT = "wav"
DEFAULT_OUT_DIR = r"C:\Users\PCL13\Downloads"
DEFAULT_SEG_LEN = 500

# 预置音色（可手动输入自定义值）
SPK_OPTIONS = ["中文女", "中文男", "英文女", "英文男", "日语男", "粤语女", "韩语女"]

# 预置情感风格（可手动输入自定义值）
STYLE_OPTIONS = ["", "开心", "温柔", "严肃", "活泼", "深情"]

# 语速快捷选项
SPEED_OPTIONS = ["0.8", "1.0", "1.2", "1.5"]

# subprocess 静默标记（Windows）
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ---------- 日志模块（可选依赖，失败降级） ----------
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


# ============================================================
# 配置持久化
# ============================================================
def load_config():
    """加载配置；不存在或解析失败返回默认值"""
    cfg = {
        "model_dir": DEFAULT_MODEL_DIR,
        "repo_dir": DEFAULT_REPO_DIR,
        "conda_python": DEFAULT_CONDA_PY,
        "spk": DEFAULT_SPK,
        "style": DEFAULT_STYLE,
        "speed": DEFAULT_SPEED,
        "format": DEFAULT_FORMAT,
        "out_dir": DEFAULT_OUT_DIR,
        "seg_len": DEFAULT_SEG_LEN,
        "prefix": "",
        "prompt_audio": "",
        "prompt_text": "",
    }
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                cfg.update({k: v for k, v in saved.items() if k in cfg})
            logger.info("已加载配置: %s", CONFIG_PATH)
    except Exception as e:
        logger.error("加载配置失败，使用默认值: %s", e)
    return cfg


def save_config(cfg):
    """保存配置到 json"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存: %s", CONFIG_PATH)
    except Exception as e:
        logger.error("保存配置失败: %s", e)


# ============================================================
# 文本切段
# ============================================================
_SENT_ENDS = set("。！？!?\n；;")


def split_text(text, max_chars=DEFAULT_SEG_LEN):
    """按 max_chars 软上限切段，尽量在句末标点结束。
    单句超过 2*max_chars 时强制硬切，避免超长文本导致 OOM。
    """
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
# ffmpeg 后处理（语速 / MP3）
# ============================================================
def _check_ffmpeg():
    return shutil.which("ffmpeg") is not None


def _build_atempo_filter(speed):
    """atempo 单次范围 0.5~2.0，超出则级联"""
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


def apply_speed(wav_path, speed, log=print):
    """用 ffmpeg atempo 调整 wav 语速；speed≈1.0 时跳过"""
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        return
    if abs(speed - 1.0) < 0.01:
        return
    if not _check_ffmpeg():
        log("  [警告] 未找到 ffmpeg，语速调整已跳过")
        logger.warning("ffmpeg 未安装，无法调整语速")
        return
    tmp_path = wav_path + ".tmp.wav"
    af = _build_atempo_filter(speed)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-filter:a", af, tmp_path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=_NO_WINDOW)
        if proc.returncode != 0 or not os.path.isfile(tmp_path):
            err = (proc.stderr or "").strip()[-500:]
            log(f"  [错误] ffmpeg 调速失败: {err}")
            logger.error("ffmpeg atempo 失败: %s", err)
            return
        os.replace(tmp_path, wav_path)
        log(f"  [调速] {speed}x 已应用")
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def wav_to_mp3(wav_path, mp3_path, log=print):
    """用 ffmpeg 将 wav 转 mp3；成功返回 True"""
    if not _check_ffmpeg():
        log("  [警告] 未找到 ffmpeg，MP3 转换已跳过")
        logger.warning("ffmpeg 未安装，无法转 MP3")
        return False
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path,
             "-codec:a", "libmp3lame", "-qscale:a", "2", mp3_path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=_NO_WINDOW)
        if proc.returncode != 0 or not os.path.isfile(mp3_path):
            err = (proc.stderr or "").strip()[-500:]
            log(f"  [错误] ffmpeg 转 MP3 失败: {err}")
            logger.error("ffmpeg 转 MP3 失败: %s", err)
            return False
        return True
    except Exception as e:
        log(f"  [错误] ffmpeg 转 MP3 异常: {e}")
        logger.error("ffmpeg 转 MP3 异常: %s", e)
        return False


# ============================================================
# 调用 CosyVoice Worker
# ============================================================
def call_worker(text, out_wav, cfg, log=print):
    """通过 subprocess 调用 worker 生成 wav。成功返回 True。"""
    if not WORKER_PATH.is_file():
        raise RuntimeError(f"找不到 worker 脚本: {WORKER_PATH}")

    model_dir = cfg["model_dir"]
    repo_dir = cfg["repo_dir"]
    conda_py = cfg["conda_python"]

    if not os.path.isdir(model_dir):
        raise RuntimeError(f"模型目录不存在: {model_dir}")
    if not os.path.isfile(conda_py):
        raise RuntimeError(
            f"conda python 不存在: {conda_py}\n"
            f"  请先安装 CosyVoice conda 环境，或指定正确的 python.exe 路径")

    # 构造 PYTHONPATH：仓库根目录 + third_party/Matcha-TTS
    env = dict(os.environ)
    if repo_dir and os.path.isdir(repo_dir):
        paths = [repo_dir, os.path.join(repo_dir, "third_party", "Matcha-TTS")]
        cur = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in paths if p] + ([cur] if cur else []))
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [conda_py, str(WORKER_PATH),
           "--model_dir", model_dir,
           "--text", text,
           "--output", out_wav,
           "--spk", cfg.get("spk") or DEFAULT_SPK]
    style = (cfg.get("style") or "").strip()
    if style:
        cmd += ["--style", style]
    # Zero-Shot 音色复刻参数
    prompt_audio = (cfg.get("prompt_audio") or "").strip()
    prompt_text = (cfg.get("prompt_text") or "").strip()
    if prompt_audio and prompt_text:
        cmd += ["--prompt_audio", prompt_audio, "--prompt_text", prompt_text]

    mode_desc = "zero-shot" if (prompt_audio and prompt_text) else ("instruct2" if style else "sft")
    log(f"  [worker] 调用 CosyVoice({mode_desc}): {os.path.basename(out_wav)}")
    logger.info("调用 worker: mode=%s spk=%s style=%s text_len=%d",
                mode_desc, cfg.get("spk"), style, len(text))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=900, env=env, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError("CosyVoice 生成超时（>15分钟），可能模型未就绪或显存不足")
    except FileNotFoundError:
        raise RuntimeError(f"找不到 Python 解释器: {conda_py}")

    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RuntimeError(f"CosyVoice 生成失败: {err[-1500:]}")

    if not os.path.isfile(out_wav):
        raise RuntimeError("Worker 未产出文件，请检查模型路径与音色参数")
    return True


# ============================================================
# 文件命名
# ============================================================
def _safe_name(s):
    """过滤文件名中的非法字符"""
    if not s:
        return ""
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in s).strip()


def build_out_paths(out_dir, segments_count, cfg, timestamp=None):
    """根据段数生成输出文件路径列表"""
    ts = timestamp or time.strftime("%Y%m%d_%H%M%S")
    prefix = _safe_name(cfg.get("prefix") or "")
    spk = _safe_name(cfg.get("spk") or DEFAULT_SPK)
    style = _safe_name(cfg.get("style") or "")
    base_parts = [p for p in (prefix or spk, style, ts) if p]
    base = "_".join(base_parts)

    ext = (cfg.get("format") or DEFAULT_FORMAT).lower()
    if ext not in ("wav", "mp3"):
        ext = "wav"

    paths = []
    for i in range(segments_count):
        if segments_count == 1:
            name = f"{base}.{ext}"
        else:
            name = f"{base}-{i+1:03d}.{ext}"
        paths.append(os.path.join(out_dir, name))
    return paths


# ============================================================
# GUI 主程序
# ============================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("CosyVoice 本地 TTS 生成器")
        root.geometry("780x820")
        root.minsize(700, 700)
        # 尝试最大化
        try:
            root.state("zoomed")
        except Exception:
            pass

        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self._stop_event = threading.Event()

        # 变量
        self.text_content = ""           # 当前文本内容
        self.txt_file_path = ""          # 已导入的 txt 文件路径
        self.spk_var = tk.StringVar(value=DEFAULT_SPK)
        self.style_var = tk.StringVar(value=DEFAULT_STYLE)
        self.speed_var = tk.StringVar(value=str(DEFAULT_SPEED))
        self.format_var = tk.StringVar(value=DEFAULT_FORMAT)
        self.out_dir_var = tk.StringVar(value=DEFAULT_OUT_DIR)
        self.prefix_var = tk.StringVar(value="")
        self.seg_len_var = tk.StringVar(value=str(DEFAULT_SEG_LEN))
        self.model_dir_var = tk.StringVar(value=DEFAULT_MODEL_DIR)
        self.repo_dir_var = tk.StringVar(value=DEFAULT_REPO_DIR)
        self.conda_py_var = tk.StringVar(value=DEFAULT_CONDA_PY)
        self.prompt_audio_var = tk.StringVar(value="")
        self.prompt_text_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.open_dir_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._load_config_to_ui()
        self._after_poll()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # 使用 Notebook 分两页：配置 / 日志
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, **pad)

        # ===== 配置页 =====
        cfg_tab = ttk.Frame(self.notebook)
        self.notebook.add(cfg_tab, text=" 配置 ")

        # --- 文本输入区 ---
        frm_text = ttk.LabelFrame(cfg_tab, text="1. 文本内容")
        frm_text.pack(fill="both", expand=True, padx=10, pady=4)

        btn_row = ttk.Frame(frm_text)
        btn_row.pack(fill="x", padx=6, pady=2)
        ttk.Button(btn_row, text="导入 TXT 文件", command=self._import_txt).pack(side="left", padx=4)
        ttk.Button(btn_row, text="清空文本", command=self._clear_text).pack(side="left", padx=4)
        self.lbl_text_info = ttk.Label(btn_row, text="可直接粘贴文本，或导入 TXT 文件", foreground="#666")
        self.lbl_text_info.pack(side="left", padx=10)

        text_frame = ttk.Frame(frm_text)
        text_frame.pack(fill="both", expand=True, padx=6, pady=4)
        self.txt_widget = tk.Text(text_frame, height=8, wrap="word", font=("Microsoft YaHei UI", 10))
        self.txt_widget.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(text_frame, command=self.txt_widget.yview)
        sb.pack(side="right", fill="y")
        self.txt_widget.config(yscrollcommand=sb.set)

        # --- 音色 / 风格 / 语速 / 格式 ---
        frm_voice = ttk.LabelFrame(cfg_tab, text="2. 音色 / 风格 / 语速 / 格式")
        frm_voice.pack(fill="x", padx=10, pady=4)

        row = ttk.Frame(frm_voice)
        row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="音色:").pack(side="left")
        self.spk_combo = ttk.Combobox(row, textvariable=self.spk_var, width=12, values=SPK_OPTIONS)
        self.spk_combo.pack(side="left", padx=6)
        ttk.Label(row, text="风格:").pack(side="left", padx=(16, 0))
        self.style_combo = ttk.Combobox(row, textvariable=self.style_var, width=12, values=STYLE_OPTIONS)
        self.style_combo.pack(side="left", padx=6)
        ttk.Label(row, text="语速:").pack(side="left", padx=(16, 0))
        self.speed_combo = ttk.Combobox(row, textvariable=self.speed_var, width=6, values=SPEED_OPTIONS)
        self.speed_combo.pack(side="left", padx=6)
        ttk.Label(row, text="格式:").pack(side="left", padx=(16, 0))
        ttk.Radiobutton(row, text="WAV", value="wav", variable=self.format_var).pack(side="left", padx=4)
        ttk.Radiobutton(row, text="MP3", value="mp3", variable=self.format_var).pack(side="left", padx=4)

        row2 = ttk.Frame(frm_voice)
        row2.pack(fill="x", padx=6, pady=3)
        ttk.Label(row2, text="切段字数:").pack(side="left")
        ttk.Entry(row2, textvariable=self.seg_len_var, width=8).pack(side="left", padx=6)
        ttk.Label(row2, text="文件名前缀:").pack(side="left", padx=(16, 0))
        ttk.Entry(row2, textvariable=self.prefix_var, width=18).pack(side="left", padx=6)
        ttk.Label(row2, text="（留空则用音色名）", foreground="#888").pack(side="left")

        # --- 参考音频（Zero-Shot 音色复刻） ---
        frm_clone = ttk.LabelFrame(cfg_tab, text="2b. 参考音频（Zero-Shot 音色复刻，可选）")
        frm_clone.pack(fill="x", padx=10, pady=4)

        row_audio = ttk.Frame(frm_clone)
        row_audio.pack(fill="x", padx=6, pady=2)
        ttk.Label(row_audio, text="参考音频:", width=12).pack(side="left")
        self.prompt_audio_entry = ttk.Entry(row_audio, textvariable=self.prompt_audio_var)
        self.prompt_audio_entry.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row_audio, text="选择音频…", command=self._pick_prompt_audio).pack(side="right")
        ttk.Button(row_audio, text="清除", command=self._clear_prompt_audio, width=5).pack(side="right", padx=2)

        row_ptext = ttk.Frame(frm_clone)
        row_ptext.pack(fill="x", padx=6, pady=2)
        ttk.Label(row_ptext, text="音频对应文本:", width=12).pack(side="left")
        ttk.Entry(row_ptext, textvariable=self.prompt_text_var).pack(side="left", fill="x", expand=True, padx=4)

        self.lbl_clone_hint = ttk.Label(
            frm_clone,
            text="提示：选择参考音频后，将使用 Zero-Shot 复刻该音频的音色，上方\"音色\"下拉框将被忽略。\n"
                 "      参考音频建议 3~10 秒清晰人声；\"音频对应文本\"填写该录音中说的话。",
            foreground="#666", wraplength=700, justify="left")
        self.lbl_clone_hint.pack(anchor="w", padx=6, pady=2)

        # --- 输出目录 ---
        frm_out = ttk.LabelFrame(cfg_tab, text="3. 输出目录")
        frm_out.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_out)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Entry(row, textvariable=self.out_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_out_dir).pack(side="right", padx=4)
        ttk.Checkbutton(row, text="完成后打开目录", variable=self.open_dir_var).pack(side="right", padx=8)

        # --- 环境配置 ---
        frm_env = ttk.LabelFrame(cfg_tab, text="4. CosyVoice 环境配置")
        frm_env.pack(fill="x", padx=10, pady=4)

        row = ttk.Frame(frm_env)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="模型目录:", width=14).pack(side="left")
        ttk.Entry(row, textvariable=self.model_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_model_dir).pack(side="right")

        row = ttk.Frame(frm_env)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="仓库目录:", width=14).pack(side="left")
        ttk.Entry(row, textvariable=self.repo_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_repo_dir).pack(side="right")

        row = ttk.Frame(frm_env)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="conda python:", width=14).pack(side="left")
        ttk.Entry(row, textvariable=self.conda_py_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_conda_py).pack(side="right")

        # ===== 日志页 =====
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text=" 日志 ")
        frm_log = ttk.Frame(log_tab)
        frm_log.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(frm_log, height=20, wrap="word", state="disabled",
                                font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        log_sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=log_sb.set)

        # ===== 底部操作栏 =====
        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(fill="x", padx=10, pady=6)

        self.start_btn = ttk.Button(btn_bar, text="开始生成", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(btn_bar, text="停止", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))

        # 进度条
        self.progress_bar = ttk.Progressbar(btn_bar, variable=self.progress_var,
                                            maximum=100, length=200)
        self.progress_bar.pack(side="left", padx=16)
        self.lbl_status = ttk.Label(btn_bar, textvariable=self.status_var, foreground="#333")
        self.lbl_status.pack(side="left", padx=8)

    # ---------- 浏览按钮 ----------
    def _import_txt(self):
        path = filedialog.askopenfilename(
            title="选择 TXT 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="gbk", errors="replace") as f:
                content = f.read()
        self.txt_widget.delete("1.0", "end")
        self.txt_widget.insert("1.0", content)
        self.txt_file_path = path
        self.lbl_text_info.config(text=f"已导入: {os.path.basename(path)}（{len(content)} 字符）")
        self._log(f"[导入] {path}，共 {len(content)} 字符")

    def _clear_text(self):
        self.txt_widget.delete("1.0", "end")
        self.txt_file_path = ""
        self.lbl_text_info.config(text="可直接粘贴文本，或导入 TXT 文件")

    def _pick_out_dir(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.out_dir_var.set(p)

    def _pick_model_dir(self):
        p = filedialog.askdirectory(title="选择 CosyVoice 模型目录")
        if p:
            self.model_dir_var.set(p)

    def _pick_repo_dir(self):
        p = filedialog.askdirectory(title="选择 CosyVoice 仓库目录")
        if p:
            self.repo_dir_var.set(p)

    def _pick_conda_py(self):
        p = filedialog.askopenfilename(
            title="选择 conda 环境的 python.exe",
            filetypes=[("python.exe", "python.exe"), ("所有文件", "*.*")])
        if p:
            self.conda_py_var.set(p)

    def _pick_prompt_audio(self):
        p = filedialog.askopenfilename(
            title="选择参考音频文件（建议 3~10 秒清晰人声）",
            filetypes=[("音频文件", "*.wav *.mp3 *.flac *.ogg *.m4a"), ("所有文件", "*.*")])
        if p:
            self.prompt_audio_var.set(p)
            self._update_spk_state()
            self._log(f"[参考音频] 已选择: {p}")

    def _clear_prompt_audio(self):
        self.prompt_audio_var.set("")
        self.prompt_text_var.set("")
        self._update_spk_state()
        self._log("[参考音频] 已清除，将使用预置音色")

    def _update_spk_state(self):
        """有参考音频时禁用音色下拉框（以复刻音色为准）"""
        if self.prompt_audio_var.get().strip():
            self.spk_combo.config(state="disabled")
        else:
            self.spk_combo.config(state="normal")

    # ---------- 配置 ----------
    def _load_config_to_ui(self):
        cfg = load_config()
        self.spk_var.set(cfg.get("spk", DEFAULT_SPK))
        self.style_var.set(cfg.get("style", DEFAULT_STYLE))
        self.speed_var.set(str(cfg.get("speed", DEFAULT_SPEED)))
        self.format_var.set(cfg.get("format", DEFAULT_FORMAT))
        self.out_dir_var.set(cfg.get("out_dir", DEFAULT_OUT_DIR))
        self.prefix_var.set(cfg.get("prefix", ""))
        self.seg_len_var.set(str(cfg.get("seg_len", DEFAULT_SEG_LEN)))
        self.model_dir_var.set(cfg.get("model_dir", DEFAULT_MODEL_DIR))
        self.repo_dir_var.set(cfg.get("repo_dir", DEFAULT_REPO_DIR))
        self.conda_py_var.set(cfg.get("conda_python", DEFAULT_CONDA_PY))
        self.prompt_audio_var.set(cfg.get("prompt_audio", ""))
        self.prompt_text_var.set(cfg.get("prompt_text", ""))
        # 根据参考音频状态更新音色下拉框
        self._update_spk_state()

    def _save_config_from_ui(self):
        cfg = {
            "spk": self.spk_var.get().strip(),
            "style": self.style_var.get().strip(),
            "speed": float(self.speed_var.get().strip() or 1.0),
            "format": self.format_var.get(),
            "out_dir": self.out_dir_var.get().strip(),
            "prefix": self.prefix_var.get().strip(),
            "seg_len": int(self.seg_len_var.get().strip() or DEFAULT_SEG_LEN),
            "model_dir": self.model_dir_var.get().strip(),
            "repo_dir": self.repo_dir_var.get().strip(),
            "conda_python": self.conda_py_var.get().strip(),
            "prompt_audio": self.prompt_audio_var.get().strip(),
            "prompt_text": self.prompt_text_var.get().strip(),
        }
        save_config(cfg)
        return cfg

    # ---------- 日志 ----------
    def _log(self, s):
        self.log_text.config(state="normal")
        self.log_text.insert("end", s + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _thread_log(self, s):
        """后台线程安全地往日志推送"""
        self.msg_queue.put(("log", s))

    def _switch_to_log_tab(self):
        self.notebook.select(1)

    # ---------- 控制 ----------
    def _start(self):
        # 获取文本
        content = self.txt_widget.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("提示", "请先输入或导入文本内容。")
            return

        # 校验路径
        model_dir = self.model_dir_var.get().strip()
        conda_py = self.conda_py_var.get().strip()
        if not os.path.isdir(model_dir):
            messagebox.showerror("错误", f"模型目录不存在：\n{model_dir}")
            return
        if not os.path.isfile(conda_py):
            messagebox.showerror("错误", f"conda python 不存在：\n{conda_py}")
            return
        if not WORKER_PATH.is_file():
            messagebox.showerror("错误", f"Worker 脚本不存在：\n{WORKER_PATH}")
            return

        # 校验参考音频（若选了音频但未填文本，提示用户）
        prompt_audio = self.prompt_audio_var.get().strip()
        prompt_text = self.prompt_text_var.get().strip()
        if prompt_audio and not prompt_text:
            messagebox.showwarning("提示", "已选择参考音频，但未填写\"音频对应文本\"。\n"
                                   "请填写参考音频中说的内容，或清除参考音频。")
            return
        if prompt_audio and not os.path.isfile(prompt_audio):
            messagebox.showerror("错误", f"参考音频文件不存在：\n{prompt_audio}")
            return

        # 保存配置并收集参数
        cfg = self._save_config_from_ui()

        # 切段
        seg_len = int(self.seg_len_var.get().strip() or DEFAULT_SEG_LEN)
        segments = split_text(content, seg_len)
        if not segments:
            messagebox.showwarning("提示", "文本切段后为空，请检查内容。")
            return

        # 切换到日志页，准备开始
        self._stop_event.clear()
        self._switch_to_log_tab()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_var.set(0)
        self.status_var.set(f"正在生成 0/{len(segments)}")
        # 显示当前模式
        if cfg.get('prompt_audio') and cfg.get('prompt_text'):
            mode_str = "Zero-Shot复刻"
            voice_str = os.path.basename(cfg['prompt_audio'])
        else:
            mode_str = "预置音色"
            voice_str = cfg['spk']
        self._log("=" * 60)
        self._log(f"开始生成：共 {len(segments)} 段，模式={mode_str}，音色={voice_str}，"
                  f"风格={cfg['style'] or '无'}，语速={cfg['speed']}x，格式={cfg['format'].upper()}")
        self._log(f"输出目录：{cfg['out_dir']}")
        self._log("=" * 60)

        # 启动后台线程
        self.worker_thread = threading.Thread(
            target=self._work, args=(segments, cfg), daemon=True)
        self.worker_thread.start()

    def _stop(self):
        self._stop_event.set()
        self._log("[停止] 用户请求停止...")
        self.status_var.set("正在停止...")
        logger.info("用户请求停止")

    def _work(self, segments, cfg):
        """后台线程：逐段调用 worker 生成音频"""
        out_dir = cfg.get("out_dir") or DEFAULT_OUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        speed = float(cfg.get("speed") or 1.0)
        fmt = (cfg.get("format") or "wav").lower()
        total = len(segments)

        ts = time.strftime("%Y%m%d_%H%M%S")
        wav_paths = build_out_paths(out_dir, total, {**cfg, "format": "wav"}, ts)
        final_paths = []

        try:
            for idx, text in enumerate(segments, start=1):
                if self._stop_event.is_set():
                    self.msg_queue.put(("stopped", f"已在第 {idx-1}/{total} 段后停止"))
                    return

                wav_path = wav_paths[idx - 1]
                self.msg_queue.put(("progress", idx, total))
                self.msg_queue.put(("log", f"\n[{idx}/{total}] 生成中..."))

                try:
                    call_worker(text, wav_path, cfg, log=self._thread_log)
                except Exception as e:
                    self._thread_log(f"  [错误] 第 {idx}/{total} 段失败: {e}")
                    logger.error("段 %d 失败: %s", idx, e)
                    continue

                # 语速调整
                if abs(speed - 1.0) >= 0.01:
                    apply_speed(wav_path, speed, log=self._thread_log)

                # 格式转换
                if fmt == "mp3":
                    mp3_path = os.path.splitext(wav_path)[0] + ".mp3"
                    if wav_to_mp3(wav_path, mp3_path, log=self._thread_log):
                        try:
                            os.remove(wav_path)
                        except Exception:
                            pass
                        final_paths.append(mp3_path)
                        self._thread_log(f"  [完成] {os.path.basename(mp3_path)}")
                    else:
                        final_paths.append(wav_path)
                        self._thread_log(f"  [完成] {os.path.basename(wav_path)}（MP3失败，保留WAV）")
                else:
                    final_paths.append(wav_path)
                    self._thread_log(f"  [完成] {os.path.basename(wav_path)}")

            # 全部完成
            self.msg_queue.put(("done", final_paths, out_dir))
        except Exception as e:
            traceback.print_exc()
            self.msg_queue.put(("error", f"生成异常：{e}"))

    # ---------- 消息轮询 ----------
    def _after_poll(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    idx, total = msg[1], msg[2]
                    pct = idx / total * 100
                    self.progress_var.set(pct)
                    self.status_var.set(f"正在生成 {idx}/{total}")
                elif kind == "done":
                    paths, out_dir = msg[1], msg[2]
                    self.progress_var.set(100)
                    self.status_var.set(f"完成，共 {len(paths)} 个文件")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self._log("\n" + "=" * 60)
                    self._log(f"[完成] 共生成 {len(paths)} 个文件：")
                    for p in paths:
                        self._log(f"  {p}")
                    self._log("=" * 60)
                    logger.info("GUI 生成完成，共 %d 个文件", len(paths))
                    messagebox.showinfo("完成", f"共生成 {len(paths)} 个音频文件：\n{out_dir}")
                    # 自动打开输出目录
                    if self.open_dir_var.get() and os.path.isdir(out_dir):
                        try:
                            os.startfile(out_dir)
                        except Exception:
                            pass
                elif kind == "stopped":
                    self.status_var.set("已停止")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self._log(f"\n[停止] {msg[1]}")
                elif kind == "error":
                    self.status_var.set("出错")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self._log(f"\n[错误] {msg[1]}")
                    messagebox.showerror("出错", msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._after_poll)


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
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
