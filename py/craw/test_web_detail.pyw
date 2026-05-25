import logging
import os
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import *
from tkinter import messagebox, ttk

import pymysql
import json

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "device_stress_test"
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
    "DB_HOST": "localhost",
    "DB_PORT": 3306,
    "DB_USER": "root",
    "DB_PASSWORD": "",
    "DB_NAME": "test",
    "close_after_seconds": 5,  # 保留但不在UI显示
    "open_batch_size": 2,
    "batch_interval_seconds": 2,
    "url_open_interval": 1.0,  # 同一批次内打开URL的间隔（秒）
    "url_suffix": "",  # URL后缀参数
    "data_type_filter": "V33-IMG-AI"  # data_type过滤条件
}

# ==============================
# 数据库工具
# ==============================
def get_db_connection(db_config=None):
    """获取数据库连接"""
    if db_config is None:
        # 如果没有传入配置，从配置文件读取
        if not DB_CONFIG_PATH.exists():
            raise FileNotFoundError(f"数据库配置文件不存在: {DB_CONFIG_PATH}")
        with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
            db_config = json.load(f)
    
    try:
        return pymysql.connect(
            host=db_config.get("DB_HOST", "localhost"),
            port=int(db_config.get("DB_PORT", 3306)),
            user=db_config.get("DB_USER", "root"),
            password=db_config.get("DB_PASSWORD", ""),
            database=db_config.get("DB_NAME", "test"),
            charset="utf8mb4"
        )
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        raise

def fetch_pending_urls(batch_size=2, data_type_filter="V33-IMG-AI", db_config=None):
    """从 general_data 表中获取待加载的链接"""
    try:
        conn = get_db_connection(db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        query = """
            SELECT id, data_key, data_content, data_type
            FROM general_data
            WHERE data_type LIKE %s
              AND is_deleted = 0
            ORDER BY id ASC
            LIMIT %s
        """
        cursor.execute(query, (data_type_filter, batch_size))
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return results
    except Exception as e:
        logger.error(f"数据库查询失败: {e}")
        raise

def check_urls_completed(url_ids, db_config=None):
    """检查指定ID列表的URL是否都已标记为完成(is_deleted = 1)
    
    Returns:
        tuple: (是否全部完成, 未完成的ID列表)
    """
    if not url_ids:
        return True, []
    
    try:
        conn = get_db_connection(db_config)
        cursor = conn.cursor()
        
        # 构建查询：查找这些ID中 is_deleted = 0 的记录
        placeholders = ','.join(['%s'] * len(url_ids))
        query = f"""
            SELECT id
            FROM general_data
            WHERE id IN ({placeholders})
              AND is_deleted = 0
        """
        cursor.execute(query, tuple(url_ids))
        incomplete_ids = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return len(incomplete_ids) == 0, incomplete_ids
    except Exception as e:
        logger.error(f"检查URL完成状态失败: {e}")
        return False, url_ids  # 出错时返回所有ID未完成

def mark_url_as_completed(url_id, db_config=None):
    """手动将URL标记为已完成(is_deleted = 1)
    
    Args:
        url_id: 数据ID
        db_config: 数据库配置
        
    Returns:
        bool: 是否成功
    """
    try:
        conn = get_db_connection(db_config)
        cursor = conn.cursor()
        
        update_query = """
            UPDATE general_data
            SET is_deleted = 1
            WHERE id = %s
        """
        cursor.execute(update_query, (url_id,))
        conn.commit()
        
        affected_rows = cursor.rowcount
        cursor.close()
        conn.close()
        
        if affected_rows > 0:
            logger.info(f"手动标记 ID={url_id} 为已完成")
            return True
        else:
            logger.warning(f"标记 ID={url_id} 失败：记录不存在或已被标记")
            return False
            
    except Exception as e:
        logger.error(f"手动标记 ID={url_id} 失败: {e}")
        return False

# ==============================
# 核心逻辑
# ==============================
def build_url_with_suffix(base_url, suffix, general_data_id=None, source=None):
    """在URL后面拼接自定义后缀、generalDataId和source参数"""
    params = []
    
    # 添加自定义后缀
    if suffix:
        suffix = suffix.strip()
        params.append(suffix)
    
    # 添加 generalDataId 参数
    if general_data_id is not None:
        params.append(f"generalDataId={general_data_id}")
    
    # 添加 source 参数（来自 data_type 字段）
    if source:
        source = source.strip()
        params.append(f"source={source}")
    
    # 如果没有参数，直接返回原URL
    if not params:
        return base_url
    
    # 拼接所有参数
    combined_params = "&".join(params)
    
    # 如果base_url已经有参数，使用&连接；否则使用?连接
    if '?' in base_url:
        return f"{base_url}&{combined_params}"
    else:
        return f"{base_url}?{combined_params}"

def open_and_close_url(url, delay_seconds, url_id, on_complete_callback):
    """在默认浏览器中打开 URL，等待 N 秒后记录行为（不修改数据库状态）"""
    try:
        logger.info(f"正在打开: {url}")
        
        # 尝试打开浏览器
        result = webbrowser.open(url)
        
        if not result:
            logger.warning(f"⚠️ webbrowser.open() 返回 False，可能无法打开浏览器")
            logger.warning(f"请检查：")
            logger.warning(f"  1. 系统是否安装了默认浏览器")
            logger.warning(f"  2. 默认浏览器是否可以正常启动")
            logger.warning(f"  3. URL 格式是否正确: {url}")
        else:
            logger.info(f"✅ 已调用浏览器打开 URL")
        
        time.sleep(delay_seconds)
        # 注意：不再修改数据库状态，由浏览器端监听脚本负责
        logger.info(f"已加载完成 (ID={url_id})，等待浏览器端处理")
        on_complete_callback(url_id, True, None)
    except Exception as e:
        logger.error(f"❌ 处理 URL 失败 ({url}): {e}")
        logger.error(f"可能的原因：")
        logger.error(f"  1. 系统未安装浏览器")
        logger.error(f"  2. 默认浏览器损坏或被卸载")
        logger.error(f"  3. 权限不足或被安全软件阻止")
        logger.error(f"  4. URL 格式错误")
        on_complete_callback(url_id, False, str(e))

# ==============================
# GUI 主类
# ==============================
class DeviceStressTestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🔥 设备极限压力测试工具")
        self.root.geometry("550x680")
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
        frame_cfg = LabelFrame(self.root, text="⚙️ 测试配置", padx=10, pady=8)
        frame_cfg.pack(fill=X, padx=10, pady=5)

        # === 数据库配置 ===
        db_frame = LabelFrame(frame_cfg, text="数据库配置", padx=5, pady=5)
        db_frame.pack(fill=X, pady=5)

        # 主机
        row_db1 = Frame(db_frame)
        row_db1.pack(fill=X, pady=2)
        Label(row_db1, text="主机:", width=10, anchor=W).pack(side=LEFT)
        self.db_host_var = StringVar(value=self.config.get("DB_HOST", "localhost"))
        Entry(row_db1, textvariable=self.db_host_var, width=20).pack(side=LEFT, padx=5)
        Label(row_db1, text="(IP或域名)", foreground="gray", font=("Arial", 8)).pack(side=LEFT)

        # 端口
        row_db2 = Frame(db_frame)
        row_db2.pack(fill=X, pady=2)
        Label(row_db2, text="端口:", width=10, anchor=W).pack(side=LEFT)
        self.db_port_var = StringVar(value=str(self.config.get("DB_PORT", 3306)))
        Spinbox(row_db2, from_=1, to=65535, textvariable=self.db_port_var, width=10).pack(side=LEFT, padx=5)

        # 用户名
        row_db3 = Frame(db_frame)
        row_db3.pack(fill=X, pady=2)
        Label(row_db3, text="用户名:", width=10, anchor=W).pack(side=LEFT)
        self.db_user_var = StringVar(value=self.config.get("DB_USER", "root"))
        Entry(row_db3, textvariable=self.db_user_var, width=20).pack(side=LEFT, padx=5)

        # 密码
        row_db4 = Frame(db_frame)
        row_db4.pack(fill=X, pady=2)
        Label(row_db4, text="密码:", width=10, anchor=W).pack(side=LEFT)
        self.db_pwd_var = StringVar(value=self.config.get("DB_PASSWORD", ""))
        Entry(row_db4, textvariable=self.db_pwd_var, width=20, show="*").pack(side=LEFT, padx=5)

        # 数据库名
        row_db5 = Frame(db_frame)
        row_db5.pack(fill=X, pady=2)
        Label(row_db5, text="数据库:", width=10, anchor=W).pack(side=LEFT)
        self.db_name_var = StringVar(value=self.config.get("DB_NAME", "test"))
        Entry(row_db5, textvariable=self.db_name_var, width=20).pack(side=LEFT, padx=5)

        # data_type 过滤条件
        row1 = Frame(frame_cfg)
        row1.pack(fill=X, pady=3)
        Label(row1, text="data_type过滤:", width=20, anchor=W).pack(side=LEFT)
        self.data_type_var = StringVar(value=self.config.get("data_type_filter", "V33-IMG-AI"))
        Entry(row1, textvariable=self.data_type_var, width=25).pack(side=LEFT, padx=5)
        Label(row1, text="(支持%通配符)", foreground="gray", font=("Arial", 8)).pack(side=LEFT)

        # 批量大小
        row2 = Frame(frame_cfg)
        row2.pack(fill=X, pady=3)
        Label(row2, text="每次打开网页数量:", width=20, anchor=W).pack(side=LEFT)
        self.batch_var = StringVar(value=str(self.config.get("open_batch_size", 2)))
        Spinbox(row2, from_=1, to=20, textvariable=self.batch_var, width=8).pack(side=LEFT)

        # 同一批次内打开URL的间隔
        row2b = Frame(frame_cfg)
        row2b.pack(fill=X, pady=3)
        Label(row2b, text="URL打开间隔（秒）:", width=20, anchor=W).pack(side=LEFT)
        self.url_open_interval_var = StringVar(value=str(self.config.get("url_open_interval", 1.0)))
        Spinbox(row2b, from_=0.1, to=10, increment=0.1, textvariable=self.url_open_interval_var, width=8).pack(side=LEFT)
        Label(row2b, text="(建议1-3秒，避免Chrome卡死)", foreground="gray", font=("Arial", 8)).pack(side=LEFT)

        # 批次间隔时间
        row3 = Frame(frame_cfg)
        row3.pack(fill=X, pady=3)
        Label(row3, text="批次间隔时间（秒）:", width=20, anchor=W).pack(side=LEFT)
        self.interval_var = StringVar(value=str(self.config.get("batch_interval_seconds", 2)))
        Spinbox(row3, from_=1, to=60, textvariable=self.interval_var, width=8).pack(side=LEFT)

        # URL后缀参数
        row4 = Frame(frame_cfg)
        row4.pack(fill=X, pady=3)
        Label(row4, text="URL后缀参数:", width=20, anchor=W).pack(side=LEFT)
        self.suffix_var = StringVar(value=self.config.get("url_suffix", ""))
        Entry(row4, textvariable=self.suffix_var, width=25).pack(side=LEFT, padx=5)
        Label(row4, text="例: pageFrom=image", foreground="gray", font=("Arial", 8)).pack(side=LEFT)

        # 按钮区
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        self.start_btn = Button(btn_frame, text="▶️ 开始测试", command=self.start_test, bg="#4CAF50", fg="white", width=10, height=2)
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
        self.progress_var = StringVar(value="等待开始测试...")
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
            batch_size = int(self.batch_var.get())
            interval_sec = int(self.interval_var.get())
            url_open_interval = float(self.url_open_interval_var.get())
            data_type_filter = self.data_type_var.get().strip()
            url_suffix = self.suffix_var.get().strip()
            
            # 数据库配置
            db_host = self.db_host_var.get().strip()
            db_port = int(self.db_port_var.get())
            db_user = self.db_user_var.get().strip()
            db_password = self.db_pwd_var.get()
            db_name = self.db_name_var.get().strip()
            
            if batch_size < 1 or interval_sec < 1:
                raise ValueError("时间参数必须大于0")
            if url_open_interval < 0.1:
                raise ValueError("URL打开间隔至少0.1秒")
            if not data_type_filter:
                raise ValueError("data_type过滤条件不能为空")
            if not db_host:
                raise ValueError("数据库主机不能为空")
            if not db_user:
                raise ValueError("数据库用户名不能为空")
            if not db_name:
                raise ValueError("数据库名称不能为空")
            
            self.config["DB_HOST"] = db_host
            self.config["DB_PORT"] = db_port
            self.config["DB_USER"] = db_user
            self.config["DB_PASSWORD"] = db_password
            self.config["DB_NAME"] = db_name
            self.config["open_batch_size"] = batch_size
            self.config["batch_interval_seconds"] = interval_sec
            self.config["url_open_interval"] = url_open_interval
            self.config["data_type_filter"] = data_type_filter
            self.config["url_suffix"] = url_suffix
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
        self.log_to_gui("开始设备极限压力测试...")

        thread = threading.Thread(target=self.run_test_cycle, daemon=True)
        thread.start()

    def pause_test(self):
        if self.running and not self.paused:
            self.paused = True
            self.pause_btn.config(state=DISABLED)
            self.resume_btn.config(state=NORMAL)
            self.status_var.set("已暂停")
            self.log_to_gui("测试已暂停。")

    def resume_test(self):
        if self.running and self.paused:
            self.paused = False
            self.pause_btn.config(state=NORMAL)
            self.resume_btn.config(state=DISABLED)
            self.status_var.set("正在运行...")
            self.log_to_gui("测试已恢复。")

    def stop_test(self):
        self.running = False
        self.paused = False
        self.status_var.set("用户已停止")
        self.log_to_gui("用户手动停止测试。")
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.resume_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)

    def run_test_cycle(self):
        try:
            total_processed = 0
            total_urls = 0
            data_type_filter = self.config["data_type_filter"]
            url_suffix = self.config["url_suffix"]
            
            # 构建数据库配置
            db_config = {
                "DB_HOST": self.config["DB_HOST"],
                "DB_PORT": self.config["DB_PORT"],
                "DB_USER": self.config["DB_USER"],
                "DB_PASSWORD": self.config["DB_PASSWORD"],
                "DB_NAME": self.config["DB_NAME"]
            }

            # 首先统计总共有多少待处理的URL
            try:
                conn = get_db_connection(db_config)
                cursor = conn.cursor()
                count_query = """
                    SELECT COUNT(*) as count
                    FROM general_data
                    WHERE data_type LIKE %s
                      AND is_deleted = 0
                """
                cursor.execute(count_query, (data_type_filter,))
                result = cursor.fetchone()
                total_urls = result[0] if result else 0
                cursor.close()
                conn.close()
                self.progress_var.set(f"总待处理: {total_urls} 个链接 (data_type: {data_type_filter})")
            except Exception as e:
                logger.error(f"统计总链接数失败: {e}")
                self.progress_var.set("统计总链接数失败")
                return

            while self.running:
                # 检查是否暂停
                while self.paused and self.running:
                    time.sleep(0.1)

                if not self.running:
                    break

                urls = fetch_pending_urls(self.config["open_batch_size"], data_type_filter, db_config)
                if not urls:
                    self.log_to_gui("✅ 所有待测试的链接已处理完毕！")
                    break

                self.log_to_gui(f"当前批次获取 {len(urls)} 个待测链接，即将打开...")
                self.status_var.set(f"正在处理批次...")

                threads = []
                completed = [0]
                total = len(urls)

                # 定义回调函数
                def on_url_done(url_id, success, error_msg):
                    nonlocal total_processed
                    completed[0] += 1
                    total_processed += 1
                    if success:
                        self.log_to_gui(f"✅ 已完成加载 (ID={url_id})")
                    else:
                        self.log_to_gui(f"❌ 加载失败 (ID={url_id}): {error_msg}")

                    # 更新进度信息
                    self.progress_var.set(f"已处理: {total_processed}/{total_urls} 个链接")

                delay = self.config["close_after_seconds"]
                url_open_interval = self.config["url_open_interval"]  # 获取URL打开间隔
                batch_ids = [item['id'] for item in urls]  # 记录当前批次的ID列表
                
                for item in urls:
                    if not self.running:
                        break
                    
                    # 构建带后缀、generalDataId和source的URL
                    final_url = build_url_with_suffix(
                        item['data_content'], 
                        url_suffix,
                        general_data_id=item['id'],
                        source=item.get('data_type', '')  # 添加 source 参数
                    )
                    
                    t = threading.Thread(
                        target=open_and_close_url,
                        args=(final_url, delay, item['id'], on_url_done),
                        daemon=True
                    )
                    threads.append(t)
                    t.start()
                    time.sleep(url_open_interval)  # 使用配置的间隔时间

                # 等待当前批次所有页面都成功加载（通过检查数据库状态）
                self.log_to_gui(f"等待浏览器端处理完成... (共 {len(batch_ids)} 个页面)")
                                
                # 重试机制配置
                max_wait_time = 60  # 单次等待最多60秒（1分钟）
                max_retries = 3  # 最多重试3次
                retry_count = 0
                                
                # 记录每个ID的重试次数
                retry_tracker = {url_id: 0 for url_id in batch_ids}
                                
                while self.running and not self.paused:
                    # 检查是否所有页面都已标记为完成
                    all_completed, incomplete_ids = check_urls_completed(batch_ids, db_config)
                                    
                    if all_completed:
                        self.log_to_gui(f"✅ 当前批次所有页面已成功加载")
                        break
                                    
                    # 显示未完成的情况
                    if len(incomplete_ids) < len(batch_ids):
                        completed_count = len(batch_ids) - len(incomplete_ids)
                        self.log_to_gui(f"⏳ 已完成 {completed_count}/{len(batch_ids)} 个，等待剩余 {len(incomplete_ids)} 个...")
                                    
                    # 等待1秒后检查
                    time.sleep(1)
                    waited_time += 1
                                    
                    # 每10秒显示一次等待信息
                    if waited_time % 10 == 0:
                        self.log_to_gui(f"⏳ 等待中... ({waited_time}秒，未完成: {len(incomplete_ids)}个)")
                                    
                    # 检查是否超时（超过1分钟）
                    if waited_time >= max_wait_time:
                        retry_count += 1
                                        
                        if retry_count <= max_retries:
                            # 记录需要重新打开的ID
                            ids_to_reopen = []
                                            
                            for url_id in incomplete_ids:
                                retry_tracker[url_id] = retry_tracker.get(url_id, 0) + 1
                                                
                                # 如果某个ID重试超过3次，直接标记为完成
                                if retry_tracker[url_id] >= 3:
                                    self.log_to_gui(f"⚠️ ID={url_id} 已重试 {retry_tracker[url_id]} 次，强制标记为完成")
                                    mark_url_as_completed(url_id, db_config)
                                else:
                                    ids_to_reopen.append(url_id)
                                            
                            # 重新打开未完成的URL
                            if ids_to_reopen:
                                self.log_to_gui(f"🔄 第 {retry_count} 次重试，重新打开 {len(ids_to_reopen)} 个未完成的页面...")
                                                
                                for url_id in ids_to_reopen:
                                    if not self.running:
                                        break
                                                    
                                    # 找到对应的URL
                                    url_item = next((item for item in urls if item['id'] == url_id), None)
                                    if url_item:
                                        final_url = build_url_with_suffix(
                                            url_item['data_content'],
                                            url_suffix,
                                            general_data_id=url_id,
                                            source=url_item.get('data_type', '')
                                        )
                                                        
                                        # 重新打开URL
                                        try:
                                            logger.info(f"重新打开: {final_url}")
                                            webbrowser.open(final_url)
                                            self.log_to_gui(f"🔄 重新打开 ID={url_id}")
                                        except Exception as e:
                                            logger.error(f"重新打开 ID={url_id} 失败: {e}")
                                                        
                                        time.sleep(0.5)  # 重新打开时稍微延迟
                                                
                                # 重置等待时间，继续监听
                                waited_time = 0
                                self.log_to_gui(f"继续监听未完成页面...")
                            else:
                                # 所有未完成的都已经被强制标记
                                self.log_to_gui("✅ 所有页面已处理完成（部分强制标记）")
                                break
                        else:
                            # 超过最大重试次数，强制标记所有剩余的
                            self.log_to_gui(f"⚠️ 已达到最大重试次数 ({max_retries})，强制标记剩余 {len(incomplete_ids)} 个页面")
                            for url_id in incomplete_ids:
                                mark_url_as_completed(url_id, db_config)
                            break
                                
                # 如果用户停止或暂停，退出循环
                if not self.running or self.paused:
                    break

                # 如果还有更多URL待处理，等待批次间隔时间
                remaining_count_query = """
                    SELECT COUNT(*) as count
                    FROM general_data
                    WHERE data_type LIKE %s
                      AND is_deleted = 0
                """
                try:
                    conn = get_db_connection(db_config)
                    cursor = conn.cursor()
                    cursor.execute(remaining_count_query, (data_type_filter,))
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
            self.log_to_gui(f"❌ 启动测试失败: {e}")
            logger.exception("启动测试异常")
            self.root.after(0, self.finish_run)

    def finish_run(self):
        self.running = False
        self.paused = False
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.resume_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)
        self.status_var.set("测试完成")
        self.log_to_gui("所有测试完成。")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = DeviceStressTestGUI(root)
    root.mainloop()