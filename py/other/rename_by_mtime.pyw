# rename_by_mtime.pyw （含排序选项+间隔10重命名）
import os
import json
import logging
import shutil
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog
import threading
import tkinter.ttk as ttk

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "rename_by_mtime"
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
    "target_dir": "",
    "sort_method": "mtime"  # ✅ 新增：排序方式（mtime 或 filename）
}

# 排序选项映射
SORT_OPTIONS = {
    "修改时间": "mtime",
    "文件名": "filename"
}
REVERSE_SORT_MAP = {v: k for k, v in SORT_OPTIONS.items()}  # 反向映射

# ==============================
# 核心重命名函数
# ==============================
def rename_files_by_mtime(target_dir: Path, sort_method: str):
    """按指定方式排序，重命名为 0010, 0020..."""
    if not target_dir.is_dir():
        return False, "目标路径不是有效文件夹"

    # 获取所有文件（排除子目录）
    files = [f for f in target_dir.iterdir() if f.is_file()]
    if not files:
        return False, "文件夹中没有文件"

    # 按指定方式排序
    if sort_method == "mtime":
        files.sort(key=lambda x: x.stat().st_mtime)
    elif sort_method == "filename":
        files.sort(key=lambda x: x.name)
    else:
        return False, f"未知排序方式: {sort_method}"

    total = len(files)
    renamed = 0
    errors = []

    # 预生成新文件名，检查冲突
    new_names = []
    for i, file in enumerate(files, start=1):
        new_name = f"{(i * 10):04d}{file.suffix}"  # ✅ 改为间隔10：0010, 0020...
        new_path = target_dir / new_name
        new_names.append(new_path)

    # 检查是否已有同名文件（避免覆盖）
    existing_new_names = set()
    for new_path in new_names:
        if new_path.exists():
            errors.append(f"目标文件已存在，无法安全重命名: {new_path.name}")

    if errors:
        return False, "\n".join(errors)

    # 执行重命名
    temp_dir = target_dir / ".rename_temp"
    try:
        temp_dir.mkdir(exist_ok=True)
        # 先移动到临时目录避免命名冲突
        temp_files = []
        for file in files:
            temp_file = temp_dir / file.name
            shutil.move(str(file), str(temp_file))
            temp_files.append(temp_file)

        # 再从临时目录按序重命名回原目录
        for i, temp_file in enumerate(temp_files, start=1):
            new_name = f"{(i * 10):04d}{temp_file.suffix}"  # ✅ 间隔10
            final_path = target_dir / new_name
            shutil.move(str(temp_file), str(final_path))
            logger.info(f"重命名: {temp_file.name} → {new_name}")
            renamed += 1

    except Exception as e:
        # 出错时尽量恢复（可选）
        logger.error(f"重命名过程中出错: {e}")
        errors.append(str(e))
    finally:
        # 清理临时目录
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

    if errors:
        return False, "\n".join(errors)
    return True, f"成功重命名 {renamed} 个文件（按{'修改时间' if sort_method == 'mtime' else '文件名'}排序）"

# ==============================
# GUI 主类
# ==============================
class RenameByMtimeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🔢 文件重命名（按修改时间/文件名 → 0010, 0020...）")
        self.root.geometry("600x360")  # 高度+40适配新选项
        self.root.resizable(True, True)

        self.config = load_config()
        self.setup_ui()

    def setup_ui(self):
        # 目标文件夹选择
        dir_frame = LabelFrame(self.root, text="📂 选择要处理的文件夹", padx=10, pady=8)
        dir_frame.pack(fill=X, padx=10, pady=5)
        self.dir_var = StringVar(value=self.config["target_dir"])
        Entry(dir_frame, textvariable=self.dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_frame, text="📁 浏览", command=self.browse_dir).pack(side=RIGHT, padx=(5, 0))

        # 排序方式选择（新增）
        sort_frame = LabelFrame(self.root, text="🔄 排序方式", padx=10, pady=8)
        sort_frame.pack(fill=X, padx=10, pady=5)
        self.sort_var = StringVar(value=REVERSE_SORT_MAP.get(self.config.get("sort_method", "mtime"), "修改时间"))
        sort_combo = ttk.Combobox(sort_frame, textvariable=self.sort_var, values=list(SORT_OPTIONS.keys()), state="readonly", width=15)
        sort_combo.pack(side=LEFT)
        Label(sort_frame, text="（默认：修改时间）", font=("Arial", 8), fg="gray").pack(side=LEFT, padx=(5, 0))

        # 操作按钮
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        self.start_btn = Button(btn_frame, text="▶️ 开始重命名", command=self.start_rename, bg="#4CAF50", fg="white", width=15, height=2)
        self.start_btn.pack()

        # 日志显示
        log_frame = LabelFrame(self.root, text="📋 操作日志", padx=10, pady=8)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.log_text = Text(log_frame, wrap=WORD, height=8, state=DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)
        log_scroll = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

    def browse_dir(self):
        folder = filedialog.askdirectory(title="选择要处理的文件夹", initialdir=self.dir_var.get())
        if folder:
            self.dir_var.set(folder)

    def log_message(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def start_rename(self):
        target_dir = Path(self.dir_var.get().strip())
        sort_method = SORT_OPTIONS.get(self.sort_var.get(), "mtime")  # 映射到英文键

        if not target_dir or not target_dir.exists():
            messagebox.showwarning("警告", "请选择一个有效的文件夹！")
            return

        # 保存配置（包含新增字段）
        current_config = {
            "target_dir": str(target_dir),
            "sort_method": sort_method  # ✅ 保存排序方式
        }
        save_config(current_config)

        # 禁用按钮，启动后台线程
        self.start_btn.config(state=DISABLED, text="🔄 处理中...")
        self.status_var.set("正在处理...")
        self.log_message(f"开始处理文件夹: {target_dir}，排序方式: {'修改时间' if sort_method == 'mtime' else '文件名'}")

        thread = threading.Thread(target=self.run_rename, args=(target_dir, sort_method), daemon=True)
        thread.start()

    def run_rename(self, target_dir, sort_method):
        success, msg = rename_files_by_mtime(target_dir, sort_method)
        self.root.after(0, self.on_rename_complete, success, msg)

    def on_rename_complete(self, success, msg):
        self.start_btn.config(state=NORMAL, text="▶️ 开始重命名")
        if success:
            self.status_var.set("✅ 重命名完成！")
            self.log_message("✅ " + msg)
            messagebox.showinfo("成功", msg)
        else:
            self.status_var.set("❌ 操作失败")
            self.log_message("❌ " + msg)
            messagebox.showerror("错误", msg)

# ==============================
# 配置工具函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 按要求引入 DB_CONFIG（即使不用）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)
        except:
            pass

    root = Tk()
    app = RenameByMtimeGUI(root)
    root.mainloop()
