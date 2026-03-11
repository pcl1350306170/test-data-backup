# filter_txt_by_line_length.pyw

import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk
from datetime import datetime

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "filter_txt_by_line_length"  # 脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
LOGS_DIR = CONFIG_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"

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
    "input_file": "",
    "overwrite_original": False,
    "max_chars_per_line": 50,
}


# ==============================
# 核心处理函数
# ==============================
def process_txt_file(input_path: Path, max_chars: int, overwrite: bool) -> tuple[bool, str]:
    if not input_path.exists():
        return False, "输入文件不存在"

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        return False, f"读取文件失败: {e}"

    # 过滤：保留字数 <= max_chars 的行（注意：strip() 后计算）
    filtered_lines = []
    deleted_count = 0
    for line in lines:
        stripped = line.rstrip('\r\n')
        if len(stripped) <= max_chars:
            filtered_lines.append(line)  # 保留原始换行符
        else:
            deleted_count += 1

    # 确定输出路径
    if overwrite:
        output_path = input_path
    else:
        stem = input_path.stem
        suffix = input_path.suffix
        output_path = input_path.parent / f"{stem}_filtered{suffix}"

    try:
        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            f.writelines(filtered_lines)
        return True, f"成功！删除 {deleted_count} 行，结果保存至: {output_path}"
    except Exception as e:
        return False, f"写入文件失败: {e}"


# ==============================
# GUI 主类
# ==============================
class TxtLineFilterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("✂️ TXT 行长度过滤器")
        self.root.geometry("700x320")
        self.root.resizable(True, False)

        self.config = self.load_config()
        self.setup_ui()

    def setup_ui(self):
        # 输入文件
        file_frame = LabelFrame(self.root, text="📄 选择TXT文件", padx=10, pady=8)
        file_frame.pack(fill=X, padx=10, pady=5)

        self.file_var = StringVar(value=self.config.get("input_file", ""))
        Entry(file_frame, textvariable=self.file_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(file_frame, text="📁 浏览", command=self.browse_file).pack(side=RIGHT, padx=(5, 0))

        # 覆盖选项
        option_frame = Frame(self.root)
        option_frame.pack(fill=X, padx=10, pady=5)

        self.overwrite_var = BooleanVar(value=self.config.get("overwrite_original", False))
        Checkbutton(
            option_frame,
            text="☑ 覆盖原文件（否则生成 _filtered 新文件）",
            variable=self.overwrite_var,
            anchor=W
        ).pack(side=LEFT)

        # 每行字数限制
        char_frame = LabelFrame(self.root, text="📏 每行最大字数（超过则删除整行）", padx=10, pady=8)
        char_frame.pack(fill=X, padx=10, pady=5)

        self.max_chars_var = StringVar(value=str(self.config.get("max_chars_per_line", 50)))
        Entry(char_frame, textvariable=self.max_chars_var, width=10, justify=CENTER).pack()

        # 操作按钮
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)

        self.start_btn = Button(btn_frame, text="▶️ 开始处理", command=self.start_process, bg="#4CAF50", fg="white", width=12)
        self.start_btn.pack(side=LEFT, padx=10)

        self.clear_btn = Button(btn_frame, text="🗑️ 清空配置", command=self.clear_config, width=10)
        self.clear_btn.pack(side=LEFT, padx=10)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="选择TXT文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=Path(self.file_var.get()).parent if self.file_var.get() else None
        )
        if file_path:
            self.file_var.set(file_path)

    def start_process(self):
        input_file = self.file_var.get().strip()
        if not input_file:
            messagebox.showwarning("警告", "请选择一个TXT文件！")
            return

        try:
            max_chars = int(self.max_chars_var.get())
            if max_chars < 1:
                raise ValueError("字数必须 ≥ 1")
        except ValueError as e:
            messagebox.showerror("输入错误", f"每行字数设置无效：{e}")
            return

        overwrite = self.overwrite_var.get()

        # 保存配置
        current_config = {
            "input_file": input_file,
            "overwrite_original": overwrite,
            "max_chars_per_line": max_chars,
        }
        self.save_config(current_config)

        # 执行处理
        input_path = Path(input_file)
        success, msg = process_txt_file(input_path, max_chars, overwrite)
        logger.info(f"[{'成功' if success else '失败'}] {msg}")

        self.status_var.set(msg)
        if success:
            messagebox.showinfo("完成", msg)
        else:
            messagebox.showerror("错误", msg)

    def load_config(self):
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

    def save_config(self, config):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def clear_config(self):
        if messagebox.askyesno("确认", "清空所有配置？"):
            self.file_var.set("")
            self.overwrite_var.set(False)
            self.max_chars_var.set("50")
            self.save_config(DEFAULT_CONFIG.copy())
            self.status_var.set("配置已重置")


# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 尝试加载 DB_CONFIG（非必需）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)
        except:
            pass

    root = Tk()
    app = TxtLineFilterGUI(root)
    root.mainloop()
