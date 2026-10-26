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

# ---------- 音频处理（可选依赖，仅用于兼容旧接口） ----------
try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _sanitize_filename(name):
    """去除文件名中系统不允许的字符"""
    invalid = '<>:"/\\|?*\x00'
    return "".join(c for c in name if c not in invalid).strip()

# 统一的目标音频参数（所有输入都会被规范化到此参数，避免拼接时参数不一致）
_TARGET_SAMPLE_RATE = 44100
_TARGET_CHANNELS = 2


def _ffprobe_duration(filepath):
    """通过 ffprobe 快速获取音频时长（秒），不解码音频数据"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", filepath],
        capture_output=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("ffprobe 失败: %s" % (
            (result.stderr or "").strip()[-300:]))
    text = (result.stdout or "").strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        raise RuntimeError("无法解析时长: %s (输出=%r)" % (filepath, text))


def _ffmpeg_concat_batch(file_paths, output_wav):
    """使用 ffmpeg concat demuxer 合并音频文件列表到统一格式的 WAV
    相比 pydub 内存拼接，避免大量数据在 Python 中处理导致的串台问题
    """
    import tempfile
    list_fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="audio_merge_concat_")
    try:
        with os.fdopen(list_fd, "w", encoding="utf-8") as f:
            for fp in file_paths:
                # ffmpeg concat 文件路径规范：使用正斜杠，单引号需转义
                safe = fp.replace("\\", "/").replace("'", "'\\''")
                f.write("file '%s'\n" % safe)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin",
               "-f", "concat", "-safe", "0", "-i", list_path,
               "-ar", str(_TARGET_SAMPLE_RATE), "-ac", str(_TARGET_CHANNELS),
               "-acodec", "pcm_s16le", output_wav]
        result = subprocess.run(cmd, capture_output=True,
                                creationflags=_NO_WINDOW, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError("ffmpeg concat 失败: %s" % (
                (result.stderr or b"").decode("utf-8", errors="replace")[-500:]))
        if not os.path.isfile(output_wav) or os.path.getsize(output_wav) == 0:
            raise RuntimeError("ffmpeg concat 未生成有效文件: %s" % output_wav)
    finally:
        try:
            os.unlink(list_path)
        except Exception:
            pass


def _ffmpeg_finalize(input_wav, output_path, fmt="wav",
                     bgm_path=None, bgm_volume=30, total_duration=0.0,
                     metadata=None, cover_path=None, bg_image_path=None):
    """最终处理：可选 BGM 叠加 + 元数据/封面嵌入 + 格式转换
    全部由 ffmpeg 一次完成，不再经由 Python 内存
    """
    has_bgm = bool(bgm_path) and os.path.isfile(bgm_path) and bgm_volume > 0

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin", "-i", input_wav]
    next_input = 1

    filter_parts = []
    if has_bgm:
        cmd += ["-i", bgm_path]
        gain_db = -30.0 + (bgm_volume / 100.0) * 30.0
        fade_start = max(0.0, total_duration - 2.0)
        filter_parts.append(
            "[1:a]volume=%.2fdB,aloop=loop=-1:size=2147483647,"
            "atrim=duration=%.3f,afade=t=out:st=%.3f:d=2,"
            "aformat=sample_rates=%d:channel_layouts=stereo[bgm]" % (
                gain_db, total_duration, fade_start, _TARGET_SAMPLE_RATE))
        filter_parts.append(
            "[0:a][bgm]amix=inputs=2:duration=first:normalize=0[out]")
        next_input = 2

    # 收集图片输入（仅 MP3）
    images = []
    if fmt == "mp3":
        if cover_path and os.path.isfile(cover_path):
            images.append((cover_path, "Album cover", "Cover (front)"))
        if bg_image_path and os.path.isfile(bg_image_path):
            images.append((bg_image_path, "Background", "Other"))
        for img_path, _t, _c in images:
            cmd += ["-i", img_path]

    # 音频流映射
    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[out]"]
    else:
        cmd += ["-map", "0:a"]

    # 图片流映射
    img_start = next_input
    if images:
        for idx in range(len(images)):
            cmd += ["-map", "%d:0" % (img_start + idx)]
        cmd += ["-c:v", "mjpeg", "-id3v2_version", "3"]
        for idx, (_p, title, comment) in enumerate(images):
            cmd += ["-metadata:s:v:%d" % idx, "title=%s" % title,
                    "-metadata:s:v:%d" % idx, "comment=%s" % comment]

    # 编码参数
    if fmt == "mp3":
        cmd += ["-acodec", "libmp3lame", "-q:a", "2"]
    else:
        cmd += ["-acodec", "pcm_s16le"]

    # 元数据
    if metadata:
        for k, v in metadata.items():
            if v:
                cmd += ["-metadata", "%s=%s" % (k, v)]

    cmd += [output_path]

    result = subprocess.run(cmd, capture_output=True,
                            creationflags=_NO_WINDOW, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 最终处理失败: %s" % (
            (result.stderr or b"").decode("utf-8", errors="replace")[-500:]))


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
        self.start_num = tk.StringVar(value="1")
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
        ttk.Label(row1, text="起始序号:").pack(side="left", padx=(20, 0))
        self.entry_start_num = ttk.Entry(row1, textvariable=self.start_num, width=6)
        self.entry_start_num.pack(side="left", padx=5)
        self.entry_start_num.bind("<FocusOut>", lambda e: self._auto_save())
        self.entry_start_num.bind("<Return>", lambda e: self._auto_save())
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
            if not self._check_ffmpeg():
                self._show_toast(
                    "缺少 ffmpeg",
                    "合并需要 ffmpeg，请确保已安装并添加到环境变量。",
                    level="error", duration_ms=6000)
                return
            self.bgm_path.set(path)
            # 仅验证文件可读，不再加载到内存（合并时由 ffmpeg 直接读取）
            try:
                dur = _ffprobe_duration(path)
                logger.info("背景音乐已验证: %s (%.1f秒)", path, dur)
            except Exception as e:
                self._show_toast("错误", f"无法读取背景音乐: {e}", level="error")
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
        """按动态目标时长将文件分组，确保各组时长均匀
        :return: [[文件名, ...], ...]
        """
        target_ms = self.target_duration.get() * 60 * 1000
        dir_path = self.input_dir.get()

        # 第一遍：快速获取每个文件的时长（仅读取头信息，不解码音频数据）
        file_durs = []
        for fname in self.wav_files:
            fpath = os.path.join(dir_path, fname)
            try:
                dur_sec = _ffprobe_duration(fpath)
                file_durs.append((fname, int(dur_sec * 1000)))  # 转为毫秒
            except Exception as e:
                logger.warning("跳过文件 %s: %s", fname, e)
                continue

        if not file_durs:
            return []

        # 计算总时长和组数
        import math
        total_dur = sum(d for _, d in file_durs)
        num_batches = max(1, math.ceil(total_dur / target_ms))
        logger.info("音频总时长 %.1f 分钟，目标 %d 分钟，分为 %d 组",
                    total_dur / 60000, self.target_duration.get(), num_batches)

        # 第二遍：动态分组，每组切分后重新计算剩余目标
        batches = []
        current_batch = []
        current_dur = 0
        remaining_dur = total_dur
        remaining_batches = num_batches

        for fname, dur in file_durs:
            if current_batch:
                dynamic_avg = remaining_dur / remaining_batches
                if current_dur + dur > dynamic_avg:
                    batches.append(current_batch)
                    remaining_dur -= current_dur
                    remaining_batches -= 1
                    current_batch = [fname]
                    current_dur = dur
                else:
                    current_batch.append(fname)
                    current_dur += dur
            else:
                current_batch = [fname]
                current_dur = dur

        if current_batch:
            batches.append(current_batch)

        return batches

    # ==================== 操作 ====================

    def _test_merge(self):
        """测试模式：只合并第一组"""
        if not self._check_ffmpeg():
            self._show_toast("错误", "缺少 ffmpeg，请确保已安装并添加到环境变量", level="error")
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
        if not self._check_ffmpeg():
            self._show_toast("错误", "缺少 ffmpeg，请确保已安装并添加到环境变量", level="error")
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
        # 解析起始序号（非法输入回退到 1）
        try:
            start = int(self.start_num.get().strip() or "1")
            if start < 0:
                start = 1
        except (ValueError, tk.TclError):
            start = 1
        # 序号补零宽度 = 用户输入的起始序号字符串长度（如 "001" → 3 位宽）
        width = max(1, len(self.start_num.get().strip() or "1"))
        seq_num = start + part_num - 1
        if title:
            title = f"{title}{seq_num:0{width}d}"
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
        """执行合并（后台线程）—— 使用 ffmpeg concat 代替 pydub 内存拼接"""
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

        dir_name = os.path.basename(os.path.normpath(out_dir))
        bgm_file = self.bgm_path.get().strip()
        bgm_vol = self.bgm_volume.get()

        for batch_idx, batch_files in enumerate(batches):
            if self._stop_flag:
                break

            part_num = batch_idx + 1
            metadata = self._build_metadata(part_num, total_batches)
            title = (metadata.get("title") or "").strip()
            base = _sanitize_filename(title) if title else dir_name
            if not base:
                base = dir_name or f"output_{part_num:02d}"
            filename = f"{base}.{ext}"
            output_path = os.path.join(out_dir, filename)
            temp_wav = os.path.join(out_dir, f"_temp_concat_{part_num:02d}.wav")

            # 构建完整文件路径列表
            file_paths = [os.path.join(dir_path, f) for f in batch_files]

            # Step 1: ffmpeg concat 合并到临时 WAV
            self.root.after(0, self.status_text.set,
                            f"{tag}第 {part_num}/{total_batches} 组: 合并 {len(batch_files)} 个文件...")
            try:
                _ffmpeg_concat_batch(file_paths, temp_wav)
            except Exception as e:
                logger.error("第 %d 组合并失败: %s", part_num, e)
                pn = part_num
                self.root.after(0, lambda err=str(e), p=pn: self._show_toast(
                    "错误", f"第 {p} 组合并失败: {err}", level="error"))
                try:
                    os.unlink(temp_wav)
                except Exception:
                    pass
                continue

            if self._stop_flag:
                try:
                    os.unlink(temp_wav)
                except Exception:
                    pass
                break

            # Step 2: 最终处理（BGM + 元数据 + 封面 + 格式转换）
            self.root.after(0, self.status_text.set,
                            f"{tag}导出 {part_num}/{total_batches}: {filename}")
            progress = ((batch_idx + 1) / total_batches) * 100
            self.root.after(0, self.progress_var.set, progress)

            try:
                total_dur = _ffprobe_duration(temp_wav)
                _ffmpeg_finalize(
                    temp_wav, output_path, fmt,
                    bgm_path=bgm_file if bgm_file else None,
                    bgm_volume=bgm_vol,
                    total_duration=total_dur,
                    metadata=metadata,
                    cover_path=self.cover_path.get().strip(),
                    bg_image_path=self.bg_image_path.get().strip())
                logger.info("第 %d 组导出成功: %s (%.1f秒, %d个文件)",
                            part_num, output_path, total_dur, len(batch_files))
            except Exception as e:
                logger.error("第 %d 组导出失败: %s", part_num, e)
                pn = part_num
                self.root.after(0, lambda err=str(e), p=pn: self._show_toast(
                    "错误", f"第 {p} 组导出失败: {err}", level="error"))
            finally:
                try:
                    os.unlink(temp_wav)
                except Exception:
                    pass

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
            "start_num": self.start_num.get(),
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
                    bgm = cfg["bgm_path"]
                    if os.path.isfile(bgm):
                        self.bgm_path.set(bgm)
                    # 文件不存在则不设置，合并时由 ffmpeg 直接读取
                if cfg.get("bgm_volume") is not None:
                    self.bgm_volume.set(cfg["bgm_volume"])
                if cfg.get("start_num") is not None:
                    self.start_num.set(cfg["start_num"])
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


def _build_cli_metadata(args, part_num, total_parts):
    """CLI 模式下构建元数据（与 GUI 版 _build_metadata 对齐）"""
    from datetime import date
    title = (args.title or "").strip()
    raw = str(args.start_num).strip() or "1"
    try:
        start = int(raw)
        if start < 0:
            start = 1
            raw = "1"
    except ValueError:
        start = 1
        raw = "1"
    width = max(1, len(raw))
    seq_num = start + part_num - 1
    if title:
        title = f"{title}{seq_num:0{width}d}"
    metadata = {
        "title": title,
        "artist": args.artist or "",
        "album": args.album or "",
        "date": args.date or date.today().strftime("%Y"),
        "comment": args.comment or "",
        "track": f"{part_num}/{total_parts}",
    }
    return {k: v for k, v in metadata.items() if v}


def main_cli():
    """命令行模式：无 GUI，按目标时长分组合并音频"""
    import argparse

    parser = argparse.ArgumentParser(description="音频合并工具（CLI模式）")
    parser.add_argument("--input", required=True, help="音频目录（WAV文件）")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument("--duration", type=int, default=20, help="目标时长（分钟，默认20）")
    parser.add_argument("--format", choices=["wav", "mp3"], default="wav", help="输出格式")
    parser.add_argument("--bgm", help="背景音乐文件路径")
    parser.add_argument("--bgm-volume", type=int, default=30, help="BGM音量 0-100（默认30）")
    parser.add_argument("--start-num", default="1", help="标题起始序号（默认1，支持前导零如 055）")
    parser.add_argument("--title", help="标题")
    parser.add_argument("--artist", help="作者")
    parser.add_argument("--album", help="专辑")
    parser.add_argument("--date", help="日期")
    parser.add_argument("--comment", help="备注")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        print("[ERROR] 缺少 ffmpeg，请确保已安装并添加到环境变量")
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

    # 验证 BGM
    bgm_file = None
    if args.bgm and os.path.isfile(args.bgm):
        try:
            dur = _ffprobe_duration(args.bgm)
            bgm_file = args.bgm
            print(f"[INFO] BGM 已验证: {args.bgm} ({dur:.1f}秒)")
        except Exception as e:
            print(f"[WARN] BGM 验证失败: {e}")

    # 用 ffprobe 快速获取时长（不解码音频数据）
    import math
    target_ms = args.duration * 60 * 1000
    file_durs = []
    for fname in wav_files:
        fpath = os.path.join(args.input, fname)
        try:
            dur_sec = _ffprobe_duration(fpath)
            file_durs.append((fname, int(dur_sec * 1000)))
        except Exception as e:
            print(f"[WARN] 跳过 {fname}: {e}")
            continue

    if not file_durs:
        print("[ERROR] 没有可处理的音频文件")
        sys.exit(1)

    total_dur = sum(d for _, d in file_durs)
    num_batches = max(1, math.ceil(total_dur / target_ms))
    print(f"[INFO] 总时长 {total_dur / 60000:.1f} 分钟，目标 {args.duration} 分钟，"
          f"分为 {num_batches} 组")

    # 动态分组
    batches = []
    current_batch = []
    current_dur = 0
    remaining_dur = total_dur
    remaining_batches = num_batches
    for fname, dur in file_durs:
        if current_batch:
            dynamic_avg = remaining_dur / remaining_batches
            if current_dur + dur > dynamic_avg:
                batches.append(current_batch)
                remaining_dur -= current_dur
                remaining_batches -= 1
                current_batch = [fname]
                current_dur = dur
            else:
                current_batch.append(fname)
                current_dur += dur
        else:
            current_batch = [fname]
            current_dur = dur
    if current_batch:
        batches.append(current_batch)

    print(f"[INFO] 分为 {len(batches)} 组")
    ext = args.format
    dir_name = os.path.basename(os.path.normpath(args.output))

    for batch_idx, batch_files in enumerate(batches):
        part_num = batch_idx + 1
        print(f"\n[INFO] 第 {part_num}/{len(batches)} 组 ({len(batch_files)} 个文件)")
        for fname in batch_files:
            print(f"  - {fname}")

        file_paths = [os.path.join(args.input, f) for f in batch_files]
        metadata = _build_cli_metadata(args, part_num, len(batches))
        title = (metadata.get("title") or "").strip()
        base = _sanitize_filename(title) if title else dir_name
        if not base:
            base = dir_name or f"output_{part_num:02d}"
        filename = f"{base}.{ext}"
        output_path = os.path.join(args.output, filename)
        temp_wav = os.path.join(args.output, f"_temp_concat_{part_num:02d}.wav")

        try:
            # Step 1: ffmpeg concat 合并
            _ffmpeg_concat_batch(file_paths, temp_wav)
            total_sec = _ffprobe_duration(temp_wav)

            # Step 2: 最终处理（BGM + 格式转换）
            _ffmpeg_finalize(
                temp_wav, output_path, ext,
                bgm_path=bgm_file,
                bgm_volume=args.bgm_volume,
                total_duration=total_sec,
                metadata=metadata,
                cover_path=None,
                bg_image_path=None)
            print(f"  [OK] {filename} ({total_sec:.1f}秒)")
        except Exception as e:
            print(f"  [ERROR] 第 {part_num} 组失败: {e}")
        finally:
            try:
                os.unlink(temp_wav)
            except Exception:
                pass

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
