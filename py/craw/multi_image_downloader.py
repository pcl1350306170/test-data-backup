import os
import re
import json
import requests
import pymysql
import threading
import logging
from logging.handlers import RotatingFileHandler
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path
import time
import sys

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "multi_image_downloader"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# 日志配置
MAX_LOG_SIZE = 1 * 1024 * 1024  # 1MB

# 默认配置
DEFAULT_CONFIG = {
    "DB_HOST": "localhost",
    "DB_PORT": 3306,
    "DB_USER": "root",
    "DB_PASSWORD": "123456",
    "DB_NAME": "test",
    "BASE_DIR": str(SCRIPT_DIR / "download" / "MTMT"),
    "MAX_THREADS": 5,
    "RETRY_COUNT": 2,
    "SAVE_LOG_FILE": True,
    "CROP_IMAGE": True,  # 新增：是否裁剪图片
    "SOURCE_FILTER": "%动漫%"  # source 过滤条件（支持 % 通配符）
}

# 需要跳过的图片文件名
SKIP_IMAGES = {
    "rss.png",
    "post.png",
    "reply.png",
    "none.gif",
    "home-old.gif",
    "7.gif"
}

# 停止标志
STOP_FLAG = False
STOP_LOCK = threading.Lock()

# ==============================
# 配置文件操作
# ==============================


def load_config():
    """加载配置文件"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
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

# ==============================
# 日志配置
# ==============================


def setup_logger():
    """配置日志系统"""
    logger = logging.getLogger(SCRIPT_NAME)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    config = load_config()
    if config["SAVE_LOG_FILE"]:
        file_handler = RotatingFileHandler(
            PROCESS_LOG_FILE,
            mode='a',
            maxBytes=MAX_LOG_SIZE,
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()

# 加载配置
config = load_config()

# ==============================
# 工具函数
# ==============================


def get_filename_from_url(url):
    """从URL中提取文件名"""
    filename = url.split("/")[-1].split("?")[0]
    return filename if filename else "unknown.jpg"


def check_skip_image(url):
    """检查是否是需要跳过的特定图片"""
    filename = get_filename_from_url(url)
    return filename in SKIP_IMAGES


def check_image_exists(url, save_dir):
    """检查图片是否已存在"""
    filename = get_filename_from_url(url)
    filepath = os.path.join(save_dir, filename)
    return os.path.exists(filepath)


def crop_image(original_path, output_path):
    """裁剪图片并保存，完成后删除原图片（与 download_img_see.py 规则一致）"""
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


def download_image(url, save_dir, retry=0):
    """下载单张图片，支持重试机制"""
    try:
        with STOP_LOCK:
            if STOP_FLAG:
                logger.warning(f"检测到停止信号，终止下载: {url}")
                return False

        if check_skip_image(url):
            logger.info(f"[跳过指定小图] {url}")
            return True

        if check_image_exists(url, save_dir):
            filename = get_filename_from_url(url)
            logger.info(f"[已存在] {os.path.join(save_dir, filename)}")
            return True

        resp = requests.get(url.strip(), timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[失败] 状态码：{resp.status_code} => {url}")
            if retry < config["RETRY_COUNT"] and resp.status_code in [500, 502, 503, 504, 429]:
                logger.info(
                    f"[重试] {url} (剩余次数: {config['RETRY_COUNT'] - retry - 1})")
                time.sleep(1)
                return download_image(url, save_dir, retry + 1)
            return False

        img = Image.open(BytesIO(resp.content))
        if img.width < 100 or img.height < 100:
            logger.info(f"[跳过小图] {url} ({img.width}x{img.height})")
            return True

        filename = get_filename_from_url(url)
        filepath = os.path.join(save_dir, filename)
        
        # 根据配置决定是否裁剪
        if config.get("CROP_IMAGE", True):
            # 先保存到临时文件
            temp_path = os.path.join(save_dir, f"temp_{filename}")
            img.save(temp_path)
            # 裁剪图片（裁剪后会删除临时文件）
            crop_image(temp_path, filepath)
        else:
            # 直接保存原图
            img.save(filepath)
            
        logger.info(f"[完成] {filepath}")
        return True

    except requests.exceptions.Timeout:
        logger.warning(f"[超时] {url}")
        if retry < config["RETRY_COUNT"]:
            logger.info(
                f"[重试] {url} (剩余次数: {config['RETRY_COUNT'] - retry - 1})")
            time.sleep(1)
            return download_image(url, save_dir, retry + 1)
        return False
    except Exception as e:
        logger.error(f"[错误] {url} => {str(e)[:100]}")
        return False


def get_db_connection(db_config):
    """获取数据库连接"""
    try:
        return pymysql.connect(
            host=db_config["DB_HOST"],
            port=db_config["DB_PORT"],
            user=db_config["DB_USER"],
            password=db_config["DB_PASSWORD"],
            database=db_config["DB_NAME"],
            charset="utf8mb4"
        )
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return None


def fetch_data(db_config, source_filter="%动漫%"):
    """从数据库读取数据"""
    conn = get_db_connection(db_config)
    if not conn:
        return []

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        query = "SELECT uid, title, content, source FROM web_crawl_data WHERE is_deleted=0 AND source LIKE %s"
        cursor.execute(query, (source_filter,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        logger.info(f"获取到 {len(rows)} 条待处理记录 (source过滤: {source_filter})")
        return rows
    except Exception as e:
        logger.error(f"获取待处理数据失败: {e}")
        conn.close()
        return []


def mark_as_deleted(db_config, uid):
    """标记数据库中的记录为已处理"""
    conn = get_db_connection(db_config)
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_deleted FROM web_crawl_data WHERE uid=%s", (uid,))
        current_status = cursor.fetchone()

        if not current_status:
            logger.warning(f"[更新失败] UID: {uid} 不存在")
            conn.close()
            return False

        if current_status[0] == 1:
            logger.info(f"[已更新状态] UID: {uid} (状态已为1)")
            conn.close()
            return True

        affected_rows = cursor.execute(
            "UPDATE web_crawl_data SET is_deleted=1 WHERE uid=%s",
            (uid,)
        )
        conn.commit()
        conn.close()

        if affected_rows > 0:
            logger.info(f"[已更新状态] UID: {uid} (之前状态: {current_status[0]})")
        else:
            logger.warning(f"[更新失败] UID: {uid} 未找到或已更新")

        return affected_rows > 0
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        logger.error(f"[更新状态错误] UID: {uid} => {e}")
        return False


def worker_task(uid, title, urls, db_config, status_callback, source=""):
    """线程任务：下载一个数据记录中的所有图片"""
    # 清理标题中的非法字符
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "untitled"
    
    # 根据 source 和 title 构建目录结构
    if source:
        # 清理 source 中的非法字符
        safe_source = "".join(c for c in source if c.isalnum() or c in " _-").strip() or "unknown"
        save_dir = os.path.join(config["BASE_DIR"], safe_source, safe_title)
    else:
        save_dir = os.path.join(config["BASE_DIR"], safe_title)
    
    os.makedirs(save_dir, exist_ok=True)

    total = len(urls)
    success_count = 0
    failed_urls = []

    for i, url in enumerate(urls):
        with STOP_LOCK:
            if STOP_FLAG:
                logger.warning("⚠️ 检测到停止信号，等待当前任务结束...")
                return (False, failed_urls)

        if download_image(url, save_dir):
            success_count += 1
        else:
            failed_urls.append(url)

        # 更新进度
        progress = f"{i+1}/{total}" if total > 0 else "0/0"
        status_callback(f"处理中: {safe_title} - 图片进度: {progress}")

    completion_rate = success_count / total if total > 0 else 1
    task_completed = completion_rate > 0

    logger.info(f"[任务总结] UID:{uid} 完成{success_count}/{total} 图片")
    status_callback(f"完成: {safe_title} - {success_count}/{total} 图片")

    return (task_completed, failed_urls)

# ==============================
# GUI 界面
# ==============================


class MultiImageDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("多线程图片下载器")
        self.root.geometry("700x600")
        self.root.resizable(True, True)

        self.running = False
        self.executor = None

        # 加载配置
        self.config = load_config()

        self.create_widgets()

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 下载配置 ===
        dl_frame = ttk.LabelFrame(main_frame, text="下载配置", padding="10")
        dl_frame.pack(fill=tk.X, pady=5)

        ttk.Label(dl_frame, text="保存目录:").grid(
            row=0, column=0, sticky=tk.W, pady=3)
        self.base_dir_var = tk.StringVar(value=self.config["BASE_DIR"])
        ttk.Entry(dl_frame, textvariable=self.base_dir_var,
                  width=40).grid(row=0, column=1, padx=5, pady=3)
        ttk.Button(dl_frame, text="浏览...", command=self.browse_save_dir).grid(
            row=0, column=2, padx=5, pady=3)

        ttk.Label(dl_frame, text="线程数:").grid(
            row=1, column=0, sticky=tk.W, pady=3)
        self.thread_count_var = tk.IntVar(value=self.config["MAX_THREADS"])
        ttk.Spinbox(dl_frame, from_=1, to=20, textvariable=self.thread_count_var,
                    width=10).grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(dl_frame, text="重试次数:").grid(
            row=1, column=2, sticky=tk.W, pady=3)
        self.retry_count_var = tk.IntVar(value=self.config["RETRY_COUNT"])
        ttk.Spinbox(dl_frame, from_=1, to=10, textvariable=self.retry_count_var,
                    width=10).grid(row=1, column=3, sticky=tk.W, padx=5, pady=3)

        ttk.Label(dl_frame, text="保存日志:").grid(
            row=2, column=0, sticky=tk.W, pady=3)
        self.save_log_var = tk.BooleanVar(value=self.config["SAVE_LOG_FILE"])
        ttk.Checkbutton(dl_frame, variable=self.save_log_var).grid(
            row=2, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(dl_frame, text="裁剪图片:").grid(
            row=2, column=2, sticky=tk.W, pady=3)
        self.crop_image_var = tk.BooleanVar(value=self.config.get("CROP_IMAGE", True))
        ttk.Checkbutton(dl_frame, variable=self.crop_image_var).grid(
            row=2, column=3, sticky=tk.W, padx=5, pady=3)

        ttk.Label(dl_frame, text="source过滤:").grid(
            row=3, column=0, sticky=tk.W, pady=3)
        self.source_filter_var = tk.StringVar(value=self.config.get("SOURCE_FILTER", "%动漫%"))
        ttk.Entry(dl_frame, textvariable=self.source_filter_var,
                  width=40).grid(row=3, column=1, columnspan=3, padx=5, pady=3, sticky=tk.W)
        ttk.Label(dl_frame, text="(支持%通配符，例: %动漫%, %小说%)", 
                  foreground="gray", font=("Arial", 8)).grid(row=4, column=0, columnspan=4, sticky=tk.W, padx=5)

        # === 状态显示 ===
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=5)

        ttk.Label(status_frame, text="状态:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(status_frame, text="进度:").pack(side=tk.LEFT, padx=(20, 0))
        self.progress_var = tk.StringVar(value="0/0")
        ttk.Label(status_frame, textvariable=self.progress_var).pack(
            side=tk.LEFT, padx=5)

        # 进度条
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=5)

        # === 日志区域 ===
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(
            log_frame, height=10, yscrollcommand=scrollbar.set, state=tk.DISABLED)
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
        text_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(text_handler)

        # === 按钮区域 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.start_btn = ttk.Button(
            btn_frame, text="开始下载", command=self.start_download)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(
            btn_frame, text="停止", command=self.stop_download, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.save_config_btn = ttk.Button(
            btn_frame, text="保存配置", command=self.save_current_config)
        self.save_config_btn.pack(side=tk.LEFT, padx=5)

        self.view_log_btn = ttk.Button(
            btn_frame, text="查看日志文件", command=self.view_log_file)
        self.view_log_btn.pack(side=tk.LEFT, padx=5)

    def browse_save_dir(self):
        directory = filedialog.askdirectory(title="选择保存目录")
        if directory:
            self.base_dir_var.set(directory)

    def save_current_config(self):
        new_config = {
            "DB_HOST": self.config["DB_HOST"],
            "DB_PORT": self.config["DB_PORT"],
            "DB_USER": self.config["DB_USER"],
            "DB_PASSWORD": self.config["DB_PASSWORD"],
            "DB_NAME": self.config["DB_NAME"],
            "BASE_DIR": self.base_dir_var.get(),
            "MAX_THREADS": self.thread_count_var.get(),
            "RETRY_COUNT": self.retry_count_var.get(),
            "SAVE_LOG_FILE": self.save_log_var.get(),
            "CROP_IMAGE": self.crop_image_var.get(),
            "SOURCE_FILTER": self.source_filter_var.get()
        }
        save_config(new_config)

        # 更新全局配置
        global config
        config = new_config

        # 重新配置日志
        global logger
        logger = setup_logger()

        messagebox.showinfo("成功", "配置已保存")

    def view_log_file(self):
        try:
            if PROCESS_LOG_FILE.exists():
                os.startfile(str(PROCESS_LOG_FILE))
            else:
                messagebox.showinfo("提示", "日志文件不存在")
        except Exception as e:
            logger.error(f"打开日志文件失败: {e}")
            messagebox.showerror("错误", f"打开日志文件失败: {e}")

    def start_download(self):
        global STOP_FLAG
        with STOP_LOCK:
            STOP_FLAG = False

        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.save_config_btn.config(state=tk.DISABLED)

        # 先保存配置
        self.save_current_config()

        # 创建保存目录
        os.makedirs(config["BASE_DIR"], exist_ok=True)

        # 构建数据库配置
        db_config = {
            "DB_HOST": config["DB_HOST"],
            "DB_PORT": config["DB_PORT"],
            "DB_USER": config["DB_USER"],
            "DB_PASSWORD": config["DB_PASSWORD"],
            "DB_NAME": config["DB_NAME"]
        }

        # 获取数据
        source_filter = self.source_filter_var.get().strip()
        if not source_filter:
            source_filter = "%"  # 如果为空，匹配所有
        
        rows = fetch_data(db_config, source_filter)
        if not rows:
            messagebox.showinfo("提示", f"没有待处理的记录 (source过滤: {source_filter})")
            self.reset_ui_state()
            return

        logger.info(f"共读取 {len(rows)} 条数据")
        self.progress.start(10)

        # 在新线程中执行下载
        thread = threading.Thread(
            target=self.run_download, args=(rows, db_config), daemon=True)
        thread.start()

    def run_download(self, rows, db_config):
        try:
            completed_count = 0
            total_count = len(rows)

            def update_status(msg):
                self.root.after(0, lambda: self.status_var.set(msg))

            def update_progress():
                nonlocal completed_count
                completed_count += 1
                self.root.after(0, lambda: self.progress_var.set(
                    f"{completed_count}/{total_count}"))

            with ThreadPoolExecutor(max_workers=config["MAX_THREADS"]) as executor:
                futures = {}
                for row in rows:
                    uid = row["uid"]
                    title = row["title"] or "untitled"
                    content = row["content"]
                    source = row.get("source", "")  # 获取 source 字段

                    if not content:
                        logger.info(f"{uid} 没有图片，跳过并标记为已处理")
                        mark_as_deleted(db_config, uid)
                        update_progress()
                        continue

                    urls = [u.strip() for u in content.split(",") if u.strip()]
                    futures[executor.submit(
                        worker_task, uid, title, urls, db_config, update_status, source)] = uid

                for f in as_completed(futures):
                    with STOP_LOCK:
                        if STOP_FLAG:
                            break

                    uid = futures[f]
                    try:
                        result, failed_urls = f.result()
                        update_success = mark_as_deleted(db_config, uid)

                        if not update_success:
                            logger.warning(f"[警告] UID: {uid} 状态更新失败")
                        elif not result:
                            logger.warning(
                                f"[部分失败] UID: {uid} 已标记为处理，但有 {len(failed_urls)} 张图片下载失败")
                    except Exception as e:
                        logger.error(f"[任务异常] UID: {uid} => {e}")
                        mark_as_deleted(db_config, uid)

                    update_progress()

            if not STOP_FLAG:
                logger.info("✅ 所有下载任务完成")
                self.root.after(
                    0, lambda: messagebox.showinfo("完成", "所有下载任务完成！"))
        except Exception as e:
            logger.error(f"下载过程出错: {e}")
            self.root.after(
                0, lambda: messagebox.showerror("错误", f"下载过程出错: {e}"))
        finally:
            self.root.after(0, self.reset_ui_state)

    def stop_download(self):
        global STOP_FLAG
        with STOP_LOCK:
            STOP_FLAG = True

        self.status_var.set("正在停止...")
        logger.warning("收到停止信号，将在完成当前任务后停止...")
        self.stop_btn.config(state=tk.DISABLED)

    def reset_ui_state(self):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.save_config_btn.config(state=tk.NORMAL)
        self.status_var.set("就绪")
        self.progress_var.set("0/0")
        self.progress.stop()


# ==============================
# 程序入口
# ==============================
if __name__ == "__main__":
    root = tk.Tk()
    app = MultiImageDownloaderApp(root)
    root.mainloop()
