# node_packager_fixed.py

import os
import subprocess
import json
import platform
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime
import threading

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "node_packager"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
LOG_DIR = SCRIPT_DIR / "json" / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

class NodePackagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Node项目打包工具")
        self.root.geometry("800x600")
        self.root.minsize(700, 500)

        # 初始化变量
        self.project_path = tk.StringVar()
        self.is_packaging = False

        # 创建UI
        self._create_widgets()

        # 加载配置
        self._load_config()

    def _select_project_dir(self):
        """选择项目目录"""
        dir_path = filedialog.askdirectory(title="选择Node项目目录")
        if dir_path:
            # 检查是否包含package.json
            package_json = os.path.join(dir_path, "package.json")
            if not os.path.exists(package_json):
                messagebox.showerror("错误", "所选目录不是Node项目（未找到package.json）")
                return

            self.project_path.set(dir_path)
            self._log(f"选择项目目录: {dir_path}")

    def _check_node_version(self):
        """检查当前Node版本并提示用户"""
        try:
            result = subprocess.check_output(["node", "-v"], text=True, encoding='utf-8')
            current_version = result.strip()
            self._log(f"当前Node版本: {current_version}")

            # 检查package.json中的engines配置
            if self.project_path.get():
                package_json_path = os.path.join(self.project_path.get(), "package.json")
                if os.path.exists(package_json_path):
                    with open(package_json_path, 'r', encoding='utf-8') as f:
                        package_data = json.load(f)

                    required_version = package_data.get("engines", {}).get("node")
                    if required_version:
                        self._log(f"项目要求Node版本: {required_version}")
                        messagebox.showwarning(
                            "版本检查",
                            f"项目要求Node版本: {required_version}\n当前版本: {current_version}\n请确保版本兼容，否则可能打包失败。"
                        )

            return True
        except Exception as e:
            self._log(f"检查Node版本失败: {str(e)}", logging.WARNING)
            messagebox.showwarning("版本检查", "无法检测Node版本，请确保已安装Node.js并配置到环境变量中。")
            return False

    def _run_npm_command(self, command):
        """运行npm命令"""
        if not self.project_path.get():
            messagebox.showerror("错误", "请先选择项目目录")
            return False

        # 检查Node版本
        if not self._check_node_version():
            return False

        project_dir = self.project_path.get()

        try:
            self.is_packaging = True
            self._update_button_states()

            # 修复：将命令拆分为列表
            if " " in command:
                # 例如 "run build" 拆分为 ["run", "build"]
                cmd_parts = command.split()
                cmd = ["npm"] + cmd_parts
            else:
                cmd = ["npm", command]

            self._log(f"开始执行命令: {' '.join(cmd)}")

            # 执行命令并实时输出
            process = subprocess.Popen(
                cmd,
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                shell=platform.system() == "Windows"  # Windows需要shell=True
            )

            # 实时读取输出
            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        self._log(line.strip())

            # 确保读取剩余输出
            if process.stdout:
                remaining = process.stdout.read()
                if remaining:
                    self._log(remaining.strip())

            # 检查执行结果
            if process.returncode == 0:
                self._log(f"命令 'npm {command}' 执行成功")
                return True
            else:
                self._log(f"命令 'npm {command}' 执行失败，返回代码: {process.returncode}", logging.ERROR)
                return False

        except Exception as e:
            self._log(f"执行命令出错: {str(e)}", logging.ERROR)
            return False
        finally:
            self.is_packaging = False
            self._update_button_states()

    def _build_project(self):
        """执行build打包"""
        threading.Thread(target=self._run_npm_command, args=("run build",), daemon=True).start()

    def _render2_project(self):
        """执行render2打包"""
        threading.Thread(target=self._run_npm_command, args=("run lib-render2",), daemon=True).start()

    def _build_all(self):
        """执行全部打包"""
        def run_all():
            build_success = self._run_npm_command("run build")
            if build_success:
                self._log("===== build 完成，开始执行 lib-render2 =====")
                render_success = self._run_npm_command("run lib-render2")
                if render_success:
                    self._log("===== 所有打包命令执行完成 =====")
                    self._open_project_dir()
                else:
                    self._log("===== lib-render2 执行失败 =====", logging.ERROR)
            else:
                self._log("===== build 执行失败，终止后续操作 =====", logging.ERROR)

        threading.Thread(target=run_all, daemon=True).start()

    def _open_project_dir(self):
        """打开项目目录"""
        if self.project_path.get():
            try:
                project_dir = self.project_path.get()
                if platform.system() == "Windows":
                    os.startfile(project_dir)
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", project_dir])
                else:  # Linux
                    subprocess.run(["xdg-open", project_dir])
                self._log(f"已打开项目目录: {project_dir}")
            except Exception as e:
                self._log(f"打开项目目录失败: {str(e)}", logging.ERROR)

    def _log(self, message, level=logging.INFO):
        """记录日志并更新UI"""
        logging.log(level, message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        # 强制刷新UI
        self.root.update_idletasks()

    def _update_button_states(self):
        """更新按钮状态"""
        state = tk.DISABLED if self.is_packaging else tk.NORMAL
        self.build_btn.config(state=state)
        self.render2_btn.config(state=state)
        self.build_all_btn.config(state=state)
        self.select_project_btn.config(state=state)

    def _save_config(self):
        """保存配置"""
        config = {
            "last_project_path": self.project_path.get()
        }

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log("配置已保存")
        except Exception as e:
            self._log(f"保存配置失败: {str(e)}", logging.ERROR)

    def _load_config(self):
        """加载配置"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if "last_project_path" in config and os.path.exists(config["last_project_path"]):
                    self.project_path.set(config["last_project_path"])

                self._log("配置已加载")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

    def _create_widgets(self):
        """创建UI组件"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 项目路径选择
        project_frame = ttk.LabelFrame(main_frame, text="项目配置", padding="5")
        project_frame.pack(fill=tk.X, pady=5)

        ttk.Label(project_frame, text="项目目录:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(project_frame, textvariable=self.project_path, width=60).grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.select_project_btn = ttk.Button(project_frame, text="浏览...", command=self._select_project_dir)
        self.select_project_btn.grid(row=0, column=2, padx=5, pady=5)

        # 版本提示
        version_info = ttk.Label(
            project_frame,
            text="提示: 请手动确保Node版本正确，脚本不会自动切换版本",
            foreground="orange"
        )
        version_info.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W)

        project_frame.columnconfigure(1, weight=1)

        # 操作按钮
        button_frame = ttk.LabelFrame(main_frame, text="打包操作", padding="5")
        button_frame.pack(fill=tk.X, pady=5)

        self.build_btn = ttk.Button(button_frame, text="执行 build", command=self._build_project, width=15)
        self.build_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.render2_btn = ttk.Button(button_frame, text="执行 render2", command=self._render2_project, width=15)
        self.render2_btn.pack(side=tk.LEFT, padx=10, pady=10)

        self.build_all_btn = ttk.Button(button_frame, text="都打包 (build + render2)", command=self._build_all, width=20)
        self.build_all_btn.pack(side=tk.LEFT, padx=10, pady=10)

        ttk.Button(button_frame, text="打开项目目录", command=self._open_project_dir).pack(side=tk.RIGHT, padx=10, pady=10)
        ttk.Button(button_frame, text="保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=10, pady=10)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="打包日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = NodePackagerApp(root)
    root.mainloop()
