# pyinstaller_gui.py

import sys
import os
import subprocess
import json
import logging
from pathlib import Path
import platform

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QFileDialog,
    QTextEdit, QMessageBox
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt

# ========================
# 配置与常量
# ========================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "pyinstaller_gui"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
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

DEFAULT_CONFIG = {
    "script_path": "",
    "onefile": True,
    "windowed": True,
    "icon_path": "",
    "output_path": str(SCRIPT_DIR / "output"),
    "dist_path": "",
    "work_path": ""
}

# ========================
# 配置管理
# ========================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
            return config
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
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
        logger.error(f"保存配置失败: {e}")

# ========================
# 打包工作线程（避免界面卡死）
# ========================
class PackagerThread(QThread):
    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, str)  # ✅ 新增第三个参数: 输出目录路径

    def __init__(self, cmd, dist_path):
        super().__init__()
        self.cmd = cmd
        self.dist_path = dist_path

    def run(self):
        try:
            self.output_signal.emit(f"执行命令:\n{' '.join(self.cmd)}\n")
            result = subprocess.run(
                self.cmd,
                cwd=SCRIPT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            output = result.stdout
            self.output_signal.emit(output)
            success = result.returncode == 0
            msg = "打包成功！" if success else "打包失败，请查看日志。"
            self.finished_signal.emit(success, msg, self.dist_path)
        except Exception as e:
            error_msg = f"异常: {str(e)}"
            self.output_signal.emit(error_msg)
            self.finished_signal.emit(False, error_msg, self.dist_path)

# ========================
# 主窗口
# ========================
class PackerGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyInstaller 打包工具 - 可视化版")
        self.resize(700, 600)
        self.config = load_config()
        self.thread = None
        self.init_ui()
        self.load_config_to_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 脚本选择
        script_layout = QHBoxLayout()
        self.script_input = QLineEdit()
        script_btn = QPushButton("选择主脚本 (.py)")
        script_btn.clicked.connect(self.select_script)
        script_layout.addWidget(QLabel("主脚本:"))
        script_layout.addWidget(self.script_input)
        script_layout.addWidget(script_btn)
        layout.addLayout(script_layout)

        # 图标选择
        icon_layout = QHBoxLayout()
        self.icon_input = QLineEdit()
        icon_btn = QPushButton("选择图标 (.ico)")
        icon_btn.clicked.connect(self.select_icon)
        icon_layout.addWidget(QLabel("图标 (可选):"))
        icon_layout.addWidget(self.icon_input)
        icon_layout.addWidget(icon_btn)
        layout.addLayout(icon_layout)

        # ✅ 新增：输出目录选择
        output_layout = QHBoxLayout()
        self.output_input = QLineEdit()
        output_btn = QPushButton("选择输出目录")
        output_btn.clicked.connect(self.select_output_dir)
        output_layout.addWidget(QLabel("输出目录:"))
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(output_btn)
        layout.addLayout(output_layout)

        # 选项
        self.onefile_cb = QCheckBox("--onefile (单文件)")
        self.windowed_cb = QCheckBox("--windowed (无控制台)")
        self.onefile_cb.setChecked(True)
        self.windowed_cb.setChecked(True)
        layout.addWidget(self.onefile_cb)
        layout.addWidget(self.windowed_cb)

        # 按钮
        btn_layout = QHBoxLayout()
        self.pack_btn = QPushButton("开始打包")
        self.pack_btn.clicked.connect(self.start_pack)
        self.save_btn = QPushButton("保存配置")
        self.save_btn.clicked.connect(self.save_config_only)
        btn_layout.addWidget(self.pack_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        # 输出日志
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(QLabel("打包日志:"))
        layout.addWidget(self.log_text)

        self.setLayout(layout)

    def select_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Python 脚本", "", "Python Files (*.py *.pyw)")
        if path:
            self.script_input.setText(path)

    def select_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 ICO 图标", "", "Icon Files (*.ico)")
        if path:
            self.icon_input.setText(path)

    def select_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择打包输出目录", "")
        if path:
            self.output_input.setText(path)

    def load_config_to_ui(self):
        self.script_input.setText(self.config.get("script_path", ""))
        self.icon_input.setText(self.config.get("icon_path", ""))
        self.output_input.setText(self.config.get("output_path", str(SCRIPT_DIR / "output")))
        self.onefile_cb.setChecked(self.config.get("onefile", True))
        self.windowed_cb.setChecked(self.config.get("windowed", True))

    def get_config_from_ui(self):
        output_path = self.output_input.text().strip()
        if not output_path:
            output_path = str(SCRIPT_DIR / "output")
        return {
            "script_path": self.script_input.text().strip(),
            "icon_path": self.icon_input.text().strip(),
            "output_path": output_path,
            "onefile": self.onefile_cb.isChecked(),
            "windowed": self.windowed_cb.isChecked(),
            "dist_path": os.path.join(output_path, "dist"),
            "work_path": os.path.join(output_path, "build")
        }

    def save_config_only(self):
        config = self.get_config_from_ui()
        save_config(config)
        QMessageBox.information(self, "提示", "配置已保存")

    def start_pack(self):
        config = self.get_config_from_ui()
        script = config["script_path"]
        if not script or not os.path.isfile(script):
            QMessageBox.warning(self, "错误", "请选择有效的主脚本 (.py) 文件！")
            return

        # 构建 PyInstaller 命令
        cmd = [sys.executable, "-m", "PyInstaller"]
        if config["onefile"]:
            cmd.append("--onefile")
        if config["windowed"]:
            cmd.append("--windowed")
        if config["icon_path"] and os.path.isfile(config["icon_path"]):
            cmd.extend(["--icon", config["icon_path"]])
        cmd.extend([
            "--distpath", config["dist_path"],
            "--workpath", config["work_path"],
            script
        ])

        # 禁用按钮
        self.pack_btn.setEnabled(False)
        self.log_text.clear()
        self.log_text.append("开始打包...\n")

        # 启动线程（传递dist_path用于打包完成后打开目录）
        self.thread = PackagerThread(cmd, config["dist_path"])
        self.thread.output_signal.connect(self.append_log)
        self.thread.finished_signal.connect(self.on_pack_finished)
        self.thread.start()

    def append_log(self, text):
        self.log_text.append(text)

    def on_pack_finished(self, success, msg, dist_path):
        self.pack_btn.setEnabled(True)
        QMessageBox.information(self, "打包完成", msg)
        logger.info(f"打包结束: {'成功' if success else '失败'}")
        # ✅ 打包成功后自动打开输出目录
        if success and dist_path and os.path.isdir(dist_path):
            self.log_text.append(f"\n打开输出目录: {dist_path}\n")
            self._open_directory(dist_path)

    def _open_directory(self, path):
        """跨平台打开目录"""
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(path)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", path])
            else:  # Linux
                subprocess.run(["xdg-open", path])
            logger.info(f"已打开目录: {path}")
        except Exception as e:
            logger.error(f"打开目录失败: {e}")

# ========================
# 主程序
# ========================
def main():
    app = QApplication(sys.argv)
    window = PackerGUI()
    window.show()
    logger.info("PyInstaller GUI 启动")
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
