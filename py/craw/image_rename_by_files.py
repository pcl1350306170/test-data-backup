import os
import re
import json
import pymysql
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "image_rename_by_files"
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
    logger.setLevel(logging.DEBUG)
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


def find_record_by_filenames(db_config, filenames):
    """根据文件名列表在数据库中查找匹配的记录
    
    Args:
        db_config: 数据库配置
        filenames: 文件名列表（按顺序）
        
    Returns:
        dict: 匹配的记录，或 None
    """
    conn = get_db_connection(db_config)
    if not conn:
        return None

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 逐步增加查询条件，直到找到唯一匹配
        for i in range(1, len(filenames) + 1):
            current_files = filenames[:i]
            
            # 构建 LIKE 查询条件
            conditions = []
            params = []
            for filename in current_files:
                conditions.append("content LIKE %s")
                params.append(f"%{filename}%")
            
            query = f"""
                SELECT uid, title, content, source 
                FROM web_crawl_data 
                WHERE 1=1 AND {' AND '.join(conditions)}
            """
            
            cursor.execute(query, tuple(params))
            results = cursor.fetchall()
            
            logger.debug(f"使用 {i} 个文件查询: {current_files}")
            logger.debug(f"  找到 {len(results)} 条记录")
            
            # 如果只找到一条记录，返回
            if len(results) == 1:
                logger.info(f"✅ 找到唯一匹配记录: UID={results[0]['uid']}, title={results[0]['title']}")
                cursor.close()
                conn.close()
                return results[0]
            
            # 如果找到多条，继续增加条件
            if len(results) > 1 and i < len(filenames):
                logger.debug(f"  找到多条记录，继续使用下一个文件缩小范围...")
                continue
        
        # 如果遍历完所有文件仍未找到唯一匹配
        if len(results) == 0:
            logger.warning(f"❌ 未找到匹配的记录")
        else:
            logger.warning(f"⚠️ 找到 {len(results)} 条匹配记录，无法确定唯一记录")
            for r in results:
                logger.warning(f"  - UID={r['uid']}, title={r['title']}")
        
        cursor.close()
        conn.close()
        return None
        
    except Exception as e:
        logger.error(f"查询数据库失败: {e}")
        conn.close()
        return None


# ==============================
# 工具函数
# ==============================


def get_image_files_in_folder(folder_path):
    """获取文件夹中的所有图片文件（按文件系统顺序）"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    
    if not os.path.exists(folder_path):
        return []
    
    files = []
    for filename in os.listdir(folder_path):
        filepath = os.path.join(folder_path, filename)
        if os.path.isfile(filepath):
            _, ext = os.path.splitext(filename.lower())
            if ext in image_extensions:
                files.append(filename)
    
    # 按文件名排序，确保顺序一致
    files.sort()
    return files


def parse_image_urls_from_content(content):
    """从 content 字段解析图片 URL 列表（保持顺序）"""
    if not content:
        return []
    
    # 按逗号分割
    urls = [url.strip() for url in content.split(",") if url.strip()]
    
    # 提取文件名
    image_filenames = []
    for url in urls:
        # 从 URL 中提取文件名
        filename = os.path.basename(url.split("?")[0])
        if filename:
            image_filenames.append(filename)
    
    return image_filenames


def rename_images_in_folder(folder_path, ordered_filenames):
    """根据有序的文件名列表重命名文件夹中的图片
    
    Args:
        folder_path: 文件夹路径
        ordered_filenames: 按顺序的文件名列表（来自数据库 content）
        
    Returns:
        tuple: (成功数量, 失败数量, 详细日志)
    """
    success_count = 0
    failed_count = 0
    logs = []
    
    if not os.path.exists(folder_path):
        logs.append(f"❌ 文件夹不存在: {folder_path}")
        return 0, 1, logs
    
    # 获取文件夹中实际存在的文件
    existing_files = set(os.listdir(folder_path))
    
    # 构建文件名映射（原始文件名 -> 新序号）
    filename_to_index = {}
    for index, filename in enumerate(ordered_filenames, start=1):
        if filename in existing_files:
            filename_to_index[filename] = index
    
    if not filename_to_index:
        logs.append(f"⚠️ 文件夹中没有匹配的图片文件")
        return 0, 0, logs
    
    logs.append(f"📋 找到 {len(filename_to_index)} 个需要重命名的文件")
    
    # 第一步：将所有需要重命名的文件移动到临时名称
    temp_renames = {}
    for original_filename, new_index in filename_to_index.items():
        temp_name = f"_temp_{new_index:03d}_{original_filename}"
        old_path = os.path.join(folder_path, original_filename)
        temp_path = os.path.join(folder_path, temp_name)
        
        try:
            os.rename(old_path, temp_path)
            temp_renames[temp_name] = (original_filename, new_index)
            logs.append(f"  ✅ 临时重命名: {original_filename} -> {temp_name}")
        except Exception as e:
            logs.append(f"  ❌ 临时重命名失败: {original_filename} - {e}")
            failed_count += 1
    
    # 第二步：将临时文件重命名为最终名称
    for temp_name, (original_filename, new_index) in temp_renames.items():
        # 确定文件扩展名
        _, ext = os.path.splitext(original_filename)
        if not ext:
            ext = ".jpg"  # 默认扩展名
        
        new_filename = f"{new_index:03d}{ext}"
        temp_path = os.path.join(folder_path, temp_name)
        new_path = os.path.join(folder_path, new_filename)
        
        try:
            os.rename(temp_path, new_path)
            success_count += 1
            logs.append(f"  ✅ 最终重命名: {original_filename} -> {new_filename}")
        except Exception as e:
            logs.append(f"  ❌ 最终重命名失败: {original_filename} -> {new_filename} - {e}")
            failed_count += 1
    
    return success_count, failed_count, logs


# ==============================
# GUI 界面
# ==============================


class ImageRenameByFilesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📝 图片批量重命名工具（反向查找）")
        self.root.geometry("900x700")
        self.root.resizable(True, True)

        # 加载配置
        self.config = load_config()

        # 存储处理结果
        self.process_results = []

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
                  width=60).grid(row=0, column=1, padx=5, pady=3)
        ttk.Button(config_frame, text="浏览...", command=self.browse_directory).grid(
            row=0, column=2, padx=5, pady=3)

        # 保存日志
        ttk.Label(config_frame, text="保存日志:").grid(
            row=1, column=0, sticky=tk.W, pady=3)
        self.save_log_var = tk.BooleanVar(value=self.config.get("SAVE_LOG_FILE", True))
        ttk.Checkbutton(config_frame, variable=self.save_log_var).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=3)

        # === 按钮区域 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.scan_btn = ttk.Button(
            btn_frame, text="🔍 扫描并预览", command=self.scan_and_preview)
        self.scan_btn.pack(side=tk.LEFT, padx=5)

        self.rename_btn = ttk.Button(
            btn_frame, text="📝 开始重命名", command=self.start_rename, state=tk.DISABLED)
        self.rename_btn.pack(side=tk.LEFT, padx=5)

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

        ttk.Label(status_frame, text="待处理:").pack(side=tk.LEFT, padx=(20, 0))
        self.count_var = tk.StringVar(value="0")
        ttk.Label(status_frame, textvariable=self.count_var).pack(
            side=tk.LEFT, padx=5)

        # === 预览列表 ===
        preview_frame = ttk.LabelFrame(main_frame, text="📋 处理预览", padding="5")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        columns = ("folder", "uid", "title", "image_count", "status")
        self.tree = ttk.Treeview(preview_frame, columns=columns, show="headings")
        
        self.tree.heading("folder", text="文件夹名")
        self.tree.heading("uid", text="UID")
        self.tree.heading("title", text="标题")
        self.tree.heading("image_count", text="图片数")
        self.tree.heading("status", text="状态")
        
        self.tree.column("folder", width=200)
        self.tree.column("uid", width=80)
        self.tree.column("title", width=200)
        self.tree.column("image_count", width=80)
        self.tree.column("status", width=150)

        scrollbar = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # === 日志区域 ===
        log_frame = ttk.LabelFrame(main_frame, text="📝 操作日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=False, pady=5)

        log_scrollbar = ttk.Scrollbar(log_frame)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(
            log_frame, height=10, yscrollcommand=log_scrollbar.set, state=tk.DISABLED)
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
        directory = filedialog.askdirectory(title="选择包含图片文件夹的目录")
        if directory:
            self.base_dir_var.set(directory)

    def save_current_config(self):
        new_config = {
            "DB_HOST": self.config["DB_HOST"],
            "DB_PORT": self.config["DB_PORT"],
            "DB_USER": self.config["DB_USER"],
            "DB_PASSWORD": self.config["DB_PASSWORD"],
            "DB_NAME": self.config["DB_NAME"],
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

    def scan_and_preview(self):
        base_dir = self.base_dir_var.get().strip()
        if not base_dir:
            messagebox.showwarning("警告", "请先选择目录")
            return

        if not os.path.exists(base_dir):
            messagebox.showerror("错误", f"目录不存在: {base_dir}")
            return

        self.status_var.set("正在扫描...")
        logger.info("="*50)
        logger.info(f"开始扫描目录: {base_dir}")

        # 构建数据库配置
        db_config = {
            "DB_HOST": self.config["DB_HOST"],
            "DB_PORT": self.config["DB_PORT"],
            "DB_USER": self.config["DB_USER"],
            "DB_PASSWORD": self.config["DB_PASSWORD"],
            "DB_NAME": self.config["DB_NAME"]
        }

        # 获取所有子目录
        subdirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        logger.info(f"找到 {len(subdirs)} 个子目录")

        # 清空预览列表
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.process_results = []

        # 遍历每个子目录
        matched_count = 0
        for folder_name in subdirs:
            folder_path = os.path.join(base_dir, folder_name)
            
            logger.info(f"\n处理文件夹: {folder_name}")
            
            # 获取文件夹中的图片文件
            image_files = get_image_files_in_folder(folder_path)
            
            if not image_files:
                logger.info(f"  ⚠️ 没有图片文件，跳过")
                continue
            
            logger.info(f"  📁 找到 {len(image_files)} 个图片文件")
            logger.debug(f"  文件列表: {image_files[:5]}{'...' if len(image_files) > 5 else ''}")
            
            # 根据文件名在数据库中查找记录
            record = find_record_by_filenames(db_config, image_files)
            
            if not record:
                logger.info(f"  ❌ 未找到匹配的数据库记录")
                continue
            
            # 解析 content 中的图片顺序
            ordered_filenames = parse_image_urls_from_content(record["content"])
            
            if not ordered_filenames:
                logger.info(f"  ⚠️ 记录中没有图片 URL")
                continue
            
            logger.info(f"  ✅ 匹配成功: UID={record['uid']}, title={record['title']}")
            logger.info(f"  📋 Content 中有 {len(ordered_filenames)} 个图片 URL")
            
            # 添加到预览列表
            self.tree.insert("", tk.END, values=(
                folder_name[:50],
                record["uid"],
                record["title"][:50],
                len(ordered_filenames),
                "待处理"
            ))

            # 保存处理信息
            self.process_results.append({
                "folder_name": folder_name,
                "folder_path": folder_path,
                "uid": record["uid"],
                "title": record["title"],
                "ordered_filenames": ordered_filenames,
                "image_files": image_files
            })

            matched_count += 1

        self.count_var.set(str(matched_count))
        self.status_var.set(f"扫描完成，找到 {matched_count} 个可处理的文件夹")

        if matched_count > 0:
            self.rename_btn.config(state=tk.NORMAL)
            logger.info(f"\n✅ 找到 {matched_count} 个匹配的文件夹")
        else:
            messagebox.showinfo("提示", "没有找到匹配的文件夹")

    def start_rename(self):
        if not self.process_results:
            messagebox.showwarning("警告", "没有可处理的项目")
            return

        # 确认对话框
        confirm_msg = f"即将重命名 {len(self.process_results)} 个文件夹中的图片\n\n"
        confirm_msg += "⚠️ 此操作会修改文件名，是否继续？"
        
        if not messagebox.askyesno("确认重命名", confirm_msg):
            logger.info("用户取消了重命名操作")
            return

        self.status_var.set("正在重命名...")
        logger.info(f"开始重命名 {len(self.process_results)} 个文件夹...")

        total_success = 0
        total_failed = 0

        for i, result in enumerate(self.process_results, 1):
            folder_path = result["folder_path"]
            ordered_filenames = result["ordered_filenames"]
            folder_name = result["folder_name"]
            uid = result["uid"]
            title = result["title"]

            logger.info(f"\n[{i}/{len(self.process_results)}] 处理: {folder_name} (UID: {uid})")
            logger.info(f"  文件夹: {folder_path}")
            logger.info(f"  标题: {title}")
            logger.info(f"  图片数: {len(ordered_filenames)}")

            # 重命名图片
            success, failed, logs = rename_images_in_folder(folder_path, ordered_filenames)
            
            total_success += success
            total_failed += failed

            # 输出详细日志
            for log in logs:
                logger.info(f"  {log}")

            # 更新 Treeview 状态
            item_id = self.tree.get_children()[i-1]
            if failed == 0:
                self.tree.set(item_id, "status", f"✅ 成功 {success} 个")
            else:
                self.tree.set(item_id, "status", f"⚠️ 成功 {success}, 失败 {failed}")

            # 更新状态
            self.status_var.set(f"处理中: {i}/{len(self.process_results)}")
            self.root.update_idletasks()

        # 完成
        logger.info(f"\n{'='*50}")
        logger.info(f"✅ 重命名完成!")
        logger.info(f"   总计成功: {total_success} 个文件")
        logger.info(f"   总计失败: {total_failed} 个文件")
        
        messagebox.showinfo(
            "完成",
            f"重命名完成!\n\n成功: {total_success} 个文件\n失败: {total_failed} 个文件"
        )
        
        self.status_var.set(f"完成: 成功 {total_success}, 失败 {total_failed}")


# ==============================
# 程序入口
# ==============================
if __name__ == "__main__":
    root = tk.Tk()
    app = ImageRenameByFilesApp(root)
    root.mainloop()
