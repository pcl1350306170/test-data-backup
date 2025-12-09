# file_renamer.pyw

import os
import sys
import json
import logging
import shutil
from pathlib import Path
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "file_renamer"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR = SCRIPT_DIR / "json" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 通用数据库配置路径（虽不使用，但按要求定义）
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# ================== 主程序类 ==================
class FileRenamerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("文件批量重命名工具")
        self.root.geometry("900x700")
        self.root.minsize(800, 650)

        self.selected_files = []
        self.selected_dir = ""

        self.config = self.load_config()
        self.create_widgets()
        self.apply_config()

    def load_config(self):
        default_config = {
            "mode": "prefix",
            "content": "",
            "replace_from": "",
            "replace_to": "",
            "input_type": "files",
            "last_files": [],
            "last_directory": "",
        }
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    user_cfg = json.load(f)
                    default_config.update(user_cfg)
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
        return default_config

    def save_config(self):
        cfg = {
            "mode": self.mode_var.get(),
            "content": self.content_var.get().strip(),
            "replace_from": self.replace_from_var.get().strip(),
            "replace_to": self.replace_to_var.get().strip(),
            "input_type": self.input_type_var.get(),
            "last_files": self.selected_files,
            "last_directory": self.selected_dir,
        }
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def apply_config(self):
        self.mode_var.set(self.config.get("mode", "prefix"))
        self.content_var.set(self.config.get("content", ""))
        self.replace_from_var.set(self.config.get("replace_from", ""))
        self.replace_to_var.set(self.config.get("replace_to", ""))
        self.input_type_var.set(self.config.get("input_type", "files"))
        self.selected_dir = self.config.get("last_directory", "")
        self.selected_files = self.config.get("last_files", [])
        self.update_file_list()
        self.on_mode_change()

    def create_widgets(self):
        main_frame = Frame(self.root)
        main_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # === 1. 输入方式选择 ===
        input_frame = LabelFrame(main_frame, text="输入方式", padx=5, pady=5)
        input_frame.pack(fill=X, pady=5)
        self.input_type_var = StringVar(value="files")
        Radiobutton(input_frame, text="选择具体文件", variable=self.input_type_var, value="files",
                    command=self.on_input_type_change).pack(side=LEFT, padx=(0,10))
        Radiobutton(input_frame, text="选择整个文件夹", variable=self.input_type_var, value="directory",
                    command=self.on_input_type_change).pack(side=LEFT)

        # === 2. 文件/目录选择区域 ===
        select_frame = Frame(main_frame)
        select_frame.pack(fill=X, pady=5)
        self.select_btn = Button(select_frame, text="选择文件", command=self.select_input)
        self.select_btn.pack(side=LEFT)
        self.clear_btn = Button(select_frame, text="清空", command=self.clear_input)
        self.clear_btn.pack(side=LEFT, padx=(5,0))
        self.path_label = Label(select_frame, text="未选择", anchor=W, fg="gray")
        self.path_label.pack(side=LEFT, padx=(10,0), fill=X, expand=True)

        # === 3. 重命名规则 ===
        rule_frame = LabelFrame(main_frame, text="重命名规则", padx=5, pady=5)
        rule_frame.pack(fill=X, pady=5)

        # 模式选择
        mode_row = Frame(rule_frame)
        mode_row.pack(fill=X, pady=2)
        Label(mode_row, text="重命名方式:").pack(side=LEFT)
        self.mode_var = StringVar(value="prefix")
        modes = [
            ("添加前缀", "prefix"),
            ("添加后缀", "suffix"),
            ("保留“-”前部分", "split_dash"),
            ("关键字替换", "replace")
        ]
        for text, val in modes:
            Radiobutton(mode_row, text=text, variable=self.mode_var, value=val,
                        command=self.on_mode_change).pack(side=LEFT, padx=(10,0))

        # 内容输入（前缀/后缀用）
        self.content_frame = Frame(rule_frame)
        self.content_frame.pack(fill=X, pady=5)
        Label(self.content_frame, text="内容:").pack(side=LEFT)
        self.content_var = StringVar()
        self.content_entry = Entry(self.content_frame, textvariable=self.content_var, width=40)
        self.content_entry.pack(side=LEFT, padx=5, fill=X, expand=True)
        self.content_hint = Label(self.content_frame, text="", fg="gray")
        self.content_hint.pack(side=LEFT, padx=(5,0))

        # 关键字替换输入（仅 replace 模式显示）
        self.replace_frame = Frame(rule_frame)
        self.replace_frame.pack(fill=X, pady=5)
        Label(self.replace_frame, text="原关键字:").pack(side=LEFT)
        self.replace_from_var = StringVar()
        Entry(self.replace_frame, textvariable=self.replace_from_var, width=20).pack(side=LEFT, padx=5)
        Label(self.replace_frame, text="→ 替换为:").pack(side=LEFT)
        self.replace_to_var = StringVar()
        Entry(self.replace_frame, textvariable=self.replace_to_var, width=20).pack(side=LEFT, padx=5)

        # === 4. 文件列表预览 ===
        list_frame = LabelFrame(main_frame, text="待处理文件（最多显示20条）", padx=5, pady=5)
        list_frame.pack(fill=BOTH, expand=True, pady=5)
        self.file_listbox = Listbox(list_frame, height=8)
        scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        self.file_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # === 5. 操作按钮 ===
        btn_frame = Frame(main_frame)
        btn_frame.pack(fill=X, pady=10)
        self.rename_btn = Button(btn_frame, text="执行重命名", command=self.execute_rename,
                                 bg="#4CAF50", fg="white", height=2, state=DISABLED)
        self.rename_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        self.preview_btn = Button(btn_frame, text="刷新预览", command=self.update_preview,
                                  bg="#2196F3", fg="white", height=2)
        self.preview_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))

        # === 6. 日志区域 ===
        log_frame = LabelFrame(main_frame, text="操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, height=8)
        self.log_text.pack(fill=BOTH, expand=True)

        # 绑定事件
        self.input_type_var.trace_add("write", lambda *a: self.save_config())
        self.mode_var.trace_add("write", lambda *a: self.on_mode_change())
        self.content_var.trace_add("write", lambda *a: self.update_preview())
        self.replace_from_var.trace_add("write", lambda *a: self.update_preview())
        self.replace_to_var.trace_add("write", lambda *a: self.update_preview())

    def on_input_type_change(self):
        self.save_config()
        if self.input_type_var.get() == "files":
            self.select_btn.config(text="选择文件")
        else:
            self.select_btn.config(text="选择文件夹")

    def on_mode_change(self):
        mode = self.mode_var.get()
        # 隐藏/显示控件
        self.content_frame.pack_forget()
        self.replace_frame.pack_forget()

        if mode == "replace":
            self.replace_frame.pack(fill=X, pady=5)
            self.content_hint.config(text="")
        else:
            self.content_frame.pack(fill=X, pady=5)
            if mode == "prefix":
                self.content_hint.config(text="将添加到文件名开头")
            elif mode == "suffix":
                self.content_hint.config(text="将添加到文件名末尾（扩展名前）")
            elif mode == "split_dash":
                self.content_hint.config(text="自动移除“-”及之后内容")

        self.save_config()
        self.update_preview()

    def select_input(self):
        if self.input_type_var.get() == "files":
            files = filedialog.askopenfilenames(
                title="选择要重命名的文件",
                filetypes=[("所有文件", "*.*")]
            )
            if files:
                self.selected_files = list(files)
                self.selected_dir = ""
                self.path_label.config(text=f"已选择 {len(self.selected_files)} 个文件")
        else:
            folder = filedialog.askdirectory(title="选择包含文件的文件夹")
            if folder:
                self.selected_dir = folder
                self.selected_files = []
                self.path_label.config(text=f"文件夹: {folder}")
        self.update_file_list()
        self.save_config()

    def clear_input(self):
        self.selected_files = []
        self.selected_dir = ""
        self.path_label.config(text="未选择")
        self.update_file_list()
        self.save_config()

    def update_file_list(self):
        self.file_listbox.delete(0, END)
        files = self.get_all_files()
        for i, f in enumerate(files[:20]):
            self.file_listbox.insert(END, os.path.basename(f))
        if len(files) > 20:
            self.file_listbox.insert(END, f"... 还有 {len(files)-20} 个文件")

    def get_all_files(self):
        if self.input_type_var.get() == "files":
            return self.selected_files
        else:
            if not self.selected_dir:
                return []
            try:
                return [str(p) for p in Path(self.selected_dir).iterdir() if p.is_file()]
            except Exception as e:
                self.log(f"读取目录失败: {e}")
                return []

    def generate_new_name(self, old_path):
        old_path = Path(old_path)
        stem = old_path.stem
        suffix = old_path.suffix

        mode = self.mode_var.get()
        if mode == "prefix":
            new_stem = self.content_var.get().strip() + stem
        elif mode == "suffix":
            new_stem = stem + self.content_var.get().strip()
        elif mode == "split_dash":
            parts = stem.split("-", 1)
            new_stem = parts[0].rstrip()
        elif mode == "replace":
            from_str = self.replace_from_var.get()
            to_str = self.replace_to_var.get()
            if from_str == "":
                new_stem = stem  # 不替换
            else:
                new_stem = stem.replace(from_str, to_str)
        else:
            new_stem = stem

        return str(old_path.parent / (new_stem + suffix))

    def update_preview(self):
        self.file_listbox.delete(0, END)
        files = self.get_all_files()
        if not files:
            self.rename_btn.config(state=DISABLED)
            return

        self.rename_btn.config(state=NORMAL)
        for i, f in enumerate(files[:20]):
            new_name = self.generate_new_name(f)
            disp = f"{os.path.basename(f)} → {os.path.basename(new_name)}"
            self.file_listbox.insert(END, disp)
        if len(files) > 20:
            self.file_listbox.insert(END, f"... 共 {len(files)} 个文件")

    def log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def execute_rename(self):
        files = self.get_all_files()
        if not files:
            messagebox.showwarning("警告", "没有可处理的文件！")
            return

        # 特别检查：replace 模式下是否填写了原关键字
        if self.mode_var.get() == "replace" and not self.replace_from_var.get().strip():
            messagebox.showwarning("警告", "“关键字替换”模式下，请输入“原关键字”！")
            return

        if not messagebox.askyesno("确认", f"即将重命名 {len(files)} 个文件，是否继续？"):
            return

        success = 0
        for f in files:
            try:
                old_path = Path(f)
                new_path_str = self.generate_new_name(f)
                new_path = Path(new_path_str)

                if old_path == new_path:
                    continue

                if new_path.exists():
                    self.log(f"⚠️ 跳过（目标已存在）: {new_path.name}")
                    continue

                shutil.move(str(old_path), str(new_path))
                self.log(f"✅ 重命名: {old_path.name} → {new_path.name}")
                success += 1
            except Exception as e:
                self.log(f"❌ 失败: {f} - {e}")

        self.log(f"🎉 完成！成功重命名 {success} / {len(files)} 个文件")
        self.update_file_list()

    def on_closing(self):
        self.root.destroy()


# ================== 启动程序 ==================
if __name__ == "__main__":
    # 加载 DB_CONFIG（虽不使用）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)  # 占位，满足需求
        except:
            pass

    root = Tk()
    app = FileRenamerGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
