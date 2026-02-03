# ppt_to_images.pyw （修复中文路径问题版）
import os
import json
import logging
import threading
import queue
import time
import tempfile
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "ppt_to_imagesandpdf"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOGS_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# 默认配置
DEFAULT_CONFIG = {
    "input_files": [],
    "output_dir": str(Path.home() / "Documents"),
    "max_workers": 3,
    "convert_to_pdf": False,
    "pdf_output_dir": ""
}

# 支持的文件类型
PPT_EXTENSIONS = [("PowerPoint Files", "*.ppt *.pptx *.pps *.ppsx"), ("All Files", "*.*")]

# 全局控制事件
stop_event = threading.Event()
pause_event = threading.Event()
pause_event.set()  # 初始为运行状态

# ==============================
# PPT 转图片核心函数（使用 win32com）
# ==============================
def ppt_to_images(ppt_path: Path, base_output_dir: Path):
    """将 PPT 文件转换为 PNG 图片，保存在 {base_output_dir}/{ppt_stem}/ 目录下，文件名为 1.PNG, 2.PNG..."""
    try:
        import win32com.client
        import win32api

        # 创建输出子目录：与 PPT 同名
        output_subdir = base_output_dir / ppt_path.stem
        output_subdir.mkdir(parents=True, exist_ok=True)

        # 获取短路径（解决中文/特殊符号问题）
        ppt_short = win32api.GetShortPathName(str(ppt_path))

        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
        powerpoint.DisplayAlerts = False
        powerpoint.Visible = True  # 必须为 True，否则可能失败

        deck = powerpoint.Presentations.Open(ppt_short, WithWindow=False)
        slide_count = deck.Slides.Count

        # 逐页导出为 1.PNG, 2.PNG, ...
        for i in range(1, slide_count + 1):
            slide = deck.Slides(i)
            # 构造目标路径：{subdir}/{i}.PNG
            img_path = output_subdir / f"{i}.PNG"
            # PowerPoint 的 Export 方法要求传入完整路径（含扩展名）
            slide.Export(str(img_path), "PNG")

        deck.Close()
        powerpoint.Quit()

        return True, f"成功导出 {slide_count} 张图片到 {output_subdir}"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"转换 {ppt_path} 失败: {error_msg}")
        try:
            powerpoint.Quit()
        except:
            pass
        return False, error_msg

# ==============================
# 图片转PDF函数（修复中文路径问题）
# ==============================
def images_to_pdf(image_dir: Path, pdf_path: Path):
    """将 image_dir 目录下的 1.PNG, 2.PNG... 合并为 PDF"""
    try:
        from PIL import Image

        # 获取所有图片文件（按数字顺序排序）
        image_files = []
        for f in sorted(image_dir.iterdir(), key=lambda x: int(x.stem) if x.stem.isdigit() else float('inf')):
            if f.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                image_files.append(f)

        if not image_files:
            return False, "未找到任何图片文件"

        # 打开第一张图作为基础（获取尺寸）
        first_img = Image.open(image_files[0])
        # 转换为RGB（某些PNG可能有透明通道，PDF不支持）
        first_img = first_img.convert("RGB")

        # 打开其余图片并转换为RGB
        other_imgs = []
        for img_path in image_files[1:]:
            img = Image.open(img_path)
            img = img.convert("RGB")
            other_imgs.append(img)

        # 创建临时PDF文件（避免中文路径问题）
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            temp_pdf_path = tmp_file.name

        try:
            # 保存为临时PDF
            first_img.save(
                temp_pdf_path,
                "PDF",
                resolution=100.0,
                save_all=True,
                append_images=other_imgs,
                append=True
            )

            # 将临时文件移动到目标位置
            import shutil
            pdf_path.parent.mkdir(parents=True, exist_ok=True)  # 确保目标目录存在
            shutil.move(temp_pdf_path, pdf_path)

            return True, f"成功生成PDF: {pdf_path.name}"

        except Exception as e:
            # 清理临时文件
            try:
                os.unlink(temp_pdf_path)
            except:
                pass
            raise e

    except Exception as e:
        error_msg = str(e)
        logger.error(f"生成PDF失败 {pdf_path}: {error_msg}")
        return False, error_msg

# ==============================
# 多线程工作队列处理器
# ==============================
def worker(task_queue, result_callback):
    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=0.5)
            if task is None:
                break

            ppt_file, output_dir = task

            # 检查是否暂停
            while not pause_event.is_set() and not stop_event.is_set():
                time.sleep(0.1)

            if stop_event.is_set():
                break

            success, msg = ppt_to_images(ppt_file, output_dir)
            result_callback(ppt_file, success, msg)
            task_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Worker 异常: {e}")

# ==============================
# GUI 主类
# ==============================
class PptToImagesGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🖼️ 演示文稿转图片工具")
        self.root.geometry("720x580")
        self.root.resizable(True, True)

        self.config = load_config()
        self.task_queue = None
        self.workers = []
        self.completed_count = 0
        self.total_count = 0
        self.setup_ui()

    def setup_ui(self):
        # 输入文件
        input_frame = LabelFrame(self.root, text="📂 选择 PPT/PPS 文件", padx=10, pady=8)
        input_frame.pack(fill=X, padx=10, pady=5)
        self.input_listbox = Listbox(input_frame, selectmode=EXTENDED, height=6)
        self.input_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = Scrollbar(input_frame, orient=VERTICAL, command=self.input_listbox.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.input_listbox.config(yscrollcommand=scrollbar.set)

        btn_frame = Frame(input_frame)
        btn_frame.pack(side=RIGHT, padx=(10, 0))
        Button(btn_frame, text="➕ 添加", command=self.add_files).pack(pady=2)
        Button(btn_frame, text="🗑️ 删除", command=self.remove_files).pack(pady=2)
        Button(btn_frame, text="🧹 清空", command=self.clear_files).pack(pady=2)

        # 输出目录
        output_frame = LabelFrame(self.root, text="📁 基础输出目录（每份PPT会创建同名子文件夹）", padx=10, pady=8)
        output_frame.pack(fill=X, padx=10, pady=5)
        self.output_dir_var = StringVar(value=self.config["output_dir"])
        Entry(output_frame, textvariable=self.output_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(output_frame, text="📁 浏览", command=self.browse_output_dir).pack(side=RIGHT, padx=(5, 0))

        # 线程数设置
        thread_frame = LabelFrame(self.root, text="⚙️ 转换线程数", padx=10, pady=8)
        thread_frame.pack(fill=X, padx=10, pady=5)
        self.thread_var = IntVar(value=self.config.get("max_workers", 3))
        Spinbox(thread_frame, from_=1, to=10, textvariable=self.thread_var, width=5).pack(side=LEFT)
        Label(thread_frame, text="（建议 1～5）").pack(side=LEFT, padx=(10, 0))

        # PDF 选项
        pdf_frame = LabelFrame(self.root, text="📄 PDF 选项", padx=10, pady=8)
        pdf_frame.pack(fill=X, padx=10, pady=5)

        self.convert_pdf_var = BooleanVar(value=self.config.get("convert_to_pdf", False))
        self.convert_pdf_check = Checkbutton(pdf_frame, text="同时将图片合并为 PDF（每个PPT生成一个PDF）",
                                             variable=self.convert_pdf_var, command=self.toggle_pdf_options)
        self.convert_pdf_check.pack(anchor=W)

        pdf_output_frame = Frame(pdf_frame)
        pdf_output_frame.pack(fill=X, pady=5)
        self.pdf_output_dir_var = StringVar(value=self.config.get("pdf_output_dir", ""))
        self.pdf_output_label = Label(pdf_output_frame, text="PDF 输出目录:", width=15, anchor=W)
        self.pdf_output_entry = Entry(pdf_output_frame, textvariable=self.pdf_output_dir_var, font=("Consolas", 9))
        self.pdf_output_browse_btn = Button(pdf_output_frame, text="📁 浏览", command=self.browse_pdf_output_dir)

        # 默认隐藏PDF选项
        self.toggle_pdf_options()

        # 控制按钮
        control_frame = Frame(self.root)
        control_frame.pack(pady=10)
        self.start_btn = Button(control_frame, text="▶️ 开始", command=self.start_conversion, bg="#4CAF50", fg="white", width=10)
        self.start_btn.pack(side=LEFT, padx=5)
        self.pause_btn = Button(control_frame, text="⏸️ 暂停", command=self.toggle_pause, bg="#FF9800", fg="white", width=10, state=DISABLED)
        self.pause_btn.pack(side=LEFT, padx=5)
        self.stop_btn = Button(control_frame, text="⏹️ 停止", command=self.stop_conversion, bg="#F44336", fg="white", width=10, state=DISABLED)
        self.stop_btn.pack(side=LEFT, padx=5)

        # 日志显示
        log_frame = LabelFrame(self.root, text="📋 转换日志", padx=10, pady=8)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.log_text = Text(log_frame, wrap=WORD, height=10, state=DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)
        log_scroll = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

        # 初始化文件列表
        for f in self.config.get("input_files", []):
            if Path(f).exists():
                self.input_listbox.insert(END, f)

    def toggle_pdf_options(self):
        """根据复选框状态显示/隐藏PDF相关控件"""
        if self.convert_pdf_var.get():
            self.pdf_output_label.pack(side=LEFT)
            self.pdf_output_entry.pack(side=LEFT, fill=X, expand=True, padx=(5, 0))
            self.pdf_output_browse_btn.pack(side=RIGHT)
        else:
            self.pdf_output_label.pack_forget()
            self.pdf_output_entry.pack_forget()
            self.pdf_output_browse_btn.pack_forget()

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="选择基础输出目录", initialdir=self.output_dir_var.get())
        if folder:
            self.output_dir_var.set(folder)

    def browse_pdf_output_dir(self):
        folder = filedialog.askdirectory(title="选择PDF输出目录", initialdir=self.pdf_output_dir_var.get())
        if folder:
            self.pdf_output_dir_var.set(folder)

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 PPT/PPS 文件",
            filetypes=PPT_EXTENSIONS
        )
        for f in files:
            self.input_listbox.insert(END, f)

    def remove_files(self):
        selected = list(self.input_listbox.curselection())
        for index in reversed(selected):
            self.input_listbox.delete(index)

    def clear_files(self):
        self.input_listbox.delete(0, END)

    def log_message(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def start_conversion(self):
        # 获取输入
        files = [Path(self.input_listbox.get(i)) for i in range(self.input_listbox.size())]
        output_dir = Path(self.output_dir_var.get().strip())
        max_workers = self.thread_var.get()

        if not files:
            messagebox.showwarning("警告", "请至少选择一个 PPT/PPS 文件！")
            return
        if not output_dir:
            messagebox.showwarning("警告", "请指定基础输出目录！")
            return

        # 验证文件存在
        missing = [f for f in files if not f.exists()]
        if missing:
            messagebox.showerror("错误", f"以下文件不存在：\n" + "\n".join(str(f) for f in missing))
            return

        # 保存配置（包含新增字段）
        current_config = {
            "input_files": [str(f) for f in files],
            "output_dir": str(output_dir),
            "max_workers": max_workers,
            "convert_to_pdf": self.convert_pdf_var.get(),
            "pdf_output_dir": self.pdf_output_dir_var.get()
        }
        save_config(current_config)

        # 初始化状态
        self.completed_count = 0
        self.total_count = len(files)
        self.status_var.set(f"准备中... 共 {self.total_count} 个文件")
        self.log_message(f"开始转换 {self.total_count} 个文件，线程数: {max_workers}")

        # 重置全局事件
        global stop_event, pause_event
        stop_event.clear()
        pause_event.set()

        # 创建任务队列
        self.task_queue = queue.Queue()
        for f in files:
            self.task_queue.put((f, output_dir))

        # 启动工作线程
        self.workers = []
        for _ in range(max_workers):
            t = threading.Thread(target=worker, args=(self.task_queue, self.on_task_complete), daemon=True)
            t.start()
            self.workers.append(t)

        # 更新 UI
        self.start_btn.config(state=DISABLED)
        self.pause_btn.config(state=NORMAL)
        self.stop_btn.config(state=NORMAL)

        # 启动监控线程（自动结束）
        monitor_thread = threading.Thread(target=self.monitor_completion, daemon=True)
        monitor_thread.start()

    def monitor_completion(self):
        """监控任务完成，自动结束"""
        while not stop_event.is_set():
            if self.completed_count >= self.total_count:
                self.root.after(0, self.finalize_conversion)
                break
            time.sleep(0.3)

    def on_task_complete(self, ppt_file, success, msg):
        self.completed_count += 1
        prefix = "✅ 成功" if success else "❌ 失败"
        self.root.after(0, lambda m=f"{prefix}: {ppt_file.name} | {msg}": self.log_message(m))

        # ✅ 如果原任务成功 且 用户勾选了转PDF，则执行PDF转换
        if success and self.convert_pdf_var.get():
            output_base_dir = Path(self.output_dir_var.get())
            image_subdir = output_base_dir / ppt_file.stem

            if image_subdir.exists():
                # PDF输出目录
                pdf_output_dir_str = self.pdf_output_dir_var.get().strip()
                pdf_output_dir = Path(pdf_output_dir_str) if pdf_output_dir_str else output_base_dir
                pdf_output_dir.mkdir(parents=True, exist_ok=True)

                pdf_path = pdf_output_dir / f"{ppt_file.stem}.pdf"

                # 在后台线程中执行PDF转换，避免阻塞GUI
                pdf_thread = threading.Thread(
                    target=self.run_pdf_conversion,
                    args=(image_subdir, pdf_path, ppt_file.name),
                    daemon=True
                )
                pdf_thread.start()
            else:
                self.root.after(0, lambda: self.log_message(f"⚠️ 警告: 图片目录不存在，无法生成PDF: {image_subdir}"))

        self.root.after(0, lambda: self.status_var.set(f"进度: {self.completed_count}/{self.total_count}"))

    def run_pdf_conversion(self, image_dir, pdf_path, ppt_name):
        """在后台线程中执行PDF转换"""
        success, msg = images_to_pdf(image_dir, pdf_path)
        prefix = "📄 PDF" if success else "❌ PDF"
        self.root.after(0, lambda m=f"{prefix}: {ppt_name} | {msg}": self.log_message(m))

    def finalize_conversion(self):
        """所有任务完成后自动清理和提示"""
        global stop_event
        stop_event.set()  # 确保所有线程退出

        # 恢复按钮状态
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)
        self.status_var.set("✅ 转换完成！")
        self.log_message("所有任务已完成。")

        # 弹窗提示（在主线程中）
        self.root.after(0, lambda: messagebox.showinfo("完成", f"✅ 转换完成！共处理 {self.total_count} 个文件。"))

    def toggle_pause(self):
        global pause_event
        if pause_event.is_set():
            pause_event.clear()
            self.pause_btn.config(text="▶️ 继续")
            self.status_var.set("⏸️ 已暂停")
        else:
            pause_event.set()
            self.pause_btn.config(text="⏸️ 暂停")
            self.status_var.set("▶️ 恢复中...")

    def stop_conversion(self):
        global stop_event
        stop_event.set()
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)
        self.status_var.set("⏹️ 已停止")
        self.log_message("用户已停止转换。")

# ==============================
# 配置工具函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 按要求引入 DB_CONFIG（即使不用）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)
        except:
            pass

    root = Tk()
    app = PptToImagesGUI(root)
    root.mainloop()
