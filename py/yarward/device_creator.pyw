# device_creator.pyw - 批量创建设备测试数据工具

import os
import json
import logging
import threading
import time
import uuid
import random
from pathlib import Path
from tkinter import *
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "device_creator"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOGS_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"

CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8')]
)
logger = logging.getLogger()

DEFAULT_CONFIG = {
    "server_ip": "192.168.31.97",
    "port": "7000",
    "context_path": "/tdms",
    "org_id": "2d07238e7b0f4381a5b9f9c63c4f99b2",
    "dept_id": "",
    "device_type": "wnBedSideExtension",
    "api_version": "old",
    "device_count": 10,
    "start_device_num": "BED001",
    "start_ip": "192.168.31.201",
    "device_model": "A10",
    "room_id_template": "",
    "bed_id_template": "",
    "mac_prefix": "AA:BB:CC:DD:EE",
    "device_name_prefix": "床旁分机",
    "versions_json": json.dumps({
        "appVersion": "3.4.2.004-20260327",
        "authVersion": "1.2.5",
        "callVersion": "1.61.0.17-alpha163",
        "upbsVersion": "3.4.0.004-20251017",
        "systemVersion": "rk3566_rgo-userdebug 11 RQ2A.210505.003 eng.yarwar.20230908.222902 release-keys",
        "hardwareVersion": "无硬件版本信息 - 4C:31:2D:2B:32:0B"
    }, ensure_ascii=False, indent=2),
    "params_json": json.dumps({
        "rotate": "0",
        "volume": "6",
        "brighter": "0",
        "resolution": "1024*600"
    }, ensure_ascii=False, indent=2),
    "positions_json": json.dumps({
        "bedId": "",
        "roomId": "",
        "roomIdList": [],
        "positionStr": None,
        "InstallationRoomId": ""
    }, ensure_ascii=False, indent=2)
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(data):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


# ==============================
# 数据生成工具
# ==============================
def generate_uuid():
    return str(uuid.uuid4()).replace('-', '')


def generate_device_app_id():
    return ''.join(random.choices('0123456789abcdef', k=16))


def parse_number(s):
    """从字符串末尾提取数字部分"""
    import re
    m = re.search(r'(\d+)$', s)
    return int(m.group(1)) if m else 0


def generate_device_num(start_num_str, index):
    """生成设备号，如 BED001 -> BED002 -> BED003"""
    import re
    base_num = parse_number(start_num_str)
    prefix = re.sub(r'\d+$', '', start_num_str)
    current = base_num + index
    return f"{prefix}{current:03d}"


def generate_ip(start_ip, index):
    """生成递增IP"""
    parts = start_ip.split('.')
    last_octet = int(parts[3]) + index
    if last_octet > 254:
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}.{last_octet}"


def generate_mac(prefix, index):
    last_part = f"{index:02X}"
    return f"{prefix}:{last_part}"


def generate_device_name(prefix, index):
    return f"{prefix}{index + 1:03d}"


def replace_template(template, index):
    if not template:
        return ''
    return template.replace('{index}', f"{index + 1:03d}")


def build_request_data(cfg, index):
    """构建单个设备的请求数据"""
    device_id = generate_uuid()
    device_num = generate_device_num(cfg['start_device_num'], index)
    ip = generate_ip(cfg['start_ip'], index)
    if not ip:
        raise ValueError(f"IP地址超出范围 (index={index})")

    data = {
        "ip": ip,
        "deviceName": generate_device_name(cfg['device_name_prefix'], index),
        "deviceNum": device_num,
        "deviceAppId": generate_device_app_id(),
        "deviceType": cfg['device_type'],
        "orgId": cfg['org_id'],
        "deviceModel": cfg['device_model'],
        "mac": generate_mac(cfg['mac_prefix'], index)
    }

    # 新接口需要 deviceId
    if cfg['api_version'] == 'new':
        data['deviceId'] = device_id

    if cfg.get('dept_id'):
        data['deptId'] = cfg['dept_id']

    # Versions
    if cfg.get('versions_json'):
        data['versions'] = cfg['versions_json']

    # Params
    if cfg.get('params_json'):
        data['params'] = cfg['params_json']

    # Positions (替换模板)
    if cfg.get('positions_json'):
        try:
            positions = json.loads(cfg['positions_json'])
            positions['roomId'] = replace_template(cfg.get('room_id_template', ''), index)
            positions['bedId'] = replace_template(cfg.get('bed_id_template', ''), index)
            data['positions'] = json.dumps(positions, ensure_ascii=False)
        except json.JSONDecodeError:
            pass

    return data, device_id


def get_api_url(cfg):
    port = cfg['port']
    port_str = '' if port == '80' else f':{port}'
    api_path = '/app-td/device/new' if cfg['api_version'] == 'new' else '/app-td/device'
    return f"http://{cfg['server_ip']}{port_str}{cfg['context_path']}{api_path}"


# ==============================
# GUI
# ==============================
class DeviceCreatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🛏️ 批量创建设备测试数据")
        self.root.geometry("780x750")
        self.root.minsize(700, 700)

        self.config = load_config()
        self.is_running = False
        self._setup_ui()
        self._load_ui_from_config()

    def _setup_ui(self):
        # 使用 Notebook 创建标签页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=5)

        # ========== 标签页1：设备配置 + 日志 ==========
        tab1_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab1_frame, text="📱 设备配置")

        # 标签页1 使用 Canvas + Scrollbar
        canvas_frame1 = ttk.Frame(tab1_frame)
        canvas_frame1.pack(fill=BOTH, expand=True)
        self.canvas1 = Canvas(canvas_frame1, highlightthickness=0)
        sb1 = ttk.Scrollbar(canvas_frame1, orient=VERTICAL, command=self.canvas1.yview)
        scroll1 = ttk.Frame(self.canvas1)
        scroll1.bind("<Configure>", lambda e: self.canvas1.configure(scrollregion=self.canvas1.bbox("all")))
        self.canvas1.create_window((0, 0), window=scroll1, anchor="nw")
        self.canvas1.configure(yscrollcommand=sb1.set)
        self.canvas1.pack(side=LEFT, fill=BOTH, expand=True)
        sb1.pack(side=RIGHT, fill=Y)
        self.canvas1.bind_all("<MouseWheel>", lambda e: self.canvas1.yview_scroll(int(-1*(e.delta/120)), "units"))

        main = scroll1
        pad = dict(padx=8, pady=3)

        # --- 服务器配置 ---
        frame_server = ttk.LabelFrame(main, text="🌐 服务器配置", padding=6)
        frame_server.pack(fill=X, **pad)

        r = 0
        ttk.Label(frame_server, text="服务器IP:").grid(row=r, column=0, sticky=W, pady=2)
        self.server_ip_var = StringVar()
        ttk.Entry(frame_server, textvariable=self.server_ip_var, width=25).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_server, text="端口号:").grid(row=r, column=0, sticky=W, pady=2)
        self.port_var = StringVar()
        ttk.Entry(frame_server, textvariable=self.port_var, width=10).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_server, text="上下文路径:").grid(row=r, column=0, sticky=W, pady=2)
        self.context_path_var = StringVar()
        ttk.Entry(frame_server, textvariable=self.context_path_var, width=25).grid(row=r, column=1, sticky=W, padx=5)

        # --- 设备配置 ---
        frame_device = ttk.LabelFrame(main, text="📱 设备配置", padding=6)
        frame_device.pack(fill=X, **pad)

        r = 0
        ttk.Label(frame_device, text="机构ID:").grid(row=r, column=0, sticky=W, pady=2)
        self.org_id_var = StringVar()
        ttk.Entry(frame_device, textvariable=self.org_id_var, width=45).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_device, text="科室ID:").grid(row=r, column=0, sticky=W, pady=2)
        self.dept_id_var = StringVar()
        ttk.Entry(frame_device, textvariable=self.dept_id_var, width=45).grid(row=r, column=1, sticky=W, padx=5)
        ttk.Label(frame_device, text="(可选)", foreground="gray").grid(row=r, column=2, sticky=W)
        r += 1
        ttk.Label(frame_device, text="设备类型:").grid(row=r, column=0, sticky=W, pady=2)
        self.device_type_var = StringVar()
        ttk.Combobox(frame_device, textvariable=self.device_type_var, width=25, state="readonly",
                      values=["wnBedHeadExtension", "wnBedSideExtension"]).grid(row=r, column=1, sticky=W, padx=5)
        self.device_type_display = {"wnBedHeadExtension": "🛏️ 床头分机", "wnBedSideExtension": "🖥️ 床旁分机"}
        r += 1
        ttk.Label(frame_device, text="接口版本:").grid(row=r, column=0, sticky=W, pady=2)
        self.api_version_var = StringVar()
        api_frame = ttk.Frame(frame_device)
        api_frame.grid(row=r, column=1, sticky=W, padx=5)
        ttk.Radiobutton(api_frame, text="老接口 (/app-td/device)", variable=self.api_version_var, value="old").pack(side=LEFT)
        ttk.Radiobutton(api_frame, text="新接口 (/app-td/device/new)", variable=self.api_version_var, value="new").pack(side=LEFT, padx=10)
        r += 1
        ttk.Label(frame_device, text="设备数量:").grid(row=r, column=0, sticky=W, pady=2)
        self.device_count_var = StringVar()
        ttk.Entry(frame_device, textvariable=self.device_count_var, width=10).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_device, text="起始设备号:").grid(row=r, column=0, sticky=W, pady=2)
        self.start_device_num_var = StringVar()
        ttk.Entry(frame_device, textvariable=self.start_device_num_var, width=20).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_device, text="起始IP地址:").grid(row=r, column=0, sticky=W, pady=2)
        self.start_ip_var = StringVar()
        ttk.Entry(frame_device, textvariable=self.start_ip_var, width=20).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_device, text="设备型号:").grid(row=r, column=0, sticky=W, pady=2)
        self.device_model_var = StringVar()
        ttk.Combobox(frame_device, textvariable=self.device_model_var, width=15,
                      values=["A10", "A27L", "A36", "A25"]).grid(row=r, column=1, sticky=W, padx=5)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=X, padx=8, pady=8)
        self.btn_start = ttk.Button(btn_frame, text="🚀 开始添加设备", command=self._start_create)
        self.btn_start.pack(side=LEFT, padx=3)
        ttk.Button(btn_frame, text="👁️ 预览数据", command=self._preview_data).pack(side=LEFT, padx=3)
        ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config).pack(side=LEFT, padx=3)
        ttk.Button(btn_frame, text="🔄 重置", command=self._reset_form).pack(side=LEFT, padx=3)

        # --- 进度 ---
        self.progress = ttk.Progressbar(main, mode='determinate')
        self.progress.pack(fill=X, padx=8, pady=(0, 3))
        self.progress_label = Label(main, text="", fg="blue", wraplength=600, justify=LEFT)
        self.progress_label.pack(pady=2)

        # --- 日志 ---
        frame_log = ttk.LabelFrame(main, text="📝 操作日志", padding=4)
        frame_log.pack(fill=BOTH, expand=True, padx=8, pady=(0, 5))
        self.log_text = scrolledtext.ScrolledText(frame_log, height=8, state=DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

        # ========== 标签页2：高级配置 ==========
        tab2_frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab2_frame, text="⚙️ 高级配置")

        canvas_frame2 = ttk.Frame(tab2_frame)
        canvas_frame2.pack(fill=BOTH, expand=True)
        self.canvas2 = Canvas(canvas_frame2, highlightthickness=0)
        sb2 = ttk.Scrollbar(canvas_frame2, orient=VERTICAL, command=self.canvas2.yview)
        scroll2 = ttk.Frame(self.canvas2)
        scroll2.bind("<Configure>", lambda e: self.canvas2.configure(scrollregion=self.canvas2.bbox("all")))
        self.canvas2.create_window((0, 0), window=scroll2, anchor="nw")
        self.canvas2.configure(yscrollcommand=sb2.set)
        self.canvas2.pack(side=LEFT, fill=BOTH, expand=True)
        sb2.pack(side=RIGHT, fill=Y)

        adv = scroll2
        apad = dict(padx=8, pady=3)

        # --- 模板配置 ---
        frame_tpl = ttk.LabelFrame(adv, text="🏷️ ID与名称模板", padding=6)
        frame_tpl.pack(fill=X, **apad)

        r = 0
        ttk.Label(frame_tpl, text="房间ID模板:").grid(row=r, column=0, sticky=W, pady=2)
        self.room_id_template_var = StringVar()
        ttk.Entry(frame_tpl, textvariable=self.room_id_template_var, width=35).grid(row=r, column=1, sticky=W, padx=5)
        ttk.Label(frame_tpl, text="如 room{index}", foreground="gray").grid(row=r, column=2, sticky=W)
        r += 1
        ttk.Label(frame_tpl, text="床位ID模板:").grid(row=r, column=0, sticky=W, pady=2)
        self.bed_id_template_var = StringVar()
        ttk.Entry(frame_tpl, textvariable=self.bed_id_template_var, width=35).grid(row=r, column=1, sticky=W, padx=5)
        ttk.Label(frame_tpl, text="如 bed{index}", foreground="gray").grid(row=r, column=2, sticky=W)
        r += 1
        ttk.Label(frame_tpl, text="MAC地址前缀:").grid(row=r, column=0, sticky=W, pady=2)
        self.mac_prefix_var = StringVar()
        ttk.Entry(frame_tpl, textvariable=self.mac_prefix_var, width=25).grid(row=r, column=1, sticky=W, padx=5)
        r += 1
        ttk.Label(frame_tpl, text="设备名称前缀:").grid(row=r, column=0, sticky=W, pady=2)
        self.device_name_prefix_var = StringVar()
        ttk.Entry(frame_tpl, textvariable=self.device_name_prefix_var, width=25).grid(row=r, column=1, sticky=W, padx=5)

        # --- JSON 配置 ---
        frame_json = ttk.LabelFrame(adv, text="📄 JSON 参数配置", padding=6)
        frame_json.pack(fill=BOTH, expand=True, **apad)

        r = 0
        ttk.Label(frame_json, text="Versions JSON:").grid(row=r, column=0, sticky=NW, pady=2)
        self.versions_text = scrolledtext.ScrolledText(frame_json, height=6, width=55, font=("Consolas", 9))
        self.versions_text.grid(row=r, column=1, sticky=EW, padx=5, pady=2)
        r += 1
        ttk.Label(frame_json, text="Params JSON:").grid(row=r, column=0, sticky=NW, pady=2)
        self.params_text = scrolledtext.ScrolledText(frame_json, height=5, width=55, font=("Consolas", 9))
        self.params_text.grid(row=r, column=1, sticky=EW, padx=5, pady=2)
        r += 1
        ttk.Label(frame_json, text="Positions JSON:").grid(row=r, column=0, sticky=NW, pady=2)
        self.positions_text = scrolledtext.ScrolledText(frame_json, height=5, width=55, font=("Consolas", 9))
        self.positions_text.grid(row=r, column=1, sticky=EW, padx=5, pady=2)

    def _log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {msg}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def _get_config_from_ui(self):
        return {
            "server_ip": self.server_ip_var.get().strip(),
            "port": self.port_var.get().strip(),
            "context_path": self.context_path_var.get().strip(),
            "org_id": self.org_id_var.get().strip(),
            "dept_id": self.dept_id_var.get().strip(),
            "device_type": self.device_type_var.get().strip(),
            "api_version": self.api_version_var.get().strip(),
            "device_count": int(self.device_count_var.get().strip() or 10),
            "start_device_num": self.start_device_num_var.get().strip(),
            "start_ip": self.start_ip_var.get().strip(),
            "device_model": self.device_model_var.get().strip(),
            "room_id_template": self.room_id_template_var.get().strip(),
            "bed_id_template": self.bed_id_template_var.get().strip(),
            "mac_prefix": self.mac_prefix_var.get().strip(),
            "device_name_prefix": self.device_name_prefix_var.get().strip(),
            "versions_json": self.versions_text.get("1.0", END).strip(),
            "params_json": self.params_text.get("1.0", END).strip(),
            "positions_json": self.positions_text.get("1.0", END).strip()
        }

    def _load_ui_from_config(self):
        c = self.config
        self.server_ip_var.set(c.get("server_ip", DEFAULT_CONFIG["server_ip"]))
        self.port_var.set(c.get("port", DEFAULT_CONFIG["port"]))
        self.context_path_var.set(c.get("context_path", DEFAULT_CONFIG["context_path"]))
        self.org_id_var.set(c.get("org_id", DEFAULT_CONFIG["org_id"]))
        self.dept_id_var.set(c.get("dept_id", ""))
        self.device_type_var.set(c.get("device_type", DEFAULT_CONFIG["device_type"]))
        self.api_version_var.set(c.get("api_version", DEFAULT_CONFIG["api_version"]))
        self.device_count_var.set(str(c.get("device_count", DEFAULT_CONFIG["device_count"])))
        self.start_device_num_var.set(c.get("start_device_num", DEFAULT_CONFIG["start_device_num"]))
        self.start_ip_var.set(c.get("start_ip", DEFAULT_CONFIG["start_ip"]))
        self.device_model_var.set(c.get("device_model", DEFAULT_CONFIG["device_model"]))
        self.room_id_template_var.set(c.get("room_id_template", ""))
        self.bed_id_template_var.set(c.get("bed_id_template", ""))
        self.mac_prefix_var.set(c.get("mac_prefix", DEFAULT_CONFIG["mac_prefix"]))
        self.device_name_prefix_var.set(c.get("device_name_prefix", DEFAULT_CONFIG["device_name_prefix"]))

        self.versions_text.delete("1.0", END)
        self.versions_text.insert(END, c.get("versions_json", DEFAULT_CONFIG["versions_json"]))
        self.params_text.delete("1.0", END)
        self.params_text.insert(END, c.get("params_json", DEFAULT_CONFIG["params_json"]))
        self.positions_text.delete("1.0", END)
        self.positions_text.insert(END, c.get("positions_json", DEFAULT_CONFIG["positions_json"]))

        self._log("配置已加载")

    def _save_config(self):
        cfg = self._get_config_from_ui()
        save_config(cfg)
        self._log("✅ 配置已保存")
        messagebox.showinfo("成功", "配置已保存！")

    def _reset_form(self):
        c = DEFAULT_CONFIG
        self.server_ip_var.set(c["server_ip"])
        self.port_var.set(c["port"])
        self.context_path_var.set(c["context_path"])
        self.org_id_var.set(c["org_id"])
        self.dept_id_var.set("")
        self.device_type_var.set(c["device_type"])
        self.api_version_var.set(c["api_version"])
        self.device_count_var.set(str(c["device_count"]))
        self.start_device_num_var.set(c["start_device_num"])
        self.start_ip_var.set(c["start_ip"])
        self.device_model_var.set(c["device_model"])
        self.room_id_template_var.set("")
        self.bed_id_template_var.set("")
        self.mac_prefix_var.set(c["mac_prefix"])
        self.device_name_prefix_var.set(c["device_name_prefix"])

        self.versions_text.delete("1.0", END)
        self.versions_text.insert(END, c["versions_json"])
        self.params_text.delete("1.0", END)
        self.params_text.insert(END, c["params_json"])
        self.positions_text.delete("1.0", END)
        self.positions_text.insert(END, c["positions_json"])

        self._log("表单已重置为默认值")

    def _validate(self, cfg):
        if not cfg['server_ip']:
            return "请输入服务器IP地址"
        if not cfg['port']:
            return "请输入端口号"
        if not cfg['context_path']:
            return "请输入上下文路径"
        if not cfg['org_id']:
            return "请输入机构ID"
        if not cfg['device_type']:
            return "请选择设备类型"
        if not cfg['api_version']:
            return "请选择接口版本"
        try:
            count = int(cfg['device_count'])
            if count <= 0:
                return "设备数量必须大于0"
        except ValueError:
            return "设备数量格式错误"
        if not cfg['start_device_num']:
            return "请输入起始设备号"
        import re
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', cfg['start_ip']):
            return "起始IP地址格式不正确"
        if not cfg['device_model']:
            return "请选择或输入设备型号"
        return None

    def _preview_data(self):
        cfg = self._get_config_from_ui()
        err = self._validate(cfg)
        if err:
            messagebox.showwarning("提示", err)
            return

        count = min(3, cfg['device_count'])
        lines = [f"将创建 {cfg['device_count']} 个设备，以下是前 {count} 个的预览：\n"]
        for i in range(count):
            try:
                data, device_id = build_request_data(cfg, i)
                lines.append(f"--- 设备 {i+1} ---")
                lines.append(f"  DeviceID: {device_id}")
                lines.append(f"  设备号: {data['deviceNum']}")
                lines.append(f"  IP: {data['ip']}")
                lines.append(f"  MAC: {data['mac']}")
                lines.append(f"  名称: {data['deviceName']}")
                lines.append(f"  型号: {data['deviceModel']}")
                lines.append("")
            except Exception as e:
                lines.append(f"设备 {i+1}: 错误 - {e}\n")

        url = get_api_url(cfg)
        lines.append(f"请求地址: {url}")

        # 弹出预览窗口
        preview_win = Toplevel(self.root)
        preview_win.title("数据预览")
        preview_win.geometry("550x400")
        text = scrolledtext.ScrolledText(preview_win, font=("Consolas", 10), wrap=WORD)
        text.pack(fill=BOTH, expand=True, padx=10, pady=10)
        text.insert(END, '\n'.join(lines))
        text.config(state=DISABLED)

    def _start_create(self):
        if self.is_running:
            return

        cfg = self._get_config_from_ui()
        err = self._validate(cfg)
        if err:
            messagebox.showerror("错误", err)
            return

        # 保存配置
        save_config(cfg)

        self.is_running = True
        self.btn_start.config(state=DISABLED)
        self.progress['maximum'] = cfg['device_count']
        self.progress['value'] = 0
        self.progress_label.config(text="正在批量创建设备...")

        # 清空日志
        self.log_text.config(state=NORMAL)
        self.log_text.delete("1.0", END)
        self.log_text.config(state=DISABLED)

        url = get_api_url(cfg)
        self._log(f"开始创建设备: {cfg['device_count']} 个")
        self._log(f"请求地址: {url}")

        threading.Thread(
            target=self._do_batch_create,
            args=(cfg, url),
            daemon=True
        ).start()

    def _do_batch_create(self, cfg, url):
        success_count = 0
        fail_count = 0
        total = cfg['device_count']
        logged_first_request = False  # 只在第一次请求时打印完整详情

        try:
            for i in range(total):
                try:
                    data, device_id = build_request_data(cfg, i)
                except ValueError as e:
                    self._log(f"⚠️ 设备 {i+1}: {e}")
                    fail_count += 1
                    self.root.after(0, lambda v=i+1: self.progress.config(value=v))
                    continue

                # 第一次请求时打印完整的请求详情
                if not logged_first_request:
                    logged_first_request = True
                    self._log(f"{'='*50}")
                    self._log(f"📤 请求URL: {url}")
                    self._log(f"📤 请求方法: POST")
                    self._log(f"📤 Content-Type: application/json")
                    body_str = json.dumps(data, ensure_ascii=False, indent=2)
                    self._log(f"📤 请求体:\n{body_str}")
                    self._log(f"{'='*50}")

                try:
                    resp = requests.post(
                        url,
                        json=data,
                        headers={"Content-Type": "application/json"},
                        timeout=15
                    )

                    if resp.status_code == 200:
                        try:
                            res = resp.json() if resp.text else {}
                        except json.JSONDecodeError:
                            res = {}
                        code = res.get('code', None)
                        status = res.get('status', None)
                        desc = res.get('desc', res.get('message', ''))

                        # 成功判断：status==200 或 code==0 或 status=='success'
                        is_success = (
                            status == 200 or
                            code == 0 or
                            status == 'success' or
                            (isinstance(status, str) and status.lower() == 'success')
                        )

                        if is_success:
                            success_count += 1
                            # 尝试提取返回的deviceId
                            ret_device_id = ''
                            if isinstance(res.get('data'), dict):
                                ret_device_id = res['data'].get('deviceId', '')
                            extra = f" [deviceId={ret_device_id}]" if ret_device_id else ''
                            self._log(f"✅ 设备 {i+1}: {data['deviceNum']} ({data['ip']}) - {desc or '操作成功'}{extra}")
                        else:
                            fail_count += 1
                            self._log(f"❌ 设备 {i+1}: {data['deviceNum']} ({data['ip']}) - status={status}, code={code}, desc={desc}")
                            # 失败时打印完整响应
                            self._log(f"   📨 响应体: {resp.text[:500]}")
                            if i == 0:
                                self._log(f"   📨 响应头: {dict(resp.headers)}")
                    else:
                        fail_count += 1
                        self._log(f"❌ 设备 {i+1}: {data['deviceNum']} ({data['ip']}) - HTTP {resp.status_code}")
                        self._log(f"   📨 响应体: {resp.text[:500]}")
                        if i == 0:
                            self._log(f"   📨 响应头: {dict(resp.headers)}")

                except requests.exceptions.Timeout as e:
                    fail_count += 1
                    self._log(f"❌ 设备 {i+1}: 请求超时 (15s)")
                    self._log(f"   错误详情: {e}")
                except requests.exceptions.ConnectionError as e:
                    fail_count += 1
                    self._log(f"❌ 设备 {i+1}: 连接失败 - {url}")
                    self._log(f"   错误详情: {e}")
                    # 连接失败只打印第一个请求的详细错误
                    if i > 0:
                        self._log(f"   💡 后续连接失败不再打印详情")
                        # 后续连接失败不再逐个重试，快速失败
                        remaining = total - i - 1
                        if remaining > 0:
                            self._log(f"   ⚠️ 跳过剩余 {remaining} 个设备（服务器不可达）")
                            fail_count += remaining
                            break
                except Exception as e:
                    fail_count += 1
                    self._log(f"❌ 设备 {i+1}: 未知错误 - {type(e).__name__}: {e}")

                # 更新进度
                self.root.after(0, lambda v=i+1: self.progress.config(value=v))
                self.root.after(0, lambda v=i+1, t=total: self.progress_label.config(
                    text=f"正在处理: {v} / {t}"
                ))

                if i < total - 1:
                    time.sleep(0.3)

            # 完成
            self._log(f"{'='*50}")
            self._log(f"🎉 批量创建完成！成功: {success_count}, 失败: {fail_count}")

            self.root.after(0, lambda: self.progress_label.config(
                text=f"完成！成功: {success_count}, 失败: {fail_count}"
            ))
            self.root.after(0, lambda: messagebox.showinfo(
                "完成", f"批量创建设备完成！\n成功: {success_count}\n失败: {fail_count}"
            ))

        except Exception as e:
            self._log(f"❌ 批量创建异常: {type(e).__name__}: {e}")
            self.root.after(0, lambda: messagebox.showerror("错误", f"批量创建异常: {e}"))
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.btn_start.config(state=NORMAL))


# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    if not requests:
        root = Tk()
        root.withdraw()
        messagebox.showerror("依赖缺失", "缺少 requests 库，请运行：\n\npip install requests")
        root.destroy()
        exit(1)

    root = Tk()
    app = DeviceCreatorGUI(root)
    root.mainloop()
