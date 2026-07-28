# yarward_upgrade.pyw - 门诊前端/服务端升级工具

import os
import json
import logging
import threading
import time
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk, simpledialog, scrolledtext
from datetime import datetime

# ==============================
# 第三方库导入
# ==============================
try:
    import paramiko
except ImportError:
    paramiko = None

try:
    pass
except ImportError:
    pass

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "yarward_upgrade"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
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

# 服务端升级相关路径
SERVER_REMOTE_DIR = "/home/ym_clinic/ym801s_setup/application/webapps/server"
PUBLISH_SCRIPT = "publish_server.sh"

# 前端升级相关路径
FRONT_REMOTE_DIR = "/home/ym_clinic/ym801s_setup/application/webapps/front"
PUBLISH_FRONT_SCRIPT = "publish_front.sh"

# 本地 SVN 门诊目录（用于关键字搜索）
SVN_MENZ_BASE_DIR = Path(r"D:\CODE\Yarward\SVN\0门诊")

# ==============================
# 工具函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    return {"servers": {}, "last_server": "", "common_password": ""}

def save_config(data):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Config saved.")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")


# ==============================
# testServer.json 公共服务器配置
# ==============================
TEST_SERVER_PATH = CONFIG_DIR / "testServer.json"


def load_test_servers():
    """从 testServer.json 加载服务器配置"""
    if TEST_SERVER_PATH.exists():
        try:
            with open(TEST_SERVER_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 testServer.json 失败: {e}")
    return {}


def save_test_servers(data):
    """保存服务器配置到 testServer.json"""
    try:
        with open(TEST_SERVER_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("服务器配置已保存到 testServer.json")
    except Exception as e:
        logger.error(f"保存 testServer.json 失败: {e}")

def get_ssh_client(host, username="root", password="", timeout=10):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=username, password=password, timeout=timeout)
    return client

def ensure_remote_dir_exists(sftp, remote_path, progress_callback=None):
    """确保远程目录存在，不存在则递归创建"""
    try:
        sftp.stat(remote_path)
        if progress_callback:
            progress_callback(f"✅ 远程目录已存在: {remote_path}")
        return True
    except FileNotFoundError:
        if progress_callback:
            progress_callback(f"📁 创建远程目录: {remote_path}")
        parent_dir = '/'.join(remote_path.split('/')[:-1])
        if parent_dir:
            ensure_remote_dir_exists(sftp, parent_dir, progress_callback)
        try:
            sftp.mkdir(remote_path)
            logger.info(f"Created remote directory: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create remote directory {remote_path}: {e}")
            raise

# ==============================
# 关键字搜索与文件查找
# ==============================
def find_dirs_by_keyword(base_dir, keyword):
    """根据关键字搜索目录名称，返回匹配的目录路径列表"""
    results = []
    if not base_dir.exists():
        return results
    for item in base_dir.iterdir():
        if item.is_dir() and keyword.lower() in item.name.lower():
            results.append(item)
    return results


def find_war_files(directory, pattern="YM-801S-OSCS-*.war"):
    """在目录及其子目录中查找 war 包，返回 war 文件路径列表"""
    results = []
    directory = Path(directory)
    if not directory.exists():
        return results
    for war_file in directory.rglob(pattern):
        if war_file.is_file():
            results.append(war_file)
    return results


def find_zip_files(directory, pattern="YM-801S-*.zip"):
    """在目录及其子目录中查找 zip 包，返回 zip 文件路径列表"""
    results = []
    directory = Path(directory)
    if not directory.exists():
        return results
    for zip_file in directory.rglob(pattern):
        if zip_file.is_file():
            results.append(zip_file)
    return results


def do_front_upgrade(host, username, password, zip_paths, progress_callback):
    """前端升级：上传 zip 包并执行 publish_front.sh 脚本"""
    progress_callback(f"正在连接服务器 {host}...")
    with get_ssh_client(host, username=username, password=password) as ssh:
        sftp = ssh.open_sftp()
        ensure_remote_dir_exists(sftp, FRONT_REMOTE_DIR, progress_callback)

        # 上传所有 zip 包
        remote_zip_names = []
        for zip_path in zip_paths:
            zip_file = Path(zip_path)
            zip_name = zip_file.name
            remote_zip_path = f"{FRONT_REMOTE_DIR}/{zip_name}"
            progress_callback(f"正在上传: {zip_name}...")
            sftp.put(str(zip_file), remote_zip_path)
            progress_callback(f"✅ 已上传: {zip_name}")
            remote_zip_names.append(zip_name)

        sftp.close()

        # 逐个执行 publish_front.sh
        for zip_name in remote_zip_names:
            progress_callback(f"正在执行 {PUBLISH_FRONT_SCRIPT} {zip_name}...")
            cmd = f"cd {FRONT_REMOTE_DIR} && sh {PUBLISH_FRONT_SCRIPT} {zip_name}"
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
            for line in iter(stdout.readline, ""):
                if line:
                    progress_callback(line.strip())
            exit_status = stdout.channel.recv_exit_status()
            stderr_output = stderr.read().decode().strip()
            if stderr_output:
                progress_callback(f"[STDERR] {stderr_output}")
            if exit_status == 0:
                progress_callback(f"✅ {zip_name} 前端升级完成！")
            else:
                raise Exception(f"publish_front.sh {zip_name} 执行失败，返回码: {exit_status}")


def do_server_upgrade(host, username, password, war_path, progress_callback):
    """服务端升级：上传 war 包并执行 publish 脚本"""
    war_file = Path(war_path)
    war_name = war_file.name
    remote_war_path = f"{SERVER_REMOTE_DIR}/{war_name}"

    progress_callback(f"正在连接服务器 {host}...")
    with get_ssh_client(host, username=username, password=password) as ssh:
        sftp = ssh.open_sftp()

        # 确保远程目录存在
        ensure_remote_dir_exists(sftp, SERVER_REMOTE_DIR, progress_callback)

        # 上传 war 包
        progress_callback(f"正在上传 war 包: {war_name}...")
        sftp.put(str(war_file), remote_war_path)
        progress_callback(f"✅ war 包已上传到: {remote_war_path}")

        sftp.close()

        # 执行 publish 脚本
        progress_callback(f"正在执行 {PUBLISH_SCRIPT} {war_name}...")
        cmd = f"cd {SERVER_REMOTE_DIR} && sh {PUBLISH_SCRIPT} {war_name}"
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)

        # 实时读取输出
        for line in iter(stdout.readline, ""):
            if line:
                progress_callback(line.strip())

        exit_status = stdout.channel.recv_exit_status()
        stderr_output = stderr.read().decode().strip()
        if stderr_output:
            progress_callback(f"[STDERR] {stderr_output}")

        if exit_status == 0:
            progress_callback(f"✅ 服务端升级完成！")
        else:
            raise Exception(f"publish_server.sh 执行失败，返回码: {exit_status}")


# ==============================
# 历史记录管理
# ==============================
def load_history(config):
    """加载历史记录"""
    return {
        "frontend": config.get("history_frontend", []),
        "server": config.get("history_server", [])
    }


def save_frontend_history(config, record):
    """保存前端升级历史记录（最多50条）"""
    history = config.get("history_frontend", [])
    # 去重：按服务器+zip包名
    key = f"{record['server']}_{record.get('zip_names', '')}"
    history = [r for r in history if f"{r.get('server', '')}_{r.get('zip_names', '')}" != key]
    history.insert(0, record)
    history = history[:50]
    config["history_frontend"] = history
    save_config(config)
    return history


def save_server_history(config, record):
    """保存服务端升级历史记录（最多50条）"""
    history = config.get("history_server", [])
    # 去重：按服务器+war包名
    key = f"{record['server']}_{record.get('war_name', '')}"
    history = [r for r in history if f"{r.get('server', '')}_{r.get('war_name', '')}" != key]
    history.insert(0, record)
    history = history[:50]
    config["history_server"] = history
    save_config(config)
    return history

# ==============================
# GUI
# ==============================
class YarwardUpgradeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Yarward 门诊前端/服务端 升级工具")
        self.root.geometry("800x750")
        self.root.minsize(700, 600)

        self.config = load_config()

        # 从 testServer.json 加载服务器列表，并迁移旧配置
        self.test_servers = load_test_servers()
        old_servers = self.config.get("servers", {})
        if old_servers:
            migrated = False
            for host, pwd in old_servers.items():
                if host not in self.test_servers:
                    self.test_servers[host] = {
                        "link": host,
                        "name": "root",
                        "password": pwd if isinstance(pwd, str) else ""
                    }
                    migrated = True
            if migrated:
                save_test_servers(self.test_servers)
            self.config.pop("servers", None)
            save_config(self.config)

        # 前端升级相关变量
        self.front_matched_dirs = []  # 前端关键字搜索匹配的目录列表
        self.front_found_zip_files = []  # 找到的 zip 包列表
        self.front_selected_zips = []  # 选中的 zip 包列表
        self.front_svn_dir_name = ""  # 前端当前匹配的SVN目录名称

        # 服务端升级相关变量
        self.matched_dirs = []  # 关键字搜索匹配的目录列表
        self.found_war_files = []  # 找到的 war 包列表
        self.server_svn_dir_name = ""  # 服务端当前匹配的SVN目录名称

        self.create_widgets()

    def create_widgets(self):
        main = ttk.Frame(self.root, padding=5)
        main.pack(fill=BOTH, expand=True)

        # 服务器配置（共用）
        frame_server = LabelFrame(main, text="🖥️ 服务器配置", padx=10, pady=5)
        frame_server.pack(pady=5, fill=X)

        Label(frame_server, text="服务器:").grid(row=0, column=0, sticky=W, pady=3)
        self.server_var = StringVar(value=self.config.get("last_server", ""))
        server_list = list(self.test_servers.keys())
        if not server_list:
            server_list = [""]
        self.server_combo = ttk.Combobox(
            frame_server, textvariable=self.server_var, values=server_list,
            width=25, state="normal"
        )
        self.server_combo.grid(row=0, column=1, padx=5, pady=3)
        self.server_combo.bind("<<ComboboxSelected>>", self.on_server_selected)
        self.server_combo.bind("<KeyRelease>", self.on_server_typed)

        Label(frame_server, text="用户名:").grid(row=0, column=2, sticky=W, pady=3, padx=(10, 0))
        self.username_var = StringVar(value="root")
        Entry(frame_server, textvariable=self.username_var, width=10).grid(row=0, column=3, padx=5, pady=3)

        Label(frame_server, text="密码:").grid(row=1, column=0, sticky=W, pady=3)
        self.pwd_var = StringVar()
        Entry(frame_server, textvariable=self.pwd_var, width=25, show="*").grid(row=1, column=1, padx=5, pady=3)
        Button(frame_server, text="💾 保存配置", command=self.save_server_config).grid(row=0, column=4, rowspan=2, padx=10)

        # 加载初始服务器信息
        if self.server_var.get() and self.server_var.get() in self.test_servers:
            srv = self.test_servers[self.server_var.get()]
            self.pwd_var.set(srv.get("password", ""))
            self.username_var.set(srv.get("name", "root"))

        # Notebook 标签页
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=BOTH, expand=True, pady=5)

        # 标签页1：前端升级
        tab_frontend = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab_frontend, text="🌐 前端升级")
        self.create_frontend_tab(tab_frontend)

        # 标签页2：服务端升级
        tab_server = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab_server, text="⚙️ 服务端升级")
        self.create_server_tab(tab_server)

        # 标签页3：历史记录
        tab_history = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab_history, text="📜 历史记录")
        self.create_history_tab(tab_history)

        # 日志区域（底部共用）
        frame_log = LabelFrame(main, text="📝 升级日志")
        frame_log.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(frame_log, state=DISABLED, wrap=WORD, height=8, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

        # 进度条
        self.progress = ttk.Progressbar(main, mode='indeterminate')
        self.progress.pack(fill=X, pady=(0, 5))

    def create_frontend_tab(self, parent):
        """创建前端升级标签页"""
        # zip 包选择方式
        frame_zip = LabelFrame(parent, text="ZIP 包选择", padx=10, pady=5)
        frame_zip.pack(pady=5, fill=X)

        # 方式1：直接选择 zip 包
        row1 = Frame(frame_zip)
        row1.pack(fill=X, pady=3)
        Label(row1, text="直接选择:").pack(side=LEFT)
        self.front_zip_path_var = StringVar()
        Entry(row1, textvariable=self.front_zip_path_var, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=5)
        Button(row1, text="📁 选择 ZIP", command=self.select_front_zip_file).pack(side=RIGHT)

        # 方式2：关键字搜索
        row2 = Frame(frame_zip)
        row2.pack(fill=X, pady=3)
        Label(row2, text="关键字搜索:").pack(side=LEFT)
        self.front_keyword_var = StringVar()
        Entry(row2, textvariable=self.front_keyword_var, width=20).pack(side=LEFT, padx=5)
        Button(row2, text="🔍 搜索", command=self.search_front_by_keyword).pack(side=LEFT, padx=5)
        Label(row2, text=f"(在 {SVN_MENZ_BASE_DIR.name} 下搜索)", foreground="gray").pack(side=LEFT)

        # 搜索结果列表
        frame_result = LabelFrame(parent, text="搜索结果（双击选择目录）", padx=10, pady=5)
        frame_result.pack(pady=5, fill=BOTH, expand=True)

        self.front_search_listbox = Listbox(frame_result, height=4)
        self.front_search_listbox.pack(fill=BOTH, expand=True)
        self.front_search_listbox.bind("<Double-Button-1>", self.on_front_search_result_selected)

        # 找到的 zip 包列表（支持多选）
        frame_zip_list = LabelFrame(parent, text="找到的 ZIP 包（Ctrl+点击多选，双击全选）", padx=10, pady=5)
        frame_zip_list.pack(pady=5, fill=BOTH, expand=True)

        self.front_zip_listbox = Listbox(frame_zip_list, height=4, selectmode=EXTENDED)
        self.front_zip_listbox.pack(fill=BOTH, expand=True)
        self.front_zip_listbox.bind("<Double-Button-1>", self.on_front_zip_select_all)

        # 操作按钮
        btn_frame = Frame(parent)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="🚀 开始前端升级", command=self.start_frontend_upgrade,
               bg="#4CAF50", fg="white", width=18, height=2).pack()

    def create_server_tab(self, parent):
        """创建服务端升级标签页"""
        # war 包选择方式
        frame_war = LabelFrame(parent, text="WAR 包选择", padx=10, pady=5)
        frame_war.pack(pady=5, fill=X)

        # 方式1：直接选择 war 包
        row1 = Frame(frame_war)
        row1.pack(fill=X, pady=3)
        Label(row1, text="直接选择:").pack(side=LEFT)
        self.war_path_var = StringVar()
        Entry(row1, textvariable=self.war_path_var, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=5)
        Button(row1, text="📁 选择 WAR", command=self.select_war_file).pack(side=RIGHT)

        # 方式2：关键字搜索
        row2 = Frame(frame_war)
        row2.pack(fill=X, pady=3)
        Label(row2, text="关键字搜索:").pack(side=LEFT)
        self.war_keyword_var = StringVar()
        Entry(row2, textvariable=self.war_keyword_var, width=20).pack(side=LEFT, padx=5)
        Button(row2, text="🔍 搜索", command=self.search_war_by_keyword).pack(side=LEFT, padx=5)
        Label(row2, text=f"(在 {SVN_MENZ_BASE_DIR.name} 下搜索)", foreground="gray").pack(side=LEFT)

        # 搜索结果列表
        frame_result = LabelFrame(parent, text="搜索结果（双击选择目录）", padx=10, pady=5)
        frame_result.pack(pady=5, fill=BOTH, expand=True)

        self.search_result_listbox = Listbox(frame_result, height=4)
        self.search_result_listbox.pack(fill=BOTH, expand=True)
        self.search_result_listbox.bind("<Double-Button-1>", self.on_search_result_selected)

        # 找到的 war 包列表
        frame_war_list = LabelFrame(parent, text="找到的 WAR 包（双击选择）", padx=10, pady=5)
        frame_war_list.pack(pady=5, fill=BOTH, expand=True)

        self.war_listbox = Listbox(frame_war_list, height=4)
        self.war_listbox.pack(fill=BOTH, expand=True)
        self.war_listbox.bind("<Double-Button-1>", self.on_war_file_selected)

        # 操作按钮
        btn_frame = Frame(parent)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="🚀 开始服务端升级", command=self.start_server_upgrade,
               bg="#FF9800", fg="white", width=18, height=2).pack()

    def create_history_tab(self, parent):
        """创建历史记录标签页"""
        # 使用 Notebook 区分前端/服务端历史
        history_notebook = ttk.Notebook(parent)
        history_notebook.pack(fill=BOTH, expand=True)

        # 前端历史
        tab_fe_hist = ttk.Frame(history_notebook, padding=5)
        history_notebook.add(tab_fe_hist, text="🌐 前端升级历史")
        self.create_history_list(tab_fe_hist, "frontend")

        # 服务端历史
        tab_sv_hist = ttk.Frame(history_notebook, padding=5)
        history_notebook.add(tab_sv_hist, text="⚙️ 服务端升级历史")
        self.create_history_list(tab_sv_hist, "server")

    def create_history_list(self, parent, history_type):
        """创建历史记录列表"""
        frame = Frame(parent)
        frame.pack(fill=BOTH, expand=True)

        listbox = Listbox(frame, font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(frame, orient=VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)
        listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        listbox.bind("<Double-Button-1>", lambda e, t=history_type: self.load_history_record(t))

        # 保存引用
        if history_type == "frontend":
            self.frontend_history_listbox = listbox
        else:
            self.server_history_listbox = listbox

        # 按钮区
        btn_frame = Frame(parent)
        btn_frame.pack(fill=X, pady=5)
        Button(btn_frame, text="📥 加载选中记录", command=lambda: self.load_history_record(history_type)).pack(side=LEFT, padx=5)
        Button(btn_frame, text="🗑️ 删除选中记录", command=lambda: self.delete_history_record(history_type)).pack(side=LEFT, padx=5)
        Label(parent, text="💡 双击记录可加载配置并再次升级", foreground="gray").pack(anchor=W)

        # 刷新显示
        self.refresh_history_listbox(history_type)

    def _log(self, message):
        """写入日志到 GUI 和文件"""
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(message)

    def _show_toast(self, title, message, level="info", duration_ms=180000):
        """屏幕右下角弹出消息提醒"""
        toast = Toplevel(self.root)
        toast.withdraw()
        toast.overrideredirect(True)
        toast.attributes('-topmost', True)

        colors = {
            "success": ("#2e7d32", "#e8f5e9", "✅"),
            "error":   ("#c62828", "#ffebee", "❌"),
            "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
        }
        fg, bg, icon = colors.get(level, colors["info"])
        toast.configure(bg=bg)

        header = Frame(toast, bg=bg)
        header.pack(fill=X, padx=10, pady=8)
        Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
              fg=fg, bg=bg).pack(side=LEFT)
        close_btn = Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
        close_btn.pack(side=RIGHT)
        close_btn.bind("<Button-1>", lambda e: toast.destroy())

        Label(toast, text=message, font=("Microsoft YaHei UI", 10),
              fg="#333", bg=bg, wraplength=320, justify=LEFT).pack(padx=12, pady=(4, 10), anchor=W)

        toast.update_idletasks()
        w, h = toast.winfo_width(), toast.winfo_height()
        sx = toast.winfo_screenwidth()
        sy = toast.winfo_screenheight()
        x = sx - w - 20
        y = sy - h - 60
        toast.geometry(f"+{x}+{y}")
        toast.deiconify()
        toast.after(duration_ms, toast.destroy)

    # ==============================
    # 服务器配置相关
    # ==============================
    def on_server_selected(self, event=None):
        """当选中已有服务器时，自动填入密码"""
        host = self.server_var.get().strip()
        if host in self.test_servers:
            srv = self.test_servers[host]
            self.pwd_var.set(srv.get("password", ""))
            self.username_var.set(srv.get("name", "root"))
        else:
            self.pwd_var.set("")

    def on_server_typed(self, event=None):
        """当手动输入服务器时，清空密码（除非恰好匹配已存）"""
        host = self.server_var.get().strip()
        if host in self.test_servers:
            srv = self.test_servers[host]
            self.pwd_var.set(srv.get("password", ""))
            self.username_var.set(srv.get("name", "root"))
        else:
            self.pwd_var.set("")

    def save_server_config(self):
        server = self.server_var.get().strip()
        pwd = self.pwd_var.get().strip()
        username = self.username_var.get().strip() or "root"
        if not server or not pwd:
            messagebox.showwarning("警告", "请填写服务器地址和密码！")
            return
        self.config["last_server"] = server
        # 保存到 testServer.json
        if server not in self.test_servers:
            self.test_servers[server] = {"link": server}
        self.test_servers[server]["name"] = username
        self.test_servers[server]["password"] = pwd
        save_test_servers(self.test_servers)
        save_config(self.config)
        # 更新下拉框选项
        self.server_combo['values'] = list(self.test_servers.keys())
        messagebox.showinfo("成功", "服务器配置已保存！")

    def _get_server_credentials(self):
        """获取服务器连接信息，返回 (host, username, password) 或 None"""
        host = self.server_var.get().strip()
        if not host:
            messagebox.showerror("错误", "请输入服务器地址！")
            return None

        username = self.username_var.get().strip() or "root"
        password = self.pwd_var.get().strip()

        if password:
            return host, username, password

        # 尝试从 testServer.json 获取
        if host in self.test_servers:
            srv = self.test_servers[host]
            password = srv.get("password", "")
            username = srv.get("name", username)
            if password:
                self.pwd_var.set(password)
                self.username_var.set(username)
                return host, username, password

        # 尝试默认密码
        DEFAULT_PASSWORDS = ["Yahua3585668", "yh123456", "Huawei@123"]
        for pwd in DEFAULT_PASSWORDS:
            try:
                self._log(f"尝试默认密码: {pwd}")
                self.root.update_idletasks()
                test_client = get_ssh_client(host, username=username, password=pwd, timeout=5)
                test_client.close()
                password = pwd
                self.pwd_var.set(pwd)
                # 保存到 testServer.json
                if host not in self.test_servers:
                    self.test_servers[host] = {"link": host}
                self.test_servers[host]["name"] = username
                self.test_servers[host]["password"] = pwd
                save_test_servers(self.test_servers)
                return host, username, password
            except Exception:
                continue

        # 所有默认密码都失败，弹出手动输入
        pwd_input = simpledialog.askstring(
            "密码错误",
            f"默认密码均无法连接 {host}。\n请手动输入 {username} 密码：",
            parent=self.root
        )
        if not pwd_input:
            return None
        password = pwd_input
        self.pwd_var.set(password)
        # 保存到 testServer.json
        if host not in self.test_servers:
            self.test_servers[host] = {"link": host}
        self.test_servers[host]["name"] = username
        self.test_servers[host]["password"] = password
        save_test_servers(self.test_servers)
        return host, username, password

    # ==============================
    # 前端升级相关
    # ==============================
    def select_front_zip_file(self):
        """直接选择 zip 包文件"""
        path = filedialog.askopenfilename(
            title="选择 ZIP 包文件",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if path:
            self.front_zip_path_var.set(path)
            self.front_selected_zips = [path]
            # 清空搜索结果
            self.front_search_listbox.delete(0, END)
            self.front_zip_listbox.delete(0, END)
            self.front_matched_dirs = []
            self.front_found_zip_files = []

    def search_front_by_keyword(self):
        """根据关键字搜索目录并查找 zip 包"""
        keyword = self.front_keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入搜索关键字！")
            return

        self._log(f"前端搜索关键字: {keyword}")
        self.front_search_listbox.delete(0, END)
        self.front_zip_listbox.delete(0, END)
        self.front_matched_dirs = []
        self.front_found_zip_files = []
        self.front_selected_zips = []

        # 搜索匹配的目录
        matched = find_dirs_by_keyword(SVN_MENZ_BASE_DIR, keyword)
        if not matched:
            messagebox.showinfo("提示", f"未找到包含 '{keyword}' 的目录")
            return

        self.front_matched_dirs = matched
        for d in matched:
            self.front_search_listbox.insert(END, str(d))

        self._log(f"找到 {len(matched)} 个匹配目录")

        # 如果只有一个目录，自动展开查找 zip 包
        if len(matched) == 1:
            self._find_front_zips_in_dir(matched[0])

    def on_front_search_result_selected(self, event=None):
        """双击搜索结果目录，查找其中的 zip 包"""
        sel = self.front_search_listbox.curselection()
        if not sel or sel[0] >= len(self.front_matched_dirs):
            return
        selected_dir = self.front_matched_dirs[sel[0]]
        self._find_front_zips_in_dir(selected_dir)

    def _find_front_zips_in_dir(self, directory):
        """在指定目录中查找 zip 包"""
        self._log(f"在 {directory.name} 中查找 ZIP 包...")
        self.front_svn_dir_name = directory.name  # 记录SVN目录名称
        zips = find_zip_files(directory)
        self.front_found_zip_files = zips
        self.front_zip_listbox.delete(0, END)

        if not zips:
            self._log(f"⚠️ 未找到 YM-801S-*.zip 文件")
            return

        for z in zips:
            self.front_zip_listbox.insert(END, z.name)

        self._log(f"找到 {len(zips)} 个 ZIP 包")

        # 如果只有一个 zip，自动选中
        if len(zips) == 1:
            self.front_zip_listbox.selection_set(0)
            self.front_selected_zips = [str(zips[0])]
            self.front_zip_path_var.set(str(zips[0]))

    def on_front_zip_select_all(self, event=None):
        """双击 zip 列表：如果未选中则全选，否则获取当前选中项"""
        if len(self.front_found_zip_files) == 0:
            return
        # 获取当前选中项
        sel = self.front_zip_listbox.curselection()
        if sel:
            self.front_selected_zips = [str(self.front_found_zip_files[i]) for i in sel]
        else:
            # 全选
            self.front_zip_listbox.select_set(0, END)
            self.front_selected_zips = [str(z) for z in self.front_found_zip_files]
        if self.front_selected_zips:
            names = ", ".join(Path(z).name for z in self.front_selected_zips)
            self._log(f"已选择 {len(self.front_selected_zips)} 个 ZIP 包: {names}")
            self.front_zip_path_var.set(names)

    def start_frontend_upgrade(self):
        creds = self._get_server_credentials()
        if not creds:
            return
        host, username, password = creds

        # 获取选中的 zip 包
        if self.front_found_zip_files:
            sel = self.front_zip_listbox.curselection()
            if sel:
                zip_paths = [str(self.front_found_zip_files[i]) for i in sel]
            elif self.front_selected_zips:
                zip_paths = self.front_selected_zips
            else:
                messagebox.showerror("错误", "请在 ZIP 包列表中选择要升级的文件！")
                return
        elif self.front_zip_path_var.get().strip():
            zip_paths = [self.front_zip_path_var.get().strip()]
        else:
            messagebox.showerror("错误", "请先选择或搜索 ZIP 包文件！")
            return

        # 验证所有文件存在
        for zp in zip_paths:
            if not Path(zp).is_file():
                messagebox.showerror("错误", f"文件不存在: {zp}")
                return

        self.progress.start(10)
        self._log("准备前端升级...")
        self.notebook.select(0)

        thread = threading.Thread(
            target=self.run_frontend_upgrade,
            args=(host, username, password, zip_paths),
            daemon=True
        )
        thread.start()

    def run_frontend_upgrade(self, host, username, password, zip_paths):
        try:
            def update_status(msg):
                self.root.after(0, lambda: self._log(msg))

            do_front_upgrade(host, username, password, zip_paths, update_status)

            # 保存历史记录
            zip_names = ", ".join(Path(zp).name for zp in zip_paths)
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "server": host,
                "username": username,
                "zip_paths": zip_paths,
                "zip_names": zip_names,
                "svn_dir": self.front_svn_dir_name
            }
            self.root.after(0, lambda: self._save_frontend_history_ui(record))

            self._log("=" * 40)
            self._log(f"🎉 服务器 {host} 前端升级完成！")
            self.root.after(0, lambda: self._show_toast("升级完成", f"服务器 {host} 前端升级完成！", "success"))
        except Exception as e:
            error_msg = f"前端升级失败：{str(e)}"
            self.root.after(0, lambda: self._show_toast("升级失败", error_msg, "error"))
            logger.exception("Frontend upgrade failed")
        finally:
            self.root.after(0, lambda: self.progress.stop())

    # ==============================
    # 服务端升级相关
    # ==============================
    def select_war_file(self):
        """直接选择 war 包文件"""
        path = filedialog.askopenfilename(
            title="选择 WAR 包文件",
            filetypes=[("WAR files", "*.war"), ("All files", "*.*")]
        )
        if path:
            self.war_path_var.set(path)
            # 清空搜索结果
            self.search_result_listbox.delete(0, END)
            self.war_listbox.delete(0, END)
            self.matched_dirs = []
            self.found_war_files = []

    def search_war_by_keyword(self):
        """根据关键字搜索目录并查找 war 包"""
        keyword = self.war_keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入搜索关键字！")
            return

        self._log(f"搜索关键字: {keyword}")
        self.search_result_listbox.delete(0, END)
        self.war_listbox.delete(0, END)
        self.matched_dirs = []
        self.found_war_files = []

        # 搜索匹配的目录
        matched = find_dirs_by_keyword(SVN_MENZ_BASE_DIR, keyword)
        if not matched:
            messagebox.showinfo("提示", f"未找到包含 '{keyword}' 的目录")
            return

        self.matched_dirs = matched
        for d in matched:
            self.search_result_listbox.insert(END, str(d))

        self._log(f"找到 {len(matched)} 个匹配目录")

        # 如果只有一个目录，自动展开查找 war 包
        if len(matched) == 1:
            self._find_wars_in_dir(matched[0])

    def on_search_result_selected(self, event=None):
        """双击搜索结果目录，查找其中的 war 包"""
        sel = self.search_result_listbox.curselection()
        if not sel or sel[0] >= len(self.matched_dirs):
            return
        selected_dir = self.matched_dirs[sel[0]]
        self._find_wars_in_dir(selected_dir)

    def _find_wars_in_dir(self, directory):
        """在指定目录中查找 war 包"""
        self._log(f"在 {directory.name} 中查找 WAR 包...")
        self.server_svn_dir_name = directory.name  # 记录SVN目录名称
        wars = find_war_files(directory)
        self.found_war_files = wars
        self.war_listbox.delete(0, END)

        if not wars:
            self._log(f"⚠️ 未找到 YM-801S-OSCS-*.war 文件")
            return

        for w in wars:
            self.war_listbox.insert(END, str(w))

        self._log(f"找到 {len(wars)} 个 WAR 包")

        # 如果只有一个 war，自动选中
        if len(wars) == 1:
            self.war_listbox.selection_set(0)
            self.war_path_var.set(str(wars[0]))

    def on_war_file_selected(self, event=None):
        """双击选择 war 包"""
        sel = self.war_listbox.curselection()
        if not sel or sel[0] >= len(self.found_war_files):
            return
        selected_war = self.found_war_files[sel[0]]
        self.war_path_var.set(str(selected_war))
        self._log(f"已选择 WAR 包: {selected_war.name}")

    def start_server_upgrade(self):
        creds = self._get_server_credentials()
        if not creds:
            return
        host, username, password = creds

        war_path = self.war_path_var.get().strip()
        if not war_path or not Path(war_path).is_file():
            messagebox.showerror("错误", "请先选择有效的 WAR 包文件！")
            return

        self.progress.start(10)
        self._log("准备服务端升级...")
        self.notebook.select(1)  # 切换到服务端标签页

        thread = threading.Thread(
            target=self.run_server_upgrade,
            args=(host, username, password, war_path),
            daemon=True
        )
        thread.start()

    def run_server_upgrade(self, host, username, password, war_path):
        try:
            def update_status(msg):
                self.root.after(0, lambda: self._log(msg))

            war_name = Path(war_path).name
            do_server_upgrade(host, username, password, war_path, update_status)

            # 保存历史记录
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "server": host,
                "username": username,
                "war_path": war_path,
                "war_name": war_name,
                "svn_dir": self.server_svn_dir_name
            }
            self.root.after(0, lambda: self._save_server_history_ui(record))

            self._log("=" * 40)
            self._log(f"🎉 服务器 {host} 服务端升级完成！")
            self.root.after(0, lambda: self._show_toast("升级完成", f"服务器 {host} 服务端升级完成！", "success"))
        except Exception as e:
            error_msg = f"服务端升级失败：{str(e)}"
            self.root.after(0, lambda: self._show_toast("升级失败", error_msg, "error"))
            logger.exception("Server upgrade failed")
        finally:
            self.root.after(0, lambda: self.progress.stop())

    # ==============================
    # 历史记录相关
    # ==============================
    def _save_frontend_history_ui(self, record):
        """保存前端升级历史并刷新列表"""
        save_frontend_history(self.config, record)
        self.refresh_history_listbox("frontend")

    def _save_server_history_ui(self, record):
        """保存服务端升级历史并刷新列表"""
        save_server_history(self.config, record)
        self.refresh_history_listbox("server")

    def refresh_history_listbox(self, history_type):
        """刷新历史记录列表"""
        if history_type == "frontend":
            listbox = self.frontend_history_listbox
            history = self.config.get("history_frontend", [])
        else:
            listbox = self.server_history_listbox
            history = self.config.get("history_server", [])

        listbox.delete(0, END)
        for record in history:
            ts = record.get("timestamp", "")
            server = record.get("server", "")
            if history_type == "frontend":
                zip_names = record.get("zip_names", "")
                svn_dir = record.get("svn_dir", "")
                dir_info = f"[{svn_dir}]" if svn_dir else ""
                text = f"[{ts}] {server} {dir_info} - {zip_names}"
            else:
                war_name = record.get("war_name", "")
                svn_dir = record.get("svn_dir", "")
                dir_info = f"[{svn_dir}]" if svn_dir else ""
                text = f"[{ts}] {server} {dir_info} - {war_name}"
            listbox.insert(END, text)

    def load_history_record(self, history_type):
        """加载历史记录到界面"""
        if history_type == "frontend":
            listbox = self.frontend_history_listbox
            history = self.config.get("history_frontend", [])
        else:
            listbox = self.server_history_listbox
            history = self.config.get("history_server", [])

        sel = listbox.curselection()
        if not sel or sel[0] >= len(history):
            messagebox.showwarning("提示", "请先选择一条记录！")
            return

        record = history[sel[0]]

        # 恢复服务器信息
        server = record.get("server", "")
        username = record.get("username", "root")
        self.server_var.set(server)
        self.username_var.set(username)
        if server in self.test_servers:
            self.pwd_var.set(self.test_servers[server].get("password", ""))

        if history_type == "frontend":
            # 恢复前端升级配置
            zip_paths = record.get("zip_paths", [])
            if zip_paths:
                self.front_zip_path_var.set(", ".join(Path(z).name for z in zip_paths))
                self.front_selected_zips = zip_paths
            self.notebook.select(0)
            self._log(f"已加载前端升级历史: {record.get('timestamp', '')}")
        else:
            # 恢复服务端升级配置
            war_path = record.get("war_path", "")
            self.war_path_var.set(war_path)
            self.notebook.select(1)
            self._log(f"已加载服务端升级历史: {record.get('timestamp', '')}")

    def delete_history_record(self, history_type):
        """删除选中的历史记录"""
        if history_type == "frontend":
            listbox = self.frontend_history_listbox
            key = "history_frontend"
        else:
            listbox = self.server_history_listbox
            key = "history_server"

        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一条记录！")
            return

        history = self.config.get(key, [])
        if sel[0] >= len(history):
            return

        if messagebox.askyesno("确认删除", "确定删除这条历史记录吗？"):
            del history[sel[0]]
            self.config[key] = history
            save_config(self.config)
            self.refresh_history_listbox(history_type)

# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    missing = []
    if not paramiko:
        missing.append("paramiko")

    if missing:
        root = Tk()
        root.withdraw()
        msg = "缺少依赖库，请运行以下命令安装：\n\npip install " + " ".join(missing)
        messagebox.showerror("依赖缺失", msg)
        root.destroy()
        exit(1)

    # 加载 DB_CONFIG（虽不用，但按要求读取）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_config = json.load(f)
        except:
            pass

    root = Tk()
    app = YarwardUpgradeGUI(root)
    root.mainloop()
