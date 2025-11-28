import os
import json
import logging
from PIL import Image
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path

# ==============================
# 🧩 配置与常量
# ==============================
# 获取当前脚本所在目录的绝对路径
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))

# 配置日志记录
def setup_logger():
    logger = logging.getLogger('image_cleaner')
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(message)s')

    # 文件处理器
    file_handler = logging.FileHandler('./json/logs/delete_small_img.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()

# 配置文件处理
CONFIG_PATH = SCRIPT_DIR / "json" / "config_delete_small_img.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / "process_log_crop_logo_advanced.txt"

def load_config():
    """加载配置文件"""
    default_config = {
        "image_dir": "",
        "process_subdirs": True,
        "min_width": 800,
        "min_height": 800
    }

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载配置失败，使用默认配置: {e}")
    return default_config

def save_config(config):
    """保存配置到文件"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

# 图片处理函数
def is_image_file(filename):
    """判断是否为图片文件"""
    return filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif'))

def process_images(image_dir, process_subdirs, min_width, min_height, status_callback):
    """处理图片文件"""
    total = 0
    deleted = 0

    if not os.path.exists(image_dir):
        status_callback(f"错误: 目录不存在 - {image_dir}")
        return total, deleted

    for root, _, files in os.walk(image_dir):
        for file in files:
            if is_image_file(file):
                total += 1
                path = os.path.join(root, file)
                try:
                    with Image.open(path) as img:
                        w, h = img.size

                    status = f"检查: {os.path.basename(path)} ({w}x{h})"
                    status_callback(status)

                    if w < min_width or h < min_height:
                        os.remove(path)
                        deleted += 1
                        msg = f"已删除: {path} ({w}x{h})"
                        status_callback(msg)
                        logger.info(msg)
                    else:
                        status_callback(f"保留: {os.path.basename(path)} ({w}x{h})")
                except Exception as e:
                    err_msg = f"读取失败: {path} -> {e}"
                    status_callback(err_msg)
                    logger.warning(err_msg)

        if not process_subdirs:
            break

    return total, deleted

# 界面类
class ImageCleanerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片清理工具")
        self.root.geometry("600x500")
        self.root.resizable(True, True)

        # 加载配置
        self.config = load_config()

        # 创建界面组件
        self.create_widgets()

        # 填充配置数据
        self.fill_config_data()

    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 目录选择区域
        dir_frame = ttk.LabelFrame(main_frame, text="图片目录", padding="5")
        dir_frame.pack(fill=tk.X, pady=5)

        self.dir_var = tk.StringVar()
        ttk.Entry(dir_frame, textvariable=self.dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(dir_frame, text="浏览...", command=self.browse_directory).pack(side=tk.RIGHT, padx=5)

        # 配置区域
        config_frame = ttk.LabelFrame(main_frame, text="过滤配置", padding="5")
        config_frame.pack(fill=tk.X, pady=5)

        # 分辨率设置
        res_frame = ttk.Frame(config_frame)
        res_frame.pack(fill=tk.X, pady=5)

        ttk.Label(res_frame, text="最小宽度:").pack(side=tk.LEFT, padx=5)
        self.width_var = tk.StringVar()
        ttk.Entry(res_frame, textvariable=self.width_var, width=10).pack(side=tk.LEFT, padx=5)

        ttk.Label(res_frame, text="最小高度:").pack(side=tk.LEFT, padx=5)
        self.height_var = tk.StringVar()
        ttk.Entry(res_frame, textvariable=self.height_var, width=10).pack(side=tk.LEFT, padx=5)

        # 子目录处理
        self.subdir_var = tk.BooleanVar()
        ttk.Checkbutton(config_frame, text="处理子目录", variable=self.subdir_var).pack(anchor=tk.W, pady=5)

        # 按钮区域
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="开始清理", command=self.start_cleaning).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="保存配置", command=self.save_current_config).pack(side=tk.LEFT, padx=5)

        # 状态区域
        status_frame = ttk.LabelFrame(main_frame, text="处理状态", padding="5")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 滚动条
        scrollbar = ttk.Scrollbar(status_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 状态文本框
        self.status_text = tk.Text(status_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, height=10)
        self.status_text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.status_text.yview)

        # 结果标签
        self.result_var = tk.StringVar()
        ttk.Label(main_frame, textvariable=self.result_var).pack(fill=tk.X, pady=5)

    def fill_config_data(self):
        """填充配置数据到界面"""
        self.dir_var.set(self.config.get("image_dir", ""))
        self.width_var.set(str(self.config.get("min_width", 800)))
        self.height_var.set(str(self.config.get("min_height", 800)))
        self.subdir_var.set(self.config.get("process_subdirs", True))

    def browse_directory(self):
        """浏览选择目录"""
        directory = filedialog.askdirectory()
        if directory:
            self.dir_var.set(directory)

    def save_current_config(self):
        """保存当前配置"""
        try:
            new_config = {
                "image_dir": self.dir_var.get(),
                "process_subdirs": self.subdir_var.get(),
                "min_width": int(self.width_var.get()),
                "min_height": int(self.height_var.get())
            }

            save_config(new_config)
            self.config = new_config
            messagebox.showinfo("成功", "配置已保存")
        except ValueError:
            messagebox.showerror("错误", "分辨率必须是整数")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def update_status(self, message):
        """更新状态文本框"""
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.root.update_idletasks()

    def start_cleaning(self):
        """开始清理图片"""
        try:
            # 验证输入
            image_dir = self.dir_var.get()
            if not image_dir:
                messagebox.showerror("错误", "请选择图片目录")
                return

            try:
                min_width = int(self.width_var.get())
                min_height = int(self.height_var.get())
                if min_width <= 0 or min_height <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("错误", "分辨率必须是正整数")
                return

            process_subdirs = self.subdir_var.get()

            # 清空状态
            self.status_text.delete(1.0, tk.END)
            self.update_status("开始处理图片...")

            # 保存当前配置
            self.save_current_config()

            # 处理图片
            total, deleted = process_images(
                image_dir,
                process_subdirs,
                min_width,
                min_height,
                self.update_status
            )

            # 显示结果
            result_msg = f"处理完成 - 共检查 {total} 张图片，删除 {deleted} 张"
            self.result_var.set(result_msg)
            self.update_status(result_msg)
            messagebox.showinfo("完成", result_msg)

        except Exception as e:
            error_msg = f"处理过程中出错: {str(e)}"
            self.update_status(error_msg)
            messagebox.showerror("错误", error_msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCleanerApp(root)
    root.mainloop()
