import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image
import os
import sys
import json
import queue
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ──────────── 公共日志模块（可选依赖）────────────
_PY_DIR = str(Path(__file__).resolve().parent.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger()
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

# 增强库状态（None=加载中，True=已加载，False=不可用）
HAS_REALESRGAN = None
HAS_GFPGAN = None

# 延迟导入的库模块引用
_RealESRGANer = None
_RRDBNet = None
_GFPGANer = None

# 配置文件路径
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config_image_enhancer.json"

# 模型权重目录和下载地址
# 优先级：配置文件指定 > D:/.models/ > ~/AppData/Local/ > 脚本目录（旧兼容）
def _resolve_weights_dir():
    """解析模型权重目录：优先非系统盘，重装系统不丢失"""
    # 1. 检查配置文件中的自定义路径
    cfg = CONFIG_DIR / "config_image_enhancer.json"
    if cfg.exists():
        try:
            with open(cfg, 'r', encoding='utf-8') as f:
                custom = json.load(f).get('weights_dir', '')
            if custom and os.path.isdir(custom):
                return Path(custom)
        except Exception:
            pass
    # 2. 优先使用非系统盘（重装系统不丢）
    if os.path.isdir('D:\\'):
        return Path('D:/.models/image_enhancer')
    # 3. 回退到用户目录
    return Path.home() / '.image_enhancer' / 'weights'

WEIGHTS_DIR = _resolve_weights_dir()
MODEL_URLS = {
    'RealESRGAN_x4plus.pth': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
    'GFPGANv1.4.pth': 'https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth',
}


class ImageEnhancerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🔍 图片放大增强工具 - 人物照片优化")
        self.root.geometry("950x750")
        self.root.resizable(True, True)

        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))
        self.style.configure("TCheckbutton", font=("SimHei", 9))

        # 初始化变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.weights_dir = tk.StringVar(value=str(WEIGHTS_DIR))
        self.upscale_factor = tk.IntVar(value=2)
        self.face_enhance = tk.BooleanVar(value=True)
        self.thread_count = tk.IntVar(value=1)
        self._stop_event = threading.Event()
        self.is_processing = False
        self.log_queue = queue.Queue()

        # 模型实例（延迟初始化）
        self.upsampler = None
        self.face_enhancer = None

        # 创建UI组件
        self.create_widgets()

        # 加载配置
        self.load_config()

        # 启动日志队列轮询
        self._poll_log_queue()

        # 后台加载增强库（不阻塞 UI）
        threading.Thread(target=self._load_enhance_libs, daemon=True).start()

        logger.info("图片放大增强工具启动")

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(main_frame, text="图片放大增强工具 - 人物照片优化", 
                               font=("SimHei", 16, "bold"))
        title_label.pack(pady=(0, 15))

        # 输入目录选择
        input_frame = ttk.LabelFrame(main_frame, text="输入设置", padding="10")
        input_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(input_frame, text="图片目录:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Entry(input_frame, textvariable=self.input_dir, width=60).grid(row=0, column=1, padx=5)
        ttk.Button(input_frame, text="选择目录", command=self.select_input_dir).grid(row=0, column=2, padx=5)

        # 输出目录选择
        ttk.Label(input_frame, text="导出目录:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        ttk.Entry(input_frame, textvariable=self.output_dir, width=60).grid(row=1, column=1, padx=5, pady=(10, 0))
        ttk.Button(input_frame, text="选择目录", command=self.select_output_dir).grid(row=1, column=2, padx=5, pady=(10, 0))

        # 模型目录选择
        ttk.Label(input_frame, text="模型目录:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        ttk.Entry(input_frame, textvariable=self.weights_dir, width=60).grid(row=2, column=1, padx=5, pady=(10, 0))
        ttk.Button(input_frame, text="选择目录", command=self.select_weights_dir).grid(row=2, column=2, padx=5, pady=(10, 0))

        # 增强参数设置
        param_frame = ttk.LabelFrame(main_frame, text="增强参数", padding="10")
        param_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(param_frame, text="放大倍数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        factor_combo = ttk.Combobox(
            param_frame,
            textvariable=self.upscale_factor,
            values=[2, 3, 4],
            state="readonly",
            width=8
        )
        factor_combo.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(param_frame, text="线程数:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        thread_spin = ttk.Spinbox(
            param_frame,
            from_=1,
            to=4,
            textvariable=self.thread_count,
            width=5
        )
        thread_spin.grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Checkbutton(
            param_frame,
            text="启用人脸增强（GFPGAN，针对人物照片优化）",
            variable=self.face_enhance
        ).grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(10, 0))

        # 库状态提示（初始显示加载中）
        self.lib_status_label = ttk.Label(
            param_frame, text="⏳ 正在加载增强库...", foreground="gray", font=("SimHei", 8)
        )
        self.lib_status_label.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(5, 0))

        # 技术说明
        tech_desc = "技术方案: Real-ESRGAN（通用超分辨率）+ GFPGAN（人脸专用增强）"
        ttk.Label(param_frame, text=tech_desc, foreground="gray", font=("SimHei", 8)).grid(
            row=3, column=0, columnspan=4, sticky=tk.W, pady=(2, 0)
        )

        # 控制按钮
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="开始增强", command=self.start_processing)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_processing, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="清空日志", command=self.clear_log).pack(side=tk.LEFT, padx=5)

        # 进度条
        progress_frame = ttk.Frame(main_frame, padding="5")
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress.pack(fill=tk.X, expand=True)

        self.progress_label = ttk.Label(progress_frame, text="就绪")
        self.progress_label.pack(fill=tk.X, pady=(5, 0))

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="处理日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=15, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def select_input_dir(self):
        directory = filedialog.askdirectory(title="选择图片所在目录")
        if directory:
            self.input_dir.set(directory)
            logger.info(f"选择输入目录: {directory}")

    def select_output_dir(self):
        directory = filedialog.askdirectory(title="选择导出目录")
        if directory:
            self.output_dir.set(directory)
            logger.info(f"选择输出目录: {directory}")

    def select_weights_dir(self):
        directory = filedialog.askdirectory(title="选择模型文件存放目录")
        if directory:
            self.weights_dir.set(directory)
            logger.info(f"选择模型目录: {directory}")

    def load_config(self):
        """加载配置文件"""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.input_dir.set(config.get('input_dir', ''))
                    self.output_dir.set(config.get('output_dir', ''))
                    wdir = config.get('weights_dir', '')
                    if wdir and os.path.isdir(wdir):
                        self.weights_dir.set(wdir)
                    self.upscale_factor.set(config.get('upscale_factor', 2))
                    self.face_enhance.set(config.get('face_enhance', True))
                    self.thread_count.set(config.get('thread_count', 1))
                logger.info("配置加载成功")
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")

    def save_config(self):
        """保存配置文件"""
        try:
            config = {
                'input_dir': self.input_dir.get(),
                'output_dir': self.output_dir.get(),
                'weights_dir': self.weights_dir.get(),
                'upscale_factor': self.upscale_factor.get(),
                'face_enhance': self.face_enhance.get(),
                'thread_count': self.thread_count.get()
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def _poll_log_queue(self):
        """轮询日志队列，在主线程中更新UI"""
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, message + '\n')
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def log(self, message):
        """添加日志消息到队列"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def _show_toast(self, title, message, level="info", duration_ms=3500):
        """右下角 Toast 通知，duration_ms 毫秒后自动消失"""
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

    def clear_log(self):
        """清空日志显示"""
        self.log_text.delete(1.0, tk.END)

    def _load_enhance_libs(self):
        """后台加载增强库，不阻塞 UI"""
        global HAS_REALESRGAN, HAS_GFPGAN, _RealESRGANer, _RRDBNet, _GFPGANer

        # 加载 Real-ESRGAN
        try:
            from realesrgan import RealESRGANer
            from basicsr.archs.rrdbnet_arch import RRDBNet
            _RealESRGANer = RealESRGANer
            _RRDBNet = RRDBNet
            HAS_REALESRGAN = True
            logger.info("Real-ESRGAN 库加载完成")
        except ImportError:
            HAS_REALESRGAN = False
            logger.warning("Real-ESRGAN 库未安装")

        # 加载 GFPGAN
        try:
            from gfpgan import GFPGANer
            _GFPGANer = GFPGANer
            HAS_GFPGAN = True
            logger.info("GFPGAN 库加载完成")
        except ImportError:
            HAS_GFPGAN = False
            logger.warning("GFPGAN 库未安装")

        # 更新 UI 状态
        self.root.after(0, self._update_lib_status)

    def _update_lib_status(self):
        """更新界面库状态显示"""
        self.lib_status_label.config(foreground="gray", text="⏳ 正在加载增强库...")
        
        lib_status = []
        if HAS_REALESRGAN:
            lib_status.append("✅ Real-ESRGAN")
        if HAS_GFPGAN:
            lib_status.append("✅ GFPGAN")

        if lib_status:
            self.lib_status_label.config(
                text="可用增强库: " + " | ".join(lib_status),
                foreground="green"
            )
        elif HAS_REALESRGAN is False and HAS_GFPGAN is False:
            self.lib_status_label.config(
                text="⚠️ 未安装增强库（pip install realesrgan gfpgan basicsr facexlib）",
                foreground="red"
            )
        else:
            self.lib_status_label.config(text="⏳ 正在加载增强库...", foreground="gray")

    def _download_model(self, filename, url):
        """下载模型文件（带进度显示）"""
        import urllib.request
        # 使用用户在界面选择的目录（运行时解析）
        weights_dir = Path(self.weights_dir.get())
        weights_dir.mkdir(parents=True, exist_ok=True)
        dest = weights_dir / filename
        if dest.exists():
            return str(dest)
        
        self.log(f"正在下载模型 {filename}（首次使用需下载，请耐心等待）...")
        logger.info(f"下载模型: {url}")
        
        def reporthook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100, downloaded * 100 // total_size)
                mb_done = downloaded / 1024 / 1024
                mb_total = total_size / 1024 / 1024
                # 每 10% 更新一次日志
                if pct % 10 == 0:
                    logger.debug(f"下载进度: {pct}% ({mb_done:.1f}/{mb_total:.1f} MB)")
        
        try:
            urllib.request.urlretrieve(url, str(dest), reporthook)
            self.log(f"✅ 模型 {filename} 下载完成")
            return str(dest)
        except Exception as e:
            # 下载失败时删除不完整的文件
            if dest.exists():
                dest.unlink()
            raise RuntimeError(f"模型下载失败: {e}\n请手动下载: {url}\n保存到: {dest}")

    def init_models(self):
        """初始化超分辨率模型"""
        try:
            if not HAS_REALESRGAN:
                raise RuntimeError("未安装 Real-ESRGAN，请执行: pip install realesrgan basicsr facexlib")

            self.log("正在加载 Real-ESRGAN 模型...")
            logger.info("初始化 Real-ESRGAN 模型")

            # 下载/获取模型权重
            realesrgan_weight = self._download_model(
                'RealESRGAN_x4plus.pth',
                MODEL_URLS['RealESRGAN_x4plus.pth']
            )

            # 初始化 Real-ESRGAN
            model = _RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32)
            self.upsampler = _RealESRGANer(
                scale=4,  # 模型默认 4x
                model_path=str(realesrgan_weight),
                model=model,
                tile=256,  # 分块处理，降低内存占用（CPU 模式必须开启）
                tile_pad=10,
                pre_pad=0,
                half=False  # True 使用半精度（需要 GPU 支持）
            )

            self.log("✅ Real-ESRGAN 模型加载完成")

            # 如果启用人脸增强
            if self.face_enhance.get() and HAS_GFPGAN:
                self.log("正在加载 GFPGAN 人脸增强模型...")
                logger.info("初始化 GFPGAN 模型")

                gfpgan_weight = self._download_model(
                    'GFPGANv1.4.pth',
                    MODEL_URLS['GFPGANv1.4.pth']
                )

                self.face_enhancer = _GFPGANer(
                    model_path=str(gfpgan_weight),
                    upscale=self.upscale_factor.get(),
                    arch='clean',
                    channel_multiplier=2,
                    bg_upsampler=self.upsampler
                )

                self.log("✅ GFPGAN 人脸增强模型加载完成")

            return True

        except Exception as e:
            logger.error(f"模型初始化失败: {e}")
            self.log(f"❌ 模型初始化失败: {e}")
            return False

    def start_processing(self):
        """开始批量处理"""
        input_dir = self.input_dir.get()
        output_dir = self.output_dir.get()

        # 验证输入
        if not input_dir or not os.path.isdir(input_dir):
            messagebox.showerror("错误", "请选择有效的图片目录")
            return

        if not output_dir:
            messagebox.showerror("错误", "请选择导出目录")
            return

        # 检查库是否安装（None=还在加载中）
        if HAS_REALESRGAN is None:
            messagebox.showinfo("提示", "增强库正在加载中，请稍后再试...")
            return
        if not HAS_REALESRGAN:
            messagebox.showerror("错误", "未安装 Real-ESRGAN\n请执行: pip install realesrgan basicsr facexlib")
            return

        if self.face_enhance.get() and not HAS_GFPGAN:
            if not messagebox.askyesno("警告", "未安装 GFPGAN，人脸增强功能将禁用\n是否继续？\n安装命令: pip install gfpgan"):
                return

        # 创建输出目录
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建输出目录: {e}")
            return

        # 扫描图片文件
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        image_files = []
        
        for file_path in Path(input_dir).rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                image_files.append(str(file_path))

        if not image_files:
            messagebox.showwarning("警告", "未找到图片文件")
            return

        self.log(f"找到 {len(image_files)} 张图片")
        self.log(f"放大倍数: {self.upscale_factor.get()}x")
        self.log(f"人脸增强: {'启用' if self.face_enhance.get() else '禁用'}")
        self.log(f"线程数: {self.thread_count.get()}")

        # 保存配置
        self.save_config()

        # 初始化模型
        if not self.init_models():
            messagebox.showerror("错误", "模型初始化失败，请查看日志")
            return

        # 禁用开始按钮，启用停止按钮
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.is_processing = True
        self._stop_event.clear()

        # 重置进度
        self.progress['value'] = 0
        self.progress['maximum'] = len(image_files)

        # 启动处理线程
        thread = threading.Thread(
            target=self._process_images,
            args=(image_files, output_dir),
            daemon=True
        )
        thread.start()

    def stop_processing(self):
        """停止处理"""
        self._stop_event.set()
        self.is_processing = False
        self.log("⚠️ 正在停止，等待当前任务完成...")

    def _process_images(self, image_files, output_dir):
        """在工作线程中处理图片"""
        executor = None
        try:
            success_count = 0
            fail_count = 0
            total = len(image_files)

            # 手动管理线程池
            executor = ThreadPoolExecutor(max_workers=self.thread_count.get())
            futures = {}

            # 提交任务阶段
            for image_path in image_files:
                if self._stop_event.is_set():
                    break
                future = executor.submit(
                    self._process_single_image,
                    image_path,
                    output_dir
                )
                futures[future] = image_path

            if self._stop_event.is_set() and not futures:
                self.log("⚠️ 已停止，未提交任何任务")
                return

            # 收集结果阶段
            pending = set(futures.keys())
            while pending:
                if self._stop_event.is_set():
                    cancelled = 0
                    for f in list(pending):
                        if f.cancel():
                            pending.discard(f)
                            cancelled += 1
                    if cancelled > 0:
                        self.log(f"已取消 {cancelled} 个排队中的任务")
                    if not pending:
                        break

                done = set()
                for f in list(pending):
                    if f.done():
                        done.add(f)

                if not done:
                    self._stop_event.wait(timeout=0.2)
                    continue

                for future in done:
                    pending.discard(future)
                    image_path = futures[future]
                    try:
                        result = future.result()
                        if result:
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        fail_count += 1
                        self.log(f"❌ {os.path.basename(image_path)}: {e}")

                    current = success_count + fail_count
                    self.root.after(0, lambda v=current: self.progress.config(value=v))
                    self.root.after(0, lambda s=success_count, f=fail_count, t=total:
                                  self.progress_label.config(text=f"进度: {s + f}/{t} (成功: {s}, 失败: {f})"))

            if self._stop_event.is_set():
                self.log(f"⚠️ 处理已停止。已处理: {success_count + fail_count}/{total} (成功: {success_count}, 失败: {fail_count})")
            else:
                self.log(f"✅ 处理完成！成功: {success_count}, 失败: {fail_count}")
                msg = f"成功: {success_count}，失败: {fail_count}"
                self.root.after(0, lambda: self._show_toast("图片增强完成", msg, "success"))

        except Exception as e:
            logger.error(f"批量处理出错: {e}")
            self.log(f"❌ 处理出错: {e}")

        finally:
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    executor.shutdown(wait=False)
            self.is_processing = False
            self._stop_event.clear()
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    def _enhance_with_retry(self, img):
        """增强图片，tile模式失败时自动回退到整图模式重试"""
        # 第一次尝试：tile 分块模式（内存友好）
        try:
            if self.face_enhance.get() and self.face_enhancer:
                _, _, output = self.face_enhancer.enhance(
                    img, has_aligned=False, only_center_face=False,
                    paste_back=True, weight=0.5
                )
            else:
                output, _ = self.upsampler.enhance(
                    img, outscale=self.upscale_factor.get()
                )
            return output
        except RuntimeError as e:
            if 'tile' not in str(e).lower() and 'size' not in str(e).lower():
                raise  # 非 tile 相关错误，直接抛出
            logger.warning(f"tile 模式处理失败，回退到整图模式重试: {e}")
            self.log("⚠️ 分块模式失败，切换整图模式重试（内存占用较大）...")

        # 第二次尝试：关闭 tile，整图处理
        original_tile = self.upsampler.tile
        try:
            self.upsampler.tile = 0
            if self.face_enhance.get() and self.face_enhancer:
                _, _, output = self.face_enhancer.enhance(
                    img, has_aligned=False, only_center_face=False,
                    paste_back=True, weight=0.5
                )
            else:
                output, _ = self.upsampler.enhance(
                    img, outscale=self.upscale_factor.get()
                )
            return output
        finally:
            self.upsampler.tile = original_tile

    def _process_single_image(self, image_path, output_dir):
        """处理单张图片，返回是否成功"""
        try:
            import cv2
            import numpy as np
            
            # 读取图片（支持中文路径）
            img = cv2.imdecode(
                np.fromfile(image_path, dtype=np.uint8),
                cv2.IMREAD_UNCHANGED
            )
            
            if img is None:
                raise ValueError(f"无法读取图片: {image_path}")

            # 获取原始尺寸
            h, w = img.shape[:2]
            logger.debug(f"处理图片: {os.path.basename(image_path)} 原始尺寸: {w}x{h}")
            self.log(f"⏳ 正在处理 {os.path.basename(image_path)} ({w}x{h})，CPU 模式较慢请耐心等待...")

            output = self._enhance_with_retry(img)

            # 生成输出路径（保留原文件名）
            rel_path = os.path.relpath(image_path, self.input_dir.get())
            output_path = os.path.join(output_dir, rel_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # 保存（支持中文路径）
            ext = os.path.splitext(output_path)[1]
            success, buf = cv2.imencode(ext, output)
            if success:
                buf.tofile(output_path)
            else:
                raise RuntimeError(f"编码图片失败: {output_path}")

            new_h, new_w = output.shape[:2]
            self.log(f"✅ {os.path.basename(image_path)} ({w}x{h}) → ({new_w}x{new_h})")
            logger.info(f"增强成功: {image_path} → {output_path}")
            return True

        except Exception as e:
            logger.error(f"处理失败: {image_path} | {e}")
            self.log(f"❌ {os.path.basename(image_path)}: {e}")
            return False


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageEnhancerApp(root)
    root.mainloop()
