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

# 尝试导入主体检测库
try:
    from rembg import remove as rembg_remove
    HAS_REMBG = True
except ImportError:
    HAS_REMBG = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# 配置文件路径
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config_batch_image_cropper.json"


class BatchImageCropperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🖼️ 批量图片裁剪工具")
        self.root.geometry("900x700")
        self.root.resizable(True, True)

        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))
        self.style.configure("TCheckbutton", font=("SimHei", 9))

        # 初始化变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.crop_ratio = tk.StringVar(value="自动")
        self.thread_count = tk.IntVar(value=5)
        self.subject_aware = tk.BooleanVar(value=True)
        self._stop_event = threading.Event()  # 线程安全的停止信号
        self.is_processing = False
        self.log_queue = queue.Queue()

        # 创建UI组件
        self.create_widgets()

        # 加载配置
        self.load_config()

        # 启动日志队列轮询
        self._poll_log_queue()

        logger.info("批量裁剪工具启动")

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(main_frame, text="批量图片裁剪工具", font=("SimHei", 16, "bold"))
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

        # 裁剪参数设置
        param_frame = ttk.LabelFrame(main_frame, text="裁剪参数", padding="10")
        param_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(param_frame, text="裁剪比例:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ratio_combo = ttk.Combobox(
            param_frame,
            textvariable=self.crop_ratio,
            values=["自动", "1:1", "16:9", "9:16"],
            state="readonly",
            width=10
        )
        ratio_combo.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(param_frame, text="线程数:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        thread_spin = ttk.Spinbox(
            param_frame,
            from_=1,
            to=20,
            textvariable=self.thread_count,
            width=5
        )
        thread_spin.grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Checkbutton(
            param_frame,
            text="智能主体检测（自动识别人物/主体）",
            variable=self.subject_aware
        ).grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(10, 0))

        # 检测库状态提示
        lib_status = []
        if HAS_REMBG:
            lib_status.append("✅ rembg")
        if HAS_CV2:
            lib_status.append("✅ opencv")
        
        if lib_status:
            status_text = "可用检测库: " + " | ".join(lib_status)
            status_color = "green"
        else:
            status_text = "⚠️ 未安装检测库，将使用中心裁剪（pip install rembg 或 opencv-python 可启用智能检测）"
            status_color = "orange"

        ttk.Label(param_frame, text=status_text, foreground=status_color, font=("SimHei", 8)).grid(
            row=2, column=0, columnspan=4, sticky=tk.W, pady=(5, 0)
        )

        # 控制按钮
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="开始裁剪", command=self.start_processing)
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

    def load_config(self):
        """加载配置文件"""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.input_dir.set(config.get('input_dir', ''))
                    self.output_dir.set(config.get('output_dir', ''))
                    self.crop_ratio.set(config.get('crop_ratio', '1:1'))
                    self.thread_count.set(config.get('thread_count', 5))
                    self.subject_aware.set(config.get('subject_aware', True))
                logger.info("配置加载成功")
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")

    def save_config(self):
        """保存配置文件"""
        try:
            config = {
                'input_dir': self.input_dir.get(),
                'output_dir': self.output_dir.get(),
                'crop_ratio': self.crop_ratio.get(),
                'thread_count': self.thread_count.get(),
                'subject_aware': self.subject_aware.get()
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

    def clear_log(self):
        """清空日志显示"""
        self.log_text.delete(1.0, tk.END)

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

        # 创建输出目录
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建输出目录: {e}")
            return

        # 扫描图片文件
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
        image_files = []
        
        for file_path in Path(input_dir).rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                image_files.append(str(file_path))

        if not image_files:
            messagebox.showwarning("警告", "未找到图片文件")
            return

        self.log(f"找到 {len(image_files)} 张图片")
        ratio_mode = self.crop_ratio.get()
        self.log(f"裁剪比例: {ratio_mode}" + ("（根据主体自动适配）" if ratio_mode == "自动" else ""))
        self.log(f"线程数: {self.thread_count.get()}")
        self.log(f"智能主体检测: {'启用' if self.subject_aware.get() else '禁用'}")

        # 保存配置
        self.save_config()

        # 禁用开始按钮，启用停止按钮
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.is_processing = True
        self._stop_event.clear()  # 重置停止信号

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
        self._stop_event.set()  # 立即发出停止信号
        self.is_processing = False
        self.log("⚠️ 正在停止，等待当前任务完成...")

    def _process_images(self, image_files, output_dir):
        """在工作线程中处理图片"""
        executor = None
        try:
            ratio_mode = self.crop_ratio.get()
            # 预解析固定比例（"自动"模式下每张图单独计算）
            fixed_target_ratio = None
            if ratio_mode != "自动":
                rw, rh = map(int, ratio_mode.split(':'))
                fixed_target_ratio = rw / rh

            success_count = 0
            fail_count = 0
            total = len(image_files)

            # 手动管理线程池，不用 with 语句（避免 __exit__ 阻塞等待）
            executor = ThreadPoolExecutor(max_workers=self.thread_count.get())
            futures = {}

            # 提交任务阶段：逐个提交，遇到停止信号立即中断
            for image_path in image_files:
                if self._stop_event.is_set():
                    break
                future = executor.submit(
                    self._process_single_image,
                    image_path,
                    output_dir,
                    fixed_target_ratio
                )
                futures[future] = image_path

            submitted_count = len(futures)
            if self._stop_event.is_set() and not futures:
                # 还没提交任何任务就停止了
                self.log("⚠️ 已停止，未提交任何任务")
                return

            # 收集结果阶段：用非阻塞方式轮询，遇到停止信号立即中断
            pending = set(futures.keys())
            while pending:
                if self._stop_event.is_set():
                    # 取消尚未开始的任务
                    cancelled = 0
                    for f in list(pending):
                        if f.cancel():
                            pending.discard(f)
                            cancelled += 1
                    if cancelled > 0:
                        self.log(f"已取消 {cancelled} 个排队中的任务")
                    # 仍在运行的任务等其完成
                    if not pending:
                        break

                # 非阻塞检查已完成的 future
                done = set()
                for f in list(pending):
                    if f.done():
                        done.add(f)

                if not done:
                    # 没有已完成的 future，短暂等待避免 CPU 空转
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

                    # 更新进度
                    current = success_count + fail_count
                    self.root.after(0, lambda v=current: self.progress.config(value=v))
                    self.root.after(0, lambda s=success_count, f=fail_count, t=total:
                                  self.progress_label.config(text=f"进度: {s + f}/{t} (成功: {s}, 失败: {f})"))

            # 完成
            if self._stop_event.is_set():
                self.log(f"⚠️ 处理已停止。已处理: {success_count + fail_count}/{total} (成功: {success_count}, 失败: {fail_count})")
            else:
                self.log(f"✅ 处理完成！成功: {success_count}, 失败: {fail_count}")
                self.root.after(0, lambda: messagebox.showinfo("完成", f"批量裁剪完成！\n成功: {success_count}\n失败: {fail_count}"))

        except Exception as e:
            logger.error(f"批量处理出错: {e}")
            self.log(f"❌ 处理出错: {e}")

        finally:
            # 手动关闭线程池，不阻塞等待
            if executor is not None:
                try:
                    # Python 3.9+ 支持 cancel_futures 参数
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    # Python < 3.9 不支持 cancel_futures
                    executor.shutdown(wait=False)
            self.is_processing = False
            self._stop_event.clear()
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    # 主体边距缓冲系数：在主体边界外扩展一定比例，避免裁切太紧
    SUBJECT_PADDING_RATIO = 0.15  # 每边扩展 15%

    def _calc_crop_with_subject(self, img_w, img_h, target_ratio, subject_box):
        """
        根据主体边界框和目标比例计算最佳裁剪区域
        返回: (crop_x1, crop_y1, crop_x2, crop_y2, actual_ratio_label)
        """
        sx1, sy1, sx2, sy2 = subject_box
        subject_w = sx2 - sx1
        subject_h = sy2 - sy1
        subject_cx = (sx1 + sx2) // 2
        subject_cy = (sy1 + sy2) // 2

        # 添加边距缓冲
        padding_x = int(subject_w * self.SUBJECT_PADDING_RATIO)
        padding_y = int(subject_h * self.SUBJECT_PADDING_RATIO)

        # 扩展后的主体区域
        expanded_x1 = max(0, sx1 - padding_x)
        expanded_y1 = max(0, sy1 - padding_y)
        expanded_x2 = min(img_w, sx2 + padding_x)
        expanded_y2 = min(img_h, sy2 + padding_y)

        expanded_w = expanded_x2 - expanded_x1
        expanded_h = expanded_y2 - expanded_y1
        expanded_ratio = expanded_w / expanded_h

        # 如果目标比例为 None（自动模式），使用主体的自然比例
        if target_ratio is None:
            # 使用扩展后的主体比例
            crop_w = expanded_w
            crop_h = expanded_h
            crop_cx = (expanded_x1 + expanded_x2) // 2
            crop_cy = (expanded_y1 + expanded_y2) // 2

            # 确保裁剪区域在图片范围内
            crop_x1 = max(0, crop_cx - crop_w // 2)
            crop_y1 = max(0, crop_cy - crop_h // 2)
            crop_x2 = crop_x1 + crop_w
            crop_y2 = crop_y1 + crop_h

            # 如果超出边界，调整
            if crop_x2 > img_w:
                crop_x2 = img_w
                crop_x1 = crop_x2 - crop_w
            if crop_y2 > img_h:
                crop_y2 = img_h
                crop_y1 = crop_y2 - crop_h

            actual_ratio = f"自动({crop_w}:{crop_h})"
            return (crop_x1, crop_y1, crop_x2, crop_y2, actual_ratio)

        # 固定比例模式：确保主体完全包含在裁剪区域内
        img_ratio = img_w / img_h

        if img_ratio > target_ratio:
            # 图片更宽，以高度为基准
            crop_h = img_h
            crop_w = int(img_h * target_ratio)
        else:
            # 图片更高，以宽度为基准
            crop_w = img_w
            crop_h = int(img_w / target_ratio)

        # 检查主体是否能放入固定比例的裁剪框
        if expanded_w > crop_w or expanded_h > crop_h:
            # 主体太大，需要扩大裁剪框以包含主体
            # 保持目标比例，但扩大尺寸
            scale_w = expanded_w / crop_w if expanded_w > crop_w else 1.0
            scale_h = expanded_h / crop_h if expanded_h > crop_h else 1.0
            scale = max(scale_w, scale_h)

            crop_w = int(crop_w * scale)
            crop_h = int(crop_h * scale)

            # 确保不超过图片边界
            crop_w = min(crop_w, img_w)
            crop_h = min(crop_h, img_h)

        # 以主体为中心放置裁剪框
        crop_x1 = max(0, min(img_w - crop_w, subject_cx - crop_w // 2))
        crop_y1 = max(0, min(img_h - crop_h, subject_cy - crop_h // 2))
        crop_x2 = crop_x1 + crop_w
        crop_y2 = crop_y1 + crop_h

        return (crop_x1, crop_y1, crop_x2, crop_y2, None)

    def _process_single_image(self, image_path, output_dir, fixed_target_ratio):
        """处理单张图片，返回是否成功"""
        try:
            # 打开图片
            img = Image.open(image_path)
            img_width, img_height = img.size

            # 默认居中裁剪
            orig_x1 = (img_width - img_width) // 2
            orig_y1 = (img_height - img_height) // 2
            orig_x2 = orig_x1 + img_width
            orig_y2 = orig_y1 + img_height
            actual_ratio_label = None

            # 如果启用智能主体检测
            if self.subject_aware.get():
                subject_box = self._detect_subject(img)
                if subject_box:
                    # 使用智能裁剪计算
                    result = self._calc_crop_with_subject(
                        img_width, img_height,
                        fixed_target_ratio,
                        subject_box
                    )
                    orig_x1, orig_y1, orig_x2, orig_y2, actual_ratio_label = result
            else:
                # 无主体检测，使用固定比例居中裁剪
                if fixed_target_ratio is not None:
                    img_ratio = img_width / img_height
                    if img_ratio > fixed_target_ratio:
                        crop_h = img_height
                        crop_w = int(img_height * fixed_target_ratio)
                    else:
                        crop_w = img_width
                        crop_h = int(img_width / fixed_target_ratio)

                    orig_x1 = (img_width - crop_w) // 2
                    orig_y1 = (img_height - crop_h) // 2
                    orig_x2 = orig_x1 + crop_w
                    orig_y2 = orig_y1 + crop_h

            # 裁剪
            cropped = img.crop((orig_x1, orig_y1, orig_x2, orig_y2))

            # 生成输出路径
            rel_path = os.path.relpath(image_path, self.input_dir.get())
            output_path = os.path.join(output_dir, rel_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # 保存
            if output_path.lower().endswith('.png'):
                cropped.save(output_path, 'PNG')
            elif output_path.lower().endswith(('.jpg', '.jpeg')):
                cropped.save(output_path, 'JPEG', quality=95)
            else:
                cropped.save(output_path)

            ratio_info = f" [{actual_ratio_label}]" if actual_ratio_label else ""
            self.log(f"✅ {os.path.basename(image_path)}{ratio_info} → {os.path.basename(output_path)}")
            logger.info(f"裁剪成功: {image_path} → {output_path}{ratio_info}")
            return True

        except Exception as e:
            logger.error(f"处理失败: {image_path} | {e}")
            return False

    def _detect_subject(self, img):
        """检测图片中的主体，返回边界框 (x1, y1, x2, y2) 或 None"""
        try:
            # 优先使用 rembg（效果最好）
            if HAS_REMBG:
                return self._detect_with_rembg(img)
            
            # 其次使用 opencv 人脸检测
            if HAS_CV2:
                return self._detect_with_opencv(img)
            
            return None
        except Exception as e:
            logger.debug(f"主体检测失败: {e}")
            return None

    def _detect_with_rembg(self, img):
        """使用 rembg 检测主体"""
        try:
            # 移除背景
            result = rembg_remove(img)
            
            # 转换为 RGBA
            if result.mode != 'RGBA':
                result = result.convert('RGBA')
            
            # 获取 alpha 通道
            alpha = result.split()[3]
            
            # 找到非透明区域的边界
            bbox = alpha.getbbox()
            if bbox:
                logger.debug(f"rembg 检测到主体: {bbox}")
                return bbox
            
            return None
        except Exception as e:
            logger.debug(f"rembg 检测失败: {e}")
            return None

    def _detect_with_opencv(self, img):
        """使用 opencv 检测人脸"""
        try:
            # 转换为 RGB
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 转换为 numpy 数组
            import numpy as np
            img_array = np.array(img)
            
            # 转换为灰度图
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # 加载人脸检测器
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            face_cascade = cv2.CascadeClassifier(cascade_path)
            
            # 检测人脸
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            
            if len(faces) > 0:
                # 取最大的人脸区域
                largest_face = max(faces, key=lambda f: f[2] * f[3])
                x, y, w, h = largest_face
                
                # 扩展区域以包含更多主体（大约是脸部的 2 倍）
                x1 = max(0, x - w // 2)
                y1 = max(0, y - h // 2)
                x2 = min(img.width, x + w + w // 2)
                y2 = min(img.height, y + h + h // 2)
                
                logger.debug(f"opencv 检测到人脸: {(x, y, w, h)} → 主体区域: {(x1, y1, x2, y2)}")
                return (x1, y1, x2, y2)
            
            return None
        except Exception as e:
            logger.debug(f"opencv 检测失败: {e}")
            return None


if __name__ == "__main__":
    root = tk.Tk()
    app = BatchImageCropperApp(root)
    root.mainloop()
