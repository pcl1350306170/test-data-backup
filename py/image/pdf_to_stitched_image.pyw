# pdf_to_stitched_image.pyw

import sys
import json
import logging
from pathlib import Path
import os

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox, QSpinBox,
    QFormLayout, QColorDialog, QCheckBox
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

# ========================
# 配置与常量
# ========================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "pdf_to_stitched_image"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "split_count": 3,
    "pdf_path": "",
    "output_dir": str(SCRIPT_DIR),
    "background_color": "#000000",  # 黑色
    "text_color": "#FF0000",        # 红色
    "dpi": 150                      # 渲染清晰度
}

# ========================
# 配置管理
# ========================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info("配置加载成功")
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
            return config
        except Exception as e:
            logger.error(f"配置文件读取失败: {e}")
            return DEFAULT_CONFIG.copy()
    else:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"配置保存失败: {e}")
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, "错误", f"无法保存配置：{e}")

# ========================
# PDF 转图片核心逻辑
# ========================
def pdf_to_long_image(pdf_path, bg_color, text_color, dpi=150):
    """
    将 PDF 转为一张纵向拼接的超长图片
    注意：pdf2image 使用 poppler，需系统安装或指定路径
    """
    try:
        from pdf2image import convert_from_path
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:
        raise ImportError("缺少依赖库，请安装：pip install pdf2image pillow\n" + str(e))

    logger.info(f"开始将 PDF 转为图片，DPI={dpi}...")

    # 尝试使用系统 poppler（Windows 需额外安装）
    images = []
    try:
        images = convert_from_path(pdf_path, dpi=dpi, thread_count=4)
    except Exception as e:
        if "poppler" in str(e).lower():
            raise RuntimeError(
                "未找到 Poppler。请安装 Poppler 并将其 bin 目录加入系统 PATH。\n"
                "Windows 用户可从 https://github.com/oschwartz10612/poppler-windows/releases 下载"
            )
        else:
            raise e

    if not images:
        raise ValueError("PDF 转换失败：未生成任何图像")

    # 获取统一宽度（取最大页宽）
    max_width = max(img.width for img in images)
    total_height = sum(img.height for img in images)

    # 创建黑色背景长图
    long_img = Image.new('RGB', (max_width, total_height), color=bg_color)

    # 纵向粘贴每一页（自动居中对齐）
    y_offset = 0
    for img in images:
        # 如果页面宽度小于 max_width，左右居中
        x_offset = (max_width - img.width) // 2
        long_img.paste(img, (x_offset, y_offset))
        y_offset += img.height

    logger.info(f"PDF 转换完成：{len(images)} 页 → 图片尺寸 {max_width}x{total_height}")
    return long_img

# ========================
# 裁剪并水平拼接
# ========================
def crop_and_stitch_image(long_img, split_count):
    width, height = long_img.size
    if height <= 1000:
        logger.warning("图片高度较低，但仍继续处理...")

    part_height = height // split_count
    remainder = height % split_count

    parts = []
    y = 0
    for i in range(split_count):
        h = part_height + (1 if i < remainder else 0)
        box = (0, y, width, y + h)
        part = long_img.crop(box)
        parts.append(part)
        y += h

    # 水平拼接
    total_width = sum(p.width for p in parts)
    max_height = max(p.height for p in parts)
    stitched = Image.new('RGB', (total_width, max_height), (0, 0, 0))  # 黑底

    x = 0
    for part in parts:
        stitched.paste(part, (x, 0))
        x += part.width

    return stitched

# ========================
# 主窗口
# ========================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 超长图裁剪拼接工具")
        self.setGeometry(300, 200, 650, 400)
        self.config = load_config()
        self.bg_color = QColor(self.config.get("background_color", "#000000"))
        self.text_color = QColor(self.config.get("text_color", "#FF0000"))
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        layout = QFormLayout()

        # PDF 选择
        self.pdf_path_edit = QLineEdit()
        self.pdf_path_edit.setText(self.config.get("pdf_path", ""))
        self.browse_pdf_btn = QPushButton("选择 PDF...")
        self.browse_pdf_btn.clicked.connect(self.browse_pdf)
        layout.addRow("PDF 文件（支持多页）:", self.pdf_path_edit)
        layout.addRow("", self.browse_pdf_btn)

        # 分割份数
        self.split_spin = QSpinBox()
        self.split_spin.setRange(1, 20)
        self.split_spin.setValue(self.config.get("split_count", 3))
        layout.addRow("均分为几份:", self.split_spin)

        # 输出目录
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setText(self.config.get("output_dir", str(SCRIPT_DIR)))
        self.browse_output_btn = QPushButton("选择输出目录...")
        self.browse_output_btn.clicked.connect(self.browse_output)
        layout.addRow("输出目录:", self.output_dir_edit)
        layout.addRow("", self.browse_output_btn)

        # 颜色配置
        self.bg_btn = QPushButton("设置背景色")
        self.bg_btn.clicked.connect(self.pick_bg_color)
        self.bg_label = QLabel()
        self.update_color_preview()

        self.text_btn = QPushButton("设置文字/前景色")
        self.text_btn.clicked.connect(self.pick_text_color)

        layout.addRow("背景颜色:", self.bg_btn)
        layout.addRow("", self.bg_label)
        layout.addRow("文字/前景颜色:", self.text_btn)

        # DPI 设置（高级）
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 300)
        self.dpi_spin.setValue(self.config.get("dpi", 150))
        layout.addRow("渲染 DPI（清晰度）:", self.dpi_spin)

        # 按钮区
        btn_layout = QHBoxLayout()
        self.process_btn = QPushButton("开始处理 PDF → 拼接图")
        self.save_config_btn = QPushButton("仅保存配置")
        self.quit_btn = QPushButton("退出")

        self.process_btn.clicked.connect(self.process_pdf)
        self.save_config_btn.clicked.connect(self.save_config_only)
        self.quit_btn.clicked.connect(self.close)

        btn_layout.addWidget(self.process_btn)
        btn_layout.addWidget(self.save_config_btn)
        btn_layout.addWidget(self.quit_btn)

        main_layout = QVBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(btn_layout)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

    def update_color_preview(self):
        self.bg_label.setStyleSheet(
            f"background-color: {self.bg_color.name()}; border: 1px solid #ccc; min-width: 100px; min-height: 20px;"
        )

    def browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "", "PDF Files (*.pdf)")
        if path:
            self.pdf_path_edit.setText(path)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text())
        if path:
            self.output_dir_edit.setText(path)

    def pick_bg_color(self):
        color = QColorDialog.getColor(self.bg_color, self, "选择背景颜色")
        if color.isValid():
            self.bg_color = color
            self.update_color_preview()

    def pick_text_color(self):
        color = QColorDialog.getColor(self.text_color, self, "选择文字/前景颜色")
        if color.isValid():
            self.text_color = color

    def get_current_config(self):
        return {
            "split_count": self.split_spin.value(),
            "pdf_path": self.pdf_path_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
            "background_color": self.bg_color.name(),
            "text_color": self.text_color.name(),
            "dpi": self.dpi_spin.value()
        }

    def save_config_only(self):
        config = self.get_current_config()
        save_config(config)
        QMessageBox.information(self, "成功", "配置已保存！")

    def process_pdf(self):
        config = self.get_current_config()
        pdf_path = config["pdf_path"]
        output_dir = config["output_dir"]
        split_count = config["split_count"]

        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "错误", "请选择有效的 PDF 文件！")
            return
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.warning(self, "错误", "请选择有效的输出目录！")
            return

        try:
            # 步骤1: PDF → 超长图
            long_img = pdf_to_long_image(
                pdf_path,
                bg_color=tuple(self.bg_color.getRgb()[:3]),
                text_color=tuple(self.text_color.getRgb()[:3]),
                dpi=config["dpi"]
            )

            # 步骤2: 裁剪 + 水平拼接
            stitched_img = crop_and_stitch_image(long_img, split_count)

            # 步骤3: 保存
            pdf_name = Path(pdf_path).stem
            output_path = Path(output_dir) / f"{pdf_name}_stitched.jpg"
            stitched_img.save(output_path, quality=95)
            save_config(config)

            logger.info(f"处理完成！输出: {output_path}")
            QMessageBox.information(self, "成功", f"处理完成！\n输出文件：\n{output_path}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"处理失败: {error_msg}")
            QMessageBox.critical(self, "错误", f"处理失败：\n{error_msg}")

# ========================
# 主程序入口
# ========================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDFToStitchedImage")

    window = MainWindow()
    window.show()

    logger.info("程序启动成功")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
