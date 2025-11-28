# adb_device_manager.pyw

import os
import json
import logging
import subprocess
import threading
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "adb_device_manager"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR = CONFIG_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "adb_dir": r"D:\tools\QtScrcpy-win-x86-v3.3.1",
    "scrcpy_exe": r"D:\tools\QtScrcpy-win-x86-v3.3.1\QtScrcpy.exe",
    "device_ip": "192.168.1.100"
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

def run_adb_command(adb_path, args, cwd=None, shell=False):
    """执行 ADB 命令，返回 (returncode, stdout, stderr)"""
    try:
        cmd = [adb_path] + args
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            shell=shell,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)

def run_shell_sequence(adb_path, device_serial, commands):
    """在 adb shell 中顺序执行多条命令"""
    try:
        # 构建完整 shell 命令
        full_cmd = " && ".join(commands)
        result = subprocess.run(
            [adb_path, "-s", device_serial, "shell", full_cmd],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)

# ================== 主GUI类 ==================

class ADBDeviceManager:
    def __init__(self, root):
        self.root = root
        self.root.title("📱 ADB 设备管理器 - QtScrcpy 集成版")
        self.root.geometry("700x550")
        self.root.resizable(True, True)

        self.config = load_or_create_config()
        self.adb_executable = Path(self.config["adb_dir"]) / "adb.exe"

        self.setup_ui()
        self.update_display()

    def setup_ui(self):
        # ADB 路径设置
        frame_adb = LabelFrame(self.root, text="🔧 ADB 工具路径", padx=10, pady=10)
        frame_adb.pack(fill=X, padx=20, pady=10)

        self.adb_dir_var = StringVar(value=self.config["adb_dir"])
        Entry(frame_adb, textvariable=self.adb_dir_var, width=60, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_adb, text="📂 选择目录", command=self.select_adb_dir).pack(side=LEFT, padx=5)

        # Scrcpy 路径设置
        frame_scrcpy = LabelFrame(self.root, text="🖥️ QtScrcpy 投屏程序", padx=10, pady=10)
        frame_scrcpy.pack(fill=X, padx=20, pady=10)

        self.scrcpy_exe_var = StringVar(value=self.config["scrcpy_exe"])
        Entry(frame_scrcpy, textvariable=self.scrcpy_exe_var, width=60, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_scrcpy, text="📂 选择文件", command=self.select_scrcpy_exe).pack(side=LEFT, padx=5)

        # 设备IP输入
        frame_ip = LabelFrame(self.root, text="📡 设备IP地址", padx=10, pady=10)
        frame_ip.pack(fill=X, padx=20, pady=10)

        self.device_ip_var = StringVar(value=self.config["device_ip"])
        Entry(frame_ip, textvariable=self.device_ip_var, font=("Arial", 14), width=20).pack(side=LEFT, padx=5)
        Button(frame_ip, text="💾 保存IP", command=self.save_ip).pack(side=LEFT, padx=5)

        # 操作按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=20)

        Button(btn_frame, text="🔌 连接设备", command=self.connect_device, bg="#4CAF50", fg="white", width=12, height=2).grid(row=0, column=0, padx=10, pady=5)
        Button(btn_frame, text="📺 启动投屏", command=self.launch_scrcpy, bg="#2196F3", fg="white", width=12, height=2).grid(row=0, column=1, padx=10, pady=5)
        Button(btn_frame, text="🧹 清空设备", command=self.clear_device, bg="#FF9800", fg="white", width=12, height=2).grid(row=0, column=2, padx=10, pady=5)
        Button(btn_frame, text="📜 查看日志", command=self.view_logcat, bg="#9C27B0", fg="white", width=12, height=2).grid(row=0, column=3, padx=10, pady=5)

        # 状态显示
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 12))
        self.status_label.pack(pady=10)

        # 日志输出框（可选）
        log_frame = LabelFrame(self.root, text="📝 最近操作日志", padx=10, pady=10)
        log_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))

        self.log_text = Text(log_frame, height=8, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    def update_display(self):
        self.adb_dir_var.set(self.config["adb_dir"])
        self.scrcpy_exe_var.set(self.config["scrcpy_exe"])
        self.device_ip_var.set(self.config["device_ip"])
        self.adb_executable = Path(self.config["adb_dir"]) / "adb.exe"

    def select_adb_dir(self):
        folder = filedialog.askdirectory(initialdir=self.config["adb_dir"])
        if folder:
            self.config["adb_dir"] = folder
            save_config(self.config)
            self.update_display()
            logging.info(f"ADB 目录更新为: {folder}")

    def select_scrcpy_exe(self):
        file_path = filedialog.askopenfilename(
            title="选择 QtScrcpy.exe",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
            initialdir=Path(self.config["scrcpy_exe"]).parent
        )
        if file_path:
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
        self.status_label.config(text=f"IP 已保存: {ip}", fg="blue")
        logging.info(f"设备IP更新为: {ip}")

    def set_status(self, msg, color="black"):
        self.status_label.config(text=msg, fg=color)
        self.root.update_idletasks()

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    def connect_device(self):
        ip = self.device_ip_var.get().strip()
        if not ip:
            messagebox.showerror("错误", "请先输入设备IP！")
            return

        self.set_status("正在连接设备...", "orange")
        logging.info(f"尝试连接设备: {ip}")

        code, out, err = run_adb_command(str(self.adb_executable), ["connect", ip])
        if code == 0 and "connected" in out.lower():
            msg = f"✅ 成功连接 {ip}"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            logging.info(msg)
        else:
            msg = f"❌ 连接失败: {err or out}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.error(msg)
            messagebox.showerror("连接失败", msg)

    def launch_scrcpy(self):
        scrcpy_exe = self.scrcpy_exe_var.get()
        if not Path(scrcpy_exe).exists():
            messagebox.showerror("文件不存在", f"未找到 QtScrcpy.exe:\n{scrcpy_exe}")
            return

        try:
            # 启动投屏（不阻塞主线程）
            subprocess.Popen([scrcpy_exe], cwd=Path(scrcpy_exe).parent)
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

        confirm = messagebox.askyesno("确认操作", "此操作将清除设备配置并重启！\n确定继续？")
        if not confirm:
            return

        self.set_status("正在清空设备...", "orange")
        logging.info("开始执行设备清空流程")

        # 步骤1: 确保设备已连接
        code, _, _ = run_adb_command(str(self.adb_executable), ["connect", ip])
        if code != 0:
            self.set_status("⚠️ 设备未连接，尝试继续...", "orange")

        # 步骤2: 执行 shell 命令序列
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

        # 步骤3: 重启设备
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

        # 先连接设备
        run_adb_command(str(self.adb_executable), ["connect", ip])

        # 在新终端中打开 logcat（Windows 使用 start cmd）
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
