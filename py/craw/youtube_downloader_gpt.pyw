"""
YouTube 下载器（可视化 .pyw）
功能：
 - 可输入一个或多个视频 URL
 - 保存/加载配置到 JSON（使用绝对路径 CONFIG_PATH）
 - 支持并发线程数可配置
 - 支持选择下载视频或仅音频，音频格式可选
 - 支持选择清晰度（best / worst / 720 / 1080 / etc.）
 - 支持进度显示（在表格里），支持暂停/继续（基于事件的粗粒度暂停）
 - 支持重试次数
 - 记录操作日志（PROCESS_LOG_FILE）
 - 最终生成的脚本可保存为 .pyw 双击运行（无控制台）
 - 支持Cookie文件路径配置

注意：
 - 依赖：yt-dlp, ffmpeg（系统安装），可选 psutil（用于更可靠的进程暂停/继续）
 - 在 Windows 上访问 Android/data 等需要管理员权限（与此脚本无关）

使用方法：
 - 保存为 youtube_downloader_pyw.pyw
 - 确保安装依赖： pip install yt-dlp psutil
 - 双击运行即可（.pyw 会隐藏控制台）

作者：生成脚本（示例）
"""

import os
import sys
import json
import time
import logging
import threading
import queue
from pathlib import Path
from functools import partial
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil

# Try imports
try:
    import yt_dlp
except Exception:
    yt_dlp = None

try:
    import psutil
except Exception:
    psutil = None

# ---------------------- 配置与常量（使用你给定的结构） ----------------------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "youtube_downloader_gpt"  # 脚本名称（按需修改）
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
PROCESS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 默认配置
DEFAULT_CONFIG = {
    "output_dir": str(SCRIPT_DIR / "downloads"),
    "threads": 3,
    "download_type": "video",  # video / audio
    "audio_format": "mp3",
    "quality": "best",
    "retry_count": 3,
    "urls": [],
    "ffmpeg_path": "",  # 新增ffmpeg路径配置
    "cookie_path": ""   # 新增cookie路径配置
}

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ytdl_gui")

# ---------------------- 工具函数 ----------------------

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            # 保证字段完整
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception as e:
            logger.exception("加载配置失败，使用默认配置")
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        logger.info(f"配置保存到 {CONFIG_PATH}")
    except Exception as e:
        logger.exception("保存配置失败")


# safe path create
def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)

def find_ffmpeg():
    """查找ffmpeg路径"""
    # 首先尝试从系统PATH中查找
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path

    # 如果在PATH中找不到，返回空字符串
    return ""

# ---------------------- 下载管理 ----------------------
class DownloadTask:
    def __init__(self, url, options, retries=3):
        self.url = url
        self.options = options
        self.retries = retries
        self.attempt = 0
        self.status = 'pending'  # pending, running, paused, success, failed
        self.progress = 0.0
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._ydl = None
        self._info = None

    def run(self, progress_callback=None):
        self.attempt = 0
        while self.attempt <= self.retries and not self._stop_event.is_set():
            try:
                self.attempt += 1
                self.status = 'running'
                logger.info(f"开始下载：{self.url} (尝试 {self.attempt})")
                self._download(progress_callback)
                if self.status == 'success':
                    return True
            except Exception as e:
                logger.exception(f"下载错误：{self.url}")
                self.status = 'failed'
                if self.attempt <= self.retries:
                    logger.info(f"重试 {self.attempt}/{self.retries} - {self.url}")
                    time.sleep(1)
                else:
                    break
        return False

    def _download(self, progress_callback=None):
        if yt_dlp is None:
            raise RuntimeError("yt-dlp 未安装，请先运行: pip install yt-dlp")

        ydl_opts = self.options.copy()
        # 添加 progress hook
        def progress_hook(d):
            # d 包含 status, downloaded_bytes, total_bytes, tmpfilename 等
            if d.get('status') == 'downloading':
                if d.get('total_bytes'):
                    self.progress = d.get('downloaded_bytes', 0) / max(1, d.get('total_bytes', 1))
                else:
                    # 估算
                    self.progress = 0.0
                if progress_callback:
                    progress_callback(self.url, self.progress, d)
            elif d.get('status') == 'finished':
                self.progress = 1.0
                if progress_callback:
                    progress_callback(self.url, self.progress, d)
                logger.info(f"下载完成(未转码)：{self.url}")
            # 检查暂停事件；在 hook 内做粗粒度暂停
            while self._pause_event.is_set() and not self._stop_event.is_set():
                self.status = 'paused'
                time.sleep(0.2)
            if self._stop_event.is_set():
                raise yt_dlp.utils.DownloadError('stopped by user')

        ydl_opts.setdefault('progress_hooks', []).append(progress_hook)
        # 强制使用 ffmpeg 进行合并/转码（若需要）
        ydl_opts.setdefault('format', ydl_opts.get('format', 'best'))

        # 开始下载
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            self._ydl = ydl
            info = ydl.extract_info(self.url, download=True)
            self._info = info
            # 如果选择 audio 且需要转换格式，yt-dlp 已在 postprocessors 处理中
            self.status = 'success'
            logger.info(f"下载成功：{self.url}")

    def pause(self):
        logger.info(f"请求暂停：{self.url}")
        self._pause_event.set()

    def resume(self):
        logger.info(f"请求继续：{self.url}")
        self._pause_event.clear()

    def stop(self):
        logger.info(f"请求停止：{self.url}")
        self._stop_event.set()
        # 如果有正在运行的 ydl，尝试使用 psutil 杀进程或抛异常
        if self._ydl and psutil:
            # 找到子进程并终止（最佳努力）
            try:
                proc = psutil.Process()
                # 这里没有直接引用下载子进程 ID，跳过
            except Exception:
                pass


class DownloadManager:
    def __init__(self, max_workers=3):
        self.max_workers = max_workers
        self.tasks = []  # list of DownloadTask
        self.queue = queue.Queue()
        self._threads = []
        self._running = False

    def add_task(self, task: DownloadTask):
        self.tasks.append(task)
        self.queue.put(task)

    def start(self, progress_callback=None):
        self._running = True
        for _ in range(self.max_workers):
            t = threading.Thread(target=self._worker, args=(progress_callback,), daemon=True)
            self._threads.append(t)
            t.start()

    def _worker(self, progress_callback):
        while self._running:
            try:
                task: DownloadTask = self.queue.get(timeout=1)
            except queue.Empty:
                # 队列空，检查是否退出
                if all(t.status in ('success', 'failed') for t in self.tasks):
                    break
                continue
            if task:
                task.run(progress_callback=progress_callback)
            self.queue.task_done()

    def pause_all(self):
        for t in self.tasks:
            t.pause()

    def resume_all(self):
        for t in self.tasks:
            t.resume()

    def stop_all(self):
        self._running = False
        while not self.queue.empty():
            try:
                tq = self.queue.get_nowait()
                tq.stop()
                self.queue.task_done()
            except Exception:
                break
        for t in self.tasks:
            t.stop()

# ---------------------- GUI ----------------------
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube 下载器")
        self.cfg = load_config()

        # manager
        self.manager = None

        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        # 左侧：输入与设置
        left = ttk.Frame(frm)
        left.pack(side=tk.LEFT, fill=tk.Y)

        # URLs 文本框
        ttk.Label(left, text="视频 URL (每行一个):").pack(anchor=tk.W)
        self.txt_urls = tk.Text(left, width=50, height=10)
        self.txt_urls.pack()
        # 加载已有 urls
        if self.cfg.get('urls'):
            self.txt_urls.insert('1.0', '\n'.join(self.cfg.get('urls', [])))

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill=tk.X, pady=6)
        ttk.Button(btn_frame, text="从剪贴板添加", command=self._add_clipboard).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="清空", command=lambda: self.txt_urls.delete('1.0', tk.END)).pack(side=tk.LEFT)

        # 设置区
        settings = ttk.LabelFrame(left, text="设置")
        settings.pack(fill=tk.X, pady=6)

        # Output dir
        outfrm = ttk.Frame(settings)
        outfrm.pack(fill=tk.X, pady=2)
        ttk.Label(outfrm, text="输出目录:").pack(side=tk.LEFT)
        self.var_out = tk.StringVar(value=self.cfg.get('output_dir'))
        ttk.Entry(outfrm, textvariable=self.var_out, width=30).pack(side=tk.LEFT, padx=4)
        ttk.Button(outfrm, text="浏览", command=self._browse_out).pack(side=tk.LEFT)

        # FFmpeg 路径
        ffmpegfrm = ttk.Frame(settings)
        ffmpegfrm.pack(fill=tk.X, pady=2)
        ttk.Label(ffmpegfrm, text="FFmpeg 路径:").pack(side=tk.LEFT)
        self.var_ffmpeg = tk.StringVar(value=self.cfg.get('ffmpeg_path', find_ffmpeg()))
        ttk.Entry(ffmpegfrm, textvariable=self.var_ffmpeg, width=30).pack(side=tk.LEFT, padx=4)
        ttk.Button(ffmpegfrm, text="浏览", command=self._browse_ffmpeg).pack(side=tk.LEFT)

        # Cookie 路径
        cookiefrm = ttk.Frame(settings)
        cookiefrm.pack(fill=tk.X, pady=2)
        ttk.Label(cookiefrm, text="Cookie 文件路径:").pack(side=tk.LEFT)
        self.var_cookie = tk.StringVar(value=self.cfg.get('cookie_path', ''))
        ttk.Entry(cookiefrm, textvariable=self.var_cookie, width=30).pack(side=tk.LEFT, padx=4)
        ttk.Button(cookiefrm, text="浏览", command=self._browse_cookie).pack(side=tk.LEFT)

        # Threads
        thfrm = ttk.Frame(settings)
        thfrm.pack(fill=tk.X, pady=2)
        ttk.Label(thfrm, text="线程数:").pack(side=tk.LEFT)
        self.var_threads = tk.IntVar(value=self.cfg.get('threads', 3))
        ttk.Spinbox(thfrm, from_=1, to=10, textvariable=self.var_threads, width=5).pack(side=tk.LEFT)

        # Download type
        dtfrm = ttk.Frame(settings)
        dtfrm.pack(fill=tk.X, pady=2)
        self.var_type = tk.StringVar(value=self.cfg.get('download_type', 'video'))
        ttk.Radiobutton(dtfrm, text='视频', variable=self.var_type, value='video').pack(side=tk.LEFT)
        ttk.Radiobutton(dtfrm, text='音频', variable=self.var_type, value='audio').pack(side=tk.LEFT)

        # Audio format & quality
        afrm = ttk.Frame(settings)
        afrm.pack(fill=tk.X, pady=2)
        ttk.Label(afrm, text='音频格式:').pack(side=tk.LEFT)
        self.var_afmt = tk.StringVar(value=self.cfg.get('audio_format', 'mp3'))
        ttk.Combobox(afrm, textvariable=self.var_afmt, values=['mp3','wav','flac','m4a'], width=6).pack(side=tk.LEFT)

        ttk.Label(afrm, text='  清晰度:').pack(side=tk.LEFT, padx=6)
        self.var_quality = tk.StringVar(value=self.cfg.get('quality', 'best'))
        ttk.Combobox(afrm, textvariable=self.var_quality, values=['best','worst','1080','720','480','360'], width=6).pack(side=tk.LEFT)

        # Retry
        rfrm = ttk.Frame(settings)
        rfrm.pack(fill=tk.X, pady=2)
        ttk.Label(rfrm, text='重试次数:').pack(side=tk.LEFT)
        self.var_retry = tk.IntVar(value=self.cfg.get('retry_count', 3))
        ttk.Spinbox(rfrm, from_=0, to=10, textvariable=self.var_retry, width=5).pack(side=tk.LEFT)

        # Config Buttons
        cfgfrm = ttk.Frame(left)
        cfgfrm.pack(fill=tk.X, pady=6)
        ttk.Button(cfgfrm, text='加载配置', command=self._load_cfg).pack(side=tk.LEFT)
        ttk.Button(cfgfrm, text='保存配置', command=self._save_cfg).pack(side=tk.LEFT)

        # 操作按钮
        opfrm = ttk.Frame(left)
        opfrm.pack(fill=tk.X, pady=6)
        ttk.Button(opfrm, text='开始', command=self._start).pack(side=tk.LEFT)
        self.btn_pause = ttk.Button(opfrm, text='暂停', command=self._pause_all, state=tk.DISABLED)
        self.btn_pause.pack(side=tk.LEFT, padx=4)
        self.btn_resume = ttk.Button(opfrm, text='继续', command=self._resume_all, state=tk.DISABLED)
        self.btn_resume.pack(side=tk.LEFT)
        ttk.Button(opfrm, text='停止', command=self._stop_all).pack(side=tk.LEFT, padx=4)

        # 右侧：任务表格
        right = ttk.Frame(frm)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        columns = ('url', 'status', 'progress')
        self.tree = ttk.Treeview(right, columns=columns, show='headings')
        self.tree.heading('url', text='URL')
        self.tree.heading('status', text='状态')
        self.tree.heading('progress', text='进度')
        self.tree.column('url', width=400)
        self.tree.column('status', width=100)
        self.tree.column('progress', width=100)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # 底部日志视图
        logframe = ttk.LabelFrame(self.root, text='日志')
        logframe.pack(fill=tk.BOTH)
        self.txt_log = tk.Text(logframe, height=8)
        self.txt_log.pack(fill=tk.BOTH)

        # 将 logger 输出也写到 GUI
        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget

            def emit(self, record):
                msg = self.format(record) + '\n'
                try:
                    self.text_widget.insert(tk.END, msg)
                    self.text_widget.see(tk.END)
                except Exception:
                    pass

        th = TextHandler(self.txt_log)
        th.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(th)

    # ---------------- UI 行为 ----------------
    def _add_clipboard(self):
        try:
            s = self.root.clipboard_get()
            if s:
                self.txt_urls.insert(tk.END, s + '\n')
        except Exception:
            messagebox.showinfo('信息', '剪贴板为空或不可用')

    def _browse_out(self):
        d = filedialog.askdirectory(initialdir=self.var_out.get() or str(SCRIPT_DIR))
        if d:
            self.var_out.set(d)

    def _browse_ffmpeg(self):
        """手动选择FFmpeg路径"""
        d = filedialog.askopenfilename(
            title="选择FFmpeg可执行文件",
            filetypes=[("可执行文件", "ffmpeg.exe;ffmpeg"), ("所有文件", "*.*")]
        )
        if d:
            self.var_ffmpeg.set(d)

    def _browse_cookie(self):
        """手动选择Cookie文件路径"""
        d = filedialog.askopenfilename(
            title="选择Cookie文件",
            filetypes=[("Cookie文件", "*.txt"), ("所有文件", "*.*")]
        )
        if d:
            self.var_cookie.set(d)

    def _load_cfg(self):
        self.cfg = load_config()
        self.var_out.set(self.cfg.get('output_dir'))
        self.var_ffmpeg.set(self.cfg.get('ffmpeg_path', find_ffmpeg()))
        self.var_cookie.set(self.cfg.get('cookie_path', ''))
        self.var_threads.set(self.cfg.get('threads'))
        self.var_type.set(self.cfg.get('download_type'))
        self.var_afmt.set(self.cfg.get('audio_format'))
        self.var_quality.set(self.cfg.get('quality'))
        self.var_retry.set(self.cfg.get('retry_count'))
        urls = self.cfg.get('urls', [])
        self.txt_urls.delete('1.0', tk.END)
        self.txt_urls.insert('1.0', '\n'.join(urls))
        messagebox.showinfo('已加载', f'配置已从 {CONFIG_PATH} 加载')

    def _save_cfg(self):
        urls = [line.strip() for line in self.txt_urls.get('1.0', tk.END).splitlines() if line.strip()]
        cfg = {
            'output_dir': self.var_out.get(),
            'ffmpeg_path': self.var_ffmpeg.get(),
            'cookie_path': self.var_cookie.get(),
            'threads': int(self.var_threads.get()),
            'download_type': self.var_type.get(),
            'audio_format': self.var_afmt.get(),
            'quality': self.var_quality.get(),
            'retry_count': int(self.var_retry.get()),
            'urls': urls
        }
        save_config(cfg)
        messagebox.showinfo('已保存', f'配置已保存到 {CONFIG_PATH}')

    def _start(self):
        urls = [line.strip() for line in self.txt_urls.get('1.0', tk.END).splitlines() if line.strip()]
        if not urls:
            messagebox.showwarning('警告', '请先输入至少一个 URL')
            return
        outdir = self.var_out.get()
        ensure_dir(outdir)

        # 保存当前配置
        cfg = {
            'output_dir': outdir,
            'ffmpeg_path': self.var_ffmpeg.get(),
            'cookie_path': self.var_cookie.get(),
            'threads': int(self.var_threads.get()),
            'download_type': self.var_type.get(),
            'audio_format': self.var_afmt.get(),
            'quality': self.var_quality.get(),
            'retry_count': int(self.var_retry.get()),
            'urls': urls
        }
        save_config(cfg)

        # 检查FFmpeg路径
        ffmpeg_path = cfg['ffmpeg_path'] or find_ffmpeg()
        if not ffmpeg_path:
            messagebox.showerror('错误', '未找到FFmpeg，请手动设置路径')
            return

        # 检查Cookie文件是否存在（如果设置了）
        if cfg['cookie_path'] and not os.path.exists(cfg['cookie_path']):
            messagebox.showerror('错误', f'Cookie文件不存在: {cfg["cookie_path"]}')
            return

        # 清空表格 & 创建任务
        for i in self.tree.get_children():
            self.tree.delete(i)

        tasks = []
        ydl_base_opts = {
            'outtmpl': os.path.join(outdir, '%(title)s - %(id)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 3,
            # 设置ffmpeg路径
            'ffmpeg_location': ffmpeg_path,
            # progress hook will be appended in DownloadTask
        }

        # 如果设置了Cookie文件，则添加到选项中
        if cfg['cookie_path']:
            ydl_base_opts['cookiefile'] = cfg['cookie_path']

        # 根据选择设置 postprocessors
        if cfg['download_type'] == 'audio':
            ydl_base_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': cfg['audio_format'],
                    'preferredquality': '192'
                }]
            })
        else:
            # video, quality
            q = cfg['quality']
            if q.isdigit():
                ydl_base_opts['format'] = f'bestvideo[height<={q}]+bestaudio/best[height<={q}]'
            elif q == 'best':
                ydl_base_opts['format'] = 'best'
            elif q == 'worst':
                ydl_base_opts['format'] = 'worst'
            else:
                ydl_base_opts['format'] = 'best'

        for u in urls:
            task = DownloadTask(u, ydl_base_opts, retries=cfg['retry_count'])
            tasks.append(task)
            self.tree.insert('', tk.END, iid=u, values=(u, task.status, f"{int(task.progress*100)}%"))

        # 创建 manager
        self.manager = DownloadManager(max_workers=cfg['threads'])
        for t in tasks:
            self.manager.add_task(t)

        # 按钮状态
        self.btn_pause.config(state=tk.NORMAL)
        self.btn_resume.config(state=tk.DISABLED)

        # 启动
        self.manager.start(progress_callback=self._on_progress)

        # 启动 UI 更新线程
        self._ui_updater = threading.Thread(target=self._update_loop, daemon=True)
        self._ui_updater.start()

    def _on_progress(self, url, progress, d):
        # 该回调来自下载线程；为了线程安全，使用 after 将更新放到主线程
        self.root.after(0, partial(self._update_row, url, progress, d))

    def _update_row(self, url, progress, d):
        pct = f"{int(progress*100)}%"
        status = d.get('status', '')
        if status == 'finished':
            status = '完成'
            pct = '100%'
        self.tree.set(url, 'status', status)
        self.tree.set(url, 'progress', pct)

    def _update_loop(self):
        # 定期检查任务状态，更新表格
        while True:
            if not self.manager:
                break
            all_done = True
            for t in self.manager.tasks:
                iid = t.url
                cur = self.tree.exists(iid)
                if cur:
                    self.tree.set(iid, 'status', t.status)
                    self.tree.set(iid, 'progress', f"{int(t.progress*100)}%")
                if t.status not in ('success', 'failed'):
                    all_done = False
            if all_done:
                logger.info('所有任务完成')
                self.btn_pause.config(state=tk.DISABLED)
                self.btn_resume.config(state=tk.DISABLED)
                break
            time.sleep(0.8)

    def _pause_all(self):
        if self.manager:
            self.manager.pause_all()
            self.btn_pause.config(state=tk.DISABLED)
            self.btn_resume.config(state=tk.NORMAL)

    def _resume_all(self):
        if self.manager:
            self.manager.resume_all()
            self.btn_pause.config(state=tk.NORMAL)
            self.btn_resume.config(state=tk.DISABLED)

    def _stop_all(self):
        if self.manager:
            self.manager.stop_all()
            self.btn_pause.config(state=tk.DISABLED)
            self.btn_resume.config(state=tk.DISABLED)


# ---------------------- Main ----------------------

def main():
    # 检查依赖
    miss = []
    if yt_dlp is None:
        miss.append('yt-dlp')
    if not find_ffmpeg():
        miss.append('ffmpeg (system)')
    if miss:
        logger.warning('缺少依赖: ' + ', '.join(miss) + '. 请先安装（pip install yt-dlp; 安装 ffmpeg 到 PATH）')

    root = tk.Tk()
    app = App(root)
    root.geometry('1000x600')
    root.mainloop()


if __name__ == '__main__':
    main()
