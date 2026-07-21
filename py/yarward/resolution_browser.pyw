# resolution_browser.pyw

import sys
import json
import logging
from pathlib import Path
import os

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QMessageBox, QFormLayout
)
from PyQt5.QtCore import QUrl, Qt, QPoint
from PyQt5.QtWebEngineWidgets import QWebEngineView

# ========================
# 配置与常量
# ========================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "resolution_browser"  # 脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
# ──────────── 公共日志模块（可选依赖）────────────
import sys
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

# 默认配置
DEFAULT_CONFIG = {
    "width": 2880,
    "height": 320,
    "url": "http://localhost:3000",
    "frameless": True,
    "resizable": False,
    "movable": True
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
            # 合并缺失的默认值
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
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:  # 修复：移除多余空格
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"配置保存失败: {e}")
        # 在 .pyw 中，弹窗是唯一可见的错误提示
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(None, "错误", f"无法保存配置：{e}")

# ========================
# 可拖动无边框窗口辅助类
# ========================
class DraggableFramelessWindow(QMainWindow):
    def __init__(self, movable=True):
        super().__init__()
        self._drag_pos = QPoint()
        self._movable = movable

    def mousePressEvent(self, event):
        if self._movable and event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._movable and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

# ========================
# 主控制面板
# ========================
class ControlPanel(QWidget):
    def __init__(self, browser_window):
        super().__init__()
        self.browser_window = browser_window
        self.config = load_config()
        self.init_ui()
        self.load_into_ui()

    def init_ui(self):
        layout = QFormLayout()

        self.width_input = QLineEdit()
        self.height_input = QLineEdit()
        self.url_input = QLineEdit()
        self.frameless_cb = QCheckBox()
        self.resizable_cb = QCheckBox()
        self.movable_cb = QCheckBox()

        layout.addRow("宽度 (px):", self.width_input)
        layout.addRow("高度 (px):", self.height_input)
        layout.addRow("URL:", self.url_input)
        layout.addRow("无边框:", self.frameless_cb)
        layout.addRow("可调整大小:", self.resizable_cb)
        layout.addRow("可拖动 (仅无边框时有效):", self.movable_cb)

        # 按钮
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("应用并刷新")
        self.save_btn = QPushButton("保存配置")
        self.quit_btn = QPushButton("退出")

        self.apply_btn.clicked.connect(self.apply_config)
        self.save_btn.clicked.connect(self.save_only)
        self.quit_btn.clicked.connect(QApplication.instance().quit)

        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.quit_btn)

        main_layout = QVBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

    def load_into_ui(self):
        self.width_input.setText(str(self.config.get("width", 2880)))
        self.height_input.setText(str(self.config.get("height", 320)))
        self.url_input.setText(self.config.get("url", "http://localhost:3000"))
        self.frameless_cb.setChecked(self.config.get("frameless", True))
        self.resizable_cb.setChecked(self.config.get("resizable", False))
        self.movable_cb.setChecked(self.config.get("movable", True))

    def get_config_from_ui(self):
        try:
            width = int(self.width_input.text())
            height = int(self.height_input.text())
            url = self.url_input.text().strip()
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            return {
                "width": width,
                "height": height,
                "url": url,
                "frameless": self.frameless_cb.isChecked(),
                "resizable": self.resizable_cb.isChecked(),
                "movable": self.movable_cb.isChecked()
            }
        except ValueError:
            raise ValueError("宽度和高度必须是整数")

    def apply_config(self):
        try:
            config = self.get_config_from_ui()
            self.browser_window.update_window(config)
            save_config(config)
            logger.info(f"应用新配置: {config}")
        except Exception as e:
            logger.error(f"应用配置失败: {e}")
            QMessageBox.warning(self, "输入错误", f"配置无效：{e}")

    def save_only(self):
        try:
            config = self.get_config_from_ui()
            save_config(config)
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"配置无效：{e}")

# ========================
# 浏览器主窗口
# ========================
class BrowserWindow(DraggableFramelessWindow):
    def __init__(self):
        super().__init__()
        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)
        self.control_panel = None

    def update_window(self, config):
        # 先关闭旧窗口属性
        self.setWindowFlags(Qt.Widget)  # 重置 flags

        # 设置新属性
        if config["frameless"]:
            self.setWindowFlags(Qt.FramelessWindowHint)
            self._movable = config["movable"]
        else:
            self._movable = False

        if not config["resizable"]:
            self.setFixedSize(config["width"], config["height"])
        else:
            self.resize(config["width"], config["height"])
            self.setMinimumSize(400, 200)

        # 加载 URL
        self.web_view.setUrl(QUrl(config["url"]))

        # 显示窗口
        self.show()
        logger.info(f"窗口更新: {config['width']}x{config['height']}, URL={config['url']}")

# ========================
# 主程序入口
# ========================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Resolution Browser")

    # 创建浏览器窗口（初始隐藏）
    browser = BrowserWindow()
    browser.hide()

    # 创建控制面板
    control = ControlPanel(browser)
    control.setWindowTitle("分辨率浏览器 - 控制面板")
    control.resize(400, 300)
    control.show()

    logger.info("程序启动成功")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
