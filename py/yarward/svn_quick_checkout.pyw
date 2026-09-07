# svn_quick_checkout.pyw

import os
import sys
import json
import logging
import subprocess
import threading
import ctypes
import ctypes.wintypes
import time as _time
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
    from log_utils import get_logger  # noqa — 运行时由 _PY_DIR 加入 sys.path
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
        "svn_base_url": "https://10.1.1.120/svn/智慧病房特殊订单",
        "local_checkout_dir": r"D:\CODE\Yarward\SVN\病房"
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

# 缓存 SVN 版本信息，用于日志排查
_svn_version_cached = None

def _get_svn_version():
    global _svn_version_cached
    if _svn_version_cached is not None:
        return _svn_version_cached
    try:
        r = subprocess.run(
            ['svn', '--version', '--quiet'],
            capture_output=True, text=True, encoding='utf-8',
            timeout=10
        )
        _svn_version_cached = r.stdout.strip() or 'unknown'
    except Exception:
        _svn_version_cached = 'unknown'
    return _svn_version_cached

def _try_hide_console(pid, max_wait=3.0):
    """后台线程：高频轮询查找指定 PID 的控制台窗口并立即隐藏"""
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    ShowWindow = user32.ShowWindow
    IsWindowVisible = user32.IsWindowVisible
    SW_HIDE = 0
    found = [False]
    _ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _enum_cb(hwnd, _):
        if found[0]:
            return True
        proc_id = ctypes.wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid and IsWindowVisible(hwnd):
            ShowWindow(hwnd, SW_HIDE)
            found[0] = True
        return True

    deadline = _time.time() + max_wait
    while _time.time() < deadline and not found[0]:
        EnumWindows(_ENUM_PROC(_enum_cb), 0)
        if not found[0]:
            _time.sleep(0.001)  # 1ms 轮询，最小化闪烁

# SVN 公共参数（非交互式 + 信任自签名证书）
_SVN_COMMON_ARGS = [
    '--non-interactive',
    '--trust-server-cert',
]

def _ensure_console_hidden():
    """为当前进程分配控制台并立即隐藏窗口，使子进程（SVN）继承隐藏的控制台"""
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # AllocConsole：如果当前进程没有控制台则创建一个；已有则失败（无害）
    if kernel32.AllocConsole():
        logger.info("AllocConsole 成功，正在隐藏控制台窗口")
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
            logger.info("控制台窗口已隐藏")
        else:
            logger.warning("GetConsoleWindow 返回空")
    else:
        # 已有控制台，尝试找到并隐藏
        hwnd = kernel32.GetConsoleWindow()
        if hwnd and user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 0)
            logger.info("已有控制台窗口，已隐藏")
        else:
            logger.info("控制台已存在且不可见，无需处理")

def _decode_svn_output(data):
    """解码 SVN 输出：UTF-8 → GBK → UTF-8(replace) 三级回退"""
    if not data:
        return ''
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return data.decode('gbk')
        except UnicodeDecodeError:
            return data.decode('utf-8', errors='replace')

def run_svn_command(args, cwd=None, timeout=60):
    try:
        full_cmd = ['svn'] + args
        logger.info(f"SVN 执行: svn {args[0]} (timeout={timeout}s)")
        env = os.environ.copy()
        env['SVN_SSL_NO_VERIFY'] = '1'

        # ① 为父进程分配控制台并立即隐藏 —— SVN 继承此隐藏控制台，不再弹出黑框
        _ensure_console_hidden()

        # ② 二进制模式捕获，避免 SVN 中文输出 GBK 编码与 UTF-8 解码冲突
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        # ③ 后台线程安全网：万一 SVN 仍创建了可见窗口，立即隐藏
        hide_thread = threading.Thread(
            target=_try_hide_console,
            args=(proc.pid,),
            daemon=True
        )
        hide_thread.start()

        # 等待进程完成
        try:
            raw_out, raw_err = proc.communicate(timeout=timeout)
            return proc.returncode, _decode_svn_output(raw_out), _decode_svn_output(raw_err)
        except subprocess.TimeoutExpired:
            proc.kill()
            raw_out, raw_err = proc.communicate()
            leftover = _decode_svn_output(raw_out or b'') + _decode_svn_output(raw_err or b'')
            msg = f"命令超时（{timeout}s）"
            if leftover.strip():
                msg += f"\n已收到输出: {leftover.strip()}"
            return -1, "", msg
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


def _svn_list_dirs(url, username, password):
    """列出 SVN 服务器上指定 URL 下的所有目录名"""
    code, stdout, stderr = run_svn_command([
        "list", url,
        "--username", username,
        "--password", password,
        *_SVN_COMMON_ARGS
    ], timeout=60)
    if code != 0:
        logger.warning(f"svn list 失败: {stderr or stdout}")
        return []
    dirs = [line.rstrip('/') for line in (stdout or '').strip().splitlines() if line.strip()]
    return dirs


def _find_matching_order(server_dirs, order_name):
    """根据订单号前缀（YYYY-NNNN）在服务器目录列表中模糊匹配"""
    if len(order_name) < 9:
        return None
    prefix = order_name[:9]
    for d in server_dirs:
        if len(d) >= 9 and d[:9] == prefix:
            logger.info(f"模糊匹配成功: 用户输入 '{order_name}' → 服务器已有 '{d}'")
            return d
    return None


# ==============================
# GUI 主类
# ==============================
class SVNQuickCheckoutGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 SVN 快速创建 & 检出工具")
        self.root.geometry("700x650")
        self.root.resizable(False, False)

        self.config = load_config()
        self.tab_index = 0
        # 病房目录浏览器状态
        self._ward_mode = False
        self._ward_url_stack = []
        self._ward_current_url = ""
        self._ward_hospital_name = ""
        self._ward_list_initialized = False
        self.create_widgets()
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.on_tab_changed(init=True)  # 初始化加载默认标签页配置（不保存，避免空值覆盖）

    def create_widgets(self):
        # 创建标签页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=(10, 0))

        # ══════════ 病房 Tab ══════════
        ward_tab = Frame(self.notebook)
        self.notebook.add(ward_tab, text=" 📂 病房 ")

        # SVN 目录浏览器
        browser_frame = LabelFrame(ward_tab, text="SVN 目录浏览（双击进入，可搜索）", padx=10, pady=5)
        browser_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        search_row = Frame(browser_frame)
        search_row.pack(fill=X, pady=(0, 5))
        self.ward_search_var = StringVar()
        self.ward_search_entry = Entry(search_row, textvariable=self.ward_search_var, font=("Arial", 11), width=40)
        self.ward_search_entry.pack(side=LEFT, fill=X, expand=True)
        self.ward_search_entry.bind("<Return>", lambda e: self._ward_search())
        Button(search_row, text="🔍 搜索", command=self._ward_search).pack(side=LEFT, padx=(5, 0))
        self.ward_listbox = Listbox(browser_frame, height=8, font=("Microsoft YaHei UI", 10), selectmode=EXTENDED)
        self.ward_listbox.pack(fill=BOTH, expand=True)
        self.ward_listbox.bind("<Double-1>", self._ward_on_double_click)
        ward_sb = Scrollbar(browser_frame, orient=VERTICAL, command=self.ward_listbox.yview)
        self.ward_listbox.configure(yscrollcommand=ward_sb.set)
        ward_sb.pack(side=RIGHT, fill=Y)
        self.ward_path_label = Label(browser_frame, text="当前路径：", fg="#666", font=("Consolas", 8), anchor=W)
        self.ward_path_label.pack(fill=X, pady=(3, 0))
        ward_btn_row = Frame(browser_frame)
        ward_btn_row.pack(fill=X, pady=(5, 0))
        Button(ward_btn_row, text="⬆ 返回上级", command=self._ward_go_back, width=12).pack(side=LEFT, padx=(0, 5))
        Button(ward_btn_row, text="📁 新建文件夹", command=self._ward_create_folder, width=12).pack(side=LEFT, padx=(0, 5))
        Button(ward_btn_row, text="🚀 检出选中", command=self._ward_start_checkout, width=12, bg="#4CAF50", fg="white").pack(side=LEFT)

        # 病房 SVN 账号
        ward_auth = LabelFrame(ward_tab, text="🔑 SVN 账号", padx=10, pady=5)
        ward_auth.pack(fill=X, padx=10, pady=5)
        Label(ward_auth, text="用户名:").grid(row=0, column=0, sticky=W)
        self.username_var = StringVar()
        Entry(ward_auth, textvariable=self.username_var, width=20).grid(row=0, column=1, padx=5)
        Label(ward_auth, text="密码:").grid(row=0, column=2, sticky=W, padx=(10,0))
        self.password_var = StringVar()
        Entry(ward_auth, textvariable=self.password_var, show="*", width=20).grid(row=0, column=3, padx=5)

        # 病房 本地检出目录
        ward_local = LabelFrame(ward_tab, text="💻 本地检出目录", padx=10, pady=5)
        ward_local.pack(fill=X, padx=10, pady=5)
        self.local_dir_var = StringVar()
        Entry(ward_local, textvariable=self.local_dir_var, width=60, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(ward_local, text="📂 选择", command=self.select_local_dir).pack(side=RIGHT)

        # ══════════ 门诊 Tab ══════════
        menz_tab = Frame(self.notebook)
        self.notebook.add(menz_tab, text=" 📋 门诊 ")

        frame_svn = LabelFrame(menz_tab, text="🌐 SVN 基础地址（在该路径下新建目录）", padx=10, pady=5)
        frame_svn.pack(fill=X, padx=10, pady=5)
        self.svn_url_var = StringVar()
        Entry(frame_svn, textvariable=self.svn_url_var, width=80, font=("Consolas", 9)).pack(pady=3)

        mz_auth = LabelFrame(menz_tab, text="🔑 SVN 账号", padx=10, pady=5)
        mz_auth.pack(fill=X, padx=10, pady=5)
        Label(mz_auth, text="用户名:").grid(row=0, column=0, sticky=W)
        self.mz_username_var = StringVar()
        Entry(mz_auth, textvariable=self.mz_username_var, width=20).grid(row=0, column=1, padx=5)
        Label(mz_auth, text="密码:").grid(row=0, column=2, sticky=W, padx=(10,0))
        self.mz_password_var = StringVar()
        Entry(mz_auth, textvariable=self.mz_password_var, show="*", width=20).grid(row=0, column=3, padx=5)

        frame_order = LabelFrame(menz_tab, text="📋 订单名称（格式：2025-2308江苏省中医院溧阳分院）", padx=10, pady=5)
        frame_order.pack(fill=X, padx=10, pady=5)
        self.order_name_var = StringVar()
        Entry(frame_order, textvariable=self.order_name_var, font=("Arial", 12), width=60).pack(pady=3)

        mz_local = LabelFrame(menz_tab, text="💻 本地检出目录", padx=10, pady=5)
        mz_local.pack(fill=X, padx=10, pady=5)
        self.mz_local_dir_var = StringVar()
        Entry(mz_local, textvariable=self.mz_local_dir_var, width=60, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(mz_local, text="📂 选择", command=lambda: self._select_mz_dir()).pack(side=RIGHT)

        Button(menz_tab, text="🚀 开始创建 & 检出", command=self.start_process, bg="#4CAF50", fg="white", width=18, height=2).pack(pady=10)

        # ══════════ 共享区域（标签页下方）══════════
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 10))
        self.status_label.pack(pady=(5, 2))

        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_text = Text(log_frame, height=6, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    def on_tab_changed(self, event=None, init=False):
        idx = self.notebook.index(self.notebook.select())
        old_idx = self.tab_index
        self.tab_index = idx
        if not init:
            # 保存旧标签页配置
            old_key = "病房" if old_idx == 0 else "门诊"
            if old_idx == 0:
                self.config[old_key]["username"] = self.username_var.get().strip()
                self.config[old_key]["password"] = self.password_var.get().strip()
                self.config[old_key]["local_checkout_dir"] = self.local_dir_var.get().strip()
            else:
                self.config[old_key]["svn_base_url"] = self.svn_url_var.get().strip()
                self.config[old_key]["username"] = self.mz_username_var.get().strip()
                self.config[old_key]["password"] = self.mz_password_var.get().strip()
                self.config[old_key]["local_checkout_dir"] = self.mz_local_dir_var.get().strip()
            self.config["last_type"] = "病房" if idx == 0 else "门诊"
            save_config(self.config)
        # 加载新标签页配置
        new_key = "病房" if idx == 0 else "门诊"
        data = self.config[new_key]
        if idx == 0:
            self.username_var.set(data.get("username", DEFAULTS["病房"]["username"]))
            self.password_var.set(data.get("password", DEFAULTS["病房"]["password"]))
            self.local_dir_var.set(data.get("local_checkout_dir", DEFAULTS["病房"]["local_checkout_dir"]))
            if not self._ward_list_initialized:
                self.root.after(200, self._ward_load_list)
                self._ward_list_initialized = True
        else:
            self.svn_url_var.set(data.get("svn_base_url", DEFAULTS["门诊"]["svn_base_url"]))
            self.mz_username_var.set(data.get("username", DEFAULTS["门诊"]["username"]))
            self.mz_password_var.set(data.get("password", DEFAULTS["门诊"]["password"]))
            self.mz_local_dir_var.set(data.get("local_checkout_dir", DEFAULTS["门诊"]["local_checkout_dir"]))

    def _select_mz_dir(self):
        folder = filedialog.askdirectory(initialdir=self.mz_local_dir_var.get())
        if folder:
            self.mz_local_dir_var.set(folder)

    # ──────── 病房目录浏览器方法 ────────
    def _ward_search(self):
        keyword = self.ward_search_var.get().strip()
        self._ward_load_list(keyword)

    def _ward_load_list(self, keyword=""):
        self.ward_listbox.delete(0, END)
        self.ward_listbox.insert(END, "加载中...")
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        url = self._ward_current_url or self.config["病房"]["svn_base_url"].rstrip('/')

        def _do():
            code, stdout, stderr = run_svn_command([
                "list", url,
                "--username", username,
                "--password", password,
                *_SVN_COMMON_ARGS
            ], timeout=60)
            self.root.after(0, lambda: self._ward_fill_list(code, stdout, keyword))

        threading.Thread(target=_do, daemon=True).start()

    def _ward_fill_list(self, code, stdout, keyword=""):
        self.ward_listbox.delete(0, END)
        if code != 0:
            self.ward_listbox.insert(END, "❌ 获取目录列表失败")
            self.log(f"svn list 失败: {stdout}")
            return
        dirs = [line.rstrip('/') for line in (stdout or '').strip().splitlines() if line.strip()]
        if keyword:
            dirs = [d for d in dirs if keyword in d]
        if not dirs:
            self.ward_listbox.insert(END, "（无匹配结果）" if keyword else "（空目录）")
        else:
            for d in dirs:
                self.ward_listbox.insert(END, d)
        self.ward_path_label.config(text=f"当前路径：{self._ward_current_url}")
        self._ward_mode = True

    def _ward_on_double_click(self, event):
        sel = self.ward_listbox.curselection()
        if not sel:
            return
        name = self.ward_listbox.get(sel[0])
        if name.startswith("（") or name.startswith("❌") or name == "加载中...":
            return
        self._ward_url_stack.append(self._ward_current_url)
        base = self._ward_current_url or self.config["病房"]["svn_base_url"].rstrip('/')
        self._ward_current_url = f"{base}/{name}"
        if len(self._ward_url_stack) == 1:
            self._ward_hospital_name = name
        self.ward_search_var.set("")
        self._ward_load_list()

    def _ward_go_back(self):
        if not self._ward_url_stack:
            return
        self._ward_current_url = self._ward_url_stack.pop()
        if not self._ward_url_stack:
            self._ward_hospital_name = ""
        self.ward_search_var.set("")
        self._ward_load_list()

    def _ward_create_folder(self):
        name = self.ward_search_var.get().strip()
        if not name:
            messagebox.showinfo("提示", "请先在搜索框中输入文件夹名称")
            return
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        base = self._ward_current_url or self.config["病房"]["svn_base_url"].rstrip('/')
        target_url = f"{base}/{name}"
        self.log(f"正在创建 SVN 目录: {target_url}")

        def _do():
            code, out, err = run_svn_command([
                "mkdir", target_url, "-m", f"Create {name}",
                "--username", username,
                "--password", password,
                *_SVN_COMMON_ARGS
            ], timeout=60)
            if code == 0:
                self.root.after(0, lambda: self.log(f"✅ 目录创建成功: {name}"))
                self.root.after(0, lambda: self._ward_load_list())
            else:
                self.root.after(0, lambda: self.log(f"❌ 创建失败: {err or out}"))
                self.root.after(0, lambda: messagebox.showerror("创建失败", f"SVN mkdir 失败:\n{err or out}"))

        threading.Thread(target=_do, daemon=True).start()

    def _ward_start_checkout(self):
        sel = self.ward_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要检出的目录")
            return
        names = [self.ward_listbox.get(i) for i in sel]
        if any(n.startswith("（") or n.startswith("❌") or n == "加载中..." for n in names):
            messagebox.showinfo("提示", "请选择有效的目录")
            return
        selected_name = names[0]
        base = self._ward_current_url or self.config["病房"]["svn_base_url"].rstrip('/')
        target_url = f"{base}/{selected_name}"
        depth = len(self._ward_url_stack)
        if depth == 0:
            local_name = selected_name
        elif depth == 1:
            local_name = f"{selected_name}{self._ward_hospital_name}"
        else:
            local_name = selected_name
        local_dir = self.local_dir_var.get().strip()
        if not local_dir:
            messagebox.showerror("错误", "请配置本地检出目录")
            return
        self.config["last_type"] = "病房"
        self.config["病房"]["username"] = self.username_var.get().strip()
        self.config["病房"]["password"] = self.password_var.get().strip()
        self.config["病房"]["local_checkout_dir"] = local_dir
        save_config(self.config)
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(padx=20, fill=X)
        self.progress.start(10)
        self.set_status("检出中...", "blue")
        threading.Thread(
            target=self._ward_do_checkout,
            args=(target_url, local_dir, local_name),
            daemon=True
        ).start()

    def _ward_do_checkout(self, target_url, local_dir, local_name):
        try:
            checkout_path = Path(local_dir) / local_name
            self.log(f"正在检出: {target_url}")
            self.log(f"检出路经: {checkout_path}")
            username = self.username_var.get().strip()
            password = self.password_var.get().strip()
            co_code, co_out, co_err = run_svn_command([
                "checkout", target_url, str(checkout_path),
                "--username", username,
                "--password", password,
                *_SVN_COMMON_ARGS
            ], timeout=300)
            if co_code != 0:
                raise Exception(f"检出失败: {co_err or co_out}")
            (checkout_path / "前端").mkdir(exist_ok=True)
            self.log("✅ 已创建 '前端' 目录")
            os.startfile(str(checkout_path))
            self.root.after(0, lambda: self._show_toast("SVN 检出完成", f"已打开：{checkout_path}", "success"))
        except Exception as e:
            error_msg = f"❌ 操作失败: {str(e)}"
            self.log(error_msg)
            self.root.after(0, lambda: self._show_toast("SVN 操作失败", error_msg, "error"))
        finally:
            self.root.after(0, lambda: self.progress.stop())
            self.root.after(0, lambda: self.progress.destroy())
            self.root.after(0, lambda: self.set_status("完成", "green"))

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
        svn_base = self.svn_url_var.get().strip()
        username = self.mz_username_var.get().strip()
        password = self.mz_password_var.get().strip()
        order_name = self.order_name_var.get().strip()
        local_dir = self.mz_local_dir_var.get().strip()

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

        # 完整保存门诊配置
        self.config["last_type"] = "门诊"
        self.config["门诊"] = {
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
            args=("门诊", svn_base, username, password, order_name, local_dir),
            daemon=True
        )
        thread.start()

    def do_svn_workflow(self, order_type, svn_base, username, password, order_name, local_dir):
        try:
            svn_ver = _get_svn_version()
            self.log(f"SVN 客户端版本: {svn_ver}")
            hospital_name = order_name[9:]  # 提取医院名

            if order_type == "病房":
                # 病房：两级目录
                hospital_url = f"{svn_base.rstrip('/')}/{hospital_name}"
                target_url = f"{hospital_url}/{order_name}"
                self.log(f"病房模式：医院目录 = {hospital_url}")
                self.log(f"病房模式：订单目录 = {target_url}")

                # 1. 检查并创建医院目录（支持按订单号前缀模糊匹配）
                code, _, err = run_svn_command([
                    "info", hospital_url,
                    "--username", username,
                    "--password", password,
                    *_SVN_COMMON_ARGS
                ])
                if code != 0:
                    # 精确查找失败，列出所有目录按前缀匹配
                    self.log("🔍 医院目录精确匹配失败，正在搜索同编号目录...")
                    server_dirs = _svn_list_dirs(svn_base.rstrip('/'), username, password)
                    matched = _find_matching_order(server_dirs, hospital_name)
                    if matched:
                        self.log(f"⚠️ 找到相似医院目录：{matched}")
                        confirm_result = [None]
                        confirm_event = threading.Event()
                        def _ask():
                            r = messagebox.askyesno(
                                "发现已有订单",
                                f"服务器上已存在相似医院目录：\n\n「{matched}」\n\n"
                                f"您输入的是：「{hospital_name}」\n\n"
                                f"是否使用该已有目录？"
                            )
                            confirm_result[0] = r
                            confirm_event.set()
                        self.root.after(0, _ask)
                        confirm_event.wait()
                        if not confirm_result[0]:
                            self.log("❌ 用户取消操作")
                            return
                        hospital_name = matched
                        hospital_url = f"{svn_base.rstrip('/')}/{hospital_name}"
                        target_url = f"{hospital_url}/{order_name}"
                        self.log(f"✅ 使用已有医院目录：{hospital_url}")
                    else:
                        self.log("📁 医院目录不存在，正在创建...")
                        mkdir_code, out, err = run_svn_command([
                            "mkdir", hospital_url, "-m", f"Auto create hospital dir for {hospital_name}",
                            "--username", username,
                            "--password", password,
                            *_SVN_COMMON_ARGS
                        ], timeout=60)
                        if mkdir_code != 0:
                            raise Exception(f"创建医院目录失败: {err or out}")

                # 2. 检查并创建订单目录（在医院目录下，支持按订单号前缀模糊匹配）
                code, _, err = run_svn_command([
                    "info", target_url,
                    "--username", username,
                    "--password", password,
                    *_SVN_COMMON_ARGS
                ])
                if code != 0:
                    # 精确查找失败，列出医院目录下所有子目录按前缀匹配
                    self.log("🔍 订单目录精确匹配失败，正在搜索同编号订单...")
                    server_dirs = _svn_list_dirs(hospital_url, username, password)
                    matched = _find_matching_order(server_dirs, order_name)
                    if matched:
                        self.log(f"⚠️ 找到相似订单目录：{matched}")
                        confirm_result = [None]
                        confirm_event = threading.Event()
                        def _ask():
                            r = messagebox.askyesno(
                                "发现已有订单",
                                f"服务器上已存在相似订单目录：\n\n「{matched}」\n\n"
                                f"您输入的是：「{order_name}」\n\n"
                                f"是否使用该已有目录？"
                            )
                            confirm_result[0] = r
                            confirm_event.set()
                        self.root.after(0, _ask)
                        confirm_event.wait()
                        if not confirm_result[0]:
                            self.log("❌ 用户取消操作")
                            return
                        order_name = matched
                        target_url = f"{hospital_url}/{order_name}"
                        self.log(f"✅ 使用已有订单目录：{target_url}")
                    else:
                        self.log("📁 订单目录不存在，正在创建...")
                        mkdir_code, out, err = run_svn_command([
                            "mkdir", target_url, "-m", f"Auto create for {order_name}",
                            "--username", username,
                            "--password", password,
                            *_SVN_COMMON_ARGS
                        ], timeout=60)
                        if mkdir_code != 0:
                            raise Exception(f"创建订单目录失败: {err or out}")
                else:
                    self.log("✅ 订单目录已存在（精确匹配）")

            else:  # 门诊
                target_url = f"{svn_base.rstrip('/')}/{order_name}"
                self.log(f"门诊模式：订单目录 = {target_url}")

                # 检查并创建订单目录（支持按订单号前缀模糊匹配）
                code, _, err = run_svn_command([
                    "info", target_url,
                    "--username", username,
                    "--password", password,
                    *_SVN_COMMON_ARGS
                ])
                if code != 0:
                    # 精确查找失败，列出所有目录按前缀匹配
                    self.log("🔍 订单目录精确匹配失败，正在搜索同编号订单...")
                    server_dirs = _svn_list_dirs(svn_base.rstrip('/'), username, password)
                    matched = _find_matching_order(server_dirs, order_name)
                    if matched:
                        self.log(f"⚠️ 找到相似订单目录：{matched}")
                        confirm_result = [None]
                        confirm_event = threading.Event()
                        def _ask():
                            r = messagebox.askyesno(
                                "发现已有订单",
                                f"服务器上已存在相似订单目录：\n\n「{matched}」\n\n"
                                f"您输入的是：「{order_name}」\n\n"
                                f"是否使用该已有目录？"
                            )
                            confirm_result[0] = r
                            confirm_event.set()
                        self.root.after(0, _ask)
                        confirm_event.wait()
                        if not confirm_result[0]:
                            self.log("❌ 用户取消操作")
                            return
                        order_name = matched
                        target_url = f"{svn_base.rstrip('/')}/{order_name}"
                        self.log(f"✅ 使用已有订单目录：{target_url}")
                    else:
                        self.log("📁 订单目录不存在，正在创建...")
                        mkdir_code, out, err = run_svn_command([
                            "mkdir", target_url, "-m", f"Auto create for {order_name}",
                            "--username", username,
                            "--password", password,
                            *_SVN_COMMON_ARGS
                        ], timeout=60)
                        if mkdir_code != 0:
                            raise Exception(f"创建订单目录失败: {err or out}")
                else:
                    self.log("✅ 订单目录已存在（精确匹配）")

            # 检出到本地
            checkout_local_path = Path(local_dir) / order_name
            self.log(f"检出到本地: {checkout_local_path}")

            co_code, co_out, co_err = run_svn_command([
                "checkout", target_url, str(checkout_local_path),
                "--username", username,
                "--password", password,
                *_SVN_COMMON_ARGS
            ], timeout=300)

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
