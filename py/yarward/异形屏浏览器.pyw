# 异形屏浏览器.pyw
# 异形屏（LED 条幅屏）模拟器：每个面板的 QWebEngineView 按自身行宽独立渲染，
# 垂直方向裁剪出对应"行"的区域，水平并排显示在普通显示器上

import sys
import json
from pathlib import Path
import os

# ──────────── QWebEngine 启动优化（必须在 QApplication 之前）────────────
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox --disable-software-rasterizer"
# ─────────────────────────────────────────────────────────────────────

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QCheckBox, QMessageBox, QFormLayout,
    QComboBox, QGroupBox, QLabel
)
from PyQt5.QtCore import QUrl, Qt, QPoint, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView

# ========================
# 配置与常量
# ========================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "led_banner_browser"  # 脚本名称
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

MAX_ROWS = 6

# 默认配置
DEFAULT_CONFIG = {
    "url": "http://localhost:3000",
    "totalHeight": 134,       # 页面总高度（仅手动模式使用，行高=总高/行数）
    "autoDetectHeight": True, # 自动检测页面总高
    "rows": [                 # 每行只需配置宽度，起始Y=行序号×行高 自动累加
        {"width": 1334},
        {"width": 1664}
    ],
    "showGap": False,         # 是否显示面板间隙
    "gap": 8,                 # 间隙像素
    "frameless": True,
    "movable": True,
    "alwaysOnTop": False
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
# 浏览器主窗口（多面板）
# ========================
class BrowserWindow(DraggableFramelessWindow):
    def __init__(self):
        super().__init__()
        self.config = None
        self.panels = []            # [(container, view, row_width)]
        self.detected_height = None # JS 检测到的页面总高
        self._pending_detect = 0
        self._init_container()

    def _init_container(self):
        self._root = QWidget(self)
        self._layout = QHBoxLayout(self._root)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setCentralWidget(self._root)

    # ---------- 冻结页面滚动（注入 JS） ----------
    _FREEZE_JS = """
    (function(){
        if (!document.getElementById('__led_freeze__')) {
            var s = document.createElement('style');
            s.id = '__led_freeze__';
            s.textContent = 'html,body{overflow:hidden !important;}';
            (document.head || document.documentElement).appendChild(s);
        }
        window.scrollTo(0, 0);
    })();
    """

    _HEIGHT_JS = ("Math.max(document.body.scrollHeight, "
                  "document.documentElement.scrollHeight)")

    def update_window(self, config):
        """应用配置：重建所有面板并加载 URL"""
        self.config = config
        self.detected_height = None

        # 窗口 flags
        flags = Qt.Widget
        if config["frameless"]:
            flags |= Qt.FramelessWindowHint
        if config["alwaysOnTop"]:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self._movable = config["movable"]

        self._rebuild_panels()
        self.show()
        logger.info(f"窗口更新: {len(config['rows'])} 行, 总高={config['totalHeight']}, URL={config['url']}")

    def _clear_panels(self):
        for container, view, _ in self.panels:
            view.deleteLater()
            container.deleteLater()
        self.panels = []
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _rebuild_panels(self):
        self._clear_panels()
        config = self.config
        gap = config["gap"] if config["showGap"] else 0
        self._layout.setSpacing(gap)

        row_height = self._current_row_height()
        total_height = self._current_total_height()

        for i, row in enumerate(config["rows"]):
            row_width = int(row["width"])
            start_y = int(i * row_height)

            container = QWidget()
            container.setFixedSize(row_width, int(row_height))
            container.setStyleSheet("background:#222;")

            view = QWebEngineView(container)
            # 视图按该行自身宽度独立渲染；负 y 偏移实现垂直裁剪，容器负责裁掉下方多余部分
            view.setGeometry(0, -start_y, row_width, int(total_height))

            view.page().loadFinished.connect(
                lambda ok, v=view: self._on_load_finished(ok, v))
            view.setUrl(QUrl(config["url"]))

            self._layout.addWidget(container)
            self.panels.append((container, view, row_width))

        self._resize_window()

    # ---------- 高度计算 ----------
    def _current_total_height(self):
        config = self.config
        if config["autoDetectHeight"] and self.detected_height:
            return self.detected_height
        return int(config["totalHeight"])

    def _current_row_height(self):
        rows = len(self.config["rows"])
        return max(1, self._current_total_height() // rows)

    def _resize_window(self):
        gap = self.config["gap"] if self.config["showGap"] else 0
        total_w = sum(p[2] for p in self.panels) + gap * (len(self.panels) - 1)
        total_h = self._current_row_height()
        self.setFixedSize(int(total_w), int(total_h))

    def _relayout_panels(self):
        """高度检测完成后，重新计算行高与偏移并调整视图"""
        row_height = self._current_row_height()
        total_height = self._current_total_height()
        for i, (container, view, row_width) in enumerate(self.panels):
            container.setFixedSize(row_width, int(row_height))
            view.setGeometry(0, -int(i * row_height), row_width, int(total_height))
        self._resize_window()

    def _on_load_finished(self, ok, view):
        if not ok:
            logger.warning("页面加载失败")
            return
        view.page().runJavaScript(self._FREEZE_JS)
        # 自动检测模式下，用第一个面板检测页面总高
        if self.config["autoDetectHeight"] and view is self.panels[0][1]:
            def on_height(h):
                try:
                    h = int(h)
                except (TypeError, ValueError):
                    return
                if h > 0 and h != self.detected_height:
                    self.detected_height = h
                    logger.info(f"自动检测页面总高: {h}px")
                    QTimer.singleShot(0, self._relayout_panels)
            view.page().runJavaScript(self._HEIGHT_JS, on_height)

# ========================
# 主控制面板
# ========================
class ControlPanel(QWidget):
    def __init__(self, browser_window):
        super().__init__()
        self.browser_window = browser_window
        self.config = load_config()
        self.row_width_inputs = []
        self.init_ui()
        self.load_into_ui()

    def init_ui(self):
        self._scroll = QVBoxLayout()

        form = QFormLayout()
        self.url_input = QLineEdit()
        self.total_height_input = QLineEdit()
        self.auto_height_cb = QCheckBox("自动检测（总高/行数）")
        self.rows_combo = QComboBox()
        self.rows_combo.addItems([str(i) for i in range(1, MAX_ROWS + 1)])
        self.rows_combo.currentIndexChanged.connect(self.rebuild_row_groups)

        self.frameless_cb = QCheckBox()
        self.movable_cb = QCheckBox()
        self.topmost_cb = QCheckBox()
        self.show_gap_cb = QCheckBox()
        self.gap_input = QLineEdit()

        form.addRow("URL:", self.url_input)
        form.addRow("行数 (1~%d):" % MAX_ROWS, self.rows_combo)
        self._height_form_wrap = QHBoxLayout()
        self._height_form_wrap.addWidget(self.total_height_input)
        self._height_form_wrap.addWidget(self.auto_height_cb)
        form.addRow("页面总高度 (px):", self._wrap(self._height_form_wrap))
        form.addRow("显示面板间隙:", self.show_gap_cb)
        form.addRow("间隙宽度 (px):", self.gap_input)
        form.addRow("无边框:", self.frameless_cb)
        form.addRow("可拖动:", self.movable_cb)
        form.addRow("窗口置顶:", self.topmost_cb)
        self._scroll.addLayout(form)

        # 每行宽度配置区（动态生成）
        self._rows_area = QVBoxLayout()
        self._scroll.addLayout(self._rows_area)

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
        self._scroll.addLayout(btn_layout)

        self.setLayout(self._scroll)

    @staticmethod
    def _wrap(hbox):
        w = QWidget()
        w.setLayout(hbox)
        return w

    def rebuild_row_groups(self):
        """按行数下拉值动态生成每行宽度输入框"""
        while self._rows_area.count():
            item = self._rows_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.row_width_inputs = []
        count = int(self.rows_combo.currentText())
        saved = self.config.get("rows", [])
        for i in range(count):
            box = QGroupBox(f"第{i + 1}行")
            fl = QFormLayout()
            width_input = QLineEdit()
            width_input.setPlaceholderText("该行宽度 (px)")
            if i < len(saved):
                width_input.setText(str(saved[i].get("width", "")))
            fl.addRow("宽度:", width_input)
            box.setLayout(fl)
            self._rows_area.addWidget(box)
            self.row_width_inputs.append(width_input)

    def load_into_ui(self):
        c = self.config
        self.url_input.setText(c.get("url", DEFAULT_CONFIG["url"]))
        self.total_height_input.setText(str(c.get("totalHeight", 134)))
        auto = c.get("autoDetectHeight", True)
        self.auto_height_cb.setChecked(auto)
        self.total_height_input.setEnabled(not auto)
        self.auto_height_cb.toggled.connect(self.total_height_input.setDisabled)
        self.rows_combo.setCurrentIndex(max(0, min(len(c.get("rows", [])) - 1, MAX_ROWS - 1)))
        self.rebuild_row_groups()
        self.show_gap_cb.setChecked(c.get("showGap", False))
        self.gap_input.setText(str(c.get("gap", 8)))
        self.frameless_cb.setChecked(c.get("frameless", True))
        self.movable_cb.setChecked(c.get("movable", True))
        self.topmost_cb.setChecked(c.get("alwaysOnTop", False))

    def get_config_from_ui(self):
        try:
            total_height = int(self.total_height_input.text())
            gap = int(self.gap_input.text() or "0")
        except ValueError:
            raise ValueError("高度/间隙必须是整数")
        if total_height <= 0:
            raise ValueError("总高度必须大于 0")
        rows = []
        for i, inp in enumerate(self.row_width_inputs):
            try:
                w = int(inp.text())
            except ValueError:
                raise ValueError(f"第{i + 1}行宽度必须是整数")
            if w <= 0:
                raise ValueError(f"第{i + 1}行宽度必须大于 0")
            rows.append({"width": w})
        url = self.url_input.text().strip()
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        return {
            "url": url,
            "totalHeight": total_height,
            "autoDetectHeight": self.auto_height_cb.isChecked(),
            "rows": rows,
            "showGap": self.show_gap_cb.isChecked(),
            "gap": gap,
            "frameless": self.frameless_cb.isChecked(),
            "movable": self.movable_cb.isChecked(),
            "alwaysOnTop": self.topmost_cb.isChecked()
        }

    def apply_config(self):
        try:
            config = self.get_config_from_ui()
            self.browser_window.update_window(config)
            save_config(config)
            self.config = config
            logger.info(f"应用新配置: {config}")
        except Exception as e:
            logger.error(f"应用配置失败: {e}")
            QMessageBox.warning(self, "输入错误", f"配置无效：{e}")

    def save_only(self):
        try:
            config = self.get_config_from_ui()
            save_config(config)
            self.config = config
        except Exception as e:
            QMessageBox.warning(self, "输入错误", f"配置无效：{e}")

# ========================
# 主程序入口
# ========================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LED Banner Browser")

    browser = BrowserWindow()
    browser.hide()

    control = ControlPanel(browser)
    control.setWindowTitle("异形屏模拟器 - 控制面板")
    control.resize(420, 560)
    control.show()

    # 启动时自动应用已保存的配置（延迟到事件循环，避免初始化阻塞）
    QTimer.singleShot(200, control.apply_config)

    logger.info("程序启动成功")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
