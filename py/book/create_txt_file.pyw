# create_txt_file.pyw

import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, scrolledtext

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "create_txt_file"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)



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
# 默认配置
DEFAULT_CONFIG = {
    "save_directory": str(Path.home() / "Documents"),
    "file_title": "默认标题",
    "file_content": "这是默认内容。\n你可以在这里输入大段文本。"
}

# ==============================
# 工具函数
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

def save_config(save_dir, title, content):
    config = {
        "save_directory": save_dir.strip(),
        "file_title": title.strip(),
        "file_content": content
    }
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False

def create_txt_file(save_dir, title, content):
    try:
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        # 使用标题作为文件名（去除非法字符）
        safe_title = "".join(c for c in title if c not in r'<>:"/\|?*')
        if not safe_title:
            safe_title = "untitled"
        file_path = save_path / f"{safe_title}.txt"

        # 写入 UTF-8 编码文件
        with open(file_path, 'w', encoding='utf-8') as f:
            # 第一行是标题（如果内容不以标题开头，则添加）
            lines = content.splitlines()
            if not lines or lines[0] != title:
                full_content = title + "\n\n" + content
            else:
                full_content = content
            f.write(full_content)

        logger.info(f"文件已创建: {file_path}")
        return True, str(file_path)
    except Exception as e:
        logger.error(f"创建文件失败: {e}")
        return False, str(e)

# ==============================
# GUI 主类
# ==============================
class CreateTxtGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📄 自动创建 TXT 文件工具")
        self.root.geometry("600x520")
        self.root.resizable(True, True)

        self.config = load_config()
        self.setup_ui()

    def setup_ui(self):
        # 保存目录
        dir_frame = LabelFrame(self.root, text="📂 保存目录", padx=10, pady=8)
        dir_frame.pack(fill=X, padx=10, pady=5)
        self.dir_var = StringVar(value=self.config["save_directory"])
        Entry(dir_frame, textvariable=self.dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_frame, text="📁 选择目录", command=self.select_dir).pack(side=RIGHT, padx=(5, 0))

        # 文件标题
        title_frame = LabelFrame(self.root, text="🔖 文件标题（将作为第一行）", padx=10, pady=8)
        title_frame.pack(fill=X, padx=10, pady=5)
        self.title_var = StringVar(value=self.config["file_title"])
        Entry(title_frame, textvariable=self.title_var, font=("Consolas", 10)).pack(fill=X)

        # 文件内容
        content_frame = LabelFrame(self.root, text="📝 文件内容（大段文本）", padx=10, pady=8)
        content_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.content_text = scrolledtext.ScrolledText(content_frame, wrap=WORD, font=("Consolas", 10), height=12)
        self.content_text.pack(fill=BOTH, expand=True)
        self.content_text.insert(END, self.config["file_content"])

        # 按钮区域
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="💾 保存配置", command=self.save_config_action, bg="#4CAF50", fg="white", width=12).pack(side=LEFT, padx=5)
        Button(btn_frame, text="📄 创建 TXT 文件", command=self.create_file_action, bg="#2196F3", fg="white", width=18, height=1).pack(side=LEFT, padx=5)
        Button(btn_frame, text="📂 打开保存目录", command=self.open_save_dir, bg="#9C27B0", fg="white", width=15).pack(side=LEFT, padx=5)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue").pack(side=BOTTOM, fill=X)

    def select_dir(self):
        folder = filedialog.askdirectory(title="选择保存目录", initialdir=self.dir_var.get())
        if folder:
            self.dir_var.set(folder)

    def open_save_dir(self):
        save_dir = self.dir_var.get().strip()
        if Path(save_dir).exists():
            os.startfile(save_dir)
        else:
            messagebox.showwarning("警告", "保存目录不存在！")

    def save_config_action(self):
        save_dir = self.dir_var.get().strip()
        title = self.title_var.get().strip()
        content = self.content_text.get(1.0, END).strip()
        if not save_dir or not title:
            messagebox.showwarning("输入错误", "保存目录和文件标题不能为空！")
            return
        if save_config(save_dir, title, content):
            self.status_var.set("✅ 配置已保存")
            logger.info("配置已保存")
        else:
            messagebox.showerror("错误", "保存配置失败，请查看日志。")

    def create_file_action(self):
        save_dir = self.dir_var.get().strip()
        title = self.title_var.get().strip()
        content = self.content_text.get(1.0, END).strip()

        if not save_dir or not title:
            messagebox.showwarning("输入错误", "保存目录和文件标题不能为空！")
            return

        # 保存当前配置
        save_config(save_dir, title, content)

        self.status_var.set("正在创建文件...")
        self.root.update()

        success, result = create_txt_file(save_dir, title, content)
        if success:
            self.status_var.set("✅ 文件创建成功！")
            messagebox.showinfo("成功", f"TXT 文件已创建：\n{result}")
        else:
            self.status_var.set("❌ 创建失败")
            messagebox.showerror("错误", f"创建文件失败：\n{result}")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 尝试加载 DB_CONFIG（即使不用，也按要求引入）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_config = json.load(f)
                # 这里可以做验证，但脚本不需要数据库，所以仅加载
        except Exception as e:
            pass  # 忽略 DB 加载错误

    root = Tk()
    app = CreateTxtGUI(root)
    root.mainloop()
