# add_text_to_images.pyw

import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk, colorchooser
from PIL import Image, ImageDraw, ImageFont
import threading

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "add_text_to_images"
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
    "text_position": "右下",
    "font_size": 25,
    "font_color": "#000000",
    "font_path": "msyh.ttc",  # 微软雅黑
    "opacity": 1.0,
    "auto_blank_area": False,
    "texts_per_file": {},  # {"1.jpg": "Hello", "2.png": ""}
}

# 支持的图片格式
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff'}

# 位置映射
POSITION_MAP = {
    "左上": (10, 10),
    "中上": ("center", 10),
    "右上": (-10, 10),
    "左中": (10, "center"),
    "居中": ("center", "center"),
    "右中": (-10, "center"),
    "左下": (10, -10),
    "中下": ("center", -10),
    "右下": (-20, -20),
}

# ==============================
# 工具函数：智能空白区域检测（简化版）
# ==============================
def find_blank_area(img, text_w, text_h, margin=20):
    """简单策略：从右下角开始扫描，找一个不包含太多非白像素的区域"""
    try:
        w, h = img.size
        # 转为灰度图
        gray = img.convert("L")
        pixels = gray.load()

        # 从右下角开始，步进扫描
        step = max(10, min(w, h) // 20)
        for y in range(h - text_h - margin, margin, -step):
            for x in range(w - text_w - margin, margin, -step):
                # 检查该区域是否“空白”（平均亮度 > 200）
                total = 0
                count = 0
                for dy in range(text_h):
                    for dx in range(text_w):
                        if x+dx < w and y+dy < h:
                            total += pixels[x+dx, y+dy]
                            count += 1
                if count > 0 and total / count > 200:  # 较亮区域视为“空白”
                    return (x, y)
        # 如果没找到，返回默认右下
        return (w - text_w - margin, h - text_h - margin)
    except:
        return (img.width - text_w - 20, img.height - text_h - 20)

# ==============================
# 核心处理函数
# ==============================
def process_image_with_text(image_path: Path, output_path: Path, text: str, config: dict):
    """给单张图片添加文案"""
    if not text.strip():
        return False, "文案为空，跳过"

    try:
        with Image.open(image_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # 准备绘图
            txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_layer)

            # 加载字体
            font_size = config.get("font_size", 25)
            font_path = config.get("font_path", "msyh.ttc")
            try:
                font = ImageFont.truetype(font_path, font_size)
            except:
                try:
                    font = ImageFont.truetype("simhei.ttf", font_size)
                except:
                    font = ImageFont.load_default()

            # 获取文本尺寸
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # 确定位置
            if config.get("auto_blank_area", False):
                pos = find_blank_area(img, text_w, text_h)
            else:
                pos_key = config.get("text_position", "右下")
                default_pos = POSITION_MAP.get(pos_key, (-10, -10))
                x_offset, y_offset = default_pos

                if x_offset == "center":
                    x = (img.width - text_w) // 2
                elif x_offset < 0:
                    x = img.width - text_w + x_offset
                else:
                    x = x_offset

                if y_offset == "center":
                    y = (img.height - text_h) // 2
                elif y_offset < 0:
                    y = img.height - text_h + y_offset
                else:
                    y = y_offset

                pos = (x, y)

            # 设置颜色和透明度
            color_hex = config.get("font_color", "#000000")
            opacity = float(config.get("opacity", 1.0))
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)
            a = int(255 * opacity)

            # 绘制文字
            draw.text(pos, text, fill=(r, g, b, a), font=font)

            # 合并图层
            combined = Image.alpha_composite(img, txt_layer)
            if combined.mode in ("RGBA", "P"):
                combined = combined.convert("RGB")
            combined.save(output_path, quality=95)
            return True, "成功添加文案"
    except Exception as e:
        logger.error(f"处理 {image_path.name} 失败: {e}")
        return False, str(e)

# ==============================
# GUI 主类
# ==============================
class AddTextToImagesGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🖼️ 批量给图片加文案")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        self.config = load_config()
        self.image_files = []
        self.text_entries = {}  # {filename: Entry}
        self.setup_ui()

    def setup_ui(self):
        # 输入目录
        dir_frame = LabelFrame(self.root, text="📂 图片目录", padx=10, pady=8)
        dir_frame.pack(fill=X, padx=10, pady=5)
        self.input_dir_var = StringVar(value=self.config["input_dir"])
        Entry(dir_frame, textvariable=self.input_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_frame, text="📁 浏览", command=self.browse_input_dir).pack(side=RIGHT, padx=(5, 0))

        # 刷新按钮
        Button(dir_frame, text="🔄 刷新图片列表", command=self.load_images).pack(side=RIGHT, padx=(5, 0))

        # 文案设置
        settings_frame = LabelFrame(self.root, text="⚙️ 文案设置", padx=10, pady=8)
        settings_frame.pack(fill=X, padx=10, pady=5)

        # 位置
        Label(settings_frame, text="位置:").grid(row=0, column=0, sticky=W)
        self.pos_var = StringVar(value=self.config.get("text_position", "右下"))
        pos_combo = ttk.Combobox(settings_frame, textvariable=self.pos_var, values=list(POSITION_MAP.keys()), width=8)
        pos_combo.grid(row=0, column=1, padx=5)

        # 字体大小
        Label(settings_frame, text="字体大小:").grid(row=0, column=2, sticky=W)
        self.size_var = StringVar(value=str(self.config.get("font_size", 25)))
        size_entry = Entry(settings_frame, textvariable=self.size_var, width=6)
        size_entry.grid(row=0, column=3, padx=5)

        # 颜色
        Label(settings_frame, text="颜色:").grid(row=0, column=4, sticky=W)
        self.color_var = StringVar(value=self.config.get("font_color", "#000000"))
        color_btn = Button(settings_frame, text="🎨 选择", command=self.choose_color, width=6)
        color_btn.grid(row=0, column=5, padx=5)
        color_preview = Label(settings_frame, bg=self.color_var.get(), width=2, relief=SUNKEN)
        color_preview.grid(row=0, column=6, padx=(0, 10))
        self.color_preview = color_preview

        # 透明度
        Label(settings_frame, text="透明度 (0~1):").grid(row=1, column=0, sticky=W, pady=(5,0))
        self.opacity_var = StringVar(value=str(self.config.get("opacity", 1.0)))
        opa_entry = Entry(settings_frame, textvariable=self.opacity_var, width=6)
        opa_entry.grid(row=1, column=1, padx=5, pady=(5,0))

        # 自动空白区域
        self.auto_blank_var = BooleanVar(value=self.config.get("auto_blank_area", False))
        auto_check = Checkbutton(settings_frame, text="自动放置在空白区域（避开主体）", variable=self.auto_blank_var)
        auto_check.grid(row=1, column=2, columnspan=3, sticky=W, pady=(5,0))

        # 图片与文案列表
        list_frame = LabelFrame(self.root, text="📝 为每张图片输入文案", padx=10, pady=8)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)

        canvas = Canvas(list_frame)
        scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=canvas.yview)
        scrollable_frame = Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.scrollable_frame = scrollable_frame
        self.canvas = canvas

        # 控制按钮
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        self.start_btn = Button(btn_frame, text="▶️ 开始添加文案", command=self.start_processing, bg="#4CAF50", fg="white", width=15)
        self.start_btn.pack()

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

        # 初始加载
        self.load_images()

    def browse_input_dir(self):
        folder = filedialog.askdirectory(title="选择图片目录", initialdir=self.input_dir_var.get())
        if folder:
            self.input_dir_var.set(folder)
            self.load_images()

    def choose_color(self):
        color_code = colorchooser.askcolor(title="选择字体颜色", color=self.color_var.get())[1]
        if color_code:
            self.color_var.set(color_code)
            self.color_preview.config(bg=color_code)

    def load_images(self):
        input_dir = Path(self.input_dir_var.get().strip())
        if not input_dir.exists():
            return

        # 清空旧列表
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.text_entries.clear()

        # 获取图片
        self.image_files = sorted([
            f for f in input_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ], key=lambda x: x.name)

        if not self.image_files:
            Label(self.scrollable_frame, text="⚠️ 该目录下无图片文件", fg="red").pack(pady=10)
            return

        # 创建输入框
        saved_texts = self.config.get("texts_per_file", {})
        for img_path in self.image_files:
            frame = Frame(self.scrollable_frame)
            frame.pack(fill=X, pady=2)
            Label(frame, text=img_path.name, width=30, anchor=W).pack(side=LEFT)
            text_var = StringVar(value=saved_texts.get(img_path.name, ""))
            entry = Entry(frame, textvariable=text_var, width=50)
            entry.pack(side=LEFT, fill=X, expand=True, padx=(10, 0))
            self.text_entries[img_path.name] = text_var

    def start_processing(self):
        input_dir = Path(self.input_dir_var.get().strip())
        if not input_dir.exists():
            messagebox.showwarning("警告", "请选择有效的图片目录！")
            return
        if not self.image_files:
            messagebox.showwarning("警告", "没有可处理的图片！")
            return

        # 收集配置
        try:
            font_size = int(self.size_var.get())
            opacity = float(self.opacity_var.get())
            if not (0 <= opacity <= 1):
                raise ValueError("透明度必须在 0~1 之间")
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数错误：{e}")
            return

        # 保存配置
        current_texts = {name: var.get() for name, var in self.text_entries.items()}
        current_config = {
            "input_dir": str(input_dir),
            "text_position": self.pos_var.get(),
            "font_size": font_size,
            "font_color": self.color_var.get(),
            "font_path": "msyh.ttc",
            "opacity": opacity,
            "auto_blank_area": self.auto_blank_var.get(),
            "texts_per_file": current_texts,
        }
        save_config(current_config)

        # 启动后台线程
        self.start_btn.config(state=DISABLED, text="🔄 处理中...")
        self.status_var.set("正在处理...")
        thread = threading.Thread(target=self.run_processing, args=(current_config,), daemon=True)
        thread.start()

    def run_processing(self, config):
        input_dir = Path(config["input_dir"])
        success_count = 0
        total = len(self.image_files)

        for i, img_path in enumerate(self.image_files, 1):
            text = config["texts_per_file"].get(img_path.name, "")
            if not text.strip():
                logger.info(f"跳过 {img_path.name}（无文案）")
                continue

            output_path = input_dir / f"{img_path.stem}_with_text{img_path.suffix}"
            success, msg = process_image_with_text(img_path, output_path, text, config)
            if success:
                success_count += 1
                logger.info(f"✅ {img_path.name} → {output_path.name}")
            else:
                logger.error(f"❌ {img_path.name}: {msg}")

        self.root.after(0, self.on_complete, success_count, total)

    def on_complete(self, success_count, total):
        self.start_btn.config(state=NORMAL, text="▶️ 开始添加文案")
        msg = f"处理完成！成功 {success_count}/{total} 张图片。输出文件已添加 '_with_text' 后缀。"
        self.status_var.set("✅ " + msg)
        messagebox.showinfo("完成", msg)

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

    # 检查依赖
    try:
        from PIL import Image
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 Pillow:\npip install Pillow")
        exit(1)

    root = Tk()
    app = AddTextToImagesGUI(root)
    root.mainloop()
