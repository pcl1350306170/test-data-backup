# network_configurator.pyw

import os
import json
import logging
import subprocess
import sys
from pathlib import Path
from tkinter import *
from tkinter import messagebox, ttk

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "network_configurator"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOGS_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# 默认配置
DEFAULT_CONFIG = {
    "ip_address": "192.168.1.100",
    "subnet_mask": "255.255.255.0",
    "gateway": "192.168.1.1",
    "dns_primary": "8.8.8.8",
    "dns_secondary": "114.114.114.114"
}

# ==============================
# 工具函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return DEFAULT_CONFIG

def save_config(data):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def get_network_interfaces():
    """获取可用的以太网/Wi-Fi 接口名称（Windows）"""
    try:
        result = subprocess.run(["netsh", "interface", "show", "interface"], capture_output=True, text=True, shell=True)
        lines = result.stdout.splitlines()
        interfaces = []
        for line in lines:
            if "已启用" in line or "Enabled" in line:
                # 提取接口名（通常在最后）
                parts = line.strip().split()
                if len(parts) >= 4:
                    name = " ".join(parts[3:])
                    interfaces.append(name)
        return interfaces
    except Exception as e:
        logger.error(f"获取网络接口失败: {e}")
        return ["以太网", "本地连接", "Wi-Fi"]  # 常见默认名兜底

def configure_network(ip, subnet, gateway, dns1, dns2, interface_name):
    """使用 netsh 配置静态 IP（仅 Windows）"""
    if sys.platform != "win32":
        raise OSError("此脚本仅支持 Windows 系统")

    try:
        # 设置静态 IP
        cmd_ip = [
            "netsh", "interface", "ip", "set", "address",
            f"name={interface_name}",
            "source=static",
            f"addr={ip}",
            f"mask={subnet}",
            f"gateway={gateway}",
            "gwmetric=1"
        ]
        subprocess.run(cmd_ip, check=True, shell=True, capture_output=True)

        # 设置 DNS
        cmd_dns1 = [
            "netsh", "interface", "ip", "set", "dns",
            f"name={interface_name}",
            "source=static",
            f"addr={dns1}"
        ]
        subprocess.run(cmd_dns1, check=True, shell=True, capture_output=True)

        if dns2.strip():
            cmd_dns2 = [
                "netsh", "interface", "ip", "add", "dns",
                f"name={interface_name}",
                f"addr={dns2}",
                "index=2"
            ]
            subprocess.run(cmd_dns2, check=True, shell=True, capture_output=True)

        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"netsh 命令失败: {e}")
        return False
    except Exception as e:
        logger.error(f"配置网络时出错: {e}")
        return False

# ==============================
# GUI 主类
# ==============================
class NetworkConfigGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🌐 一键配置电脑网络（IPv4）")
        self.root.geometry("500x420")
        self.root.resizable(False, False)

        self.config = load_config()
        self.setup_ui()

    def setup_ui(self):
        # 网络接口选择
        frame_iface = LabelFrame(self.root, text="🔌 网络接口", padx=10, pady=5)
        frame_iface.pack(fill=X, padx=10, pady=5)
        self.interface_var = StringVar()
        interfaces = get_network_interfaces()
        if not interfaces:
            interfaces = ["以太网"]
        self.interface_var.set(interfaces[0])
        OptionMenu(frame_iface, self.interface_var, *interfaces).pack(pady=3)

        # IP 地址
        frame_ip = LabelFrame(self.root, text="📡 IP 地址", padx=10, pady=5)
        frame_ip.pack(fill=X, padx=10, pady=5)
        self.ip_var = StringVar(value=self.config.get("ip_address", DEFAULT_CONFIG["ip_address"]))
        Entry(frame_ip, textvariable=self.ip_var, font=("Consolas", 10)).pack(fill=X, pady=3)

        # 子网掩码
        frame_mask = LabelFrame(self.root, text="🧮 子网掩码", padx=10, pady=5)
        frame_mask.pack(fill=X, padx=10, pady=5)
        self.mask_var = StringVar(value=self.config.get("subnet_mask", DEFAULT_CONFIG["subnet_mask"]))
        Entry(frame_mask, textvariable=self.mask_var, font=("Consolas", 10)).pack(fill=X, pady=3)

        # 网关
        frame_gw = LabelFrame(self.root, text="🚪 默认网关", padx=10, pady=5)
        frame_gw.pack(fill=X, padx=10, pady=5)
        self.gw_var = StringVar(value=self.config.get("gateway", DEFAULT_CONFIG["gateway"]))
        Entry(frame_gw, textvariable=self.gw_var, font=("Consolas", 10)).pack(fill=X, pady=3)

        # DNS
        frame_dns = LabelFrame(self.root, text="🔍 DNS 服务器", padx=10, pady=5)
        frame_dns.pack(fill=X, padx=10, pady=5)
        self.dns1_var = StringVar(value=self.config.get("dns_primary", DEFAULT_CONFIG["dns_primary"]))
        self.dns2_var = StringVar(value=self.config.get("dns_secondary", DEFAULT_CONFIG["dns_secondary"]))
        Frame_dns1 = Frame(frame_dns)
        Frame_dns1.pack(fill=X)
        Entry(Frame_dns1, textvariable=self.dns1_var, width=20, font=("Consolas", 10)).pack(side=LEFT, padx=(0,5))
        Label(Frame_dns1, text="主").pack(side=LEFT)

        Frame_dns2 = Frame(frame_dns)
        Frame_dns2.pack(fill=X, pady=(5,0))
        Entry(Frame_dns2, textvariable=self.dns2_var, width=20, font=("Consolas", 10)).pack(side=LEFT, padx=(0,5))
        Label(Frame_dns2, text="备").pack(side=LEFT)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        Button(btn_frame, text="💾 保存配置", command=self.save_config_action, bg="#2196F3", fg="white", width=12).pack(side=LEFT, padx=5)
        Button(btn_frame, text="🚀 应用并配置网络", command=self.apply_network_config, bg="#4CAF50", fg="white", width=18, height=2).pack(side=LEFT, padx=5)

        # 状态标签
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 10))
        self.status_label.pack(pady=5)

    def log(self, msg):
        logger.info(msg)

    def set_status(self, msg, color="black"):
        self.status_label.config(text=msg, fg=color)
        self.root.update_idletasks()

    def save_config_action(self):
        config = {
            "ip_address": self.ip_var.get().strip(),
            "subnet_mask": self.mask_var.get().strip(),
            "gateway": self.gw_var.get().strip(),
            "dns_primary": self.dns1_var.get().strip(),
            "dns_secondary": self.dns2_var.get().strip()
        }
        save_config(config)
        self.config = config
        self.log("✅ 配置已保存")
        messagebox.showinfo("提示", "配置已保存！")

    def apply_network_config(self):
        ip = self.ip_var.get().strip()
        mask = self.mask_var.get().strip()
        gw = self.gw_var.get().strip()
        dns1 = self.dns1_var.get().strip()
        dns2 = self.dns2_var.get().strip()
        iface = self.interface_var.get().strip()

        if not all([ip, mask, gw, dns1, iface]):
            messagebox.showerror("输入错误", "请填写完整网络参数！")
            return

        # 保存当前配置
        self.save_config_action()

        self.set_status("正在配置网络...", "blue")
        self.root.update()

        success = configure_network(ip, mask, gw, dns1, dns2, iface)

        if success:
            self.set_status("✅ 网络配置成功！", "green")
            self.log(f"网络配置成功: IP={ip}, 接口={iface}")
            messagebox.showinfo("成功", f"网络已配置为：\nIP: {ip}\n接口: {iface}")
        else:
            self.set_status("❌ 配置失败，请以管理员身份运行！", "red")
            self.log("网络配置失败")
            messagebox.showerror("失败", "配置失败！\n\n请确保：\n1. 以【管理员身份运行】此程序\n2. 网络接口名称正确\n3. 参数格式合法")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 可选：检查 DB_CONFIG.json（虽不用，但按要求引入路径）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_config = json.load(f)
        except Exception as e:
            logger.warning(f"DB_CONFIG 加载失败（非必需）: {e}")

    root = Tk()
    app = NetworkConfigGUI(root)
    root.mainloop()
