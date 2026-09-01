# batch_add_text_to_images.pyw （含绘本脚本JSON匹配+粘贴JSON+进度条+亮度调节+边距设置+测试预览+Toast通知）
import os
import json
import random
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

# 绘本脚本 JSON 所在目录（默认取工作区下的 “AI Work Space/AI绘本脚本”）
DEFAULT_SCRIPT_JSON_DIR = SCRIPT_DIR.parent.parent / "AI Work Space" / "AI绘本脚本"
# 分镜脚本中剧情描述的字段名
PLOT_KEY = "plotContent"

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
    "output_dir": "",  # ✅ 新增：输出目录
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
    "text_margin_x": 30,         # ✅ 新增：文案左右边距
    "script_json_dir": str(DEFAULT_SCRIPT_JSON_DIR),  # ✅ 新增：绘本脚本 JSON 目录
    "script_json_file": "",                            # ✅ 新增：上次选中的脚本 JSON 文件名
    "bottom_height_mode": "auto",   # 'auto' 自动计算16:9 / 'manual' 手动输入
    "force_169": False,             # 手动模式下是否强制输出16:9画布
    "canvas_bg_color": "#000000"    # 强制16:9画布背景色，默认黑色
}

# 支持的图片格式
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff'}

# 测试预览（随机抽样）相关配置
TEST_PREFIX = "TEST_"
TEST_SAMPLE_COUNT = 5
TEST_SAMPLE_TEXTS = [
    "示例文案：这是一段用于查看排版效果的测试文字",
    "预览效果：可调节字体大小、颜色和边距后再试一次",
    "测试文案：底部扩展区域的高度是否合适",
    "效果预览：右下角空白块与透明度检查",
    "示例文字：亮度调节后的显示效果",
]


def is_test_image(name: str) -> bool:
    """判断文件名是否为测试预览生成的图片"""
    return name.startswith(TEST_PREFIX)


def clean_test_images(output_dir: Path) -> int:
    """清理输出目录下的测试预览图片，返回删除数量"""
    deleted = 0
    try:
        for f in output_dir.iterdir():
            if f.is_file() and is_test_image(f.name) and f.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    f.unlink()
                    deleted += 1
                    logger.info(f"已清理测试图片 {f.name}")
                except Exception as e:
                    logger.error(f"清理测试图片 {f.name} 失败: {e}")
    except Exception as e:
        logger.error(f"清理测试图片失败: {e}")
    return deleted


def list_script_json_files(script_dir: Path) -> list:
    """列出绘本脚本目录下的所有 JSON 文件名（按名称排序）"""
    try:
        return sorted(
            [f.name for f in script_dir.iterdir()
             if f.is_file() and f.suffix.lower() == '.json'],
            key=lambda x: x
        )
    except Exception as e:
        logger.error(f"读取脚本目录 {script_dir} 失败: {e}")
        return []


def parse_plot_contents(json_path: Path) -> list:
    """解析分镜脚本 JSON，按顺序返回剧情描述（plotContent）列表"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON 根节点必须是数组")
    plots = []
    for idx, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx} 项不是对象")
        plots.append(str(item.get(PLOT_KEY, "") or "").strip())
    return plots

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
                height_mode = config.get("bottom_height_mode", "auto")
                force_169 = config.get("force_169", False) and height_mode == "manual"

                if height_mode == "auto" or not force_169:
                    # --- 自动计算 / 手动输入(非强制16:9) ---
                    if height_mode == "auto":
                        # 根据原图宽度动态计算底部扩展高度，使输出图片达到 16:9
                        target_output_h = int(orig_w * 9 / 16)
                        bottom_area_height = target_output_h - orig_h
                        min_text_area = 60  # 最小文本区域高度（至少容纳一行文字）
                        if bottom_area_height <= 0:
                            logger.warning(f"{image_path.name}: 原图比例已≥16:9({orig_w}x{orig_h})，无扩展区域，使用最小高度{min_text_area}px")
                            bottom_area_height = min_text_area
                        elif bottom_area_height < min_text_area:
                            logger.info(f"{image_path.name}: 计算的扩展区域{bottom_area_height}px过小，使用最小高度{min_text_area}px")
                            bottom_area_height = min_text_area
                        else:
                            logger.info(f"{image_path.name}: 动态计算扩展区域高度={bottom_area_height}px (原图{orig_w}x{orig_h}, 目标输出{orig_w}x{target_output_h})")
                    else:
                        bottom_area_height = int(config.get("bottom_area_height", 150))

                    new_h = orig_h + bottom_area_height
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

                    margin_x = config.get("text_margin_x", 30)
                    margin_y = 50
                    max_text_width = orig_w - 2 * margin_x
                    lines = wrap_text(draw, text, font, max_text_width)
                    line_height = font_size + 6
                    total_text_h = len(lines) * line_height
                    start_y = orig_h + (bottom_area_height - total_text_h) // 2
                    y = max(start_y, orig_h + margin_y)

                    for line in lines:
                        bbox = draw.textbbox((0, 0), line, font=font)
                        text_w = bbox[2] - bbox[0]
                        x = (orig_w - text_w) // 2
                        if x < margin_x:
                            x = margin_x
                        draw.text((x, y), line, fill=(r, g, b), font=font)
                        y += line_height

                    new_img.save(output_path, quality=95)
                    return True, "成功添加底部文案"

                else:
                    # --- 手动输入 + 强制16:9画布模式 ---
                    canvas_w = orig_w
                    canvas_h = int(orig_w * 9 / 16)

                    # 画布背景色
                    canvas_bg_hex = config.get("canvas_bg_color", "#000000")
                    canvas_bg_r = int(canvas_bg_hex[1:3], 16)
                    canvas_bg_g = int(canvas_bg_hex[3:5], 16)
                    canvas_bg_b = int(canvas_bg_hex[5:7], 16)

                    # 字体设置
                    font_size = config.get("font_size", 25)
                    font_path = config.get("font_path", "msyh.ttc")
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                    except:
                        try:
                            font = ImageFont.truetype("simhei.ttf", font_size)
                        except:
                            font = ImageFont.load_default()

                    # 计算文案所需高度
                    margin_x = config.get("text_margin_x", 30)
                    temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
                    max_text_width = canvas_w - 2 * margin_x
                    lines = wrap_text(temp_draw, text, font, max_text_width)
                    line_height = font_size + 6
                    text_total_h = len(lines) * line_height
                    text_padding = 20
                    text_area_h = text_total_h + text_padding * 2

                    # 在可用区域内等比缩放原图，最大化显示
                    available_h = max(canvas_h - text_area_h, 10)
                    scale = min(canvas_w / orig_w, available_h / orig_h)
                    scaled_w = int(orig_w * scale)
                    scaled_h = int(orig_h * scale)

                    logger.info(f"{image_path.name}: 强制16:9画布 {canvas_w}x{canvas_h}, 图片缩放{scale:.2f} → {scaled_w}x{scaled_h}, 文案区域{text_area_h}px")

                    # 创建画布
                    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(canvas_bg_r, canvas_bg_g, canvas_bg_b))

                    # 原图居中放置在画布上方区域
                    img_resized = img.resize((scaled_w, scaled_h), Image.LANCZOS)
                    img_x = (canvas_w - scaled_w) // 2
                    img_y = (available_h - scaled_h) // 2
                    canvas.paste(img_resized, (img_x, img_y))

                    # 在图片下方绘制文案
                    draw = ImageDraw.Draw(canvas)
                    color_hex = config.get("font_color", "#000000")
                    fr = int(color_hex[1:3], 16)
                    fg = int(color_hex[3:5], 16)
                    fb = int(color_hex[5:7], 16)

                    text_y_start = available_h + text_padding
                    for line in lines:
                        bbox = draw.textbbox((0, 0), line, font=font)
                        text_w = bbox[2] - bbox[0]
                        x = (canvas_w - text_w) // 2
                        if x < margin_x:
                            x = margin_x
                        draw.text((x, text_y_start), line, fill=(fr, fg, fb), font=font)
                        text_y_start += line_height

                    canvas.save(output_path, quality=95)
                    return True, "成功添加底部文案(强制16:9画布)"

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

        # ✅ 新增：启动后直接最大化显示
        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception as e:
                logger.warning(f"窗口最大化失败: {e}")

    def setup_ui(self):
        # 创建标签页容器
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=BOTH, expand=True, padx=5, pady=5)

        # ==================== Tab 1: 文件目录 ====================
        tab_dir = Frame(notebook)
        notebook.add(tab_dir, text="  📂 文件目录  ")

        # 输入目录
        dir_frame = LabelFrame(tab_dir, text="📂 图片目录", padx=10, pady=8)
        dir_frame.pack(fill=X, padx=10, pady=5)
        self.input_dir_var = StringVar(value=self.config["input_dir"])
        Entry(dir_frame, textvariable=self.input_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_frame, text="📁 浏览", command=self.browse_input_dir).pack(side=RIGHT, padx=(5, 0))
        Button(dir_frame, text="🔄 刷新", command=self.load_images).pack(side=RIGHT, padx=(5, 0))

        # ✅ 新增：输出目录
        output_dir_frame = LabelFrame(tab_dir, text="💾 输出目录", padx=10, pady=8)
        output_dir_frame.pack(fill=X, padx=10, pady=5)
        self.output_dir_var = StringVar(value=self.config.get("output_dir", ""))
        Entry(output_dir_frame, textvariable=self.output_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(output_dir_frame, text="📁 选择目录", command=self.browse_output_dir).pack(side=RIGHT, padx=(5, 0))

        # ==================== Tab 2: 配置 ====================
        tab_config = Frame(notebook)
        notebook.add(tab_config, text="  ⚙️ 配置  ")

        # 配置页可滚动容器
        config_canvas = Canvas(tab_config, highlightthickness=0)
        config_scrollbar = Scrollbar(tab_config, orient=VERTICAL, command=config_canvas.yview)
        self.config_scrollable = Frame(config_canvas)
        self.config_scrollable.bind("<Configure>", lambda e: config_canvas.configure(scrollregion=config_canvas.bbox("all")))
        config_canvas.create_window((0, 0), window=self.config_scrollable, anchor="nw")
        config_canvas.configure(yscrollcommand=config_scrollbar.set)
        config_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        config_scrollbar.pack(side=RIGHT, fill=Y)

        def _on_config_mousewheel(event):
            config_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        config_canvas.bind("<MouseWheel>", _on_config_mousewheel)
        self.config_scrollable.bind("<MouseWheel>", _on_config_mousewheel)

        # ✅ 新增：绘本脚本 JSON（自动匹配剧情文案）
        script_frame = LabelFrame(tab_dir, text="📜 绘本脚本 JSON（按文件名顺序匹配剧情描述）", padx=10, pady=8)
        script_frame.pack(fill=X, padx=10, pady=5)

        dir_row = Frame(script_frame)
        dir_row.pack(fill=X)
        self.script_dir_var = StringVar(value=self.config.get("script_json_dir", str(DEFAULT_SCRIPT_JSON_DIR)))
        Entry(dir_row, textvariable=self.script_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_row, text="📁 浏览", command=self.browse_script_dir).pack(side=RIGHT, padx=(5, 0))
        Button(dir_row, text="🔄 刷新", command=self.refresh_script_json_list).pack(side=RIGHT, padx=(5, 0))

        file_row = Frame(script_frame)
        file_row.pack(fill=X, pady=(6, 0))
        Label(file_row, text="脚本文件:").pack(side=LEFT)
        self.json_file_var = StringVar(value=self.config.get("script_json_file", ""))
        self.json_combo = ttk.Combobox(file_row, textvariable=self.json_file_var, state="readonly", width=50, values=[])
        self.json_combo.pack(side=LEFT, padx=(5, 0))
        self.json_combo.bind("<<ComboboxSelected>>", self.on_script_json_selected)
        Button(file_row, text="📥 匹配文案", command=self.apply_script_json, bg="#2196F3", fg="white", width=12).pack(side=LEFT, padx=(10, 0))
        self.json_count_label = Label(file_row, text="", fg="gray")
        self.json_count_label.pack(side=LEFT, padx=(10, 0))

        # 模式选择（使用 Radiobutton）
        mode_frame = LabelFrame(self.config_scrollable, text="🎨 显示模式", padx=10, pady=8)
        mode_frame.pack(fill=X, padx=10, pady=5)

        self.mode_var = StringVar(value=self.config.get("mode", "bottom"))
        Radiobutton(mode_frame, text="在图片下方扩展区域显示文案", variable=self.mode_var, value="bottom", command=self.toggle_mode).pack(side=LEFT)
        Radiobutton(mode_frame, text="在右下角叠加空白块显示文案", variable=self.mode_var, value="block", command=self.toggle_mode).pack(side=LEFT, padx=(20, 0))

        # ✅ 新增：亮度调节选项
        brightness_frame = LabelFrame(self.config_scrollable, text="☀️ 亮度调节", padx=10, pady=8)
        brightness_frame.pack(fill=X, padx=10, pady=5)

        self.adjust_brightness_var = BooleanVar(value=self.config.get("adjust_brightness", False))
        self.brightness_check = Checkbutton(brightness_frame, text="开启亮度调节", variable=self.adjust_brightness_var)
        self.brightness_check.pack(side=LEFT)

        Label(brightness_frame, text="亮度等级:").pack(side=LEFT, padx=(10, 0))
        self.brightness_level_var = StringVar(value=self.config.get("brightness_level", "10%"))
        brightness_combo = ttk.Combobox(brightness_frame, textvariable=self.brightness_level_var, values=["5%", "10%", "15%", "20%", "25%", "30%"], state="readonly", width=8)
        brightness_combo.pack(side=LEFT, padx=(5, 0))

        # 字体设置（始终显示）
        font_frame = LabelFrame(self.config_scrollable, text="🔤 字体设置", padx=10, pady=8)
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
        self.bottom_frame = LabelFrame(self.config_scrollable, text="🔽 底部扩展区域设置", padx=10, pady=8)
        self.bottom_frame.pack(fill=X, padx=10, pady=5)

        # 高度增加方式：自动计算 / 手动输入
        self.bottom_height_mode_var = StringVar(value=self.config.get("bottom_height_mode", "auto"))
        height_mode_row = Frame(self.bottom_frame)
        height_mode_row.pack(fill=X)
        Label(height_mode_row, text="高度方式:").pack(side=LEFT)
        Radiobutton(height_mode_row, text="自动计算(输出16:9)", variable=self.bottom_height_mode_var,
                    value="auto", command=self.toggle_bottom_height_mode).pack(side=LEFT, padx=(5, 0))
        Radiobutton(height_mode_row, text="手动输入", variable=self.bottom_height_mode_var,
                    value="manual", command=self.toggle_bottom_height_mode).pack(side=LEFT, padx=(10, 0))

        # 自动计算提示（auto 模式时显示）
        self.bottom_auto_frame = Frame(self.bottom_frame)
        Label(self.bottom_auto_frame, text="高度根据原图宽度自动计算，输出比例为16:9", fg="gray").pack(anchor=W)

        # 手动输入区域（manual 模式时显示）
        self.bottom_manual_frame = Frame(self.bottom_frame)
        manual_row = Frame(self.bottom_manual_frame)
        manual_row.pack(fill=X)
        Label(manual_row, text="高度(px):").pack(side=LEFT)
        self.bottom_h_var = StringVar(value=str(self.config.get("bottom_area_height", 150)))
        Entry(manual_row, textvariable=self.bottom_h_var, width=8).pack(side=LEFT, padx=5)

        self.force_169_var = BooleanVar(value=self.config.get("force_169", False))
        Checkbutton(self.bottom_manual_frame, text="强制输出16:9(画布模式)",
                    variable=self.force_169_var, command=self.toggle_force_169
                    ).pack(anchor=W, pady=(5, 0))

        # 画布背景色（强制16:9时显示）
        self.canvas_bg_frame = Frame(self.bottom_manual_frame)
        Label(self.canvas_bg_frame, text="画布背景色:").pack(side=LEFT)
        self.canvas_bg_color_var = StringVar(value=self.config.get("canvas_bg_color", "#000000"))
        Button(self.canvas_bg_frame, text="🎨 选择", command=self.choose_canvas_bg_color, width=6
               ).pack(side=LEFT, padx=5)
        self.canvas_bg_preview = Label(self.canvas_bg_frame, bg=self.canvas_bg_color_var.get(),
                                       width=2, relief=SUNKEN)
        self.canvas_bg_preview.pack(side=LEFT, padx=(0, 5))

        # 右下角空白块设置（放在字体设置之后）
        self.block_frame = LabelFrame(self.config_scrollable, text="🔷 右下角空白块设置", padx=10, pady=8)
        self.block_frame.pack(fill=X, padx=10, pady=5)

        Label(self.block_frame, text="宽度(%):").grid(row=0, column=0, sticky=W)
        self.blank_w_var = StringVar(value=str(self.config.get("blank_block_width_pct", 10)))
        Entry(self.block_frame, textvariable=self.blank_w_var, width=6).grid(row=0, column=1, padx=5)

        Label(self.block_frame, text="高度(%):").grid(row=0, column=2, sticky=W, padx=(10,0))
        self.blank_h_var = StringVar(value=str(self.config.get("blank_block_height_pct", 15)))
        Entry(self.block_frame, textvariable=self.blank_h_var, width=6).grid(row=0, column=3, padx=5)

        # 初始显示正确面板
        self.toggle_mode()

        # ==================== Tab 3: 图片文案 ====================
        tab_images = Frame(notebook)
        notebook.add(tab_images, text="  📝 图片文案  ")

        # 图片与文案列表
        list_frame = LabelFrame(tab_images, text="📝 为每张图片输入文案", padx=10, pady=8)
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

        # 绑定鼠标滚轮（仅图片列表标签页内）
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind("<MouseWheel>", _on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", _on_mousewheel)

        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 控制按钮
        btn_frame = Frame(tab_images)
        btn_frame.pack(pady=5)
        self.start_btn = Button(btn_frame, text="▶️ 开始处理", command=self.start_processing, bg="#4CAF50", fg="white", width=15)
        self.start_btn.pack(side=LEFT, padx=5)

        self.test_btn = Button(btn_frame, text=f"🧪 测试效果({TEST_SAMPLE_COUNT}张)", command=self.start_test, bg="#FF9800", fg="white", width=15)
        self.test_btn.pack(side=LEFT, padx=5)

        Button(btn_frame, text="📋 粘贴JSON", command=self.paste_json_texts, bg="#2196F3", fg="white", width=12).pack(side=LEFT, padx=5)

        # 进度条
        self.progress_var = DoubleVar()
        self.progress_bar = ttk.Progressbar(tab_images, variable=self.progress_var, maximum=100, length=400)
        self.progress_bar.pack(pady=5)

        # 状态栏（全局，不在标签页内）
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

        self.load_images()
        self.refresh_script_json_list()

    def _show_toast(self, title, message, level="info", duration_ms=3500):
        """右下角 Toast 通知，duration_ms 毫秒后自动消失"""
        try:
            toast = Toplevel(self.root)
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

            header = Frame(toast, bg=bg)
            header.pack(fill=X, padx=10, pady=8)
            Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                  fg=fg, bg=bg).pack(side=LEFT)
            close_btn = Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())

            Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                  fg="#333", bg=bg, wraplength=340, justify=LEFT).pack(padx=12, pady=(4, 10), anchor=W)

            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            sx = toast.winfo_screenwidth()
            sy = toast.winfo_screenheight()
            toast.geometry(f"+{sx - w - 20}+{sy - h - 60}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    def toggle_mode(self):
        mode = self.mode_var.get()
        if mode == "bottom":
            self.bottom_frame.pack(fill=X, padx=10, pady=5)
            self.block_frame.pack_forget()
            self.toggle_bottom_height_mode()
        else:
            self.bottom_frame.pack_forget()
            self.block_frame.pack(fill=X, padx=10, pady=5)

    def toggle_bottom_height_mode(self):
        """切换底部扩展区域的高度方式：自动计算 / 手动输入"""
        if self.bottom_height_mode_var.get() == "auto":
            self.bottom_auto_frame.pack(fill=X, pady=(5, 0))
            self.bottom_manual_frame.pack_forget()
        else:
            self.bottom_auto_frame.pack_forget()
            self.bottom_manual_frame.pack(fill=X, pady=(5, 0))
            self.toggle_force_169()

    def toggle_force_169(self):
        """切换强制16:9画布背景色选择器的显示"""
        if self.force_169_var.get():
            self.canvas_bg_frame.pack(fill=X, pady=(5, 0))
        else:
            self.canvas_bg_frame.pack_forget()

    def choose_canvas_bg_color(self):
        """选择强制16:9画布背景色"""
        color_code = colorchooser.askcolor(title="选择画布背景色", color=self.canvas_bg_color_var.get())[1]
        if color_code:
            self.canvas_bg_color_var.set(color_code)
            self.canvas_bg_preview.config(bg=color_code)

    def browse_input_dir(self):
        folder = filedialog.askdirectory(title="选择图片目录", initialdir=self.input_dir_var.get())
        if folder:
            self.input_dir_var.set(folder)
            self.load_images()

    def browse_output_dir(self):
        """选择输出目录"""
        folder = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir_var.get())
        if folder:
            self.output_dir_var.set(folder)

    def browse_script_dir(self):
        """选择绘本脚本 JSON 所在目录"""
        folder = filedialog.askdirectory(title="选择绘本脚本目录", initialdir=self.script_dir_var.get())
        if folder:
            self.script_dir_var.set(folder)
            self.save_script_json_choice()
            self.refresh_script_json_list()

    def refresh_script_json_list(self):
        """重新加载脚本目录下的 JSON 列表到下拉框"""
        dir_text = self.script_dir_var.get().strip()
        script_dir = Path(dir_text) if dir_text else None
        json_files = list_script_json_files(script_dir) if script_dir else []
        self.json_combo.config(values=json_files)

        current = self.json_file_var.get().strip()
        if current and current not in json_files:
            self.json_file_var.set("")
            current = ""

        if not script_dir or not script_dir.exists():
            self.json_count_label.config(text="⚠️ 脚本目录不存在", fg="#c62828")
        elif not json_files:
            self.json_count_label.config(text="⚠️ 目录下无 JSON 文件", fg="#e65100")
        else:
            self.json_count_label.config(
                text=f"共 {len(json_files)} 个 JSON" + (f"，当前：{current}" if current else "，未选择"),
                fg="gray"
            )

    def on_script_json_selected(self, event=None):
        """下拉选择脚本 JSON 后，立即解析并匹配文案"""
        self.save_script_json_choice()
        self.apply_script_json()

    def save_script_json_choice(self):
        """记住脚本目录与当前选中的 JSON 文件"""
        cfg = dict(self.config)
        cfg["script_json_dir"] = self.script_dir_var.get().strip()
        cfg["script_json_file"] = self.json_file_var.get().strip()
        self.config = cfg
        self.save_config(cfg)

    def apply_script_json(self):
        """解析选中的脚本 JSON，按图片文件名顺序自动填充剧情描述文案"""
        file_name = self.json_file_var.get().strip()
        if not file_name:
            self._show_toast("绘本脚本", "请先在下拉框中选择一个脚本 JSON 文件", "warning")
            return

        dir_text = self.script_dir_var.get().strip()
        if not dir_text or not Path(dir_text).exists():
            self.status_var.set("⚠️ 脚本目录不存在，未解析")
            self._show_toast("绘本脚本", f"脚本目录不存在：\n{dir_text or '（未填写）'}", "error")
            return

        json_path = Path(dir_text) / file_name
        if not json_path.exists():
            self.status_var.set(f"⚠️ 脚本文件不存在：{file_name}，未解析")
            self._show_toast("绘本脚本", f"文件不存在：\n{json_path}", "error")
            self.refresh_script_json_list()
            return

        images = [p for p in self.image_files if not is_test_image(p.name)]
        if not images:
            self.status_var.set("⚠️ 图片目录下没有图片，未解析")
            self._show_toast("绘本脚本", "图片目录下没有图片，请先选择有效的图片目录", "warning")
            return

        try:
            plots = parse_plot_contents(json_path)
        except json.JSONDecodeError:
            self.status_var.set(f"⚠️ JSON 格式无效：{file_name}，未解析")
            self._show_toast("绘本脚本", f"JSON 格式无效：{file_name}", "error")
            return
        except Exception as e:
            self.status_var.set(f"⚠️ 解析失败：{e}")
            self._show_toast("绘本脚本", f"解析失败：{e}", "error")
            return

        # 数量不一致直接提醒，不再解析文案
        if len(plots) != len(images):
            self._show_toast(
                "数量不一致",
                f"已取消解析。\nJSON 剧情数：{len(plots)}\n图片文件数：{len(images)}",
                "warning", duration_ms=6000
            )
            self.status_var.set(f"⚠️ 脚本 JSON {len(plots)} 条 / 图片 {len(images)} 张，数量不一致，未解析")
            logger.info(f"脚本 JSON {file_name} 剧情 {len(plots)} 条，图片 {len(images)} 张，数量不一致")
            return

        filled = 0
        for img_path, text in zip(images, plots):
            text_var = self.text_entries.get(img_path.name)
            if text_var is None or not text:
                continue
            text_var.set(text)
            filled += 1

        self.refresh_script_json_list()
        self.status_var.set(f"✅ 已按《{file_name}》自动填充 {filled} 条文案")
        self._show_toast("绘本脚本", f"已自动填充 {filled}/{len(images)} 条文案\n来源：{file_name}", "success")
        logger.info(f"脚本 JSON {file_name} 匹配成功，填充 {filled} 条文案")

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
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS and not is_test_image(f.name)
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

    def collect_config(self):
        """校验界面参数并收集配置，失败时提示并返回 None"""
        input_dir = Path(self.input_dir_var.get().strip())
        output_dir = Path(self.output_dir_var.get().strip())

        if not input_dir.exists():
            messagebox.showwarning("警告", "请选择有效的图片目录！")
            return None

        # ✅ 新增：验证输出目录，不存在则自动创建
        if not output_dir:
            messagebox.showwarning("警告", "请选择或输入输出目录！")
            return None
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"创建输出目录失败：\n{output_dir}\n{e}")
            return None

        if not self.image_files:
            messagebox.showwarning("警告", "没有可处理的图片！")
            return None

        try:
            font_size = int(self.size_var.get())
            opacity = float(self.opacity_var.get())
            text_margin_x = int(self.margin_x_var.get())  # ✅ 新增：获取边距值
            if not (0 <= opacity <= 1):
                raise ValueError("透明度必须在 0~1 之间")
            if text_margin_x < 0:
                raise ValueError("左右边距不能为负数")

            mode = self.mode_var.get()
            if mode != "bottom":
                w_pct = float(self.blank_w_var.get())
                h_pct = float(self.blank_h_var.get())
                if not (1 <= w_pct <= 100) or not (1 <= h_pct <= 100):
                    raise ValueError("空白块宽高百分比应在1~100之间")
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数错误：{e}")
            return None

        current_texts = {name: var.get() for name, var in self.text_entries.items()}
        current_config = {
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),  # ✅ 新增：保存输出目录
            "font_size": font_size,
            "font_color": self.color_var.get(),
            "bg_color": self.bg_color_var.get(),
            "font_path": self.font_path_var.get(),
            "opacity": opacity,
            "bottom_area_height": int(self.bottom_h_var.get()) if self.bottom_height_mode_var.get() == "manual" else self.config.get("bottom_area_height", 150),
            "bottom_height_mode": self.bottom_height_mode_var.get(),
            "force_169": self.force_169_var.get(),
            "canvas_bg_color": self.canvas_bg_color_var.get(),
            "mode": mode,
            "blank_block_width_pct": float(self.blank_w_var.get()),
            "blank_block_height_pct": float(self.blank_h_var.get()),
            "texts_per_file": current_texts,
            "adjust_brightness": self.adjust_brightness_var.get(),  # ✅ 保存亮度设置
            "brightness_level": self.brightness_level_var.get(),   # ✅ 保存亮度等级
            "text_margin_x": text_margin_x,                        # ✅ 保存边距设置
            "script_json_dir": self.script_dir_var.get().strip(),   # ✅ 保存脚本目录
            "script_json_file": self.json_file_var.get().strip()    # ✅ 保存选中的脚本文件
        }
        return input_dir, output_dir, current_config

    def start_processing(self):
        collected = self.collect_config()
        if not collected:
            return
        input_dir, output_dir, current_config = collected
        self.config = current_config
        self.save_config(current_config)

        self.start_btn.config(state=DISABLED, text="🔄 处理中...")
        self.test_btn.config(state=DISABLED)
        self.progress_var.set(0)
        self.status_var.set("正在处理...")
        thread = threading.Thread(target=self.run_processing, args=(current_config,), daemon=True)
        thread.start()

    def start_test(self):
        """随机抽取图片生成测试预览，用于查看效果"""
        collected = self.collect_config()
        if not collected:
            return
        input_dir, output_dir, current_config = collected

        self.start_btn.config(state=DISABLED)
        self.test_btn.config(state=DISABLED, text="🧪 测试中...")
        self.progress_var.set(0)
        self.status_var.set("正在生成测试图片...")
        thread = threading.Thread(target=self.run_test, args=(current_config,), daemon=True)
        thread.start()

    def run_processing(self, config):
        input_dir = Path(config["input_dir"])
        output_dir = Path(config["output_dir"])  # ✅ 新增：获取输出目录
        success_count = 0
        total = len(self.image_files)

        # 正式生成前，清理之前遗留的测试预览图片
        cleaned_count = clean_test_images(output_dir)
        if cleaned_count:
            logger.info(f"正式处理前共清理 {cleaned_count} 张测试图片")

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

            # ✅ 修改：输出到指定目录，保持原文件名
            output_path = output_dir / img_path.name
            success, msg = process_image_with_text(img_path, output_path, text, config)
            if success:
                success_count += 1
                logger.info(f"✅ {img_path.name} → {output_path}")

            # 更新进度
            progress = (i / len(images_with_text)) * 100
            self.root.after(0, lambda p=progress: self.progress_var.set(p))
            self.root.after(0, lambda s=f"正在处理 ({i}/{len(images_with_text)})...": self.status_var.set(s))

        self.root.after(0, self.on_complete, success_count, len(images_with_text), cleaned_count)

    def on_complete(self, success_count, total, cleaned_count=0):
        self.start_btn.config(state=NORMAL, text="▶️ 开始处理")
        self.test_btn.config(state=NORMAL)
        self.progress_var.set(100)
        output_dir = self.output_dir_var.get().strip()
        msg = f"处理完成！成功 {success_count}/{total} 张图片。\n输出目录：{output_dir}"
        if cleaned_count:
            msg += f"\n已清理 {cleaned_count} 张测试图片"
        self.status_var.set("✅ " + msg.replace("\n", " "))
        self._show_toast("完成", msg, "success")

    def run_test(self, config):
        """后台线程：随机抽取 TEST_SAMPLE_COUNT 张图片生成测试预览"""
        output_dir = Path(config["output_dir"])
        texts = config["texts_per_file"]

        candidates = [img for img in self.image_files if not is_test_image(img.name)]
        random.shuffle(candidates)
        test_images = candidates[:TEST_SAMPLE_COUNT]
        if not test_images:
            self.root.after(0, self.on_test_complete, 0, 0)
            return

        success_count = 0
        for i, img_path in enumerate(test_images, 1):
            text = texts.get(img_path.name, "").strip()
            if text:
                text_source = "已填文案"
            else:
                text = random.choice(TEST_SAMPLE_TEXTS)
                text_source = "示例文案"

            output_path = output_dir / f"{TEST_PREFIX}{img_path.name}"
            success, msg = process_image_with_text(img_path, output_path, text, config)
            if success:
                success_count += 1
                logger.info(f"🧪 测试 {img_path.name}（{text_source}）→ {output_path.name}")
            else:
                logger.info(f"🧪 测试 {img_path.name} 失败：{msg}")

            progress = (i / len(test_images)) * 100
            self.root.after(0, lambda p=progress: self.progress_var.set(p))
            self.root.after(0, lambda s=f"正在测试 ({i}/{len(test_images)})...": self.status_var.set(s))

        self.root.after(0, self.on_test_complete, success_count, len(test_images))

    def on_test_complete(self, success_count, total):
        self.start_btn.config(state=NORMAL)
        self.test_btn.config(state=NORMAL, text=f"🧪 测试效果({TEST_SAMPLE_COUNT}张)")
        self.progress_var.set(100)
        output_dir = self.output_dir_var.get().strip()
        if total == 0:
            self.status_var.set("🧪 没有可用于测试的图片")
            self._show_toast("测试", "没有可用于测试的图片", "warning")
            return
        msg = (f"已生成 {success_count}/{total} 张测试图片。\n输出目录：{output_dir}\n"
               f"测试文件名以 {TEST_PREFIX} 开头，正式生成时会自动清理")
        self.status_var.set(f"🧪 测试完成：成功 {success_count}/{total} 张")
        self._show_toast("测试效果", msg, "info")

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
