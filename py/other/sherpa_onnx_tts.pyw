# -*- coding: utf-8 -*-
"""Sherpa-ONNX TTS 语音合成（离线 VITS）GUI 版
====================================
依赖：pip install sherpa-onnx numpy（离线运行，无需联网）
运行方式：双击运行（.pyw 无控制台窗口），或 python sherpa_onnx_tts.pyw
功能：文本导入/粘贴 → 切段 → 逐段合成 WAV（可调说话人/语速）→ 暂停/停止/测试
模型资源：D:/dev/sherpa-models/sherpa-onnx-vits-zh-ll
"""
import json
import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
import wave
from pathlib import Path
from tkinter import messagebox, ttk, filedialog

import numpy as np

# ---------- 路径与常量 ----------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "sherpa_onnx_tts"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

DEFAULT_MODEL_DIR = r"D:\dev\sherpa-models\sherpa-onnx-vits-zh-ll"
DEFAULT_SID = "0"
DEFAULT_SPEED = "1.0"
DEFAULT_OUT_DIR = r"C:\Users\PCL13\Downloads"
DEFAULT_SEG_LEN = 500

# sherpa-onnx 依赖检测
try:
    import sherpa_onnx
    HAVE_SHERPA_ONNX = True
except ImportError:
    HAVE_SHERPA_ONNX = False

# 说话人选项（sid + 描述，共 5 个）
SID_OPTIONS = [
    "0 - 温柔女声",
    "1 - 沉稳男声",
    "2 - 知性女声",
    "3 - 不清晰男声",
    "4 - 空灵男声",
]

# 语速选项（直接作为 speed 参数传给 sherpa-onnx）
SPEED_OPTIONS = ["0.8", "1.0", "1.2", "1.5"]

# 日志模块（可选依赖，失败降级）
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
    cfg = {
        "model_dir": DEFAULT_MODEL_DIR,
        "sid": DEFAULT_SID,
        "speed": DEFAULT_SPEED,
        "out_dir": DEFAULT_OUT_DIR,
        "seg_len": DEFAULT_SEG_LEN,
        "prefix": "",
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
    """按 max_chars 软上限切段，尽量在句末标点结束；超长硬切。"""
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
# Sherpa-ONNX 合成
# ============================================================
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean_text(text):
    """剔除控制字符（保留 \\n \\r \\t），避免合成异常"""
    return _CTRL_CHARS.sub("", text)


def _find_model_files(model_dir):
    """在模型目录中定位必要文件（.onnx / tokens.txt / lexicon.txt / dict / .fst）"""
    model_path = None
    tokens_path = None
    lexicon_path = None
    data_dir = None
    rule_fsts = []
    for f in os.listdir(model_dir):
        fp = os.path.join(model_dir, f)
        if f.lower().endswith(".onnx"):
            if "int8" not in f.lower():
                model_path = fp
            elif model_path is None:
                model_path = fp
        elif f.lower() == "tokens.txt":
            tokens_path = fp
        elif f.lower() == "lexicon.txt":
            lexicon_path = fp
        elif f.lower() in ("espeak-ng-data", "dict"):
            data_dir = fp
        elif f.lower().endswith(".fst"):
            rule_fsts.append(fp)
    if not model_path or not tokens_path:
        raise RuntimeError("模型目录中未找到 .onnx 和 tokens.txt，请检查目录。")
    return model_path, tokens_path, lexicon_path, data_dir, rule_fsts


def synthesize_segment(text, model_dir, sid, speed, out_path, log=print):
    """调用 sherpa-onnx 合成单段 WAV。成功返回 True。"""
    if not HAVE_SHERPA_ONNX:
        raise RuntimeError("未安装 sherpa-onnx，请先运行：pip install sherpa-onnx")
    text = _clean_text(text)
    if not text.strip():
        raise RuntimeError("文本为空（可能仅含无效字符）")

    model_path, tokens_path, lexicon_path, data_dir, rule_fsts = _find_model_files(model_dir)

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
    spd = float(speed) if speed else 1.0
    result = tts.generate(text, sid=int(sid), speed=spd)
    samples = np.asarray(result.samples, dtype=np.float32)
    sample_rate = result.sample_rate

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes((samples * 32767).astype(np.int16).tobytes())

    log(f"  [合成] sid={sid} speed={spd} sr={sample_rate}")
    logger.info("合成: sid=%s speed=%s len=%d", sid, spd, len(text))
    return True


# ============================================================
# 文件命名
# ============================================================
def _safe_name(s):
    if not s:
        return ""
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in s).strip()


def build_out_paths(out_dir, segments_count, cfg, timestamp=None):
    ts = timestamp or time.strftime("%Y%m%d_%H%M%S")
    prefix = _safe_name(cfg.get("prefix") or "")
    sid = cfg.get("sid") or DEFAULT_SID
    sid_short = sid.split("-")[0].strip() if sid else "0"
    base_parts = [p for p in (prefix or f"sid{sid_short}", ts) if p]
    base = "_".join(base_parts)
    paths = []
    for i in range(segments_count):
        name = f"{base}.wav" if segments_count == 1 else f"{base}-{i+1:03d}.wav"
        paths.append(os.path.join(out_dir, name))
    return paths


# ============================================================
# GUI 主程序
# ============================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Sherpa-ONNX TTS 语音合成（离线 VITS）")
        root.geometry("760x720")
        root.minsize(680, 640)
        try:
            root.state("zoomed")
        except Exception:
            pass

        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

        self.text_content = ""
        self.txt_file_path = ""
        self.model_dir_var = tk.StringVar(value=DEFAULT_MODEL_DIR)
        self.sid_var = tk.StringVar(value=DEFAULT_SID)
        self.speed_var = tk.StringVar(value=DEFAULT_SPEED)
        self.out_dir_var = tk.StringVar(value=DEFAULT_OUT_DIR)
        self.prefix_var = tk.StringVar(value="")
        self.seg_len_var = tk.StringVar(value=str(DEFAULT_SEG_LEN))
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.open_dir_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._load_config_to_ui()
        self._after_poll()

        if not HAVE_SHERPA_ONNX:
            self.root.after(300, self._warn_no_sherpa_onnx)

    def _warn_no_sherpa_onnx(self):
        messagebox.showwarning(
            "缺少依赖",
            "未检测到 sherpa-onnx 库，语音合成无法运行。\n\n"
            "请在命令行执行：\n  pip install sherpa-onnx numpy\n\n"
            "安装后重启本程序。", parent=self.root)

    # ---------- UI 构建 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

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

        # --- 模型目录 ---
        frm_model = ttk.LabelFrame(cfg_tab, text="2. 模型目录")
        frm_model.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_model)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Entry(row, textvariable=self.model_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_model_dir).pack(side="right", padx=4)

        # --- 说话人 / 语速 ---
        frm_voice = ttk.LabelFrame(cfg_tab, text="3. 说话人 / 语速")
        frm_voice.pack(fill="x", padx=10, pady=4)

        row = ttk.Frame(frm_voice)
        row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="说话人:").pack(side="left")
        self.sid_combo = ttk.Combobox(row, textvariable=self.sid_var, width=28,
                                      values=SID_OPTIONS, state="readonly")
        self.sid_combo.pack(side="left", padx=6)
        ttk.Label(row, text="语速:").pack(side="left", padx=(16, 0))
        self.speed_combo = ttk.Combobox(row, textvariable=self.speed_var, width=5,
                                        values=SPEED_OPTIONS, state="readonly")
        self.speed_combo.pack(side="left", padx=6)

        row2 = ttk.Frame(frm_voice)
        row2.pack(fill="x", padx=6, pady=3)
        ttk.Label(row2, text="切段字数:").pack(side="left")
        ttk.Entry(row2, textvariable=self.seg_len_var, width=8).pack(side="left", padx=6)
        ttk.Label(row2, text="文件名前缀:").pack(side="left", padx=(16, 0))
        ttk.Entry(row2, textvariable=self.prefix_var, width=18).pack(side="left", padx=6)
        ttk.Label(row2, text="（留空则用 sid 编号）", foreground="#888").pack(side="left")

        # --- 输出目录 ---
        frm_out = ttk.LabelFrame(cfg_tab, text="4. 输出目录")
        frm_out.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_out)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Entry(row, textvariable=self.out_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_out_dir).pack(side="right", padx=4)
        ttk.Checkbutton(row, text="完成后打开目录", variable=self.open_dir_var).pack(side="right", padx=8)

        # ===== 日志页 =====
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text=" 日志 ")
        frm_log = ttk.Frame(log_tab)
        frm_log.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(frm_log, height=20, wrap="word", state="disabled", font=("Consolas", 9))
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
        self.pause_btn = ttk.Button(btn_bar, text="暂停", command=self._pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.resume_btn = ttk.Button(btn_bar, text="继续", command=self._resume, state="disabled")
        self.resume_btn.pack(side="left", padx=(0, 6))
        self.test_btn = ttk.Button(btn_bar, text="测试", command=self._test_generate)
        self.test_btn.pack(side="left", padx=(0, 6))

        self.progress_bar = ttk.Progressbar(btn_bar, variable=self.progress_var, maximum=100, length=200)
        self.progress_bar.pack(side="left", padx=16)
        self.lbl_status = ttk.Label(btn_bar, textvariable=self.status_var, foreground="#333")
        self.lbl_status.pack(side="left", padx=8)

    # ---------- 浏览按钮 ----------
    def _import_txt(self):
        path = filedialog.askopenfilename(
            title="选择 TXT 文件", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
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

    def _pick_model_dir(self):
        p = filedialog.askdirectory(title="选择 sherpa-onnx 模型目录")
        if p:
            self.model_dir_var.set(p)

    def _pick_out_dir(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.out_dir_var.set(p)

    # ---------- 配置 ----------
    def _load_config_to_ui(self):
        cfg = load_config()
        self.model_dir_var.set(cfg.get("model_dir", DEFAULT_MODEL_DIR))
        self.sid_var.set(cfg.get("sid", DEFAULT_SID))
        self.speed_var.set(str(cfg.get("speed", DEFAULT_SPEED)))
        self.out_dir_var.set(cfg.get("out_dir", DEFAULT_OUT_DIR))
        self.prefix_var.set(cfg.get("prefix", ""))
        self.seg_len_var.set(str(cfg.get("seg_len", DEFAULT_SEG_LEN)))

    def _save_config_from_ui(self):
        cfg = {
            "model_dir": self.model_dir_var.get().strip(),
            "sid": self.sid_var.get().strip() or DEFAULT_SID,
            "speed": self.speed_var.get().strip() or DEFAULT_SPEED,
            "out_dir": self.out_dir_var.get().strip(),
            "prefix": self.prefix_var.get().strip(),
            "seg_len": int(self.seg_len_var.get().strip() or DEFAULT_SEG_LEN),
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
        self.msg_queue.put(("log", s))

    def _switch_to_log_tab(self):
        self.notebook.select(1)

    # ---------- Toast ----------
    def _show_toast(self, title, message, level="info", duration_ms=3500):
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)
            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error": ("#c62828", "#ffebee", "❌"),
                "info": ("#1565c0", "#e3f2fd", "ℹ️"),
                "warning": ("#e65100", "#fff3e0", "⚠️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)
            header = tk.Frame(toast, bg=bg)
            header.pack(fill=tk.X, padx=10, pady=8)
            tk.Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                     fg=fg, bg=bg).pack(side=tk.LEFT)
            close_btn = tk.Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())
            tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                     fg="#333", bg=bg, wraplength=320, justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)
            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            sx, sy = toast.winfo_screenwidth(), toast.winfo_screenheight()
            toast.geometry(f"+{sx - w - 20}+{sy - h - 60}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    # ---------- 控制 ----------
    def _start(self):
        if not HAVE_SHERPA_ONNX:
            self._show_toast("缺少依赖", "请先安装 sherpa-onnx：pip install sherpa-onnx numpy", "error")
            return
        model_dir = self.model_dir_var.get().strip()
        if not model_dir or not os.path.isdir(model_dir):
            self._show_toast("提示", "请先指定有效的模型目录。", "warning")
            return
        content = self.txt_widget.get("1.0", "end").strip()
        if not content:
            self._show_toast("提示", "请先输入或导入文本内容。", "warning")
            return
        cfg = self._save_config_from_ui()
        seg_len = int(self.seg_len_var.get().strip() or DEFAULT_SEG_LEN)
        segments = split_text(content, seg_len)
        if not segments:
            self._show_toast("提示", "文本切段后为空，请检查内容", "warning")
            return

        sid_label = cfg["sid"]
        sid_val = sid_label.split("-")[0].strip() if "-" in sid_label else sid_label

        self._stop_event.clear()
        self._pause_event.clear()
        self._switch_to_log_tab()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.pause_btn.config(state="normal")
        self.resume_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        self.progress_var.set(0)
        self.status_var.set(f"正在生成 0/{len(segments)}")
        self._log("=" * 60)
        self._log(f"开始生成：共 {len(segments)} 段，说话人={sid_label}，"
                  f"语速={cfg['speed']}x")
        self._log(f"模型目录：{model_dir}")
        self._log(f"输出目录：{cfg['out_dir']}")
        self._log("=" * 60)
        self.worker_thread = threading.Thread(
            target=self._work, args=(segments, cfg, sid_val), daemon=True)
        self.worker_thread.start()

    def _stop(self):
        self._stop_event.set()
        self._pause_event.clear()
        self._log("[停止] 用户请求停止...")
        self.status_var.set("正在停止...")

    def _pause(self):
        self._pause_event.set()
        self.pause_btn.config(state="disabled")
        self.resume_btn.config(state="normal")
        self.status_var.set("已暂停（等待当前段完成）")
        self._log("[暂停] 当前段完成后将暂停...")

    def _resume(self):
        self._pause_event.clear()
        self.pause_btn.config(state="normal")
        self.resume_btn.config(state="disabled")
        self.status_var.set("继续生成中...")
        self._log("[继续] 恢复生成")

    # ---------- 测试 ----------
    _TEST_SENTENCES = [
        "清晨的阳光洒在窗台上，鸟儿在枝头欢快地歌唱，新的一天开始了。",
        "春天的田野里，油菜花金灿灿的一片，微风吹过，带来阵阵清香。",
        "夜幕降临，繁星点点，月亮悄悄爬上了树梢，一切都安静了下来。",
        "小溪潺潺流过石桥，鱼儿在水中自由自在地游来游去。",
        "秋天的果园里，红彤彤的苹果挂满枝头，空气中弥漫着丰收的喜悦。",
        "雨后的街道格外清新，路面上的水洼倒映着天空和行人。",
        "远处的山峦层叠起伏，云雾缭绕其间，宛如一幅水墨画卷。",
        "咖啡的香气弥漫在房间里，书页在指尖轻轻翻动，时光静好。",
    ]

    def _test_generate(self):
        if not HAVE_SHERPA_ONNX:
            self._show_toast("缺少依赖", "请先安装 sherpa-onnx：pip install sherpa-onnx numpy", "error")
            return
        model_dir = self.model_dir_var.get().strip()
        if not model_dir or not os.path.isdir(model_dir):
            self._show_toast("提示", "请先指定有效的模型目录。", "warning")
            return
        cfg = self._save_config_from_ui()
        sid_val = cfg["sid"].split("-")[0].strip() if "-" in cfg["sid"] else cfg["sid"]
        test_text = random.choice(self._TEST_SENTENCES)
        out_dir = cfg.get("out_dir") or DEFAULT_OUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"测试_sid{sid_val}_{ts}.wav")

        self._switch_to_log_tab()
        self.test_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.status_var.set("测试生成中...")
        self._log(f"\n{'=' * 40}")
        self._log(f"[测试] 随机文本: {test_text}")
        self._log(f"[测试] 输出: {out_path}")
        self._log(f"{'=' * 40}")

        def _do_test():
            try:
                synthesize_segment(test_text, model_dir, sid_val,
                                   cfg["speed"], out_path, log=self._thread_log)
                self.msg_queue.put(("test_done", out_path))
            except Exception as e:
                self.msg_queue.put(("test_error", str(e)))

        threading.Thread(target=_do_test, daemon=True).start()

    # ---------- 后台工作线程 ----------
    def _work(self, segments, cfg, sid_val):
        out_dir = cfg.get("out_dir") or DEFAULT_OUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        model_dir = cfg.get("model_dir") or DEFAULT_MODEL_DIR
        total = len(segments)
        final_paths = []
        failed_idx = []
        wav_paths = build_out_paths(out_dir, total, cfg)
        try:
            for idx, text in enumerate(segments, start=1):
                if self._stop_event.is_set():
                    self.msg_queue.put(("stopped", f"已在第 {idx - 1}/{total} 段后停止"))
                    return
                if self._pause_event.is_set():
                    self.msg_queue.put(("log", "  [暂停] 等待继续..."))
                    while self._pause_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.3)
                    if self._stop_event.is_set():
                        self.msg_queue.put(("stopped", f"已在第 {idx - 1}/{total} 段后停止"))
                        return
                    self.msg_queue.put(("log", "  [继续] 恢复生成"))

                out_path = wav_paths[idx - 1]
                self.msg_queue.put(("progress", idx, total))
                self.msg_queue.put(("log", f"\n[{idx}/{total}] 生成中..."))
                try:
                    synthesize_segment(text, model_dir, sid_val,
                                       cfg["speed"], out_path, log=self._thread_log)
                except Exception as e:
                    failed_idx.append(idx)
                    self._thread_log(f"  [错误] 第 {idx}/{total} 段失败: {e}")
                    logger.error("段 %d 失败: %s", idx, e)
                    continue
                final_paths.append(out_path)
                self._thread_log(f"  [完成] {os.path.basename(out_path)}")
            self.msg_queue.put(("done", final_paths, out_dir, failed_idx))
        except Exception as e:
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
                    self.progress_var.set(idx / total * 100)
                    self.status_var.set(f"正在生成 {idx}/{total}")
                elif kind == "done":
                    paths, out_dir, failed_idx = msg[1], msg[2], msg[3]
                    self.progress_var.set(100)
                    self.status_var.set(f"完成，共 {len(paths)} 个文件")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.pause_btn.config(state="disabled")
                    self.resume_btn.config(state="disabled")
                    self.test_btn.config(state="normal")
                    self._log("\n" + "=" * 60)
                    self._log(f"[完成] 共生成 {len(paths)} 个文件：")
                    for p in paths:
                        self._log(f"  {p}")
                    if failed_idx:
                        self._log(f"[失败] {len(failed_idx)} 段未生成：{failed_idx}")
                        self._log(f"       （可修改失败段文本后重试）")
                    self._log("=" * 60)
                    logger.info("GUI 生成完成，共 %d 个文件，失败 %d 段", len(paths), len(failed_idx))
                    if failed_idx:
                        self._show_toast("生成完成（部分失败）",
                                         f"共生成 {len(paths)} 个文件\n{len(failed_idx)} 段失败：{failed_idx}\n{out_dir}",
                                         "warning", 7000)
                    else:
                        self._show_toast("生成完成", f"共生成 {len(paths)} 个音频文件\n{out_dir}", "success", 5000)
                    if self.open_dir_var.get() and os.path.isdir(out_dir):
                        try:
                            os.startfile(out_dir)
                        except Exception:
                            pass
                elif kind == "stopped":
                    self.status_var.set("已停止")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.pause_btn.config(state="disabled")
                    self.resume_btn.config(state="disabled")
                    self.test_btn.config(state="normal")
                    self._log(f"\n[停止] {msg[1]}")
                elif kind == "error":
                    self.status_var.set("出错")
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.pause_btn.config(state="disabled")
                    self.resume_btn.config(state="disabled")
                    self.test_btn.config(state="normal")
                    self._log(f"\n[错误] {msg[1]}")
                    self._show_toast("出错", msg[1], "error", 6000)
                elif kind == "test_done":
                    self.test_btn.config(state="normal")
                    self.start_btn.config(state="normal")
                    self.status_var.set("测试完成")
                    self._log(f"\n[测试完成] {msg[1]}")
                    self._show_toast("测试完成", f"音频已生成：\n{os.path.basename(msg[1])}", "success", 4000)
                elif kind == "test_error":
                    self.test_btn.config(state="normal")
                    self.start_btn.config(state="normal")
                    self.status_var.set("测试失败")
                    self._log(f"\n[测试失败] {msg[1]}")
                    self._show_toast("测试失败", msg[1], "error", 6000)
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
