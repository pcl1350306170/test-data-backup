# web_uploader.py

import os
import json
import logging
import threading
import webbrowser
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
PROCESS_LOG_FILE = CONFIG_DIR / "logs" / f"log_{SCRIPT_NAME}.log"
PROCESS_LOG_FILE.parent.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "local_web_dir": r"G:\CODE\GIT\pcl1350306170.github.io",
    "server_host": "192.168.18.218",
    "server_username": "root",
    "server_password": "Yahua3585668",
    "remote_upload_dir": "/home/ym_clinic/ym801s/upload/baseweb",
    "exclude_patterns": [".git", ".idea"]
}

# ================== 工具函数 ==================

def load_or_create_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 确保 exclude_patterns 存在
            if "exclude_patterns" not in config:
                config["exclude_patterns"] = DEFAULT_CONFIG["exclude_patterns"]
            logging.info("配置文件加载成功")
            return config
        except Exception as e:
            logging.error(f"配置文件解析失败: {e}")
            messagebox.showerror("配置错误", f"配置文件损坏，将使用默认配置。\n{e}")

    # 创建默认配置
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
    logging.info("已创建默认配置文件")
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logging.info("配置已保存")
    except Exception as e:
        logging.error(f"保存配置失败: {e}")
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

    # 确保远程目录存在
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        if progress_callback:
            progress_callback(f"创建远程目录: {remote_dir}")
        # 通过 SSH 执行 mkdir -p（SFTP 无法递归创建）
        raise FileNotFoundError("Remote dir not exists")  # 将由上层处理

    uploaded_count = 0
    for item in local_path.rglob("*"):
        if should_exclude(item, exclude_patterns):
            continue

        rel_path = item.relative_to(local_path)
        remote_path = f"{remote_dir.rstrip('/')}/{rel_path.as_posix()}"

        try:
            if item.is_file():
                # 确保远程父目录存在
                remote_parent = "/".join(remote_path.split("/")[:-1])
                try:
                    sftp.stat(remote_parent)
                except FileNotFoundError:
                    # 递归创建远程目录（简单方式：逐级创建）
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
            logging.warning(f"跳过文件 {item}: {e}")
            if progress_callback:
                progress_callback(f"⚠️ 跳过: {rel_path} ({e})")

    return uploaded_count

def upload_web_files(config, progress_callback=None):
    """上传 Web 目录到服务器"""
    try:
        local_dir = config["local_web_dir"]
        remote_dir = config["remote_upload_dir"]
        exclude_patterns = config.get("exclude_patterns", [".git", ".idea"])

        if not Path(local_dir).exists():
            raise FileNotFoundError(f"本地目录不存在: {local_dir}")

        # 连接服务器
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
        logging.info(f"已连接到服务器: {config['server_host']}")

        # 创建远程根目录（使用 SSH，因为 SFTP 不能递归 mkdir -p）
        stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_dir}")
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            raise Exception(f"无法创建远程目录: {error}")

        # 开启 SFTP
        sftp = ssh.open_sftp()

        # 上传目录
        if progress_callback:
            progress_callback(f"开始上传目录: {local_dir} → {remote_dir}")

        count = upload_directory(sftp, local_dir, remote_dir, exclude_patterns, progress_callback)

        sftp.close()
        ssh.close()

        logging.info(f"上传完成，共上传 {count} 个文件")
        if progress_callback:
            progress_callback(f"✅ 上传成功！共上传 {count} 个文件")

        # 自动打开浏览器
        url = f"http://{config['server_host']}:7000/upload/baseweb/num/index.html"
        if progress_callback:
            progress_callback(f"🌐 正在打开页面: {url}")
        webbrowser.open(url)

        return True

    except Exception as e:
        logging.error(f"上传失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 上传失败: {e}")
        return False

# ================== GUI 类 ==================

class WebUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🌐 Web 页面上传工具")
        self.root.geometry("800x550")
        self.root.resizable(True, True)

        self.config = load_or_create_config()
        self.setup_ui()

    def setup_ui(self):
        # 本地目录选择
        frame_local = LabelFrame(self.root, text="1. 本地 Web 目录", padx=10, pady=10)
        frame_local.pack(fill=X, padx=20, pady=10)

        self.local_dir_var = StringVar(value=self.config["local_web_dir"])
        Entry(frame_local, textvariable=self.local_dir_var, width=70, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_local, text="📁 选择目录", command=self.select_local_dir).pack(side=LEFT, padx=5)

        # 排除模式
        frame_exclude = LabelFrame(self.root, text="2. 排除文件/目录（用逗号分隔）", padx=10, pady=10)
        frame_exclude.pack(fill=X, padx=20, pady=10)

        exclude_str = ",".join(self.config.get("exclude_patterns", [".git", ".idea"]))
        self.exclude_var = StringVar(value=exclude_str)
        Entry(frame_exclude, textvariable=self.exclude_var, width=80).pack(padx=5)

        # 服务器配置
        server_frame = LabelFrame(self.root, text="3. 服务器配置", padx=10, pady=10)
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

        Label(server_frame, text="远程目录:", font=("Arial", 10)).grid(row=1, column=0, sticky=W, padx=5, pady=(10,0))
        self.remote_dir_var = StringVar(value=self.config["remote_upload_dir"])
        Entry(server_frame, textvariable=self.remote_dir_var, width=60).grid(row=1, column=1, columnspan=5, padx=5, pady=(10,0), sticky=W)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)

        Button(btn_frame, text="💾 保存配置", command=self.save_config, bg="#9C27B0", fg="white", width=12).grid(row=0, column=0, padx=10)
        Button(btn_frame, text="🚀 上传并打开页面", command=self.upload, bg="#4CAF50", fg="white", width=18, height=2).grid(row=0, column=1, padx=10)

        # 进度显示
        self.progress_label = Label(self.root, text="就绪", fg="green", font=("Arial", 12))
        self.progress_label.pack(pady=10)

        # 日志输出
        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=10)
        log_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))

        self.log_text = Text(log_frame, height=12, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    def select_local_dir(self):
        dir_path = filedialog.askdirectory(
            title="选择本地 Web 目录",
            initialdir=self.config["local_web_dir"]
        )
        if dir_path:
            self.local_dir_var.set(dir_path)

    def save_config(self):
        exclude_list = [x.strip() for x in self.exclude_var.get().split(",") if x.strip()]
        self.config.update({
            "local_web_dir": self.local_dir_var.get(),
            "server_host": self.host_var.get(),
            "server_username": self.username_var.get(),
            "server_password": self.password_var.get(),
            "remote_upload_dir": self.remote_dir_var.get(),
            "exclude_patterns": exclude_list
        })
        save_config(self.config)
        messagebox.showinfo("保存成功", "配置已保存！")
        logging.info("配置已保存")

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    def update_progress(self, msg):
        self.progress_label.config(text=msg)
        self.root.update_idletasks()

    def upload(self):
        local_dir = self.local_dir_var.get().strip()
        if not local_dir or not Path(local_dir).exists():
            messagebox.showerror("错误", "请选择有效的本地目录！")
            return

        # 保存配置
        self.save_config()

        self.update_progress("开始上传...")
        self.log_to_gui("开始上传 Web 页面...")

        def run_upload():
            success = upload_web_files(
                self.config,
                progress_callback=lambda msg: self.root.after(0, lambda: self.update_progress(msg))
            )
            if success:
                self.root.after(0, lambda: self.log_to_gui("✅ 上传完成！页面已自动打开。"))
            else:
                self.root.after(0, lambda: self.log_to_gui("❌ 上传失败，请查看日志。"))

        threading.Thread(target=run_upload, daemon=True).start()

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = WebUploaderApp(root)
    root.mainloop()
