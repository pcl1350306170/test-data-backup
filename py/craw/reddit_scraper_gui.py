# reddit_scraper_gui.py
"""
Reddit 子版块抓取器（tkinter GUI）
功能：
 - GUI 可选择保存目录、填写子版块、选择文件类型、时间段、批次、线程数
 - 将配置写入脚本目录的 json/config_<SCRIPT_NAME>.json（绝对路径）
 - 支持 PRAW（OAuth）或匿名抓取（从 reddit JSON 页面）
 - 多线程下载媒体并批量持久化元数据
 - 可选写入数据库（使用 DB_CONFIG.json，在脚本父目录的 json 文件夹内）
 - 日志写入 PROCESS_LOG_FILE
"""
import os
import json
import threading
import logging
import queue
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import Tk, Label, Entry, Button, StringVar, IntVar, BooleanVar, Checkbutton, filedialog, ttk, messagebox, Frame
import requests
from urllib.parse import urlparse
from dateutil import parser as date_parser
from tqdm import tqdm

# 尝试导入可选库
try:
    import praw
    HAS_PRAW = True
except Exception:
    HAS_PRAW = False

try:
    import pymysql
    HAS_PYMYSQL = True
except Exception:
    HAS_PYMYSQL = False

# -------------------- 配置与常量（按你给出的示例） --------------------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "reddit_scraper_gui"  # 脚本名称，可以修改
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
PROCESS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 默认保存目录（可以被 GUI 修改）
DEFAULT_SAVE_DIR = Path(r"G:\下载\Reddit\java")

# 日志配置
logging.basicConfig(
    filename=str(PROCESS_LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)
logger = logging.getLogger("reddit_scraper")
logger.addHandler(logging.StreamHandler())  # 终端也打印

# -------------------- 帮助函数 --------------------
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            logger.info(f"加载配置：{CONFIG_PATH}")
            return cfg
        except Exception as e:
            logger.exception("读取配置失败，使用默认配置")
    # 默认配置结构
    default = {
        "save_dir": str(DEFAULT_SAVE_DIR),
        "subreddit": "r/java",
        "use_praw": False,
        "praw": {"client_id": "", "client_secret": "", "user_agent": "reddit_scraper"},
        "download_types": {"images": True, "videos": True, "gifs": True, "documents": True},
        "start_date": "",  # yyyy-mm-dd
        "end_date": "",    # yyyy-mm-dd
        "batch_size": 50,
        "threads": 5,
        "write_to_db": False,
        "db_config_path": str(DB_CONFIG_PATH),
        "last_run": ""
    }
    return default

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存配置到 {CONFIG_PATH}")

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def safe_filename_from_url(url: str):
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name:
        name = parsed.netloc
    # 防止重复或非法字符
    name = name.split("?")[0]
    return name

def url_is_media(url: str, allow_images=True, allow_videos=True, allow_gifs=True, allow_docs=True):
    url = url.lower()
    # 简单扩展名判断
    extensions_img = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
    extensions_vid = (".mp4", ".mov", ".m4v", ".mkv", ".webm")
    extensions_gif = (".gif", ".gifv")
    extensions_doc = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md")

    if allow_images and url.endswith(extensions_img):
        return True
    if allow_videos and url.endswith(extensions_vid):
        return True
    if allow_gifs and url.endswith(extensions_gif):
        return True
    if allow_docs and url.endswith(extensions_doc):
        return True
    # 一些外部托管站点（imgur, gfycat 等）需要特殊处理，下面仅作基础支持
    if allow_images and ("i.imgur.com" in url or "imgur.com" in url):
        return True
    if (allow_videos or allow_gifs) and ("gfycat.com" in url or "v.redd.it" in url):
        return True
    return False

# -------------------- Reddit 抓取实现 --------------------
class RedditFetcher:
    def __init__(self, config):
        self.config = config
        self.use_praw = config.get("use_praw", False) and HAS_PRAW and config.get("praw", {}).get("client_id")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.get("praw", {}).get("user_agent", "reddit_scraper/0.1")})

        if self.use_praw:
            try:
                self.reddit = praw.Reddit(
                    client_id=config["praw"]["client_id"],
                    client_secret=config["praw"]["client_secret"],
                    user_agent=config["praw"]["user_agent"],
                    check_for_async=False
                )
                logger.info("使用 PRAW 连接 Reddit")
            except Exception as e:
                logger.exception("PRAW 初始化失败，回退到匿名抓取")
                self.use_praw = False
                self.reddit = None
        else:
            self.reddit = None

    def fetch_posts(self, subreddit: str, start_date: str, end_date: str, limit=None):
        """
        返回帖子元数据的生成器（字典列表）
        如果配置了 PRAW 则使用 PRAW（可以分页获取较多数据），否则使用匿名 reddit JSON（受限）
        start_date/end_date: 'YYYY-MM-DD' 或空
        """
        logger.info(f"开始抓取：{subreddit} 时间: {start_date} - {end_date} limit={limit}")
        start_ts = None
        end_ts = None
        if start_date:
            start_ts = int(date_parser.parse(start_date).timestamp())
        if end_date:
            # 含当天，设为当天 23:59:59
            d = date_parser.parse(end_date)
            d_end = datetime(d.year, d.month, d.day, 23, 59, 59)
            end_ts = int(d_end.timestamp())

        if self.use_praw and self.reddit:
            # 使用 PRAW：可以遍历 subreddit.new() 或 .top(time_filter)
            subname = subreddit.replace("r/", "").strip()
            try:
                subreddit_obj = self.reddit.subreddit(subname)
                # 这里我们用 .new() 并自己筛选时间
                count = 0
                for submission in subreddit_obj.new(limit=None):
                    created = int(submission.created_utc)
                    if start_ts and created < start_ts:
                        continue
                    if end_ts and created > end_ts:
                        continue
                    post = {
                        "id": submission.id,
                        "title": submission.title,
                        "url": submission.url,
                        "created_utc": submission.created_utc,
                        "is_video": submission.is_video,
                        "media": getattr(submission, "media", None),
                        "preview": getattr(submission, "preview", None),
                        "num_comments": submission.num_comments,
                        "score": submission.score,
                        "permalink": submission.permalink,
                        "author": str(submission.author)
                    }
                    yield post
                    count += 1
                    if limit and count >= limit:
                        break
            except Exception as e:
                logger.exception("PRAW 抓取出错")
                return
        else:
            # 匿名抓取 reddit JSON（一次最多 100 条，分页使用 after）
            # 注意：此方法可能被 Reddit 限速或返回 429，实际用 PRAW 更稳
            subname = subreddit.replace("r/", "").strip()
            after = None
            total = 0
            while True:
                url = f"https://www.reddit.com/r/{subname}/new.json"
                params = {"limit": 100}
                if after:
                    params["after"] = after
                try:
                    resp = self.session.get(url, params=params, timeout=30)
                    if resp.status_code == 429:
                        logger.warning("被 Reddit 限速 429，暂停 10s")
                        import time; time.sleep(10)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.exception("匿名抓取 reddit JSON 出错或达到限制")
                    break
                children = data.get("data", {}).get("children", [])
                if not children:
                    break
                for child in children:
                    d = child.get("data", {})
                    created = d.get("created_utc")
                    if start_ts and created < start_ts:
                        continue
                    if end_ts and created > end_ts:
                        continue
                    post = {
                        "id": d.get("id"),
                        "title": d.get("title"),
                        "url": d.get("url"),
                        "created_utc": d.get("created_utc"),
                        "is_video": d.get("is_video"),
                        "media": d.get("media"),
                        "preview": d.get("preview"),
                        "num_comments": d.get("num_comments"),
                        "score": d.get("score"),
                        "permalink": d.get("permalink"),
                        "author": d.get("author")
                    }
                    yield post
                    total += 1
                    if limit and total >= limit:
                        return
                after = data.get("data", {}).get("after")
                if not after:
                    break

# -------------------- 下载与持久化 --------------------
class Downloader:
    def __init__(self, config, save_dir: Path, db_config=None):
        self.config = config
        self.save_dir = Path(save_dir)
        ensure_dir(self.save_dir)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.get("praw", {}).get("user_agent", "reddit_scraper/0.1")})
        self.batch = []
        self.batch_size = int(config.get("batch_size", 50))
        self.lock = threading.Lock()
        self.db_config = db_config
        self.db_conn = None
        if db_config and HAS_PYMYSQL:
            try:
                self.db_conn = pymysql.connect(
                    host=db_config["host"],
                    port=int(db_config.get("port", 3306)),
                    user=db_config["user"],
                    password=db_config["password"],
                    database=db_config["database"],
                    charset=db_config.get("charset", "utf8mb4"),
                    autocommit=True
                )
                logger.info("数据库连接已建立")
            except Exception:
                logger.exception("数据库连接失败，继续离线模式")
                self.db_conn = None

    def close(self):
        if self.db_conn:
            self.db_conn.close()

    def download_media(self, post):
        """从帖子中识别媒体 URL 并下载，返回元数据记录（包含本地路径）"""
        url = post.get("url") or ""
        preview = post.get("preview")
        media = post.get("media")
        results = []
        allow = self.config.get("download_types", {})
        allow_images = allow.get("images", True)
        allow_videos = allow.get("videos", True)
        allow_gifs = allow.get("gifs", True)
        allow_docs = allow.get("documents", True)

        candidate_urls = set()
        # 1) 直接 url
        if url and url_is_media(url, allow_images, allow_videos, allow_gifs, allow_docs):
            candidate_urls.add(url)
        # 2) preview.images
        if isinstance(preview, dict):
            imgs = preview.get("images", [])
            for im in imgs:
                src = im.get("source", {}).get("url")
                if src:
                    candidate_urls.add(src.replace("&amp;", "&"))
        # 3) media reddit video
        if isinstance(media, dict):
            reddit_video = media.get("reddit_video")
            if reddit_video:
                dash_url = reddit_video.get("fallback_url")
                if dash_url:
                    candidate_urls.add(dash_url)
        # 4) gfycat/imgur 等处理（简要）
        if "gfycat.com" in url:
            # gfycat 原始 gif/video 链接可能需转换，但这里尝试直接下载 url + .mp4
            candidate_urls.add(url + ".mp4")
        # 5) imgur 链接
        if "imgur.com" in url and not url.endswith((".jpg", ".png", ".gif")):
            candidate_urls.add(url + ".jpg")
            candidate_urls.add(url + ".png")

        # 下载候选
        for murl in candidate_urls:
            try:
                r = self.session.get(murl, stream=True, timeout=30)
                if r.status_code == 200:
                    fname = safe_filename_from_url(murl)
                    # 加个前缀：postid_title
                    safe_title = "".join(ch for ch in post.get("title", "") if ch.isalnum() or ch in (" ", "_", "-"))[:50].strip()
                    prefix = f"{post.get('id')}_{safe_title}" if safe_title else post.get("id")
                    save_name = f"{prefix}_{fname}"
                    out_path = self.save_dir / save_name
                    # 若已存在则跳过或改名
                    if out_path.exists():
                        # 添加数字后缀
                        i = 1
                        while True:
                            alt = out_path.with_name(f"{out_path.stem}_{i}{out_path.suffix}")
                            if not alt.exists():
                                out_path = alt
                                break
                            i += 1
                    with open(out_path, "wb") as wf:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                wf.write(chunk)
                    logger.info(f"已下载：{murl} -> {out_path}")
                    results.append({"url": murl, "local_path": str(out_path), "post_id": post.get("id")})
                else:
                    logger.warning(f"下载失败 {murl} 状态码 {r.status_code}")
            except Exception:
                logger.exception(f"下载异常：{murl}")
        return results

    def persist_batch(self, batch_records):
        # 写入本地 JSON 文件（以时间戳命名追加）
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        meta_file = self.save_dir / f"meta_batch_{now}.json"
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(batch_records, f, ensure_ascii=False, indent=2)
            logger.info(f"批次元数据已写入 {meta_file}")
        except Exception:
            logger.exception("写入元数据失败")

        # 可选：写入数据库（简单示例，需根据实际表结构修改）
        if self.db_conn:
            try:
                with self.db_conn.cursor() as cur:
                    for rec in batch_records:
                        # 假设表名为 reddit_posts，字段 (post_id, title, url, local_paths_json, created_utc)
                        sql = "INSERT INTO reddit_posts (post_id, title, url, local_paths_json, created_utc) VALUES (%s,%s,%s,%s,%s)"
                        local_paths = [x.get("local_path") for x in rec.get("media_saved", [])]
                        cur.execute(sql, (
                            rec.get("id"),
                            rec.get("title")[:255] if rec.get("title") else None,
                            rec.get("url"),
                            json.dumps(local_paths, ensure_ascii=False),
                            datetime.utcfromtimestamp(int(rec.get("created_utc"))) if rec.get("created_utc") else None
                        ))
                logger.info("已写入数据库（批次）")
            except Exception:
                logger.exception("写入数据库失败")

    def add_record_and_check_flush(self, record):
        with self.lock:
            self.batch.append(record)
            if len(self.batch) >= self.batch_size:
                to_write = self.batch[:]
                self.batch = []
                # 持久化
                try:
                    self.persist_batch(to_write)
                except Exception:
                    logger.exception("批次持久化出错")

# -------------------- GUI 与 主流程 --------------------
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Reddit 子版块抓取器")
        self.cfg = load_config()

        # TK variables
        self.save_dir_var = StringVar(value=self.cfg.get("save_dir"))
        self.subreddit_var = StringVar(value=self.cfg.get("subreddit"))
        self.batch_var = IntVar(value=self.cfg.get("batch_size", 50))
        self.threads_var = IntVar(value=self.cfg.get("threads", 5))
        self.use_praw_var = BooleanVar(value=self.cfg.get("use_praw", False))
        self.write_db_var = BooleanVar(value=self.cfg.get("write_to_db", False))
        self.start_date_var = StringVar(value=self.cfg.get("start_date", ""))
        self.end_date_var = StringVar(value=self.cfg.get("end_date", ""))

        # download types
        dt = self.cfg.get("download_types", {})
        self.images_var = BooleanVar(value=dt.get("images", True))
        self.videos_var = BooleanVar(value=dt.get("videos", True))
        self.gifs_var = BooleanVar(value=dt.get("gifs", True))
        self.docs_var = BooleanVar(value=dt.get("documents", True))

        # build GUI
        self._build()

        # runtime control
        self._stop_event = threading.Event()
        self._worker_thread = None

    def _build(self):
        row = 0
        Label(self.root, text="保存目录:").grid(row=row, column=0, sticky="w", padx=6, pady=6)
        Entry(self.root, textvariable=self.save_dir_var, width=50).grid(row=row, column=1, sticky="w")
        Button(self.root, text="选择...", command=self.choose_dir).grid(row=row, column=2, padx=6)
        row += 1

        Label(self.root, text="子版块 (例如 r/java 或 java):").grid(row=row, column=0, sticky="w", padx=6, pady=6)
        Entry(self.root, textvariable=self.subreddit_var, width=30).grid(row=row, column=1, sticky="w")
        row += 1

        Label(self.root, text="抓取时间段 (YYYY-MM-DD):").grid(row=row, column=0, sticky="w", padx=6, pady=6)
        Entry(self.root, textvariable=self.start_date_var, width=12).grid(row=row, column=1, sticky="w")
        Entry(self.root, textvariable=self.end_date_var, width=12).grid(row=row, column=1, sticky="e")
        row += 1

        # 下载类型
        Label(self.root, text="下载类型:").grid(row=row, column=0, sticky="w", padx=6, pady=6)
        FrameBox = Frame(self.root)
        FrameBox.grid(row=row, column=1, sticky="w")
        Checkbutton(FrameBox, text="图片", variable=self.images_var).pack(side="left")
        Checkbutton(FrameBox, text="视频", variable=self.videos_var).pack(side="left")
        Checkbutton(FrameBox, text="GIF", variable=self.gifs_var).pack(side="left")
        Checkbutton(FrameBox, text="文档", variable=self.docs_var).pack(side="left")
        row += 1

        Label(self.root, text="每批保存条数:").grid(row=row, column=0, sticky="w", padx=6, pady=6)
        Entry(self.root, textvariable=self.batch_var, width=8).grid(row=row, column=1, sticky="w")
        Label(self.root, text="多线程数量:").grid(row=row, column=1, sticky="e")
        Entry(self.root, textvariable=self.threads_var, width=6).grid(row=row, column=2, sticky="w")
        row += 1

        Checkbutton(self.root, text="使用 PRAW（需在配置中填写 client_id 等）", variable=self.use_praw_var).grid(row=row, column=0, columnspan=3, sticky="w", padx=6)
        row += 1
        Checkbutton(self.root, text="写入数据库（需在脚本父目录/json/DB_CONFIG.json 提供 DB 配置）", variable=self.write_db_var).grid(row=row, column=0, columnspan=3, sticky="w", padx=6)
        row += 1

        # Buttons
        Button(self.root, text="保存配置", command=self.on_save_config).grid(row=row, column=0, padx=6, pady=10)
        Button(self.root, text="开始抓取", command=self.on_start).grid(row=row, column=1, padx=6)
        Button(self.root, text="停止", command=self.on_stop).grid(row=row, column=2, padx=6)
        row += 1

        # progress
        self.progress = ttk.Progressbar(self.root, mode="determinate", length=500)
        self.progress.grid(row=row, column=0, columnspan=3, padx=6, pady=6)
        row += 1

        # status label
        self.status_var = StringVar(value="Ready")
        Label(self.root, textvariable=self.status_var).grid(row=row, column=0, columnspan=3, sticky="w", padx=6)

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.save_dir_var.get() or os.getcwd())
        if d:
            self.save_dir_var.set(d)

    def on_save_config(self):
        cfg = {
            "save_dir": self.save_dir_var.get(),
            "subreddit": self.subreddit_var.get(),
            "use_praw": self.use_praw_var.get(),
            "praw": self.cfg.get("praw", {}),
            "download_types": {
                "images": self.images_var.get(),
                "videos": self.videos_var.get(),
                "gifs": self.gifs_var.get(),
                "documents": self.docs_var.get()
            },
            "start_date": self.start_date_var.get(),
            "end_date": self.end_date_var.get(),
            "batch_size": int(self.batch_var.get()),
            "threads": int(self.threads_var.get()),
            "write_to_db": self.write_db_var.get(),
            "db_config_path": str(DB_CONFIG_PATH),
            "last_run": ""
        }
        # 如果使用 PRAW，需要把 praw 子项写入（会保留已有）
        if "praw" in self.cfg:
            cfg["praw"].update(self.cfg.get("praw", {}))
        save_config(cfg)
        self.cfg = cfg
        messagebox.showinfo("配置", "配置已保存")

    def on_start(self):
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showwarning("进行中", "已有抓取任务正在运行")
            return
        # update cfg
        self.on_save_config()
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self.worker_main, daemon=True)
        self._worker_thread.start()

    def on_stop(self):
        self._stop_event.set()
        self.status_var.set("停止中...")

    def worker_main(self):
        cfg = load_config()
        # 更新最后运行时间
        cfg["last_run"] = datetime.now().isoformat()
        save_config(cfg)

        save_dir = Path(cfg.get("save_dir") or DEFAULT_SAVE_DIR)
        ensure_dir(save_dir)

        # DB config
        db_cfg = None
        if cfg.get("write_to_db"):
            # 读取 DB_CONFIG_PATH
            dbp = Path(cfg.get("db_config_path") or DB_CONFIG_PATH)
            if dbp.exists():
                try:
                    with open(dbp, "r", encoding="utf-8") as f:
                        db_cfg = json.load(f)
                        logger.info(f"读取数据库配置：{dbp}")
                except Exception:
                    logger.exception("读取 DB 配置失败")
            else:
                logger.warning(f"未找到 DB_CONFIG.json：{dbp}. 将以离线模式运行。")

        fetcher = RedditFetcher(cfg)
        downloader = Downloader(cfg, save_dir, db_cfg)

        sub = cfg.get("subreddit", "r/java")
        start = cfg.get("start_date", "")
        end = cfg.get("end_date", "")
        threads = int(cfg.get("threads", 5))
        batch_size = int(cfg.get("batch_size", 50))
        total_processed = 0

        # 我们先把要抓取的帖子收集到 list（逐条下载），也可以边抓边下载（这里为简洁先收集再下载）
        post_generator = fetcher.fetch_posts(sub, start, end, limit=None)

        # 为了显示 progress，我们尽量统计但匿名抓取无法得知总数，故 progress 设置为不确定模式
        self.progress.config(mode="indeterminate")
        self.progress.start(10)
        self.status_var.set("抓取帖子中...（progress 不确定，若使用 PRAW 则可稳定）")
        posts = []
        try:
            for p in post_generator:
                posts.append(p)
                if self._stop_event.is_set():
                    logger.info("检测到停止信号，退出抓取循环")
                    break
        except Exception:
            logger.exception("抓取期间发生异常")
        finally:
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)

        if not posts:
            self.status_var.set("未抓取到任何帖子或已停止")
            downloader.close()
            return

        # 多线程下载媒体
        self.status_var.set(f"开始下载媒体，共 {len(posts)} 帖子，使用 {threads} 线程")
        self.progress.config(maximum=len(posts), value=0)
        self.progress.config(mode="determinate")
        futures = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            for post in posts:
                if self._stop_event.is_set():
                    break
                futures.append(executor.submit(self._process_post, downloader, post))
            # 遍历完成
            for fut in as_completed(futures):
                if self._stop_event.is_set():
                    break
                try:
                    rec = fut.result()
                    total_processed += 1
                    self.progress.step(1)
                    self.status_var.set(f"已处理 {total_processed}/{len(posts)}")
                except Exception:
                    logger.exception("任务执行异常")
        # 最后 flush 剩余 batch
        if downloader.batch:
            try:
                downloader.persist_batch(downloader.batch)
            except Exception:
                logger.exception("最后批次持久化失败")
        downloader.close()
        self.status_var.set(f"完成，共处理 {total_processed} 帖子")
        logger.info("任务完成")

    def _process_post(self, downloader: Downloader, post):
        # 下载媒体
        media_saved = downloader.download_media(post)
        rec = {
            "id": post.get("id"),
            "title": post.get("title"),
            "url": post.get("url"),
            "created_utc": post.get("created_utc"),
            "media_saved": media_saved,
            "fetched_at": datetime.now().isoformat()
        }
        # 批量持久化控制
        downloader.add_record_and_check_flush(rec)
        return rec

# -------------------- 启动 --------------------
def main():
    root = Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
