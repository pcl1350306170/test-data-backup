# pdf_to_images_fixed.py

import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
from threading import Thread
import subprocess
from pdf2image import convert_from_path
from PIL import Image

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "pdf_to_images"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR = CONFIG_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "last_output_dir": str(Path.home() / "Desktop"),
    "poppler_path": ""  # 可选：手动指定 poppler 路径
}

# ================== 工具函数 ==================

def load_or_create_config():
    """加载或创建配置文件"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logging.info("配置文件加载成功")
            return config
        except Exception as e:
            logging.error(f"配置文件解析失败: {e}")
            messagebox.showerror("配置错误", f"配置文件损坏，将使用默认配置。\n{e}")

    # 创建默认配置
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
    logging.info("已创建默认配置文件")
    return DEFAULT_CONFIG

def save_config(config):
    """保存配置到文件"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logging.info("配置已保存")
    except Exception as e:
        logging.error(f"保存配置失败: {e}")

def check_poppler():
    """检查 Poppler 是否可用"""
    try:
        subprocess.run(['pdftoppm', '-h'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def pdf_to_images(pdf_path: Path, output_dir: Path, poppler_path=None, progress_callback=None):
    """将PDF转换为图片"""
    try:
        # 创建以PDF文件名命名的子目录
        pdf_name = pdf_path.stem
        target_dir = output_dir / pdf_name
        target_dir.mkdir(parents=True, exist_ok=True)

        logging.info(f"开始转换: {pdf_path} -> {target_dir}")

        # 转换PDF为图片列表
        kwargs = {'dpi': 300}
        if poppler_path:
            kwargs['poppler_path'] = poppler_path

        images = convert_from_path(str(pdf_path), **kwargs)

        total = len(images)
        if total == 0:
            logging.warning(f"PDF 无页面: {pdf_path}")
            return True, 0

        for i, image in enumerate(images, 1):
            img_filename = f"{i:04d}.png"
            img_path = target_dir / img_filename
            image.save(img_path, "PNG")
            if progress_callback:
                progress_callback(i, total)

        logging.info(f"转换完成: {pdf_path} 共 {total} 页")
        return True, total
    except Exception as e:
        error_msg = f"转换失败 {pdf_path}: {e}"
        logging.error(error_msg)
        return False, str(e)

# ================== 主GUI类 ==================

class PDFToImagesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📄 PDF 转图片工具")
        self.root.geometry("700x700")
        self.root.resizable(True, True)

        self.config = load_or_create_config()
        self.pdf_files = []
        self.output_dir = Path(self.config.get("last_output_dir", str(Path.home() / "Desktop")))

        # Poppler 检查
        self.poppler_available = check_poppler()
        if not self.poppler_available:
            messagebox.showwarning("警告", "未检测到 Poppler，PDF 转换将失败。\n请安装 Poppler 并将其添加到系统 PATH。")
            logging.warning("Poppler 未安装或不可用")

        self.setup_ui()

    def setup_ui(self):
        # Poppler 状态
        status_frame = Frame(self.root)
        status_frame.pack(fill=X, padx=20, pady=5)
        status_text = "✅ Poppler 可用" if self.poppler_available else "❌ Poppler 未找到，请安装！"
        status_color = "green" if self.poppler_available else "red"
        Label(status_frame, text=status_text, fg=status_color, font=("Arial", 10, "bold")).pack(anchor=W)

        # PDF 选择区域
        frame_pdf = LabelFrame(self.root, text="1. 选择PDF文件", padx=10, pady=10)
        frame_pdf.pack(fill=X, padx=20, pady=10)

        self.pdf_listbox = Listbox(frame_pdf, height=6, selectmode=EXTENDED)
        self.pdf_listbox.pack(fill=X, pady=5)

        btn_frame = Frame(frame_pdf)
        btn_frame.pack(fill=X)
        Button(btn_frame, text="📁 添加PDF", command=self.add_pdfs).pack(side=LEFT)
        Button(btn_frame, text="🗑️ 清空", command=self.clear_pdfs).pack(side=LEFT, padx=5)

        # 输出目录区域
        frame_out = LabelFrame(self.root, text="2. 输出目录", padx=10, pady=10)
        frame_out.pack(fill=X, padx=20, pady=10)

        self.output_label = Label(frame_out, text=str(self.output_dir), fg="blue", anchor=W, wraplength=500)
        self.output_label.pack(fill=X, pady=5)
        Button(frame_out, text="📂 选择输出目录", command=self.select_output_dir).pack()

        # Poppler 路径设置（可选）
        frame_poppler = LabelFrame(self.root, text="3. Poppler 路径设置（可选）", padx=10, pady=10)
        frame_poppler.pack(fill=X, padx=20, pady=10)

        self.poppler_var = StringVar(value=self.config.get("poppler_path", ""))
        Entry(frame_poppler, textvariable=self.poppler_var, state="readonly").pack(fill=X, pady=5)
        Button(frame_poppler, text="🔧 设置 Poppler 路径", command=self.set_poppler_path).pack()

        # 转换按钮
        self.convert_btn = Button(
            self.root,
            text="🔄 开始转换",
            command=self.start_conversion,
            bg="#4CAF50",
            fg="white",
            height=2,
            state=DISABLED
        )
        self.convert_btn.pack(pady=20)

        # 进度条
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=X, padx=50, pady=5)
        self.progress_label = Label(self.root, text="", fg="gray")
        self.progress_label.pack()

    def set_poppler_path(self):
        path = filedialog.askdirectory(title="选择 Poppler 的 bin 目录")
        if path:
            if Path(path).joinpath("pdftoppm.exe").exists() or Path(path).joinpath("pdftoppm").exists():
                self.poppler_var.set(path)
                self.config["poppler_path"] = path
                save_config(self.config)
                messagebox.showinfo("成功", f"Poppler 路径已设置: {path}")
            else:
                messagebox.showerror("错误", "该目录中未找到 pdftoppm 可执行文件！")

    def add_pdfs(self):
        files = filedialog.askopenfilenames(
            title="选择一个或多个PDF文件",
            filetypes=[("PDF files", "*.pdf")]
        )
        if files:
            for f in files:
                if f not in self.pdf_files:
                    self.pdf_files.append(f)
                    self.pdf_listbox.insert(END, Path(f).name)
            self.check_ready()

    def clear_pdfs(self):
        self.pdf_files.clear()
        self.pdf_listbox.delete(0, END)
        self.check_ready()

    def select_output_dir(self):
        dir_selected = filedialog.askdirectory(initialdir=self.output_dir)
        if dir_selected:
            self.output_dir = Path(dir_selected)
            self.output_label.config(text=str(self.output_dir))
            self.config["last_output_dir"] = str(self.output_dir)
            save_config(self.config)
            self.check_ready()

    def check_ready(self):
        ready = bool(self.pdf_files and self.output_dir)
        if not self.poppler_available:
            ready = False
        self.convert_btn.config(state=NORMAL if ready else DISABLED)

    def update_progress(self, current, total):
        self.progress['value'] = (current / total) * 100
        self.progress_label.config(text=f"正在处理第 {current}/{total} 页...")
        self.root.update_idletasks()

    def start_conversion(self):
        if not self.pdf_files or not self.output_dir:
            return

        if not self.poppler_available:
            messagebox.showerror("错误", "Poppler 未安装或不可用，无法转换！")
            return

        self.convert_btn.config(state=DISABLED)
        self.progress['value'] = 0
        self.progress_label.config(text="开始转换...")

        # 在新线程中执行转换，避免界面卡死
        Thread(target=self.run_conversion, daemon=True).start()

    def run_conversion(self):
        success_count = 0
        total_files = len(self.pdf_files)
        poppler_path = self.config.get("poppler_path") or None

        for idx, pdf_path in enumerate(self.pdf_files, 1):
            self.progress_label.config(text=f"处理文件 {idx}/{total_files}: {Path(pdf_path).name}")
            self.root.update_idletasks()

            ok, info = pdf_to_images(
                Path(pdf_path),
                self.output_dir,
                poppler_path=poppler_path,
                progress_callback=lambda c, t: self.update_progress(c, t)
            )
            if ok:
                success_count += 1

        # 转换完成
        self.root.after(0, lambda: self.conversion_finished(success_count, total_files))

    def conversion_finished(self, success, total):
        self.convert_btn.config(state=NORMAL)
        self.progress['value'] = 100
        self.progress_label.config(text="✅ 转换完成！")

        msg = f"成功转换 {success}/{total} 个PDF文件！\n输出目录：{self.output_dir}"
        messagebox.showinfo("完成", msg)
        logging.info(f"批量转换完成: {success}/{total} 成功")

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = PDFToImagesApp(root)
    root.mainloop()
