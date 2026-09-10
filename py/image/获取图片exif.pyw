# exif_extractor.py

import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
from threading import Thread
from PIL import Image
from PIL.ExifTags import TAGS

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "exif_extractor"
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

# 支持的图片格式（注意：PNG 不支持标准 EXIF，但部分工具写入 XMP）
SUPPORTED_EXTS = {'.jpg', '.jpeg', '.tiff', '.tif', '.webp'}

# 默认配置
DEFAULT_CONFIG = {
    "last_output_dir": str(Path.home() / "Desktop"),
    "include_subdirs": True
}

# ================== 工具函数 ==================

def load_or_create_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logging.info("配置文件加载成功")
            return config
        except Exception as e:
            logging.error(f"配置文件解析失败: {e}")
            messagebox.showerror("配置错误", f"配置文件损坏，将使用默认配置。\n{e}")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
    logging.info("已创建默认配置文件")
    return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logging.info("配置已保存")
    except Exception as e:
        logging.error(f"保存配置失败: {e}")

def get_image_paths_from_files(file_list):
    """从文件列表中筛选出支持 EXIF 的图片"""
    images = []
    for f in file_list:
        p = Path(f)
        if p.suffix.lower() in SUPPORTED_EXTS:
            images.append(p)
    return images

def get_image_paths_from_folder(folder: Path, include_subdirs: bool):
    """从文件夹中获取所有支持 EXIF 的图片路径"""
    pattern = "**/*" if include_subdirs else "*"
    images = []
    for ext in SUPPORTED_EXTS:
        images.extend(folder.glob(f"{pattern}{ext}"))
        images.extend(folder.glob(f"{pattern}{ext.upper()}"))
    return sorted(set(images))

def extract_exif(image_path: Path):
    """提取单张图片的 EXIF 信息，返回格式化字符串"""
    try:
        image = Image.open(image_path)
        exifdata = image.getexif()
        if not exifdata:
            return "无 EXIF 信息"

        lines = []
        for tag_id, value in exifdata.items():
            tag = TAGS.get(tag_id, tag_id)
            # 处理字节数据（如 MakerNote）
            if isinstance(value, bytes):
                try:
                    value = value.decode('utf-8', errors='replace')
                except:
                    value = "<二进制数据>"
            lines.append(f"  {tag}: {value}")
        return "\n".join(lines) if lines else "EXIF 存在但无有效标签"
    except Exception as e:
        return f"读取失败: {str(e)}"

def process_images(image_paths, output_txt: Path, progress_callback=None):
    """批量提取 EXIF 并写入 TXT"""
    try:
        total = len(image_paths)
        with open(output_txt, 'w', encoding='utf-8') as f:
            f.write(f"# EXIF 信息提取结果\n")
            f.write(f"# 共 {total} 张图片\n")
            f.write("=" * 60 + "\n\n")

            for i, img_path in enumerate(image_paths, 1):
                f.write(f"📁 文件: {img_path}\n")
                exif_str = extract_exif(img_path)
                f.write(f"{exif_str}\n")
                f.write("-" * 60 + "\n\n")

                logging.info(f"已处理: {img_path}")
                if progress_callback:
                    progress_callback(i, total)

        logging.info(f"EXIF 结果已保存至: {output_txt}")
        return True, total

    except Exception as e:
        logging.error(f"批量处理失败: {e}")
        return False, str(e)

# ================== 主GUI类 ==================

class EXIFExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📸 图片 EXIF 信息提取工具")
        self.root.geometry("720x520")
        self.root.resizable(True, True)

        self.config = load_or_create_config()
        self.image_paths = []
        self.output_dir = Path(self.config.get("last_output_dir", str(Path.home() / "Desktop")))
        self.include_subdirs = BooleanVar(value=self.config.get("include_subdirs", True))

        self.setup_ui()

    def setup_ui(self):
        # 输入方式选择
        frame_mode = LabelFrame(self.root, text="1. 选择输入方式", padx=10, pady=10)
        frame_mode.pack(fill=X, padx=20, pady=10)

        Button(frame_mode, text="📁 选择图片文件", command=self.select_files, width=15).pack(side=LEFT, padx=5)
        Button(frame_mode, text="📂 选择文件夹", command=self.select_folder, width=15).pack(side=LEFT, padx=5)

        # 当前选中文件显示
        self.file_label = Label(self.root, text="未选择任何图片", fg="gray", wraplength=650, justify=LEFT)
        self.file_label.pack(pady=5)

        # 子目录选项
        check_frame = Frame(self.root)
        check_frame.pack(pady=5)
        Checkbutton(
            check_frame,
            text="包含子目录",
            variable=self.include_subdirs,
            command=self.on_subdir_change
        ).pack()

        # 输出目录
        frame_out = LabelFrame(self.root, text="2. 输出目录", padx=10, pady=10)
        frame_out.pack(fill=X, padx=20, pady=10)

        self.output_label = Label(frame_out, text=str(self.output_dir), fg="blue", anchor=W, wraplength=500)
        self.output_label.pack(fill=X, pady=5)
        Button(frame_out, text="📂 设置输出目录", command=self.select_output_dir).pack()

        # 开始按钮
        self.run_btn = Button(
            self.root,
            text="🔍 提取 EXIF 信息",
            command=self.start_extraction,
            bg="#4A90E2",
            fg="white",
            height=2,
            state=DISABLED
        )
        self.run_btn.pack(pady=20)

        # 进度条
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=X, padx=50, pady=5)
        self.progress_label = Label(self.root, text="", fg="gray")
        self.progress_label.pack()

    def on_subdir_change(self):
        self.config["include_subdirs"] = self.include_subdirs.get()
        save_config(self.config)

    def select_files(self):
        files = filedialog.askopenfilenames(
            title="选择一个或多个图片（仅 JPG/JPEG/TIFF/WEBP）",
            filetypes=[
                ("支持 EXIF 的图片", "*.jpg *.jpeg *.tiff *.tif *.webp"),
                ("所有文件", "*.*")
            ]
        )
        if files:
            self.image_paths = get_image_paths_from_files(files)
            self.update_file_label()

    def select_folder(self):
        folder = filedialog.askdirectory(title="选择图片文件夹")
        if folder:
            folder_path = Path(folder)
            self.image_paths = get_image_paths_from_folder(folder_path, self.include_subdirs.get())
            self.update_file_label()

    def update_file_label(self):
        count = len(self.image_paths)
        if count == 0:
            text = "❌ 未找到支持 EXIF 的图片（仅支持 JPG/JPEG/TIFF/WEBP）"
            color = "red"
        else:
            sample = "\n".join([str(p.name) for p in self.image_paths[:3]])
            more = f"... 等 {count} 个文件" if count > 3 else ""
            text = f"✅ 已选择 {count} 个图片:\n{sample}{more}"
            color = "green"
        self.file_label.config(text=text, fg=color)
        self.run_btn.config(state=NORMAL if count > 0 else DISABLED)

    def select_output_dir(self):
        dir_selected = filedialog.askdirectory(initialdir=self.output_dir)
        if dir_selected:
            self.output_dir = Path(dir_selected)
            self.output_label.config(text=str(self.output_dir))
            self.config["last_output_dir"] = str(self.output_dir)
            save_config(self.config)

    def update_progress(self, current, total):
        self.progress['value'] = (current / total) * 100
        self.progress_label.config(text=f"正在处理第 {current}/{total} 张...")
        self.root.update_idletasks()

    def start_extraction(self):
        if not self.image_paths or not self.output_dir:
            return

        output_txt = self.output_dir / f"exif_results_{SCRIPT_NAME}.txt"

        self.run_btn.config(state=DISABLED)
        self.progress['value'] = 0
        self.progress_label.config(text="开始提取 EXIF...")

        Thread(target=self.run_extraction, args=(output_txt,), daemon=True).start()

    def run_extraction(self, output_txt):
        ok, info = process_images(
            self.image_paths,
            output_txt,
            progress_callback=lambda c, t: self.update_progress(c, t)
        )
        self.root.after(0, lambda: self.extraction_finished(ok, output_txt, info))

    def extraction_finished(self, success, output_path, info):
        self.run_btn.config(state=NORMAL)
        self.progress['value'] = 100

        if success:
            self.progress_label.config(text="✅ EXIF 提取完成！")
            messagebox.showinfo("完成", f"EXIF 信息已保存至：\n{output_path}")
            logging.info(f"任务成功完成，结果文件: {output_path}")
        else:
            self.progress_label.config(text="❌ 提取失败！")
            messagebox.showerror("错误", f"处理过程中出错：\n{info}")
            logging.error(f"任务失败: {info}")

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = EXIFExtractorApp(root)
    root.mainloop()
