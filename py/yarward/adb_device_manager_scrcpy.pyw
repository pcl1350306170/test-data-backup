# adb_device_manager.pyw

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

# 如果被打包为 exe，则资源在 _internal 下（PyInstaller 标准做法）
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = SCRIPT_DIR

# 默认 scrcpy 路径（开发环境）
DEFAULT_SCRCPY_DIR = r"D:\tools\scrcpy-win64-v3.3.3"

# 运行时实际使用的 scrcpy 目录（优先用配置，其次默认，最后尝试打包内嵌）
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / "config_adb_device_manager_scrcpy.json"
LOGS_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOGS_DIR / "log_adb_device_manager.log"

CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# ==============================
# 工具函数
# ==============================
def get_scrcpy_dir_from_config():
    """从配置或默认值获取 scrcpy 目录"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                path = config.get("scrcpy_dir", "").strip()
                if path and Path(path).exists():
                    return Path(path)
        except Exception as e:
            logging.error(f"配置加载失败: {e}")

    # 尝试默认路径
    if Path(DEFAULT_SCRCPY_DIR).exists():
        return Path(DEFAULT_SCRCPY_DIR)

    # 尝试打包内嵌路径（_internal/scrcpy/）
    embedded = BASE_DIR / "_internal" / "scrcpy"
    if embedded.exists():
        return embedded

    # 兜底
    return Path(DEFAULT_SCRCPY_DIR)


def load_config():
    """加载完整配置（scrcpy路径 + 历史设备）"""
    config = {"scrcpy_dir": "", "history_devices": []}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    config["scrcpy_dir"] = data.get("scrcpy_dir", "")
                    config["history_devices"] = data.get("history_devices", [])
        except Exception as e:
            logging.error(f"配置加载失败: {e}")
    return config


def save_config(scrcpy_dir: Path, history_devices: list = None):
    try:
        data = {"scrcpy_dir": str(scrcpy_dir)}
        if history_devices is not None:
            data["history_devices"] = history_devices
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"配置已保存: scrcpy_dir={scrcpy_dir}, history={history_devices}")
    except Exception as e:
        logging.error(f"保存配置失败: {e}")
        messagebox.showerror("错误", f"无法保存配置：{e}")


def run_adb_command(adb_path, args, timeout=30):
    try:
        cmd = [str(adb_path)] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)


# ==============================
# GUI 主类
# ==============================
class ADBDeviceManager:
    MAX_HISTORY = 30  # 最多记住的历史设备数

    def __init__(self, root):
        self.root = root
        self.root.title("📱 ADB 设备管理器 - Scrcpy 集成版")
        self.root.geometry("720x620")
        self.root.resizable(True, True)

        # 初始化路径
        config = load_config()
        scrcpy_dir_str = config.get("scrcpy_dir", "").strip()
        if scrcpy_dir_str and Path(scrcpy_dir_str).exists():
            self.scrcpy_dir = Path(scrcpy_dir_str)
        else:
            self.scrcpy_dir = get_scrcpy_dir_from_config()

        self.adb_exe = self.scrcpy_dir / "adb.exe"
        self.scrcpy_exe = self.scrcpy_dir / "scrcpy.exe"

        # 历史设备列表
        self.history_devices = config.get("history_devices", [])

        self.setup_ui()
        self.update_display()
        self.refresh_history_dropdown()

        # 启动后自动刷新已连接设备
        self.root.after(300, self.refresh_connected_devices)

    # ------------------------------
    # UI 构建
    # ------------------------------
    def setup_ui(self):
        # Scrcpy 路径设置
        frame_scrcpy = LabelFrame(self.root, text="🖥️ Scrcpy 路径（含 adb.exe）", padx=10, pady=10)
        frame_scrcpy.pack(fill=X, padx=20, pady=(10, 5))

        self.scrcpy_dir_var = StringVar(value=str(self.scrcpy_dir))
        Entry(frame_scrcpy, textvariable=self.scrcpy_dir_var, width=60, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_scrcpy, text="📂 选择目录", command=self.select_scrcpy_dir).pack(side=LEFT, padx=5)

        # 设备 IP 输入 + 历史设备下拉
        frame_ip = LabelFrame(self.root, text="📡 设备 IP 地址（如 192.168.1.100）", padx=10, pady=10)
        frame_ip.pack(fill=X, padx=20, pady=5)

        self.device_ip_var = StringVar()
        ip_entry = Entry(frame_ip, textvariable=self.device_ip_var, font=("Arial", 14), width=20)
        ip_entry.pack(side=LEFT, padx=(5, 10))
        ip_entry.bind("<Return>", lambda e: self.connect_device())

        # 历史设备下拉
        Label(frame_ip, text="历史设备:", font=("Arial", 10)).pack(side=LEFT, padx=(10, 5))
        self.history_combo = ttk.Combobox(frame_ip, textvariable=StringVar(), width=22, state="readonly", font=("Consolas", 10))
        self.history_combo.pack(side=LEFT, padx=5)
        self.history_combo.bind("<<ComboboxSelected>>", self.on_history_selected)

        # 按钮区 - 连接 / 投屏 / 刷新
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=8)

        Button(btn_frame, text="🔌 连接设备", command=self.connect_device,
               bg="#4CAF50", fg="white", width=12, height=2).grid(row=0, column=0, padx=10)
        Button(btn_frame, text="📺 启动投屏", command=self.launch_scrcpy,
               bg="#2196F3", fg="white", width=12, height=2).grid(row=0, column=1, padx=10)
        Button(btn_frame, text="🔄 刷新状态", command=self.refresh_connected_devices,
               bg="#FF9800", fg="white", width=12, height=2).grid(row=0, column=2, padx=10)

        # ---- 已连接设备列表 ----
        connected_frame = LabelFrame(self.root, text="📋 已连接设备列表", padx=10, pady=5)
        connected_frame.pack(fill=X, padx=20, pady=5)

        list_inner = Frame(connected_frame)
        list_inner.pack(fill=X)

        self.connected_listbox = Listbox(list_inner, height=4, font=("Consolas", 10),
                                         selectmode=EXTENDED, bg="#f9f9f9")
        scrollbar_conn = Scrollbar(list_inner, orient=VERTICAL, command=self.connected_listbox.yview)
        self.connected_listbox.configure(yscrollcommand=scrollbar_conn.set)
        self.connected_listbox.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        scrollbar_conn.pack(side=RIGHT, fill=Y)

        conn_btn_frame = Frame(connected_frame)
        conn_btn_frame.pack(fill=X, pady=(5, 0))

        Button(conn_btn_frame, text="❌ 断开选中", command=self.disconnect_selected,
               bg="#f44336", fg="white", width=14).pack(side=LEFT, padx=10)
        Button(conn_btn_frame, text="⛔ 断开所有连接", command=self.disconnect_all,
               bg="#d32f2f", fg="white", width=18).pack(side=LEFT, padx=10)

        # 状态显示
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 12))
        self.status_label.pack(pady=5)

        # 日志输出
        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))

        self.log_text = Text(log_frame, height=6, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    # ------------------------------
    # 显示更新
    # ------------------------------
    def update_display(self):
        self.scrcpy_dir_var.set(str(self.scrcpy_dir))
        self.adb_exe = self.scrcpy_dir / "adb.exe"
        self.scrcpy_exe = self.scrcpy_dir / "scrcpy.exe"

    def refresh_history_dropdown(self):
        """刷新历史设备下拉列表"""
        self.history_combo["values"] = self.history_devices
        if self.history_devices:
            self.history_combo.current(0)

    # ------------------------------
    # 路径选择
    # ------------------------------
    def select_scrcpy_dir(self):
        folder = filedialog.askdirectory(initialdir=str(self.scrcpy_dir))
        if folder:
            new_dir = Path(folder)
            adb_path = new_dir / "adb.exe"
            scrcpy_path = new_dir / "scrcpy.exe"
            if not adb_path.exists():
                messagebox.showerror("错误", "所选目录中未找到 adb.exe！")
                return
            if not scrcpy_path.exists():
                messagebox.showwarning("警告", "未找到 scrcpy.exe，仅支持 ADB 功能。")

            self.scrcpy_dir = new_dir
            save_config(self.scrcpy_dir, self.history_devices)
            self.update_display()
            self.log_to_gui(f"Scrcpy 路径已更新为: {new_dir}")

    # ------------------------------
    # 状态与日志
    # ------------------------------
    def set_status(self, msg, color="black"):
        self.status_label.config(text=msg, fg=color)
        self.root.update_idletasks()

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logging.info(msg)

    # ------------------------------
    # 历史设备管理
    # ------------------------------
    def add_to_history(self, ip: str):
        """将设备 IP 加入历史（去重，保持最新在前）"""
        if ip in self.history_devices:
            self.history_devices.remove(ip)
        self.history_devices.insert(0, ip)
        # 限制最大数量
        if len(self.history_devices) > self.MAX_HISTORY:
            self.history_devices = self.history_devices[:self.MAX_HISTORY]
        save_config(self.scrcpy_dir, self.history_devices)
        self.refresh_history_dropdown()

    def remove_from_history(self, ip: str):
        """从历史中移除设备"""
        if ip in self.history_devices:
            self.history_devices.remove(ip)
            save_config(self.scrcpy_dir, self.history_devices)
            self.refresh_history_dropdown()

    def on_history_selected(self, event=None):
        """历史下拉选中时，自动填入 IP 并连接"""
        selection = self.history_combo.get()
        if selection:
            self.device_ip_var.set(selection)

    # ------------------------------
    # 连接设备
    # ------------------------------
    def connect_device(self):
        ip = self.device_ip_var.get().strip()
        if not ip:
            messagebox.showerror("错误", "请输入设备 IP 地址！")
            return

        if not self.adb_exe.exists():
            messagebox.showerror("错误", f"adb.exe 不存在：{self.adb_exe}")
            return

        self.set_status("正在连接设备...", "orange")
        code, out, err = run_adb_command(self.adb_exe, ["connect", ip])
        if code == 0 and ("connected" in out.lower() or "already connected" in out.lower()):
            msg = f"✅ 成功连接 {ip}"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            self.add_to_history(ip)
            # 延迟刷新已连接列表
            self.root.after(500, self.refresh_connected_devices)
        else:
            msg = f"❌ 连接失败: {err or out}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            messagebox.showerror("连接失败", msg)

    # ------------------------------
    # 已连接设备管理
    # ------------------------------
    def refresh_connected_devices(self):
        """刷新已连接设备列表"""
        if not self.adb_exe.exists():
            self.set_status("adb.exe 不存在", "red")
            return

        code, out, _ = run_adb_command(self.adb_exe, ["devices"])
        self.connected_listbox.delete(0, END)

        if code == 0:
            lines = [line.strip() for line in out.strip().split('\n') if '\t' in line]
            devices = []
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 2:
                    dev_id = parts[0]
                    dev_state = parts[1]
                    devices.append(dev_id)
                    display = f"{dev_id}  [{dev_state}]"
                    self.connected_listbox.insert(END, display)

            count = len(devices)
            if count > 0:
                self.set_status(f"已连接设备数: {count}", "blue")
                self.log_to_gui(f"已连接 {count} 台设备: {', '.join(devices)}")
            else:
                self.set_status("当前无已连接设备", "gray")
        else:
            self.set_status("adb devices 命令失败", "red")

    def disconnect_selected(self):
        """断开选中的设备"""
        selection = self.connected_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要断开的设备")
            return

        # 收集要断开的设备 ID（从后往前删，避免索引偏移）
        devices_to_disconnect = []
        for idx in selection:
            text = self.connected_listbox.get(idx)
            dev_id = text.split("  [")[0]  # 提取 IP:port 部分
            devices_to_disconnect.append(dev_id)

        for dev_id in devices_to_disconnect:
            code, out, err = run_adb_command(self.adb_exe, ["disconnect", dev_id])
            if code == 0:
                msg = f"🔌 已断开 {dev_id}"
                self.log_to_gui(msg)
            else:
                msg = f"⚠️ 断开 {dev_id} 失败: {err or out}"
                self.log_to_gui(msg)

        self.refresh_connected_devices()

    def disconnect_all(self):
        """断开所有连接"""
        if not self.adb_exe.exists():
            return

        # 先获取当前列表中的设备
        count = self.connected_listbox.size()
        if count == 0:
            messagebox.showinfo("提示", "当前没有已连接的设备")
            return

        confirm = messagebox.askyesno("确认", f"确定要断开所有 {count} 台设备的连接吗？")
        if not confirm:
            return

        code, out, _ = run_adb_command(self.adb_exe, ["disconnect"])
        if code == 0:
            msg = f"⛔ 已断开所有设备连接（共 {count} 台）"
            self.set_status(msg, "orange")
            self.log_to_gui(msg)
        else:
            msg = "⚠️ 断开所有连接时出现问题"
            self.set_status(msg, "red")
            self.log_to_gui(msg)

        self.refresh_connected_devices()

    # ------------------------------
    # 启动投屏
    # ------------------------------
    def launch_scrcpy(self):
        if not self.scrcpy_exe.exists():
            messagebox.showerror("错误", f"scrcpy.exe 不存在：{self.scrcpy_exe}")
            return

        try:
            # 启动 scrcpy（不阻塞）
            subprocess.Popen([str(self.scrcpy_exe), "--no-audio"], cwd=self.scrcpy_dir)
            msg = "✅ 已启动 Scrcpy 投屏"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
        except Exception as e:
            msg = f"❌ 启动失败: {e}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            messagebox.showerror("启动失败", str(e))


# ==============================
# 启动程序
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = ADBDeviceManager(root)
    root.mainloop()
