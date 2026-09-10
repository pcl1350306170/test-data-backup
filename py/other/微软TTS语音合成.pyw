# -*- coding: utf-8 -*-
"""微软 TTS 语音合成（Edge-TTS）GUI 版
====================================
依赖：pip install edge-tts（需联网，调用微软在线 TTS 服务）
运行方式：双击运行（.pyw 无控制台窗口），或 python 微软TTS语音合成.pyw
功能：文本导入/粘贴 → 切段 → 逐段合成 MP3（可调速/音量/音调）→ 暂停/停止/测试
"""
import asyncio
import json
import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk, filedialog

# ---------- 路径与常量 ----------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "microsoft_tts"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# edge-tts 依赖检测
try:
    import edge_tts
    HAVE_EDGE_TTS = True
except ImportError:
    HAVE_EDGE_TTS = False

# ---------- 默认配置 ----------
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_SPEED = "1.0"
DEFAULT_VOLUME = "+0%"
DEFAULT_PITCH = "+0Hz"
DEFAULT_OUT_DIR = r"C:\Users\PCL13\Downloads"
DEFAULT_SEG_LEN = 500

# 微软声音列表（可手动输入自定义 voice 名，如 zh-CN-XiaoxiaoNeural）
VOICE_OPTIONS = [
    "zh-CN-XiaoxiaoNeural",            # 晓晓（普通话女）
    "zh-CN-XiaoyiNeural",              # 晓伊（普通话女）
    "zh-CN-YunxiNeural",               # 云希（普通话男）
    "zh-CN-YunjianNeural",             # 云健（普通话男）
    "zh-CN-YunyangNeural",             # 云扬（新闻男）
    "zh-CN-YunxiaNeural",              # 云夏（少年男）
    "zh-CN-liaoning-XiaobeiNeural",    # 晓北（东北话女）
    "zh-CN-shaanxi-XiaoniNeural",      # 晓妮（陕西话女）
    "zh-TW-HsiaoChenNeural",           # 曉臻（台湾女）
    "zh-TW-HsiaoYuNeural",             # 曉雨（台湾女）
    "zh-TW-YunJheNeural",              # 雲哲（台湾男）
    "zh-HK-HiuGaaiNeural",             # 曉佳（粤语女）
    "zh-HK-HiuMaanNeural",             # 曉曼（粤语女）
    "en-US-AriaNeural",                # Aria（英文女）
    "en-US-JennyNeural",               # Jenny（英文女）
    "en-US-GuyNeural",                 # Guy（英文男）
    "en-GB-SoniaNeural",               # Sonia（英音女）
    "ja-JP-NanamiNeural",              # Nanami（日文女）
    "ko-KR-SunHiNeural",               # SunHi（韩文女）
]

# 语速选项 -> Edge-TTS rate 参数
SPEED_OPTIONS = ["0.8", "1.0", "1.2", "1.5"]
RATE_MAP = {"0.8": "-20%", "1.0": "+0%", "1.2": "+20%", "1.5": "+50%"}

# 音量 / 音调（可手动输入）
VOLUME_OPTIONS = ["+0%", "-10%", "+10%", "-20%", "+20%", "-30%", "+30%", "-50%", "+50%"]
PITCH_OPTIONS = ["+0Hz", "+5Hz", "+10Hz", "+15Hz", "+20Hz", "-5Hz", "-10Hz", "-20Hz", "-30Hz", "+30Hz"]

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
        "voice": DEFAULT_VOICE,
        "speed": DEFAULT_SPEED,
        "volume": DEFAULT_VOLUME,
        "pitch": DEFAULT_PITCH,
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
# Edge-TTS 合成
# ============================================================
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean_text(text):
    """剔除控制字符（保留 \n \r \t），避免服务端解析异常"""
    return _CTRL_CHARS.sub("", text)


def synthesize_segment(text, voice, speed, volume, pitch, out_path, log=print, max_retries=3):
    """调用 edge-tts 合成单段 mp3，失败自动重试（指数退避）。成功返回 True。"""
    if not HAVE_EDGE_TTS:
        raise RuntimeError("未安装 edge-tts 库，请先运行：pip install edge-tts")
    text = _clean_text(text)
    if not text.strip():
        raise RuntimeError("文本为空（可能仅含无效字符）")
    rate = RATE_MAP.get(str(speed), "+0%")
    vol = (volume or "+0%").strip() or "+0%"
    pch = (pitch or "+0Hz").strip() or "+0Hz"

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=vol, pitch=pch)
        await communicate.save(str(out_path))

    log(f"  [合成] voice={voice} rate={rate} volume={vol} pitch={pch}")
    logger.info("合成: voice=%s rate=%s vol=%s pitch=%s len=%d", voice, rate, vol, pch, len(text))

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            asyncio.run(_run())
            if os.path.isfile(out_path):
                return True
            raise RuntimeError("Edge-TTS 未产出文件")
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 2 ** attempt  # 2s / 4s / 8s
                log(f"  [重试 {attempt}/{max_retries}] {e}，{wait} 秒后重试...")
                logger.warning("段合成失败，第 %d 次重试: %s", attempt, e)
                time.sleep(wait)
            else:
                log(f"  [失败] 已重试 {max_retries} 次仍失败: {e}")
    raise RuntimeError(f"Edge-TTS 合成失败（已重试 {max_retries} 次）: {last_err}")


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
    voice = cfg.get("voice") or DEFAULT_VOICE
    voice_short = voice.split("-")[-1] if voice else "tts"
    base_parts = [p for p in (prefix or voice_short, ts) if p]
    base = "_".join(base_parts)
    paths = []
    for i in range(segments_count):
        name = f"{base}.mp3" if segments_count == 1 else f"{base}-{i+1:03d}.mp3"
        paths.append(os.path.join(out_dir, name))
    return paths


# ============================================================
# GUI 主程序
# ============================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("微软 TTS 语音合成（Edge-TTS）")
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
        self.voice_var = tk.StringVar(value=DEFAULT_VOICE)
        self.speed_var = tk.StringVar(value=DEFAULT_SPEED)
        self.volume_var = tk.StringVar(value=DEFAULT_VOLUME)
        self.pitch_var = tk.StringVar(value=DEFAULT_PITCH)
        self.out_dir_var = tk.StringVar(value=DEFAULT_OUT_DIR)
        self.prefix_var = tk.StringVar(value="")
        self.seg_len_var = tk.StringVar(value=str(DEFAULT_SEG_LEN))
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.open_dir_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._load_config_to_ui()
        self._after_poll()

        if not HAVE_EDGE_TTS:
            self.root.after(300, self._warn_no_edge_tts)

    def _warn_no_edge_tts(self):
        messagebox.showwarning(
            "缺少依赖",
            "未检测到 edge-tts 库，语音合成无法运行。\n\n"
            "请在命令行执行：\n  pip install edge-tts\n\n"
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

        # --- 音色 / 语速 / 音量 / 音调 ---
        frm_voice = ttk.LabelFrame(cfg_tab, text="2. 音色 / 语速 / 音量 / 音调")
        frm_voice.pack(fill="x", padx=10, pady=4)

        row = ttk.Frame(frm_voice)
        row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="音色:").pack(side="left")
        self.voice_combo = ttk.Combobox(row, textvariable=self.voice_var, width=32, values=VOICE_OPTIONS)
        self.voice_combo.pack(side="left", padx=6)
        ttk.Label(row, text="语速:").pack(side="left", padx=(16, 0))
        self.speed_combo = ttk.Combobox(row, textvariable=self.speed_var, width=5, values=SPEED_OPTIONS, state="readonly")
        self.speed_combo.pack(side="left", padx=6)
        ttk.Label(row, text="音量:").pack(side="left", padx=(16, 0))
        self.volume_combo = ttk.Combobox(row, textvariable=self.volume_var, width=8, values=VOLUME_OPTIONS)
        self.volume_combo.pack(side="left", padx=6)
        ttk.Label(row, text="音调:").pack(side="left", padx=(16, 0))
        self.pitch_combo = ttk.Combobox(row, textvariable=self.pitch_var, width=8, values=PITCH_OPTIONS)
        self.pitch_combo.pack(side="left", padx=6)

        row2 = ttk.Frame(frm_voice)
        row2.pack(fill="x", padx=6, pady=3)
        ttk.Label(row2, text="切段字数:").pack(side="left")
        ttk.Entry(row2, textvariable=self.seg_len_var, width=8).pack(side="left", padx=6)
        ttk.Label(row2, text="文件名前缀:").pack(side="left", padx=(16, 0))
        ttk.Entry(row2, textvariable=self.prefix_var, width=18).pack(side="left", padx=6)
        ttk.Label(row2, text="（留空则用声音名）", foreground="#888").pack(side="left")

        # --- 输出目录 ---
        frm_out = ttk.LabelFrame(cfg_tab, text="3. 输出目录")
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

    def _pick_out_dir(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.out_dir_var.set(p)

    # ---------- 配置 ----------
    def _load_config_to_ui(self):
        cfg = load_config()
        self.voice_var.set(cfg.get("voice", DEFAULT_VOICE))
        self.speed_var.set(str(cfg.get("speed", DEFAULT_SPEED)))
        self.volume_var.set(cfg.get("volume", DEFAULT_VOLUME))
        self.pitch_var.set(cfg.get("pitch", DEFAULT_PITCH))
        self.out_dir_var.set(cfg.get("out_dir", DEFAULT_OUT_DIR))
        self.prefix_var.set(cfg.get("prefix", ""))
        self.seg_len_var.set(str(cfg.get("seg_len", DEFAULT_SEG_LEN)))

    def _save_config_from_ui(self):
        cfg = {
            "voice": self.voice_var.get().strip(),
            "speed": self.speed_var.get().strip() or DEFAULT_SPEED,
            "volume": self.volume_var.get().strip() or DEFAULT_VOLUME,
            "pitch": self.pitch_var.get().strip() or DEFAULT_PITCH,
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
        if not HAVE_EDGE_TTS:
            self._show_toast("缺少依赖", "请先安装 edge-tts：pip install edge-tts", "error")
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
        self._log(f"开始生成：共 {len(segments)} 段，声音={cfg['voice']}，"
                  f"语速={cfg['speed']}x，音量={cfg['volume']}，音调={cfg['pitch']}")
        self._log(f"输出目录：{cfg['out_dir']}")
        self._log("=" * 60)
        self.worker_thread = threading.Thread(
            target=self._work, args=(segments, cfg), daemon=True)
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
        if not HAVE_EDGE_TTS:
            self._show_toast("缺少依赖", "请先安装 edge-tts：pip install edge-tts", "error")
            return
        cfg = self._save_config_from_ui()
        test_text = random.choice(self._TEST_SENTENCES)
        out_dir = cfg.get("out_dir") or DEFAULT_OUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        voice_short = (cfg.get("voice") or "tts").split("-")[-1]
        out_path = os.path.join(out_dir, f"测试_{_safe_name(voice_short)}_{ts}.mp3")

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
                synthesize_segment(test_text, cfg["voice"], cfg["speed"],
                                   cfg["volume"], cfg["pitch"], out_path, log=self._thread_log)
                self.msg_queue.put(("test_done", out_path))
            except Exception as e:
                self.msg_queue.put(("test_error", str(e)))

        threading.Thread(target=_do_test, daemon=True).start()

    # ---------- 后台工作线程 ----------
    def _work(self, segments, cfg):
        out_dir = cfg.get("out_dir") or DEFAULT_OUT_DIR
        os.makedirs(out_dir, exist_ok=True)
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
                    synthesize_segment(text, cfg["voice"], cfg["speed"],
                                       cfg["volume"], cfg["pitch"], out_path, log=self._thread_log)
                except Exception as e:
                    failed_idx.append(idx)
                    self._thread_log(f"  [错误] 第 {idx}/{total} 段失败: {e}")
                    logger.error("段 %d 失败: %s", idx, e)
                    continue
                final_paths.append(out_path)
                self._thread_log(f"  [完成] {os.path.basename(out_path)}")
                # 段间小间隔，降低连续请求频率，预防限流
                time.sleep(0.6)
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
                        self._log(f"       （可修改失败段文本后重试，或稍后再跑一次）")
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
