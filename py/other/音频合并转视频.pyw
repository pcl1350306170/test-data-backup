# -*- coding: utf-8 -*-
"""音频合并转视频 - 合并多个WAV音频，支持添加背景音乐、图片转视频"""

import os
import json
import sys
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "音频合并转视频"
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


class AudioMergerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("音频合并转视频")
        root.geometry("750x720")
        root.minsize(700, 680)

        # 变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.bgm_path = tk.StringVar()
        self.bgm_volume = tk.IntVar(value=30)
        self.generate_video = tk.BooleanVar(value=False)
        self.image_dir = tk.StringVar()
        self.file_count = tk.StringVar(value="共 0 个文件")
        self.png_count = tk.StringVar(value="共 0 张图片")
        self.status_text = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)

        self.wav_files = []
        self.png_files = []
        self.bgm_audio = None
        self._stop_flag = False
        self._thread = None
        self._save_after_id = None  # 防抖自动保存

        self._build_ui()
        self._load_config()

    # ==================== UI ====================

    def _build_ui(self):
        pad = dict(padx=10, pady=5)

        # ---------- 输入目录 ----------
        f_in = ttk.LabelFrame(self.root, text="音频目录")
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

        # ---------- 视频生成 ----------
        f_video = ttk.LabelFrame(self.root, text="视频生成（可选）")
        f_video.pack(fill="x", **pad)

        ttk.Checkbutton(f_video, text="合并后自动生成视频",
                        variable=self.generate_video,
                        command=self._on_video_toggle).pack(
            side="left", padx=10, pady=5)

        self.f_img = ttk.Frame(f_video)
        self.f_img.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(self.f_img, text="图片目录:").pack(side="left")
        self.entry_image = ttk.Entry(self.f_img, textvariable=self.image_dir)
        self.entry_image.pack(side="left", fill="x", expand=True, padx=5)
        self.entry_image.bind("<FocusOut>", self._on_image_path_change)
        self.entry_image.bind("<Return>", self._on_image_path_change)
        ttk.Button(self.f_img, text="浏览",
                   command=self._browse_image_dir).pack(side="left")
        self.lbl_png_count = ttk.Label(f_video, textvariable=self.png_count,
                                       foreground="gray")
        self.lbl_png_count.pack(anchor="w", padx=10, pady=(0, 5))
        self.f_img.state(["disabled"])

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
        self.btn_test = ttk.Button(f_btn, text="试听（前3个）", command=self._test_merge)
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
        """手动输入路径后，失焦或回车时识别并扫描"""
        path = self.input_dir.get().strip()
        if path and os.path.isdir(path):
            self.input_dir.set(path)
            self._scan_files()
        self._auto_save()

    def _browse_image_dir(self):
        path = filedialog.askdirectory(title="选择图片目录")
        if path:
            self.image_dir.set(path)
            self._scan_images()
            self._auto_save()

    def _on_image_path_change(self, event=None):
        """手动输入图片目录路径后识别"""
        path = self.image_dir.get().strip()
        if path and os.path.isdir(path):
            self.image_dir.set(path)
            self._scan_images()
        self._auto_save()

    def _on_video_toggle(self):
        """勾选/取消视频生成时启用/禁用图片目录区域"""
        if self.generate_video.get():
            self.f_img.state(["!disabled"])
            self.entry_input.configure(state="!disabled")  # 确保不被影响
        else:
            self.f_img.state(["disabled"])
        self._auto_save()

    def _scan_images(self):
        """扫描图片目录下的所有 png 文件"""
        dir_path = self.image_dir.get()
        if not dir_path or not os.path.isdir(dir_path):
            self.png_files = []
            self.png_count.set("共 0 张图片")
            return
        self.png_files = sorted(
            [f for f in os.listdir(dir_path) if f.lower().endswith(".png")],
            key=lambda x: x.lower())
        self.png_count.set(f"共 {len(self.png_files)} 张图片")
        logger.info("扫描到 %d 张 PNG 图片: %s", len(self.png_files), dir_path)

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

    @staticmethod
    def _check_ffmpeg():
        """检测 ffmpeg 是否可用"""
        return shutil.which("ffmpeg") is not None

    def _browse_bgm(self):
        path = filedialog.askopenfilename(
            title="选择背景音乐",
            filetypes=[("WAV 音频", "*.wav"), ("MP3 音频", "*.mp3"),
                       ("所有音频", "*.wav;*.mp3;*.m4a;*.flac"),
                       ("所有文件", "*.*")])
        if path:
            ext = os.path.splitext(path)[1].lower()
            # 非 wav 格式需要 ffmpeg
            if ext != ".wav" and not self._check_ffmpeg():
                self._show_toast(
                    "缺少 ffmpeg",
                    f"加载 {ext} 格式需要 ffmpeg，请确保已安装并添加到环境变量。",
                    level="error", duration_ms=6000)
                return
            self.bgm_path.set(path)
            try:
                self.bgm_audio = AudioSegment.from_file(path)
                logger.info("背景音乐已加载: %s", path)
            except Exception as e:
                self._show_toast("错误", f"无法加载背景音乐: {e}", level="error")
                self.bgm_audio = None
                self.bgm_path.set("")

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
        """将 audio 的声道数匹配到 target"""
        if audio.channels == target.channels:
            return audio
        if target.channels == 2 and audio.channels == 1:
            return audio.set_channels(2)
        if target.channels == 1 and audio.channels == 2:
            return audio.set_channels(1)
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

    def _merge_files(self, file_list, output_path, is_test=False):
        """
        核心合并逻辑
        :param file_list: 要合并的文件名列表
        :param output_path: 输出文件路径
        :param is_test: 是否为试听模式
        """
        dir_path = self.input_dir.get()
        combined = AudioSegment.empty()
        segment_durations = []  # 记录每段音频时长（用于视频生成）
        total = len(file_list)
        tag = "[试听] " if is_test else ""

        for i, fname in enumerate(file_list):
            if self._stop_flag:
                break

            fpath = os.path.join(dir_path, fname)
            self.root.after(0, self.status_text.set,
                            f"{tag}合并中 {i + 1}/{total}: {fname}")
            self.root.after(0, self.progress_var.set,
                            (i / total) * 100 if total else 0)
            logger.info("%s正在合并 [%d/%d]: %s", tag, i + 1, total, fname)

            try:
                seg = AudioSegment.from_wav(fpath)
                segment_durations.append(len(seg) / 1000.0)  # 秒
                combined += seg
            except Exception as e:
                logger.error("读取失败 %s: %s", fname, e)
                continue

        if self._stop_flag or len(combined) == 0:
            self.root.after(0, self._reset_ui)
            return

        # 背景音乐叠加
        if self.bgm_audio and not self._stop_flag:
            self.root.after(0, self.status_text.set, f"{tag}正在叠加背景音乐...")
            vol = self.bgm_volume.get()
            if vol > 0:
                # 音量映射：0-100 → -inf ~ 0 dB
                gain = -30.0 + (vol / 100.0) * 30.0
                bgm = self.bgm_audio.apply_gain(gain)
                bgm = self._match_channels(bgm, combined)
                bgm = self._loop_bgm(bgm, len(combined))
                # 尾部 2 秒淡出
                fade_ms = min(2000, len(bgm))
                bgm = bgm.fade_out(fade_ms)
                combined = combined.overlay(bgm)
                logger.info("背景音乐已叠加 (音量=%d%%)", vol)

        # 导出音频
        self.root.after(0, self.status_text.set, f"{tag}正在导出音频...")
        self.root.after(0, self.progress_var.set, 90)
        try:
            combined.export(output_path, format="wav")
            duration_sec = len(combined) / 1000
            logger.info("%s音频导出成功: %s (%.1f秒)", tag, output_path, duration_sec)
        except Exception as e:
            logger.error("导出失败: %s", e)
            self.root.after(0, lambda: self._show_toast("错误", f"导出失败: {e}", level="error"))
            self.root.after(0, self._reset_ui)
            return

        # 视频生成（非试听模式 + 勾选了生成视频）
        if (not is_test and self.generate_video.get()
                and self.png_files and not self._stop_flag):
            video_path = self._get_video_output_path()
            self.root.after(0, self.status_text.set, f"正在生成视频...")
            self.root.after(0, self.progress_var.set, 95)
            success = self._generate_video(output_path, video_path,
                                           file_list, segment_durations)
            if success:
                self.root.after(0, self.progress_var.set, 100)
                self.root.after(0, lambda: self._show_toast(
                    "完成",
                    f"合并完成! 视频: {video_path}  时长: {duration_sec:.1f}秒",
                    level="success", duration_ms=5000))
            else:
                self.root.after(0, self.progress_var.set, 100)
                self.root.after(0, lambda: self._show_toast(
                    "部分完成", "音频已导出，但视频生成失败，请查看日志。",
                    level="warning", duration_ms=6000))
        else:
            self.root.after(0, self.progress_var.set, 100)
            self.root.after(0, self.status_text.set,
                            f"{tag}完成! 时长 {duration_sec:.1f}秒")
            self.root.after(0, lambda: self._show_toast(
                "完成",
                f"{'[试听] ' if is_test else ''}合并完成! 输出: {output_path}  时长: {duration_sec:.1f}秒",
                level="success", duration_ms=5000))

        self.root.after(0, self._reset_ui)

    def _get_output_path(self, suffix=""):
        """生成输出路径：输出目录名_日期[_suffix].wav"""
        out_dir = self.output_dir.get()
        dir_name = os.path.basename(os.path.normpath(out_dir))
        from datetime import date
        date_str = date.today().strftime("%Y%m%d")
        filename = f"{dir_name}_{date_str}{suffix}.wav"
        return os.path.join(out_dir, filename)

    def _get_video_output_path(self):
        """生成视频输出路径：输出目录名_日期.mp4"""
        out_dir = self.output_dir.get()
        dir_name = os.path.basename(os.path.normpath(out_dir))
        from datetime import date
        date_str = date.today().strftime("%Y%m%d")
        filename = f"{dir_name}_{date_str}.mp4"
        return os.path.join(out_dir, filename)

    def _generate_video(self, audio_path, video_path, file_list, segment_durations):
        """
        使用 ffmpeg 将图片+音频合成为视频
        :param audio_path: 合并后的音频文件路径
        :param video_path: 视频输出路径
        :param file_list: 音频文件名列表（与图片一一对应）
        :param segment_durations: 每段音频的时长（秒）
        :return: True=成功, False=失败
        """
        if not self._check_ffmpeg():
            logger.error("ffmpeg 不可用，无法生成视频")
            return False

        img_dir = self.image_dir.get()
        total = len(file_list)

        # 校验图片数量
        if len(self.png_files) != len(self.wav_files):
            logger.error("图片数量(%d)与音频数量(%d)不一致",
                         len(self.png_files), len(self.wav_files))
            self.root.after(0, lambda: self._show_toast(
                "数量不匹配",
                f"图片({len(self.png_files)})与音频({len(self.wav_files)})数量不一致",
                level="error", duration_ms=6000))
            return False

        try:
            # 创建 concat 清单文件
            concat_file = os.path.join(tempfile.gettempdir(), "audio_merger_concat.txt")
            with open(concat_file, "w", encoding="utf-8") as f:
                for i, fname in enumerate(file_list):
                    # 音频文件名与图片文件名一一对应（去掉扩展名匹配）
                    base = os.path.splitext(fname)[0]
                    # 查找对应的 png 文件
                    png_name = base + ".png"
                    png_match = [p for p in self.png_files if p.lower() == png_name.lower()]
                    if not png_match:
                        logger.warning("未找到匹配图片: %s -> %s", fname, png_name)
                        continue
                    img_path = os.path.join(img_dir, png_match[0]).replace("\\", "/")
                    dur = segment_durations[i] if i < len(segment_durations) else 1.0
                    f.write(f"file '{img_path}'\n")
                    f.write(f"duration {dur}\n")
                # 最后一张图片需要再写一次（ffmpeg concat 的已知行为）
                if file_list:
                    base = os.path.splitext(file_list[-1])[0]
                    png_match = [p for p in self.png_files
                                 if p.lower() == (base + ".png").lower()]
                    if png_match:
                        last_img = os.path.join(img_dir, png_match[0]).replace("\\", "/")
                        f.write(f"file '{last_img}'\n")

            logger.info("concat 清单已生成: %s (%d 段)", concat_file, total)

            # 构建 ffmpeg 命令
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_file,
                "-i", audio_path,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                video_path
            ]

            logger.info("开始生成视频: %s", video_path)
            self.root.after(0, self.status_text.set, "ffmpeg 正在生成视频...")

            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)

            if result.returncode == 0:
                logger.info("视频生成成功: %s", video_path)
                return True
            else:
                logger.error("ffmpeg 失败 (code=%d): %s",
                             result.returncode, result.stderr[-500:] if result.stderr else "")
                return False

        except Exception as e:
            logger.error("视频生成异常: %s", e)
            return False

    # ==================== 操作 ====================

    def _test_merge(self):
        """试听模式：合并前 3 个文件"""
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

        files = self.wav_files[:3]
        output = self._get_output_path("_试听")
        self._set_running_state()
        self._stop_flag = False
        self._thread = threading.Thread(target=self._merge_files,
                                        args=(files, output, True), daemon=True)
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

        self._save_config()
        output = self._get_output_path()
        self._set_running_state()
        self._stop_flag = False
        self._thread = threading.Thread(target=self._merge_files,
                                        args=(self.wav_files, output, False),
                                        daemon=True)
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
            tk.Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                     fg=fg, bg=bg).pack(side=tk.LEFT)
            close_btn = tk.Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())

            tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                     fg="#333", bg=bg, wraplength=320, justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)

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
            "bgm_path": self.bgm_path.get(),
            "bgm_volume": self.bgm_volume.get(),
            "generate_video": self.generate_video.get(),
            "image_dir": self.image_dir.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    def _load_config(self):
        try:
            # 兼容旧配置文件名
            config_path = CONFIG_PATH
            old_config = CONFIG_DIR / "config_audio_merger.json"
            if not config_path.exists() and old_config.exists():
                config_path = old_config
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("input_dir"):
                    self.input_dir.set(cfg["input_dir"])
                    self._scan_files()
                if cfg.get("output_dir"):
                    self.output_dir.set(cfg["output_dir"])
                if cfg.get("bgm_path"):
                    self.bgm_path.set(cfg["bgm_path"])
                    try:
                        self.bgm_audio = AudioSegment.from_file(cfg["bgm_path"])
                    except Exception:
                        self.bgm_audio = None
                        self.bgm_path.set("")
                if cfg.get("bgm_volume") is not None:
                    self.bgm_volume.set(cfg["bgm_volume"])
                if cfg.get("generate_video"):
                    self.generate_video.set(True)
                    self.f_img.state(["!disabled"])
                if cfg.get("image_dir"):
                    self.image_dir.set(cfg["image_dir"])
                    self._scan_images()
                logger.info("已加载配置: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("加载配置失败: %s", e)


if __name__ == "__main__":
    root = tk.Tk()
    app = AudioMergerApp(root)
    root.mainloop()
