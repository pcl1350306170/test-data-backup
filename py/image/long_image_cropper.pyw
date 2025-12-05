# long_image_cropper.pyw

import sys
import json
import logging
from pathlib import Path
import os

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox, QSpinBox, QFormLayout
)
from PyQt5.QtCore import Qt
from PIL import Image

# ========================
# 配置与常量
# ========================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "long_image_cropper"  # 脚本名称
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
    "input_image_path": "",
    "output_dir": str(SCRIPT_DIR)
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
# 图像处理核心函数
# ========================
def crop_and_stitch(image_path: str, split_count: int, output_dir: str):
    try:
        img = Image.open(image_path)
        width, height = img.size

        if height <= 10000:
            raise ValueError(f"图片高度需 >10000px，当前高度：{height}px")

        if split_count < 1:
            raise ValueError("分割份数必须 ≥1")

        # 计算每份高度（最后一份可能略大）
        part_height = height // split_count
        remainder = height % split_count

        parts = []
        y = 0
        for i in range(split_count):
            h = part_height + (1 if i < remainder else 0)
            box = (0, y, width, y + h)
            part = img.crop(box)
            parts.append(part)
            y += h

        # 水平拼接（从左到右）
        total_width = width * split_count
        max_height = max(p.size[1] for p in parts)
        stitched = Image.new('RGB', (total_width, max_height), (255, 255, 255))

        x = 0
        for part in parts:
            stitched.paste(part, (x, 0))
            x += part.size[0]

        # 生成输出路径
        input_name = Path(image_path).stem
        output_path = Path(output_dir) / f"{input_name}_stitched.jpg"
        stitched.save(output_path, quality=95)
        logger.info(f"拼接完成，保存至: {output_path}")
        return str(output_path)

    except Exception as e:
        logger.error(f"图像处理失败: {e}")
        raise e

# ========================
# 主窗口
# ========================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("超长图片裁剪拼接工具")
        self.setGeometry(300, 200, 600, 300)
        self.config = load_config()
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        layout = QFormLayout()

        # 输入图片
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setText(self.config.get("input_image_path", ""))
        self.browse_input_btn = QPushButton("选择图片...")
        self.browse_input_btn.clicked.connect(self.browse_input)

        layout.addRow("输入图片（高度>10000px）:", self.input_path_edit)
        layout.addRow("", self.browse_input_btn)

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

        # 按钮区
        btn_layout = QHBoxLayout()
        self.process_btn = QPushButton("开始裁剪并拼接")
        self.save_config_btn = QPushButton("仅保存配置")
        self.quit_btn = QPushButton("退出")

        self.process_btn.clicked.connect(self.process_image)
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

    def browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择超长图片", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )
        if path:
            self.input_path_edit.setText(path)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text())
        if path:
            self.output_dir_edit.setText(path)

    def get_current_config(self):
        return {
            "split_count": self.split_spin.value(),
            "input_image_path": self.input_path_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip()
        }

    def save_config_only(self):
        config = self.get_current_config()
        save_config(config)
        QMessageBox.information(self, "成功", "配置已保存！")

    def process_image(self):
        config = self.get_current_config()
        input_path = config["input_image_path"]
        output_dir = config["output_dir"]
        split_count = config["split_count"]

        # 校验
        if not input_path or not os.path.isfile(input_path):
            QMessageBox.warning(self, "错误", "请选择有效的输入图片！")
            return
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.warning(self, "错误", "请选择有效的输出目录！")
            return

        try:
            output_path = crop_and_stitch(input_path, split_count, output_dir)
            save_config(config)  # 成功后自动保存配置
            QMessageBox.information(self, "成功", f"处理完成！\n输出文件：\n{output_path}")
        except Exception as e:
            QMessageBox.critical(self, "处理失败", f"错误：{str(e)}")

# ========================
# 主程序入口
# ========================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LongImageCropper")

    window = MainWindow()
    window.show()

    logger.info("程序启动成功")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
