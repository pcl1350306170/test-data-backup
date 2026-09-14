# -*- coding: utf-8 -*-
"""音频合并工具 - 按目标时长分组合并WAV音频，支持背景音乐，输出多文件"""

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
SCRIPT_NAME = "音频合并工具"
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


def _ffmpeg_export_audio(audio_segment, output_path, fmt="wav", metadata=None, cover_path=None, bg_image_path=None):
    """通过 ffmpeg 管道导出 AudioSegment（避免 pydub 弹黑窗）
    :param fmt: "wav" 或 "mp3"
    :param metadata: 可选元数据字典，如 {"title": "xxx", "artist": "xxx"}
    :param cover_path: 可选封面图片路径（仅 MP3 有效，APIC 类型 Cover (front)）
    :param bg_image_path: 可选播放背景图路径（仅 MP3 有效，APIC 类型 Other）
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

    # 收集所有需要嵌入的图片（仅 MP3 有效）
    images = []
    if fmt == "mp3":
        if cover_path and os.path.isfile(cover_path):
            images.append((cover_path, "Album cover", "Cover (front)"))
        if bg_image_path and os.path.isfile(bg_image_path):
            images.append((bg_image_path, "Background", "Other"))

    if images:
        for img_path, _t, _c in images:
            cmd += ["-i", img_path]
        # 音频映射为流 0，图片依次为流 1..N
        cmd += ["-map", "0:a"]
        for idx in range(1, len(images) + 1):
            cmd += ["-map", f"{idx}:0"]
        cmd += ["-c:v", "mjpeg", "-id3v2_version", "3"]
        for idx, (_p, title, comment) in enumerate(images):
            cmd += [f"-metadata:s:v:{idx}", f"title={title}",
                    f"-metadata:s:v:{idx}", f"comment={comment}"]

    cmd += [*codec_args, *meta_args, output_path]
    result = subprocess.run(cmd,
        input=audio_segment.raw_data,
        capture_output=True, creationflags=_NO_WINDOW, timeout=300)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 导出失败: %s" % (
            (result.stderr or b"").decode("utf-8", errors="replace")[-500:]))


class AudioBatchMergerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(SCRIPT_NAME)
        root.geometry("720x960")
        root.minsize(680, 900)

        # 变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.target_duration = tk.IntVar(value=20)
        self.output_format = tk.StringVar(value="wav")
        self.bgm_path = tk.StringVar()
        self.bgm_volume = tk.IntVar(value=30)
        self.meta_title = tk.StringVar()
        self.meta_artist = tk.StringVar()
        self.meta_album = tk.StringVar()
        self.meta_date = tk.StringVar()
        self.meta_comment = tk.StringVar()
        self.cover_path = tk.StringVar()
        self.bg_image_path = tk.StringVar()
        self._cover_photo = None
        self._bg_image_photo = None
        self.file_count = tk.StringVar(value="共 0 个文件")
        self.status_text = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)

        self.wav_files = []
        self.bgm_audio = None
        self._stop_flag = False
        self._thread = None
        self._save_after_id = None

        self._build_ui()
        self._load_config()

    # ==================== UI ====================

    def _build_ui(self):
        pad = dict(padx=10, pady=5)

        # ---------- 输入目录 ----------
        f_in = ttk.LabelFrame(self.root, text="音频目录（WAV）")
        f_in.pack(fill="x", **pad)
        self.entry_input = ttk.Entry(f_in, textvariable=self.input_dir)
        self.entry_input.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=5)
        self.entry_input.bind("<FocusOut>", self._on_input_path_change)
        self.entry_input.bind("<Return>", self._on_input_path_change)
        ttk.Button(f_in, text="浏览", command=self._browse_input).pack(
            side="left", padx=(0, 10), pady=5)

        # ---------- 输出目录 ----------
        f_out = ttk.LabelFrame(self.root, text="输出目录")
        f_out.pack(fill="x", **pad)
        self.entry_output = ttk.Entry(f_out, textvariable=self.output_dir)
        self.entry_output.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=5)
        self.entry_output.bind("<FocusOut>", lambda e: self._auto_save())
        self.entry_output.bind("<Return>", lambda e: self._auto_save())
        ttk.Button(f_out, text="浏览", command=self._browse_output).pack(
            side="left", padx=(0, 10), pady=5)

        # ---------- 目标时长 & 输出格式 ----------
        f_opt = ttk.LabelFrame(self.root, text="合并选项")
        f_opt.pack(fill="x", **pad)

        row1 = ttk.Frame(f_opt)
        row1.pack(fill="x", padx=10, pady=(5, 2))
        ttk.Label(row1, text="目标时长（分钟）:").pack(side="left")
        self.spin_duration = ttk.Spinbox(
            row1, from_=1, to=999, textvariable=self.target_duration, width=6)
        self.spin_duration.pack(side="left", padx=5)
        self.spin_duration.bind("<FocusOut>", lambda e: self._auto_save())
        ttk.Label(row1, text="输出格式:").pack(side="left", padx=(20, 0))
        ttk.Radiobutton(row1, text="WAV", variable=self.output_format,
                        value="wav", command=self._auto_save).pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="MP3", variable=self.output_format,
                        value="mp3", command=self._auto_save).pack(side="left")

        # ---------- 背景音乐 ----------
        f_bgm = ttk.LabelFrame(self.root, text="背景音乐（可选）")
        f_bgm.pack(fill="x", **pad)
        ttk.Label(f_bgm, textvariable=self.bgm_path,
                  foreground="gray").pack(side="left", fill="x", expand=True,
                                          padx=(10, 5), pady=5)
        ttk.Button(f_bgm, text="选择音乐", command=self._browse_bgm).pack(
            side="left", padx=(0, 10), pady=5)
        f_vol = ttk.Frame(f_bgm)
        f_vol.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(f_vol, text="音量:").pack(side="left")
        ttk.Scale(f_vol, from_=0, to=100, variable=self.bgm_volume,
                  orient="horizontal").pack(side="left", fill="x", expand=True, padx=5)
        self.lbl_vol_val = ttk.Label(f_vol, text="30%")
        self.lbl_vol_val.pack(side="left")
        self.bgm_volume.trace_add("write", self._on_vol_change)

        # ---------- 元数据（可选） ----------
        f_meta = ttk.LabelFrame(self.root, text="音频信息（可选）")
        f_meta.pack(fill="x", **pad)
        meta_grid = ttk.Frame(f_meta)
        meta_grid.pack(fill="x", padx=10, pady=5)
        for i in range(2):
            meta_grid.columnconfigure(i * 2, weight=0)
            meta_grid.columnconfigure(i * 2 + 1, weight=1)
        ttk.Label(meta_grid, text="标题:").grid(row=0, column=0, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_title).grid(
            row=0, column=1, sticky="ew", padx=(0, 10), pady=2)
        ttk.Label(meta_grid, text="作者:").grid(row=0, column=2, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_artist).grid(
            row=0, column=3, sticky="ew", pady=2)
        ttk.Label(meta_grid, text="专辑:").grid(row=1, column=0, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_album).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=2)
        ttk.Label(meta_grid, text="日期:").grid(row=1, column=2, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_date, width=12).grid(
            row=1, column=3, sticky="w", pady=2)
        ttk.Label(meta_grid, text="备注:").grid(row=2, column=0, sticky="e", padx=(0, 5), pady=2)
        ttk.Entry(meta_grid, textvariable=self.meta_comment).grid(
            row=2, column=1, columnspan=3, sticky="ew", pady=2)

        # ---------- 专辑封面 & 播放背景图 ----------
        f_cover = ttk.Frame(f_meta)
        f_cover.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(f_cover, text="封面:").pack(side="left")
        ttk.Entry(f_cover, textvariable=self.cover_path).pack(
            side="left", fill="x", expand=True, padx=5)
        ttk.Button(f_cover, text="浏览", command=self._browse_cover).pack(
            side="left", padx=(0, 5))
        ttk.Button(f_cover, text="清除", width=5,
                   command=self._clear_cover).pack(side="left")

        f_bgimg = ttk.Frame(f_meta)
        f_bgimg.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(f_bgimg, text="播放背景图:").pack(side="left")
        ttk.Entry(f_bgimg, textvariable=self.bg_image_path).pack(
            side="left", fill="x", expand=True, padx=5)
        ttk.Button(f_bgimg, text="浏览", command=self._browse_bg_image).pack(
            side="left", padx=(0, 5))
        ttk.Button(f_bgimg, text="清除", width=5,
                   command=self._clear_bg_image).pack(side="left")

        # 预览容器：左封面，右背景图
        preview_row = ttk.Frame(f_meta)
        preview_row.pack(fill="x", padx=10, pady=(0, 5))
        cover_box = ttk.Frame(preview_row)
        cover_box.pack(side="left", expand=True)
        ttk.Label(cover_box, text="封面预览", anchor="center").pack()
        self.cover_preview = ttk.Label(cover_box, anchor="center")
        self.cover_preview.pack()
        bg_box = ttk.Frame(preview_row)
        bg_box.pack(side="left", expand=True)
        ttk.Label(bg_box, text="背景图预览", anchor="center").pack()
        self.bg_image_preview = ttk.Label(bg_box, anchor="center")
        self.bg_image_preview.pack()

        # ---------- 文件列表 ----------
        f_list = ttk.LabelFrame(self.root, text="音频文件列表")
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
        self.btn_test = ttk.Button(f_btn, text="测试（第1组）", command=self._test_merge)
        self.btn_test.pack(side="left", expand=True, padx=(10, 5))
        self.btn_start = ttk.Button(f_btn, text="开始合并", command=self._start_merge)
        self.btn_start.pack(side="left", expand=True, padx=5)
        self.btn_stop = ttk.Button(f_btn, text="停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", expand=True, padx=(5, 10))

    # ==================== 事件 ====================

    def _on_vol_change(self, *args):
        self.lbl_vol_val.config(text=f"{self.bgm_volume.get()}%")
        self._auto_save()

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
        path = filedialog.askdirectory(title="选择音频目录")
        if path:
            self.input_dir.set(path)
            self._scan_files()

    def _browse_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)
            self._auto_save()

    @staticmethod
    def _check_ffmpeg():
        return shutil.which("ffmpeg") is not None

    def _browse_bgm(self):
        path = filedialog.askopenfilename(
            title="选择背景音乐",
            filetypes=[("WAV 音频", "*.wav"), ("MP3 音频", "*.mp3"),
                       ("所有音频", "*.wav;*.mp3;*.m4a;*.flac"),
                       ("所有文件", "*.*")])
        if path:
            ext = os.path.splitext(path)[1].lower()
            if ext != ".wav" and not self._check_ffmpeg():
                self._show_toast(
                    "缺少 ffmpeg",
                    f"加载 {ext} 格式需要 ffmpeg，请确保已安装并添加到环境变量。",
                    level="error", duration_ms=6000)
                return
            self.bgm_path.set(path)
            try:
                self.bgm_audio = _ffmpeg_load_audio(path)
                logger.info("背景音乐已加载(ffmpeg): %s", path)
            except Exception as e:
                self._show_toast("错误", f"无法加载背景音乐: {e}", level="error")
                self.bgm_audio = None
                self.bgm_path.set("")
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

    def _clear_cover(self):
        self.cover_path.set("")
        self._update_cover_preview()
        self._auto_save()

    def _browse_bg_image(self):
        path = filedialog.askopenfilename(
            title="选择播放背景图",
            initialdir=self.input_dir.get() or None,
            filetypes=[("图片文件", "*.jpg;*.jpeg;*.png"),
                       ("所有文件", "*.*")])
        if path:
            self.bg_image_path.set(path)
            self._update_bg_image_preview()
            self._auto_save()

    def _clear_bg_image(self):
        self.bg_image_path.set("")
        self._update_bg_image_preview()
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
            img.thumbnail((120, 120))
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            self._cover_photo = tk.PhotoImage(data=buf.getvalue())
            self.cover_preview.config(image=self._cover_photo, text="")
        except Exception:
            self._cover_photo = None
            self.cover_preview.config(image="", text=os.path.basename(path))

    def _update_bg_image_preview(self):
        path = self.bg_image_path.get().strip()
        if not path or not os.path.isfile(path):
            self.bg_image_preview.config(image="", text="")
            self._bg_image_photo = None
            return
        try:
            from PIL import Image
            img = Image.open(path)
            img.thumbnail((120, 120))
            import io as _io
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            self._bg_image_photo = tk.PhotoImage(data=buf.getvalue())
            self.bg_image_preview.config(image=self._bg_image_photo, text="")
        except Exception:
            self._bg_image_photo = None
            self.bg_image_preview.config(image="", text=os.path.basename(path))

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

    # ==================== 音频处理 ====================

    @staticmethod
    def _match_channels(audio, target):
        if audio.channels == target.channels:
            return audio
        return audio.set_channels(target.channels)

    def _loop_bgm(self, bgm, target_duration_ms):
        """循环背景音乐到目标时长"""
        if len(bgm) >= target_duration_ms:
            return bgm[:target_duration_ms]
        loops = (target_duration_ms // len(bgm)) + 1
        result = bgm
        for _ in range(loops - 1):
            result = result + bgm
        return result[:target_duration_ms]

    def _group_files(self):
        """按平均时长将文件分组（总时长 / 组数，避免最后一组过短）
        :return: [[文件名, ...], ...]
        """
        target_ms = self.target_duration.get() * 60 * 1000
        dir_path = self.input_dir.get()

        # 第一遍：获取每个文件的时长
        file_durs = []
        for fname in self.wav_files:
            fpath = os.path.join(dir_path, fname)
            try:
                seg = _ffmpeg_load_audio(fpath)
                file_durs.append((fname, len(seg)))
            except Exception as e:
                logger.warning("跳过文件 %s: %s", fname, e)
                continue

        if not file_durs:
            return []

        # 计算总时长和组数，用平均值作为每组的实际目标
        import math
        total_dur = sum(d for _, d in file_durs)
        num_batches = max(1, math.ceil(total_dur / target_ms))
        avg_ms = total_dur / num_batches
        logger.info("音频总时长 %.1f 分钟，目标 %d 分钟，分为 %d 组，平均 %.1f 分钟/组",
                    total_dur / 60000, self.target_duration.get(), num_batches, avg_ms / 60000)

        # 第二遍：按平均时长分组
        batches = []
        current_batch = []
        current_dur = 0

        for fname, dur in file_durs:
            if current_batch and current_dur + dur > avg_ms:
                batches.append(current_batch)
                current_batch = [fname]
                current_dur = dur
            else:
                current_batch.append(fname)
                current_dur += dur

        if current_batch:
            batches.append(current_batch)

        return batches

    # ==================== 操作 ====================

    def _test_merge(self):
        """测试模式：只合并第一组"""
        if AudioSegment is None:
            self._show_toast("错误", "缺少 pydub 库，请执行: pip install pydub", level="error")
            return
        if not self.wav_files:
            self._show_toast("提示", "请先选择音频目录", level="warning")
            return
        out_dir = self.output_dir.get()
        if not out_dir:
            self._show_toast("提示", "请选择输出目录", level="warning")
            return

        self._set_running_state()
        self._stop_flag = False
        self._thread = threading.Thread(target=self._do_merge, args=(True,), daemon=True)
        self._thread.start()

    def _start_merge(self):
        """全量合并"""
        if AudioSegment is None:
            self._show_toast("错误", "缺少 pydub 库，请执行: pip install pydub", level="error")
            return
        if not self.wav_files:
            self._show_toast("提示", "请先选择音频目录", level="warning")
            return
        out_dir = self.output_dir.get()
        if not out_dir:
            self._show_toast("提示", "请选择输出目录", level="warning")
            return

        try:
            self.target_duration.get()
        except tk.TclError:
            self._show_toast("错误", "请输入有效的目标时长", level="error")
            return

        self._save_config()
        self._set_running_state()
        self._stop_flag = False
        self._thread = threading.Thread(target=self._do_merge, args=(False,), daemon=True)
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

    def _build_metadata(self, part_num, total_parts):
        """构建元数据字典，空值字段自动过滤"""
        from datetime import date
        title = self.meta_title.get().strip()
        if title and total_parts > 1:
            title = f"{title} ({part_num}/{total_parts})"
        metadata = {
            "title": title,
            "artist": self.meta_artist.get().strip(),
            "album": self.meta_album.get().strip(),
            "date": self.meta_date.get().strip() or date.today().strftime("%Y"),
            "comment": self.meta_comment.get().strip(),
            "track": f"{part_num}/{total_parts}",
        }
        return {k: v for k, v in metadata.items() if v}

    def _do_merge(self, is_test=False):
        """执行合并（后台线程）"""
        dir_path = self.input_dir.get()
        out_dir = self.output_dir.get()
        fmt = self.output_format.get()
        ext = "mp3" if fmt == "mp3" else "wav"
        tag = "[测试] " if is_test else ""

        # 输出目录不存在则自动创建
        try:
            os.makedirs(out_dir, exist_ok=True)
            logger.info("输出目录已就绪: %s", out_dir)
        except Exception as e:
            logger.error("创建输出目录失败 %s: %s", out_dir, e)
            self.root.after(0, lambda err=str(e): self._show_toast(
                "错误", f"无法创建输出目录: {err}", level="error"))
            self.root.after(0, self._reset_ui)
            return

        # 分组
        self.root.after(0, self.status_text.set, f"{tag}正在分析文件时长...")
        batches = self._group_files()

        if not batches:
            self.root.after(0, lambda: self._show_toast(
                "错误", "没有可处理的音频文件", level="error"))
            self.root.after(0, self._reset_ui)
            return

        if is_test:
            batches = [batches[0]]

        total_batches = len(batches)
        logger.info("%s共 %d 个文件，分为 %d 组", tag, len(self.wav_files), total_batches)

        from datetime import date
        date_str = date.today().strftime("%Y%m%d")
        dir_name = os.path.basename(os.path.normpath(out_dir))

        for batch_idx, batch_files in enumerate(batches):
            if self._stop_flag:
                break

            # 合并当前批次
            combined = AudioSegment.empty()
            for i, fname in enumerate(batch_files):
                if self._stop_flag:
                    break
                fpath = os.path.join(dir_path, fname)
                self.root.after(0, self.status_text.set,
                                f"{tag}第 {batch_idx + 1}/{total_batches} 组: {fname}")
                try:
                    seg = _ffmpeg_load_audio(fpath)
                    combined += seg
                except Exception as e:
                    logger.error("读取失败 %s: %s", fname, e)
                    continue

            if self._stop_flag or len(combined) == 0:
                break

            # 背景音乐叠加
            if self.bgm_audio and not self._stop_flag:
                vol = self.bgm_volume.get()
                if vol > 0:
                    gain = -30.0 + (vol / 100.0) * 30.0
                    bgm = self.bgm_audio.apply_gain(gain)
                    bgm = self._match_channels(bgm, combined)
                    bgm = self._loop_bgm(bgm, len(combined))
                    fade_ms = min(2000, len(bgm))
                    bgm = bgm.fade_out(fade_ms)
                    combined = combined.overlay(bgm)
                    logger.info("第 %d 组背景音乐已叠加 (音量=%d%%)", batch_idx + 1, vol)

            # 导出
            part_num = batch_idx + 1
            filename = f"{dir_name}_{date_str}_{part_num:02d}.{ext}"
            output_path = os.path.join(out_dir, filename)

            self.root.after(0, self.status_text.set,
                            f"{tag}导出 {part_num}/{total_batches}: {filename}")
            progress = ((batch_idx + 1) / total_batches) * 100
            self.root.after(0, self.progress_var.set, progress)

            try:
                metadata = self._build_metadata(part_num, total_batches)
                _ffmpeg_export_audio(
                    combined, output_path, fmt, metadata,
                    self.cover_path.get().strip(),
                    self.bg_image_path.get().strip())
                duration_sec = len(combined) / 1000
                logger.info("第 %d 组导出成功: %s (%.1f秒, %d个文件)",
                            part_num, output_path, duration_sec, len(batch_files))
            except Exception as e:
                logger.error("第 %d 组导出失败: %s", part_num, e)
                self.root.after(0, lambda err=str(e): self._show_toast(
                    "错误", f"导出失败: {err}", level="error"))
                continue

        # 完成
        if not self._stop_flag:
            self.root.after(0, self.progress_var.set, 100)
            self.root.after(0, self.status_text.set, "完成!")
            self.root.after(0, lambda: self._show_toast(
                "完成",
                f"{tag}合并完成! 共输出 {total_batches} 个文件到: {out_dir}",
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
            "target_duration": self.target_duration.get(),
            "output_format": self.output_format.get(),
            "bgm_path": self.bgm_path.get(),
            "bgm_volume": self.bgm_volume.get(),
            "meta_title": self.meta_title.get(),
            "meta_artist": self.meta_artist.get(),
            "meta_album": self.meta_album.get(),
            "meta_date": self.meta_date.get(),
            "meta_comment": self.meta_comment.get(),
            "cover_path": self.cover_path.get(),
            "bg_image_path": self.bg_image_path.get(),
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
                if cfg.get("target_duration"):
                    self.target_duration.set(cfg["target_duration"])
                if cfg.get("output_format"):
                    self.output_format.set(cfg["output_format"])
                if cfg.get("bgm_path"):
                    self.bgm_path.set(cfg["bgm_path"])
                    try:
                        self.bgm_audio = _ffmpeg_load_audio(cfg["bgm_path"])
                    except Exception:
                        self.bgm_audio = None
                        self.bgm_path.set("")
                if cfg.get("bgm_volume") is not None:
                    self.bgm_volume.set(cfg["bgm_volume"])
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
                if cfg.get("bg_image_path"):
                    self.bg_image_path.set(cfg["bg_image_path"])
                    self._update_bg_image_preview()
                logger.info("已加载配置: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("加载配置失败: %s", e)


def main_cli():
    """命令行模式：无 GUI，按目标时长分组合并音频"""
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(description="音频合并工具（CLI模式）")
    parser.add_argument("--input", required=True, help="音频目录（WAV文件）")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument("--duration", type=int, default=20, help="目标时长（分钟，默认20）")
    parser.add_argument("--format", choices=["wav", "mp3"], default="wav", help="输出格式")
    parser.add_argument("--bgm", help="背景音乐文件路径")
    parser.add_argument("--bgm-volume", type=int, default=30, help="BGM音量 0-100（默认30）")
    args = parser.parse_args()

    if AudioSegment is None:
        print("[ERROR] 缺少 pydub 库，请执行: pip install pydub")
        sys.exit(1)

    # 扫描音频文件
    if not os.path.isdir(args.input):
        print(f"[ERROR] 音频目录不存在: {args.input}")
        sys.exit(1)
    wav_files = sorted(
        [f for f in os.listdir(args.input) if f.lower().endswith(".wav")],
        key=lambda x: x.lower())
    if not wav_files:
        print(f"[ERROR] 音频目录为空: {args.input}")
        sys.exit(1)
    print(f"[INFO] 找到 {len(wav_files)} 个 WAV 文件")

    os.makedirs(args.output, exist_ok=True)

    # 加载 BGM
    bgm_audio = None
    if args.bgm and os.path.isfile(args.bgm):
        try:
            bgm_audio = _ffmpeg_load_audio(args.bgm)
            print(f"[INFO] BGM 已加载(ffmpeg): {args.bgm}")
        except Exception as e:
            print(f"[WARN] BGM 加载失败: {e}")

    # 按平均时长分组（总时长 / 组数，避免最后一组过短）
    import math
    target_ms = args.duration * 60 * 1000
    file_durs = []
    for fname in wav_files:
        fpath = os.path.join(args.input, fname)
        try:
            seg = _ffmpeg_load_audio(fpath)
            file_durs.append((fname, len(seg)))
        except Exception as e:
            print(f"[WARN] 跳过 {fname}: {e}")
            continue

    if file_durs:
        total_dur = sum(d for _, d in file_durs)
        num_batches = max(1, math.ceil(total_dur / target_ms))
        avg_ms = total_dur / num_batches
        print(f"[INFO] 总时长 {total_dur / 60000:.1f} 分钟，目标 {args.duration} 分钟，"
              f"分为 {num_batches} 组，平均 {avg_ms / 60000:.1f} 分钟/组")

    batches = []
    current_batch = []
    current_dur = 0
    for fname, dur in file_durs:
        if current_batch and current_dur + dur > avg_ms:
            batches.append(current_batch)
            current_batch = [fname]
            current_dur = dur
        else:
            current_batch.append(fname)
            current_dur += dur
    if current_batch:
        batches.append(current_batch)

    print(f"[INFO] 分为 {len(batches)} 组")
    ext = args.format
    date_str = date.today().strftime("%Y%m%d")
    dir_name = os.path.basename(os.path.normpath(args.output))

    for batch_idx, batch_files in enumerate(batches):
        print(f"\n[INFO] 第 {batch_idx + 1}/{len(batches)} 组 ({len(batch_files)} 个文件)")
        combined = AudioSegment.empty()
        for fname in batch_files:
            fpath = os.path.join(args.input, fname)
            print(f"  - {fname}")
            try:
                seg = _ffmpeg_load_audio(fpath)
                combined += seg
            except Exception as e:
                print(f"  [ERROR] {fname}: {e}")

        if len(combined) == 0:
            print("  [WARN] 合并结果为空，跳过")
            continue

        # BGM
        if bgm_audio and args.bgm_volume > 0:
            gain = -30.0 + (args.bgm_volume / 100.0) * 30.0
            bgm = bgm_audio.apply_gain(gain)
            if bgm.channels != combined.channels:
                bgm = bgm.set_channels(combined.channels)
            if len(bgm) < len(combined):
                loops = (len(combined) // len(bgm)) + 1
                for _ in range(loops - 1):
                    bgm = bgm + bgm_audio.apply_gain(gain)
            bgm = bgm[:len(combined)].fade_out(2000)
            combined = combined.overlay(bgm)

        part_num = batch_idx + 1
        filename = f"{dir_name}_{date_str}_{part_num:02d}.{ext}"
        output_path = os.path.join(args.output, filename)
        _ffmpeg_export_audio(combined, output_path, ext)
        duration_sec = len(combined) / 1000
        print(f"  [OK] {filename} ({duration_sec:.1f}秒)")

    print(f"\n[DONE] 全部完成，共输出 {len(batches)} 个文件到: {args.output}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--input", "--output", "-h", "--help"):
        main_cli()
        return

    root = tk.Tk()
    app = AudioBatchMergerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
