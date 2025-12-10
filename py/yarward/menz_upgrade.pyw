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
from tkinter import filedialog, messagebox, ttk, simpledialog

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

    if not dist_dir.exists() or not lib_render_dir.exists():
        raise ValueError("项目目录下缺少 dist 或 lib-render-dist 目录！请先打包。")

    progress_callback("正在连接服务器...")
    with get_ssh_client(host, password=password) as ssh:
        sftp = ssh.open_sftp()

        progress_callback("清空 design 目录...")
        clear_remote_dir(sftp, DESIGN_REMOTE_PATH)
        progress_callback("上传 design 文件...")
        upload_dir(sftp, str(dist_dir), DESIGN_REMOTE_PATH)

        progress_callback("清空 render-design 目录...")
        clear_remote_dir(sftp, RENDER_REMOTE_PATH)
        progress_callback("上传 render-design 文件...")
        upload_dir(sftp, str(lib_render_dir), RENDER_REMOTE_PATH)

        sftp.close()
    progress_callback("✅ 目录升级完成！")

def do_package_upgrade(host, password, zip_path, progress_callback):
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
        resource_js_render = root_dir / "resource" / "js" / "render-design"

        if not design_dir.exists() or not resource_js_render.exists():
            raise ValueError("压缩包内缺少 design 或 resource/js/render-design 目录！")

        progress_callback("正在连接服务器...")
        with get_ssh_client(host, password=password) as ssh:
            sftp = ssh.open_sftp()

            progress_callback("清空 design 目录...")
            clear_remote_dir(sftp, DESIGN_REMOTE_PATH)
            progress_callback("上传 design 文件...")
            upload_dir(sftp, str(design_dir), DESIGN_REMOTE_PATH)

            progress_callback("清空 render-design 目录...")
            clear_remote_dir(sftp, RENDER_REMOTE_PATH)
            progress_callback("上传 render-design 文件...")
            upload_dir(sftp, str(resource_js_render), RENDER_REMOTE_PATH)

            sftp.close()
        progress_callback("✅ 压缩包升级完成！")

# ==============================
# GUI
# ==============================
class YarwardUpgradeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Yarward 门诊前端一键升级")
        self.root.geometry("650x480")
        self.root.resizable(False, False)

        self.config = load_config()
        self.create_widgets()

    def create_widgets(self):
        frame_server = LabelFrame(self.root, text="服务器配置", padx=10, pady=5)
        frame_server.pack(pady=5, padx=10, fill=X)

        Label(frame_server, text="服务器地址:").grid(row=0, column=0, sticky=W, pady=3)
        self.server_var = StringVar(value=self.config.get("last_server", ""))
        server_entry = Entry(frame_server, textvariable=self.server_var, width=30)
        server_entry.grid(row=0, column=1, padx=5, pady=3)

        Label(frame_server, text="通用密码:").grid(row=1, column=0, sticky=W, pady=3)
        self.pwd_var = StringVar(value=self.config.get("common_password", ""))
        pwd_entry = Entry(frame_server, textvariable=self.pwd_var, show="*", width=30)
        pwd_entry.grid(row=1, column=1, padx=5, pady=3)

        Button(frame_server, text="保存配置", command=self.save_server_config).grid(row=0, column=2, rowspan=2, padx=10)

        frame_mode = LabelFrame(self.root, text="升级方式", padx=10, pady=5)
        frame_mode.pack(pady=5, padx=10, fill=X)

        self.upgrade_mode = StringVar(value="directory")
        Radiobutton(frame_mode, text="目录升级", variable=self.upgrade_mode, value="directory").pack(anchor=W)
        Radiobutton(frame_mode, text="压缩包升级", variable=self.upgrade_mode, value="package").pack(anchor=W)

        self.path_var = StringVar()
        path_frame = Frame(frame_mode)
        path_frame.pack(fill=X, pady=5)
        self.path_entry = Entry(path_frame, textvariable=self.path_var, state='readonly')
        self.path_entry.pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(path_frame, text="选择", command=self.select_path).pack(side=RIGHT)

        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)

        Button(btn_frame, text="开始一键升级", command=self.start_upgrade, bg="#4CAF50", fg="white", width=15, height=2).pack()

        self.progress_label = Label(self.root, text="", fg="blue", wraplength=600, justify=LEFT)
        self.progress_label.pack(pady=5)

        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(padx=20, fill=X)

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

        password = ""
        if host in self.config.get("servers", {}):
            password = self.config["servers"][host]
        else:
            password = self.config.get("common_password", "")

        if not password:
            password = simpledialog.askstring("输入密码", f"未找到 {host} 的密码，请手动输入（用户名：root）：", show='*')
            if not password:
                return

        self.progress.start(10)
        self.progress_label.config(text="准备升级...")
        thread = threading.Thread(
            target=self.run_upgrade,
            args=(host, password, local_path, mode),
            daemon=True
        )
        thread.start()

    def run_upgrade(self, host, password, local_path, mode):
        try:
            def update_status(msg):
                self.root.after(0, lambda: self.progress_label.config(text=msg))

            if mode == "directory":
                do_directory_upgrade(host, password, local_path, update_status)
            else:
                do_package_upgrade(host, password, local_path, update_status)

            # === 新增：调用通知接口 ===
            notify_template_update(host, update_status)

            self.root.after(0, lambda: messagebox.showinfo("成功", f"服务器 {host} 升级及通知完成！"))
            logger.info(f"Full upgrade and notification succeeded for {host}")
        except Exception as e:
            error_msg = f"升级失败：{str(e)}"
            self.root.after(0, lambda: messagebox.showerror("错误", error_msg))
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
