import os
import re
import json
import time
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, scrolledtext
from datetime import datetime
import hashlib
from queue import Queue
import requests
import timeout_decorator


# 配置与常量
CONFIG_FILE = "./json/md_translator_config.json"
TRANSLATION_MARKER = "<!-- 中文对照已添加 -->"
DEFAULT_IGNORES = [".git", "node_modules", "venv", "__pycache__", ".translation_logs"]
SUPPORTED_API = ["baidu", "google"]
LOG_DIR = ".translation_logs"

# 确保配置目录存在
os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

# 全局变量（使用线程安全的队列传递状态更新）
task_queue = Queue()
pause_event = threading.Event()
stop_event = threading.Event()
progress_lock = threading.Lock()
# 用队列传递UI更新任务，避免跨线程直接操作GUI
ui_update_queue = Queue()

# 处理状态（通过锁保护）
processing_stats = {
    "total": 0,
    "completed": 0,
    "failed": 0,
    "current_file": ""
}
failed_files = []
config = {
    "api_provider": "baidu",
    "baidu_appid": "",
    "baidu_secret": "",
    "google_api_key": "",
    "timeout": 30,
    "rate_limit": 1,
    "ignore_patterns": DEFAULT_IGNORES.copy()
}


class TranslationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Markdown中英文对照翻译工具")
        self.root.geometry("900x700")
        self.root.resizable(True, True)

        # 加载配置
        self.load_config()

        # 创建UI
        self.create_widgets()

        # 初始化状态
        self.scanned_files = []
        self.processing_thread = None
        self.log_file = None

        # 启动UI更新循环（每100ms检查一次更新队列）
        self.root.after(100, self.process_ui_updates)

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 文件夹选择区域
        folder_frame = ttk.LabelFrame(main_frame, text="代码库选择", padding="10")
        folder_frame.pack(fill=tk.X, pady=5)

        self.folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self.folder_var, width=70).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(folder_frame, text="浏览...", command=self.select_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(folder_frame, text="扫描文件", command=self.scan_files).pack(side=tk.LEFT, padx=5)

        # 2. 配置区域
        config_frame = ttk.LabelFrame(main_frame, text="翻译配置", padding="10")
        config_frame.pack(fill=tk.X, pady=5)

        # API选择
        ttk.Label(config_frame, text="翻译服务:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.api_var = tk.StringVar(value=config["api_provider"])
        api_combo = ttk.Combobox(config_frame, textvariable=self.api_var, values=SUPPORTED_API, state="readonly", width=10)
        api_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        api_combo.bind("<<ComboboxSelected>>", self.update_api_fields)

        # 百度API配置
        ttk.Label(config_frame, text="百度APP ID:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.baidu_appid = tk.StringVar(value=config["baidu_appid"])
        ttk.Entry(config_frame, textvariable=self.baidu_appid, width=30).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(config_frame, text="百度密钥:").grid(row=1, column=2, sticky=tk.W, padx=5, pady=5)
        self.baidu_secret = tk.StringVar(value=config["baidu_secret"])
        ttk.Entry(config_frame, textvariable=self.baidu_secret, width=30).grid(row=1, column=3, sticky=tk.W, padx=5, pady=5)

        # 谷歌API配置
        ttk.Label(config_frame, text="谷歌API密钥:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.google_api_key = tk.StringVar(value=config["google_api_key"])
        ttk.Entry(config_frame, textvariable=self.google_api_key, width=30).grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)

        # 其他配置
        ttk.Label(config_frame, text="超时时间(秒):").grid(row=2, column=2, sticky=tk.W, padx=5, pady=5)
        self.timeout_var = tk.StringVar(value=str(config["timeout"]))
        ttk.Entry(config_frame, textvariable=self.timeout_var, width=10).grid(row=2, column=3, sticky=tk.W, padx=5, pady=5)

        ttk.Label(config_frame, text="请求间隔(秒):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.rate_limit_var = tk.StringVar(value=str(config["rate_limit"]))
        ttk.Entry(config_frame, textvariable=self.rate_limit_var, width=10).grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Button(config_frame, text="保存配置", command=self.save_config).grid(row=3, column=3, sticky=tk.E, padx=5, pady=5)

        # 3. 忽略设置
        ignore_frame = ttk.LabelFrame(main_frame, text="忽略设置", padding="10")
        ignore_frame.pack(fill=tk.X, pady=5)

        ttk.Label(ignore_frame, text="忽略文件/文件夹(每行一个):").pack(anchor=tk.W, padx=5, pady=5)
        self.ignore_text = scrolledtext.ScrolledText(ignore_frame, height=3, width=80)
        self.ignore_text.pack(fill=tk.X, padx=5, pady=5)
        self.ignore_text.insert(tk.END, "\n".join(config["ignore_patterns"]))

        # 4. 状态与进度
        status_frame = ttk.LabelFrame(main_frame, text="处理状态", padding="10")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 进度条
        self.progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, maximum=100)
        progress_bar.pack(fill=tk.X, padx=5, pady=5)

        # 状态标签
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor=tk.W, padx=5)

        self.stats_var = tk.StringVar(value="总文件: 0 | 已完成: 0 | 失败: 0")
        ttk.Label(status_frame, textvariable=self.stats_var).pack(anchor=tk.W, padx=5)

        self.current_file_var = tk.StringVar(value="当前文件: 无")
        ttk.Label(status_frame, textvariable=self.current_file_var).pack(anchor=tk.W, padx=5)

        # 日志区域
        ttk.Label(status_frame, text="处理日志:").pack(anchor=tk.W, padx=5, pady=5)
        self.log_text = scrolledtext.ScrolledText(status_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state="disabled")

        # 5. 控制按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.start_btn = ttk.Button(btn_frame, text="开始处理", command=self.start_processing)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = ttk.Button(btn_frame, text="暂停", command=self.pause_processing, state="disabled")
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_processing, state="disabled")
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.retry_btn = ttk.Button(btn_frame, text="重试失败文件", command=self.retry_failed, state="disabled")
        self.retry_btn.pack(side=tk.LEFT, padx=5)

        self.preview_btn = ttk.Button(btn_frame, text="预览翻译", command=self.preview_translation, state="disabled")
        self.preview_btn.pack(side=tk.RIGHT, padx=5)

        # 初始隐藏不相关的API配置
        self.update_api_fields()

    def select_folder(self):
        folder = filedialog.askdirectory(title="选择代码库根目录")
        if folder:
            self.folder_var.set(folder)

    def scan_files(self):
        root_folder = self.folder_var.get()
        if not root_folder or not os.path.exists(root_folder):
            messagebox.showerror("错误", "请选择有效的文件夹")
            return

        # 保存当前忽略设置
        self.save_ignore_settings()

        # 扫描所有MD文件
        self.add_ui_update(("log", "开始扫描MD文件..."))
        self.scanned_files = []

        ignore_patterns = config["ignore_patterns"]

        for root, dirs, files in os.walk(root_folder):
            # 过滤忽略的目录
            dirs[:] = [d for d in dirs if d not in ignore_patterns]

            for file in files:
                if file.lower().endswith(".md"):
                    file_path = os.path.join(root, file)
                    # 检查是否已翻译
                    if not self.is_translated(file_path):
                        self.scanned_files.append(file_path)

        count = len(self.scanned_files)
        self.add_ui_update(("log", f"扫描完成，发现 {count} 个未翻译的MD文件"))
        messagebox.showinfo("扫描完成", f"共发现 {count} 个未翻译的MD文件")

        # 更新按钮状态
        self.add_ui_update(("btn_state", "start", "normal"))
        self.add_ui_update(("btn_state", "preview", "normal" if count > 0 else "disabled"))

    def is_translated(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                return TRANSLATION_MARKER in content
        except Exception:
            return False

    def update_api_fields(self, event=None):
        api = self.api_var.get()

        # 显示当前API对应的配置项，隐藏其他
        if api == "baidu":
            # 显示百度配置，隐藏谷歌配置
            for child in self.root.winfo_children():
                for sub_child in child.winfo_children():
                    if hasattr(sub_child, "grid_info"):
                        info = sub_child.grid_info()
                        if info.get("row") == 1:  # 百度配置行
                            sub_child.grid()
                        elif info.get("row") == 2 and info.get("column") in [0, 1]:  # 谷歌配置行
                            sub_child.grid_remove()
        elif api == "google":
            # 显示谷歌配置，隐藏百度配置
            for child in self.root.winfo_children():
                for sub_child in child.winfo_children():
                    if hasattr(sub_child, "grid_info"):
                        info = sub_child.grid_info()
                        if info.get("row") == 1:  # 百度配置行
                            sub_child.grid_remove()
                        elif info.get("row") == 2 and info.get("column") in [0, 1]:  # 谷歌配置行
                            sub_child.grid()

    def save_config(self):
        try:
            config["api_provider"] = self.api_var.get()
            config["baidu_appid"] = self.baidu_appid.get()
            config["baidu_secret"] = self.baidu_secret.get()
            config["google_api_key"] = self.google_api_key.get()
            config["timeout"] = int(self.timeout_var.get())
            config["rate_limit"] = float(self.rate_limit_var.get())

            # 保存忽略设置
            self.save_ignore_settings()

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            self.add_ui_update(("log", "配置已保存"))
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            self.add_ui_update(("log", f"保存配置失败: {str(e)}"))
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def save_ignore_settings(self):
        ignores = self.ignore_text.get("1.0", tk.END).strip().split("\n")
        config["ignore_patterns"] = [i.strip() for i in ignores if i.strip()]

    def load_config(self):
        global config
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    config.update(loaded)
            except Exception as e:
                self.add_ui_update(("log", f"加载配置失败: {e}"))

    def start_processing(self):
        if not self.scanned_files:
            self.scan_files()
            if not self.scanned_files:
                return

        # 保存配置
        self.save_config()

        # 验证API配置
        if not self.validate_api_config():
            return

        # 初始化任务队列
        for file_path in self.scanned_files:
            task_queue.put(file_path)

        # 初始化统计
        with progress_lock:
            processing_stats["total"] = len(self.scanned_files)
            processing_stats["completed"] = 0
            processing_stats["failed"] = 0
            processing_stats["current_file"] = ""
            failed_files.clear()

        # 更新UI
        self.add_ui_update(("progress",))
        self.add_ui_update(("status", "处理中"))
        self.add_ui_update(("btn_state", "start", "disabled"))
        self.add_ui_update(("btn_state", "pause", "normal"))
        self.add_ui_update(("btn_state", "stop", "normal"))

        # 启动处理线程
        self.processing_thread = threading.Thread(target=self.process_queue)
        self.processing_thread.daemon = True
        self.processing_thread.start()

        # 启动日志记录
        self.init_log()

    def validate_api_config(self):
        api = config["api_provider"]
        if api == "baidu" and (not config["baidu_appid"] or not config["baidu_secret"]):
            messagebox.showerror("配置错误", "请填写百度翻译API的APP ID和密钥")
            return False
        if api == "google" and not config["google_api_key"]:
            messagebox.showerror("配置错误", "请填写谷歌翻译API的密钥")
            return False
        return True

    def process_queue(self):
        while not stop_event.is_set() and not task_queue.empty():
            if pause_event.is_set():
                time.sleep(0.5)
                continue

            file_path = task_queue.get()
            with progress_lock:
                processing_stats["current_file"] = file_path

            self.add_ui_update(("progress",))
            self.add_ui_update(("log", f"开始处理: {os.path.basename(file_path)}"))

            try:
                # 使用当前配置的超时时间（避免全局变量问题）
                timeout = config["timeout"]
                # 动态设置超时装饰器
                @timeout_decorator.timeout(timeout, use_signals=False)
                def process_with_timeout():
                    return self.process_file(file_path)

                success = process_with_timeout()
                with progress_lock:
                    if success:
                        processing_stats["completed"] += 1
                    else:
                        processing_stats["failed"] += 1
                        failed_files.append(file_path)
            except timeout_decorator.TimeoutError:
                self.add_ui_update(("log", f"处理 {os.path.basename(file_path)} 超时"))
                with progress_lock:
                    processing_stats["failed"] += 1
                    failed_files.append(file_path)
            except Exception as e:
                self.add_ui_update(("log", f"处理 {os.path.basename(file_path)} 出错: {str(e)}"))
                with progress_lock:
                    processing_stats["failed"] += 1
                    failed_files.append(file_path)

            self.add_ui_update(("progress",))
            task_queue.task_done()
            time.sleep(config["rate_limit"])  # 频率限制

        # 处理完成
        if not stop_event.is_set():
            self.add_ui_update(("status", "处理完成"))
            with progress_lock:
                completed = processing_stats["completed"]
                failed = processing_stats["failed"]
            self.add_ui_update(("log", f"全部处理完成 - 成功: {completed}, 失败: {failed}"))
            self.save_log()

        # 重置按钮状态
        self.add_ui_update(("reset_buttons",))

    def process_file(self, file_path):
        try:
            # 读取文件内容
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # 处理内容
            in_code_block = False
            new_lines = []

            for line in lines:
                # 检查代码块标记
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
                    new_lines.append(line)
                    continue

                # 跳过代码块和已翻译内容
                if in_code_block or TRANSLATION_MARKER in line:
                    new_lines.append(line)
                    continue

                # 检查是否需要翻译的行
                stripped_line = line.strip()
                if self.needs_translation(stripped_line):
                    new_lines.append(line)
                    # 翻译并添加到下一行
                    translation = self.translate_text(stripped_line)
                    new_lines.append(f"{translation}\n")
                else:
                    new_lines.append(line)

            # 添加翻译完成标记
            if TRANSLATION_MARKER not in "".join(new_lines):
                new_lines.append(f"\n{TRANSLATION_MARKER}\n")

            # 写回文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            return True
        except Exception as e:
            self.add_ui_update(("log", f"处理文件错误: {str(e)}"))
            return False

    def needs_translation(self, text):
        # 判断是否需要翻译（简单规则）
        if not text:
            return False

        # 检查是否是链接
        if re.match(r"^\[.+\]\(.+\)$", text):
            return False

        # 检查是否是图片
        if re.match(r"^!\[.+\]\(.+\)$", text):
            return False

        # 检查是否主要是英文
        return bool(re.search(r"[a-zA-Z]", text))

    def translate_text(self, text):
        api = config["api_provider"]

        try:
            if api == "baidu":
                return self.baidu_translate(text)
            elif api == "google":
                return self.google_translate(text)
            else:
                return f"[未支持的翻译服务: {api}]"
        except Exception as e:
            self.add_ui_update(("log", f"翻译失败: {str(e)}"))
            return f"[翻译失败: {str(e)}]"

    def baidu_translate(self, text):
        url = "http://api.fanyi.baidu.com/api/trans/vip/translate"
        salt = str(int(time.time() * 1000))
        sign = hashlib.md5(f"{config['baidu_appid']}{text}{salt}{config['baidu_secret']}".encode()).hexdigest()

        params = {
            "q": text,
            "from": "en",
            "to": "zh",
            "appid": config["baidu_appid"],
            "salt": salt,
            "sign": sign
        }

        response = requests.get(url, params=params, timeout=config["timeout"])
        result = response.json()

        if "trans_result" in result:
            return result["trans_result"][0]["dst"]
        else:
            raise Exception(f"百度翻译错误: {result.get('error_msg', '未知错误')}")

    def google_translate(self, text):
        url = f"https://translation.googleapis.com/language/translate/v2?key={config['google_api_key']}"

        data = {
            "q": text,
            "source": "en",
            "target": "zh-CN",
            "format": "text"
        }

        response = requests.post(url, json=data, timeout=config["timeout"])
        result = response.json()

        if "data" in result and "translations" in result["data"]:
            return result["data"]["translations"][0]["translatedText"]
        else:
            raise Exception(f"谷歌翻译错误: {result.get('error', {}).get('message', '未知错误')}")

    def add_ui_update(self, update_task):
        """添加UI更新任务到队列（线程安全）"""
        ui_update_queue.put(update_task)

    def process_ui_updates(self):
        """处理UI更新队列（在主线程执行）"""
        while not ui_update_queue.empty():
            task = ui_update_queue.get()
            try:
                if task[0] == "log":
                    # 日志更新
                    message = task[1]
                    self.log_text.config(state="normal")
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
                    self.log_text.see(tk.END)
                    self.log_text.config(state="disabled")
                elif task[0] == "progress":
                    # 进度更新
                    with progress_lock:
                        total = processing_stats["total"]
                        completed = processing_stats["completed"]
                        failed = processing_stats["failed"]
                        current_file = processing_stats["current_file"]

                    if total > 0:
                        percent = (completed + failed) / total * 100
                        self.progress_var.set(percent)

                    self.stats_var.set(f"总文件: {total} | 已完成: {completed} | 失败: {failed}")
                    self.current_file_var.set(f"当前文件: {os.path.basename(current_file) if current_file else '无'}")
                elif task[0] == "status":
                    # 状态更新
                    self.status_var.set(task[1])
                elif task[0] == "btn_state":
                    # 按钮状态更新
                    btn_name, state = task[1], task[2]
                    if btn_name == "start":
                        self.start_btn.config(state=state)
                    elif btn_name == "pause":
                        self.pause_btn.config(state=state)
                    elif btn_name == "stop":
                        self.stop_btn.config(state=state)
                    elif btn_name == "preview":
                        self.preview_btn.config(state=state)
                    elif btn_name == "retry":
                        self.retry_btn.config(state=state)
                elif task[0] == "reset_buttons":
                    # 重置按钮状态
                    with progress_lock:
                        has_failed = len(failed_files) > 0
                    self.start_btn.config(state="normal")
                    self.pause_btn.config(state="disabled", text="暂停")
                    self.stop_btn.config(state="disabled")
                    self.retry_btn.config(state="normal" if has_failed else "disabled")
            except Exception as e:
                print(f"处理UI更新失败: {e}")

        # 继续循环
        self.root.after(100, self.process_ui_updates)

    def init_log(self):
        # 确保日志目录存在
        root_folder = self.folder_var.get()
        if root_folder:
            log_dir = os.path.join(root_folder, LOG_DIR)
            os.makedirs(log_dir, exist_ok=True)

            # 创建新日志文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_file = os.path.join(log_dir, f"translation_{timestamp}.log")

            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write(f"翻译日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"代码库目录: {root_folder}\n")
                with progress_lock:
                    total = processing_stats["total"]
                f.write(f"总文件数: {total}\n\n")

    def save_log(self):
        if self.log_file and os.path.exists(self.log_file):
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"\n处理完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                with progress_lock:
                    completed = processing_stats["completed"]
                    failed = processing_stats["failed"]
                f.write(f"成功: {completed}\n")
                f.write(f"失败: {failed}\n")

                with progress_lock:
                    failed_list = failed_files.copy()
                if failed_list:
                    f.write("\n失败文件列表:\n")
                    for file in failed_list:
                        f.write(f"- {file}\n")

    def pause_processing(self):
        if pause_event.is_set():
            pause_event.clear()
            self.add_ui_update(("status", "处理中"))
            self.pause_btn.config(text="暂停")
            self.add_ui_update(("log", "继续处理"))
        else:
            pause_event.set()
            self.add_ui_update(("status", "已暂停"))
            self.pause_btn.config(text="继续")
            self.add_ui_update(("log", "已暂停处理"))

    def stop_processing(self):
        stop_event.set()
        self.add_ui_update(("status", "正在停止..."))
        self.add_ui_update(("log", "正在停止处理..."))

    def retry_failed(self):
        with progress_lock:
            failed_list = failed_files.copy()
        if not failed_list:
            messagebox.showinfo("提示", "没有失败的文件")
            return

        # 将失败文件加入队列
        for file_path in failed_list:
            task_queue.put(file_path)

        # 重置状态
        stop_event.clear()
        pause_event.clear()
        with progress_lock:
            processing_stats["failed"] = 0
            failed_files.clear()

        # 更新UI
        self.add_ui_update(("progress",))
        self.add_ui_update(("status", "处理中"))
        self.add_ui_update(("btn_state", "start", "disabled"))
        self.add_ui_update(("btn_state", "pause", "normal"))
        self.add_ui_update(("btn_state", "stop", "normal"))
        self.add_ui_update(("btn_state", "retry", "disabled"))

        # 启动处理线程
        self.processing_thread = threading.Thread(target=self.process_queue)
        self.processing_thread.daemon = True
        self.processing_thread.start()

    def preview_translation(self):
        if not self.scanned_files:
            messagebox.showinfo("提示", "没有可预览的文件")
            return

        # 创建预览窗口
        preview_window = tk.Toplevel(self.root)
        preview_window.title("翻译预览")
        preview_window.geometry("800x600")

        # 文件选择
        ttk.Label(preview_window, text="选择文件:").pack(anchor=tk.W, padx=10, pady=5)
        file_var = tk.StringVar(value=self.scanned_files[0])
        file_combo = ttk.Combobox(preview_window, textvariable=file_var, values=self.scanned_files, width=80)
        file_combo.pack(fill=tk.X, padx=10, pady=5)

        # 预览区域
        frame = ttk.Frame(preview_window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        ttk.Label(frame, text="原文:").pack(anchor=tk.W)
        original_text = scrolledtext.ScrolledText(frame, height=10)
        original_text.pack(fill=tk.BOTH, expand=True, pady=5)

        ttk.Label(frame, text="翻译后:").pack(anchor=tk.W)
        translated_text = scrolledtext.ScrolledText(frame, height=10)
        translated_text.pack(fill=tk.BOTH, expand=True, pady=5)

        # 加载按钮
        def load_preview():
            file_path = file_var.get()
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                original_text.delete("1.0", tk.END)
                original_text.insert(tk.END, content)

                # 生成预览翻译
                lines = content.split("\n")
                new_lines = []
                in_code_block = False

                for line in lines:
                    if line.strip().startswith("```"):
                        in_code_block = not in_code_block
                        new_lines.append(line)
                        continue

                    if in_code_block:
                        new_lines.append(line)
                        continue

                    stripped_line = line.strip()
                    if self.needs_translation(stripped_line):
                        new_lines.append(line)
                        try:
                            translation = self.translate_text(stripped_line)
                            new_lines.append(f"{translation}")
                        except:
                            new_lines.append("[翻译失败]")
                    else:
                        new_lines.append(line)

                translated_text.delete("1.0", tk.END)
                translated_text.insert(tk.END, "\n".join(new_lines))

            except Exception as e:
                messagebox.showerror("错误", f"加载文件失败: {str(e)}")

        ttk.Button(preview_window, text="加载预览", command=load_preview).pack(pady=10)
        load_preview()  # 加载第一个文件


if __name__ == "__main__":
    # 修复Windows多线程问题
    if os.name == "nt":
        import multiprocessing
        multiprocessing.freeze_support()

    root = tk.Tk()
    app = TranslationApp(root)

    # 处理窗口关闭
    def on_closing():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
