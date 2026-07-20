# yarward_upgrade.pyw

import os
import json
import logging
import threading
import time
import zipfile
import tempfile
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
    import httpx
except ImportError:
    httpx = None

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "yarward_upgrade"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# 服务器目标路径
DESIGN_REMOTE_PATH = "/home/ym_clinic/ym801s/webapps/tpleditor/design"
RENDER_REMOTE_PATH = "/home/ym_clinic/ym801s/webapps/tpleditor/resource/js/render-design"

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

def get_ssh_client(host, username="root", password="", timeout=10):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=username, password=password, timeout=timeout)
    return client

def clear_remote_dir(sftp, remote_path):
    """清空远程目录（递归删除所有文件和子目录）"""
    try:
        files = sftp.listdir(remote_path)
        for f in files:
            remote_file = f"{remote_path.rstrip('/')}/{f}"
            try:
                sftp.remove(remote_file)
            except IOError:
                # 可能是目录
                clear_remote_dir(sftp, remote_file)
                sftp.rmdir(remote_file)
    except Exception as e:
        logger.warning(f"Clear dir failed (may not exist): {remote_path}, error: {e}")

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

def upload_dir(sftp, local_dir, remote_dir):
    """递归上传本地目录到远程"""
    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir.rstrip('/')}/{item}"
        if os.path.isfile(local_path):
            sftp.put(local_path, remote_path)
            logger.debug(f"Uploaded: {local_path} -> {remote_path}")
        elif os.path.isdir(local_path):
            try:
                sftp.mkdir(remote_path)
            except:
                pass  # 可能已存在
            upload_dir(sftp, local_path, remote_path)

def notify_template_update(host, progress_callback):
    """升级完成后调用两个通知接口"""
    base_url = f"http://{host}:7000"
    endpoints = [
        "/clinic/api/irms/modeldesign/batchCreateHtml",
        "/clinic/api/irms/modelpush/batchDistribute"
    ]

    progress_callback("等待 2 秒后触发模板更新通知...")
    time.sleep(2)

    for i, endpoint in enumerate(endpoints, 1):
        url = base_url + endpoint
        progress_callback(f"正在调用通知接口 ({i}/2): {url}")
        try:
            if httpx:
                with httpx.Client(timeout=10) as client:
                    resp = client.post(url)
                    if resp.status_code == 200:
                        logger.info(f"通知成功: {url} -> {resp.status_code}")
                    else:
                        logger.warning(f"通知返回非200: {url} -> {resp.status_code}, {resp.text[:100]}")
            else:
                # fallback to urllib if httpx not available
                import urllib.request
                req = urllib.request.Request(url, method='POST')
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.getcode() == 200:
                        logger.info(f"通知成功 (urllib): {url}")
        except Exception as e:
            logger.error(f"调用通知接口失败: {url}, error: {e}")
            progress_callback(f"⚠️ 通知接口 ({i}) 调用失败，请手动检查！")

        if i == 1:
            time.sleep(1)  # 间隔 1 秒

# ==============================
# 升级逻辑
# ==============================
def do_directory_upgrade(host, password, local_project_dir, progress_callback):
    dist_dir = Path(local_project_dir) / "dist"
    lib_render_dir = Path(local_project_dir) / "lib-render-dist"

    missing_dirs = []
    if not dist_dir.exists():
        missing_dirs.append("dist")
    if not lib_render_dir.exists():
        missing_dirs.append("lib-render-dist")
    
    if missing_dirs:
        raise ValueError(f"项目目录下缺少以下目录：{', '.join(missing_dirs)}！请先打包。")

    progress_callback("正在连接服务器...")
    with get_ssh_client(host, password=password) as ssh:
        sftp = ssh.open_sftp()

        # 确保远程目录存在
        ensure_remote_dir_exists(sftp, DESIGN_REMOTE_PATH, progress_callback)
        
        progress_callback("清空 design 目录...")
        clear_remote_dir(sftp, DESIGN_REMOTE_PATH)
        progress_callback("上传 design 文件...")
        upload_dir(sftp, str(dist_dir), DESIGN_REMOTE_PATH)

        # 确保远程目录存在
        ensure_remote_dir_exists(sftp, RENDER_REMOTE_PATH, progress_callback)
        
        progress_callback("清空 render-design 目录...")
        clear_remote_dir(sftp, RENDER_REMOTE_PATH)
        progress_callback("上传 render-design 文件...")
        upload_dir(sftp, str(lib_render_dir), RENDER_REMOTE_PATH)

        sftp.close()
    progress_callback("✅ 目录升级完成！")

def do_package_upgrade(host, password, zip_path, progress_callback):
    """
    压缩包升级逻辑，支持两种目录结构：
    1. 旧版（1.5.5以下）：design/ + resource/js/render-design/
    2. 新版（1.5.5及以上）：design/ + resource/
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        progress_callback("解压压缩包...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tmpdir)

        extracted_items = list(Path(tmpdir).iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            root_dir = extracted_items[0]
        else:
            root_dir = Path(tmpdir)

        design_dir = root_dir / "design"
        
        # ✅ 检测是新版还是旧版目录结构
        new_resource_dir = root_dir / "resource"  # 新版：直接是 resource/
        old_resource_dir = root_dir / "resource" / "js" / "render-design"  # 旧版：resource/js/render-design/
        
        has_design = design_dir.exists()
        has_new_resource = new_resource_dir.exists() and not old_resource_dir.exists()
        has_old_resource = old_resource_dir.exists()
        
        if not has_design and not has_new_resource and not has_old_resource:
            raise ValueError("压缩包内缺少 design 和 resource 目录！无法进行升级。")
        
        if has_new_resource:
            # 新版结构（1.5.5+）
            resource_upload_dir = new_resource_dir
            progress_callback("✅ 检测到新版目录结构（1.5.5+）")
            logger.info(f"使用新版目录结构: resource/ -> {RENDER_REMOTE_PATH}")
        elif has_old_resource:
            # 旧版结构（1.5.5以下）
            resource_upload_dir = old_resource_dir
            progress_callback("✅ 检测到旧版目录结构（1.5.5以下）")
            logger.info(f"使用旧版目录结构: resource/js/render-design/ -> {RENDER_REMOTE_PATH}")
        else:
            resource_upload_dir = None
            progress_callback("⚠️ 压缩包中未找到 resource 目录，将跳过 resource 上传")
            logger.warning("压缩包中缺少 resource 目录")

        if not has_design:
            progress_callback("⚠️ 压缩包中未找到 design 目录，将跳过 design 上传")
            logger.warning("压缩包中缺少 design 目录")

        if not has_design and resource_upload_dir is None:
            raise ValueError("压缩包内既没有 design 也没有 resource 目录！无法进行升级。")

        progress_callback("正在连接服务器...")
        with get_ssh_client(host, password=password) as ssh:
            sftp = ssh.open_sftp()

            # 处理 design 目录
            if has_design:
                ensure_remote_dir_exists(sftp, DESIGN_REMOTE_PATH, progress_callback)
                
                progress_callback("清空 design 目录...")
                clear_remote_dir(sftp, DESIGN_REMOTE_PATH)
                progress_callback("上传 design 文件...")
                upload_dir(sftp, str(design_dir), DESIGN_REMOTE_PATH)
            else:
                progress_callback("⏭️ 跳过 design 目录上传（压缩包中不存在）")

            # 处理 resource 目录
            if resource_upload_dir is not None:
                ensure_remote_dir_exists(sftp, RENDER_REMOTE_PATH, progress_callback)
                
                progress_callback("清空 render-design 目录...")
                clear_remote_dir(sftp, RENDER_REMOTE_PATH)
                progress_callback("上传 render-design 文件...")
                upload_dir(sftp, str(resource_upload_dir), RENDER_REMOTE_PATH)
            else:
                progress_callback("⏭️ 跳过 render-design 目录上传（压缩包中不存在）")

            sftp.close()
        progress_callback("✅ 压缩包升级完成！")

# ==============================
# GUI
# ==============================
class YarwardUpgradeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Yarward 门诊前端一键升级")
        self.root.geometry("700x650")
        self.root.minsize(600, 500)

        self.config = load_config()
        self.create_widgets()

    def create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=BOTH, expand=True)

        # 服务器配置
        frame_server = LabelFrame(main, text="服务器配置", padx=10, pady=5)
        frame_server.pack(pady=5, fill=X)

        Label(frame_server, text="服务器地址:").grid(row=0, column=0, sticky=W, pady=3)
        self.server_var = StringVar()
        server_list = list(self.config.get("servers", {}).keys())
        if not server_list:
            server_list = [""]
        self.server_combo = ttk.Combobox(
            frame_server, textvariable=self.server_var, values=server_list,
            width=28, state="normal"
        )
        self.server_combo.grid(row=0, column=1, padx=5, pady=3)
        self.server_combo.bind("<<ComboboxSelected>>", self.on_server_selected)
        self.server_combo.bind("<KeyRelease>", self.on_server_typed)

        Label(frame_server, text="密码:").grid(row=1, column=0, sticky=W, pady=3)
        self.pwd_var = StringVar()
        Entry(frame_server, textvariable=self.pwd_var, width=30).grid(row=1, column=1, padx=5, pady=3)
        Button(frame_server, text="保存配置", command=self.save_server_config).grid(row=0, column=2, rowspan=2, padx=10)

        # 升级方式
        frame_mode = LabelFrame(main, text="升级方式", padx=10, pady=5)
        frame_mode.pack(pady=5, fill=X)

        self.upgrade_mode = StringVar(value="package")
        Radiobutton(frame_mode, text="目录升级", variable=self.upgrade_mode, value="directory").pack(anchor=W)
        Radiobutton(frame_mode, text="压缩包升级", variable=self.upgrade_mode, value="package").pack(anchor=W)

        self.path_var = StringVar()
        path_frame = Frame(frame_mode)
        path_frame.pack(fill=X, pady=5)
        self.path_entry = Entry(path_frame, textvariable=self.path_var, state='readonly')
        self.path_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        Button(path_frame, text="选择", command=self.select_path).pack(side=RIGHT)

        # 操作按钮
        btn_frame = Frame(main)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="开始一键升级", command=self.start_upgrade, bg="#4CAF50", fg="white", width=15, height=2).pack()

        # 进度条
        self.progress = ttk.Progressbar(main, mode='indeterminate')
        self.progress.pack(padx=20, fill=X, pady=(5, 0))

        # 日志区域
        frame_log = LabelFrame(main, text="📝 升级日志")
        frame_log.pack(fill=BOTH, expand=True, pady=(5, 0))

        self.log_text = scrolledtext.ScrolledText(frame_log, state=DISABLED, wrap=WORD, height=10, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

    def _log(self, message):
        """写入日志到 GUI 和文件"""
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(message)

    def _show_toast(self, title, message, level="info", duration_ms=180000):
        """屏幕右下角弹出消息提醒，duration_ms 后自动消失（默认3分钟）"""
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
        header.pack(fill=X, padx=10, pady=(8, 0))
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

    def on_server_selected(self, event=None):
        """当选中已有服务器时，自动填入密码"""
        host = self.server_var.get().strip()
        servers = self.config.get("servers", {})
        if host in servers:
            self.pwd_var.set(servers[host])
        else:
            self.pwd_var.set("")

    def on_server_typed(self, event=None):
        """当手动输入服务器时，清空密码（除非恰好匹配已存）"""
        host = self.server_var.get().strip()
        servers = self.config.get("servers", {})
        if host in servers:
            self.pwd_var.set(servers[host])
        else:
            self.pwd_var.set("")

    def save_server_config(self):
        server = self.server_var.get().strip()
        pwd = self.pwd_var.get().strip()
        if not server or not pwd:
            messagebox.showwarning("警告", "请填写服务器地址和密码！")
            return
        self.config["last_server"] = server
        self.config["common_password"] = pwd
        if "servers" not in self.config:
            self.config["servers"] = {}
        self.config["servers"][server] = pwd
        save_config(self.config)
        # 更新下拉框选项
        current_values = list(self.config["servers"].keys())
        self.server_combo['values'] = current_values
        messagebox.showinfo("成功", "服务器配置已保存！")

    def select_path(self):
        mode = self.upgrade_mode.get()
        if mode == "directory":
            path = filedialog.askdirectory(title="选择前端项目目录（需含 dist 和 lib-render-dist）")
        else:
            path = filedialog.askopenfilename(
                title="选择前端发布压缩包",
                filetypes=[("ZIP files", "*.zip")]
            )
        if path:
            self.path_var.set(path)

    def start_upgrade(self):
        host = self.server_var.get().strip()
        local_path = self.path_var.get().strip()
        mode = self.upgrade_mode.get()

        if not host:
            messagebox.showerror("错误", "请输入服务器地址！")
            return
        if not local_path:
            messagebox.showerror("错误", "请选择升级路径！")
            return
        if mode == "directory" and not Path(local_path).is_dir():
            messagebox.showerror("错误", "所选路径不是有效目录！")
            return
        if mode == "package" and not Path(local_path).is_file():
            messagebox.showerror("错误", "所选路径不是有效压缩包！")
            return

        password = self.pwd_var.get().strip()
        if password:
            # 如果用户已输入密码，直接使用
            final_password = password
        else:
            # 尝试默认密码列表
            DEFAULT_PASSWORDS = ["Yahua3585668", "yh123456", "Huawei@123"]
            final_password = None
            for pwd in DEFAULT_PASSWORDS:
                try:
                    self._log(f"尝试默认密码: {pwd}")
                    self.root.update_idletasks()
                    # 快速测试连接
                    test_client = get_ssh_client(host, password=pwd, timeout=5)
                    test_client.close()
                    final_password = pwd
                    self.pwd_var.set(pwd)  # 填入成功密码
                    break
                except Exception as e:
                    logger.warning(f"密码 {pwd} 连接失败: {e}")
                    continue

            if final_password is None:
                # 所有默认密码都失败，弹出手动输入
                pwd_input = simpledialog.askstring(
                    "密码错误",
                    f"默认密码（123456/888888/666666）均无法连接 {host}。\n"
                    "请手动输入 root 密码：",
                    parent=self.root
                )
                if not pwd_input:
                    return
                final_password = pwd_input
                self.pwd_var.set(final_password)  # 记住这次输入

        self.progress.start(10)
        self._log("准备升级...")
        thread = threading.Thread(
            target=self.run_upgrade,
            args=(host, password, local_path, mode),
            daemon=True
        )
        thread.start()

    def run_upgrade(self, host, password, local_path, mode):
        try:
            def update_status(msg):
                self.root.after(0, lambda: self._log(msg))

            if mode == "directory":
                do_directory_upgrade(host, password, local_path, update_status)
            else:
                do_package_upgrade(host, password, local_path, update_status)

            # 调用通知接口
            notify_template_update(host, update_status)

            self._log("=" * 40)
            self._log(f"🎉 服务器 {host} 升级及通知完成！")
            self.root.after(0, lambda: self._show_toast("升级完成", f"服务器 {host} 升级及通知完成！", "success"))
            logger.info(f"Full upgrade and notification succeeded for {host}")
        except Exception as e:
            error_msg = f"升级失败：{str(e)}"
            self.root.after(0, lambda: self._show_toast("升级失败", error_msg, "error"))
            logger.exception("Upgrade failed")
        finally:
            self.root.after(0, lambda: self.progress.stop())

# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    missing = []
    if not paramiko:
        missing.append("paramiko")
    if not httpx:
        missing.append("httpx")

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
