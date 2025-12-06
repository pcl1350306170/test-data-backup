# youtube_downloader.pyw

import os
import sys
import json
import logging
import threading
import time
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "youtube_downloader"
CONFIG_ROOT = Path(r"D:\book\封面")
CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_ROOT / f"config_{SCRIPT_NAME}.json"
LOG_DIR = SCRIPT_DIR / "json" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# 尝试导入 pytube
try:
    from pytube import YouTube
except ImportError:
    root = Tk()
    root.withdraw()
    messagebox.showerror("依赖缺失", "请先安装 pytube：\npip install pytube")
    sys.exit(1)


class YouTubeDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube 视频/音频下载器（支持 FFmpeg 转码）")
        self.root.geometry("850x700")
        self.root.minsize(750, 650)

        # 控制变量
        self.is_paused = False
        self.is_cancelled = False
        self.current_thread = None

        # 加载配置
        self.config = self.load_config()

        # 创建界面
        self.create_widgets()
        self.apply_config()

        # 启动时检查 FFmpeg
        if not self.is_ffmpeg_available():
            self.log("⚠️ 警告：未检测到 FFmpeg，音频转码功能将不可用！")
            root.after(1000, lambda: messagebox.showwarning(
                "FFmpeg 缺失",
                "未检测到 FFmpeg！\n请从 https://ffmpeg.org 下载并添加到系统 PATH\n否则无法转码为 mp3/wav/flac"
            ))

    def is_ffmpeg_available(self):
        return shutil.which("ffmpeg") is not None

    def convert_with_ffmpeg(self, input_path, output_path, target_format):
        if not self.is_ffmpeg_available():
            raise RuntimeError("FFmpeg 未安装或未加入系统 PATH")

        cmd = ["ffmpeg", "-i", str(input_path), "-vn", "-y"]
        if target_format == "mp3":
            cmd += ["-codec:a", "libmp3lame", "-b:a", "192k"]
        elif target_format == "wav":
            cmd += ["-codec:a", "pcm_s16le"]
        elif target_format == "flac":
            cmd += ["-codec:a", "flac"]
        else:
            raise ValueError(f"不支持的格式: {target_format}")
        cmd.append(str(output_path))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg 错误: {result.stderr.strip()}")
            return True
        except Exception as e:
            raise RuntimeError(f"FFmpeg 执行失败: {e}")

    def load_config(self):
        default_config = {
            "urls": [],
            "save_dir": str(Path.home() / "Downloads"),
            "download_type": "video",
            "video_resolution": "720p",
            "audio_format": "mp3",
            "max_retries": 3,
            "thread_count": 2
        }
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
        return default_config

    def save_config(self):
        config = {
            "urls": [url.strip() for url in self.url_text.get("1.0", END).splitlines() if url.strip()],
            "save_dir": self.save_dir_var.get(),
            "download_type": self.download_type.get(),
            "video_resolution": self.resolution_var.get(),
            "audio_format": self.audio_format_var.get(),
            "max_retries": int(self.retry_var.get()),
            "thread_count": int(self.thread_var.get())
        }
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def apply_config(self):
        urls = "\n".join(self.config.get("urls", []))
        self.url_text.delete("1.0", END)
        self.url_text.insert("1.0", urls)

        self.save_dir_var.set(self.config.get("save_dir", str(Path.home() / "Downloads")))
        self.download_type.set(self.config.get("download_type", "video"))
        self.resolution_var.set(self.config.get("video_resolution", "720p"))
        self.audio_format_var.set(self.config.get("audio_format", "mp3"))
        self.retry_var.set(str(self.config.get("max_retries", 3)))
        self.thread_var.set(str(self.config.get("thread_count", 2)))

        self.download_type.trace_add("write", self.on_download_type_change)
        self.on_download_type_change()

    def on_download_type_change(self, *args):
        if self.download_type.get() == "video":
            self.video_options_frame.pack(fill=X, padx=10, pady=5)
            self.audio_options_frame.pack_forget()
        else:
            self.video_options_frame.pack_forget()
            self.audio_options_frame.pack(fill=X, padx=10, pady=5)

    def create_widgets(self):
        main_frame = Frame(self.root)
        main_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # URL 输入
        url_frame = LabelFrame(main_frame, text="YouTube 视频链接（每行一个，支持带 &list= 的链接）", padx=5, pady=5)
        url_frame.pack(fill=X, pady=5)
        self.url_text = Text(url_frame, height=6)
        self.url_text.pack(fill=X)

        # 保存目录
        dir_frame = Frame(main_frame)
        dir_frame.pack(fill=X, pady=5)
        Label(dir_frame, text="保存目录:").pack(side=LEFT)
        self.save_dir_var = StringVar()
        Entry(dir_frame, textvariable=self.save_dir_var, width=60).pack(side=LEFT, fill=X, expand=True, padx=5)
        Button(dir_frame, text="浏览", command=self.select_save_dir).pack(side=RIGHT)

        # 下载类型
        type_frame = Frame(main_frame)
        type_frame.pack(fill=X, pady=5)
        self.download_type = StringVar(value="video")
        Radiobutton(type_frame, text="下载视频", variable=self.download_type, value="video").pack(side=LEFT)
        Radiobutton(type_frame, text="仅下载音频（支持 FFmpeg 转码）", variable=self.download_type, value="audio").pack(side=LEFT)

        # 视频选项
        self.video_options_frame = LabelFrame(main_frame, text="视频选项", padx=5, pady=5)
        Label(self.video_options_frame, text="清晰度:").pack(side=LEFT)
        self.resolution_var = StringVar()
        resolutions = ["144p", "240p", "360p", "480p", "720p", "1080p"]
        OptionMenu(self.video_options_frame, self.resolution_var, *resolutions).pack(side=LEFT, padx=5)

        # 音频选项
        self.audio_options_frame = LabelFrame(main_frame, text="音频输出格式（需 FFmpeg）", padx=5, pady=5)
        Label(self.audio_options_frame, text="格式:").pack(side=LEFT)
        self.audio_format_var = StringVar()
        formats = ["mp3", "wav", "flac"]  # 支持 FFmpeg 转码的格式
        OptionMenu(self.audio_options_frame, self.audio_format_var, *formats).pack(side=LEFT, padx=5)

        # 高级设置
        advanced_frame = LabelFrame(main_frame, text="高级设置", padx=5, pady=5)
        advanced_frame.pack(fill=X, pady=5)

        retry_frame = Frame(advanced_frame)
        retry_frame.pack(fill=X, pady=2)
        Label(retry_frame, text="最大重试次数:").pack(side=LEFT)
        self.retry_var = StringVar(value="3")
        Spinbox(retry_frame, from_=1, to=10, textvariable=self.retry_var, width=5).pack(side=LEFT, padx=5)

        thread_frame = Frame(advanced_frame)
        thread_frame.pack(fill=X, pady=2)
        Label(thread_frame, text="并发线程数:").pack(side=LEFT)
        self.thread_var = StringVar(value="2")
        Spinbox(thread_frame, from_=1, to=5, textvariable=self.thread_var, width=5).pack(side=LEFT, padx=5)

        # 控制按钮
        btn_frame = Frame(main_frame)
        btn_frame.pack(fill=X, pady=10)
        self.start_btn = Button(btn_frame, text="开始下载", command=self.start_download, bg="#4CAF50", fg="white", height=2)
        self.start_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        self.pause_btn = Button(btn_frame, text="暂停", command=self.toggle_pause, state=DISABLED, bg="#FFC107", height=2)
        self.pause_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        self.cancel_btn = Button(btn_frame, text="取消", command=self.cancel_download, state=DISABLED, bg="#F44336", fg="white", height=2)
        self.cancel_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))

        # 进度
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=X, pady=5)
        self.progress_label = Label(main_frame, text="就绪")
        self.progress_label.pack()

        # 日志
        log_frame = LabelFrame(main_frame, text="操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, height=10)
        self.log_text.pack(fill=BOTH, expand=True)

    def select_save_dir(self):
        path = filedialog.askdirectory(initialdir=self.save_dir_var.get())
        if path:
            self.save_dir_var.set(path)

    def log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def start_download(self):
        urls = [u.strip() for u in self.url_text.get("1.0", END).splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("警告", "请输入至少一个 YouTube 链接！")
            return
        if not self.save_dir_var.get().strip():
            messagebox.showwarning("警告", "请选择保存目录！")
            return

        self.save_config()

        self.is_paused = False
        self.is_cancelled = False
        self.start_btn.config(state=DISABLED)
        self.pause_btn.config(state=NORMAL, text="暂停")
        self.cancel_btn.config(state=NORMAL)

        self.current_thread = threading.Thread(target=self.download_worker, daemon=True)
        self.current_thread.start()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.pause_btn.config(text="继续" if self.is_paused else "暂停")

    def cancel_download(self):
        self.is_cancelled = True
        self.log("用户取消下载...")

    def download_worker(self):
        urls = [u.strip() for u in self.url_text.get("1.0", END).splitlines() if u.strip()]
        save_dir = Path(self.save_dir_var.get())
        save_dir.mkdir(parents=True, exist_ok=True)

        download_type = self.download_type.get()
        resolution = self.resolution_var.get()
        audio_format = self.audio_format_var.get()
        max_retries = int(self.retry_var.get())
        total = len(urls)
        completed = 0

        def update_ui():
            self.progress['value'] = (completed / total) * 100
            self.progress_label.config(text=f"进度: {completed}/{total}")

        for i, url in enumerate(urls):
            if self.is_cancelled:
                break

            while self.is_paused:
                time.sleep(0.5)
                if self.is_cancelled:
                    break
            if self.is_cancelled:
                break

            success = False
            for attempt in range(max_retries):
                try:
                    self.log(f"[{i+1}/{total}] 正在处理: {url}")

                    # === 关键：清理 URL，只保留 v=ID ===
                    parsed = urlparse(url)
                    query = parse_qs(parsed.query)
                    if 'v' not in query:
                        raise ValueError("无效的 YouTube 链接：缺少视频 ID")
                    clean_url = f"https://www.youtube.com/watch?v={query['v'][0]}"
                    self.log(f"→ 清理后 URL: {clean_url}")

                    yt = YouTube(clean_url)

                    if download_type == "video":
                        stream = yt.streams.filter(progressive=True, file_extension='mp4', res=resolution).first()
                        if not stream:
                            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
                        if not stream:
                            raise Exception("未找到匹配的视频流")
                        filename = stream.default_filename
                        stream.download(output_path=save_dir)
                        self.log(f"✅ 视频下载完成: {filename}")
                        success = True
                        break

                    else:  # audio
                        stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
                        if not stream:
                            raise Exception("未找到音频流")

                        temp_file = stream.download(output_path=save_dir)
                        self.log(f"→ 原始音频已下载: {os.path.basename(temp_file)}")

                        base_name = os.path.splitext(os.path.basename(temp_file))[0]
                        final_file = save_dir / f"{base_name}.{audio_format}"

                        # 如果格式相同，直接重命名
                        if temp_file.lower().endswith(f".{audio_format}"):
                            if final_file.exists():
                                final_file.unlink()
                            Path(temp_file).rename(final_file)
                            self.log(f"✅ 音频已保存: {final_file.name}")
                            success = True
                            break
                        else:
                            # 使用 FFmpeg 转码
                            self.convert_with_ffmpeg(temp_file, final_file, audio_format)
                            Path(temp_file).unlink()  # 删除临时文件
                            self.log(f"✅ 音频转码完成: {final_file.name}")
                            success = True
                            break

                except Exception as e:
                    self.log(f"⚠️ 第 {attempt+1} 次尝试失败: {str(e)}")
                    time.sleep(2)
                    if attempt == max_retries - 1:
                        self.log(f"❌ 最终失败: {url}")

            completed += 1
            self.root.after(0, update_ui)

        # 完成后恢复按钮
        def finish_ui():
            self.start_btn.config(state=NORMAL)
            self.pause_btn.config(state=DISABLED)
            self.cancel_btn.config(state=DISABLED)
            self.progress_label.config(text="✅ 下载完成！" if not self.is_cancelled else "🛑 已取消")
        self.root.after(0, finish_ui)

    def on_closing(self):
        self.is_cancelled = True
        if self.current_thread and self.current_thread.is_alive():
            self.log("正在等待任务结束...")
            time.sleep(1)
        self.root.destroy()


if __name__ == "__main__":
    root = Tk()
    app = YouTubeDownloaderGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
