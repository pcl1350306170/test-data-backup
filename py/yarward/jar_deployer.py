# jar_deployer_with_iptables.py

import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
import paramiko
import threading

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "jar_deployer"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "jar_path": r"C:\www\gitee\my-blog-api\target\base-service-3.0.0-SNAPSHOT.jar",
    "server_host": "192.168.18.218",
    "server_username": "root",
    "server_password": "Yahua3585668",
    "upload_dir": "/usr/local/apps/base-service",
    "server_port": "28019"
}

# ================== 工具函数 ==================

def load_or_create_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
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

def check_port_listening(ssh, port):
    """检查指定端口是否在监听（同时检查 IPv4 和 IPv6）"""
    # 优先使用 ss 命令
    stdin, stdout, stderr = ssh.exec_command("which ss")
    if stdout.read().strip().decode():
        # 使用 ss 命令
        stdin, stdout, stderr = ssh.exec_command(f"ss -tuln | grep :{port}")
    else:
        # 使用 netstat 命令
        stdin, stdout, stderr = ssh.exec_command(f"netstat -tuln | grep :{port}")

    output = stdout.read().decode().strip()
    return len(output) > 0

def check_firewall_type(ssh):
    """检查服务器使用哪种防火墙"""
    # 检查 firewalld
    stdin, stdout, stderr = ssh.exec_command("which firewall-cmd")
    if stdout.read().strip().decode():
        return "firewalld"

    # 检查 iptables
    stdin, stdout, stderr = ssh.exec_command("which iptables")
    if stdout.read().strip().decode():
        return "iptables"

    return "unknown"

def check_iptables_rule_exists(ssh, port):
    """检查 iptables 中是否已存在指定端口的规则"""
    stdin, stdout, stderr = ssh.exec_command(f"iptables -L -n | grep 'dpt:{port}'")
    output = stdout.read().decode().strip()
    return len(output) > 0

def add_iptables_rule(ssh, port, progress_callback=None):
    """为 iptables 添加端口规则"""
    try:
        # 检查规则是否已存在
        if check_iptables_rule_exists(ssh, port):
            if progress_callback:
                progress_callback(f"✅ iptables 端口 {port} 规则已存在")
            logging.info(f"iptables 端口 {port} 规则已存在")
            return True

        # 添加规则
        if progress_callback:
            progress_callback(f"正在添加 iptables 规则: {port}...")

        add_cmd = f"iptables -A INPUT -p tcp --dport {port} -j ACCEPT"
        stdin, stdout, stderr = ssh.exec_command(add_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status == 0:
            # 保存规则
            stdin, stdout, stderr = ssh.exec_command("service iptables save")
            save_status = stdout.channel.recv_exit_status()

            if save_status == 0:
                logging.info(f"iptables 端口 {port} 规则已添加并保存")
                if progress_callback:
                    progress_callback(f"✅ iptables 端口 {port} 规则已添加并保存")
                return True
            else:
                # 即使保存失败，规则也已生效（重启后失效）
                logging.warning(f"iptables 规则添加成功但保存失败，重启后需重新添加")
                if progress_callback:
                    progress_callback(f"⚠️ iptables 规则已添加，但保存失败（重启后需重新添加）")
                return True
        else:
            error = stderr.read().decode()
            raise Exception(f"添加 iptables 规则失败: {error}")

    except Exception as e:
        logging.error(f"添加 iptables 规则失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 添加 iptables 规则失败: {e}")
        return False

def check_and_configure_firewall(ssh, port, progress_callback=None):
    """检查并配置防火墙"""
    try:
        firewall_type = check_firewall_type(ssh)

        if firewall_type == "firewalld":
            # 检查 firewalld 端口
            stdin, stdout, stderr = ssh.exec_command(f"firewall-cmd --list-ports")
            current_ports = stdout.read().decode().strip()

            if f"{port}/tcp" not in current_ports:
                if progress_callback:
                    progress_callback(f"正在配置 firewalld 防火墙: {port}...")

                # 永久开放端口
                stdin, stdout, stderr = ssh.exec_command(f"firewall-cmd --permanent --add-port={port}/tcp")
                exit_status = stdout.channel.recv_exit_status()

                if exit_status == 0:
                    # 重新加载配置
                    stdin, stdout, stderr = ssh.exec_command("firewall-cmd --reload")
                    stdout.channel.recv_exit_status()
                    logging.info(f"firewalld 端口 {port} 已开放")
                    if progress_callback:
                        progress_callback(f"✅ firewalld 端口 {port} 已开放")
                else:
                    error = stderr.read().decode()
                    logging.warning(f"firewalld 配置失败: {error}")
                    if progress_callback:
                        progress_callback(f"⚠️ firewalld 配置失败: {error}")
            else:
                if progress_callback:
                    progress_callback(f"✅ firewalld 端口 {port} 已开放")

        elif firewall_type == "iptables":
            # 处理 iptables
            add_iptables_rule(ssh, port, progress_callback)

        else:
            if progress_callback:
                progress_callback("⚠️ 未检测到标准防火墙工具，可能需要手动配置")

        return True
    except Exception as e:
        logging.error(f"防火墙配置失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 防火墙配置失败: {e}")
        return False

def upload_and_run_jar(jar_path, server_config, progress_callback=None):
    """上传并运行 JAR 包"""
    try:
        jar_file = Path(jar_path)
        if not jar_file.exists():
            raise FileNotFoundError(f"JAR 文件不存在: {jar_path}")

        # 连接服务器
        if progress_callback:
            progress_callback("正在连接服务器...")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=server_config["server_host"],
            username=server_config["server_username"],
            password=server_config["server_password"],
            timeout=30
        )

        logging.info(f"已连接到服务器: {server_config['server_host']}")

        # 创建上传目录
        sftp = ssh.open_sftp()
        upload_dir = server_config["upload_dir"]

        # 检查并创建目录
        try:
            sftp.stat(upload_dir)
        except FileNotFoundError:
            if progress_callback:
                progress_callback(f"创建远程目录: {upload_dir}")
            ssh.exec_command(f"mkdir -p {upload_dir}")

        # 上传文件
        remote_jar_path = f"{upload_dir}/{jar_file.name}"
        if progress_callback:
            progress_callback(f"正在上传 JAR: {jar_file.name}")

        sftp.put(str(jar_file), remote_jar_path)
        sftp.close()

        logging.info(f"JAR 文件已上传至: {remote_jar_path}")

        # 停止之前的进程（如果存在）
        if progress_callback:
            progress_callback("正在停止旧进程...")

        # 查找并杀死旧进程
        stop_cmd = f"pkill -f '{jar_file.name}' || true"
        stdin, stdout, stderr = ssh.exec_command(stop_cmd)
        stdout.channel.recv_exit_status()  # 等待命令完成

        # 获取 Java 绝对路径
        if progress_callback:
            progress_callback("正在检测 Java 环境...")

        stdin, stdout, stderr = ssh.exec_command("which java")
        java_path = stdout.read().strip().decode()
        if not java_path or java_path == "":
            # 如果 which java 失败，尝试常见路径
            for common_path in ["/usr/bin/java", "/usr/local/java/bin/java", "/opt/java/bin/java", "/usr/lib/jvm/default-java/bin/java"]:
                stdin, stdout, stderr = ssh.exec_command(f"test -f {common_path} && echo exists")
                if stdout.read().strip().decode() == "exists":
                    java_path = common_path
                    break

        if not java_path or java_path == "":
            raise Exception("服务器上未找到 Java 命令，请确保 Java 已正确安装并添加到 PATH")

        logging.info(f"找到 Java 路径: {java_path}")

        # 检查并配置防火墙
        server_port = server_config.get("server_port", "8080")
        check_and_configure_firewall(ssh, server_port, progress_callback)

        # 后台运行 JAR（使用绝对路径的 Java，绑定到 0.0.0.0）
        if progress_callback:
            progress_callback(f"正在启动 JAR... (端口: {server_port})")

        # 使用绝对路径的 Java 命令，并指定绑定地址和端口
        run_cmd = f"cd {upload_dir} && nohup {java_path} -Djava.net.preferIPv4Stack=false -jar {jar_file.name} --server.address=0.0.0.0 --server.port={server_port} > app.log 2>&1 &"
        stdin, stdout, stderr = ssh.exec_command(run_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status == 0:
            logging.info("JAR 包启动命令已发送")

            # 等待应用启动
            import time
            time.sleep(10)  # 增加等待时间

            # 检查端口是否在监听
            if check_port_listening(ssh, server_port):
                logging.info(f"✅ JAR 包启动成功，端口 {server_port} 正在监听")
                if progress_callback:
                    progress_callback(f"✅ JAR 包已成功上传并后台运行！端口: {server_port}")

                # 显示访问地址
                access_url = f"http://{server_config['server_host']}:{server_port}"
                if progress_callback:
                    progress_callback(f"📋 访问地址: {access_url}")

                result = True
            else:
                # 再次检查
                time.sleep(5)
                if check_port_listening(ssh, server_port):
                    logging.info(f"✅ JAR 包启动成功，端口 {server_port} 正在监听")
                    if progress_callback:
                        progress_callback(f"✅ JAR 包已成功上传并后台运行！端口: {server_port}")

                    access_url = f"http://{server_config['server_host']}:{server_port}"
                    if progress_callback:
                        progress_callback(f"📋 访问地址: {access_url}")

                    result = True
                else:
                    error_msg = f"⚠️ JAR 启动后端口 {server_port} 未监听，请检查应用配置或日志文件 app.log"
                    logging.warning(error_msg)
                    if progress_callback:
                        progress_callback(error_msg)
                    result = False
        else:
            error = stderr.read().decode()
            raise Exception(f"启动失败: {error}")

        ssh.close()
        return result

    except Exception as e:
        logging.error(f"上传运行失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 失败: {e}")
        return False

# ================== 主GUI类 ==================

class JARDeployerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📦 JAR 包上传部署工具")
        self.root.geometry("750x500")
        self.root.resizable(True, True)

        self.config = load_or_create_config()

        self.setup_ui()

    def setup_ui(self):
        # JAR 文件选择
        frame_jar = LabelFrame(self.root, text="1. 选择 JAR 文件", padx=10, pady=10)
        frame_jar.pack(fill=X, padx=20, pady=10)

        self.jar_path_var = StringVar(value=self.config["jar_path"])
        Entry(frame_jar, textvariable=self.jar_path_var, width=60, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_jar, text="📁 选择文件", command=self.select_jar).pack(side=LEFT, padx=5)

        # 服务器配置
        server_frame = LabelFrame(self.root, text="2. 服务器配置", padx=10, pady=10)
        server_frame.pack(fill=X, padx=20, pady=10)

        # 主机
        Label(server_frame, text="主机地址:", font=("Arial", 10)).grid(row=0, column=0, sticky=W, padx=5)
        self.host_var = StringVar(value=self.config["server_host"])
        Entry(server_frame, textvariable=self.host_var, width=15).grid(row=0, column=1, padx=5)

        # 端口
        Label(server_frame, text="应用端口:", font=("Arial", 10)).grid(row=0, column=2, sticky=W, padx=5)
        self.port_var = StringVar(value=self.config.get("server_port", "28019"))
        Entry(server_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=5)

        # 用户名
        Label(server_frame, text="用户名:", font=("Arial", 10)).grid(row=1, column=0, sticky=W, padx=5)
        self.username_var = StringVar(value=self.config["server_username"])
        Entry(server_frame, textvariable=self.username_var, width=15).grid(row=1, column=1, padx=5)

        # 密码
        Label(server_frame, text="密码:", font=("Arial", 10)).grid(row=1, column=2, sticky=W, padx=5)
        self.password_var = StringVar(value=self.config["server_password"])
        Entry(server_frame, textvariable=self.password_var, show="*", width=15).grid(row=1, column=3, padx=5)

        # 上传目录
        Label(server_frame, text="上传目录:", font=("Arial", 10)).grid(row=2, column=0, sticky=W, padx=5)
        self.upload_dir_var = StringVar(value=self.config["upload_dir"])
        Entry(server_frame, textvariable=self.upload_dir_var, width=45).grid(row=2, column=1, columnspan=3, padx=5, sticky=W)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=20)

        Button(btn_frame, text="💾 保存配置", command=self.save_config, bg="#9C27B0", fg="white", width=12).grid(row=0, column=0, padx=10)
        Button(btn_frame, text="🚀 部署运行", command=self.deploy, bg="#4CAF50", fg="white", width=12, height=2).grid(row=0, column=1, padx=10)

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

    def select_jar(self):
        file_path = filedialog.askopenfilename(
            title="选择 JAR 文件",
            filetypes=[("JAR files", "*.jar"), ("All files", "*.*")],
            initialdir=Path(self.config["jar_path"]).parent
        )
        if file_path:
            self.jar_path_var.set(file_path)
            self.config["jar_path"] = file_path
            logging.info(f"选择 JAR 文件: {file_path}")

    def save_config(self):
        self.config.update({
            "jar_path": self.jar_path_var.get(),
            "server_host": self.host_var.get(),
            "server_username": self.username_var.get(),
            "server_password": self.password_var.get(),
            "upload_dir": self.upload_dir_var.get(),
            "server_port": self.port_var.get()
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

    def deploy(self):
        # 验证输入
        jar_path = self.jar_path_var.get().strip()
        if not jar_path or not Path(jar_path).exists():
            messagebox.showerror("错误", "请选择有效的 JAR 文件！")
            return

        server_port = self.port_var.get().strip()
        if not server_port.isdigit() or not (1 <= int(server_port) <= 65535):
            messagebox.showerror("错误", "请输入有效的端口号 (1-65535)！")
            return

        # 保存当前配置
        self.save_config()

        # 在新线程中执行部署，避免界面卡死
        self.update_progress("开始部署...")
        self.log_to_gui("开始部署 JAR 包...")

        def run_deploy():
            success = upload_and_run_jar(
                jar_path,
                self.config,
                progress_callback=lambda msg: self.root.after(0, lambda: self.update_progress(msg))
            )
            if success:
                self.root.after(0, lambda: self.log_to_gui("✅ 部署完成！JAR 已在服务器后台运行。"))
                # 显示访问地址
                access_url = f"http://{self.config['server_host']}:{self.config['server_port']}"
                self.root.after(0, lambda: self.log_to_gui(f"📋 可通过以下地址访问: {access_url}"))
            else:
                self.root.after(0, lambda: self.log_to_gui("❌ 部署失败，请查看日志详情。"))

        threading.Thread(target=run_deploy, daemon=True).start()

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = JARDeployerApp(root)
    root.mainloop()
