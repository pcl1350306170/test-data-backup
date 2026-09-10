import os
import sys
import glob
import json
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

import paramiko


# ============================================================
# 默认配置
# ============================================================

DEFAULT_GEEKER_DIR = r"D:\CODE\Java\Geeker-Admin-Java"
DEFAULT_BLOG_DIR = r"D:\CODE\Java\my-blog-api"

# 前端项目默认配置：本地目录 => 远程目录
DEFAULT_FRONTEND_PROJECTS = {
    "geeker_admin": {
        "name": "Geeker Admin",
        "local_dir": r"D:\CODE\FontEnd\Geeker-Admin\dist",
        "remote_dir": "/home/projects/frontend/GeekerAdmin",
    },
    "blog_site": {
        "name": "pcl1350306170.github.io",
        "local_dir": r"D:\CODE\FontEnd\pcl1350306170.github.io",
        "remote_dir": "/home/projects/frontend/pcl1350306170.github.io",
    }
}

# 前端上传时需要忽略的目录
IGNORE_DIRS = {
    ".idea", ".lingma", ".git", ".svn", ".vscode",
    "node_modules", "__pycache__", ".cache", ".husky"
}

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "java_deployer"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# ──────────── 公共日志模块（可选依赖）────────────
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

DEFAULT_CONFIG = {
    "geeker_dir": DEFAULT_GEEKER_DIR,
    "blog_dir": DEFAULT_BLOG_DIR,
    "build_geeker": True,
    "build_blog": True,
    "frontend_projects": {
        key: {"local_dir": p["local_dir"], "remote_dir": p["remote_dir"]}
        for key, p in DEFAULT_FRONTEND_PROJECTS.items()
    }
}


def load_config():
    """加载配置，不存在或损坏时创建/返回默认配置"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info("配置文件加载成功")
        except Exception as e:
            logger.error(f"配置文件损坏，使用默认配置: {e}")
            config = DEFAULT_CONFIG.copy()
    else:
        config = DEFAULT_CONFIG.copy()

    # 兼容旧配置：补全缺失的前端项目配置
    front = config.setdefault("frontend_projects", {})
    for key, project in DEFAULT_FRONTEND_PROJECTS.items():
        front.setdefault(key, {
            "local_dir": project["local_dir"],
            "remote_dir": project["remote_dir"]
        })

    return config


def save_config(config):
    """保存配置到 json/config_java_deployer.json"""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

WSL_HOST = "127.0.0.1"
WSL_PORT = 22
WSL_USERNAME = "root"
WSL_PASSWORD = "123456"

REMOTE_DIR = "/home/projects/backend"

SERVICES = {
    "geeker": {
        "name": "Geeker Admin",
        "local_dir_key": "geeker_dir",
        "jar_name": "geeker-admin.jar",
        "service": "geeker-admin.service",
        "profile": "prod",
    },
    "blog": {
        "name": "My Blog API",
        "local_dir_key": "blog_dir",
        "jar_name": "my-blog-api.jar",
        "service": "my-blog-api.service",
        "profile": "wsl",
    }
}


# ============================================================
# GUI
# ============================================================

class JavaDeployer:

    def __init__(self, root):
        self.root = root
        self.root.title("WSL一键部署工具")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        self.config = load_config()

        self.geeker_dir = tk.StringVar(
            value=self.config.get("geeker_dir", DEFAULT_GEEKER_DIR)
        )
        self.blog_dir = tk.StringVar(
            value=self.config.get("blog_dir", DEFAULT_BLOG_DIR)
        )

        self.build_geeker = tk.BooleanVar(
            value=self.config.get("build_geeker", True)
        )
        self.build_blog = tk.BooleanVar(
            value=self.config.get("build_blog", True)
        )

        # 前端项目配置（本地目录 / 远程目录）
        front_config = self.config.get("frontend_projects", {})
        self.front_local_vars = {}
        self.front_remote_vars = {}

        for key, project in DEFAULT_FRONTEND_PROJECTS.items():
            saved = front_config.get(key, {})

            self.front_local_vars[key] = tk.StringVar(
                value=saved.get("local_dir", project["local_dir"])
            )
            self.front_remote_vars[key] = tk.StringVar(
                value=saved.get("remote_dir", project["remote_dir"])
            )

        self.front_upgrade_buttons = {}
        self.service_upgrade_buttons = {}

        self.status_text = tk.StringVar(value="就绪")

        self.build_ui()

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def build_ui(self):

        main = ttk.Frame(self.root, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        # 标题
        title = ttk.Label(
            main,
            text="WSL一键部署工具",
            font=("Microsoft YaHei UI", 18, "bold")
        )
        title.pack(anchor=tk.W, pady=(0, 15))

        # ----------------------------------------------------
        # 标签页：Java 服务部署 / 前端页面升级
        # ----------------------------------------------------

        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.X)

        java_tab = ttk.Frame(notebook, padding=10)
        notebook.add(java_tab, text="Java 服务部署")
        self.build_java_tab(java_tab)

        front_tab = ttk.Frame(notebook, padding=10)
        notebook.add(front_tab, text="前端页面升级")
        self.build_frontend_tab(front_tab)

        # ----------------------------------------------------
        # 状态（两个标签页共用）
        # ----------------------------------------------------

        ttk.Label(
            main,
            textvariable=self.status_text
        ).pack(anchor=tk.W, pady=(5, 3))

        # ----------------------------------------------------
        # 日志（两个标签页共用）
        # ----------------------------------------------------

        log_frame = ttk.LabelFrame(
            main,
            text="部署日志",
            padding=5
        )
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            font=("Consolas", 10)
        )

        scrollbar = ttk.Scrollbar(
            log_frame,
            orient=tk.VERTICAL,
            command=self.log_text.yview
        )

        self.log_text.configure(
            yscrollcommand=scrollbar.set
        )

        self.log_text.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True
        )

        scrollbar.pack(
            side=tk.RIGHT,
            fill=tk.Y
        )

    # --------------------------------------------------------
    # Java 服务部署标签页
    # --------------------------------------------------------

    def build_java_tab(self, tab):

        # ----------------------------------------------------
        # 项目配置
        # ----------------------------------------------------

        project_frame = ttk.LabelFrame(
            tab,
            text="项目配置",
            padding=10
        )
        project_frame.pack(fill=tk.X)

        # Geeker
        ttk.Label(
            project_frame,
            text="Geeker-Admin-Java："
        ).grid(row=0, column=0, sticky=tk.W, pady=6)

        ttk.Entry(
            project_frame,
            textvariable=self.geeker_dir
        ).grid(row=0, column=1, sticky=tk.EW, padx=8)

        ttk.Button(
            project_frame,
            text="选择目录",
            command=lambda: self.choose_dir(self.geeker_dir)
        ).grid(row=0, column=2)

        ttk.Checkbutton(
            project_frame,
            text="Maven打包",
            variable=self.build_geeker
        ).grid(row=0, column=3, padx=10)

        geeker_button = ttk.Button(
            project_frame,
            text="🚀 升级服务",
            command=lambda: self.start_service_deploy("geeker")
        )
        geeker_button.grid(row=0, column=4, padx=(0, 4))

        self.service_upgrade_buttons["geeker"] = geeker_button

        # Blog
        ttk.Label(
            project_frame,
            text="my-blog-api："
        ).grid(row=1, column=0, sticky=tk.W, pady=6)

        ttk.Entry(
            project_frame,
            textvariable=self.blog_dir
        ).grid(row=1, column=1, sticky=tk.EW, padx=8)

        ttk.Button(
            project_frame,
            text="选择目录",
            command=lambda: self.choose_dir(self.blog_dir)
        ).grid(row=1, column=2)

        ttk.Checkbutton(
            project_frame,
            text="Maven打包",
            variable=self.build_blog
        ).grid(row=1, column=3, padx=10)

        blog_button = ttk.Button(
            project_frame,
            text="🚀 升级服务",
            command=lambda: self.start_service_deploy("blog")
        )
        blog_button.grid(row=1, column=4, padx=(0, 4))

        self.service_upgrade_buttons["blog"] = blog_button

        project_frame.columnconfigure(1, weight=1)

        # ----------------------------------------------------
        # WSL 配置
        # ----------------------------------------------------

        wsl_frame = ttk.LabelFrame(
            tab,
            text="WSL 连接",
            padding=10
        )
        wsl_frame.pack(fill=tk.X, pady=10)

        ttk.Label(wsl_frame, text="地址：").grid(
            row=0, column=0, sticky=tk.W
        )

        ttk.Label(
            wsl_frame,
            text=f"{WSL_HOST}:{WSL_PORT}"
        ).grid(
            row=0, column=1, sticky=tk.W, padx=5
        )

        ttk.Label(wsl_frame, text="用户：").grid(
            row=0, column=2, sticky=tk.W, padx=(30, 0)
        )

        ttk.Label(
            wsl_frame,
            text=WSL_USERNAME
        ).grid(
            row=0, column=3, sticky=tk.W, padx=5
        )

        ttk.Label(wsl_frame, text="远程目录：").grid(
            row=1, column=0, sticky=tk.W, pady=6
        )

        ttk.Label(
            wsl_frame,
            text=REMOTE_DIR
        ).grid(
            row=1, column=1, columnspan=3,
            sticky=tk.W, padx=5
        )

        # ----------------------------------------------------
        # 操作按钮（升级按钮已放在各项目行内）
        # ----------------------------------------------------

        button_frame = ttk.Frame(tab)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(
            button_frame,
            text="测试 WSL 连接",
            command=self.test_connection
        ).pack(side=tk.LEFT, ipadx=10, ipady=8)

    # --------------------------------------------------------
    # 前端页面升级标签页
    # --------------------------------------------------------

    def build_frontend_tab(self, tab):

        # ----------------------------------------------------
        # 前端项目配置（本地目录 => 远程目录）
        # ----------------------------------------------------

        project_frame = ttk.LabelFrame(
            tab,
            text="前端项目配置",
            padding=10
        )
        project_frame.pack(fill=tk.X)

        ttk.Label(
            project_frame,
            text="升级时忽略目录：" + "、".join(sorted(IGNORE_DIRS)),
            foreground="#888888"
        ).grid(
            row=0, column=0, columnspan=4,
            sticky=tk.W, pady=(0, 6)
        )

        row = 1

        for key, project in DEFAULT_FRONTEND_PROJECTS.items():

            ttk.Label(
                project_frame,
                text=f"{project['name']}："
            ).grid(row=row, column=0, sticky=tk.W, pady=6)

            ttk.Entry(
                project_frame,
                textvariable=self.front_local_vars[key]
            ).grid(row=row, column=1, sticky=tk.EW, padx=8)

            ttk.Button(
                project_frame,
                text="选择目录",
                command=lambda v=self.front_local_vars[key]: self.choose_dir(v)
            ).grid(row=row, column=2)

            button = ttk.Button(
                project_frame,
                text="🚀 升级前端",
                command=lambda k=key: self.start_frontend_deploy(k)
            )
            button.grid(row=row, column=3, padx=10)

            self.front_upgrade_buttons[key] = button

            row += 1

            ttk.Label(
                project_frame,
                text="远程目录："
            ).grid(row=row, column=0, sticky=tk.W, pady=(0, 6))

            ttk.Entry(
                project_frame,
                textvariable=self.front_remote_vars[key]
            ).grid(row=row, column=1, columnspan=3, sticky=tk.EW, padx=8)

            row += 1

        project_frame.columnconfigure(1, weight=1)

    # --------------------------------------------------------
    # 日志
    # --------------------------------------------------------

    def log(self, message):

        logger.info(message)

        def append():
            now = time.strftime("%H:%M:%S")

            self.log_text.insert(
                tk.END,
                f"[{now}] {message}\n"
            )

            self.log_text.see(tk.END)

        self.root.after(0, append)

    def show_toast(self, title, message, level="info", duration_ms=3500):
        """右下角 Toast 通知：info（蓝）/ success（绿）/ warning（橙）/ error（红），自动消失，点击关闭"""

        def _show():
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)

            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error": ("#c62828", "#ffebee", "❌"),
                "warning": ("#ef6c00", "#fff3e0", "⚠️"),
                "info": ("#1565c0", "#e3f2fd", "ℹ️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)
            toast.bind("<Button-1>", lambda e: toast.destroy())

            header = tk.Frame(toast, bg=bg)
            header.pack(fill=tk.X, padx=10, pady=(8, 0))

            tk.Label(
                header, text=f"{icon} {title}",
                font=("Microsoft YaHei UI", 11, "bold"),
                fg=fg, bg=bg
            ).pack(side=tk.LEFT)

            close_btn = tk.Label(
                header, text="✕",
                font=("Consolas", 10),
                fg="#999", bg=bg, cursor="hand2"
            )
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())

            tk.Label(
                toast, text=message,
                font=("Microsoft YaHei UI", 10),
                fg="#333", bg=bg,
                wraplength=320, justify=tk.LEFT
            ).pack(padx=12, pady=(4, 10), anchor=tk.W)

            toast.update_idletasks()
            w = toast.winfo_width()
            h = toast.winfo_height()
            sx = toast.winfo_screenwidth()
            sy = toast.winfo_screenheight()
            toast.geometry(f"+{sx - w - 20}+{sy - h - 60}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)

        self.root.after(0, _show)

    def get_config_from_ui(self):
        """从界面收集当前配置"""
        frontend_projects = {}

        for key in DEFAULT_FRONTEND_PROJECTS:
            frontend_projects[key] = {
                "local_dir": self.front_local_vars[key].get(),
                "remote_dir": self.front_remote_vars[key].get()
            }

        return {
            "geeker_dir": self.geeker_dir.get(),
            "blog_dir": self.blog_dir.get(),
            "build_geeker": self.build_geeker.get(),
            "build_blog": self.build_blog.get(),
            "frontend_projects": frontend_projects
        }

    def save_current_config(self):
        save_config(self.get_config_from_ui())

    def set_status(self, text):

        self.root.after(
            0,
            lambda: self.status_text.set(text)
        )

    # --------------------------------------------------------
    # 选择目录
    # --------------------------------------------------------

    def choose_dir(self, variable):

        directory = filedialog.askdirectory()

        if directory:
            variable.set(directory)
            self.save_current_config()

    # --------------------------------------------------------
    # WSL SSH
    # --------------------------------------------------------

    def create_ssh(self):

        client = paramiko.SSHClient()

        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        client.connect(
            hostname=WSL_HOST,
            port=WSL_PORT,
            username=WSL_USERNAME,
            password=WSL_PASSWORD,
            timeout=10,
            look_for_keys=False,
            allow_agent=False
        )

        return client

    # --------------------------------------------------------
    # 测试连接
    # --------------------------------------------------------

    def test_connection(self):

        def worker():

            self.set_status("正在连接 WSL...")
            self.log("开始测试 WSL SSH 连接")

            try:

                client = self.create_ssh()

                stdin, stdout, stderr = client.exec_command(
                    "hostname && whoami && java -version 2>&1 | head -n 1"
                )

                output = stdout.read().decode(
                    "utf-8",
                    errors="replace"
                )

                error = stderr.read().decode(
                    "utf-8",
                    errors="replace"
                )

                client.close()

                self.log("WSL 连接成功")

                if output:
                    self.log(output.strip())

                if error:
                    self.log(error.strip())

                self.set_status("WSL 连接成功")
                self.show_toast("连接成功", "WSL SSH 连接成功！", "success")

            except Exception as e:

                self.log(f"WSL 连接失败：{e}")
                self.set_status("WSL 连接失败")
                self.show_toast("连接失败", str(e), "error")

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    # --------------------------------------------------------
    # Maven
    # --------------------------------------------------------

    def run_maven(self, project_dir):

        project_dir = Path(project_dir)

        # 优先使用项目自己的 Maven Wrapper
        mvnw = project_dir / "mvnw.cmd"

        if mvnw.exists():
            command = [
                str(mvnw),
                "clean",
                "package",
                "-DskipTests"
            ]
        else:
            command = [
                "mvn",
                "clean",
                "package",
                "-DskipTests"
            ]

        self.log(
            f"执行 Maven：{' '.join(command)}"
        )

        process = subprocess.Popen(
            command,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )

        for line in process.stdout:
            line = line.rstrip()

            if line:
                self.log(line)

        return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(
                f"Maven 打包失败，退出码：{return_code}"
            )

        self.log("Maven 打包成功")

    # --------------------------------------------------------
    # 自动寻找 JAR
    # --------------------------------------------------------

    def find_latest_jar(self, project_dir):

        target_dir = Path(project_dir) / "target"

        if not target_dir.exists():
            raise RuntimeError(
                f"没有找到 target 目录：{target_dir}"
            )

        jars = []

        for jar in target_dir.glob("*.jar"):

            name = jar.name.lower()

            # 排除 Maven 附属 JAR
            if (
                name.endswith("-sources.jar")
                or name.endswith("-javadoc.jar")
                or name.endswith(".original")
            ):
                continue

            jars.append(jar)

        if not jars:
            raise RuntimeError(
                f"target 中没有找到可部署 JAR：{target_dir}"
            )

        # 按修改时间选择最新
        jars.sort(
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )

        selected = jars[0]

        self.log(
            f"自动选择 JAR：{selected}"
        )

        return selected

    # --------------------------------------------------------
    # 部署单个服务
    # --------------------------------------------------------

    def deploy_service(
        self,
        client,
        service_key,
        project_dir,
        should_build
    ):

        config = SERVICES[service_key]

        service_name = config["name"]
        jar_name = config["jar_name"]
        service_unit = config["service"]

        self.log("")
        self.log("=" * 60)
        self.log(f"开始部署：{service_name}")
        self.log("=" * 60)

        # 1. Maven
        if should_build:

            self.log(
                f"{service_name}：开始 Maven 打包"
            )

            self.run_maven(project_dir)

        else:

            self.log(
                f"{service_name}：跳过 Maven 打包"
            )

        # 2. 找 JAR
        jar_path = self.find_latest_jar(
            project_dir
        )

        self.log(
            f"准备上传：{jar_path.name}"
        )

        # 3. 上传临时文件
        remote_tmp = (
            f"{REMOTE_DIR}/.{jar_name}.uploading"
        )

        remote_final = (
            f"{REMOTE_DIR}/{jar_name}"
        )

        sftp = client.open_sftp()

        try:

            self.log(
                f"上传到：{remote_tmp}"
            )

            sftp.put(
                str(jar_path),
                remote_tmp
            )

        finally:

            sftp.close()

        # 4. 原子替换 + 重启
        commands = [
            f"mv -f '{remote_tmp}' '{remote_final}'",
            f"chmod 755 '{remote_final}'",
            f"systemctl restart {service_unit}",
            f"systemctl is-active --quiet {service_unit}"
        ]

        command = " && ".join(commands)

        self.log(
            f"执行远程命令：{command}"
        )

        stdin, stdout, stderr = client.exec_command(
            command
        )

        exit_code = stdout.channel.recv_exit_status()

        output = stdout.read().decode(
            "utf-8",
            errors="replace"
        )

        error = stderr.read().decode(
            "utf-8",
            errors="replace"
        )

        if output.strip():
            self.log(output.strip())

        if error.strip():
            self.log(error.strip())

        if exit_code != 0:

            raise RuntimeError(
                f"{service_name} 重启失败\n"
                f"{error.strip()}"
            )

        self.log(
            f"✓ {service_name} 部署成功"
        )

    # --------------------------------------------------------
    # 单服务部署（分开升级）
    # --------------------------------------------------------

    def start_service_deploy(self, service_key):

        config = SERVICES[service_key]

        service_name = config["name"]

        if service_key == "geeker":
            project_dir = self.geeker_dir.get()
            should_build = self.build_geeker.get()
        else:
            project_dir = self.blog_dir.get()
            should_build = self.build_blog.get()

        if not os.path.isdir(project_dir):

            self.show_toast(
                "错误",
                f"{service_name} 目录不存在",
                "error"
            )
            return

        # 保存当前界面配置
        self.save_current_config()

        threading.Thread(
            target=self.service_deploy_worker,
            args=(service_key, project_dir, should_build),
            daemon=True
        ).start()

    # --------------------------------------------------------
    # 部署线程（单个服务）
    # --------------------------------------------------------

    def service_deploy_worker(
        self,
        service_key,
        project_dir,
        should_build
    ):

        service_name = SERVICES[service_key]["name"]

        button = self.service_upgrade_buttons.get(service_key)

        self.root.after(
            0,
            lambda: button and button.configure(state=tk.DISABLED)
        )

        client = None

        try:

            self.set_status("连接 WSL...")
            self.log("开始连接 WSL...")

            client = self.create_ssh()

            self.log("✓ WSL SSH 连接成功")

            self.set_status(
                f"正在部署 {service_name}..."
            )

            self.deploy_service(
                client,
                service_key,
                project_dir,
                should_build
            )

            self.set_status(
                f"✓ 部署完成：{service_name}"
            )

            self.show_toast(
                "部署完成",
                f"{service_name} 已经升级并重启成功！",
                "success",
                duration_ms=5000
            )

        except Exception as e:

            self.set_status("✗ 部署失败")

            logger.error(f"部署失败: {e}")

            self.log(f"✗ 部署失败：{e}")

            self.show_toast("部署失败", str(e), "error", duration_ms=6000)

        finally:

            if client:
                client.close()

            self.root.after(
                0,
                lambda: button and button.configure(state=tk.NORMAL)
            )

    # --------------------------------------------------------
    # 前端页面升级
    # --------------------------------------------------------

    def start_frontend_deploy(self, project_key):

        local_dir = self.front_local_vars[project_key].get().strip()
        remote_dir = self.front_remote_vars[project_key].get().strip()

        if not os.path.isdir(local_dir):

            self.show_toast("错误", f"本地目录不存在：{local_dir}", "error")
            return

        if not remote_dir:

            self.show_toast("错误", "远程目录不能为空", "error")
            return

        # 保存当前界面配置（含前端目录）
        self.save_current_config()

        threading.Thread(
            target=self.frontend_deploy_worker,
            args=(project_key, local_dir, remote_dir),
            daemon=True
        ).start()

    def frontend_deploy_worker(self, project_key, local_dir, remote_dir):

        project_name = DEFAULT_FRONTEND_PROJECTS[project_key]["name"]

        button = self.front_upgrade_buttons.get(project_key)

        self.root.after(
            0,
            lambda: button and button.configure(state=tk.DISABLED)
        )

        client = None

        try:

            self.set_status(f"正在升级前端：{project_name}...")

            self.log("")
            self.log("=" * 60)
            self.log(f"开始前端升级：{project_name}")
            self.log(f"本地：{local_dir}  =>  远程：{remote_dir}")
            self.log("=" * 60)

            client = self.create_ssh()

            self.log("✓ WSL SSH 连接成功")

            self.upload_frontend_dir(
                client,
                local_dir,
                remote_dir
            )

            self.set_status(f"✓ 前端升级完成：{project_name}")

            self.log(f"✓ {project_name} 前端升级成功")

            self.show_toast(
                "前端升级完成",
                f"{project_name} 已上传到 {remote_dir}",
                "success",
                duration_ms=5000
            )

        except Exception as e:

            self.set_status("✗ 前端升级失败")
            logger.error(f"前端升级失败: {e}")
            self.log(f"✗ 前端升级失败：{e}")
            self.show_toast(
                "前端升级失败",
                str(e),
                "error",
                duration_ms=6000
            )

        finally:

            if client:
                client.close()

            self.root.after(
                0,
                lambda: button and button.configure(state=tk.NORMAL)
            )

    def upload_frontend_dir(self, client, local_dir, remote_dir):
        """遍历本地目录，覆盖上传到远程目录（忽略 IGNORE_DIRS 中的目录）"""

        local_dir = Path(local_dir)

        # 确保远程根目录存在（mkdir -p）
        stdin, stdout, stderr = client.exec_command(
            f"mkdir -p '{remote_dir}'"
        )
        stdout.channel.recv_exit_status()

        sftp = client.open_sftp()

        file_count = 0

        try:

            for dirpath, dirnames, filenames in os.walk(local_dir):

                # 原地过滤，阻止 os.walk 进入忽略目录（含 .idea/.lingma 等）
                dirnames[:] = [
                    d for d in dirnames if d not in IGNORE_DIRS
                ]

                current = Path(dirpath)

                rel = current.relative_to(local_dir)

                remote_current = remote_dir

                if rel != Path("."):
                    remote_current = (
                        f"{remote_dir}/"
                        + rel.as_posix()
                    )

                    try:
                        sftp.stat(remote_current)
                    except IOError:
                        sftp.mkdir(remote_current)

                for filename in filenames:

                    local_file = str(current / filename)

                    remote_file = (
                        f"{remote_current}/{filename}"
                    )

                    # put 默认覆盖已存在的远程文件
                    sftp.put(local_file, remote_file)

                    file_count += 1

                    self.log(
                        f"上传：{rel.as_posix() + '/' if rel != Path('.') else ''}{filename}"
                    )

        finally:

            sftp.close()

        self.log(f"✓ 共上传 {file_count} 个文件")


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":

    root = tk.Tk()

    app = JavaDeployer(root)

    root.mainloop()
