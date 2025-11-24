# reddit_scraper.py

import os
import json
import logging
import threading
import time
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
import praw
import requests
from datetime import datetime, timedelta
import sqlite3

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "reddit_scraper"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = CONFIG_DIR / "logs" / f"log_{SCRIPT_NAME}.log"
PROCESS_LOG_FILE.parent.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "save_directory": r"G:\下载\Reddit\java",
    "subreddit_name": "r/java",
    "content_types": ["image", "video", "gif"],  # 可选: image, video, gif, text
    "time_filter": "all",  # 可选: all, hour, day, week, month, year
    "batch_size": 50,
    "num_threads": 5,
    "save_to_db": False,
    "client_id": "",  # Reddit API 配置
    "client_secret": "",
    "user_agent": "RedditScraper/1.0 by YourUsername"
}

# ================== Reddit API 初始化 ==================
def get_reddit_instance(config):
    """创建 Reddit 实例"""
    if not config.get("client_id") or not config.get("client_secret"):
        messagebox.showerror("错误", "请在配置中设置 Reddit API 凭据（client_id 和 client_secret）")
        return None

    try:
        reddit = praw.Reddit(
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            user_agent=config["user_agent"]
        )
        # 测试连接
        reddit.subreddit('python').hot(limit=1)
        return reddit
    except Exception as e:
        logging.error(f"Reddit API 连接失败: {e}")
        messagebox.showerror("API 错误", f"Reddit API 连接失败: {e}")
        return None

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

def load_db_config():
    """加载数据库配置"""
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"数据库配置加载失败: {e}")
    return None

def create_database(db_config):
    """创建数据库表"""
    conn = sqlite3.connect(f"{db_config['database']}.db")
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reddit_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT,
            title TEXT,
            author TEXT,
            url TEXT,
            permalink TEXT,
            created_utc REAL,
            content_type TEXT,
            file_path TEXT,
            score INTEGER,
            num_comments INTEGER
        )
    ''')

    conn.commit()
    conn.close()

def save_to_database(db_config, posts_data):
    """保存数据到数据库"""
    try:
        conn = sqlite3.connect(f"{db_config['database']}.db")
        cursor = conn.cursor()

        for post in posts_data:
            cursor.execute('''
                INSERT INTO reddit_posts 
                (subreddit, title, author, url, permalink, created_utc, content_type, file_path, score, num_comments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                post.get('subreddit'), post.get('title'), post.get('author'),
                post.get('url'), post.get('permalink'), post.get('created_utc'),
                post.get('content_type'), post.get('file_path'), post.get('score'), post.get('num_comments')
            ))

        conn.commit()
        conn.close()
        logging.info(f"已保存 {len(posts_data)} 条数据到数据库")
    except Exception as e:
        logging.error(f"数据库保存失败: {e}")

def download_media(url, save_path, progress_callback=None):
    """下载媒体文件"""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        if progress_callback:
            progress_callback(f"已下载: {save_path.name}")
        return True
    except Exception as e:
        logging.error(f"下载失败 {url}: {e}")
        return False

def scrape_reddit_posts(config, progress_callback=None):
    """爬取 Reddit 帖子"""
    try:
        # 初始化 Reddit 实例
        reddit = get_reddit_instance(config)
        if not reddit:
            return False

        # 获取子版块
        subreddit_name = config["subreddit_name"].replace("r/", "")
        subreddit = reddit.subreddit(subreddit_name)

        # 时间过滤
        time_filter = config["time_filter"]
        if time_filter == "all":
            posts = subreddit.hot(limit=None)
        elif time_filter == "hour":
            posts = subreddit.top(time_filter="hour")
        elif time_filter == "day":
            posts = subreddit.top(time_filter="day")
        elif time_filter == "week":
            posts = subreddit.top(time_filter="week")
        elif time_filter == "month":
            posts = subreddit.top(time_filter="month")
        elif time_filter == "year":
            posts = subreddit.top(time_filter="year")
        else:
            posts = subreddit.hot(limit=None)

        # 创建保存目录
        save_dir = Path(config["save_directory"])
        save_dir.mkdir(parents=True, exist_ok=True)

        # 数据库配置
        db_config = load_db_config() if config.get("save_to_db") else None
        if db_config:
            create_database(db_config)

        # 获取允许的内容类型
        allowed_types = set(config.get("content_types", ["image", "video", "gif"]))

        # 开始爬取
        posts_data = []
        count = 0

        for post in posts:
            try:
                # 检查时间范围（如果设置了）
                if time_filter != "all":
                    post_time = datetime.utcfromtimestamp(post.created_utc)
                    current_time = datetime.utcnow()

                    if time_filter == "hour" and (current_time - post_time).hours > 1:
                        continue
                    elif time_filter == "day" and (current_time - post_time).days > 1:
                        continue
                    elif time_filter == "week" and (current_time - post_time).days > 7:
                        continue
                    elif time_filter == "month" and (current_time - post_time).days > 30:
                        continue
                    elif time_filter == "year" and (current_time - post_time).days > 365:
                        continue

                # 确定内容类型
                content_type = "text"
                media_url = None

                if hasattr(post, 'url'):
                    post_url = post.url.lower()
                    if any(ext in post_url for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']):
                        content_type = "image"
                        media_url = post.url
                    elif any(ext in post_url for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']):
                        content_type = "video"
                        media_url = post.url
                    elif '.gif' in post_url or 'giphy' in post_url:
                        content_type = "gif"
                        media_url = post.url
                    elif hasattr(post, 'is_video') and post.is_video:
                        content_type = "video"
                        media_url = post.url
                    elif hasattr(post, 'selftext') and post.selftext:
                        content_type = "text"

                # 检查是否在允许的类型中
                if content_type not in allowed_types:
                    continue

                # 准备数据
                post_data = {
                    'subreddit': post.subreddit.display_name,
                    'title': post.title,
                    'author': str(post.author) if post.author else '[deleted]',
                    'url': post.url,
                    'permalink': f"https://reddit.com{post.permalink}",
                    'created_utc': post.created_utc,
                    'content_type': content_type,
                    'score': post.score,
                    'num_comments': post.num_comments
                }

                # 下载媒体文件
                file_path = None
                if media_url and content_type in ['image', 'video', 'gif']:
                    ext = Path(media_url).suffix
                    if not ext:
                        ext = '.jpg' if content_type == 'image' else '.mp4'

                    filename = f"{post.id}_{content_type}{ext}"
                    file_path = save_dir / filename
                    post_data['file_path'] = str(file_path)

                    if download_media(media_url, file_path, progress_callback):
                        logging.info(f"下载成功: {filename}")
                    else:
                        post_data['file_path'] = None

                posts_data.append(post_data)
                count += 1

                if progress_callback:
                    progress_callback(f"已处理 {count} 个帖子: {post.title[:50]}...")

                # 分批保存
                if len(posts_data) >= config["batch_size"]:
                    if db_config and config.get("save_to_db"):
                        save_to_database(db_config, posts_data)
                    else:
                        # 保存到 JSON 文件
                        batch_file = save_dir / f"batch_{count // config['batch_size']}.json"
                        with open(batch_file, 'w', encoding='utf-8') as f:
                            json.dump(posts_data, f, ensure_ascii=False, indent=2)

                    posts_data = []  # 清空批次数据

            except Exception as e:
                logging.error(f"处理帖子失败 {post.id}: {e}")
                continue

        # 保存剩余数据
        if posts_data:
            if db_config and config.get("save_to_db"):
                save_to_database(db_config, posts_data)
            else:
                batch_file = save_dir / f"batch_final_{len(posts_data)}.json"
                with open(batch_file, 'w', encoding='utf-8') as f:
                    json.dump(posts_data, f, ensure_ascii=False, indent=2)

        logging.info(f"爬取完成，共处理 {count} 个帖子")
        if progress_callback:
            progress_callback(f"✅ 爬取完成！共处理 {count} 个帖子，已保存到: {save_dir}")

        return True

    except Exception as e:
        logging.error(f"爬取失败: {e}")
        if progress_callback:
            progress_callback(f"❌ 爬取失败: {e}")
        return False

# ================== GUI 类 ==================

class RedditScraperApp:
    def __init__(self, root):
        self.root = root
        self.root.title(" Reddit 子版块爬取工具")
        self.root.geometry("850x700")
        self.root.resizable(True, True)

        self.config = load_or_create_config()
        self.setup_ui()

    def setup_ui(self):
        # 保存目录
        frame_dir = LabelFrame(self.root, text="1. 保存目录", padx=10, pady=10)
        frame_dir.pack(fill=X, padx=20, pady=10)

        self.save_dir_var = StringVar(value=self.config["save_directory"])
        Entry(frame_dir, textvariable=self.save_dir_var, width=70, font=("Consolas", 10)).pack(side=LEFT, padx=5)
        Button(frame_dir, text="📁 选择目录", command=self.select_save_dir).pack(side=LEFT, padx=5)

        # 子版块名称
        frame_subreddit = LabelFrame(self.root, text="2. 子版块名称", padx=10, pady=10)
        frame_subreddit.pack(fill=X, padx=20, pady=10)

        self.subreddit_var = StringVar(value=self.config["subreddit_name"])
        Label(frame_subreddit, text="格式: r/java 或 java", font=("Arial", 10)).grid(row=0, column=0, sticky=W, padx=5)
        Entry(frame_subreddit, textvariable=self.subreddit_var, width=20).grid(row=0, column=1, padx=5)

        # 内容类型选择
        frame_content = LabelFrame(self.root, text="3. 选择内容类型", padx=10, pady=10)
        frame_content.pack(fill=X, padx=20, pady=10)

        self.content_vars = {}
        content_types = ["image", "video", "gif", "text"]
        for i, ctype in enumerate(content_types):
            var = BooleanVar(value=ctype in self.config.get("content_types", ["image", "video", "gif"]))
            Checkbutton(frame_content, text=ctype.capitalize(), variable=var).grid(row=0, column=i, padx=10)
            self.content_vars[ctype] = var

        # 时间过滤
        frame_time = LabelFrame(self.root, text="4. 时间范围", padx=10, pady=10)
        frame_time.pack(fill=X, padx=20, pady=10)

        time_options = ["all", "hour", "day", "week", "month", "year"]
        self.time_var = StringVar(value=self.config.get("time_filter", "all"))
        Label(frame_time, text="时间范围:", font=("Arial", 10)).grid(row=0, column=0, sticky=W, padx=5)
        ttk.Combobox(frame_time, textvariable=self.time_var, values=time_options, state="readonly", width=15).grid(row=0, column=1, padx=5)

        # 批次大小和线程数
        frame_batch = LabelFrame(self.root, text="5. 爬取设置", padx=10, pady=10)
        frame_batch.pack(fill=X, padx=20, pady=10)

        Label(frame_batch, text="每批保存数量:", font=("Arial", 10)).grid(row=0, column=0, sticky=W, padx=5)
        self.batch_var = StringVar(value=str(self.config.get("batch_size", 50)))
        Entry(frame_batch, textvariable=self.batch_var, width=10).grid(row=0, column=1, padx=5)

        Label(frame_batch, text="线程数:", font=("Arial", 10)).grid(row=0, column=2, sticky=W, padx=5)
        self.threads_var = StringVar(value=str(self.config.get("num_threads", 5)))
        Entry(frame_batch, textvariable=self.threads_var, width=10).grid(row=0, column=3, padx=5)

        # 数据库保存选项
        frame_db = LabelFrame(self.root, text="6. 数据库配置", padx=10, pady=10)
        frame_db.pack(fill=X, padx=20, pady=10)

        self.save_to_db_var = BooleanVar(value=self.config.get("save_to_db", False))
        Checkbutton(frame_db, text="保存到数据库", variable=self.save_to_db_var).pack(side=LEFT, padx=5)

        # Reddit API 配置
        frame_api = LabelFrame(self.root, text="7. Reddit API 配置", padx=10, pady=10)
        frame_api.pack(fill=X, padx=20, pady=10)

        Label(frame_api, text="Client ID:", font=("Arial", 10)).grid(row=0, column=0, sticky=W, padx=5)
        self.client_id_var = StringVar(value=self.config.get("client_id", ""))
        Entry(frame_api, textvariable=self.client_id_var, width=30).grid(row=0, column=1, padx=5)

        Label(frame_api, text="Client Secret:", font=("Arial", 10)).grid(row=0, column=2, sticky=W, padx=5)
        self.client_secret_var = StringVar(value=self.config.get("client_secret", ""))
        Entry(frame_api, textvariable=self.client_secret_var, width=30).grid(row=0, column=3, padx=5)

        Label(frame_api, text="User Agent:", font=("Arial", 10)).grid(row=1, column=0, sticky=W, padx=5)
        self.user_agent_var = StringVar(value=self.config.get("user_agent", "RedditScraper/1.0 by YourUsername"))
        Entry(frame_api, textvariable=self.user_agent_var, width=60).grid(row=1, column=1, columnspan=3, padx=5)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)

        Button(btn_frame, text="💾 保存配置", command=self.save_config, bg="#9C27B0", fg="white", width=12).grid(row=0, column=0, padx=10)
        Button(btn_frame, text="🚀 开始爬取", command=self.start_scraping, bg="#4CAF50", fg="white", width=15, height=2).grid(row=0, column=1, padx=10)

        # 进度显示
        self.progress_label = Label(self.root, text="就绪", fg="green", font=("Arial", 12))
        self.progress_label.pack(pady=10)

        # 日志输出
        log_frame = LabelFrame(self.root, text="📝 操作日志", padx=10, pady=10)
        log_frame.pack(fill=BOTH, expand=True, padx=20, pady=(0, 10))

        self.log_text = Text(log_frame, height=12, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

    def select_save_dir(self):
        dir_path = filedialog.askdirectory(
            title="选择保存目录",
            initialdir=self.config["save_directory"]
        )
        if dir_path:
            self.save_dir_var.set(dir_path)

    def save_config(self):
        content_types = [ctype for ctype, var in self.content_vars.items() if var.get()]

        self.config.update({
            "save_directory": self.save_dir_var.get(),
            "subreddit_name": self.subreddit_var.get(),
            "content_types": content_types,
            "time_filter": self.time_var.get(),
            "batch_size": int(self.batch_var.get()),
            "num_threads": int(self.threads_var.get()),
            "save_to_db": self.save_to_db_var.get(),
            "client_id": self.client_id_var.get(),
            "client_secret": self.client_secret_var.get(),
            "user_agent": self.user_agent_var.get()
        })
        save_config(self.config)
        messagebox.showinfo("保存成功", "配置已保存！")
        logging.info("配置已保存")

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)

    def update_progress(self, msg):
        self.progress_label.config(text=msg)
        self.root.update_idletasks()

    def start_scraping(self):
        # 验证输入
        subreddit = self.subreddit_var.get().strip()
        if not subreddit:
            messagebox.showerror("错误", "请输入子版块名称！")
            return

        # 保存配置
        self.save_config()

        self.update_progress("开始爬取...")
        self.log_to_gui("开始爬取 Reddit 数据...")

        def run_scraping():
            success = scrape_reddit_posts(
                self.config,
                progress_callback=lambda msg: self.root.after(0, lambda: self.update_progress(msg))
            )
            if success:
                self.root.after(0, lambda: self.log_to_gui("✅ 爬取完成！"))
            else:
                self.root.after(0, lambda: self.log_to_gui("❌ 爬取失败，请查看日志。"))

        threading.Thread(target=run_scraping, daemon=True).start()

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = RedditScraperApp(root)
    root.mainloop()
