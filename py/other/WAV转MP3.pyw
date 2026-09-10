# -*- coding: utf-8 -*-
"""WAV转MP3 - 批量转换WAV为MP3，支持写入元数据标签"""

import os
import json
import sys
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "WAV转MP3"
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

# ---------- 音频处理（可选依赖） ----------
try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _ffmpeg_load_audio(filepath):
    """通过 ffmpeg 加载音频为 AudioSegment（避免 pydub 弹黑窗）"""
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "stream=sample_rate,channels,channel_layout",
         "-of", "csv=p=0:nk=1", filepath],
        capture_output=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=30)
    sample_rate, channels = 44100, 2
    for line in (probe.stdout or "").strip().split("\n"):
        parts = line.strip().split(",")
        if len(parts) >= 2:
            try:
                sample_rate = int(parts[0])
                channels = int(parts[1])
                break
            except (ValueError, IndexError):
                pass
    sample_fmt = "s16le" if sample_rate <= 48000 else "fltp"
    acodec = "pcm_s16le" if sample_fmt == "s16le" else "pcm_f32le"
    raw_result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", filepath,
         "-f", sample_fmt, "-acodec", acodec,
         "-ar", str(sample_rate), "-ac", str(channels), "pipe:1"],
        capture_output=True, creationflags=_NO_WINDOW, timeout=120)
    if raw_result.returncode != 0:
        raise RuntimeError("ffmpeg 解码失败: %s" % (
            (raw_result.stderr or b"").decode("utf-8", errors="replace")[-500:]))
    if not raw_result.stdout:
        raise RuntimeError("ffmpeg 输出为空，文件可能损坏: %s" % filepath)
    sw = 2 if sample_fmt == "s16le" else 4
    return AudioSegment(
        data=raw_result.stdout,
        sample_width=sw, frame_rate=sample_rate, channels=channels)


def _ffmpeg_export_audio(audio_segment, output_path, fmt="wav", metadata=None, cover_path=None):
    """通过 ffmpeg 管道导出 AudioSegment（避免 pydub 弹黑窗）
    :param fmt: "wav" 或 "mp3"
    :param metadata: 可选元数据字典，如 {"title": "xxx", "artist": "xxx"}
    """
    if fmt == "mp3":
        codec_args = ["-acodec", "libmp3lame", "-q:a", "2"]
    else:
        codec_args = ["-acodec", "pcm_s16le"]
    meta_args = []
    if metadata:
        for k, v in metadata.items():
            if v:
                meta_args.extend(["-metadata", f"{k}={v}"])
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "s16le", "-ar", str(audio_segment.frame_rate),
           "-ac", str(audio_segment.channels), "-i", "pipe:0"]
    if cover_path and fmt == "mp3" and os.path.isfile(cover_path):
        cmd += ["-i", cover_path, "-map", "0:a", "-map", "1:0",
                "-c:v", "mjpeg", "-id3v2_version", "3",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)"]
    cmd += [*codec_args, *meta_args, output_path]
    result = subprocess.run(cmd,
        input=audio_segment.raw_data,
        capture_output=True, creationflags=_NO_WINDOW, timeout=300)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 导出失败: %s" % (
            (result.stderr or b"").decode("utf-8", errors="replace")[-500:]))


class Wav2Mp3App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(SCRIPT_NAME)
        root.geometry("650x700")
        root.minsize(600, 660)

        # 变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.meta_title = tk.StringVar()
        self.meta_artist = tk.StringVar()
        self.meta_album = tk.StringVar()
        self.meta_date = tk.StringVar()
        self.meta_comment = tk.StringVar()
        self.cover_path = tk.StringVar()
        self._cover_photo = None
        self.file_count = tk.StringVar(value="共 0 个文件")
        self.status_text = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)

        self.wav_files = []
        self._stop_flag = False
        self._thread = None
        self._save_after_id = None

        self._build_ui()
        self._load_config()

    # ==================== UI ====================

    def _build_ui(self):
        pad = dict(padx=10, pady=5)

        # ---------- 输入目录 ----------
        f_in = ttk.LabelFrame(self.root, text="WAV 文件目录")
        f_in.pack(fill="x", **pad)
        self.entry_input = ttk.Entry(f_in, textvariable=self.input_dir)
        self.entry_input.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=5)
        self.entry_input.bind("<FocusOut>", self._on_input_path_change)
        self.entry_input.bind("<Return>", self._on_input_path_change)
        ttk.Button(f_in, text="浏览", command=self._browse_input).pack(
            side="left", padx=(0, 10), pady=5)

        # ---------- 输出目录 ----------
        f_out = ttk.LabelFrame(self.root, text="MP3 输出目录")
        f_out.pack(fill="x", **pad)
        self.entry_output = ttk.Entry(f_out, textvariable=self.output_dir)
        self.entry_output.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=5)
        self.entry_output.bind("<FocusOut>", lambda e: self._auto_save())
        self.entry_output.bind("<Return>", lambda e: self._auto_save())
        ttk.Button(f_out, text="浏览", command=self._browse_output).pack(
            side="left", padx=(0, 10), pady=5)

        # ---------- 音频信息 ----------
        f_meta = ttk.LabelFrame(self.root, text="音频信息（可选）")
        f_meta.pack(fill="x", **pad)
        meta_grid = ttk.Frame(f_meta)
        meta_grid.pack(fill="x", padx=10, pady=5)
        for i in range(2):
            meta_grid.columnconfigure(i * 2, weight=0)
            meta_grid.columnconfigure(i * 2 + 1, weight=1)
        ttk.Label(meta_grid, text="标题:").grid(
            row=0, column=0, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_title).grid(
            row=0, column=1, sticky="ew", padx=(0, 10), pady=2)
        ttk.Label(meta_grid, text="作者:").grid(
            row=0, column=2, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_artist).grid(
            row=0, column=3, sticky="ew", pady=2)
        ttk.Label(meta_grid, text="专辑:").grid(
            row=1, column=0, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_album).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=2)
        ttk.Label(meta_grid, text="日期:").grid(
            row=1, column=2, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_date, width=12).grid(
            row=1, column=3, sticky="w", pady=2)
        ttk.Label(meta_grid, text="备注:").grid(
            row=2, column=0, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_comment).grid(
            row=2, column=1, columnspan=3, sticky="ew", pady=2)

        # ---------- 专辑封面 ----------
        f_cover = ttk.Frame(f_meta)
        f_cover.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(f_cover, text="封面:").pack(side="left")
        ttk.Entry(f_cover, textvariable=self.cover_path).pack(
            side="left", fill="x", expand=True, padx=5)
        ttk.Button(f_cover, text="浏览", command=self._browse_cover).pack(
            side="left")
        self.cover_preview = ttk.Label(f_meta, anchor="center")
        self.cover_preview.pack(pady=(0, 5))

        # ---------- 文件列表 ----------
        f_list = ttk.LabelFrame(self.root, text="WAV 文件列表")
        f_list.pack(fill="both", expand=True, **pad)
        ttk.Label(f_list, textvariable=self.file_count).pack(
            side="top", anchor="w", padx=10, pady=(5, 0))
        list_frame = ttk.Frame(f_list)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self.file_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                       selectmode="extended", height=8)
        self.file_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.file_listbox.yview)

        # ---------- 进度条 ----------
        f_prog = ttk.Frame(self.root)
        f_prog.pack(fill="x", **pad)
        self.progress_bar = ttk.Progressbar(f_prog, variable=self.progress_var,
                                            maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(10, 5))
        ttk.Label(f_prog, textvariable=self.status_text, width=20).pack(
            side="left", padx=(0, 10))

        # ---------- 按钮 ----------
        f_btn = ttk.Frame(self.root)
        f_btn.pack(fill="x", **pad)
        self.btn_test = ttk.Button(f_btn, text="测试（首个）", command=self._test_convert)
        self.btn_test.pack(side="left", expand=True, padx=(10, 5))
        self.btn_start = ttk.Button(f_btn, text="开始转换", command=self._start_convert)
        self.btn_start.pack(side="left", expand=True, padx=5)
        self.btn_stop = ttk.Button(f_btn, text="停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", expand=True, padx=(5, 10))

    # ==================== 事件 ====================

    def _on_input_path_change(self, event=None):
        path = self.input_dir.get().strip()
        if path and os.path.isdir(path):
            self.input_dir.set(path)
            self._scan_files()
        self._auto_save()

    def _auto_save(self):
        """防抖自动保存配置（500ms 内多次调用只执行最后一次）"""
        if self._save_after_id is not None:
            self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(500, self._save_config)

    def _browse_input(self):
        path = filedialog.askdirectory(title="选择 WAV 文件目录")
        if path:
            self.input_dir.set(path)
            self._scan_files()

    def _browse_output(self):
        path = filedialog.askdirectory(title="选择 MP3 输出目录")
        if path:
            self.output_dir.set(path)
            self._auto_save()

    def _browse_cover(self):
        path = filedialog.askopenfilename(
            title="选择封面图片",
            initialdir=self.input_dir.get() or None,
            filetypes=[("图片文件", "*.jpg;*.jpeg;*.png"),
                       ("所有文件", "*.*")])
        if path:
            self.cover_path.set(path)
            self._update_cover_preview()
            self._auto_save()

    def _update_cover_preview(self):
        path = self.cover_path.get().strip()
        if not path or not os.path.isfile(path):
            self.cover_preview.config(image="", text="")
            self._cover_photo = None
            return
        try:
            from PIL import Image
            img = Image.open(path)
            img.thumbnail((80, 80))
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            self._cover_photo = tk.PhotoImage(data=buf.getvalue())
            self.cover_preview.config(image=self._cover_photo, text="")
        except Exception:
            self._cover_photo = None
            self.cover_preview.config(image="", text=os.path.basename(path))

    def _scan_files(self):
        """扫描输入目录下的所有 wav 文件"""
        dir_path = self.input_dir.get()
        if not dir_path or not os.path.isdir(dir_path):
            return
        self.wav_files = sorted(
            [f for f in os.listdir(dir_path) if f.lower().endswith(".wav")],
            key=lambda x: x.lower())
        self.file_count.set(f"共 {len(self.wav_files)} 个文件")
        self.file_listbox.delete(0, "end")
        for f in self.wav_files:
            self.file_listbox.insert("end", f)
        logger.info("扫描到 %d 个 WAV 文件: %s", len(self.wav_files), dir_path)
        if not self.wav_files:
            self._show_toast("提示", "目录下没有找到 WAV 文件", level="warning")

    # ==================== 操作 ====================

    def _build_metadata(self, index=None, total=None):
        """构建元数据字典，空值字段自动过滤"""
        from datetime import date
        title = self.meta_title.get().strip()
        if title and total and total > 1 and index is not None:
            title = f"{title} ({index}/{total})"
        metadata = {
            "title": title,
            "artist": self.meta_artist.get().strip(),
            "album": self.meta_album.get().strip(),
            "date": self.meta_date.get().strip() or date.today().strftime("%Y"),
            "comment": self.meta_comment.get().strip(),
        }
        if index is not None and total is not None:
            metadata["track"] = f"{index}/{total}"
        return {k: v for k, v in metadata.items() if v}

    def _test_convert(self):
        """测试模式：只转换第一个文件"""
        if AudioSegment is None:
            self._show_toast("错误", "缺少 pydub 库，请执行: pip install pydub", level="error")
            return
        if not self.wav_files:
            self._show_toast("提示", "请先选择 WAV 文件目录", level="warning")
            return
        out_dir = self.output_dir.get()
        if not out_dir:
            self._show_toast("提示", "请选择输出目录", level="warning")
            return

        self._set_running_state()
        self._stop_flag = False
        self._thread = threading.Thread(target=self._do_convert, args=(True,), daemon=True)
        self._thread.start()

    def _start_convert(self):
        """全量转换"""
        if AudioSegment is None:
            self._show_toast("错误", "缺少 pydub 库，请执行: pip install pydub", level="error")
            return
        if not self.wav_files:
            self._show_toast("提示", "请先选择 WAV 文件目录", level="warning")
            return
        out_dir = self.output_dir.get()
        if not out_dir:
            self._show_toast("提示", "请选择输出目录", level="warning")
            return

        self._save_config()
        self._set_running_state()
        self._stop_flag = False
        self._thread = threading.Thread(target=self._do_convert, args=(False,), daemon=True)
        self._thread.start()

    def _stop(self):
        self._stop_flag = True
        self.status_text.set("正在停止...")
        self._reset_ui()

    def _set_running_state(self):
        self.btn_start.config(state="disabled")
        self.btn_test.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress_var.set(0)

    def _reset_ui(self):
        self.btn_start.config(state="normal")
        self.btn_test.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _do_convert(self, is_test=False):
        """执行转换（后台线程）"""
        dir_path = self.input_dir.get()
        out_dir = self.output_dir.get()
        tag = "[测试] " if is_test else ""

        # 自动创建输出目录（如果不存在）
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            self.root.after(0, lambda err=str(e): self._show_toast(
                "错误", f"无法创建输出目录: {err}", level="error"))
            self.root.after(0, self._reset_ui)
            return

        files = self.wav_files[:1] if is_test else self.wav_files
        total = len(files)

        for i, fname in enumerate(files):
            if self._stop_flag:
                break

            fpath = os.path.join(dir_path, fname)
            mp3_name = os.path.splitext(fname)[0] + ".mp3"
            output_path = os.path.join(out_dir, mp3_name)

            self.root.after(0, self.status_text.set,
                            f"{tag}转换中 {i + 1}/{total}: {fname}")
            self.root.after(0, self.progress_var.set,
                            (i / total) * 100 if total else 0)
            logger.info("%s正在转换 [%d/%d]: %s", tag, i + 1, total, fname)

            try:
                audio = _ffmpeg_load_audio(fpath)
                metadata = self._build_metadata(i + 1, total)
                _ffmpeg_export_audio(audio, output_path, "mp3", metadata, self.cover_path.get().strip())
                duration_sec = len(audio) / 1000
                logger.info("转换成功: %s → %s (%.1f秒)", fname, mp3_name, duration_sec)
            except Exception as e:
                logger.error("转换失败 %s: %s", fname, e)
                self.root.after(0, lambda err=str(e): self._show_toast(
                    "错误", f"转换失败: {err}", level="error"))
                continue

        # 完成
        if not self._stop_flag:
            self.root.after(0, self.progress_var.set, 100)
            self.root.after(0, self.status_text.set, "完成!")
            self.root.after(0, lambda: self._show_toast(
                "完成",
                f"{tag}转换完成! 共 {total} 个文件 → {out_dir}",
                level="success", duration_ms=5000))

        self.root.after(0, self._reset_ui)

    # ==================== Toast 通知 ====================

    def _show_toast(self, title, message, level="info", duration_ms=3500):
        """右下角 Toast 通知，支持 info/warning/error/success 四种级别"""
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)

            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error":   ("#c62828", "#ffebee", "❌"),
                "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
                "warning": ("#e65100", "#fff3e0", "⚠️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)

            header = tk.Frame(toast, bg=bg)
            header.pack(fill=tk.X, padx=10, pady=8)
            tk.Label(header, text=f"{icon} {title}",
                     font=("Microsoft YaHei UI", 11, "bold"),
                     fg=fg, bg=bg).pack(side=tk.LEFT)
            close_btn = tk.Label(header, text="✕", font=("Consolas", 10),
                                 fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())

            tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                     fg="#333", bg=bg, wraplength=320,
                     justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)

            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            sx = toast.winfo_screenwidth()
            sy = toast.winfo_screenheight()
            x = sx - w - 20
            y = sy - h - 60
            toast.geometry(f"+{x}+{y}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    # ==================== 配置持久化 ====================

    def _save_config(self):
        config = {
            "input_dir": self.input_dir.get(),
            "output_dir": self.output_dir.get(),
            "meta_title": self.meta_title.get(),
            "meta_artist": self.meta_artist.get(),
            "meta_album": self.meta_album.get(),
            "meta_date": self.meta_date.get(),
            "meta_comment": self.meta_comment.get(),
            "cover_path": self.cover_path.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("input_dir"):
                    self.input_dir.set(cfg["input_dir"])
                    self._scan_files()
                if cfg.get("output_dir"):
                    self.output_dir.set(cfg["output_dir"])
                if cfg.get("meta_title"):
                    self.meta_title.set(cfg["meta_title"])
                if cfg.get("meta_artist"):
                    self.meta_artist.set(cfg["meta_artist"])
                if cfg.get("meta_album"):
                    self.meta_album.set(cfg["meta_album"])
                if cfg.get("meta_date"):
                    self.meta_date.set(cfg["meta_date"])
                if cfg.get("meta_comment"):
                    self.meta_comment.set(cfg["meta_comment"])
                if cfg.get("cover_path"):
                    self.cover_path.set(cfg["cover_path"])
                    self._update_cover_preview()
                logger.info("已加载配置: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("加载配置失败: %s", e)


def main():
    root = tk.Tk()
    app = Wav2Mp3App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
