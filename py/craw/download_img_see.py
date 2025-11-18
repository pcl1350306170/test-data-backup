import os
import re
import json
import pymysql
import requests
import threading
import logging
from logging.handlers import RotatingFileHandler  # 新增导入
from queue import Queue
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PIL import Image
from io import BytesIO
import time
import signal
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path
import sys

# -------------------
# 配置与常量
# -------------------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "download_img_see"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# 数据库配置路径
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 日志配置
LOG_DIR = SCRIPT_DIR / "json" / "logs"
LOG_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOG_DIR / f"logs_{SCRIPT_NAME}.log"

# 小图映射JSON路径
SMALL_IMG_JSON = CONFIG_DIR / "imgSmallMapping.json"

# 安全停止标志
STOP_FLAG = False
STOP_LOCK = threading.Lock()

# 新增：日志文件大小限制(1MB)
MAX_LOG_SIZE = 1 * 1024 * 1024  # 1MB

# 配置默认值 - 新增"保存日志文件"配置
DEFAULT_CONFIG = {
    "SAVE_DIR": str(SCRIPT_DIR / "IMAGE" / "V33" / "已处理"),
    "THREAD_COUNT": 5,
    "RETRY_COUNT": 3,
    "SAVE_LOG_FILE": True  # 新增：是否保存日志文件
}

# -------------------
# 配置文件操作
# -------------------
def load_config():
    """加载配置文件"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置（确保所有配置项都存在）
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
        else:
            save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"配置已保存到 {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")


# -------------------
# 日志配置
# -------------------
def setup_logger():
    """配置日志系统 - 增加文件大小限制和开关控制"""
    logger = logging.getLogger(SCRIPT_NAME)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # 清除已存在的处理器，避免重复输出

    # 格式器
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # 新增：根据配置决定是否添加文件处理器
    config = load_config()
    if config["SAVE_LOG_FILE"]:
        # 使用RotatingFileHandler实现日志文件大小限制
        file_handler = RotatingFileHandler(
            PROCESS_LOG_FILE,
            mode='a',
            maxBytes=MAX_LOG_SIZE,
            backupCount=3,  # 最多保留3个备份日志
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 控制台处理器始终保留
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger()

# 加载配置
config = load_config()
SAVE_DIR = config["SAVE_DIR"]
THREAD_COUNT = config["THREAD_COUNT"]
RETRY_COUNT = config["RETRY_COUNT"]
SAVE_LOG_FILE = config["SAVE_LOG_FILE"]  # 新增：日志保存开关

# -------------------
# 初始化
# -------------------
os.makedirs(SAVE_DIR, exist_ok=True)

# 初始化小图JSON文件
if not os.path.exists(SMALL_IMG_JSON):
    with open(SMALL_IMG_JSON, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False)

# -------------------
# 数据库连接
# -------------------
def get_db_config():
    """获取数据库配置"""
    try:
        if os.path.exists(DB_CONFIG_PATH):
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.error(f"数据库配置文件不存在: {DB_CONFIG_PATH}")
            messagebox.showerror("错误", f"数据库配置文件不存在: {DB_CONFIG_PATH}")
            return None
    except Exception as e:
        logger.error(f"读取数据库配置失败: {e}")
        messagebox.showerror("错误", f"读取数据库配置失败: {e}")
        return None

def get_db_connection():
    """获取数据库连接"""
    db_config = get_db_config()
    if not db_config:
        return None
    try:
        return pymysql.connect(** db_config)
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        messagebox.showerror("错误", f"数据库连接失败: {e}")
        return None

# -------------------
# 获取待处理数据
# -------------------
def fetch_pending_data(conn):
    """从数据库获取待处理的数据"""
    if not conn:
        return []

    sql = """
        SELECT id, data_key, data_content, data_type
        FROM general_data
        WHERE data_type LIKE 'V33-IMG-%'
          AND is_deleted=0
    """
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql)
            data = cursor.fetchall()
            logger.info(f"获取到 {len(data)} 条待处理记录")
            return data
    except Exception as e:
        logger.error(f"获取待处理数据失败: {e}")
        messagebox.showerror("错误", f"获取待处理数据失败: {e}")
        return []

# -------------------
# 检查图片是否在小图列表中
# -------------------
def is_in_small_mapping(img_url):
    """检查图片是否在小图映射列表中"""
    try:
        with open(SMALL_IMG_JSON, 'r', encoding='utf-8') as f:
            small_images = json.load(f)
            return img_url in small_images
    except Exception as e:
        logger.error(f"读取小图JSON出错: {e}")
        return False

# -------------------
# 添加图片到小图列表
# -------------------
def add_to_small_mapping(img_url):
    """将小图URL添加到映射列表"""
    try:
        with open(SMALL_IMG_JSON, 'r+', encoding='utf-8') as f:
            small_images = json.load(f)
            if img_url not in small_images:
                small_images.append(img_url)
                f.seek(0)
                f.truncate()
                json.dump(small_images, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"写入小图JSON出错: {e}")

# -------------------
# 图片裁剪逻辑（裁剪后删除原图）
# -------------------
def process_image(original_path, output_path):
    """裁剪图片并保存，完成后删除原图片"""
    try:
        with Image.open(original_path) as img:
            width, height = img.size

            # 判断图片方向自动设置底部裁剪比例
            if height > width:
                CROP_RATIO_BOTTOM = 0.12  # 竖图
            else:
                CROP_RATIO_BOTTOM = 0.09  # 横图

            crop_height = int(height * (1 - CROP_RATIO_BOTTOM))
            cropped_img = img.crop((0, 0, width, crop_height))

            # 创建输出目录
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cropped_img.save(output_path)

            logger.info(f"裁剪完成: {os.path.basename(original_path)} (比例 {CROP_RATIO_BOTTOM})")

        # 裁剪成功后删除原图片
        if os.path.exists(original_path):
            os.remove(original_path)
            logger.info(f"已删除原图片: {os.path.basename(original_path)}")

    except Exception as e:
        logger.error(f"裁剪出错: {original_path} - {e}")

# -------------------
# 保存图片（带重试机制）
# -------------------
def save_image_with_retry(url, original_path, crop_path):
    """带重试机制的图片下载函数"""
    for attempt in range(RETRY_COUNT):
        try:
            # 检查是否需要安全停止
            with STOP_LOCK:
                if STOP_FLAG:
                    logger.warning(f"检测到停止信号，终止下载: {url}")
                    return False

            # 如果裁剪后的文件已经存在，直接跳过
            if os.path.exists(crop_path):
                logger.warning(f"裁剪后的图片已存在，跳过: {crop_path}")
                return True

            response = requests.get(url, stream=True, timeout=15)
            if response.status_code == 200:
                with open(original_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)

                # 下载完成后进行裁剪
                process_image(original_path, crop_path)
                logger.info(f"成功下载并处理: {crop_path}")
                return True
            else:
                logger.warning(f"下载失败（状态码: {response.status_code}），尝试第 {attempt + 1} 次: {url}")
                time.sleep(1)  # 重试前等待1秒

        except Exception as e:
            logger.warning(f"下载出错，尝试第 {attempt + 1} 次: {url} - {e}")
            time.sleep(1)  # 重试前等待1秒

    logger.error(f"达到最大重试次数，放弃下载: {url}")
    return False

# -------------------
# 从网页获取所有图片
# -------------------
def fetch_images_from_webpage(url):
    """从指定网页获取所有符合条件的图片URL"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        if resp.status_code != 200:
            logger.warning(f"获取页面失败: {url} -> 状态码: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # 查找页面中的所有 img 标签
        img_tags = soup.find_all("img")
        img_urls = []
        for img in img_tags:
            # 检查是否需要安全停止
            with STOP_LOCK:
                if STOP_FLAG:
                    logger.warning(f"检测到停止信号，终止图片获取")
                    return img_urls

            img_url = img.get("src") or img.get("data-src")  # 图片URL可能在data-src属性中
            if img_url:
                img_url = urljoin(url, img_url)  # 处理相对路径
                logger.info(f"发现图片URL: {img_url}")

                # 检查是否已在小图列表中
                if is_in_small_mapping(img_url):
                    logger.warning(f"图片在小图列表中，跳过: {img_url}")
                    continue

                # 获取图片实际尺寸
                try:
                    image_resp = requests.get(img_url, stream=True, timeout=10)
                    if image_resp.status_code == 200:
                        img = Image.open(BytesIO(image_resp.content))
                        img_width, img_height = img.size
                        # 过滤小于100px x 100px的图片并添加到小图列表
                        if img_width < 100 or img_height < 100:
                            logger.warning(f"图片尺寸过小 ({img_width}x{img_height})，添加到小图列表: {img_url}")
                            add_to_small_mapping(img_url)
                        else:
                            img_urls.append(img_url)
                except Exception as e:
                    logger.warning(f"获取图片尺寸出错: {img_url} - {e}")

        return img_urls
    except Exception as e:
        logger.warning(f"获取图片列表出错: {url} - {e}")
        return []

# -------------------
# 生成唯一保存目录
# -------------------
def generate_save_directory(data_type, data_key):
    """生成图片保存目录，处理不合法字符"""
    subdir = os.path.join(SAVE_DIR, data_type)
    os.makedirs(subdir, exist_ok=True)

    # 替换不合法字符
    invalid_chars = r'[\\/:*?"<>|]'
    data_key = re.sub(invalid_chars, '_', data_key)

    # 直接返回最终保存目录
    save_dir = os.path.join(subdir, data_key)
    os.makedirs(save_dir, exist_ok=True)

    return save_dir

# -------------------
# 更新状态为已删除
# -------------------
def mark_as_deleted(conn, record_id):
    """将数据库记录标记为已删除"""
    if not conn:
        return

    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE general_data SET is_deleted=1 WHERE id=%s", (record_id,))
        conn.commit()
        logger.info(f"已更新记录状态为已删除: {record_id}")
    except Exception as e:
        logger.error(f"更新记录状态出错: {record_id} - {e}")
        conn.rollback()

# -------------------
# 工作线程函数
# -------------------
def worker(queue, status_var):
    """处理队列中的下载任务"""
    conn = get_db_connection()
    try:
        while True:
            # 检查是否需要停止
            with STOP_LOCK:
                if STOP_FLAG and queue.empty():
                    break

            try:
                # 非阻塞获取任务，超时1秒
                record = queue.get(timeout=1)
            except:
                continue

            try:
                data_type = record["data_type"]
                data_key = record["data_key"]
                data_content = record["data_content"]
                record_id = record["id"]

                logger.info(f"\n处理中: {data_key} (线程: {threading.current_thread().name})")
                status_var.set(f"处理中: {data_key} (剩余: {queue.qsize()})")

                img_urls = fetch_images_from_webpage(data_content)

                if not img_urls:
                    logger.error("未找到有效图片，跳过")
                    mark_as_deleted(conn, record_id)
                    queue.task_done()
                    continue

                # 创建保存目录
                save_dir = generate_save_directory(data_type, data_key)

                # 下载图片并保存
                all_success = True
                for img_url in img_urls:
                    # 检查是否需要安全停止
                    with STOP_LOCK:
                        if STOP_FLAG:
                            all_success = False
                            break

                    img_name = os.path.basename(img_url)
                    # 原始图片临时路径（裁剪后会删除）
                    original_path = os.path.join(save_dir, f"temp_{img_name}")
                    # 裁剪后的最终路径
                    crop_path = os.path.join(save_dir, img_name)

                    # 下载图片（带重试）
                    if not save_image_with_retry(img_url, original_path, crop_path):
                        all_success = False

                # 无论是否全部成功，都标记为已处理
                mark_as_deleted(conn, record_id)

            except Exception as e:
                logger.error(f"处理记录出错: {record['id']} - {e}")
            finally:
                queue.task_done()
                status_var.set(f"等待任务... (剩余: {queue.qsize()})")

    finally:
        if conn:
            conn.close()
        logger.info(f"线程 {threading.current_thread().name} 已退出")

# -------------------
# 可视化界面
# -------------------
class ImageCrawlerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片爬取工具")
        self.root.geometry("600x450")  # 增加高度以容纳新选项
        self.root.resizable(True, True)

        self.task_queue = None
        self.threads = []
        self.running = False

        # 加载当前配置
        self.config = load_config()

        # 创建UI
        self.create_widgets()

        # 注册信号处理
        signal.signal(signal.SIGINT, self.handle_stop)
        signal.signal(signal.SIGTERM, self.handle_stop)

    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 保存目录设置
        ttk.Label(main_frame, text="保存目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.save_dir_var = tk.StringVar(value=self.config["SAVE_DIR"])
        ttk.Entry(main_frame, textvariable=self.save_dir_var, width=50).grid(row=0, column=1, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self.browse_save_dir).grid(row=0, column=2, padx=5, pady=5)

        # 线程数量设置
        ttk.Label(main_frame, text="线程数量:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.thread_count_var = tk.IntVar(value=self.config["THREAD_COUNT"])
        ttk.Spinbox(main_frame, from_=1, to=20, textvariable=self.thread_count_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        # 重试次数设置
        ttk.Label(main_frame, text="下载重试次数:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.retry_count_var = tk.IntVar(value=self.config["RETRY_COUNT"])
        ttk.Spinbox(main_frame, from_=1, to=10, textvariable=self.retry_count_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=5)

        # 新增：日志文件保存设置
        ttk.Label(main_frame, text="保存日志文件:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.save_log_var = tk.BooleanVar(value=self.config["SAVE_LOG_FILE"])
        ttk.Checkbutton(main_frame, variable=self.save_log_var).grid(row=3, column=1, sticky=tk.W, pady=5)

        # 状态显示
        ttk.Label(main_frame, text="状态:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(main_frame, textvariable=self.status_var).grid(row=4, column=1, sticky=tk.W, pady=5)

        # 日志区域
        ttk.Label(main_frame, text="操作日志:").grid(row=5, column=0, sticky=tk.NW, pady=5)
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=5, column=1, columnspan=2, sticky=tk.NSEW, pady=5)

        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(log_frame, height=10, width=50, yscrollcommand=scrollbar.set, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)

        # 绑定日志到文本框
        class TextHandler(logging.StreamHandler):
            def __init__(self, text_widget):
                logging.StreamHandler.__init__(self)
                self.text_widget = text_widget

            def emit(self, record):
                msg = self.format(record) + "\n"
                self.text_widget.configure(state=tk.NORMAL)
                self.text_widget.insert(tk.END, msg)
                self.text_widget.see(tk.END)
                self.text_widget.configure(state=tk.DISABLED)

        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(text_handler)

        # 按钮区域
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=6, column=0, columnspan=3, pady=10)

        self.start_btn = ttk.Button(btn_frame, text="开始爬取", command=self.start_crawling)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_crawling, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.save_config_btn = ttk.Button(btn_frame, text="保存配置", command=self.save_current_config)
        self.save_config_btn.pack(side=tk.LEFT, padx=5)

        self.view_log_btn = ttk.Button(btn_frame, text="查看日志文件", command=self.view_log_file)
        self.view_log_btn.pack(side=tk.LEFT, padx=5)

        # 配置网格权重
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(5, weight=1)

    def browse_save_dir(self):
        directory = filedialog.askdirectory(title="选择保存目录")
        if directory:
            self.save_dir_var.set(directory)

    def save_current_config(self):
        new_config = {
            "SAVE_DIR": self.save_dir_var.get(),
            "THREAD_COUNT": self.thread_count_var.get(),
            "RETRY_COUNT": self.retry_count_var.get(),
            "SAVE_LOG_FILE": self.save_log_var.get()  # 新增：保存日志配置
        }
        save_config(new_config)

        # 更新全局配置
        global SAVE_DIR, THREAD_COUNT, RETRY_COUNT, SAVE_LOG_FILE
        SAVE_DIR = new_config["SAVE_DIR"]
        THREAD_COUNT = new_config["THREAD_COUNT"]
        RETRY_COUNT = new_config["RETRY_COUNT"]
        SAVE_LOG_FILE = new_config["SAVE_LOG_FILE"]

        # 重新配置日志系统
        global logger
        logger = setup_logger()

        messagebox.showinfo("成功", "配置已保存")

    def view_log_file(self):
        try:
            if os.path.exists(PROCESS_LOG_FILE):
                os.startfile(PROCESS_LOG_FILE)
            else:
                messagebox.showinfo("提示", "日志文件不存在")
        except Exception as e:
            logger.error(f"打开日志文件失败: {e}")
            messagebox.showerror("错误", f"打开日志文件失败: {e}")

    def start_crawling(self):
        global STOP_FLAG
        with STOP_LOCK:
            STOP_FLAG = False

        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.save_config_btn.config(state=tk.DISABLED)

        # 先保存当前配置
        self.save_current_config()

        # 获取待处理数据
        conn = get_db_connection()
        if not conn:
            self.reset_ui_state()
            return

        records = fetch_pending_data(conn)
        conn.close()

        if not records:
            messagebox.showinfo("提示", "没有待处理的记录")
            self.reset_ui_state()
            return

        # 创建任务队列
        self.task_queue = Queue()
        for record in records:
            self.task_queue.put(record)

        # 启动工作线程
        self.threads = []
        thread_count = self.thread_count_var.get()
        logger.info(f"启动 {thread_count} 个工作线程...")

        for i in range(thread_count):
            t = threading.Thread(
                target=worker,
                args=(self.task_queue, self.status_var),
                name=f"Worker-{i+1}"
            )
            t.daemon = True
            t.start()
            self.threads.append(t)

        # 启动监控线程
        self.monitor_thread = threading.Thread(target=self.monitor_tasks)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def monitor_tasks(self):
        """监控任务完成情况"""
        if self.task_queue:
            self.task_queue.join()

        # 等待所有线程结束
        for t in self.threads:
            t.join()

        self.root.after(0, self.on_tasks_complete)

    def on_tasks_complete(self):
        """任务完成回调"""
        if not STOP_FLAG:  # 如果不是被强制停止的
            logger.info("所有任务已完成")
            messagebox.showinfo("完成", "所有任务已完成")

        self.reset_ui_state()

    def stop_crawling(self):
        global STOP_FLAG
        with STOP_LOCK:
            STOP_FLAG = True

        self.status_var.set("正在停止...")
        logger.warning("收到停止信号，将在完成当前任务后停止...")
        self.stop_btn.config(state=tk.DISABLED)

    def reset_ui_state(self):
        """重置UI状态"""
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.save_config_btn.config(state=tk.NORMAL)
        self.status_var.set("就绪")

    def handle_stop(self, signal, frame):
        """处理外部停止信号"""
        if self.running:
            self.stop_crawling()
        else:
            self.root.destroy()
            sys.exit(0)

# -------------------
# 程序入口
# -------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCrawlerApp(root)
    root.mainloop()
