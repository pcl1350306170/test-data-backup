# api_batch_tester.pyw

import os
import json
import logging
import threading
import time
import random
import string
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk, scrolledtext
from datetime import datetime

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "api_batch_tester"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 姓名库路径
LAST_NAME_PATH = (SCRIPT_DIR.parent) / "json" / "LastName.json"
FIRST_NAME_PATH = (SCRIPT_DIR.parent) / "json" / "FirstName.json"

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
# 默认配置
DEFAULT_CONFIG = {
    "api_url": "http://192.168.18.228:7000/clinic/api/qcss/register/made",
    "method": "POST",
    "request_body": json.dumps({
        "hasBook": 1,
        "registerTime": "2025-12-16 09:01:36",
        "signTime": "2025-12-16 09:01:36",
        "patientName": "张三",
        "patientIdNo": "zs1",
        "sex": "1",
        "age": 0,
        "ageType": "2",
        "hasPay": 0,
        "registerObjId": 1,
        "orderTags": ""
    }, ensure_ascii=False, indent=2),
    "dynamic_fields": "patientName,patientIdNo",
    "start_id": 1,  # ✅ 新增：起始ID
    "raw_headers": """POST /clinic/api/qcss/register/made HTTP/1.1
Accept: application/json, text/plain, */*
Accept-Encoding: gzip, deflate
Accept-Language: zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJsb2dpblR5cGUiOiJsb2dpbiIsImxvZ2luSWQiOiJzeXNfdXNlcjoxOm51bGwiLCJyblN0ciI6InphZDEzazdJRW5KR01WTFdiYmJyZzcxM0pTWkMwZXBQIiwiY2xpZW50aWQiOiJlNWNkN2U0ODkxYmY5NWQxZDE5MjA2Y2UyNGE3YjMyZSIsInRlbmFudElkIjoiMDAwMDAwIiwidXNlcklkIjoxfQ.PMe6oxjx7s7EDDcewV6g5Y4CBtiohmYsdP7UG1GKGuU
Connection: keep-alive
Content-Language: zh_CN
Content-Type: application/json;charset=UTF-8
Cookie: tenantId=000000; username=yarward; password=Yahua3585668; rememberMe=true; perf_dv6Tr4n=1
Host: 192.168.18.228:7000
Referer: http://192.168.18.228:7000/
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36
clientid: e5cd7e4891bf95d1d19206ce24a7b32e""",
    "call_times": 10
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

def load_name_library():
    """从 json 目录加载姓和名"""
    last_names = []
    first_names = []

    if LAST_NAME_PATH.exists():
        try:
            with open(LAST_NAME_PATH, 'r', encoding='utf-8') as f:
                last_names = json.load(f)
        except Exception as e:
            logger.error(f"加载 LastName.json 失败: {e}")

    if FIRST_NAME_PATH.exists():
        try:
            with open(FIRST_NAME_PATH, 'r', encoding='utf-8') as f:
                first_names = json.load(f)
        except Exception as e:
            logger.error(f"加载 FirstName.json 失败: {e}")

    return last_names, first_names

def generate_random_name():
    """随机组合姓和名生成真实姓名"""
    last_names, first_names = load_name_library()
    if not last_names or not first_names:
        # 兜底：使用默认库
        last_names = ["张", "李", "王", "赵", "钱", "孙", "周", "吴", "郑", "王", "冯", "陈"]
        first_names = ["三", "四", "五", "六", "七", "八", "九", "十", "一", "二", "三", "四"]

    last = random.choice(last_names)
    first = random.choice(first_names)
    return first + last  # ✅ 修复：改为 姓+名 的顺序

def generate_sequential_id(start_id, index):
    """生成递增的ID，格式为3位数字（如 001, 002, ...）"""
    current_id = start_id + index
    return f"{current_id:03d}"  # 格式化为3位数字，不足补0

def replace_dynamic_fields(request_body_str, dynamic_fields_str, start_id, index):
    """替换请求体中的动态字段
    
    Args:
        request_body_str: 原始请求体JSON字符串
        dynamic_fields_str: 需要替换的字段列表（逗号分隔）
        start_id: 起始ID
        index: 当前是第几次调用（从0开始）
    
    Returns:
        tuple: (替换后的JSON字符串, 本次使用的patientIdNo值)
    """
    data = json.loads(request_body_str)
    fields = [f.strip() for f in dynamic_fields_str.split(',')]
    
    current_patient_id = None  # 记录本次使用的patientIdNo
    
    # ✅ 新增：自动替换时间为当前时间
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "registerTime" in data:
        data["registerTime"] = current_time
    if "signTime" in data:
        data["signTime"] = current_time

    for field in fields:
        if field == "patientName":
            data[field] = generate_random_name()
        elif field == "patientIdNo":
            patient_id = generate_sequential_id(start_id, index)
            data[field] = patient_id
            current_patient_id = patient_id  # 记录当前ID
            # ✅ 如果存在 orderNo 字段，也设置为相同的值
            if "orderNo" in data:
                data["orderNo"] = patient_id
        # 可扩展其他字段

    return json.dumps(data, ensure_ascii=False), current_patient_id

def parse_raw_headers(raw_headers_str):
    """解析 Raw Headers 字符串为字典"""
    headers = {}
    lines = raw_headers_str.strip().split('\n')
    for line in lines:
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip()] = value.strip()
    return headers

# ==============================
# GUI 主类
# ==============================
class APITesterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🌐 接口批量测试数据生成器")
        self.root.geometry("800x800")
        self.root.resizable(True, True)

        self.config = load_config()
        self.setup_ui()

    def setup_ui(self):
        # API 地址
        frame_url = LabelFrame(self.root, text="🔗 接口地址", padx=10, pady=5)
        frame_url.pack(fill=X, padx=10, pady=5)
        self.url_var = StringVar(value=self.config.get("api_url", DEFAULT_CONFIG["api_url"]))
        Entry(frame_url, textvariable=self.url_var, width=80, font=("Consolas", 10)).pack(pady=3)

        # 请求方式
        frame_method = LabelFrame(self.root, text="🔄 请求方式", padx=10, pady=5)
        frame_method.pack(fill=X, padx=10, pady=5)
        self.method_var = StringVar(value=self.config.get("method", DEFAULT_CONFIG["method"]))
        Entry(frame_method, textvariable=self.method_var, width=20, font=("Consolas", 10)).pack(side=LEFT, padx=5)

        # 调用次数
        frame_times = LabelFrame(self.root, text="🔢 调用次数", padx=10, pady=5)
        frame_times.pack(fill=X, padx=10, pady=5)
        self.times_var = StringVar(value=str(self.config.get("call_times", DEFAULT_CONFIG["call_times"])))
        Entry(frame_times, textvariable=self.times_var, width=20, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        
        # ✅ 新增：起始ID
        Label(frame_times, text="起始ID:").pack(side=LEFT, padx=(10, 5))
        self.start_id_var = StringVar(value=str(self.config.get("start_id", DEFAULT_CONFIG["start_id"])))
        Entry(frame_times, textvariable=self.start_id_var, width=10, font=("Consolas", 10)).pack(side=LEFT, padx=5)

        # 动态字段
        frame_dynamic = LabelFrame(self.root, text="🔄 需要替换的字段（用逗号分隔）", padx=10, pady=5)
        frame_dynamic.pack(fill=X, padx=10, pady=5)
        self.dynamic_var = StringVar(value=self.config.get("dynamic_fields", DEFAULT_CONFIG["dynamic_fields"]))
        Entry(frame_dynamic, textvariable=self.dynamic_var, width=80, font=("Consolas", 10)).pack(pady=3)

        # Raw Headers
        frame_headers = LabelFrame(self.root, text="📤 请求头 (Raw 格式，粘贴完整 Headers)", padx=10, pady=5)
        frame_headers.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.headers_text = scrolledtext.ScrolledText(frame_headers, height=8, font=("Consolas", 9))
        self.headers_text.pack(fill=BOTH, expand=True)
        self.headers_text.insert(END, self.config.get("raw_headers", DEFAULT_CONFIG["raw_headers"]))

        # 请求体
        frame_body = LabelFrame(self.root, text="📥 请求体 (JSON)", padx=10, pady=5)
        frame_body.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.body_text = scrolledtext.ScrolledText(frame_body, height=6, font=("Consolas", 9))
        self.body_text.pack(fill=BOTH, expand=True)
        self.body_text.insert(END, self.config.get("request_body", DEFAULT_CONFIG["request_body"]))

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="💾 保存配置", command=self.save_config_action, bg="#2196F3", fg="white", width=12).pack(side=LEFT, padx=5)
        Button(btn_frame, text="🚀 开始批量调用", command=self.start_batch_call, bg="#4CAF50", fg="white", width=15, height=2).pack(side=LEFT, padx=5)

        # 进度条
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(padx=20, fill=X, pady=5)

        # 状态标签
        self.status_label = Label(self.root, text="就绪", fg="green", font=("Arial", 10))
        self.status_label.pack(pady=5)

        # 日志输出
        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=(0,10))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=6, state=DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

    def log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def set_status(self, msg, color="black"):
        self.status_label.config(text=msg, fg=color)
        self.root.update_idletasks()

    def save_config_action(self):
        config = {
            "api_url": self.url_var.get().strip(),
            "method": self.method_var.get().strip().upper(),
            "call_times": int(self.times_var.get().strip()),
            "start_id": int(self.start_id_var.get().strip()),  # ✅ 新增：保存起始ID
            "dynamic_fields": self.dynamic_var.get().strip(),
            "raw_headers": self.headers_text.get("1.0", END).strip(),
            "request_body": self.body_text.get("1.0", END).strip()
        }
        save_config(config)
        self.config = config
        self.log("✅ 配置已保存")

    def start_batch_call(self):
        # 保存当前配置
        self.save_config_action()

        # 验证输入
        try:
            url = self.url_var.get().strip()
            method = self.method_var.get().strip().upper()
            times = int(self.times_var.get().strip())
            start_id = int(self.start_id_var.get().strip())  # ✅ 新增：获取起始ID
            dynamic_fields = self.dynamic_var.get().strip()
            raw_headers_str = self.headers_text.get("1.0", END).strip()
            body_str = self.body_text.get("1.0", END).strip()

            if not url or not method or times <= 0 or not raw_headers_str:
                raise ValueError("请填写完整信息")
            if start_id < 0:
                raise ValueError("起始ID不能为负数")

            # 解析 Raw Headers
            headers = parse_raw_headers(raw_headers_str)

            # 解析 JSON
            json.loads(body_str)  # 验证 body

        except ValueError as e:
            messagebox.showerror("输入错误", f"输入格式错误：{e}")
            return
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 错误", f"JSON 格式错误：{e}")
            return

        # 启动后台线程
        self.progress['maximum'] = times
        self.progress['value'] = 0
        self.set_status("正在批量调用接口...", "blue")

        thread = threading.Thread(
            target=self.do_batch_call,
            args=(url, method, times, start_id, dynamic_fields, body_str, headers),  # ✅ 新增：传递start_id
            daemon=True
        )
        thread.start()

    def do_batch_call(self, url, method, times, start_id, dynamic_fields, body_str, headers):
        try:
            import requests  # 延迟导入

            success_count = 0
            for i in range(times):
                # 替换动态字段（传入起始ID和当前索引）
                current_body, current_patient_id = replace_dynamic_fields(body_str, dynamic_fields, start_id, i)
                
                # ✅ 在控制台打印当前使用的patientIdNo
                if current_patient_id:
                    print(f"[第{i+1}次] patientIdNo = {current_patient_id}")
                    self.log(f"📋 第 {i+1} 次 - patientIdNo: {current_patient_id}")

                # 发送请求
                try:
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=headers,
                        data=current_body.encode('utf-8'),
                        timeout=10
                    )
                    if response.status_code == 200:
                        success_count += 1
                        self.log(f"✅ 第 {i+1} 次调用成功: {response.status_code}")
                    else:
                        self.log(f"⚠️ 第 {i+1} 次调用返回: {response.status_code}, {response.text[:100]}...")
                except Exception as e:
                    self.log(f"❌ 第 {i+1} 次调用失败: {e}")

                # 更新进度
                self.progress['value'] = i + 1
                self.root.update_idletasks()
                time.sleep(0.1)  # 避免请求过快

            self.set_status(f"✅ 批量调用完成！成功 {success_count}/{times} 次", "green")
            self.log(f"🎉 总计成功 {success_count} / {times} 次")
            self.log(f"📊 ID范围: {generate_sequential_id(start_id, 0)} ~ {generate_sequential_id(start_id, times-1)}")

        except Exception as e:
            self.set_status(f"❌ 批量调用失败: {e}", "red")
            self.log(f"❌ 批量调用失败: {e}")
            messagebox.showerror("错误", f"批量调用失败：{e}")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 可选：检查 DB_CONFIG.json（虽不用，但按要求引入）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_config = json.load(f)
        except Exception as e:
            logger.warning(f"DB_CONFIG 加载失败（非必需）: {e}")

    root = Tk()
    app = APITesterGUI(root)
    root.mainloop()
