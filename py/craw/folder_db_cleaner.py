import os
import json
import pymysql
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path
import time

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "folder_db_cleaner"
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
    "SOURCE_FILTER": "%动漫%",  # source 过滤条件
    "SAVE_LOG_FILE": True
}

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
# 数据库工具
# ==============================


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


def fetch_matching_records(db_config, source_filter):
    """从数据库查询匹配的记录"""
    conn = get_db_connection(db_config)
    if not conn:
        return []

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        query = "SELECT uid, title, content, source FROM web_crawl_data WHERE source LIKE %s"
        cursor.execute(query, (source_filter,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        logger.info(f"查询到 {len(rows)} 条记录 (source过滤: {source_filter})")
        return rows
    except Exception as e:
        logger.error(f"查询数据库失败: {e}")
        conn.close()
        return []


def delete_folder(folder_path, folder_name):
    """删除文件夹及其所有内容"""
    try:
        import shutil
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"[已删除文件夹] {folder_name} - {folder_path}")
            return True
        else:
            logger.warning(f"[文件夹不存在] {folder_name} - {folder_path}")
            return False
    except Exception as e:
        logger.error(f"[删除文件夹错误] {folder_name} => {e}")
        return False


# ==============================
# 核心逻辑
# ==============================


def scan_folders(base_dir):
    """扫描目录下的所有子目录"""
    folders = []
    try:
        for item in os.listdir(base_dir):
            item_path = os.path.join(base_dir, item)
            if os.path.isdir(item_path):
                folders.append(item)
        logger.info(f"扫描到 {len(folders)} 个子目录")
        return folders
    except Exception as e:
        logger.error(f"扫描目录失败: {e}")
        return []


def find_matching_folders(folders, db_records):
    """查找文件夹名称与数据库 title 字段匹配的记录"""
    matches = []
    
    # 构建 title 集合（用于快速查找）
    db_titles = set()
    title_to_records = {}
    for record in db_records:
        title = record.get("title", "")
        if title:
            db_titles.add(title)
            if title not in title_to_records:
                title_to_records[title] = []
            title_to_records[title].append(record)
    
    # 遍历文件夹，查找匹配
    for folder_name in folders:
        if folder_name in db_titles:
            matching_records = title_to_records[folder_name]
            for record in matching_records:
                matches.append({
                    "folder_name": folder_name,
                    "uid": record["uid"],
                    "title": record["title"],
                    "source": record.get("source", ""),
                    "content_preview": record.get("content", "")[:100] + "..." if record.get("content") else ""
                })
    
    logger.info(f"找到 {len(matches)} 个匹配的文件夹-数据库记录")
    return matches


# ==============================
# GUI 界面
# ==============================


class FolderDbCleanerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🗑️ 文件夹数据库清理工具")
        self.root.geometry("800x650")
        self.root.resizable(True, True)

        # 加载配置
        self.config = load_config()

        # 存储匹配结果
        self.matched_items = []
        self.selected_items = set()

        self.create_widgets()

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 配置区域 ===
        config_frame = ttk.LabelFrame(main_frame, text="⚙️ 配置", padding="10")
        config_frame.pack(fill=tk.X, pady=5)

        # 选择目录
        ttk.Label(config_frame, text="选择目录:").grid(
            row=0, column=0, sticky=tk.W, pady=3)
        self.base_dir_var = tk.StringVar(value="")
        ttk.Entry(config_frame, textvariable=self.base_dir_var,
                  width=50).grid(row=0, column=1, padx=5, pady=3)
        ttk.Button(config_frame, text="浏览...", command=self.browse_directory).grid(
            row=0, column=2, padx=5, pady=3)

        # source 过滤
        ttk.Label(config_frame, text="source过滤:").grid(
            row=1, column=0, sticky=tk.W, pady=3)
        self.source_filter_var = tk.StringVar(value=self.config.get("SOURCE_FILTER", "%动漫%"))
        ttk.Entry(config_frame, textvariable=self.source_filter_var,
                  width=50).grid(row=1, column=1, columnspan=2, padx=5, pady=3, sticky=tk.W)
        ttk.Label(config_frame, text="(支持%通配符)", 
                  foreground="gray", font=("Arial", 8)).grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=5)

        # 保存日志
        ttk.Label(config_frame, text="保存日志:").grid(
            row=3, column=0, sticky=tk.W, pady=3)
        self.save_log_var = tk.BooleanVar(value=self.config.get("SAVE_LOG_FILE", True))
        ttk.Checkbutton(config_frame, variable=self.save_log_var).grid(
            row=3, column=1, sticky=tk.W, padx=5, pady=3)

        # === 按钮区域 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.scan_btn = ttk.Button(
            btn_frame, text="🔍 扫描匹配", command=self.scan_and_match)
        self.scan_btn.pack(side=tk.LEFT, padx=5)

        self.select_all_btn = ttk.Button(
            btn_frame, text="☑️ 全选", command=self.select_all)
        self.select_all_btn.pack(side=tk.LEFT, padx=5)

        self.deselect_all_btn = ttk.Button(
            btn_frame, text="☐ 取消全选", command=self.deselect_all)
        self.deselect_all_btn.pack(side=tk.LEFT, padx=5)

        self.delete_btn = ttk.Button(
            btn_frame, text="🗑️ 删除选中文件夹", command=self.delete_selected, state=tk.DISABLED)
        self.delete_btn.pack(side=tk.LEFT, padx=5)

        self.save_config_btn = ttk.Button(
            btn_frame, text="💾 保存配置", command=self.save_current_config)
        self.save_config_btn.pack(side=tk.LEFT, padx=5)

        # === 状态显示 ===
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=5)

        ttk.Label(status_frame, text="状态:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var).pack(
            side=tk.LEFT, padx=5)

        ttk.Label(status_frame, text="匹配数:").pack(side=tk.LEFT, padx=(20, 0))
        self.match_count_var = tk.StringVar(value="0")
        ttk.Label(status_frame, textvariable=self.match_count_var).pack(
            side=tk.LEFT, padx=5)

        # === 匹配结果列表 ===
        result_frame = ttk.LabelFrame(main_frame, text="📋 匹配结果", padding="5")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 创建 Treeview
        columns = ("folder", "uid", "title", "source")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("folder", text="文件夹名称")
        self.tree.heading("uid", text="UID")
        self.tree.heading("title", text="标题")
        self.tree.heading("source", text="来源")
        
        self.tree.column("folder", width=150)
        self.tree.column("uid", width=80)
        self.tree.column("title", width=200)
        self.tree.column("source", width=150)

        scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定选择事件
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # === 日志区域 ===
        log_frame = ttk.LabelFrame(main_frame, text="📝 操作日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=False, pady=5)

        log_scrollbar = ttk.Scrollbar(log_frame)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(
            log_frame, height=8, yscrollcommand=log_scrollbar.set, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.config(command=self.log_text.yview)

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

    def browse_directory(self):
        directory = filedialog.askdirectory(title="选择要扫描的目录")
        if directory:
            self.base_dir_var.set(directory)

    def save_current_config(self):
        new_config = {
            "DB_HOST": self.config["DB_HOST"],
            "DB_PORT": self.config["DB_PORT"],
            "DB_USER": self.config["DB_USER"],
            "DB_PASSWORD": self.config["DB_PASSWORD"],
            "DB_NAME": self.config["DB_NAME"],
            "SOURCE_FILTER": self.source_filter_var.get(),
            "SAVE_LOG_FILE": self.save_log_var.get()
        }
        save_config(new_config)

        # 更新全局配置
        global config
        config = new_config

        # 重新配置日志
        global logger
        logger = setup_logger()

        messagebox.showinfo("成功", "配置已保存")

    def scan_and_match(self):
        base_dir = self.base_dir_var.get().strip()
        if not base_dir:
            messagebox.showwarning("警告", "请先选择要扫描的目录")
            return

        if not os.path.exists(base_dir):
            messagebox.showerror("错误", f"目录不存在: {base_dir}")
            return

        source_filter = self.source_filter_var.get().strip()
        if not source_filter:
            source_filter = "%"

        self.status_var.set("正在扫描...")
        logger.info("="*50)
        logger.info(f"开始扫描目录: {base_dir}")
        logger.info(f"Source过滤条件: {source_filter}")

        # 构建数据库配置
        db_config = {
            "DB_HOST": self.config["DB_HOST"],
            "DB_PORT": self.config["DB_PORT"],
            "DB_USER": self.config["DB_USER"],
            "DB_PASSWORD": self.config["DB_PASSWORD"],
            "DB_NAME": self.config["DB_NAME"]
        }

        # 1. 扫描文件夹
        folders = scan_folders(base_dir)
        if not folders:
            messagebox.showinfo("提示", "目录下没有子文件夹")
            self.status_var.set("就绪")
            return

        # 2. 查询数据库
        db_records = fetch_matching_records(db_config, source_filter)
        if not db_records:
            messagebox.showinfo("提示", f"数据库中没有匹配的记录 (source: {source_filter})")
            self.status_var.set("就绪")
            return

        # 3. 查找匹配
        self.matched_items = find_matching_folders(folders, db_records)
        
        # 4. 显示结果
        self.display_results()
        
        self.match_count_var.set(str(len(self.matched_items)))
        self.status_var.set(f"扫描完成，找到 {len(self.matched_items)} 个匹配项")
        
        if self.matched_items:
            self.delete_btn.config(state=tk.NORMAL)
        else:
            messagebox.showinfo("提示", "没有找到匹配的文件夹")

    def display_results(self):
        """在 Treeview 中显示匹配结果"""
        # 清空现有数据
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 清空选择
        self.selected_items.clear()
        
        # 添加新数据
        for i, match in enumerate(self.matched_items):
            item_id = self.tree.insert("", tk.END, values=(
                match["folder_name"],
                match["uid"],
                match["title"],
                match["source"]
            ))
            # 存储索引以便后续引用
            match["tree_id"] = item_id
        
        logger.info(f"已在列表中显示 {len(self.matched_items)} 个匹配项")

    def on_tree_select(self, event):
        """处理树形视图选择事件"""
        selected = self.tree.selection()
        self.selected_items = set(selected)
        
        if selected:
            self.delete_btn.config(state=tk.NORMAL)
        else:
            self.delete_btn.config(state=tk.DISABLED)

    def select_all(self):
        """全选所有匹配项"""
        all_items = self.tree.get_children()
        if all_items:
            self.tree.selection_set(all_items)
            self.selected_items = set(all_items)
            self.delete_btn.config(state=tk.NORMAL)
            logger.info(f"已全选 {len(all_items)} 个项目")

    def deselect_all(self):
        """取消全选"""
        self.tree.selection_remove(self.tree.get_children())
        self.selected_items.clear()
        self.delete_btn.config(state=tk.DISABLED)
        logger.info("已取消全选")

    def delete_selected(self):
        """删除选中的文件夹"""
        if not self.selected_items:
            messagebox.showwarning("警告", "请先选择要删除的文件夹")
            return

        # 获取选中的项目信息
        base_dir = self.base_dir_var.get().strip()
        items_to_delete = []
        for tree_id in self.selected_items:
            values = self.tree.item(tree_id)["values"]
            folder_name = values[0]
            folder_path = os.path.join(base_dir, folder_name)
            items_to_delete.append({
                "tree_id": tree_id,
                "folder_name": folder_name,
                "folder_path": folder_path,
                "uid": values[1],
                "title": values[2]
            })

        # 确认对话框
        confirm_msg = f"即将删除 {len(items_to_delete)} 个文件夹及其所有内容：\n\n"
        for item in items_to_delete[:10]:  # 只显示前10个
            confirm_msg += f"• {item['folder_name']}\n  路径: {item['folder_path']}\n"
        
        if len(items_to_delete) > 10:
            confirm_msg += f"... 还有 {len(items_to_delete) - 10} 个文件夹\n"
        
        confirm_msg += "\n⚠️ 此操作不可恢复，文件夹将被永久删除！\n是否继续？"
        
        if not messagebox.askyesno("⚠️ 确认删除文件夹", confirm_msg, icon='warning'):
            logger.info("用户取消了删除操作")
            return

        # 执行删除
        deleted_count = 0
        failed_count = 0
        
        logger.info(f"开始删除 {len(items_to_delete)} 个文件夹...")
        
        for item in items_to_delete:
            folder_name = item["folder_name"]
            folder_path = item["folder_path"]
            
            if delete_folder(folder_path, folder_name):
                deleted_count += 1
                # 从树形视图中移除
                self.tree.delete(item["tree_id"])
            else:
                failed_count += 1
            
            # 更新状态
            self.status_var.set(f"删除中: {deleted_count}/{len(items_to_delete)}")
            self.root.update_idletasks()

        # 更新统计
        remaining = len(self.tree.get_children())
        self.match_count_var.set(str(remaining))
        
        # 最终状态
        if failed_count == 0:
            messagebox.showinfo("完成", f"成功删除 {deleted_count} 个文件夹")
            logger.info(f"✅ 删除完成: 成功 {deleted_count} 个文件夹")
        else:
            messagebox.showwarning(
                "部分失败", 
                f"成功删除 {deleted_count} 个文件夹，失败 {failed_count} 个"
            )
            logger.warning(f"⚠️ 删除完成: 成功 {deleted_count} 个，失败 {failed_count} 个")
        
        self.status_var.set(f"删除完成: 成功 {deleted_count}, 失败 {failed_count}")
        
        # 如果没有剩余项目，禁用删除按钮
        if remaining == 0:
            self.delete_btn.config(state=tk.DISABLED)


# ==============================
# 程序入口
# ==============================
if __name__ == "__main__":
    root = tk.Tk()
    app = FolderDbCleanerApp(root)
    root.mainloop()
