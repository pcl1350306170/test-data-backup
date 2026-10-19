# 音频文件截取.pyw
# 功能：从一个或多个音频文件中截取指定时间段的音频，输出为新文件
# 支持三种模式：手动时间段 / 固定时长切片 / 前后N秒
# 支持波形可视化拖拽选区，并可实时试听选中片段
# 依赖：ffmpeg + ffprobe（不依赖 pydub），播放使用 Windows 内置 winsound

import os
import sys
import json
import shutil
import tempfile
import threading
import subprocess
from array import array
from pathlib import Path
from queue import Queue
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import winsound  # Windows 内置音频播放，用于试听
except ImportError:
    winsound = None

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "audio_clip"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# 可选日志模块：导入失败时 DummyLogger 兜底，不影响脚本运行
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
try:
    from log_utils import get_logger
    logger = get_logger()
except Exception:
    class _Dummy:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _Dummy()

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
FILETYPE_STR = "音频文件 " + " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))

MODE_RANGE = "range"       # 手动时间段
MODE_SLICE = "slice"       # 固定时长切片
MODE_HEADTAIL = "headtail"  # 前/后 N 秒

WAVE_RATE = 8000           # 波形采样率（仅用于绘图，低采样率足够且快）
WAVE_PAD = 6               # 波形画布左右留白（像素）
HANDLE_HIT = 8             # 拖拽手柄命中半径（像素）
MIN_SEL = 0.1              # 最小选区时长（秒）


# ================== 工具函数 ==================
def parse_time_to_seconds(text: str):
    """解析时间输入，支持 HH:MM:SS(.ms)、MM:SS、纯秒数；失败返回 None"""
    text = text.strip().replace("：", ":").replace("-", ":")
    if not text:
        return None
    try:
        parts = text.split(":")
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return None
    except (ValueError, IndexError):
        return None


def fmt_tc(seconds: float) -> str:
    """秒数格式化为 HH-MM-SS，用于输出文件命名"""
    s = max(0, int(seconds))
    return f"{s // 3600:02d}-{s % 3600 // 60:02d}-{s % 60:02d}"


def fmt_hms(seconds: float) -> str:
    """秒数格式化为 HH:MM:SS.ss，用于时间输入框与选区显示"""
    s = max(0.0, seconds)
    h = int(s // 3600)
    m = int(s % 3600 // 60)
    return f"{h:02d}:{m:02d}:{s % 60:05.2f}"


def unique_path(path: Path) -> Path:
    """重名时自动追加 (1)、(2)...，不覆盖已有文件"""
    if not path.exists():
        return path
    idx = 1
    while True:
        candidate = path.with_name(f"{path.stem}({idx}){path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


# ================== 主程序类 ==================
class AudioClipper:
    def __init__(self, root):
        self.root = root
        self.root.title("音频文件截取（波形拖拽选区 / 时长切片 / 前后N秒）")
        self.root.geometry("900x720")
        self.root.minsize(780, 620)

        # 控制变量
        self.is_running = False
        self.cancel_flag = threading.Event()
        self.ffmpeg_path = ""
        self.ffprobe_path = ""

        # 文件列表
        self.input_files = []

        # 波形预览与试听状态
        self.wave_gen = 0              # 加载代数计数，丢弃过期后台线程结果
        self.wave_src = None           # 当前波形对应的文件(Path)
        self.wave_duration = 0.0
        self.wave_peaks = None         # 每像素列峰值列表
        self.wave_peak_max = 1
        self.sel_start = 0.0           # 选区起止（秒）
        self.sel_end = 0.0
        self.drag_mode = None          # None/left/right/new/move
        self.drag_anchor = 0.0
        self.preview_playing = False
        self.preview_token = 0
        self.preview_wav = Path(tempfile.gettempdir()) / "audio_clip_preview.wav"

        # 加载配置并创建界面
        self.config = self.load_config()
        self.create_widgets()
        self.apply_config()
        self.switch_mode()

        # 启动时检查 ffmpeg
        self.check_ffmpeg_on_start()

        # 恢复的文件列表自动加载首个文件的波形
        if self.input_files:
            self.file_listbox.selection_set(0)
            self.load_waveform(self.input_files[0])

    # ==================== 配置持久化 ====================

    def load_config(self):
        default_config = {
            "ffmpeg_path": "",
            "output_dir": "",
            "thread_count": 2,
            "mode": MODE_RANGE,
            "range_start": "00:00:00",
            "range_end": "00:00:30",
            "slice_seconds": "30",
            "headtail_seconds": "30",
            "headtail_pos": "head",
            "last_input_files": []
        }
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    default_config.update(json.load(f))
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
        return default_config

    def save_config(self):
        cfg = {
            "ffmpeg_path": self.ffmpeg_path,
            "output_dir": self.output_dir_var.get().strip(),
            "thread_count": self._thread_count(),
            "mode": self.mode_var.get(),
            "range_start": self.range_start_var.get().strip(),
            "range_end": self.range_end_var.get().strip(),
            "slice_seconds": self.slice_sec_var.get().strip(),
            "headtail_seconds": self.headtail_sec_var.get().strip(),
            "headtail_pos": self.headtail_pos_var.get(),
            "last_input_files": self.input_files.copy()
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def apply_config(self):
        self.ffmpeg_path = self.config.get("ffmpeg_path", "")
        self.ffmpeg_path_var.set(self.ffmpeg_path)
        self.output_dir_var.set(self.config.get("output_dir", ""))
        self.thread_var.set(str(self.config.get("thread_count", 2)))
        self.mode_var.set(self.config.get("mode", MODE_RANGE))
        self.range_start_var.set(self.config.get("range_start", "00:00:00"))
        self.range_end_var.set(self.config.get("range_end", "00:00:30"))
        self.slice_sec_var.set(self.config.get("slice_seconds", "30"))
        self.headtail_sec_var.set(self.config.get("headtail_seconds", "30"))
        self.headtail_pos_var.set(self.config.get("headtail_pos", "head"))
        for f in self.config.get("last_input_files", []):
            if Path(f).exists() and f not in self.input_files:
                self.input_files.append(f)
                self.file_listbox.insert(END, os.path.basename(f))

    def _thread_count(self):
        try:
            return max(1, min(8, int(self.thread_var.get())))
        except ValueError:
            return 2

    # ==================== ffmpeg 检测 ====================

    def check_ffmpeg_on_start(self):
        if self.ffmpeg_path and Path(self.ffmpeg_path).exists():
            self._locate_ffprobe()
            self.log(f"✅ FFmpeg: {self.ffmpeg_path}")
            return
        auto = shutil.which("ffmpeg")
        if auto:
            self.ffmpeg_path = auto
            self._locate_ffprobe()
            self.ffmpeg_path_var.set(auto)
            self.save_config()
            self.log(f"✅ 自动检测到 FFmpeg: {auto}")
        else:
            self.log("⚠️ 未检测到 FFmpeg，请手动指定路径。")
            self.show_toast("警告", "未检测到 FFmpeg，请在界面中手动指定 ffmpeg.exe",
                            level="warning", duration_ms=6000)

    def _locate_ffprobe(self):
        """ffprobe 优先与 ffmpeg 同目录，其次从 PATH 查找"""
        self.ffprobe_path = ""
        if self.ffmpeg_path:
            candidate = Path(self.ffmpeg_path).parent / "ffprobe.exe"
            if candidate.exists():
                self.ffprobe_path = str(candidate)
                return
        self.ffprobe_path = shutil.which("ffprobe") or ""

    def select_ffmpeg(self):
        path = filedialog.askopenfilename(
            title="选择 ffmpeg.exe",
            filetypes=[("Executable", "ffmpeg.exe"), ("All files", "*.*")]
        )
        if path:
            self.ffmpeg_path = path
            self.ffmpeg_path_var.set(path)
            self._locate_ffprobe()
            self.save_config()
            self.log(f"✅ FFmpeg 路径已设置: {path}")
            if not self.ffprobe_path:
                self.log("⚠️ 未找到 ffprobe，将按输入文件扩展名估算时长，可能不准。")

    # ==================== 界面构建 ====================

    def create_widgets(self):
        main_frame = Frame(self.root)
        main_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # 1. FFmpeg 路径
        ffmpeg_frame = LabelFrame(main_frame, text="FFmpeg 路径", padx=5, pady=5)
        ffmpeg_frame.pack(fill=X, pady=5)
        self.ffmpeg_path_var = StringVar()
        Entry(ffmpeg_frame, textvariable=self.ffmpeg_path_var, state="readonly") \
            .pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        Button(ffmpeg_frame, text="选择 FFmpeg", command=self.select_ffmpeg).pack(side=RIGHT)

        # 2. 输入文件
        input_frame = LabelFrame(main_frame, text="选择音频文件（支持多选）", padx=5, pady=5)
        input_frame.pack(fill=X, pady=5)
        btn_row = Frame(input_frame)
        btn_row.pack(fill=X)
        Button(btn_row, text="添加音频文件", command=self.add_files).pack(side=LEFT)
        Button(btn_row, text="移除选中", command=self.remove_selected).pack(side=LEFT, padx=(5, 0))
        Button(btn_row, text="清空列表", command=self.clear_files).pack(side=LEFT, padx=(5, 0))
        self.file_listbox = Listbox(input_frame, height=4, selectmode=EXTENDED)
        self.file_listbox.pack(fill=BOTH, expand=True, pady=(5, 0))
        self.file_listbox.bind("<<ListboxSelect>>", self.on_listbox_select)

        # 2.1 波形预览与拖拽选区
        wave_frame = LabelFrame(main_frame, text="波形预览（点选文件加载波形，拖拽选择截取区间，可试听）",
                                padx=5, pady=5)
        wave_frame.pack(fill=X, pady=5)
        wave_top = Frame(wave_frame)
        wave_top.pack(fill=X)
        self.wave_file_label = Label(wave_top, text="未加载波形", fg="#888")
        self.wave_file_label.pack(side=LEFT)
        self.play_btn = Button(wave_top, text="▶ 试听选区", command=self.play_preview)
        self.play_btn.pack(side=RIGHT, padx=(5, 0))
        self.stop_play_btn = Button(wave_top, text="⏹ 停止播放", command=self.stop_preview,
                                    state=DISABLED, bg="#F44336", fg="white")
        self.stop_play_btn.pack(side=RIGHT)
        self.wave_canvas = Canvas(wave_frame, height=110, bg="#1e1e28", highlightthickness=0,
                                  cursor="hand2")
        self.wave_canvas.pack(fill=X, pady=(5, 0))
        self.sel_info_label = Label(wave_frame, text="", anchor=W, fg="#555")
        self.sel_info_label.pack(fill=X)
        self.wave_canvas.bind("<Configure>", lambda e: self._on_canvas_resize(e.width))
        self.wave_canvas.bind("<ButtonPress-1>", self.on_wave_press)
        self.wave_canvas.bind("<B1-Motion>", self.on_wave_motion)
        self.wave_canvas.bind("<ButtonRelease-1>", self.on_wave_release)

        # 3. 截取模式
        mode_frame = LabelFrame(main_frame, text="截取模式", padx=5, pady=5)
        mode_frame.pack(fill=X, pady=5)
        self.mode_var = StringVar(value=MODE_RANGE)
        radio_row = Frame(mode_frame)
        radio_row.pack(fill=X)
        Radiobutton(radio_row, text="手动时间段", variable=self.mode_var,
                    value=MODE_RANGE, command=self.switch_mode).pack(side=LEFT)
        Radiobutton(radio_row, text="固定时长切片", variable=self.mode_var,
                    value=MODE_SLICE, command=self.switch_mode).pack(side=LEFT, padx=10)
        Radiobutton(radio_row, text="前/后 N 秒", variable=self.mode_var,
                    value=MODE_HEADTAIL, command=self.switch_mode).pack(side=LEFT)

        # 3.1 手动时间段输入
        self.range_input_frame = Frame(mode_frame)
        self.range_start_var = StringVar()
        self.range_end_var = StringVar()
        Label(self.range_input_frame, text="起始时间:").pack(side=LEFT)
        start_entry = Entry(self.range_input_frame, textvariable=self.range_start_var, width=12)
        start_entry.pack(side=LEFT, padx=(2, 10))
        Label(self.range_input_frame, text="结束时间:").pack(side=LEFT)
        end_entry = Entry(self.range_input_frame, textvariable=self.range_end_var, width=12)
        end_entry.pack(side=LEFT, padx=(2, 5))
        Label(self.range_input_frame, text="(HH:MM:SS 或秒数)", fg="#888").pack(side=LEFT)
        # 输入框修改后反向同步到波形选区
        for e in (start_entry, end_entry):
            e.bind("<Return>", self.sync_fields_to_selection)
            e.bind("<FocusOut>", self.sync_fields_to_selection)

        # 3.2 固定时长切片输入
        self.slice_input_frame = Frame(mode_frame)
        self.slice_sec_var = StringVar()
        Label(self.slice_input_frame, text="每片时长(秒):").pack(side=LEFT)
        Entry(self.slice_input_frame, textvariable=self.slice_sec_var, width=8).pack(side=LEFT, padx=(2, 5))
        Label(self.slice_input_frame, text="(整段音频按此时长切成多个文件)", fg="#888").pack(side=LEFT)

        # 3.3 前/后 N 秒输入
        self.headtail_input_frame = Frame(mode_frame)
        self.headtail_pos_var = StringVar(value="head")
        self.headtail_sec_var = StringVar()
        Radiobutton(self.headtail_input_frame, text="保留开头", variable=self.headtail_pos_var,
                    value="head").pack(side=LEFT)
        Radiobutton(self.headtail_input_frame, text="保留结尾", variable=self.headtail_pos_var,
                    value="tail").pack(side=LEFT, padx=5)
        Entry(self.headtail_input_frame, textvariable=self.headtail_sec_var, width=8).pack(side=LEFT, padx=(2, 5))
        Label(self.headtail_input_frame, text="秒", fg="#888").pack(side=LEFT)

        # 4. 输出目录
        output_frame = Frame(main_frame)
        output_frame.pack(fill=X, pady=5)
        Label(output_frame, text="输出目录:").pack(side=LEFT)
        self.output_dir_var = StringVar()
        Entry(output_frame, textvariable=self.output_dir_var, width=50) \
            .pack(side=LEFT, fill=X, expand=True, padx=5)
        Button(output_frame, text="浏览", command=self.select_output_dir).pack(side=LEFT)
        Label(main_frame, text="（输出目录留空时，默认输出到各源文件所在目录的「截取输出」子目录）",
              fg="#888").pack(anchor=W)

        # 5. 线程 + 控制按钮
        ctrl_frame = Frame(main_frame)
        ctrl_frame.pack(fill=X, pady=5)
        Label(ctrl_frame, text="处理线程数:").pack(side=LEFT)
        self.thread_var = StringVar(value="2")
        Spinbox(ctrl_frame, from_=1, to=8, textvariable=self.thread_var, width=5).pack(side=LEFT, padx=5)
        self.start_btn = Button(ctrl_frame, text="开始截取", command=self.start_clip,
                                bg="#4CAF50", fg="white", height=1)
        self.start_btn.pack(side=RIGHT, padx=(5, 0))
        self.cancel_btn = Button(ctrl_frame, text="取消", command=self.cancel_clip,
                                 state=DISABLED, bg="#F44336", fg="white", height=1)
        self.cancel_btn.pack(side=RIGHT)

        # 6. 进度
        self.progress_label = Label(main_frame, text="就绪", anchor=W)
        self.progress_label.pack(fill=X, pady=(5, 0))
        self.progress = ttk.Progressbar(main_frame, mode="determinate")
        self.progress.pack(fill=X, pady=(0, 5))

        # 7. 日志
        log_frame = LabelFrame(main_frame, text="操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, height=6)
        self.log_text.pack(fill=BOTH, expand=True)

    def switch_mode(self):
        """根据所选模式显示对应输入控件"""
        self.range_input_frame.pack_forget()
        self.slice_input_frame.pack_forget()
        self.headtail_input_frame.pack_forget()
        mode = self.mode_var.get()
        if mode == MODE_RANGE:
            self.range_input_frame.pack(fill=X, pady=(5, 0))
        elif mode == MODE_SLICE:
            self.slice_input_frame.pack(fill=X, pady=(5, 0))
        elif mode == MODE_HEADTAIL:
            self.headtail_input_frame.pack(fill=X, pady=(5, 0))

    # ==================== 日志与通知 ====================

    def log(self, msg):
        logger.info(msg)
        # 线程安全：非主线程一律经 after 回主线程更新 UI
        try:
            if threading.current_thread() is threading.main_thread():
                self._append_log(msg)
            else:
                self.root.after(0, self._append_log, msg)
        except Exception:
            pass

    def _append_log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    def show_toast(self, title, message, level="info", duration_ms=3500):
        """右下角 Toast 通知，支持 info/warning/error/success 四种级别"""
        try:
            if threading.current_thread() is not threading.main_thread():
                self.root.after(0, self.show_toast, title, message, level, duration_ms)
                return
            toast = Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)

            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error":   ("#c62828", "#ffebee", "❌"),
                "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
                "warning": ("#e65100", "#fff3e0", "⚠️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)

            header = Frame(toast, bg=bg)
            header.pack(fill=X, padx=10, pady=8)
            Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                  fg=fg, bg=bg).pack(side=LEFT)
            close_btn = Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())

            Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                  fg="#333", bg=bg, wraplength=320, justify=LEFT).pack(padx=12, pady=(4, 10), anchor=W)

            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            x = toast.winfo_screenwidth() - w - 20
            y = toast.winfo_screenheight() - h - 60
            toast.geometry(f"+{x}+{y}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    def update_progress(self, done, total):
        pct = (done / total * 100) if total else 0
        self.root.after(0, lambda: (
            self.progress_label.config(text=f"进度: {done}/{total} 段"),
            self.progress.config(value=pct)
        ))

    # ==================== 文件列表操作 ====================

    def add_files(self):
        files = filedialog.askopenfilenames(title="选择音频文件", filetypes=[(FILETYPE_STR, FILETYPE_STR), ("所有文件", "*.*")])
        added = 0
        for f in files:
            if Path(f).suffix.lower() not in AUDIO_EXTS:
                continue
            if f not in self.input_files:
                self.input_files.append(f)
                self.file_listbox.insert(END, os.path.basename(f))
                added += 1
        if added:
            self.save_config()
            if self.wave_src is None:
                self.file_listbox.selection_set(0)
                self.load_waveform(self.input_files[0])

    def remove_selected(self):
        for idx in reversed(self.file_listbox.curselection()):
            self.file_listbox.delete(idx)
            del self.input_files[idx]
        if self.wave_src and str(self.wave_src) not in self.input_files:
            self._reset_waveform()
        self.save_config()

    def clear_files(self):
        self.input_files.clear()
        self.file_listbox.delete(0, END)
        self._reset_waveform()
        self.save_config()

    def select_output_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_dir_var.get().strip() or os.path.expanduser("~"))
        if path:
            self.output_dir_var.set(path)
            self.save_config()

    # ==================== 波形预览与拖拽选区 ====================

    def on_listbox_select(self, event):
        sel = self.file_listbox.curselection()
        if sel:
            self.load_waveform(self.input_files[sel[0]])

    def load_waveform(self, file_path):
        """后台线程提取波形，不阻塞界面"""
        self.stop_preview()
        src = Path(file_path)
        if not src.exists():
            self._reset_waveform()
            return
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).exists():
            self.wave_file_label.config(text="未加载波形（缺少 FFmpeg）")
            return
        self.wave_src = src
        self.wave_gen += 1
        gen = self.wave_gen
        width = max(200, self.wave_canvas.winfo_width())  # 主线程读取宽度传给后台
        self.wave_peaks = None
        self.wave_file_label.config(text=f"波形加载中: {src.name} ...", fg="#888")
        threading.Thread(target=self._extract_waveform, args=(src, gen, width), daemon=True).start()

    def _extract_waveform(self, src: Path, gen: int, canvas_width: int):
        """ffmpeg 管道读取单声道低采样 PCM，按像素列聚合峰值"""
        cmd = [
            self.ffmpeg_path, "-nostdin",
            "-loglevel", "error",
            "-i", str(src),
            "-f", "s16le", "-ac", "1", "-ar", str(WAVE_RATE),
            "-"
        ]
        try:
            result = self._run_cmd(cmd, timeout=120)
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="ignore").strip()[:200]
                self.root.after(0, self._waveform_failed, src, f"提取波形失败: {err}")
                return
            pcm = result.stdout
            samples = array("h")
            samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
            duration = len(samples) / WAVE_RATE
            width = max(200, canvas_width - 2 * WAVE_PAD)
            bucket = max(1, len(samples) // width)
            peaks = []
            for i in range(0, len(samples), bucket):
                seg = samples[i:i + bucket]
                if seg:
                    peaks.append(max(max(seg), -min(seg)))
                else:
                    peaks.append(0)
            peak_max = max(peaks) if peaks else 1
            self.root.after(0, self._waveform_ready, gen, src, duration, peaks, peak_max)
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            self.root.after(0, self._waveform_failed, src, f"提取波形异常: {e}")

    def _waveform_ready(self, gen, src, duration, peaks, peak_max):
        if gen != self.wave_gen or self.wave_src != src:
            return  # 过期结果，丢弃
        self.wave_duration = duration
        self.wave_peaks = peaks
        self.wave_peak_max = peak_max or 1
        self.wave_file_label.config(text=f"{src.name}  时长 {fmt_hms(duration)}", fg="#333")
        # 用当前时间输入框初始化选区（无效时默认全选）
        st = parse_time_to_seconds(self.range_start_var.get())
        en = parse_time_to_seconds(self.range_end_var.get())
        if st is None or en is None or not (0 <= st < en <= duration):
            st, en = 0.0, duration
        self.sel_start, self.sel_end = st, en
        self.redraw_waveform()
        self.update_sel_info()

    def _waveform_failed(self, src, msg):
        self.wave_file_label.config(text=f"波形加载失败: {src.name}", fg="#c62828")
        self.log(f"❌ {msg}")
        self.show_toast("波形加载失败", msg, level="error", duration_ms=6000)

    def _reset_waveform(self):
        self.stop_preview()
        self.wave_gen += 1
        self.wave_src = None
        self.wave_peaks = None
        self.wave_duration = 0.0
        self.sel_start = self.sel_end = 0.0
        if hasattr(self, "wave_file_label"):
            self.wave_file_label.config(text="未加载波形", fg="#888")
        if hasattr(self, "sel_info_label"):
            self.sel_info_label.config(text="")
        if hasattr(self, "wave_canvas"):
            self.wave_canvas.delete("all")

    # ---------- 坐标换算 ----------

    def _plot_bounds(self):
        w = self.wave_canvas.winfo_width()
        return WAVE_PAD, max(w - WAVE_PAD, WAVE_PAD + 1)

    def _t_to_x(self, t):
        x0, x1 = self._plot_bounds()
        if self.wave_duration <= 0:
            return x0
        return x0 + (x1 - x0) * min(max(t / self.wave_duration, 0.0), 1.0)

    def _x_to_t(self, x):
        x0, x1 = self._plot_bounds()
        if x1 <= x0:
            return 0.0
        ratio = min(max((x - x0) / (x1 - x0), 0.0), 1.0)
        return ratio * self.wave_duration

    # ---------- 绘制 ----------

    def _on_canvas_resize(self, width):
        if self.wave_peaks is not None and width > 20:
            self.redraw_waveform()

    def redraw_waveform(self):
        """重绘波形背景（tag=wave）与选区（tag=sel）"""
        c = self.wave_canvas
        c.delete("all")
        if not self.wave_peaks or self.wave_duration <= 0:
            c.create_text(c.winfo_width() // 2, c.winfo_height() // 2,
                          text="选择音频文件后自动加载波形",
                          fill="#666", font=("Microsoft YaHei UI", 10))
            return
        h = c.winfo_height()
        mid = h / 2
        x0, x1 = self._plot_bounds()
        step = (x1 - x0) / max(len(self.wave_peaks) - 1, 1)
        half = h / 2 - 8
        for i, p in enumerate(self.wave_peaks):
            x = x0 + i * step
            y = (p / self.wave_peak_max) * half
            c.create_line(x, mid - y, x, mid + y, fill="#4a90d9", tags="wave")
        c.create_line(x0, mid, x1, mid, fill="#333", tags="wave")
        # 时间刻度
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            t = self.wave_duration * frac
            x = x0 + (x1 - x0) * frac
            anchor = W if frac == 0 else (E if frac == 1.0 else CENTER)
            c.create_text(x, h - 8, text=fmt_hms(t).split(".")[0], anchor=anchor,
                          fill="#888", font=("Consolas", 8), tags="wave")
        self._draw_selection()

    def _draw_selection(self):
        """只重绘选区层，拖拽过程中高效刷新"""
        c = self.wave_canvas
        c.delete("sel")
        if self.wave_duration <= 0:
            return
        h = c.winfo_height()
        sx = self._t_to_x(self.sel_start)
        ex = self._t_to_x(self.sel_end)
        c.create_rectangle(sx, 2, ex, h - 2, fill="#4CAF50", stipple="gray50",
                           outline="", tags="sel")
        c.create_rectangle(sx - 2.5, 2, sx + 2.5, h - 2, fill="#FFC107", outline="", tags="sel")
        c.create_rectangle(ex - 2.5, 2, ex + 2.5, h - 2, fill="#FFC107", outline="", tags="sel")

    def update_sel_info(self):
        dur = self.sel_end - self.sel_start
        self.sel_info_label.config(
            text=f"选区: {fmt_hms(self.sel_start)} → {fmt_hms(self.sel_end)}（时长 {dur:.2f}s）"
                 f"　拖动黄色手柄调整起止，拖动选区内部整体平移，空白处按下新建选区")

    # ---------- 鼠标交互 ----------

    def on_wave_press(self, event):
        if not self.wave_peaks or self.wave_duration <= 0:
            return
        self.stop_preview()
        t = self._x_to_t(event.x)
        sx = self._t_to_x(self.sel_start)
        ex = self._t_to_x(self.sel_end)
        if abs(event.x - sx) <= HANDLE_HIT:
            self.drag_mode = "left"
        elif abs(event.x - ex) <= HANDLE_HIT:
            self.drag_mode = "right"
        elif sx < event.x < ex:
            self.drag_mode = "move"
            self.drag_anchor = t
        else:
            self.drag_mode = "new"
            self.drag_anchor = t
            self.sel_start = self.sel_end = t
        self.wave_canvas.config(cursor="sb_h_double_arrow")

    def on_wave_motion(self, event):
        if not self.drag_mode:
            return
        t = self._x_to_t(event.x)
        if self.drag_mode == "left":
            self.sel_start = min(t, self.sel_end - MIN_SEL)
        elif self.drag_mode == "right":
            self.sel_end = max(t, self.sel_start + MIN_SEL)
        elif self.drag_mode == "move":
            width = self.sel_end - self.sel_start
            ns = min(max(self.sel_start + (t - self.drag_anchor), 0.0), self.wave_duration - width)
            self.sel_start, self.sel_end = ns, ns + width
            self.drag_anchor = t
        elif self.drag_mode == "new":
            self.sel_start = min(self.drag_anchor, t)
            self.sel_end = max(self.drag_anchor, t)
        self.sel_start = max(self.sel_start, 0.0)
        self.sel_end = min(self.sel_end, self.wave_duration)
        self._draw_selection()
        self.update_sel_info()
        self._sync_selection_to_fields()

    def on_wave_release(self, event):
        if self.drag_mode == "new" and self.sel_end - self.sel_start < MIN_SEL:
            # 单击未拖动：恢复为全选
            self.sel_start, self.sel_end = 0.0, self.wave_duration
            self._draw_selection()
            self.update_sel_info()
        if self.drag_mode:
            self._sync_selection_to_fields()
            self.save_config()
        self.drag_mode = None
        self.wave_canvas.config(cursor="hand2")

    def _sync_selection_to_fields(self):
        """选区实时同步到手动时间段输入框，并自动切到该模式"""
        self.range_start_var.set(fmt_hms(self.sel_start))
        self.range_end_var.set(fmt_hms(self.sel_end))
        if self.mode_var.get() != MODE_RANGE:
            self.mode_var.set(MODE_RANGE)
            self.switch_mode()

    def sync_fields_to_selection(self, event=None):
        """手动修改时间输入框后，把合法值反向同步到波形选区"""
        if self.wave_duration <= 0:
            return
        st = parse_time_to_seconds(self.range_start_var.get())
        en = parse_time_to_seconds(self.range_end_var.get())
        if st is None or en is None or st < 0 or en <= st:
            return
        self.sel_start = min(st, self.wave_duration)
        self.sel_end = min(en, self.wave_duration)
        if self.sel_end - self.sel_start < MIN_SEL:
            self.sel_start = max(0.0, self.sel_end - MIN_SEL)
        self._draw_selection()
        self.update_sel_info()

    # ==================== 试听播放 ====================

    def play_preview(self):
        if self.wave_src is None:
            self.show_toast("提示", "请先在文件列表中选择一个音频文件", level="warning")
            return
        if winsound is None:
            self.show_toast("错误", "当前环境不支持 winsound，无法试听（仅 Windows）",
                            level="error", duration_ms=6000)
            return
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).exists():
            self.show_toast("错误", "FFmpeg 路径无效，无法导出试听音频", level="error", duration_ms=6000)
            return
        if self.is_running:
            self.show_toast("提示", "批量截取进行中，暂不试听", level="warning")
            return
        if self.sel_end - self.sel_start < MIN_SEL:
            self.show_toast("提示", "选区过短，请先在波形上拖拽选择", level="warning")
            return
        self.stop_preview()
        src, start, end = self.wave_src, self.sel_start, self.sel_end
        self.play_btn.config(state=DISABLED)
        self.sel_info_label.config(text=f"正在准备试听: {fmt_hms(start)} → {fmt_hms(end)} ...")
        threading.Thread(target=self._export_preview, args=(src, start, end), daemon=True).start()

    def _export_preview(self, src: Path, start: float, end: float):
        """把选区导出为临时 WAV（22050Hz 单声道，速度快、体积小），完成后 winsound 异步播放"""
        cmd = [
            self.ffmpeg_path, "-nostdin", "-y",
            "-loglevel", "error",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(src),
            "-f", "wav", "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le",
            str(self.preview_wav)
        ]
        try:
            result = self._run_cmd(cmd, timeout=120)
            ok = result.returncode == 0
            err = "" if ok else result.stderr.decode("utf-8", errors="ignore").strip()[:200]
        except subprocess.TimeoutExpired:
            ok, err = False, "导出试听音频超时(120s)"
        except OSError as e:
            ok, err = False, f"ffmpeg 启动失败: {e}"
        if ok:
            self.root.after(0, self._start_playback, end - start)
        else:
            self.log(f"❌ 试听导出失败: {err}")
            self.root.after(0, self._preview_failed, err)

    def _start_playback(self, duration_sec):
        self.preview_token += 1
        token = self.preview_token
        try:
            winsound.PlaySound(str(self.preview_wav),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception as e:
            self._preview_failed(str(e))
            return
        self.preview_playing = True
        self.play_btn.config(state=NORMAL)
        self.stop_play_btn.config(state=NORMAL)
        self.sel_info_label.config(
            text=f"🔊 正在试听: {fmt_hms(self.sel_start)} → {fmt_hms(self.sel_end)}（{duration_sec:.2f}s）")
        self.log(f"🔊 试听: {self.wave_src.name} [{fmt_tc(self.sel_start)} → {fmt_tc(self.sel_end)}]")
        # 播放时长到期后自动恢复状态（winsound 无完成回调）
        self.root.after(int(duration_sec * 1000) + 300,
                        lambda: self._preview_finished(token))

    def _preview_finished(self, token):
        if token != self.preview_token:
            return
        self.preview_playing = False
        self.stop_play_btn.config(state=DISABLED)
        self.update_sel_info()

    def _preview_failed(self, err):
        self.play_btn.config(state=NORMAL)
        self.stop_play_btn.config(state=DISABLED)
        self.update_sel_info()
        self.show_toast("试听失败", err or "无法导出试听音频", level="error", duration_ms=6000)

    def stop_preview(self, delete_temp=False):
        """停止试听；退出窗口时顺带清理临时文件"""
        self.preview_token += 1
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if hasattr(self, "stop_play_btn"):
            try:
                self.stop_play_btn.config(state=DISABLED)
                if self.preview_playing:
                    self.sel_info_label.config(text="⏹ 已停止播放")
            except Exception:
                pass
        self.preview_playing = False
        if delete_temp:
            try:
                if self.preview_wav.exists():
                    self.preview_wav.unlink()
            except OSError:
                pass

    # ==================== ffmpeg / ffprobe 调用 ====================

    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _run_cmd(self, cmd, timeout):
        """统一静默执行外部命令：loglevel error + 无黑窗 + 超时保护"""
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=self._NO_WINDOW
        )

    def _probe_duration(self, src: Path):
        """ffprobe 读取音频时长（秒），失败返回 None"""
        if not self.ffprobe_path:
            return None
        try:
            result = self._run_cmd(
                [self.ffprobe_path, "-hide_banner", "-loglevel", "error",
                 "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                timeout=30
            )
            if result.returncode == 0:
                text = result.stdout.decode("utf-8", errors="ignore").strip()
                return float(text)
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            logger.warning(f"ffprobe 获取时长失败 {src.name}: {e}")
        return None

    def _ffmpeg_clip(self, src: Path, dst: Path, start: float, end: float):
        """重编码精确截取 [start, end] 时间段，返回 (成功, 错误信息)"""
        cmd = [
            self.ffmpeg_path, "-nostdin", "-y",
            "-loglevel", "error",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(src),
            str(dst)
        ]
        try:
            result = self._run_cmd(cmd, timeout=120)
        except subprocess.TimeoutExpired:
            return False, "ffmpeg 执行超时(120s)"
        except OSError as e:
            return False, f"ffmpeg 启动失败: {e}"
        if result.returncode == 0:
            return True, ""
        err = result.stderr.decode("utf-8", errors="ignore").strip()[:200]
        return False, err or f"ffmpeg 返回码 {result.returncode}"

    # ==================== 任务规划 ====================

    def _plan_segments(self, src: Path, duration):
        """根据当前模式生成 (start, end, 输出路径) 段列表；duration 为 None 时按无限处理"""
        mode = self.mode_var.get()
        stem, ext = src.stem, src.suffix.lower()

        if mode == MODE_RANGE:
            start = parse_time_to_seconds(self.range_start_var.get())
            end = parse_time_to_seconds(self.range_end_var.get())
            if start is None or end is None:
                return None, "时间格式错误，请使用 HH:MM:SS 或秒数"
            if start >= end:
                return None, "起始时间必须小于结束时间"
            if duration is not None and start >= duration:
                return None, f"起始时间 {start:.1f}s 超过文件时长 {duration:.1f}s"
            if duration is not None and end > duration:
                self.log(f"⚠️ {src.name}: 结束时间超出文件时长，已截断为 {duration:.1f}s")
                end = duration
            dst = self._output_dir_for(src) / f"{stem}_{fmt_tc(start)}_{fmt_tc(end)}{ext}"
            return [(start, end, unique_path(dst))], None

        if mode == MODE_SLICE:
            try:
                step = float(self.slice_sec_var.get().strip())
            except ValueError:
                return None, "每片时长必须是数字（秒）"
            if step <= 0:
                return None, "每片时长必须大于 0"
            if duration is None:
                return None, "无法获取文件时长（ffprobe 不可用），固定时长切片模式无法使用"
            segments = []
            out_dir = self._output_dir_for(src)
            idx = 1
            t = 0.0
            while t < duration - 0.05:
                end = min(t + step, duration)
                dst = out_dir / f"{stem}_{idx:03d}{ext}"
                segments.append((t, end, unique_path(dst)))
                t = end
                idx += 1
            if not segments:
                return None, f"文件时长过短（{duration:.2f}s），无法切片"
            return segments, None

        if mode == MODE_HEADTAIL:
            try:
                n = float(self.headtail_sec_var.get().strip())
            except ValueError:
                return None, "秒数必须是数字"
            if n <= 0:
                return None, "秒数必须大于 0"
            if duration is None:
                if self.headtail_pos_var.get() == "tail":
                    return None, "无法获取文件时长（ffprobe 不可用），保留结尾模式无法使用"
                start, end = 0.0, n
            else:
                if self.headtail_pos_var.get() == "head":
                    start, end = 0.0, min(n, duration)
                else:
                    start, end = max(0.0, duration - n), duration
            dst = self._output_dir_for(src) / f"{stem}_{fmt_tc(start)}_{fmt_tc(end)}{ext}"
            return [(start, end, unique_path(dst))], None

        return None, "未知截取模式"

    def _output_dir_for(self, src: Path) -> Path:
        """输出目录：界面指定则统一使用，否则为源文件目录下「截取输出」子目录"""
        custom = self.output_dir_var.get().strip()
        out_dir = Path(custom) if custom else src.parent / "截取输出"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    # ==================== 执行控制 ====================

    def cancel_clip(self):
        self.cancel_flag.set()
        self.log("🛑 用户已取消...")

    def start_clip(self):
        if self.is_running:
            return
        if not self.input_files:
            self.show_toast("警告", "请先添加音频文件！", level="warning")
            return
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).exists():
            self.show_toast("错误", "FFmpeg 路径无效，请重新选择。", level="error", duration_ms=6000)
            return

        self.save_config()
        self.is_running = True
        self.cancel_flag.clear()
        self.start_btn.config(state=DISABLED)
        self.cancel_btn.config(state=NORMAL)
        self.progress["value"] = 0
        self.progress_label.config(text="正在截取...")
        threading.Thread(target=self.run_clip, daemon=True).start()

    def run_clip(self):
        files = [Path(f) for f in self.input_files]
        lock = threading.Lock()
        completed = [0]  # 可变引用，供各线程累加

        # 先统一规划所有文件的截取段（含时长探测与参数校验）
        tasks = []       # [(src, segments)]
        for src in files:
            duration = self._probe_duration(src)
            segments, err = self._plan_segments(src, duration)
            if err:
                self.log(f"❌ 跳过 {src.name}: {err}")
            else:
                tasks.append((src, segments))

        total = sum(len(segs) for _, segs in tasks)
        if not tasks or total == 0:
            self.show_toast("错误", "没有可执行的截取任务，请检查参数设置。",
                            level="error", duration_ms=6000)
            self.root.after(0, self._reset_ui)
            return

        self.log(f"▶ 开始截取: {len(tasks)} 个文件，共 {total} 段")

        def bump():
            with lock:
                completed[0] += 1
                self.update_progress(completed[0], total)

        def worker(src, segments):
            for start, end, dst in segments:
                if self.cancel_flag.is_set():
                    return
                self.log(f"▶ {src.name} [{fmt_tc(start)} → {fmt_tc(end)}] → {dst.name}")
                ok, err = self._ffmpeg_clip(src, dst, start, end)
                if ok:
                    self.log(f"✅ 完成: {dst.name}")
                    bump()
                else:
                    self.log(f"❌ 失败: {src.name} - {err}")
                    bump()

        q = Queue()
        for src, segments in tasks:
            q.put((src, segments))

        thread_count = min(self._thread_count(), len(tasks))
        threads = []

        def pull_worker():
            while not q.empty() and not self.cancel_flag.is_set():
                try:
                    src, segments = q.get_nowait()
                except Exception:
                    break
                worker(src, segments)

        for _ in range(thread_count):
            t = threading.Thread(target=pull_worker, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        cancelled = self.cancel_flag.is_set()
        if cancelled:
            status = "🛑 已取消"
            self.show_toast("已取消", f"已完成 {completed[0]}/{total} 段。", level="warning")
        else:
            status = "✅ 截取完成！"
            self.show_toast("完成", f"共处理 {total} 段，成功 {completed[0]} 段，详见日志。",
                            level="success", duration_ms=5000)
        self.root.after(0, lambda: (
            self.progress_label.config(text=status),
            self._reset_ui()
        ))
        self.save_config()

    def _reset_ui(self):
        self.is_running = False
        self.start_btn.config(state=NORMAL)
        self.cancel_btn.config(state=DISABLED)

    # ==================== 窗口关闭 ====================

    def on_closing(self):
        self.stop_preview(delete_temp=True)
        self.save_config()
        if self.is_running:
            if messagebox.askokcancel("退出", "截取正在进行，确定要退出吗？"):
                self.cancel_clip()
                self.root.destroy()
        else:
            self.root.destroy()


# ================== 启动程序 ==================
if __name__ == "__main__":
    root = Tk()
    app = AudioClipper(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
