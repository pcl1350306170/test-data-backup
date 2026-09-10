import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime
import base64
import fractions
import logging
from logging.handlers import RotatingFileHandler

# 获取脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 配置文件和输出文件路径（与脚本平级的json目录）
JSON_DIR = os.path.join(SCRIPT_DIR, "json")
CONFIG_FILE = os.path.join(JSON_DIR, "extract_exif_config.json")
OUTPUT_FILE = os.path.join(JSON_DIR, "exif_data.json")

# 初始化日志
def init_logger():
    log_dir = os.path.join(JSON_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "exif_extractor.log")

    # 创建日志处理器，限制文件大小为1MB，保留3个备份
    handler = RotatingFileHandler(
        log_file,
        maxBytes=1*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )

    # 日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # 配置根日志
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    return logger

# 初始化日志
logger = init_logger()

class ExifExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EXIF 数据提取工具")
        self.root.geometry("700x400")

        # 默认配置
        self.default_config = {
            "source_dir": r"D:\book\img",
            "process_subdirs": True
        }
        self.current_config = self.default_config.copy()

        # 创建界面
        self.create_widgets()

        # 确保json目录存在
        self.ensure_dir_exists(JSON_DIR)

        # 加载配置
        self.load_config()

    def create_widgets(self):
        # 输入目录选择
        frame_dir = ttk.Frame(self.root, padding="10")
        frame_dir.pack(fill=tk.X, padx=10)

        ttk.Label(frame_dir, text="图片目录:").pack(side=tk.LEFT, padx=5)

        self.dir_var = tk.StringVar(value=self.current_config["source_dir"])
        ttk.Entry(frame_dir, textvariable=self.dir_var, width=50).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        ttk.Button(frame_dir, text="浏览...", command=self.browse_dir).pack(side=tk.LEFT, padx=5)

        # 递归处理选项
        frame_recursive = ttk.Frame(self.root, padding="10")
        frame_recursive.pack(fill=tk.X, padx=10)

        self.recursive_var = tk.BooleanVar(value=self.current_config["process_subdirs"])
        ttk.Checkbutton(
            frame_recursive,
            text="递归处理子目录",
            variable=self.recursive_var
        ).pack(anchor=tk.W)

        # 日志显示区域
        frame_log = ttk.Frame(self.root, padding="10")
        frame_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(frame_log, text="执行日志:").pack(anchor=tk.W)
        self.log_text = tk.Text(frame_log, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text.config(state=tk.DISABLED)

        # 状态显示
        self.status_var = tk.StringVar(value="就绪")
        frame_status = ttk.Frame(self.root, padding="10")
        frame_status.pack(fill=tk.X, padx=10)

        ttk.Label(frame_status, textvariable=self.status_var).pack(anchor=tk.W)

        # 按钮区域
        frame_buttons = ttk.Frame(self.root, padding="10")
        frame_buttons.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(
            frame_buttons,
            text="保存配置",
            command=self.save_config
        ).pack(side=tk.LEFT, padx=10)

        ttk.Button(
            frame_buttons,
            text="提取EXIF数据",
            command=self.start_extraction
        ).pack(side=tk.RIGHT, padx=10)

    def browse_dir(self):
        dir_path = filedialog.askdirectory(
            title="选择图片目录",
            initialdir=self.dir_var.get()
        )
        if dir_path:
            self.dir_var.set(dir_path)
            self.log(f"已选择图片目录: {dir_path}")

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.current_config.update(config)
                self.log(f"已加载配置: {CONFIG_FILE}")
                logger.info(f"已加载配置: {CONFIG_FILE}")
        except Exception as e:
            error_msg = f"无法加载配置文件: {str(e)}\n将使用默认配置"
            messagebox.showwarning("配置加载失败", error_msg)
            self.log(error_msg)
            logger.warning(error_msg)

    def save_config(self):
        try:
            # 更新当前配置
            self.current_config = {
                "source_dir": self.dir_var.get(),
                "process_subdirs": self.recursive_var.get()
            }

            # 保存配置
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.current_config, f, ensure_ascii=False, indent=4)

            success_msg = f"配置已保存到: {CONFIG_FILE}"
            messagebox.showinfo("成功", success_msg)
            self.log(success_msg)
            logger.info(success_msg)
        except Exception as e:
            error_msg = f"无法保存配置文件: {str(e)}"
            messagebox.showerror("保存失败", error_msg)
            self.log(error_msg)
            logger.error(error_msg)

    def ensure_dir_exists(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            self.log(f"确保目录存在: {path}")
            logger.info(f"确保目录存在: {path}")
        except Exception as e:
            error_msg = f"创建目录失败 {path}: {str(e)}"
            self.log(error_msg)
            logger.error(error_msg)
            messagebox.showerror("目录错误", error_msg)

    def log(self, message):
        """在界面日志区域显示消息"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)  # 滚动到最新日志
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()  # 刷新界面

    def convert_to_serializable(self, value):
        try:
            if isinstance(value, bytes):
                return base64.b64encode(value).decode('utf-8')
            elif isinstance(value, datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(value, fractions.Fraction):
                return float(value)
            elif isinstance(value, dict):
                return {k: self.convert_to_serializable(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [self.convert_to_serializable(v) for v in value]
            elif isinstance(value, tuple):
                return [self.convert_to_serializable(v) for v in value]
            elif isinstance(value, set):
                return [self.convert_to_serializable(v) for v in value]
            elif value is None:
                return None
            else:
                return value
        except Exception as e:
            error_msg = f"跳过无法解析的字段: {e}"
            self.log(error_msg)
            logger.warning(error_msg)
            return None

    def get_exif_data(self, image_path):
        try:
            # 尝试打开图片
            with Image.open(image_path) as image:
                # 检查图片格式是否支持EXIF
                if image.format not in ['JPEG', 'TIFF', 'PNG', 'WEBP']:
                    warn_msg = f"不支持的图片格式 {image.format}，无法提取EXIF: {image_path}"
                    self.log(warn_msg)
                    logger.warning(warn_msg)
                    return None

                # 获取EXIF数据
                exif_data = image._getexif()
                if exif_data is None:
                    info_msg = f"未找到EXIF数据: {os.path.basename(image_path)}"
                    self.log(info_msg)
                    logger.info(info_msg)
                    return None

                # 转换为可读格式
                exif_dict = {}
                for tag, value in exif_data.items():
                    tag_name = TAGS.get(tag, tag)
                    exif_dict[tag_name] = self.convert_to_serializable(value)

                info_msg = f"成功提取EXIF数据: {os.path.basename(image_path)}"
                self.log(info_msg)
                logger.info(info_msg)
                return exif_dict

        except Exception as e:
            error_msg = f"读取EXIF数据失败 {os.path.basename(image_path)}: {str(e)}"
            self.log(error_msg)
            logger.error(error_msg)
            return None

    def get_all_images(self, root_dir, process_subdirs):
        image_files = []
        image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif')

        try:
            if not os.path.isdir(root_dir):
                error_msg = f"源目录不存在: {root_dir}"
                self.log(error_msg)
                logger.error(error_msg)
                return []

            self.log(f"开始扫描图片文件，递归: {process_subdirs}")
            logger.info(f"开始扫描图片文件，目录: {root_dir}, 递归: {process_subdirs}")

            for root, _, files in os.walk(root_dir):
                dir_rel = os.path.relpath(root, root_dir)
                self.log(f"扫描目录: {dir_rel} (文件数: {len(files)})")

                for file in files:
                    if file.lower().endswith(image_extensions):
                        full_path = os.path.join(root, file)
                        image_files.append(full_path)

            info_msg = f"扫描完成，找到图片文件总数: {len(image_files)}"
            self.log(info_msg)
            logger.info(info_msg)
            return image_files

        except Exception as e:
            error_msg = f"扫描图片文件失败: {str(e)}"
            self.log(error_msg)
            logger.error(error_msg)
            return []

    def start_extraction(self):
        source_dir = self.dir_var.get()
        process_subdirs = self.recursive_var.get()

        # 验证输入目录
        if not os.path.isdir(source_dir):
            error_msg = f"目录不存在: {source_dir}"
            messagebox.showerror("错误", error_msg)
            self.log(error_msg)
            logger.error(error_msg)
            return

        try:
            self.status_var.set("正在初始化...")
            self.log("===== 开始提取EXIF数据 =====")
            logger.info("===== 开始提取EXIF数据 =====")

            # 确保输出目录存在
            self.ensure_dir_exists(JSON_DIR)

            # 获取所有图片文件
            self.status_var.set("正在扫描图片文件...")
            image_paths = self.get_all_images(source_dir, process_subdirs)

            if not image_paths:
                warn_msg = "未找到任何图片文件"
                self.status_var.set(warn_msg)
                self.log(warn_msg)
                logger.warning(warn_msg)
                messagebox.showwarning("警告", warn_msg)
                return

            exif_data_list = []
            total = len(image_paths)
            self.status_var.set(f"开始处理 {total} 个文件...")

            # 处理每个图片
            for i, img_path in enumerate(image_paths, 1):
                self.status_var.set(f"正在处理 {i}/{total}: {os.path.basename(img_path)}")
                exif_data = self.get_exif_data(img_path)

                if exif_data is not None:
                    exif_data_list.append({
                        "file_path": img_path,
                        "exif_data": exif_data
                    })

            # 保存结果
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(exif_data_list, f, ensure_ascii=False, indent=4)

            # 处理完成
            result_msg = f"✅ 完成！共处理 {total} 个文件，成功提取 {len(exif_data_list)} 个EXIF数据"
            self.status_var.set(result_msg)
            self.log(result_msg)
            self.log(f"结果已保存到: {OUTPUT_FILE}")
            logger.info(result_msg)
            messagebox.showinfo("成功", f"{result_msg}\n结果已保存到: {OUTPUT_FILE}")

        except Exception as e:
            error_msg = f"提取过程出错: {str(e)}"
            self.status_var.set("提取失败")
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            messagebox.showerror("错误", error_msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = ExifExtractorApp(root)
    root.mainloop()
