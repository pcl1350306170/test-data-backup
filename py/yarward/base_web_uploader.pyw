# web_uploader.py — 前端 Web + 服务 JAR 一体化升级工具

import os
import json
import logging
import threading
import webbrowser
import time
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
import paramiko
from stat import S_ISDIR

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "base_web_uploader"
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
# 默认配置（含 JAR 部署配置）
DEFAULT_CONFIG = {
    "local_web_dir": r"G:\CODE\GIT\pcl1350306170.github.io",
    "server_host": "192.168.18.218",
    "server_username": "root",
    "server_password": "Yahua3585668",
    "remote_upload_dir": "/home/ym_clinic/ym801s/upload/baseweb",
    "exclude_patterns": [".git", ".idea"],
    # JAR 相关配置（复用前端服务器）
    "jar_path": r"C:\www\gitee\my-blog-api\target\base-service-3.0.0-SNAPSHOT.jar",
    "jar_upload_dir": "/usr/local/apps/base-service",
    "jar_server_port": "28019",
    "also_deploy_jar": False
}

# ================== 工具函数 ==================

def load_or_create_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 确保字段存在
            for key, val in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = val
            logger.info("配置文件加载成功")
            return config
        except Exception as e:
            logger.error(f"配置文件解析失败: {e}")
            messagebox.showerror("配置错误", f"配置文件损坏，将使用默认配置。\n{e}")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
    logger.info("已创建默认配置文件")
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        messagebox.showerror("保存失败", f"无法保存配置：{e}")

def should_exclude(path, exclude_patterns):
    """判断路径是否应被排除"""
    path_str = str(path).replace("\\", "/")
    for pattern in exclude_patterns:
        if pattern in path_str.split("/"):
            return True
    return False

def upload_directory(sftp, local_dir, remote_dir, exclude_patterns, progress_callback=None):
    """递归上传目录（过滤排除项）"""
    local_path = Path(local_dir)

    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        raise FileNotFoundError("Remote dir not exists")

    uploaded_count = 0
    for item in local_path.rglob("*"):
        if should_exclude(item, exclude_patterns):
            continue

        rel_path = item.relative_to(local_path)
        remote_path = f"{remote_dir.rstrip('/')}/{rel_path.as_posix()}"

        try:
            if item.is_file():
                remote_parent = "/".join(remote_path.split("/")[:-1])
                try:
                    sftp.stat(remote_parent)
                except FileNotFoundError:
                    parts = remote_parent.strip("/").split("/")
                    current = ""
                    for part in parts:
                        if not part:
                            continue
                        current += "/" + part
                        try:
                            sftp.stat(current)
                        except FileNotFoundError:
                            sftp.mkdir(current)

                if progress_callback:
                    progress_callback(f"上传: {rel_path}")
                sftp.put(str(item), remote_path)
                uploaded_count += 1
            elif item.is_dir():
                try:
                    sftp.stat(remote_path)
                except FileNotFoundError:
                    sftp.mkdir(remote_path)
        except Exception as e:
            logger.warning(f"跳过文件 {item}: {e}")
            if progress_callback:
                progress_callback(f"⚠️ 跳过: {rel_path} ({e})")

    return uploaded_count

# ================== Web 上传逻辑 ==================

def upload_web_files(config, progress_callback=None):
    """上传 Web 目录到服务器，返回 (success, ssh) — ssh 可供后续复用"""
    ssh = None
    try:
        local_dir = config["local_web_dir"]
        remote_dir = config["remote_upload_dir"]
        exclude_patterns = config.get("exclude_patterns", [".git", ".idea"])

        if not Path(local_dir).exists():
            raise FileNotFoundError(f"本地目录不存在: {local_dir}")

        if progress_callback:
            progress_callback("正在连接服务器...")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=config["server_host"],
            username=config["server_username"],
            password=config["server_password"],
            timeout=30
        )
        logger.info(f"已连接到服务器: {config['server_host']}")

        stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_dir}")
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            raise Exception(f"无法创建远程目录: {error}")

        sftp = ssh.open_sftp()

        if progress_callback:
            progress_callback(f"开始上传目录: {local_dir} → {remote_dir}")

        count = upload_directory(sftp, local_dir, remote_dir, exclude_patterns, progress_callback)

        sftp.close()

        logger.info(f"上传完成，共上传 {count} 个文件")
        if progress_callback:
            progress_callback(f"✅ 前端上传成功！共上传 {count} 个文件")

        url = f"http://{config['server_host']}:7000/upload/baseweb/num/index.html"
        if progress_callback:
            progress_callback(f"🌐 正在打开页面: {url}")
        webbrowser.open(url)

        return True, ssh

    except Exception as e:
        logger.error(f"上传失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 前端上传失败: {e}")
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
        return False, None

# ================== JAR 部署逻辑 ==================

def check_port_listening(ssh, port):
    """检查指定端口是否在监听"""
    stdin, stdout, stderr = ssh.exec_command("which ss")
    if stdout.read().strip().decode():
        stdin, stdout, stderr = ssh.exec_command(f"ss -tuln | grep :{port}")
    else:
        stdin, stdout, stderr = ssh.exec_command(f"netstat -tuln | grep :{port}")
    output = stdout.read().decode().strip()
    return len(output) > 0

def check_firewall_type(ssh):
    stdin, stdout, stderr = ssh.exec_command("which firewall-cmd")
    if stdout.read().strip().decode():
        return "firewalld"
    stdin, stdout, stderr = ssh.exec_command("which iptables")
    if stdout.read().strip().decode():
        return "iptables"
    return "unknown"

def check_iptables_rule_exists(ssh, port):
    stdin, stdout, stderr = ssh.exec_command(f"iptables -L -n | grep 'dpt:{port}'")
    output = stdout.read().decode().strip()
    return len(output) > 0

def add_iptables_rule(ssh, port, progress_callback=None):
    try:
        if check_iptables_rule_exists(ssh, port):
            if progress_callback:
                progress_callback(f"✅ iptables 端口 {port} 规则已存在")
            return True

        if progress_callback:
            progress_callback(f"正在添加 iptables 规则: {port}...")
        add_cmd = f"iptables -A INPUT -p tcp --dport {port} -j ACCEPT"
        stdin, stdout, stderr = ssh.exec_command(add_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status == 0:
            stdin, stdout, stderr = ssh.exec_command("service iptables save")
            save_status = stdout.channel.recv_exit_status()
            if save_status == 0:
                if progress_callback:
                    progress_callback(f"✅ iptables 端口 {port} 规则已添加并保存")
                return True
            else:
                if progress_callback:
                    progress_callback(f"⚠️ iptables 规则已添加，但保存失败（重启后需重新添加）")
                return True
        else:
            error = stderr.read().decode()
            raise Exception(f"添加 iptables 规则失败: {error}")
    except Exception as e:
        logger.error(f"添加 iptables 规则失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 添加 iptables 规则失败: {e}")
        return False

def check_and_configure_firewall(ssh, port, progress_callback=None):
    try:
        firewall_type = check_firewall_type(ssh)
        if firewall_type == "firewalld":
            stdin, stdout, stderr = ssh.exec_command(f"firewall-cmd --list-ports")
            current_ports = stdout.read().decode().strip()
            if f"{port}/tcp" not in current_ports:
                if progress_callback:
                    progress_callback(f"正在配置 firewalld 防火墙: {port}...")
                stdin, stdout, stderr = ssh.exec_command(f"firewall-cmd --permanent --add-port={port}/tcp")
                exit_status = stdout.channel.recv_exit_status()
                if exit_status == 0:
                    stdin, stdout, stderr = ssh.exec_command("firewall-cmd --reload")
                    stdout.channel.recv_exit_status()
                    if progress_callback:
                        progress_callback(f"✅ firewalld 端口 {port} 已开放")
                else:
                    error = stderr.read().decode()
                    if progress_callback:
                        progress_callback(f"⚠️ firewalld 配置失败: {error}")
            else:
                if progress_callback:
                    progress_callback(f"✅ firewalld 端口 {port} 已开放")
        elif firewall_type == "iptables":
            add_iptables_rule(ssh, port, progress_callback)
        else:
            if progress_callback:
                progress_callback("⚠️ 未检测到标准防火墙工具，可能需要手动配置")
        return True
    except Exception as e:
        logger.error(f"防火墙配置失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 防火墙配置失败: {e}")
        return False

def deploy_jar(config, ssh=None, progress_callback=None):
    """上传并运行 JAR 包。若 ssh 为 None 则新建连接（用完后自动关闭），否则复用已有连接。
    返回 True/False。"""
    own_ssh = False
    try:
        jar_path = config["jar_path"]
        jar_file = Path(jar_path)
        if not jar_file.exists():
            raise FileNotFoundError(f"JAR 文件不存在: {jar_path}")

        if ssh is None:
            if progress_callback:
                progress_callback("正在连接服务器...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=config["server_host"],
                username=config["server_username"],
                password=config["server_password"],
                timeout=30
            )
            own_ssh = True
            logger.info(f"已连接到服务器: {config['server_host']}")

        # 创建上传目录
        sftp = ssh.open_sftp()
        upload_dir = config["jar_upload_dir"]
        try:
            sftp.stat(upload_dir)
        except FileNotFoundError:
            if progress_callback:
                progress_callback(f"创建远程目录: {upload_dir}")
            ssh.exec_command(f"mkdir -p {upload_dir}")

        # 上传 JAR
        remote_jar_path = f"{upload_dir}/{jar_file.name}"
        if progress_callback:
            progress_callback(f"正在上传 JAR: {jar_file.name}")
        sftp.put(str(jar_file), remote_jar_path)
        sftp.close()
        logger.info(f"JAR 文件已上传至: {remote_jar_path}")

        # 停止旧进程
        if progress_callback:
            progress_callback("正在停止旧进程...")
        stop_cmd = f"pkill -f '{jar_file.name}' || true"
        stdin, stdout, stderr = ssh.exec_command(stop_cmd)
        stdout.channel.recv_exit_status()

        # 检测 Java 路径
        if progress_callback:
            progress_callback("正在检测 Java 环境...")
        stdin, stdout, stderr = ssh.exec_command("which java")
        java_path = stdout.read().strip().decode()
        if not java_path:
            for p in ["/usr/bin/java", "/usr/local/java/bin/java", "/opt/java/bin/java"]:
                stdin, stdout, stderr = ssh.exec_command(f"test -f {p} && echo exists")
                if stdout.read().strip().decode() == "exists":
                    java_path = p
                    break
        if not java_path:
            raise Exception("服务器上未找到 Java 命令")
        logger.info(f"Java 路径: {java_path}")

        # 防火墙
        server_port = config.get("jar_server_port", "8080")
        check_and_configure_firewall(ssh, server_port, progress_callback)

        # 启动 JAR
        if progress_callback:
            progress_callback(f"正在启动 JAR... (端口: {server_port})")
        run_cmd = (f"cd {upload_dir} && nohup {java_path} -Djava.net.preferIPv4Stack=false "
                   f"-jar {jar_file.name} --server.address=0.0.0.0 --server.port={server_port} > app.log 2>&1 &")
        stdin, stdout, stderr = ssh.exec_command(run_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error = stderr.read().decode()
            raise Exception(f"启动失败: {error}")

        logger.info("JAR 启动命令已发送")
        time.sleep(10)

        if check_port_listening(ssh, server_port):
            logger.info(f"✅ JAR 启动成功，端口 {server_port} 监听中")
            if progress_callback:
                progress_callback(f"✅ JAR 已成功部署并运行！端口: {server_port}")
                progress_callback(f"📋 访问地址: http://{config['server_host']}:{server_port}")
            return True

        # 重试一次
        time.sleep(5)
        if check_port_listening(ssh, server_port):
            logger.info(f"✅ JAR 启动成功，端口 {server_port} 监听中")
            if progress_callback:
                progress_callback(f"✅ JAR 已成功部署并运行！端口: {server_port}")
                progress_callback(f"📋 访问地址: http://{config['server_host']}:{server_port}")
            return True

        msg = f"⚠️ JAR 启动后端口 {server_port} 未监听，请检查 app.log"
        logger.warning(msg)
        if progress_callback:
            progress_callback(msg)
        return False

    except Exception as e:
        logger.error(f"JAR 部署失败: {e}")
        if progress_callback:
            progress_callback(f"❌ JAR 部署失败: {e}")
        return False
    finally:
        if own_ssh and ssh:
            try:
                ssh.close()
            except Exception:
                pass

# ================== Toast 通知 ==================

def show_toast(title, message, color="#4CAF50", duration=180000):
    """右下角 toast 通知，duration 毫秒后自动关闭"""
    toast = Toplevel()
    toast.overrideredirect(True)
    toast.configure(bg=color)

    lbl_title = Label(toast, text=title, font=("Microsoft YaHei", 11, "bold"),
                      fg="white", bg=color, anchor="w", padx=12, pady=(8, 0))
    lbl_title.pack(fill=X)
    lbl_msg = Label(toast, text=message, font=("Microsoft YaHei", 9),
                    fg="white", bg=color, anchor="w", wraplength=320, justify=LEFT,
                    padx=12, pady=(2, 10))
    lbl_msg.pack(fill=X)

    toast.update_idletasks()
    w = toast.winfo_reqwidth() + 20
    h = toast.winfo_reqheight() + 10
    sw = toast.winfo_screenwidth()
    sh = toast.winfo_screenheight()
    x, y = sw - w - 20, sh - h - 80

    # Windows 上 overrideredirect 窗口需要用 after 延迟设置 geometry 才能可靠显示
    toast.geometry(f"{w}x{h}+{x + 10000}+{y + 10000}")  # 先放到屏幕外
    toast.deiconify()
    toast.lift()

    def _move_to_position():
        toast.geometry(f"{w}x{h}+{x}+{y}")
        toast.attributes("-topmost", True)
        toast.focus_force()
        toast.after(duration, toast.destroy)

    toast.after(50, _move_to_position)

# ================== GUI 类 ==================

class WebUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🌐 Web + JAR 一体化升级工具")
        self.root.geometry("820x680")
        self.root.resizable(True, True)

        self.config = load_or_create_config()
        self.setup_ui()

    def setup_ui(self):
        # ---- 1. 本地 Web 目录 ----
        frame_local = LabelFrame(self.root, text="1. 本地 Web 目录", padx=10, pady=10)
        frame_local.pack(fill=X, padx=20, pady=10)

        self.local_dir_var = StringVar(value=self.config["local_web_dir"])
        Entry(frame_local, textvariable=self.local_dir_var, width=70, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_local, text="📁 选择目录", command=self.select_local_dir).pack(side=LEFT, padx=5)

        # ---- 2. 排除模式 ----
        frame_exclude = LabelFrame(self.root, text="2. 排除文件/目录（用逗号分隔）", padx=10, pady=10)
        frame_exclude.pack(fill=X, padx=20, pady=10)

        exclude_str = ",".join(self.config.get("exclude_patterns", [".git", ".idea"]))
        self.exclude_var = StringVar(value=exclude_str)
        Entry(frame_exclude, textvariable=self.exclude_var, width=80).pack(padx=5)

        # ---- 3. 服务器配置（前端+服务共用） ----
        server_frame = LabelFrame(self.root, text="3. 服务器配置（前端 & 服务共用）", padx=10, pady=10)
        server_frame.pack(fill=X, padx=20, pady=10)

        Label(server_frame, text="主机:", font=("Arial", 10)).grid(row=0, column=0, sticky=W, padx=5)
        self.host_var = StringVar(value=self.config["server_host"])
        Entry(server_frame, textvariable=self.host_var, width=15).grid(row=0, column=1, padx=5)

        Label(server_frame, text="用户名:", font=("Arial", 10)).grid(row=0, column=2, sticky=W, padx=5)
        self.username_var = StringVar(value=self.config["server_username"])
        Entry(server_frame, textvariable=self.username_var, width=12).grid(row=0, column=3, padx=5)

        Label(server_frame, text="密码:", font=("Arial", 10)).grid(row=0, column=4, sticky=W, padx=5)
        self.password_var = StringVar(value=self.config["server_password"])
        Entry(server_frame, textvariable=self.password_var, show="*", width=15).grid(row=0, column=5, padx=5)

        Label(server_frame, text="前端远程目录:", font=("Arial", 10)).grid(row=1, column=0, sticky=W, padx=5, pady=(10, 0))
        self.remote_dir_var = StringVar(value=self.config["remote_upload_dir"])
        Entry(server_frame, textvariable=self.remote_dir_var, width=60).grid(row=1, column=1, columnspan=5, padx=5, pady=(10, 0), sticky=W)

        # ---- 4. 是否升级服务（复选框） ----
        link_frame = Frame(self.root)
        link_frame.pack(pady=(5, 0))
        self.also_deploy_jar = BooleanVar(value=self.config.get("also_deploy_jar", False))
        Checkbutton(link_frame, text="🔗 同时升级对应服务(JAR)",
                    variable=self.also_deploy_jar, font=("Microsoft YaHei", 10),
                    fg="#1565C0", command=self.toggle_jar_frame).pack()

        # ---- 5. JAR 配置区（可折叠） ----
        self.jar_frame = LabelFrame(self.root, text="4. 服务 JAR 配置", padx=10, pady=10)

        self.jar_path_var = StringVar(value=self.config.get("jar_path", ""))
        jar_row = Frame(self.jar_frame)
        jar_row.pack(fill=X, pady=(0, 5))
        Label(jar_row, text="JAR 文件:", font=("Arial", 10)).pack(side=LEFT, padx=5)
        Entry(jar_row, textvariable=self.jar_path_var, width=55, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(jar_row, text="📁 选择", command=self.select_jar).pack(side=LEFT, padx=5)

        jar_row2 = Frame(self.jar_frame)
        jar_row2.pack(fill=X)
        Label(jar_row2, text="上传目录:", font=("Arial", 10)).pack(side=LEFT, padx=5)
        self.jar_upload_dir_var = StringVar(value=self.config.get("jar_upload_dir", "/usr/local/apps/base-service"))
        Entry(jar_row2, textvariable=self.jar_upload_dir_var, width=40).pack(side=LEFT, padx=5)
        Label(jar_row2, text="应用端口:", font=("Arial", 10)).pack(side=LEFT, padx=(20, 5))
        self.jar_port_var = StringVar(value=self.config.get("jar_server_port", "28019"))
        Entry(jar_row2, textvariable=self.jar_port_var, width=8).pack(side=LEFT, padx=5)

        # 初始状态根据复选框决定
        self.toggle_jar_frame()

        # ---- 按钮区 ----
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)

        Button(btn_frame, text="💾 保存配置", command=self.save_config, bg="#9C27B0", fg="white", width=12).grid(row=0, column=0, padx=10)
        Button(btn_frame, text="🚀 开始升级", command=self.execute, bg="#4CAF50", fg="white", width=18, height=2).grid(row=0, column=1, padx=10)
        Button(btn_frame, text="📦 单独部署", command=self.execute_jar_only, bg="#FF9800", fg="white", width=18, height=2).grid(row=0, column=2, padx=10)

        # ---- 进度显示 ----
        self.progress_label = Label(self.root, text="就绪", fg="green", font=("Arial", 12))
        self.progress_label.pack(fill=X, padx=20, pady=(5, 2))

        # ---- 日志输出（固定在最底部） ----
        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=10)
        log_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10), side=BOTTOM)

        self.log_text = Text(log_frame, height=12, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    # ---- UI 辅助 ----

    def toggle_jar_frame(self):
        """根据复选框状态显示/隐藏 JAR 配置区"""
        if self.also_deploy_jar.get():
            self.jar_frame.pack(fill=X, padx=20, pady=10)
        else:
            self.jar_frame.pack_forget()

    def select_local_dir(self):
        dir_path = filedialog.askdirectory(
            title="选择本地 Web 目录",
            initialdir=self.config["local_web_dir"]
        )
        if dir_path:
            self.local_dir_var.set(dir_path)

    def select_jar(self):
        file_path = filedialog.askopenfilename(
            title="选择 JAR 文件",
            filetypes=[("JAR files", "*.jar"), ("All files", "*.*")],
            initialdir=Path(self.jar_path_var.get()).parent if self.jar_path_var.get() else "."
        )
        if file_path:
            self.jar_path_var.set(file_path)

    def save_config(self):
        exclude_list = [x.strip() for x in self.exclude_var.get().split(",") if x.strip()]
        self.config.update({
            "local_web_dir": self.local_dir_var.get(),
            "server_host": self.host_var.get(),
            "server_username": self.username_var.get(),
            "server_password": self.password_var.get(),
            "remote_upload_dir": self.remote_dir_var.get(),
            "exclude_patterns": exclude_list,
            "jar_path": self.jar_path_var.get(),
            "jar_upload_dir": self.jar_upload_dir_var.get(),
            "jar_server_port": self.jar_port_var.get(),
            "also_deploy_jar": self.also_deploy_jar.get()
        })
        save_config(self.config)
        messagebox.showinfo("保存成功", "配置已保存！")
        logger.info("配置已保存")

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    def update_progress(self, msg):
        self.progress_label.config(text=msg)
        self.root.update_idletasks()

    # ---- 主执行逻辑 ----

    def execute(self):
        # 验证前端配置
        local_dir = self.local_dir_var.get().strip()
        if not local_dir or not Path(local_dir).exists():
            messagebox.showerror("错误", "请选择有效的本地 Web 目录！")
            return

        # 验证 JAR 配置（如果勾选了）
        if self.also_deploy_jar.get():
            jar_path = self.jar_path_var.get().strip()
            if not jar_path or not Path(jar_path).exists():
                messagebox.showerror("错误", "请选择有效的 JAR 文件！")
                return
            jar_port = self.jar_port_var.get().strip()
            if not jar_port.isdigit() or not (1 <= int(jar_port) <= 65535):
                messagebox.showerror("错误", "请输入有效的 JAR 应用端口 (1-65535)！")
                return

        # 保存配置
        self.save_config()

        do_jar = self.also_deploy_jar.get()
        phase = "前端 + 服务" if do_jar else "前端"
        self.update_progress(f"开始升级 ({phase})...")
        self.log_to_gui(f"===== 开始升级：{phase} =====")

        def run_execute():
            cb = lambda msg: self.root.after(0, lambda: self.update_progress(msg))

            # ---- 第一步：上传前端 ----
            self.root.after(0, lambda: self.log_to_gui(">>> 第一步：上传前端 Web 页面..."))
            web_ok, ssh = upload_web_files(self.config, progress_callback=cb)

            if web_ok:
                self.root.after(0, lambda: self.log_to_gui("✅ 前端上传完成！页面已自动打开。"))
            else:
                self.root.after(0, lambda: self.log_to_gui("❌ 前端上传失败，终止升级。"))
                self.root.after(0, lambda: self.update_progress("❌ 前端上传失败"))
                self.root.after(0, lambda: show_toast("升级失败", "前端 Web 上传失败，请查看日志", "#F44336"))
                return

            # ---- 第二步：部署 JAR（如果勾选） ----
            jar_ok = False
            if do_jar:
                self.root.after(0, lambda: self.log_to_gui(">>> 第二步：部署服务 JAR..."))
                self.root.after(0, lambda: self.update_progress("正在部署服务 JAR..."))

                # 复用前端上传的 SSH 连接
                jar_ok = deploy_jar(self.config, ssh=ssh, progress_callback=cb)

                if jar_ok:
                    self.root.after(0, lambda: self.log_to_gui("✅ 服务 JAR 部署完成！"))
                else:
                    self.root.after(0, lambda: self.log_to_gui("❌ 服务 JAR 部署失败。"))

            # 关闭 SSH 连接（前端上传时建立的）
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass

            # ---- 最终通知 ----
            if do_jar:
                if jar_ok:
                    self.root.after(0, lambda: self.update_progress("✅ 前端 + 服务 全部升级完成！"))
                    self.root.after(0, lambda: show_toast("升级完成", "前端 + 服务 已全部升级完成！", "#4CAF50"))
                else:
                    self.root.after(0, lambda: self.update_progress("⚠️ 前端完成，服务升级失败"))
                    self.root.after(0, lambda: show_toast("部分失败", "前端升级成功，服务 JAR 升级失败", "#F44336"))
            else:
                self.root.after(0, lambda: self.update_progress("✅ 前端升级完成！"))
                self.root.after(0, lambda: show_toast("升级完成", "前端 Web 页面已成功上传！", "#4CAF50"))

        threading.Thread(target=run_execute, daemon=True).start()

    # ---- 单独部署 JAR ----

    def execute_jar_only(self):
        """仅部署 JAR，不上传前端"""
        # 验证 JAR 配置
        jar_path = self.jar_path_var.get().strip()
        if not jar_path or not Path(jar_path).exists():
            messagebox.showerror("错误", "请选择有效的 JAR 文件！")
            return
        jar_port = self.jar_port_var.get().strip()
        if not jar_port.isdigit() or not (1 <= int(jar_port) <= 65535):
            messagebox.showerror("错误", "请输入有效的 JAR 应用端口 (1-65535)！")
            return

        # 保存配置
        self.save_config()

        self.update_progress("开始单独部署服务 JAR...")
        self.log_to_gui("===== 开始单独部署服务 JAR =====")

        def run_jar_only():
            cb = lambda msg: self.root.after(0, lambda: self.update_progress(msg))

            self.root.after(0, lambda: self.log_to_gui(">>> 正在部署服务 JAR..."))
            jar_ok = deploy_jar(self.config, ssh=None, progress_callback=cb)

            if jar_ok:
                self.root.after(0, lambda: self.log_to_gui("✅ 服务 JAR 单独部署完成！"))
                self.root.after(0, lambda: self.update_progress("✅ 服务 JAR 部署完成！"))
                self.root.after(0, lambda: show_toast("部署完成", "服务 JAR 已成功部署并运行！", "#4CAF50"))
            else:
                self.root.after(0, lambda: self.log_to_gui("❌ 服务 JAR 部署失败。"))
                self.root.after(0, lambda: self.update_progress("❌ 服务 JAR 部署失败"))
                self.root.after(0, lambda: show_toast("部署失败", "服务 JAR 部署失败，请查看日志", "#F44336"))

        threading.Thread(target=run_jar_only, daemon=True).start()

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = WebUploaderApp(root)
    root.mainloop()
