# -*- coding: utf-8 -*-
"""
Reddit 子版块全量采集工具（游客 + OAuth 双模式）
作者：ChatGPT 2025
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import List, Dict, Any, Optional

import requests
import praw
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ====================== 配置与常量 ======================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "RedditCrawler"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
REDDIT_CHI_PATH = CONFIG_DIR / "reddit_chi.json"
DB_CONFIG_PATH = SCRIPT_DIR.parent / "json" / "DB_CONFIG.json"

# 自动创建目录
for p in (CONFIG_DIR, SCRIPT_DIR / "data"):
    p.mkdir(parents=True, exist_ok=True)

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

# ====================== 默认配置 ======================
DEFAULT_CONFIG = {
    "save_root": r"G:\下载\Reddit\java",
    "subreddit": "java",
    "use_oauth": False,
    "client_id": "",
    "client_secret": "",
    "user_agent": "RedditCrawler/1.0 by u/yourname",

    "download_types": {
        "image": True,
        "video": True,
        "gif": True,
        "gallery": True,
        "document": True,
        "selftext": True
    },

    "start_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
    "end_date": datetime.now().strftime("%Y-%m-%d"),

    "batch_size": 50,
    "threads": 5,

    "save_to_db": False
}

# ====================== 加载/保存配置 ======================
def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取配置失败: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def load_subreddits() -> List[Dict[str, str]]:
    if REDDIT_CHI_PATH.exists():
        try:
            with open(REDDIT_CHI_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except:
            pass
    # 默认示例
    default = [{"name": "r/java", "description": "A place for java."}]
    save_subreddits(default)
    return default

def save_subreddits(data: List[Dict[str, str]]):
    with open(REDDIT_CHI_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ====================== 数据库相关 ======================
def get_db_connection():
    if not DB_CONFIG_PATH.exists():
        return None
    try:
        with open(DB_CONFIG_PATH, encoding="utf-8") as f:
            db_cfg = json.load(f)
        import pymysql
        return pymysql.connect(**db_cfg)
    except Exception as e:
        logger.error(f"连接数据库失败: {e}")
        return None

# 建表语句（一次性执行即可）
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reddit_posts (
    id VARCHAR(20) PRIMARY KEY,
    subreddit VARCHAR(50),
    title TEXT,
    author VARCHAR(100),
    created_utc BIGINT,
    url TEXT,
    selftext TEXT,
    score INT,
    num_comments INT,
    permalink TEXT,
    media_type VARCHAR(20),
    media_path TEXT,
    downloaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_subreddit (subreddit),
    INDEX idx_created (created_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# ====================== 主窗口 ======================
class RedditCrawlerGUI:
    def __init__(self):
        self.config = load_config()
        self.subreddits = load_subreddits()

        self.root = tk.Tk()
        self.root.title("Reddit 子版块采集工具")
        self.root.geometry("760x680")

        self.create_widgets()
        self.load_config_to_ui()

    def create_widgets(self):
        row = 0

        # 1. 保存目录
        tk.Label(self.root, text="保存根目录:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        self.save_dir_var = tk.StringVar(value=self.config.get("save_root", ""))
        tk.Entry(self.root, textvariable=self.save_dir_var, width=60).grid(row=row, column=1, padx=5, pady=5)
        tk.Button(self.root, text="浏览", command=self.browse_save_dir).grid(row=row, column=2, pady=5)
        row += 1

        # 2. 子版块选择
        tk.Label(self.root, text="子版块:").grid(row=row, column=0, sticky="e", padx=5, pady=5)
        self.sub_var = tk.StringVar()
        self.sub_combo = ttk.Combobox(self.root, textvariable=self.sub_var, width=40)
        self.sub_combo["values"] = [item["name"] for item in self.subreddits]
        self.sub_combo.grid(row=row, column=1, padx=5, pady=5)
        tk.Button(self.root, text="添加/更新", command=self.add_subreddit).grid(row=row, column=2, pady=5)
        row += 1

        # 3. OAuth 可选
        self.oauth_var = tk.BooleanVar(value=self.config.get("use_oauth", False))
        tk.Checkbutton(self.root, text="使用 OAuth（更高限速）", variable=self.oauth_var,
                       command=self.toggle_oauth).grid(row=row, column=0, columnspan=2, sticky="w", padx=10)
        row += 1

        self.oauth_frame = tk.Frame(self.root)
        self.oauth_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=20)
        tk.Label(self.oauth_frame, text="client_id:").grid(row=0, column=0, sticky="e")
        self.cid_var = tk.StringVar()
        tk.Entry(self.oauth_frame, textvariable=self.cid_var, width=40).grid(row=0, column=1, padx=5)
        tk.Label(self.oauth_frame, text="client_secret:").grid(row=1, column=0, sticky="e")
        self.csec_var = tk.StringVar()
        tk.Entry(self.oauth_frame, textvariable=self.csec_var, width=40, show="*").grid(row=1, column=1, padx=5)
        row += 1

        # 4. 下载类型
        tk.Label(self.root, text="下载内容:", font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w", padx=10)
        row += 1
        types_frame = tk.Frame(self.root)
        types_frame.grid(row=row, column=0, columnspan=3, sticky="w", padx=20)
        self.type_vars = {}
        for i, (name_cn, key) in enumerate([
            ("图片", "image"), ("视频", "video"), ("GIF", "gif"),
            ("图集", "gallery"), ("文档", "document"), ("正文", "selftext")
        ]):
            var = tk.BooleanVar(value=self.config["download_types"].get(key, True))
            tk.Checkbutton(types_frame, text=name_cn, variable=var).grid(row=i//3, column=i%3, sticky="w")
            self.type_vars[key] = var
        row += 1

        # 5. 时间段
        tk.Label(self.root, text="时间范围:").grid(row=row, column=0, sticky="e", padx=5, pady=8)
        self.start_var = tk.StringVar(value=self.config.get("start_date", ""))
        tk.Entry(self.root, textvariable=self.start_var, width=15).grid(row=row, column=1, sticky="w", padx=5)
        tk.Label(self.root, text=" 至 ").grid(row=row, column=1, padx=5)
        self.end_var = tk.StringVar(value=self.config.get("end_date", ""))
        tk.Entry(self.root, textvariable=self.end_var, width=15).grid(row=row, column=1, sticky="e", padx=5)
        tk.Label(self.root, text="(YYYY-MM-DD)").grid(row=row, column=2, sticky="w")
        row += 1

        # 6. 其他参数
        tk.Label(self.root, text="每批保存数量:").grid(row=row, column=0, sticky="e", padx=5)
        self.batch_var = tk.IntVar(value=self.config.get("batch_size", 50))
        tk.Spinbox(self.root, from_=10, to=500, increment=10, textvariable=self.batch_var, width=10).grid(row=row, column=1, sticky="w")
        row += 1

        tk.Label(self.root, text="线程数:").grid(row=row, column=0, sticky="e", padx=5)
        self.thread_var = tk.IntVar(value=self.config.get("threads", 5))
        tk.Spinbox(self.root, from_=1, to=20, textvariable=self.thread_var, width=10).grid(row=row, column=1, sticky="w")
        row += 1

        # 7. 保存到数据库
        self.db_var = tk.BooleanVar(value=self.config.get("save_to_db", False))
        tk.Checkbutton(self.root, text="同时写入 MySQL 数据库", variable=self.db_var).grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=10)
        row += 1

        # 8. 开始按钮
        self.start_btn = tk.Button(self.root, text="开始采集", bg="green", fg="white", font=("Arial", 12, "bold"),
                                   command=self.start_crawl)
        self.start_btn.grid(row=row, column=0, columnspan=3, pady=15)

        # 9. 日志显示区
        self.log_text = tk.Text(self.root, height=12, state="disabled")
        self.log_text.grid(row=row+1, column=0, columnspan=3, sticky="nsew", padx=10, pady=5)
        self.root.grid_rowconfigure(row+1, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        # 重定向日志到界面
        class TextHandler(logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                self.append_log(msg + "\n")
        handler = TextHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        def append_log(msg):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        handler.append_log = append_log

    # ==================== UI 回调 ====================
    def browse_save_dir(self):
        dir_ = filedialog.askdirectory(initialdir=self.save_dir_var.get())
        if dir_:
            self.save_dir_var.set(dir_)

    def toggle_oauth(self):
        if self.oauth_var.get():
            self.oauth_frame.grid()
        else:
            self.oauth_frame.grid_remove()

    def add_subreddit(self):
        name = self.sub_var.get().strip().lower()
        if not name.startswith("r/"):
            name = "r/" + name.replace("r/", "")
        if not name[2:]:
            messagebox.showwarning("提示", "子版块名称不能为空")
            return

        # 检查是否存在
        for item in self.subreddits:
            if item["name"].lower() == name:
                messagebox.showinfo("提示", f"{name} 已存在")
                return

        desc = f"User added {name}"
        self.subreddits.append({"name": name, "description": desc})
        save_subreddits(self.subreddits)
        self.sub_combo["values"] = [item["name"] for item in self.subreddits]
        self.sub_combo.set(name)
        messagebox.showinfo("成功", f"已添加 {name}")

    def load_config_to_ui(self):
        self.save_dir_var.set(self.config.get("save_root", DEFAULT_CONFIG["save_root"]))
        self.sub_var.set(self.config.get("subreddit", "java"))
        self.oauth_var.set(self.config.get("use_oauth", False))
        self.cid_var.set(self.config.get("client_id", ""))
        self.csec_var.set(self.config.get("client_secret", ""))
        self.start_var.set(self.config.get("start_date", DEFAULT_CONFIG["start_date"]))
        self.end_var.set(self.config.get("end_date", DEFAULT_CONFIG["end_date"]))
        self.batch_var.set(self.config.get("batch_size", 50))
        self.thread_var.set(self.config.get("threads", 5))
        self.db_var.set(self.config.get("save_to_db", False))
        for k, var in self.type_vars.items():
            var.set(self.config["download_types"].get(k, True))
        self.toggle_oauth()

    def save_current_config(self):
        self.config.update({
            "save_root": self.save_dir_var.get(),
            "subreddit": self.sub_var.get().strip().replace("r/", ""),
            "use_oauth": self.oauth_var.get(),
            "client_id": self.cid_var.get().strip(),
            "client_secret": self.csec_var.get().strip(),
            "start_date": self.start_var.get().strip(),
            "end_date": self.end_var.get().strip(),
            "batch_size": self.batch_var.get(),
            "threads": self.thread_var.get(),
            "save_to_db": self.db_var.get(),
            "download_types": {k: v.get() for k, v in self.type_vars.items()}
        })
        save_config(self.config)

    def start_crawl(self):
        if not self.sub_var.get().strip():
            messagebox.showerror("错误", "请填写子版块")
            return
        self.save_current_config()
        self.start_btn.config(state="disabled", text="采集中...")
        threading.Thread(target=self.crawl_worker, daemon=True).start()

    # ==================== 核心采集逻辑 ====================
    def get_reddit_instance(self):
        if self.config["use_oauth"]:
            return praw.Reddit(
                client_id=self.config["client_id"],
                client_secret=self.config["client_secret"],
                user_agent=self.config["user_agent"]
            )
        else:
            # 游客模式
            return praw.Reddit(
                client_id="dummy",
                client_secret="dummy",
                user_agent="RedditCrawlerVisitor/1.0"
            )

    def crawl_worker(self):
        try:
            subreddit_name = self.config["subreddit"]
            save_root = Path(self.config["save_root"]) / subreddit_name
            save_root.mkdir(parents=True, exist_ok=True)

            reddit = self.get_reddit_instance()
            subreddit = reddit.subreddit(subreddit_name)

            start_ts = int(datetime.strptime(self.config["start_date"], "%Y-%m-%d").timestamp())
            end_ts = int((datetime.strptime(self.config["end_date"], "%Y-%m-%d") + timedelta(days=1)).timestamp())

            posts = []
            download_queue = Queue()
            total = 0

            def collector():
                nonlocal total
                for submission in subreddit.new(limit=None):
                    if submission.created_utc < start_ts:
                        continue
                    if submission.created_utc >= end_ts:
                        continue
                    posts.append(submission)
                    total += 1
                    if len(posts) >= self.config["batch_size"]:
                        self.save_batch(posts[:], save_root, download_queue)
                        posts.clear()
                if posts:
                    self.save_batch(posts, save_root, download_queue)
                download_queue.put(None)  # 结束信号

            def downloader():
                while True:
                    task = download_queue.get()
                    if task is None:
                        break
                    self.download_media(task["submission"], task["base_path"])

            # 启动下载线程
            for _ in range(self.config["threads"]):
                threading.Thread(target=downloader, daemon=True).start()

            # 开始采集
            collector_thread = threading.Thread(target=collector, daemon=True)
            collector_thread.start()
            collector_thread.join()

            download_queue.join()
            logger.info(f"采集完成，共处理 {total} 条帖子")
        except Exception as e:
            logger.exception(f"采集过程出错: {e}")
        finally:
            self.start_btn.config(state="normal", text="开始采集")

    def save_batch(self, batch, base_path: Path, download_queue: Queue):
        data_to_save = []
        for sub in batch:
            item = {
                "id": sub.id,
                "title": sub.title,
                "author": str(sub.author) if sub.author else "[deleted]",
                "created_utc": sub.created_utc,
                "score": sub.score,
                "num_comments": sub.num_comments,
                "permalink": f"https://reddit.com{sub.permalink}",
                "url": sub.url,
                "selftext": sub.selftext or "",
                "is_video": getattr(sub, "is_video", False),
                "media_type": None,
                "media_path": None
            }

            # 判断媒体类型
            if sub.is_self and self.config["download_types"]["selftext"]:
                item["media_type"] = "selftext"
            elif hasattr(sub, "is_gallery") and sub.is_gallery and self.config["download_types"]["gallery"]:
                item["media_type"] = "gallery"
            elif sub.url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and self.config["download_types"]["image"]:
                item["media_type"] = "image"
            elif getattr(sub, "is_video", False) and self.config["download_types"]["video"]:
                item["media_type"] = "video"
            elif sub.url.lower().endswith('.gif') and self.config["download_types"]["gif"]:
                item["media_type"] = "gif"
            elif any(sub.url.lower().endswith(ext) for ext in ('.pdf', '.doc', '.docx', '.txt')) and self.config["download_types"]["document"]:
                item["media_type"] = "document"

            if item["media_type"]:
                download_queue.put({"submission": sub, "base_path": base_path})

            data_to_save.append(item)

        # 保存 JSON
        json_path = base_path / f"posts_{int(time.time())}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)

        # 可选写入数据库
        if self.config["save_to_db"]:
            self.save_to_mysql(data_to_save)

    def download_media(self, submission, base_path: Path):
        try:
            url = submission.url
            ext = os.path.splitext(url)[1].split("?")[0] or ".jpg"
            filename = f"{submission.id}_{int(time.time())}{ext}"
            filepath = base_path / "media" / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)

            if getattr(submission, "is_video", False):
                video_url = submission.media["reddit_video"]["fallback_url"]
                r = requests.get(video_url, timeout=30)
                with open(filepath.with_suffix(".mp4"), "wb") as f:
                    f.write(r.content)
                filepath = filepath.with_suffix(".mp4")
            else:
                r = requests.get(url, timeout=30)
                with open(filepath, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            logger.error(f"下载失败 {submission.id}: {e}")

    def save_to_mysql(self, items):
        conn = get_db_connection()
        if not conn:
            return
        try:
            with conn.cursor() as cur:
                for it in items:
                    cur.execute("""
                        INSERT IGNORE INTO reddit_posts 
                        (id, subreddit, title, author, created_utc, url, selftext, score, num_comments, permalink, media_type, media_path)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        it["id"], self.config["subreddit"], it["title"], it["author"],
                        it["created_utc"], it["url"], it["selftext"], it["score"],
                        it["num_comments"], it["permalink"], it["media_type"], str(it.get("media_path"))
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"写入数据库失败: {e}")
        finally:
            conn.close()


if __name__ == "__main__":
    app = RedditCrawlerGUI()
    app.root.mainloop()
