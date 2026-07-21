# svn_quick_checkout.pyw

import os
import sys
import json
import logging
import subprocess
import threading
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "svn_quick_checkout"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建必要目录
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
# 默认配置
DEFAULTS = {
    "病房": {
        "username": "zhangsan",
        "password": "888888",
        "svn_base_url": "https://192.168.30.124/svn/智慧病房特殊订单",
        "local_checkout_dir": r"D:\CODE\Yarward\SVN"
    },
    "门诊": {
        "username": "lisi",
        "password": "666666",
        "svn_base_url": "https://192.168.30.134/svn/门诊/YM-801S/7.特殊订单/2025年特殊订单",
        "local_checkout_dir": r"D:\CODE\Yarward\SVN\0门诊"
    }
}

# ==============================
# 工具函数
# ==============================
def load_config():
    config = {
        "last_type": "病房",
        "病房": DEFAULTS["病房"].copy(),
        "门诊": DEFAULTS["门诊"].copy()
    }

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # 合并：保留已有的 last_type
                if "last_type" in loaded:
                    config["last_type"] = loaded["last_type"]
                # 安全合并“病房”和“门诊”配置
                for key in ["病房", "门诊"]:
                    if key in loaded and isinstance(loaded[key], dict):
                        config[key].update(loaded[key])  # 只更新存在的字段
        except Exception as e:
            logger.error(f"加载配置失败，使用默认配置: {e}")

    return config

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已完整保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def run_svn_command(args, cwd=None, timeout=30):
    try:
        env = os.environ.copy()
        env['SVN_SSL_NO_VERIFY'] = '1'
        result = subprocess.run(
            ['svn'] + args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            cwd=cwd,
            timeout=timeout,
            env=env
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except FileNotFoundError:
        return -2, "", "未找到 svn 命令，请确保已安装 SVN 客户端并加入 PATH"
    except Exception as e:
        return -3, "", str(e)

def is_valid_order_name(name: str):
    if len(name) < 10:
        return False
    if name[4] != '-' or not name[:4].isdigit() or not name[5:9].isdigit():
        return False
    if not name[9:].strip():
        return False
    return True

# ==============================
# GUI 主类
# ==============================
class SVNQuickCheckoutGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 SVN 快速创建 & 检出工具")
        self.root.geometry("700x520")
        self.root.resizable(False, False)

        self.config = load_config()
        self.order_type = StringVar(value=self.config.get("last_type", "病房"))
        self.create_widgets()
        self.on_type_change()

    def create_widgets(self):
        # 类型选择
        frame_type = LabelFrame(self.root, text="📁 订单类型", padx=10, pady=5)
        frame_type.pack(fill=X, padx=15, pady=5)
        Radiobutton(frame_type, text="病房", variable=self.order_type, value="病房", command=self.on_type_change).pack(side=LEFT)
        Radiobutton(frame_type, text="门诊", variable=self.order_type, value="门诊", command=self.on_type_change).pack(side=LEFT)

        # SVN 地址
        frame_svn = LabelFrame(self.root, text="🌐 SVN 基础地址（在该路径下新建目录）", padx=10, pady=5)
        frame_svn.pack(fill=X, padx=15, pady=5)
        self.svn_url_var = StringVar()
        Entry(frame_svn, textvariable=self.svn_url_var, width=80, font=("Consolas", 9)).pack(pady=3)

        # 用户名密码
        frame_auth = LabelFrame(self.root, text="🔑 SVN 账号", padx=10, pady=5)
        frame_auth.pack(fill=X, padx=15, pady=5)
        Label(frame_auth, text="用户名:").grid(row=0, column=0, sticky=W)
        self.username_var = StringVar()
        Entry(frame_auth, textvariable=self.username_var, width=20).grid(row=0, column=1, padx=5)
        Label(frame_auth, text="密码:").grid(row=0, column=2, sticky=W, padx=(10,0))
        self.password_var = StringVar()
        Entry(frame_auth, textvariable=self.password_var, show="*", width=20).grid(row=0, column=3, padx=5)

        # 订单名称
        frame_order = LabelFrame(self.root, text="📋 订单名称（格式：2025-2308江苏省中医院溧阳分院）", padx=10, pady=5)
        frame_order.pack(fill=X, padx=15, pady=5)
        self.order_name_var = StringVar()
        entry_order = Entry(frame_order, textvariable=self.order_name_var, font=("Arial", 12), width=60)
        entry_order.pack(pady=3)

        # 本地检出目录
        frame_local = LabelFrame(self.root, text="💻 本地检出目录", padx=10, pady=5)
        frame_local.pack(fill=X, padx=15, pady=5)
        self.local_dir_var = StringVar()
        entry_local = Entry(frame_local, textvariable=self.local_dir_var, width=70, state='readonly')
        entry_local.pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(frame_local, text="📂 选择", command=self.select_local_dir).pack(side=RIGHT)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        Button(btn_frame, text="🚀 开始创建 & 检出", command=self.start_process, bg="#4CAF50", fg="white", width=18, height=2).pack()

        # 状态标签
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 10))
        self.status_label.pack(pady=5)

        # 日志文本框
        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=15, pady=(0,10))
        self.log_text = Text(log_frame, height=6, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    def on_type_change(self):
        t = self.order_type.get()
        data = self.config[t]
        self.svn_url_var.set(data.get("svn_base_url", DEFAULTS[t]["svn_base_url"]))
        self.username_var.set(data.get("username", DEFAULTS[t]["username"]))
        self.password_var.set(data.get("password", DEFAULTS[t]["password"]))
        self.local_dir_var.set(data.get("local_checkout_dir", DEFAULTS[t]["local_checkout_dir"]))

    def select_local_dir(self):
        folder = filedialog.askdirectory(initialdir=self.local_dir_var.get())
        if folder:
            self.local_dir_var.set(folder)

    def log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def set_status(self, msg, color="black"):
        self.status_label.config(text=msg, fg=color)
        self.root.update_idletasks()

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

    def start_process(self):
        order_type = self.order_type.get()
        svn_base = self.svn_url_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        order_name = self.order_name_var.get().strip()
        local_dir = self.local_dir_var.get().strip()

        # 校验
        if not all([svn_base, username, password, order_name, local_dir]):
            messagebox.showerror("错误", "请填写所有字段！")
            return
        if not is_valid_order_name(order_name):
            messagebox.showerror("错误", "订单名称格式不正确！\n必须为：2025-2308医院名称")
            return
        if not Path(local_dir).exists():
            try:
                Path(local_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("错误", f"无法创建本地目录：{e}")
                return

        # ✅【关键修复】完整保存当前配置
        self.config["last_type"] = order_type
        self.config[order_type] = {
            "svn_base_url": svn_base,
            "username": username,
            "password": password,
            "local_checkout_dir": local_dir
        }
        save_config(self.config)

        # 启动后台线程
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(padx=20, fill=X)
        self.progress.start(10)
        self.set_status("处理中...", "blue")

        thread = threading.Thread(
            target=self.do_svn_workflow,
            args=(order_type, svn_base, username, password, order_name, local_dir),
            daemon=True
        )
        thread.start()

    def do_svn_workflow(self, order_type, svn_base, username, password, order_name, local_dir):
        try:
            hospital_name = order_name[9:]  # 提取医院名

            if order_type == "病房":
                # 病房：两级目录
                hospital_url = f"{svn_base.rstrip('/')}/{hospital_name}"
                target_url = f"{hospital_url}/{order_name}"
                self.log(f"病房模式：医院目录 = {hospital_url}")
                self.log(f"病房模式：订单目录 = {target_url}")

                # 1. 检查并创建医院目录
                code, _, _ = run_svn_command([
                    "info", hospital_url,
                    "--username", username,
                    "--password", password,
                    "--non-interactive",
                    "--trust-server-cert"
                ])
                if code != 0:
                    self.log("📁 医院目录不存在，正在创建...")
                    mkdir_code, out, err = run_svn_command([
                        "mkdir", hospital_url, "-m", f"Auto create hospital dir for {hospital_name}",
                        "--username", username,
                        "--password", password,
                        "--non-interactive",
                        "--trust-server-cert"
                    ])
                    if mkdir_code != 0:
                        raise Exception(f"创建医院目录失败: {err or out}")

                # 2. 检查并创建订单目录（在医院目录下）
                code, _, _ = run_svn_command([
                    "info", target_url,
                    "--username", username,
                    "--password", password,
                    "--non-interactive",
                    "--trust-server-cert"
                ])
                if code != 0:
                    self.log("📁 订单目录不存在，正在创建...")
                    mkdir_code, out, err = run_svn_command([
                        "mkdir", target_url, "-m", f"Auto create for {order_name}",
                        "--username", username,
                        "--password", password,
                        "--non-interactive",
                        "--trust-server-cert"
                    ])
                    if mkdir_code != 0:
                        raise Exception(f"创建订单目录失败: {err or out}")
                else:
                    self.log("✅ 订单目录已存在")

            else:  # 门诊
                target_url = f"{svn_base.rstrip('/')}/{order_name}"
                self.log(f"门诊模式：订单目录 = {target_url}")

                # 检查并创建订单目录
                code, _, _ = run_svn_command([
                    "info", target_url,
                    "--username", username,
                    "--password", password,
                    "--non-interactive",
                    "--trust-server-cert"
                ])
                if code != 0:
                    self.log("📁 订单目录不存在，正在创建...")
                    mkdir_code, out, err = run_svn_command([
                        "mkdir", target_url, "-m", f"Auto create for {order_name}",
                        "--username", username,
                        "--password", password,
                        "--non-interactive",
                        "--trust-server-cert"
                    ])
                    if mkdir_code != 0:
                        raise Exception(f"创建订单目录失败: {err or out}")
                else:
                    self.log("✅ 订单目录已存在")

            # 检出到本地
            checkout_local_path = Path(local_dir) / order_name
            self.log(f"检出到本地: {checkout_local_path}")

            co_code, co_out, co_err = run_svn_command([
                "checkout", target_url, str(checkout_local_path),
                "--username", username,
                "--password", password,
                "--non-interactive",
                "--trust-server-cert"
            ])

            if co_code != 0:
                raise Exception(f"检出失败: {co_err or co_out}")

            # 创建“前端”目录
            (checkout_local_path / "前端").mkdir(exist_ok=True)
            self.log("✅ 已创建 '前端' 目录")

            # 自动打开
            os.startfile(str(checkout_local_path))

            self.root.after(0, lambda: self._show_toast("SVN 操作完成", f"已打开目录：{checkout_local_path}", "success"))

        except Exception as e:
            error_msg = f"❌ 操作失败: {str(e)}"
            self.log(error_msg)
            self.root.after(0, lambda: self._show_toast("SVN 操作失败", error_msg, "error"))
        finally:
            self.root.after(0, lambda: self.progress.stop())
            self.root.after(0, lambda: self.progress.destroy())
            self.root.after(0, lambda: self.set_status("完成", "green"))

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 可选：加载 DB 配置（虽不用，但按要求引入）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_config = json.load(f)
        except Exception as e:
            logger.warning(f"DB_CONFIG 加载失败（非必需）: {e}")

    root = Tk()
    app = SVNQuickCheckoutGUI(root)
    root.mainloop()
