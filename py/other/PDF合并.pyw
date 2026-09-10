# merge_pdfs.pyw

import os
import json
import logging
import threading
import time
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk
from PyPDF2 import PdfWriter, PdfReader
from PyPDF2.errors import PdfReadError

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "merge_pdfs"
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
    "input_files": [],
    "output_dir": str(Path.home() / "Documents"),
}

# 全局控制事件
stop_event = threading.Event()
pause_event = threading.Event()
pause_event.set()  # 初始为运行状态

# ==============================
# 核心合并函数
# ==============================
def merge_pdfs(pdf_paths, output_path):
    """合并多个 PDF 为一个"""
    try:
        writer = PdfWriter()
        total_pages = 0

        for pdf_path in pdf_paths:
            if stop_event.is_set():
                return False, "用户已停止"

            # 检查暂停
            while not pause_event.is_set() and not stop_event.is_set():
                time.sleep(0.1)
            if stop_event.is_set():
                return False, "用户已停止"

            try:
                with open(pdf_path, "rb") as f:
                    reader = PdfReader(f)
                    page_count = len(reader.pages)
                    for page in reader.pages:
                        writer.add_page(page)
                    total_pages += page_count
                    logger.info(f"已添加 {pdf_path.name} ({page_count} 页)")
            except Exception as e:
                error_msg = f"读取 {pdf_path.name} 失败: {e}"
                logger.error(error_msg)
                return False, error_msg

        # 写入输出文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as out_file:
            writer.write(out_file)

        return True, f"成功合并 {len(pdf_paths)} 个 PDF，共 {total_pages} 页"

    except Exception as e:
        logger.error(f"合并过程异常: {e}")
        return False, str(e)

# ==============================
# GUI 主类
# ==============================
class MergePdfsGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📚 多 PDF 合并工具")
        self.root.geometry("720x500")
        self.root.resizable(True, True)

        self.config = load_config()
        self.running = False
        self.setup_ui()

    def setup_ui(self):
        # 输入文件
        input_frame = LabelFrame(self.root, text="📂 选择要合并的 PDF 文件（支持多选）", padx=10, pady=8)
        input_frame.pack(fill=X, padx=10, pady=5)
        self.input_listbox = Listbox(input_frame, selectmode=EXTENDED, height=6)
        self.input_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = Scrollbar(input_frame, orient=VERTICAL, command=self.input_listbox.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.input_listbox.config(yscrollcommand=scrollbar.set)

        btn_frame = Frame(input_frame)
        btn_frame.pack(side=RIGHT, padx=(10, 0))
        Button(btn_frame, text="➕ 添加", command=self.add_files).pack(pady=2)
        Button(btn_frame, text="🗑️ 删除", command=self.remove_files).pack(pady=2)
        Button(btn_frame, text="🧹 清空", command=self.clear_files).pack(pady=2)

        # 输出目录
        output_frame = LabelFrame(self.root, text="📁 输出目录", padx=10, pady=8)
        output_frame.pack(fill=X, padx=10, pady=5)
        self.output_dir_var = StringVar(value=self.config["output_dir"])
        Entry(output_frame, textvariable=self.output_dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(output_frame, text="📁 浏览", command=self.browse_output_dir).pack(side=RIGHT, padx=(5, 0))

        # 输出文件名（可选）
        name_frame = LabelFrame(self.root, text="📄 输出文件名（不含扩展名）", padx=10, pady=8)
        name_frame.pack(fill=X, padx=10, pady=5)
        self.output_name_var = StringVar(value="merged_output")
        Entry(name_frame, textvariable=self.output_name_var, font=("Consolas", 9)).pack(fill=X)

        # 控制按钮
        control_frame = Frame(self.root)
        control_frame.pack(pady=10)
        self.start_btn = Button(control_frame, text="▶️ 开始", command=self.start_merge, bg="#4CAF50", fg="white", width=10)
        self.start_btn.pack(side=LEFT, padx=5)
        self.pause_btn = Button(control_frame, text="⏸️ 暂停", command=self.toggle_pause, bg="#FF9800", fg="white", width=10, state=DISABLED)
        self.pause_btn.pack(side=LEFT, padx=5)
        self.stop_btn = Button(control_frame, text="⏹️ 停止", command=self.stop_merge, bg="#F44336", fg="white", width=10, state=DISABLED)
        self.stop_btn.pack(side=LEFT, padx=5)

        # 日志显示
        log_frame = LabelFrame(self.root, text="📋 操作日志", padx=10, pady=8)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.log_text = Text(log_frame, wrap=WORD, height=10, state=DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)
        log_scroll = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

        # 初始化文件列表
        for f in self.config.get("input_files", []):
            if Path(f).exists():
                self.input_listbox.insert(END, f)

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 PDF 文件",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
        )
        for f in files:
            self.input_listbox.insert(END, f)

    def remove_files(self):
        selected = list(self.input_listbox.curselection())
        for index in reversed(selected):
            self.input_listbox.delete(index)

    def clear_files(self):
        self.input_listbox.delete(0, END)

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir_var.get())
        if folder:
            self.output_dir_var.set(folder)

    def log_message(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def start_merge(self):
        files = [Path(self.input_listbox.get(i)) for i in range(self.input_listbox.size())]
        output_dir = Path(self.output_dir_var.get().strip())
        output_name = self.output_name_var.get().strip()

        if not files:
            messagebox.showwarning("警告", "请至少选择一个 PDF 文件！")
            return
        if not output_dir:
            messagebox.showwarning("警告", "请指定输出目录！")
            return
        if not output_name:
            messagebox.showwarning("警告", "输出文件名不能为空！")
            return

        # 验证文件存在
        missing = [f for f in files if not f.exists()]
        if missing:
            messagebox.showerror("错误", f"以下文件不存在：\n" + "\n".join(str(f) for f in missing))
            return

        # 构造完整输出路径
        output_path = output_dir / f"{output_name}.pdf"
        if output_path.exists():
            if not messagebox.askyesno("覆盖确认", f"输出文件已存在：\n{output_path}\n是否覆盖？"):
                return

        # 保存配置
        current_config = {
            "input_files": [str(f) for f in files],
            "output_dir": str(output_dir),
        }
        save_config(current_config)

        # 重置事件
        global stop_event, pause_event
        stop_event.clear()
        pause_event.set()

        # 更新 UI
        self.start_btn.config(state=DISABLED)
        self.pause_btn.config(state=NORMAL)
        self.stop_btn.config(state=NORMAL)
        self.status_var.set("正在合并...")

        # 启动后台线程
        thread = threading.Thread(
            target=self.run_merge,
            args=(files, output_path),
            daemon=True
        )
        thread.start()

    def run_merge(self, files, output_path):
        success, msg = merge_pdfs(files, output_path)
        self.root.after(0, self.finalize_merge, success, msg, output_path)

    def finalize_merge(self, success, msg, output_path):
        global stop_event
        stop_event.set()

        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)

        if success:
            self.status_var.set("✅ 合并完成！")
            self.log_message(f"✅ {msg}")
            self.log_message(f"输出文件: {output_path}")
            messagebox.showinfo("成功", f"PDF 合并完成！\n{output_path}")
        else:
            self.status_var.set("❌ 合并失败")
            self.log_message(f"❌ {msg}")
            messagebox.showerror("错误", f"合并失败：\n{msg}")

    def toggle_pause(self):
        global pause_event
        if pause_event.is_set():
            pause_event.clear()
            self.pause_btn.config(text="▶️ 继续")
            self.status_var.set("⏸️ 已暂停")
        else:
            pause_event.set()
            self.pause_btn.config(text="⏸️ 暂停")
            self.status_var.set("▶️ 恢复中...")

    def stop_merge(self):
        global stop_event
        stop_event.set()
        self.start_btn.config(state=NORMAL)
        self.pause_btn.config(state=DISABLED)
        self.stop_btn.config(state=DISABLED)
        self.status_var.set("⏹️ 已停止")
        self.log_message("用户已停止合并。")

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

    # 检查依赖
    try:
        from PyPDF2 import PdfWriter
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 PyPDF2:\npip install PyPDF2")
        exit(1)

    root = Tk()
    app = MergePdfsGUI(root)
    root.mainloop()
