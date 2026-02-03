# images_to_pdf.pyw

import os
import json
import logging
import threading
import time
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk
from PIL import Image, ImageDraw, ImageFont
import tempfile
import traceback

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "images_to_pdf"
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
    "input_dir": "",
    "output_dir": str(Path.home() / "Documents"),
    "include_cover": True  # 新增：是否包含封面
}

# 支持的图片格式
IMAGE_EXTENSIONS = {'.png','.PNG', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff'}

# 全局控制事件
stop_event = threading.Event()
pause_event = threading.Event()
pause_event.set()

# ==============================
# 工具函数：生成封面图
# ==============================
def create_cover_image(title: str, size=(1240, 1754), bg_color=(255, 255, 255), text_color=(0, 0, 0)):
    """生成一张 A4 比例（近似）的封面图，居中显示标题"""
    img = Image.new('RGB', size, color=bg_color)
    draw = ImageDraw.Draw(img)

    # 尝试加载系统字体，失败则用默认
    try:
        # Windows 常见中文字体
        font = ImageFont.truetype("msyh.ttc", 60)
    except:
        try:
            font = ImageFont.truetype("simhei.ttf", 60)
        except:
            font = ImageFont.load_default()

    # 计算文本位置（居中）
    bbox = draw.textbbox((0, 0), title, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size[0] - text_width) // 2
    y = (size[1] - text_height) // 2

    draw.text((x, y), title, fill=text_color, font=font)
    return img

# ==============================
# 核心转换函数
# ==============================

def process_story_folder(story_dir: Path, output_dir: Path, include_cover: bool = True):
    """处理单个故事子目录：生成封面 + 合并图片为 PDF"""
    try:
        if not story_dir.is_dir():
            return False, "不是有效目录"

        # 获取所有图片文件
        image_files = []
        for f in story_dir.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS:
                stem = f.stem
                try:
                    num = int(stem)
                except ValueError:
                    num = float('inf')  # 非数字放最后
                image_files.append((num, f))

        if not image_files:
            return False, "目录中无有效图片"

        image_files.sort(key=lambda x: x[0])
        sorted_paths = [f for _, f in image_files]

        # 创建封面（如果需要）
        pdf_images = []
        cover_img = None
        if include_cover:
            cover_img = create_cover_image(story_dir.name)
            pdf_images.append(cover_img)

        # 转换所有图片为 RGB（严格处理）
        for img_path in sorted_paths:
            try:
                with Image.open(img_path) as img:
                    # 如果是 GIF 且多帧，只取第一帧
                    if img.format == 'GIF' and hasattr(img, 'n_frames') and img.n_frames > 1:
                        img.seek(0)  # 取第一帧

                    # 转为 RGB
                    if img.mode in ("RGBA", "LA", "P"):
                        # 创建白色背景
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                        img = background
                    elif img.mode != "RGB":
                        img = img.convert("RGB")

                    pdf_images.append(img.copy())  # 确保图像数据被加载（避免 lazy loading 问题）
            except Exception as img_err:
                logger.warning(f"跳过无效图片 {img_path}: {img_err}")
                continue

        if len(pdf_images) == 0:  # 如果不需要封面且没有有效图片
            return False, "无有效图片可生成 PDF"

        # 保存 PDF
        output_pdf = output_dir / f"{story_dir.name}.pdf"
        pdf_images[0].save(
            output_pdf,
            save_all=True,
            append_images=pdf_images[1:],
            dpi=(150, 150),
            quality=95
        )
        pages = len(pdf_images)
        if include_cover:
            pages_info = f"共 {pages} 页（含封面）"
        else:
            pages_info = f"共 {pages} 页"

        return True, f"成功生成 PDF，{pages_info}"

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.error(f"处理 {story_dir} 时发生异常:\n{error_detail}")
        return False, str(e)

# ==============================
# GUI 主类
# ==============================
class ImagesToPdfGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📚 图片转 PDF（带封面）")
        self.root.geometry("700x480")
        self.root.resizable(True, True)

        self.config = load_config()
        self.running = False
        self.setup_ui()

    def setup_ui(self):
        # 输入目录（包含多个故事子目录）
        input_frame = LabelFrame(self.root, text="📂 输入目录（包含多个故事子文件夹）", padx=10, pady=8)
        input_frame.pack(fill=X, padx=10, pady=5)
        self.input_dir_var = StringVar(value=self.config["input_dir"])
        Entry(input_frame, textvariable=self.input_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(input_frame, text="📁 浏览", command=self.browse_input_dir).pack(side=RIGHT, padx=(5, 0))

        # 输出目录
        output_frame = LabelFrame(self.root, text="📁 输出 PDF 目录", padx=10, pady=8)
        output_frame.pack(fill=X, padx=10, pady=5)
        self.output_dir_var = StringVar(value=self.config["output_dir"])
        Entry(output_frame, textvariable=self.output_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(output_frame, text="📁 浏览", command=self.browse_output_dir).pack(side=RIGHT, padx=(5, 0))

        # 封面选项（新增）
        cover_frame = LabelFrame(self.root, text="📄 封面选项", padx=10, pady=8)
        cover_frame.pack(fill=X, padx=10, pady=5)
        self.include_cover_var = BooleanVar(value=self.config.get("include_cover", True))
        Checkbutton(cover_frame, text="生成封面页（使用文件夹名称作为标题）",
                    variable=self.include_cover_var).pack(anchor=W)


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

    def browse_input_dir(self):
        folder = filedialog.askdirectory(title="选择输入目录（包含故事子文件夹）", initialdir=self.input_dir_var.get())
        if folder:
            self.input_dir_var.set(folder)

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="选择输出 PDF 目录", initialdir=self.output_dir_var.get())
        if folder:
            self.output_dir_var.set(folder)

    def log_message(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def start_conversion(self):
        input_dir = Path(self.input_dir_var.get().strip())
        output_dir = Path(self.output_dir_var.get().strip())

        if not input_dir or not input_dir.exists():
            messagebox.showwarning("警告", "请输入有效的输入目录！")
            return
        if not output_dir:
            messagebox.showwarning("警告", "请指定输出目录！")
            return

        # 获取所有子目录（1 层）
        subdirs = [d for d in input_dir.iterdir() if d.is_dir()]
        if not subdirs:
            messagebox.showwarning("警告", "输入目录下没有子文件夹！")
            return

        # 保存配置
        current_config = {
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "include_cover": self.include_cover_var.get()
        }
        save_config(current_config)

        # 初始化状态
        self.total_count = len(subdirs)
        self.completed_count = 0
        self.status_var.set(f"准备转换 {self.total_count} 个故事...")
        self.log_message(f"开始转换 {self.total_count} 个故事到 PDF")

        # 重置事件
        global stop_event, pause_event
        stop_event.clear()
        pause_event.set()

        # 启动后台线程
        self.running = True
        self.start_btn.config(state=DISABLED)
        self.pause_btn.config(state=NORMAL)
        self.stop_btn.config(state=NORMAL)

        thread = threading.Thread(target=self.run_conversion, args=(subdirs, output_dir), daemon=True)
        thread.start()

    def run_conversion(self, subdirs, output_dir):
        for story_dir in subdirs:
            if stop_event.is_set():
                break

            # 检查暂停
            while not pause_event.is_set() and not stop_event.is_set():
                time.sleep(0.1)

            if stop_event.is_set():
                break

            success, msg = process_story_folder(story_dir, output_dir, self.include_cover_var.get())
            self.completed_count += 1
            prefix = "✅ 成功" if success else "❌ 失败"
            self.root.after(0, lambda m=f"{prefix}: {story_dir.name} | {msg}": self.log_message(m))
            self.root.after(0, lambda: self.status_var.set(f"进度: {self.completed_count}/{self.total_count}"))

        # 完成后自动结束
        self.root.after(0, self.finalize_conversion)

    def finalize_conversion(self):
        global stop_event
        stop_event.set()
        self.running = False
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)
        self.status_var.set("✅ 转换完成！")
        self.log_message("所有任务已完成。")
        messagebox.showinfo("完成", f"✅ 转换完成！共处理 {self.total_count} 个故事。")

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
        self.running = False
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

    # 检查 PIL 是否安装
    try:
        from PIL import Image
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 Pillow:\npip install Pillow")
        exit(1)

    root = Tk()
    app = ImagesToPdfGUI(root)
    root.mainloop()
