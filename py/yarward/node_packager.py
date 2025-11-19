import os
import sys
import subprocess
import json
import platform
import ctypes
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime
import threading

# 配置与常量
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
        self.is_admin = self._check_admin()
        self.nvm_path = self._find_nvm()
        self.node_versions = []
        self.selected_node_version = tk.StringVar(value="14.19.1")
        self.project_path = tk.StringVar()
        self.is_packaging = False

        # 创建UI
        self._create_widgets()

        # 加载配置
        self._load_config()

        # 初始化Node版本列表
        self._load_node_versions()

    def _check_admin(self):
        """检查是否具有管理员权限"""
        try:
            if platform.system() == "Windows":
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            else:
                return os.geteuid() == 0
        except:
            return False

    def _request_admin(self):
        """请求管理员权限"""
        if platform.system() == "Windows":
            try:
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, " ".join(sys.argv), None, 1
                )
                sys.exit(0)
            except Exception as e:
                self._log(f"请求管理员权限失败: {str(e)}", logging.ERROR)
                return False
        else:
            try:
                subprocess.check_call(['sudo', 'echo', '获取管理员权限'])
                return True
            except:
                self._log("用户拒绝提供管理员权限", logging.WARNING)
                return False

    def _find_nvm(self):
        """查找NVM安装路径"""
        system = platform.system()
        try:
            if system == "Windows":
                # Windows常见NVM路径
                appdata = os.getenv("APPDATA")
                nvm_paths = [
                    Path(appdata) / "nvm/nvm.exe",
                    Path("C:/Program Files/nvm/nvm.exe")
                ]
                for path in nvm_paths:
                    if path.exists():
                        return str(path)

                # 检查环境变量
                for path in os.environ.get("PATH", "").split(os.pathsep):
                    if "nvm" in path and os.path.exists(os.path.join(path, "nvm.exe")):
                        return os.path.join(path, "nvm.exe")

            else:
                # Linux/macOS常见NVM路径
                home = os.getenv("HOME")
                nvm_paths = [
                    Path(home) / ".nvm/nvm.sh",
                    Path("/usr/local/nvm/nvm.sh")
                ]
                for path in nvm_paths:
                    if path.exists():
                        return str(path)

                # 检查环境变量
                try:
                    subprocess.check_output(["nvm", "--version"])
                    return "nvm"
                except:
                    pass

            self._log("未找到NVM，将使用系统默认Node", logging.WARNING)
            return None
        except Exception as e:
            self._log(f"查找NVM失败: {str(e)}", logging.ERROR)
            return None

    def _select_nvm_path(self):
        """手动选择NVM路径"""
        if not self.nvm_path:
            filetypes = []
            if platform.system() == "Windows":
                filetypes = [("NVM可执行文件", "nvm.exe"), ("所有文件", "*.*")]
            else:
                filetypes = [("NVM脚本", "nvm.sh"), ("所有文件", "*.*")]

            path = filedialog.askopenfilename(
                title="选择NVM文件",
                filetypes=filetypes
            )
            if path:
                self.nvm_path = path
                self.nvm_path_var.set(path)
                self._log(f"手动选择NVM路径: {path}")
                self._load_node_versions()

    def _load_node_versions(self):
        """加载Node版本列表"""
        self.node_versions = []
        try:
            if self.nvm_path:
                if platform.system() == "Windows":
                    # Windows下使用nvm list
                    result = subprocess.check_output(
                        [self.nvm_path, "list"],
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8'
                    )
                else:
                    # Linux/macOS下使用nvm list
                    result = subprocess.check_output(
                        ["/bin/bash", "-c", f"source {self.nvm_path} && nvm list"],
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8'
                    )

                # 解析版本信息
                for line in result.splitlines():
                    line = line.strip()
                    if line and (line.startswith('v') or line.startswith('*')):
                        version = line.lstrip('* ').split(' ')[0]
                        if version not in self.node_versions:
                            self.node_versions.append(version)

            # 检查系统默认Node
            try:
                system_node = subprocess.check_output(
                    ["node", "-v"],
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8'
                ).strip()
                if system_node not in self.node_versions:
                    self.node_versions.append(system_node)
            except:
                pass

            # 更新下拉列表
            if self.node_versions:
                self.node_version_combobox['values'] = sorted(self.node_versions, reverse=True)
                # 确保默认版本存在
                if self.selected_node_version.get() not in self.node_versions:
                    self.selected_node_version.set(self.node_versions[0])

            self._log(f"已加载Node版本列表，共 {len(self.node_versions)} 个版本")
        except Exception as e:
            self._log(f"加载Node版本失败: {str(e)}", logging.ERROR)
            # 至少添加默认版本
            if "14.19.1" not in self.node_versions:
                self.node_versions.append("14.19.1")
                self.node_version_combobox['values'] = self.node_versions

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

    def _run_npm_command(self, command):
        """运行npm命令"""
        if not self.project_path.get():
            messagebox.showerror("错误", "请先选择项目目录")
            return False

        project_dir = self.project_path.get()
        node_version = self.selected_node_version.get()

        try:
            self.is_packaging = True
            self._update_button_states()

            # 构建命令
            cmd = []
            if self.nvm_path and node_version:
                self._log(f"使用NVM切换到Node版本: {node_version}")
                if platform.system() == "Windows":
                    cmd = [self.nvm_path, "use", node_version, "&&", "npm", command]
                else:
                    cmd = ["/bin/bash", "-c", f"source {self.nvm_path} && nvm use {node_version} && npm {command}"]
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
                shell=platform.system() == "Windows"  # Windows需要shell=True才能使用&&
            )

            # 实时读取输出
            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        self._log(line.strip())

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
        if self._check_admin_rights():
            threading.Thread(target=self._run_npm_command, args=("run build",), daemon=True).start()

    def _render2_project(self):
        """执行render2打包"""
        if self._check_admin_rights():
            threading.Thread(target=self._run_npm_command, args=("run lib-render2",), daemon=True).start()

    def _build_all(self):
        """执行全部打包"""
        if not self._check_admin_rights():
            return

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

    def _check_admin_rights(self):
        """检查并获取管理员权限"""
        if not self.is_admin:
            self._log("需要管理员权限执行打包操作", logging.WARNING)
            if messagebox.askyesno("权限请求", "打包操作需要管理员权限，是否获取?"):
                return self._request_admin()
            else:
                return False
        return True

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
        self.refresh_versions_btn.config(state=state)

    def _save_config(self):
        """保存配置"""
        config = {
            "nvm_path": self.nvm_path,
            "selected_node_version": self.selected_node_version.get(),
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

                if "nvm_path" in config and os.path.exists(config["nvm_path"]):
                    self.nvm_path = config["nvm_path"]
                    self.nvm_path_var.set(self.nvm_path)

                if "selected_node_version" in config:
                    self.selected_node_version.set(config["selected_node_version"])

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

        # NVM配置
        nvm_frame = ttk.LabelFrame(main_frame, text="NVM配置", padding="5")
        nvm_frame.pack(fill=tk.X, pady=5)

        self.nvm_path_var = tk.StringVar(value=self.nvm_path or "")
        ttk.Label(nvm_frame, text="NVM路径:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(nvm_frame, textvariable=self.nvm_path_var, width=50).grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(nvm_frame, text="浏览...", command=self._select_nvm_path).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(nvm_frame, text="Node版本:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.node_version_combobox = ttk.Combobox(nvm_frame, textvariable=self.selected_node_version, width=47)
        self.node_version_combobox.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        self.refresh_versions_btn = ttk.Button(nvm_frame, text="刷新版本", command=self._load_node_versions)
        self.refresh_versions_btn.grid(row=1, column=2, padx=5, pady=5)

        nvm_frame.columnconfigure(1, weight=1)

        # 项目路径选择
        project_frame = ttk.LabelFrame(main_frame, text="项目配置", padding="5")
        project_frame.pack(fill=tk.X, pady=5)

        ttk.Label(project_frame, text="项目目录:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(project_frame, textvariable=self.project_path, width=50).grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.select_project_btn = ttk.Button(project_frame, text="浏览...", command=self._select_project_dir)
        self.select_project_btn.grid(row=0, column=2, padx=5, pady=5)

        # 显示管理员权限状态
        admin_status = "已获取管理员权限" if self.is_admin else "未获取管理员权限"
        admin_color = "green" if self.is_admin else "red"
        self.admin_label = ttk.Label(
            project_frame,
            text=f"权限状态: {admin_status}",
            foreground=admin_color
        )
        self.admin_label.grid(row=0, column=3, padx=10, pady=5, sticky=tk.E)

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
    # 检查是否已以管理员权限运行，如未则请求
    if platform.system() == "Windows" and not ctypes.windll.shell32.IsUserAnAdmin():
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1
            )
            sys.exit(0)
        except:
            pass  # 用户取消了管理员权限请求，继续以普通权限运行

    root = tk.Tk()
    app = NodePackagerApp(root)
    root.mainloop()
