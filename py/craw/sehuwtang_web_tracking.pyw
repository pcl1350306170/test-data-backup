import logging
import os
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import *
from tkinter import messagebox

import pymysql

import json

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "sehuwtang_web_tracking"
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
    "close_after_seconds": 5,
    "open_batch_size": 2,
    "batch_interval_seconds": 2  # 新增：批次间隔时间
}

# ==============================
# 数据库工具
# ==============================
def get_db_connection():
    if not DB_CONFIG_PATH.exists():
        raise FileNotFoundError(f"数据库配置文件不存在: {DB_CONFIG_PATH}")
    with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
        db_config = json.load(f)
    return pymysql.connect(**db_config)

def fetch_pending_urls(batch_size=2):
    """从 general_data 表中获取待加载的埋点链接"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        query = """
            SELECT id, data_key, data_content, data_type
            FROM general_data
            WHERE data_type LIKE %s
              AND is_deleted = 0
            ORDER BY id ASC
            LIMIT %s
        """

        cursor.execute(query, ('98T-小说%', batch_size))
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"数据库查询失败: {e}")
        raise

def mark_url_as_done(url_id):
    """将指定记录的 is_deleted 设为 1"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        update_query = "UPDATE general_data SET is_deleted = 1 WHERE id = %s"
        cursor.execute(update_query, (url_id,))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"已标记 ID={url_id} 为已完成")
    except Exception as e:
        logger.error(f"更新数据库失败 (ID={url_id}): {e}")
        raise

# ==============================
# 核心逻辑
# ==============================
def open_and_close_url(url, delay_seconds, url_id, on_complete_callback):
    """在默认浏览器中打开 URL，等待 N 秒后无法真正"关闭"，但可记录行为"""
    try:
        logger.info(f"正在打开: {url}")
        webbrowser.open(url)
        time.sleep(delay_seconds)
        # 注意：Python 无法强制关闭由 webbrowser 打开的浏览器标签/窗口
        # 但我们可以记录"已加载"，并更新数据库
        mark_url_as_done(url_id)
        on_complete_callback(url_id, True, None)
    except Exception as e:
        logger.error(f"处理 URL 失败 ({url}): {e}")
        on_complete_callback(url_id, False, str(e))

# ==============================
# GUI 主类
# ==============================
class WebTrackingTesterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🔍 98糖小说加载工具")
        self.root.geometry("520x420")
        self.root.resizable(False, False)
        self.running = False
        self.paused = False

        self.config = self.load_config()
        self.setup_ui()

    def load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    # 确保有默认字段
                    for k, v in DEFAULT_CONFIG.items():
                        if k not in cfg:
                            cfg[k] = v
                    return cfg
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def setup_ui(self):
        # 配置区
        frame_cfg = LabelFrame(self.root, text="⚙️ 加载配置", padx=10, pady=8)
        frame_cfg.pack(fill=X, padx=10, pady=5)

        # 关闭延迟
        row1 = Frame(frame_cfg)
        row1.pack(fill=X, pady=3)
        Label(row1, text="网页停留时间（秒）:", width=20, anchor=W).pack(side=LEFT)
        self.delay_var = StringVar(value=str(self.config.get("close_after_seconds", 5)))
        Spinbox(row1, from_=1, to=60, textvariable=self.delay_var, width=8).pack(side=LEFT)

        # 批量大小
        row2 = Frame(frame_cfg)
        row2.pack(fill=X, pady=3)
        Label(row2, text="每次打开网页数量:", width=20, anchor=W).pack(side=LEFT)
        self.batch_var = StringVar(value=str(self.config.get("open_batch_size", 2)))
        Spinbox(row2, from_=1, to=10, textvariable=self.batch_var, width=8).pack(side=LEFT)

        # 批次间隔时间
        row3 = Frame(frame_cfg)
        row3.pack(fill=X, pady=3)
        Label(row3, text="批次间隔时间（秒）:", width=20, anchor=W).pack(side=LEFT)
        self.interval_var = StringVar(value=str(self.config.get("batch_interval_seconds", 2)))
        Spinbox(row3, from_=1, to=60, textvariable=self.interval_var, width=8).pack(side=LEFT)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        self.start_btn = Button(btn_frame, text="▶️ 开始加载", command=self.start_test, bg="#4CAF50", fg="white", width=10, height=2)
        self.start_btn.pack(side=LEFT, padx=5)
        self.pause_btn = Button(btn_frame, text="⏸️ 暂停", command=self.pause_test, bg="#FF9800", fg="white", width=10, state=DISABLED)
        self.pause_btn.pack(side=LEFT, padx=5)
        self.resume_btn = Button(btn_frame, text="⏯️ 恢复", command=self.resume_test, bg="#2196F3", fg="white", width=10, state=DISABLED)
        self.resume_btn.pack(side=LEFT, padx=5)
        self.stop_btn = Button(btn_frame, text="⏹️ 停止", command=self.stop_test, bg="#f44336", fg="white", width=10, state=DISABLED)
        self.stop_btn.pack(side=LEFT, padx=5)

        # 进度显示
        progress_frame = LabelFrame(self.root, text="📊 进度信息", padx=5, pady=5)
        progress_frame.pack(fill=X, padx=10, pady=5)
        self.progress_var = StringVar(value="等待开始加载...")
        self.progress_label = Label(progress_frame, textvariable=self.progress_var, anchor=W, fg="black")
        self.progress_label.pack(fill=X, padx=5, pady=5)

        # 日志显示
        log_frame = LabelFrame(self.root, text="📋 操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.log_text = Text(log_frame, height=8, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_bar = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_bar.pack(side=BOTTOM, fill=X)

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def start_test(self):
        if self.running:
            return

        # 保存配置
        try:
            delay_sec = int(self.delay_var.get())
            batch_size = int(self.batch_var.get())
            interval_sec = int(self.interval_var.get())
            if delay_sec < 1 or batch_size < 1 or interval_sec < 1:
                raise ValueError("参数必须大于0")
            self.config["close_after_seconds"] = delay_sec
            self.config["open_batch_size"] = batch_size
            self.config["batch_interval_seconds"] = interval_sec
            self.save_config()
        except Exception as e:
            messagebox.showerror("配置错误", f"参数无效: {e}")
            return

        # 启动后台线程
        self.running = True
        self.paused = False
        self.start_btn.config(state=DISABLED)
        self.pause_btn.config(state=NORMAL)
        self.resume_btn.config(state=DISABLED)
        self.stop_btn.config(state=NORMAL)
        self.status_var.set("正在获取待测链接...")
        self.log_to_gui("开始加载...")

        thread = threading.Thread(target=self.run_test_cycle, daemon=True)
        thread.start()

    def pause_test(self):
        if self.running and not self.paused:
            self.paused = True
            self.pause_btn.config(state=DISABLED)
            self.resume_btn.config(state=NORMAL)
            self.status_var.set("已暂停")
            self.log_to_gui("加载已暂停。")

    def resume_test(self):
        if self.running and self.paused:
            self.paused = False
            self.pause_btn.config(state=NORMAL)
            self.resume_btn.config(state=DISABLED)
            self.status_var.set("正在运行...")
            self.log_to_gui("加载已恢复。")

    def stop_test(self):
        self.running = False
        self.paused = False
        self.status_var.set("用户已停止")
        self.log_to_gui("用户手动停止加载。")
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.resume_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)

    def run_test_cycle(self):
        try:
            total_processed = 0  # 定义在函数作用域内，用于记录已处理的总数
            total_urls = 0

            # 首先统计总共有多少待处理的URL
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                count_query = """
                    SELECT COUNT(*) as count
                    FROM general_data
                    WHERE data_type LIKE %s
                      AND is_deleted = 0
                """
                cursor.execute(count_query, ('98T-小说%',))
                result = cursor.fetchone()
                total_urls = result[0] if result else 0
                cursor.close()
                conn.close()
                self.progress_var.set(f"总待处理: {total_urls} 个链接")
            except Exception as e:
                logger.error(f"统计总链接数失败: {e}")
                self.progress_var.set("统计总链接数失败")

            while self.running:
                # 检查是否暂停
                while self.paused and self.running:
                    time.sleep(0.1)

                if not self.running:
                    break

                urls = fetch_pending_urls(self.config["open_batch_size"])
                if not urls:
                    self.log_to_gui("✅ 所有待加载的埋点链接已处理完毕！")
                    break

                self.log_to_gui(f"当前批次获取 {len(urls)} 个待测链接，即将打开...")
                self.status_var.set(f"正在处理批次...")

                threads = []
                completed = [0]
                total = len(urls)

                # 定义回调函数，使用nonlocal关键字来访问外层函数的变量
                def on_url_done(url_id, success, error_msg):
                    nonlocal total_processed  # 使用nonlocal来访问外层函数的total_processed变量
                    completed[0] += 1
                    total_processed += 1  # 更新已处理总数
                    if success:
                        self.log_to_gui(f"✅ 已完成加载 (ID={url_id})")
                    else:
                        self.log_to_gui(f"❌ 加载失败 (ID={url_id}): {error_msg}")

                    # 更新进度信息
                    self.progress_var.set(f"已处理: {total_processed}/{total_urls} 个链接")

                delay = self.config["close_after_seconds"]
                for item in urls:
                    if not self.running:
                        break
                    t = threading.Thread(
                        target=open_and_close_url,
                        args=(item['data_content'], delay, item['id'], on_url_done),
                        daemon=True
                    )
                    threads.append(t)
                    t.start()
                    time.sleep(0.2)  # 同一批次内打开URL的间隔

                # 等待当前批次完成
                while completed[0] < total and self.running:
                    time.sleep(0.1)

                # 如果还有更多URL待处理，等待批次间隔时间
                remaining_count_query = """
                    SELECT COUNT(*) as count
                    FROM general_data
                    WHERE data_type LIKE %s
                      AND is_deleted = 0
                """
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(remaining_count_query, ('98T-小说%',))
                    remaining_result = cursor.fetchone()
                    remaining_count = remaining_result[0] if remaining_result else 0
                    cursor.close()
                    conn.close()

                    if remaining_count > 0 and self.running and not self.paused:
                        self.log_to_gui(f"当前批次完成，等待 {self.config['batch_interval_seconds']} 秒后继续...")
                        time.sleep(self.config["batch_interval_seconds"])
                except Exception as e:
                    logger.error(f"查询剩余链接数失败: {e}")

            self.finish_run()

        except Exception as e:
            self.log_to_gui(f"❌ 启动加载失败: {e}")
            logger.exception("启动加载异常")
            self.root.after(0, self.finish_run)

    def finish_run(self):
        self.running = False
        self.paused = False
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.resume_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)
        self.status_var.set("加载完成")
        self.log_to_gui("所有加载完成。")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = WebTrackingTesterGUI(root)
    root.mainloop()
