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
    "font_path": "msyh.ttc",
    "opacity": 1.0,
    "auto_blank_area": False,
    "use_blank_block": False,          # 新增：是否使用右下角空白块
    "blank_block_width_pct": 10,       # 宽度百分比
    "blank_block_height_pct": 15,      # 高度百分比
    "texts_per_file": {},
}

# 支持的图片格式
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff'}

# 位置映射（使用极小负数触发右/下对齐，int()后为0）
POSITION_MAP = {
    "左上": (0, 0),
    "中上": ("center", 0),
    "右上": (-0.1, 0),
    "左中": (0, "center"),
    "居中": ("center", "center"),
    "右中": (-0.1, "center"),
    "左下": (0, -0.1),
    "中下": ("center", -0.1),
    "右下": (-0.1, -0.1),
}

# ==============================
# 工具函数：智能空白区域检测（简化版）
# ==============================
def find_blank_area(img, text_w, text_h, margin=20):
    try:
        w, h = img.size
        gray = img.convert("L")
        pixels = gray.load()
        step = max(10, min(w, h) // 20)
        for y in range(h - text_h - margin, margin, -step):
            for x in range(w - text_w - margin, margin, -step):
                total = 0
                count = 0
                for dy in range(text_h):
                    for dx in range(text_w):
                        if x+dx < w and y+dy < h:
                            total += pixels[x+dx, y+dy]
                            count += 1
                if count > 0 and total / count > 200:
                    return (x, y)
        return (w - text_w - margin, h - text_h - margin)
    except:
        return (img.width - text_w - 20, img.height - text_h - 20)

# ==============================
# 自动换行文本工具
# ==============================
def wrap_text(draw, text, font, max_width):
    """将文本按最大宽度自动换行"""
    lines = []
    words = text.split(' ')
    current_line = ""
    for word in words:
        test_line = current_line + " " + word if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

# ==============================
# 核心处理函数
# ==============================
def process_image_with_text(image_path: Path, output_path: Path, text: str, config: dict):
    if not text.strip():
        return False, "文案为空，跳过"

    try:
        with Image.open(image_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")

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

            # 准备绘图层
            txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_layer)

            use_blank_block = config.get("use_blank_block", False)
            if use_blank_block:
                # === 使用右下角空白块 ===
                w, h = img.size
                block_w = int(w * config.get("blank_block_width_pct", 10) / 100)
                block_h = int(h * config.get("blank_block_height_pct", 15) / 100)

                # 计算文本所需尺寸（带换行）
                margin = 10
                max_text_width = block_w - 2 * margin
                lines = wrap_text(draw, text, font, max_text_width)
                line_height = font_size + 4
                text_total_h = len(lines) * line_height

                # 撑开高度（但不低于配置高度）
                actual_block_h = max(block_h, text_total_h + 2 * margin)
                actual_block_w = block_w

                # 确保不超出图片
                actual_block_w = min(actual_block_w, w)
                actual_block_h = min(actual_block_h, h)

                # 右下角坐标
                x0 = w - actual_block_w
                y0 = h - actual_block_h
                x1 = w
                y1 = h

                # 绘制半透明白色背景块
                alpha = int(255 * 0.7)  # 背景透明度
                draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255, alpha))

                # 绘制文字（居中或左对齐）
                text_y = y0 + margin
                for line in lines:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_x = x0 + margin  # 左对齐
                    # 或居中: text_x = x0 + (actual_block_w - text_w) // 2
                    draw.text((text_x, text_y), line, fill=(0, 0, 0, 255), font=font)
                    text_y += line_height

                pos = None  # 不再使用外部位置
            else:
                # === 原有逻辑：直接绘制文字 ===
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]

                if config.get("auto_blank_area", False):
                    pos = find_blank_area(img, text_w, text_h)
                else:
                    pos_key = config.get("text_position", "右下")
                    default_pos = POSITION_MAP.get(pos_key, (-0.1, -0.1))
                    x_offset, y_offset = default_pos

                    if x_offset == "center":
                        x = (img.width - text_w) // 2
                    elif isinstance(x_offset, (int, float)) and x_offset < 0:
                        x = img.width - text_w + int(x_offset)
                    else:
                        x = int(x_offset) if isinstance(x_offset, (int, float)) else 0

                    if y_offset == "center":
                        y = (img.height - text_h) // 2
                    elif isinstance(y_offset, (int, float)) and y_offset < 0:
                        y = img.height - text_h + int(y_offset)
                    else:
                        y = int(y_offset) if isinstance(y_offset, (int, float)) else 0

                    pos = (x, y)

                # 设置颜色和透明度
                color_hex = config.get("font_color", "#000000")
                opacity = float(config.get("opacity", 1.0))
                r = int(color_hex[1:3], 16)
                g = int(color_hex[3:5], 16)
                b = int(color_hex[5:7], 16)
                a = int(255 * opacity)
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
        self.root.geometry("850x650")
        self.root.resizable(True, True)

        self.config = load_config()
        self.image_files = []
        self.text_entries = {}
        self.setup_ui()

    def setup_ui(self):
        # 输入目录
        dir_frame = LabelFrame(self.root, text="📂 图片目录", padx=10, pady=8)
        dir_frame.pack(fill=X, padx=10, pady=5)
        self.input_dir_var = StringVar(value=self.config["input_dir"])
        Entry(dir_frame, textvariable=self.input_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_frame, text="📁 浏览", command=self.browse_input_dir).pack(side=RIGHT, padx=(5, 0))
        Button(dir_frame, text="🔄 刷新", command=self.load_images).pack(side=RIGHT, padx=(5, 0))

        # 文案设置
        settings_frame = LabelFrame(self.root, text="⚙️ 文案设置", padx=10, pady=8)
        settings_frame.pack(fill=X, padx=10, pady=5)

        row = 0
        # 位置 & 空白块开关
        Label(settings_frame, text="位置:").grid(row=row, column=0, sticky=W)
        self.pos_var = StringVar(value=self.config.get("text_position", "右下"))
        pos_combo = ttk.Combobox(settings_frame, textvariable=self.pos_var, values=list(POSITION_MAP.keys()), width=8)
        pos_combo.grid(row=row, column=1, padx=5)

        self.use_blank_var = BooleanVar(value=self.config.get("use_blank_block", False))
        blank_check = Checkbutton(settings_frame, text="在右下角添加空白区域显示文案", variable=self.use_blank_var, command=self.toggle_blank_settings)
        blank_check.grid(row=row, column=2, columnspan=3, sticky=W, padx=(10, 0))

        row += 1
        # 空白块尺寸（默认隐藏）
        self.blank_size_frame = Frame(settings_frame)
        self.blank_size_frame.grid(row=row, column=0, columnspan=6, sticky=W, pady=(5,0))
        Label(self.blank_size_frame, text="空白区宽(%):").pack(side=LEFT)
        self.blank_w_var = StringVar(value=str(self.config.get("blank_block_width_pct", 10)))
        Entry(self.blank_size_frame, textvariable=self.blank_w_var, width=5).pack(side=LEFT, padx=(5,0))
        Label(self.blank_size_frame, text="高(%):").pack(side=LEFT, padx=(10,0))
        self.blank_h_var = StringVar(value=str(self.config.get("blank_block_height_pct", 15)))
        Entry(self.blank_size_frame, textvariable=self.blank_h_var, width=5).pack(side=LEFT, padx=(5,0))

        self.toggle_blank_settings()  # 初始化显示状态

        row += 1
        # 字体大小、颜色、透明度
        Label(settings_frame, text="字体大小:").grid(row=row, column=0, sticky=W, pady=(5,0))
        self.size_var = StringVar(value=str(self.config.get("font_size", 25)))
        size_entry = Entry(settings_frame, textvariable=self.size_var, width=6)
        size_entry.grid(row=row, column=1, padx=5, pady=(5,0))

        Label(settings_frame, text="颜色:").grid(row=row, column=2, sticky=W, pady=(5,0))
        self.color_var = StringVar(value=self.config.get("font_color", "#000000"))
        color_btn = Button(settings_frame, text="🎨 选择", command=self.choose_color, width=6)
        color_btn.grid(row=row, column=3, padx=5, pady=(5,0))
        self.color_preview = Label(settings_frame, bg=self.color_var.get(), width=2, relief=SUNKEN)
        self.color_preview.grid(row=row, column=4, padx=(0, 10), pady=(5,0))

        Label(settings_frame, text="透明度 (0~1):").grid(row=row, column=5, sticky=W, pady=(5,0))
        self.opacity_var = StringVar(value=str(self.config.get("opacity", 1.0)))
        opa_entry = Entry(settings_frame, textvariable=self.opacity_var, width=6)
        opa_entry.grid(row=row, column=6, padx=5, pady=(5,0))

        row += 1
        # 自动空白区域
        self.auto_blank_var = BooleanVar(value=self.config.get("auto_blank_area", False))
        auto_check = Checkbutton(settings_frame, text="自动放置在空白区域（避开主体）", variable=self.auto_blank_var)
        auto_check.grid(row=row, column=0, columnspan=4, sticky=W, pady=(5,0))

        # 图片与文案列表（带滚轮）
        list_frame = LabelFrame(self.root, text="📝 为每张图片输入文案", padx=10, pady=8)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)

        # 使用 Canvas + Frame 实现滚动
        self.canvas = Canvas(list_frame)
        scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=self.canvas.yview)
        self.scrollable_frame = Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # 绑定鼠标滚轮
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind("<MouseWheel>", _on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        list_frame.bind("<MouseWheel>", _on_mousewheel)

        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 控制按钮
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        self.start_btn = Button(btn_frame, text="▶️ 开始添加文案", command=self.start_processing, bg="#4CAF50", fg="white", width=15)
        self.start_btn.pack()

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

        self.load_images()

    def toggle_blank_settings(self):
        if self.use_blank_var.get():
            self.blank_size_frame.grid()
        else:
            self.blank_size_frame.grid_remove()

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
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.text_entries.clear()

        if not input_dir.exists():
            return

        self.image_files = sorted([
            f for f in input_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ], key=lambda x: x.name)

        if not self.image_files:
            Label(self.scrollable_frame, text="⚠️ 该目录下无图片文件", fg="red").pack(pady=10)
            return

        saved_texts = self.config.get("texts_per_file", {})
        for img_path in self.image_files:
            frame = Frame(self.scrollable_frame)
            frame.pack(fill=X, pady=2)
            Label(frame, text=img_path.name, width=30, anchor=W).pack(side=LEFT)
            text_var = StringVar(value=saved_texts.get(img_path.name, ""))
            entry = Entry(frame, textvariable=text_var, width=60)
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

        try:
            font_size = int(self.size_var.get())
            opacity = float(self.opacity_var.get())
            if not (0 <= opacity <= 1):
                raise ValueError("透明度必须在 0~1 之间")
            if self.use_blank_var.get():
                w_pct = float(self.blank_w_var.get())
                h_pct = float(self.blank_h_var.get())
                if not (1 <= w_pct <= 100) or not (1 <= h_pct <= 100):
                    raise ValueError("空白区域宽高百分比应在 1~100 之间")
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数错误：{e}")
            return

        current_texts = {name: var.get() for name, var in self.text_entries.items()}
        current_config = {
            "input_dir": str(input_dir),
            "text_position": self.pos_var.get(),
            "font_size": font_size,
            "font_color": self.color_var.get(),
            "font_path": "msyh.ttc",
            "opacity": opacity,
            "auto_blank_area": self.auto_blank_var.get(),
            "use_blank_block": self.use_blank_var.get(),
            "blank_block_width_pct": float(self.blank_w_var.get()) if self.use_blank_var.get() else 10,
            "blank_block_height_pct": float(self.blank_h_var.get()) if self.use_blank_var.get() else 15,
            "texts_per_file": current_texts,
        }
        save_config(current_config)

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
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)
        except:
            pass

    try:
        from PIL import Image
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 Pillow:\npip install Pillow")
        exit(1)

    root = Tk()
    app = AddTextToImagesGUI(root)
    root.mainloop()
