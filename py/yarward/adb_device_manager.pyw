# adb_device_manager.py
import os
import json
import sys
import logging
import subprocess
import threading
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))

# 判断是否打包为 exe
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，主程序在 _MEIPASS，但资源应放在 .exe 同级目录
    EXE_DIR = Path(sys.executable).parent
else:
    EXE_DIR = SCRIPT_DIR

# 自动查找 QtScrcpy 目录（在脚本/EXE 同级目录下）
CANDIDATE_QTSCRCPY_DIRS = [
    EXE_DIR / "QtScrcpy",
    EXE_DIR / "QtScrcpy-win-x86",
    EXE_DIR / "QtScrcpy-win-x64",
    ]

def auto_find_qtscrcpy():
    """自动查找 QtScrcpy 目录，返回 (adb_path, scrcpy_exe) 或 (None, None)"""
    for candidate in CANDIDATE_QTSCRCPY_DIRS:
        if candidate.is_dir():
            adb_exe = candidate / "adb.exe"
            scrcpy_exe = candidate / "QtScrcpy.exe"
            if adb_exe.exists() and scrcpy_exe.exists():
                return str(candidate), str(scrcpy_exe)
    return None, None

# 配置路径
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / "config_adb_device_manager.json"
CONFIG_DIR.mkdir(exist_ok=True)

LOGS_DIR = CONFIG_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOGS_DIR / "log_adb_device_manager.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置（无路径！）
DEFAULT_CONFIG = {
    "adb_dir": "",
    "scrcpy_exe": "",
    "device_ip": "192.168.1.100",
    "history_devices": []
}

# ================== 工具函数 ==================
def load_or_create_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 兼容旧配置，补充缺失字段
                if "history_devices" not in config:
                    config["history_devices"] = []
                logging.info("配置文件加载成功")
                return config
        except Exception as e:
            logging.error(f"配置文件解析失败: {e}")
            messagebox.showerror("配置错误", f"配置文件损坏，将使用默认配置。\n{e}")

    # 创建默认配置
    config = DEFAULT_CONFIG.copy()
    save_config(config)
    logging.info("已创建默认配置文件")
    return config

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logging.info("配置已保存")
    except Exception as e:
        logging.error(f"保存配置失败: {e}")
        messagebox.showerror("保存失败", f"无法保存配置：{e}")

def run_adb_command(adb_path, args, cwd=None, shell=False):
    try:
        cmd = [adb_path] + args
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', shell=shell, timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)

def run_shell_sequence(adb_path, device_serial, commands):
    try:
        full_cmd = " && ".join(commands)
        result = subprocess.run(
            [adb_path, "-s", device_serial, "shell", full_cmd],
            capture_output=True, text=True, encoding='utf-8', timeout=60
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)

# ================== 主GUI类 ==================
class ADBDeviceManager:
    MAX_HISTORY = 30  # 最多记住的历史设备数

    def __init__(self, root):
        self.root = root
        self.root.title("📱 ADB 设备管理器 - QtScrcpy 集成版")
        self.root.geometry("720x700")
        self.root.resizable(True, True)

        self.config = load_or_create_config()

        # 尝试自动填充路径（如果配置为空）
        if not self.config["adb_dir"] or not self.config["scrcpy_exe"]:
            adb_dir_auto, scrcpy_exe_auto = auto_find_qtscrcpy()
            if adb_dir_auto and scrcpy_exe_auto:
                self.config["adb_dir"] = adb_dir_auto
                self.config["scrcpy_exe"] = scrcpy_exe_auto
                save_config(self.config)
                logging.info(f"自动发现 QtScrcpy: {adb_dir_auto}")

        self.adb_executable = Path(self.config["adb_dir"]) / "adb.exe" if self.config["adb_dir"] else None

        # 历史设备列表
        self.history_devices = self.config.get("history_devices", [])

        self.setup_ui()
        self.update_display()
        self.validate_paths_on_startup()
        self.refresh_history_dropdown()

        # 启动后自动刷新已连接设备
        self.root.after(300, self.refresh_connected_devices)

    def validate_paths_on_startup(self):
        """启动时检查路径是否有效，无效则提示选择"""
        valid_adb = self.config["adb_dir"] and (Path(self.config["adb_dir"]) / "adb.exe").exists()
        valid_scrcpy = self.config["scrcpy_exe"] and Path(self.config["scrcpy_exe"]).exists()

        if not (valid_adb and valid_scrcpy):
            self.set_status("⚠️ 未找到 ADB 或 QtScrcpy，请设置路径", "orange")
            messagebox.showwarning(
                "路径缺失",
                "未检测到有效的 ADB 或 QtScrcpy 路径。\n"
                "请通过下方按钮选择 ADB 目录和 QtScrcpy.exe。"
            )

    def setup_ui(self):
        # ADB 路径设置
        frame_adb = LabelFrame(self.root, text="🔧 ADB 工具路径", padx=10, pady=10)
        frame_adb.pack(fill=X, padx=20, pady=(10, 5))
        self.adb_dir_var = StringVar(value=self.config.get("adb_dir", ""))
        Entry(frame_adb, textvariable=self.adb_dir_var, width=60, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_adb, text="📂 选择目录", command=self.select_adb_dir).pack(side=LEFT, padx=5)

        # Scrcpy 路径设置
        frame_scrcpy = LabelFrame(self.root, text="🖥️ QtScrcpy 投屏程序", padx=10, pady=10)
        frame_scrcpy.pack(fill=X, padx=20, pady=5)
        self.scrcpy_exe_var = StringVar(value=self.config.get("scrcpy_exe", ""))
        Entry(frame_scrcpy, textvariable=self.scrcpy_exe_var, width=60, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_scrcpy, text="📂 选择文件", command=self.select_scrcpy_exe).pack(side=LEFT, padx=5)

        # 设备IP输入 + 历史设备下拉
        frame_ip = LabelFrame(self.root, text="📡 设备IP地址", padx=10, pady=10)
        frame_ip.pack(fill=X, padx=20, pady=5)
        self.device_ip_var = StringVar(value=self.config.get("device_ip", "192.168.1.100"))
        Entry(frame_ip, textvariable=self.device_ip_var, font=("Arial", 14), width=20).pack(side=LEFT, padx=5)
        Button(frame_ip, text="💾 保存IP", command=self.save_ip).pack(side=LEFT, padx=5)

        # 历史设备下拉
        Label(frame_ip, text="历史设备:", font=("Arial", 10)).pack(side=LEFT, padx=(15, 5))
        self.history_combo = ttk.Combobox(frame_ip, textvariable=StringVar(), width=22, state="readonly", font=("Consolas", 10))
        self.history_combo.pack(side=LEFT, padx=5)
        self.history_combo.bind("<<ComboboxSelected>>", self.on_history_selected)

        # 操作按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="🔌 连接设备", command=self.connect_device, bg="#4CAF50", fg="white", width=12, height=2).grid(row=0, column=0, padx=10, pady=5)
        Button(btn_frame, text="📺 启动投屏", command=self.launch_scrcpy, bg="#2196F3", fg="white", width=12, height=2).grid(row=0, column=1, padx=10, pady=5)
        Button(btn_frame, text="🧹 清空设备", command=self.clear_device, bg="#FF9800", fg="white", width=12, height=2).grid(row=0, column=2, padx=10, pady=5)
        Button(btn_frame, text="📜 查看日志", command=self.view_logcat, bg="#9C27B0", fg="white", width=12, height=2).grid(row=0, column=3, padx=10, pady=5)

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
        Button(conn_btn_frame, text="🔄 刷新列表", command=self.refresh_connected_devices,
               bg="#607D8B", fg="white", width=12).pack(side=LEFT, padx=10)

        # 状态显示
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 12))
        self.status_label.pack(pady=5)

        # 日志输出框
        log_frame = LabelFrame(self.root, text="📝 最近操作日志", padx=10, pady=10)
        log_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))
        self.log_text = Text(log_frame, height=8, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    def update_display(self):
        self.adb_dir_var.set(self.config.get("adb_dir", ""))
        self.scrcpy_exe_var.set(self.config.get("scrcpy_exe", ""))
        self.device_ip_var.set(self.config.get("device_ip", "192.168.1.100"))
        adb_dir = self.config.get("adb_dir", "")
        self.adb_executable = Path(adb_dir) / "adb.exe" if adb_dir else None

    def select_adb_dir(self):
        folder = filedialog.askdirectory(initialdir=self.config.get("adb_dir", ""))
        if folder:
            adb_exe = Path(folder) / "adb.exe"
            if not adb_exe.exists():
                messagebox.showerror("无效目录", "所选目录中未找到 adb.exe！")
                return
            self.config["adb_dir"] = folder
            save_config(self.config)
            self.update_display()
            logging.info(f"ADB 目录更新为: {folder}")

    def select_scrcpy_exe(self):
        file_path = filedialog.askopenfilename(
            title="选择 QtScrcpy.exe",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
            initialdir=Path(self.config.get("scrcpy_exe", "")).parent if self.config.get("scrcpy_exe") else EXE_DIR
        )
        if file_path:
            if not file_path.endswith("QtScrcpy.exe"):
                messagebox.showwarning("注意", "建议选择 QtScrcpy.exe 文件以确保兼容性。")
            self.config["scrcpy_exe"] = file_path
            save_config(self.config)
            self.update_display()
            logging.info(f"Scrcpy 路径更新为: {file_path}")

    def save_ip(self):
        ip = self.device_ip_var.get().strip()
        if not ip:
            messagebox.showwarning("输入错误", "设备IP不能为空！")
            return
        self.config["device_ip"] = ip
        save_config(self.config)
        self.set_status(f"IP 已保存: {ip}", "blue")
        logging.info(f"设备IP更新为: {ip}")

    def set_status(self, msg, color="black"):
        self.status_label.config(text=msg, fg=color)
        self.root.update_idletasks()

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    # ------------------------------
    # 历史设备管理
    # ------------------------------
    def refresh_history_dropdown(self):
        """刷新历史设备下拉列表"""
        self.history_combo["values"] = self.history_devices
        if self.history_devices:
            self.history_combo.current(0)

    def add_to_history(self, ip: str):
        """将设备 IP 加入历史（去重，保持最新在前）"""
        if ip in self.history_devices:
            self.history_devices.remove(ip)
        self.history_devices.insert(0, ip)
        # 限制最大数量
        if len(self.history_devices) > self.MAX_HISTORY:
            self.history_devices = self.history_devices[:self.MAX_HISTORY]
        self.config["history_devices"] = self.history_devices
        save_config(self.config)
        self.refresh_history_dropdown()

    def on_history_selected(self, event=None):
        """历史下拉选中时，自动填入 IP"""
        selection = self.history_combo.get()
        if selection:
            self.device_ip_var.set(selection)

    # ------------------------------
    # 已连接设备管理
    # ------------------------------
    def refresh_connected_devices(self):
        """刷新已连接设备列表"""
        if not self.adb_executable or not self.adb_executable.exists():
            self.set_status("ADB 未设置或路径无效", "red")
            return

        code, out, _ = run_adb_command(str(self.adb_executable), ["devices"])
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

        if not self.adb_executable or not self.adb_executable.exists():
            messagebox.showerror("ADB 未设置", "请先设置有效的 ADB 路径！")
            return

        # 收集要断开的设备 ID
        devices_to_disconnect = []
        for idx in selection:
            text = self.connected_listbox.get(idx)
            dev_id = text.split("  [")[0]
            devices_to_disconnect.append(dev_id)

        for dev_id in devices_to_disconnect:
            code, out, err = run_adb_command(str(self.adb_executable), ["disconnect", dev_id])
            if code == 0:
                msg = f"🔌 已断开 {dev_id}"
                self.log_to_gui(msg)
                logging.info(msg)
            else:
                msg = f"⚠️ 断开 {dev_id} 失败: {err or out}"
                self.log_to_gui(msg)
                logging.warning(msg)

        self.refresh_connected_devices()

    def disconnect_all(self):
        """断开所有连接"""
        if not self.adb_executable or not self.adb_executable.exists():
            messagebox.showerror("ADB 未设置", "请先设置有效的 ADB 路径！")
            return

        count = self.connected_listbox.size()
        if count == 0:
            messagebox.showinfo("提示", "当前没有已连接的设备")
            return

        confirm = messagebox.askyesno("确认", f"确定要断开所有 {count} 台设备的连接吗？")
        if not confirm:
            return

        code, out, _ = run_adb_command(str(self.adb_executable), ["disconnect"])
        if code == 0:
            msg = f"⛔ 已断开所有设备连接（共 {count} 台）"
            self.set_status(msg, "orange")
            self.log_to_gui(msg)
            logging.info(msg)
        else:
            msg = "⚠️ 断开所有连接时出现问题"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.warning(msg)

        self.refresh_connected_devices()

    # ------------------------------
    # 连接设备
    # ------------------------------
    def connect_device(self):
        ip = self.device_ip_var.get().strip()
        if not ip:
            messagebox.showerror("错误", "请先输入设备IP！")
            return
        if not self.adb_executable or not self.adb_executable.exists():
            messagebox.showerror("ADB 未设置", "请先设置有效的 ADB 路径！")
            return

        self.set_status("正在连接设备...", "orange")
        logging.info(f"尝试连接设备: {ip}")
        code, out, err = run_adb_command(str(self.adb_executable), ["connect", ip])
        if code == 0 and "connected" in out.lower():
            msg = f"✅ 成功连接 {ip}"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            logging.info(msg)
            self.add_to_history(ip)
            # 延迟刷新已连接列表
            self.root.after(500, self.refresh_connected_devices)
        else:
            msg = f"❌ 连接失败: {err or out}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.error(msg)
            messagebox.showerror("连接失败", msg)

    def launch_scrcpy(self):
        scrcpy_exe = self.scrcpy_exe_var.get()
        if not scrcpy_exe or not Path(scrcpy_exe).exists():
            messagebox.showerror("文件不存在", "请先设置有效的 QtScrcpy.exe 路径！")
            return
        try:
            exe_path = Path(scrcpy_exe)
            subprocess.Popen([str(exe_path)], cwd=exe_path.parent)
            msg = "✅ 已启动 QtScrcpy 投屏"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            logging.info(msg)
        except Exception as e:
            msg = f"❌ 启动失败: {e}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.error(msg)
            messagebox.showerror("启动失败", str(e))

    def clear_device(self):
        ip = self.device_ip_var.get().strip()
        if not ip:
            messagebox.showerror("错误", "请先输入设备IP！")
            return
        if not self.adb_executable or not self.adb_executable.exists():
            messagebox.showerror("ADB 未设置", "请先设置有效的 ADB 路径！")
            return

        confirm = messagebox.askyesno("确认操作", "此操作将清除设备配置并重启！\n确定继续？")
        if not confirm:
            return

        self.set_status("正在清空设备...", "orange")
        logging.info("开始执行设备清空流程")

        # 确保连接
        run_adb_command(str(self.adb_executable), ["connect", ip])

        # 执行清理命令
        commands = [
            "cd /sdcard/ym801/config",
            "rm -rf YM801S.xml",
            "pm clear com.yarward.ym801"
        ]
        code, out, err = run_shell_sequence(str(self.adb_executable), ip + ":5555", commands)
        if code != 0:
            msg = f"⚠️ 清理配置出错: {err or out}"
            self.log_to_gui(msg)
            logging.warning(msg)

        # 重启设备
        self.log_to_gui("正在重启设备...")
        code, _, err = run_adb_command(str(self.adb_executable), ["-s", ip + ":5555", "reboot"])
        if code == 0:
            msg = "✅ 设备已重启"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            logging.info(msg)
        else:
            msg = f"❌ 重启失败: {err}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.error(msg)

    def view_logcat(self):
        ip = self.device_ip_var.get().strip()
        if not ip:
            messagebox.showerror("错误", "请先输入设备IP！")
            return
        if not self.adb_executable or not self.adb_executable.exists():
            messagebox.showerror("ADB 未设置", "请先设置有效的 ADB 路径！")
            return

        run_adb_command(str(self.adb_executable), ["connect", ip])
        try:
            cmd = f'cmd /k "{self.adb_executable} -s {ip}:5555 logcat -v threadtime"'
            subprocess.Popen(cmd, shell=True)
            msg = "✅ 已打开日志窗口"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            logging.info(msg)
        except Exception as e:
            msg = f"❌ 无法打开日志: {e}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.error(msg)

# ================== 启动程序 ==================
if __name__ == "__main__":
    root = Tk()
    app = ADBDeviceManager(root)
    root.mainloop()
