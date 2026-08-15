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
import subprocess
import ctypes
import struct

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

# ──────────── 公共日志模块（可选依赖）────────────
import sys
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
# ────────────────────────────────────────────────

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
    "cookie_path": "",   # 新增cookie路径配置
    "auto_extract_chrome_cookies": False  # 自动从Chrome提取Cookie
}

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
        """使用 subprocess 调用 yt-dlp CLI 进行下载（CLI 能正确处理 JS 运行时）"""
        opts = self.options
        cmd = [sys.executable, '-m', 'yt_dlp']

        # 格式
        fmt = opts.get('format', 'bestvideo+bestaudio/best')
        cmd.extend(['-f', fmt])

        # 输出模板
        if opts.get('outtmpl'):
            cmd.extend(['-o', opts['outtmpl']])

        # Cookie
        if opts.get('cookiesfrombrowser'):
            cmd.extend(['--cookies-from-browser', 'chrome'])
        elif opts.get('cookiefile'):
            cmd.extend(['--cookies', opts['cookiefile']])

        # FFmpeg 路径
        if opts.get('ffmpeg_location'):
            cmd.extend(['--ffmpeg-location', opts['ffmpeg_location']])

        # JS 运行时（YouTube 签名解密需要）
        js_runtime = opts.get('js_runtime', '')
        if js_runtime:
            cmd.extend(['--js-runtimes', js_runtime])
        else:
            # 自动检测：优先 deno，其次 node
            if shutil.which('deno'):
                pass  # deno 是 yt-dlp 默认运行时，无需额外参数
            elif shutil.which('node'):
                cmd.extend(['--js-runtimes', 'node'])
                logger.info('未找到 deno，使用 Node.js 作为 JS 运行时')
            else:
                logger.warning('未找到 deno 或 node，YouTube 下载可能失败！建议安装 deno')

        # 其他选项
        if opts.get('noplaylist'):
            cmd.append('--no-playlist')
        if opts.get('extractaudio'):
            cmd.append('--extract-audio')
            if opts.get('audioformat'):
                cmd.extend(['--audio-format', opts['audioformat']])
            if opts.get('audioquality'):
                cmd.extend(['--audio-quality', opts['audioquality']])

        cmd.append(self.url)

        logger.info(f"执行命令: {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                logger.info(f"[yt-dlp] {line}")
                # 解析进度
                if '[download]' in line and '%' in line:
                    try:
                        pct_str = line.split('%')[0].split()[-1]
                        self.progress = float(pct_str) / 100.0
                        if progress_callback:
                            progress_callback(self.url, self.progress, {'status': 'downloading'})
                    except (ValueError, IndexError):
                        pass

            proc.wait()
            if proc.returncode == 0:
                self.status = 'success'
                logger.info(f"下载成功：{self.url}")
            else:
                self.status = 'failed'
                raise RuntimeError(f"yt-dlp 退出码: {proc.returncode}")
        except FileNotFoundError:
            raise RuntimeError("yt-dlp 未安装，请先运行: pip install yt-dlp")

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

        # 左右均分：使用 PanedWindow
        paned = ttk.PanedWindow(frm, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左侧：输入与设置
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        # URLs 文本框
        ttk.Label(left, text="视频 URL (每行一个):").pack(anchor=tk.W)
        self.txt_urls = tk.Text(left, height=8)
        self.txt_urls.pack(fill=tk.X)
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
        self.cookie_check_frame = ttk.Frame(settings)
        self.cookie_check_frame.pack(fill=tk.X, pady=2)
        self.var_auto_chrome_cookie = tk.BooleanVar(value=self.cfg.get('auto_extract_chrome_cookies', False))
        ttk.Checkbutton(self.cookie_check_frame, text="自动从Chrome提取Cookie", variable=self.var_auto_chrome_cookie).pack(side=tk.LEFT)
        # Cookie文件路径行（当未勾选自动提取时显示）
        self.cookie_path_frame = ttk.Frame(settings)
        self.cookie_path_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.cookie_path_frame, text="Cookie 文件路径:").pack(side=tk.LEFT)
        self.var_cookie = tk.StringVar(value=self.cfg.get('cookie_path', ''))
        ttk.Entry(self.cookie_path_frame, textvariable=self.var_cookie, width=30).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.cookie_path_frame, text="浏览", command=self._browse_cookie).pack(side=tk.LEFT)
        # 根据初始状态控制显示
        if self.var_auto_chrome_cookie.get():
            self.cookie_path_frame.pack_forget()
        self.var_auto_chrome_cookie.trace_add('write', self._toggle_cookie_controls)

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
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        columns = ('url', 'status', 'progress')
        self.tree = ttk.Treeview(right, columns=columns, show='headings')
        self.tree.heading('url', text='URL')
        self.tree.heading('status', text='状态')
        self.tree.heading('progress', text='进度')
        self.tree.column('url', width=400)
        self.tree.column('status', width=100)
        self.tree.column('progress', width=100)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # 底部日志视图（增加高度）
        logframe = ttk.LabelFrame(self.root, text='日志')
        logframe.pack(fill=tk.BOTH, expand=True)
        self.txt_log = tk.Text(logframe, height=14)
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

    # ---------------- 通知（右下角 Toast）----------------
    def _notify(self, title, message, duration=3000):
        """Windows 右下角 Toast 通知"""
        try:
            from ctypes import wintypes
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            # 使用 Windows 10+ Toast 通知（通过 PowerShell）
            import subprocess as _sp
            ps_cmd = (
                f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; '
                f'[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; '
                f'$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); '
                f'$textNodes = $template.GetElementsByTagName("text"); '
                f'$textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) | Out-Null; '
                f'$textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) | Out-Null; '
                f'$toast = [Windows.UI.Notifications.ToastNotification]::new($template); '
                f'$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("YouTube 下载器"); '
                f'$notifier.Show($toast);'
            )
            _sp.Popen(['powershell', '-Command', ps_cmd],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      creationflags=_sp.CREATE_NO_WINDOW)
        except Exception:
            # 降级：用 messagebox
            messagebox.showinfo(title, message)

    # ---------------- UI 行为 ----------------
    def _add_clipboard(self):
        try:
            s = self.root.clipboard_get()
            if s:
                self.txt_urls.insert(tk.END, s + '\n')
                self._notify('剪贴板', '已添加 URL 到列表')
        except Exception:
            self._notify('提示', '剪贴板为空或不可用')

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

    def _toggle_cookie_controls(self, *args):
        """根据是否勾选自动提取Chrome Cookie，切换Cookie文件路径区域的显示/隐藏"""
        if self.var_auto_chrome_cookie.get():
            self.cookie_path_frame.pack_forget()
        else:
            # 重新插入到复选框行之后
            self.cookie_path_frame.pack(fill=tk.X, pady=2, after=self.cookie_check_frame)

    def _load_cfg(self):
        self.cfg = load_config()
        self.var_out.set(self.cfg.get('output_dir'))
        self.var_ffmpeg.set(self.cfg.get('ffmpeg_path', find_ffmpeg()))
        self.var_cookie.set(self.cfg.get('cookie_path', ''))
        self.var_auto_chrome_cookie.set(self.cfg.get('auto_extract_chrome_cookies', False))
        self.var_threads.set(self.cfg.get('threads'))
        self.var_type.set(self.cfg.get('download_type'))
        self.var_afmt.set(self.cfg.get('audio_format'))
        self.var_quality.set(self.cfg.get('quality'))
        self.var_retry.set(self.cfg.get('retry_count'))
        urls = self.cfg.get('urls', [])
        self.txt_urls.delete('1.0', tk.END)
        self.txt_urls.insert('1.0', '\n'.join(urls))
        self._notify('配置加载', f'已从 {CONFIG_PATH.name} 加载配置')

    def _save_cfg(self):
        urls = [line.strip() for line in self.txt_urls.get('1.0', tk.END).splitlines() if line.strip()]
        cfg = {
            'output_dir': self.var_out.get(),
            'ffmpeg_path': self.var_ffmpeg.get(),
            'cookie_path': self.var_cookie.get(),
            'auto_extract_chrome_cookies': self.var_auto_chrome_cookie.get(),
            'threads': int(self.var_threads.get()),
            'download_type': self.var_type.get(),
            'audio_format': self.var_afmt.get(),
            'quality': self.var_quality.get(),
            'retry_count': int(self.var_retry.get()),
            'urls': urls
        }
        save_config(cfg)
        self._notify('配置保存', f'已保存到 {CONFIG_PATH.name}')

    def _start(self):
        urls = [line.strip() for line in self.txt_urls.get('1.0', tk.END).splitlines() if line.strip()]
        if not urls:
            self._notify('警告', '请先输入至少一个 URL')
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
            self._notify('错误', '未找到 FFmpeg，请手动设置路径')
            return

        # Cookie处理：优先使用Chrome自动提取，否则使用Cookie文件
        use_chrome_cookie = self.var_auto_chrome_cookie.get()
        cookie_path = cfg.get('cookie_path', '')
        if not use_chrome_cookie and cookie_path and not os.path.exists(cookie_path):
            self._notify('错误', f'Cookie 文件不存在: {cookie_path}')
            return

        # 清空表格 & 创建任务
        for i in self.tree.get_children():
            self.tree.delete(i)

        tasks = []
        ydl_base_opts = {
            'outtmpl': os.path.join(outdir, '%(title)s - %(id)s.%(ext)s'),
            'noplaylist': True,
            'ffmpeg_location': ffmpeg_path,
        }

        # 自动检测 JS 运行时
        if shutil.which('deno'):
            logger.info('检测到 deno，将使用 deno 作为 JS 运行时')
        elif shutil.which('node'):
            ydl_base_opts['js_runtime'] = 'node'
            logger.info('未找到 deno，将使用 Node.js 作为 JS 运行时')
        else:
            logger.warning('未找到 deno 或 node！YouTube 下载可能失败，建议安装 deno')

        # Cookie处理：优先使用Chrome自动提取，否则使用Cookie文件
        if self.var_auto_chrome_cookie.get():
            ydl_base_opts['cookiesfrombrowser'] = True
            logger.info('将自动从Chrome浏览器提取Cookie')
        elif cfg.get('cookie_path'):
            ydl_base_opts['cookiefile'] = cfg['cookie_path']

        # 根据选择设置格式和音频选项
        if cfg['download_type'] == 'audio':
            ydl_base_opts.update({
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': cfg['audio_format'],
                'audioquality': '192',
            })
        else:
            # video, quality
            q = cfg['quality']
            if q.isdigit():
                ydl_base_opts['format'] = f'bestvideo[height<={q}]+bestaudio/best[height<={q}]'
            elif q == 'best':
                ydl_base_opts['format'] = 'bestvideo+bestaudio/best'
            elif q == 'worst':
                ydl_base_opts['format'] = 'worstvideo+worstaudio/worst'
            else:
                ydl_base_opts['format'] = 'bestvideo+bestaudio/best'

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
                # 统计结果
                success = sum(1 for t in self.manager.tasks if t.status == 'success')
                failed = sum(1 for t in self.manager.tasks if t.status == 'failed')
                self._notify('下载完成', f'成功: {success}, 失败: {failed}', 5000)
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
    root.geometry('1200x750')
    # 启动时最大化
    root.state('zoomed')
    root.mainloop()


if __name__ == '__main__':
    main()
