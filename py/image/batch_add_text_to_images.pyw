# batch_add_text_to_images.pyw （含粘贴JSON+进度条+亮度调节+边距设置）
import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk, colorchooser
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import threading

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "batch_add_text_to_images"
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
    "font_size": 25,
    "font_color": "#000000",
    "bg_color": "#FFFFFF",
    "font_path": "msyh.ttc",
    "opacity": 1.0,
    "bottom_area_height": 150,
    "mode": "bottom",  # 'bottom' 或 'block'
    "blank_block_width_pct": 10,
    "blank_block_height_pct": 15,
    "texts_per_file": {},
    "adjust_brightness": False,  # ✅ 新增：是否调节亮度
    "brightness_level": "10%",   # ✅ 新增：亮度等级
    "text_margin_x": 30          # ✅ 新增：文案左右边距
}

# 支持的图片格式
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff'}

# ==============================
# 工具函数：按字符自动换行
# ==============================
def wrap_text(draw, text, font, max_width):
    lines = []
    current_line = ""
    for char in text:
        test_line = current_line + char
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]
        except:
            line_width = 0
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
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
            if img.mode != "RGB":
                img = img.convert("RGB")

            # ✅ 新增：调节亮度
            if config.get("adjust_brightness", False):
                brightness_map = {
                    "5%": 1.05,
                    "10%": 1.1,
                    "15%": 1.15,
                    "20%": 1.2,
                    "25%": 1.25,
                    "30%": 1.3
                }
                brightness_factor = brightness_map.get(config.get("brightness_level", "10%"), 1.1)
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(brightness_factor)

            orig_w, orig_h = img.size

            mode = config.get("mode", "bottom")

            # === 方案1：底部扩展区域 ===
            if mode == "bottom":
                new_h = orig_h + int(config.get("bottom_area_height", 150))
                new_img = Image.new("RGB", (orig_w, new_h), color=tuple(int(config["bg_color"].lstrip('#')[i:i+2], 16) for i in (0, 2, 4)))
                new_img.paste(img, (0, 0))

                draw = ImageDraw.Draw(new_img)
                font_size = config.get("font_size", 25)
                font_path = config.get("font_path", "msyh.ttc")
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except:
                    try:
                        font = ImageFont.truetype("simhei.ttf", font_size)
                    except:
                        font = ImageFont.load_default()

                color_hex = config.get("font_color", "#000000")
                r = int(color_hex[1:3], 16)
                g = int(color_hex[3:5], 16)
                b = int(color_hex[5:7], 16)

                # ✅ 修改：使用配置的左右边距
                margin_x = config.get("text_margin_x", 30)
                margin_y = 10
                max_text_width = orig_w - 2 * margin_x
                lines = wrap_text(draw, text, font, max_text_width)
                line_height = font_size + 6
                total_text_h = len(lines) * line_height
                start_y = orig_h + (int(config["bottom_area_height"]) - total_text_h) // 2
                y = max(start_y, orig_h + margin_y)

                for line in lines:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_w = bbox[2] - bbox[0]
                    # ✅ 修改：居中位置使用新的边距
                    x = (orig_w - text_w) // 2
                    if x < margin_x:
                        x = margin_x
                    draw.text((x, y), line, fill=(r, g, b), font=font)
                    y += line_height

                new_img.save(output_path, quality=95)
                return True, "成功添加底部文案"

            # === 方案2：右下角空白块 ===
            elif mode == "block":
                font_size = config.get("font_size", 25)
                font_path = config.get("font_path", "msyh.ttc")
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except:
                    try:
                        font = ImageFont.truetype("simhei.ttf", font_size)
                    except:
                        font = ImageFont.load_default()

                txt_layer = Image.new("RGBA", (orig_w, orig_h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(txt_layer)

                block_w = int(orig_w * config.get("blank_block_width_pct", 10) / 100)
                block_h = int(orig_h * config.get("blank_block_height_pct", 15) / 100)

                # ✅ 修改：使用配置的左右边距
                margin_x = config.get("text_margin_x", 30)
                margin_y = 10
                max_text_width = block_w - 2 * margin_x
                lines = wrap_text(draw, text, font, max_text_width)
                line_height = font_size + 4
                text_total_h = len(lines) * line_height
                actual_block_h = max(block_h, text_total_h + 2 * margin_y)
                actual_block_w = block_w

                actual_block_w = min(actual_block_w, orig_w)
                actual_block_h = min(actual_block_h, orig_h)

                x0 = orig_w - actual_block_w
                y0 = orig_h - actual_block_h

                bg_hex = config.get("bg_color", "#FFFFFF")
                br = int(bg_hex[1:3], 16)
                bg = int(bg_hex[3:5], 16)
                bb = int(bg_hex[5:7], 16)
                opacity = float(config.get("opacity", 1.0))
                alpha = int(255 * opacity)
                draw.rectangle([x0, y0, orig_w, orig_h], fill=(br, bg, bb, alpha))

                color_hex = config.get("font_color", "#000000")
                r = int(color_hex[1:3], 16)
                g = int(color_hex[3:5], 16)
                b = int(color_hex[5:7], 16)

                text_y = y0 + margin_y
                for line in lines:
                    # ✅ 修改：使用新的边距
                    draw.text((x0 + margin_x, text_y), line, fill=(r, g, b, 255), font=font)
                    text_y += line_height

                img_rgba = img.convert("RGBA")
                combined = Image.alpha_composite(img_rgba, txt_layer)
                if combined.mode != "RGB":
                    combined = combined.convert("RGB")
                combined.save(output_path, quality=95)
                return True, "成功添加右下角文案"

            else:
                return False, "未知模式"

    except Exception as e:
        logger.error(f"处理 {image_path.name} 失败: {e}")
        return False, str(e)

# ==============================
# GUI 主类
# ==============================
class BatchAddTextGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🖼️ 批量给图片加文案")
        self.root.geometry("850x800")  # 高度+80适配新组件
        self.root.resizable(True, True)

        self.config = self.load_config()
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

        # 模式选择（使用 Radiobutton）
        mode_frame = LabelFrame(self.root, text="🎨 显示模式", padx=10, pady=8)
        mode_frame.pack(fill=X, padx=10, pady=5)

        self.mode_var = StringVar(value=self.config.get("mode", "bottom"))
        Radiobutton(mode_frame, text="在图片下方扩展区域显示文案", variable=self.mode_var, value="bottom", command=self.toggle_mode).pack(side=LEFT)
        Radiobutton(mode_frame, text="在右下角叠加空白块显示文案", variable=self.mode_var, value="block", command=self.toggle_mode).pack(side=LEFT, padx=(20, 0))

        # ✅ 新增：亮度调节选项
        brightness_frame = LabelFrame(self.root, text="☀️ 亮度调节", padx=10, pady=8)
        brightness_frame.pack(fill=X, padx=10, pady=5)

        self.adjust_brightness_var = BooleanVar(value=self.config.get("adjust_brightness", False))
        self.brightness_check = Checkbutton(brightness_frame, text="开启亮度调节", variable=self.adjust_brightness_var)
        self.brightness_check.pack(side=LEFT)

        Label(brightness_frame, text="亮度等级:").pack(side=LEFT, padx=(10, 0))
        self.brightness_level_var = StringVar(value=self.config.get("brightness_level", "10%"))
        brightness_combo = ttk.Combobox(brightness_frame, textvariable=self.brightness_level_var, values=["5%", "10%", "15%", "20%", "25%", "30%"], state="readonly", width=8)
        brightness_combo.pack(side=LEFT, padx=(5, 0))

        # 字体设置（始终显示）
        font_frame = LabelFrame(self.root, text="🔤 字体设置", padx=10, pady=8)
        font_frame.pack(fill=X, padx=10, pady=5)

        row = 0
        Label(font_frame, text="字体大小:").grid(row=row, column=0, sticky=W)
        self.size_var = StringVar(value=str(self.config.get("font_size", 25)))
        Entry(font_frame, textvariable=self.size_var, width=6).grid(row=row, column=1, padx=5)

        Label(font_frame, text="字体颜色:").grid(row=row, column=2, sticky=W, padx=(10,0))
        self.color_var = StringVar(value=self.config.get("font_color", "#000000"))
        Button(font_frame, text="🎨 选择", command=self.choose_font_color, width=6).grid(row=row, column=3, padx=5)
        self.font_color_preview = Label(font_frame, bg=self.color_var.get(), width=2, relief=SUNKEN)
        self.font_color_preview.grid(row=row, column=4, padx=(0,10))

        Label(font_frame, text="背景颜色:").grid(row=row, column=5, sticky=W, padx=(10,0))
        self.bg_color_var = StringVar(value=self.config.get("bg_color", "#FFFFFF"))
        Button(font_frame, text="🎨 选择", command=self.choose_bg_color, width=6).grid(row=row, column=6, padx=5)
        self.bg_color_preview = Label(font_frame, bg=self.bg_color_var.get(), width=2, relief=SUNKEN)
        self.bg_color_preview.grid(row=row, column=7, padx=(0,10))

        row += 1
        Label(font_frame, text="透明度(0~1):").grid(row=row, column=0, sticky=W, pady=(5,0))
        self.opacity_var = StringVar(value=str(self.config.get("opacity", 1.0)))
        Entry(font_frame, textvariable=self.opacity_var, width=6).grid(row=row, column=1, padx=5, pady=(5,0))

        Label(font_frame, text="左右边距(px):").grid(row=row, column=2, sticky=W, padx=(10,0), pady=(5,0))
        self.margin_x_var = StringVar(value=str(self.config.get("text_margin_x", 30)))  # ✅ 新增：边距输入
        Entry(font_frame, textvariable=self.margin_x_var, width=6).grid(row=row, column=3, padx=5, pady=(5,0))

        Label(font_frame, text="字体文件:").grid(row=row, column=4, sticky=W, padx=(10,0), pady=(5,0))
        self.font_path_var = StringVar(value=self.config.get("font_path", "msyh.ttc"))
        Entry(font_frame, textvariable=self.font_path_var, width=20).grid(row=row, column=5, columnspan=2, padx=5, pady=(5,0))

        # 底部区域设置（初始状态根据 mode 决定）
        self.bottom_frame = LabelFrame(self.root, text="🔽 底部扩展区域设置", padx=10, pady=8)

        Label(self.bottom_frame, text="高度(px):").grid(row=0, column=0, sticky=W)
        self.bottom_h_var = StringVar(value=str(self.config.get("bottom_area_height", 150)))
        Entry(self.bottom_frame, textvariable=self.bottom_h_var, width=8).grid(row=0, column=1, padx=5)

        # 右下角空白块设置（放在字体设置之后）
        self.block_frame = LabelFrame(self.root, text="🔷 右下角空白块设置", padx=10, pady=8)

        Label(self.block_frame, text="宽度(%):").grid(row=0, column=0, sticky=W)
        self.blank_w_var = StringVar(value=str(self.config.get("blank_block_width_pct", 10)))
        Entry(self.block_frame, textvariable=self.blank_w_var, width=6).grid(row=0, column=1, padx=5)

        Label(self.block_frame, text="高度(%):").grid(row=0, column=2, sticky=W, padx=(10,0))
        self.blank_h_var = StringVar(value=str(self.config.get("blank_block_height_pct", 15)))
        Entry(self.block_frame, textvariable=self.blank_h_var, width=6).grid(row=0, column=3, padx=5)

        # 初始显示正确面板
        self.toggle_mode()

        # 图片与文案列表
        list_frame = LabelFrame(self.root, text="📝 为每张图片输入文案", padx=10, pady=8)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)

        self.canvas = Canvas(list_frame)
        scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=self.canvas.yview)
        self.scrollable_frame = Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # 绑定鼠标滚轮（Windows）
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 控制按钮
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        self.start_btn = Button(btn_frame, text="▶️ 开始处理", command=self.start_processing, bg="#4CAF50", fg="white", width=15)
        self.start_btn.pack(side=LEFT, padx=5)

        # ✅ 新增：粘贴JSON按钮
        Button(btn_frame, text="📋 粘贴JSON", command=self.paste_json_texts, bg="#2196F3", fg="white", width=12).pack(side=LEFT, padx=5)

        # ✅ 新增：进度条
        self.progress_var = DoubleVar()
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100, length=400)
        self.progress_bar.pack(pady=5)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

        self.load_images()

    def toggle_mode(self):
        mode = self.mode_var.get()
        if mode == "bottom":
            self.bottom_frame.pack(fill=X, padx=10, pady=5)
            self.block_frame.pack_forget()
        else:
            self.bottom_frame.pack_forget()
            self.block_frame.pack(fill=X, padx=10, pady=5)

    def browse_input_dir(self):
        folder = filedialog.askdirectory(title="选择图片目录", initialdir=self.input_dir_var.get())
        if folder:
            self.input_dir_var.set(folder)
            self.load_images()

    def choose_font_color(self):
        color_code = colorchooser.askcolor(title="选择字体颜色", color=self.color_var.get())[1]
        if color_code:
            self.color_var.set(color_code)
            self.font_color_preview.config(bg=color_code)

    def choose_bg_color(self):
        color_code = colorchooser.askcolor(title="选择背景颜色", color=self.bg_color_var.get())[1]
        if color_code:
            self.bg_color_var.set(color_code)
            self.bg_color_preview.config(bg=color_code)

    def paste_json_texts(self):
        """粘贴JSON文本并解析到各图片"""
        try:
            clipboard = self.root.clipboard_get()
            if not clipboard.strip():
                messagebox.showwarning("警告", "剪贴板为空！")
                return

            # 解析JSON
            texts_dict = json.loads(clipboard)
            if not isinstance(texts_dict, dict):
                raise ValueError("JSON格式错误：根对象必须是字典")

            # 更新输入框
            updated_count = 0
            for img_name, text in texts_dict.items():
                if img_name in self.text_entries:
                    self.text_entries[img_name].set(str(text))
                    updated_count += 1

            messagebox.showinfo("成功", f"已解析并更新 {updated_count} 个文案！")
            self.status_var.set(f"✅ 已粘贴JSON，更新 {updated_count} 个文案")
        except json.JSONDecodeError:
            messagebox.showerror("错误", "JSON格式无效！")
        except Exception as e:
            messagebox.showerror("错误", f"解析失败：{str(e)}")

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
            text_margin_x = int(self.margin_x_var.get())  # ✅ 新增：获取边距值
            if not (0 <= opacity <= 1):
                raise ValueError("透明度必须在 0~1 之间")
            if text_margin_x < 0:
                raise ValueError("左右边距不能为负数")

            mode = self.mode_var.get()
            if mode == "bottom":
                bottom_h = int(self.bottom_h_var.get())
                if bottom_h < 10:
                    raise ValueError("底部高度至少10px")
            else:
                w_pct = float(self.blank_w_var.get())
                h_pct = float(self.blank_h_var.get())
                if not (1 <= w_pct <= 100) or not (1 <= h_pct <= 100):
                    raise ValueError("空白块宽高百分比应在1~100之间")
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数错误：{e}")
            return

        current_texts = {name: var.get() for name, var in self.text_entries.items()}
        current_config = {
            "input_dir": str(input_dir),
            "font_size": font_size,
            "font_color": self.color_var.get(),
            "bg_color": self.bg_color_var.get(),
            "font_path": self.font_path_var.get(),
            "opacity": opacity,
            "bottom_area_height": int(self.bottom_h_var.get()),
            "mode": mode,
            "blank_block_width_pct": float(self.blank_w_var.get()),
            "blank_block_height_pct": float(self.blank_h_var.get()),
            "texts_per_file": current_texts,
            "adjust_brightness": self.adjust_brightness_var.get(),  # ✅ 保存亮度设置
            "brightness_level": self.brightness_level_var.get(),   # ✅ 保存亮度等级
            "text_margin_x": text_margin_x                         # ✅ 保存边距设置
        }
        self.save_config(current_config)

        self.start_btn.config(state=DISABLED, text="🔄 处理中...")
        self.progress_var.set(0)
        self.status_var.set("正在处理...")
        thread = threading.Thread(target=self.run_processing, args=(current_config,), daemon=True)
        thread.start()

    def run_processing(self, config):
        input_dir = Path(config["input_dir"])
        success_count = 0
        total = len(self.image_files)

        # 只处理有文案的图片
        images_with_text = [
            img_path for img_path in self.image_files
            if config["texts_per_file"].get(img_path.name, "").strip()
        ]

        for i, img_path in enumerate(images_with_text, 1):
            text = config["texts_per_file"].get(img_path.name, "")
            if not text.strip():
                logger.info(f"跳过 {img_path.name}（无文案）")
                continue

            output_path = input_dir / f"{img_path.stem}_with_text{img_path.suffix}"
            success, msg = process_image_with_text(img_path, output_path, text, config)
            if success:
                success_count += 1
                logger.info(f"✅ {img_path.name} → {output_path.name}")

            # 更新进度
            progress = (i / len(images_with_text)) * 100
            self.root.after(0, lambda p=progress: self.progress_var.set(p))
            self.root.after(0, lambda s=f"正在处理 ({i}/{len(images_with_text)})...": self.status_var.set(s))

        self.root.after(0, self.on_complete, success_count, len(images_with_text))

    def on_complete(self, success_count, total):
        self.start_btn.config(state=NORMAL, text="▶️ 开始处理")
        self.progress_var.set(100)
        msg = f"处理完成！成功 {success_count}/{total} 张图片。输出文件已添加 '_with_text' 后缀。"
        self.status_var.set("✅ " + msg)
        messagebox.showinfo("完成", msg)

    def load_config(self):
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

    def save_config(self, config):
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
    # 尝试加载 DB_CONFIG（即使不用也按规范引入）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_cfg = json.load(f)
        except Exception as e:
            logger.warning(f"DB_CONFIG 加载失败: {e}")

    try:
        from PIL import Image
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 Pillow:\npip install Pillow")
        exit(1)

    root = Tk()
    app = BatchAddTextGUI(root)
    root.mainloop()
