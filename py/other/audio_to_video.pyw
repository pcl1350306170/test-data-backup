# audio_to_video.pyw

import os
import json
import logging
import subprocess
from pathlib import Path
from tkinter import *
from tkinter import messagebox, filedialog, ttk

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "audio_to_video"
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
    "ffmpeg_path": r"D:\TOOLS\ffmpeg\ffmpeg.exe",
    "audio_file": "",
    "image_file": "",
    "output_dir": r"D:\FILES\视音频",
    "output_filename": ""
}

# 支持的文件类型
AUDIO_EXTENSIONS = [("Audio Files", "*.wav *.mp3 *.flac *.aac"), ("All Files", "*.*")]
IMAGE_EXTENSIONS = [("Image Files", "*.jpg *.jpeg *.png *.bmp"), ("All Files", "*.*")]

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

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def run_ffmpeg(ffmpeg_path, image_path, audio_path, output_path):
    """执行 FFmpeg 转换命令"""
    cmd = [
        ffmpeg_path,
        "-loop", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "192k",
        "-y",  # 覆盖输出文件
        str(output_path)
    ]

    logger.info(f"执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=3600  # 最长1小时
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown FFmpeg error"
            raise RuntimeError(f"FFmpeg 转换失败:\n{error_msg}")
        return True
    except subprocess.TimeoutExpired:
        raise RuntimeError("FFmpeg 转换超时（超过1小时）")
    except FileNotFoundError:
        raise RuntimeError("FFmpeg 未找到，请检查路径是否正确")
    except Exception as e:
        raise RuntimeError(f"执行 FFmpeg 时发生错误: {e}")

# ==============================
# GUI 主类
# ==============================
class AudioToVideoGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 音频转视频工具")
        self.root.geometry("650x420")
        self.root.resizable(False, False)

        self.config = load_config()
        self.setup_ui()

    def setup_ui(self):
        # FFmpeg 路径
        ffmpeg_frame = LabelFrame(self.root, text="🛠️ FFmpeg 路径", padx=10, pady=8)
        ffmpeg_frame.pack(fill=X, padx=10, pady=5)
        self.ffmpeg_var = StringVar(value=self.config["ffmpeg_path"])
        Entry(ffmpeg_frame, textvariable=self.ffmpeg_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(ffmpeg_frame, text="📁 浏览", command=self.browse_ffmpeg).pack(side=RIGHT, padx=(5, 0))

        # 音频文件
        audio_frame = LabelFrame(self.root, text="🎵 音频文件 (.wav/.mp3/.flac/.aac)", padx=10, pady=8)
        audio_frame.pack(fill=X, padx=10, pady=5)
        self.audio_var = StringVar(value=self.config["audio_file"])
        Entry(audio_frame, textvariable=self.audio_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(audio_frame, text="📁 浏览", command=self.browse_audio).pack(side=RIGHT, padx=(5, 0))

        # 静态图片
        image_frame = LabelFrame(self.root, text="🖼️ 静态图片 (.jpg/.png/.bmp)", padx=10, pady=8)
        image_frame.pack(fill=X, padx=10, pady=5)
        self.image_var = StringVar(value=self.config["image_file"])
        Entry(image_frame, textvariable=self.image_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(image_frame, text="📁 浏览", command=self.browse_image).pack(side=RIGHT, padx=(5, 0))

        # 输出设置
        output_frame = LabelFrame(self.root, text="📤 输出设置", padx=10, pady=8)
        output_frame.pack(fill=X, padx=10, pady=5)

        Label(output_frame, text="输出目录:", anchor=W).grid(row=0, column=0, sticky=W, padx=(0, 5))
        self.output_dir_var = StringVar(value=self.config["output_dir"])
        dir_entry = Entry(output_frame, textvariable=self.output_dir_var, font=("Consolas", 9))
        dir_entry.grid(row=0, column=1, sticky=EW, padx=(0, 5))
        Button(output_frame, text="📁 选择", command=self.browse_output_dir).grid(row=0, column=2)

        Label(output_frame, text="文件名 (不含扩展名):", anchor=W).grid(row=1, column=0, sticky=W, pady=(5,0))
        self.filename_var = StringVar(value=self.config["output_filename"])
        filename_entry = Entry(output_frame, textvariable=self.filename_var, font=("Consolas", 9))
        filename_entry.grid(row=1, column=1, sticky=EW, pady=(5,0))
        Label(output_frame, text=".mp4").grid(row=1, column=2, sticky=W, padx=(5,0))

        output_frame.columnconfigure(1, weight=1)

        # 按钮区域
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        self.convert_btn = Button(btn_frame, text="🎬 开始转换", command=self.start_conversion,
                                  bg="#4CAF50", fg="white", width=15, height=2, font=("微软雅黑", 10, "bold"))
        self.convert_btn.pack()

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_label = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue")
        status_label.pack(side=BOTTOM, fill=X)

    def browse_ffmpeg(self):
        path = filedialog.askopenfilename(
            title="选择 FFmpeg 可执行文件",
            initialdir=Path(self.ffmpeg_var.get()).parent if self.ffmpeg_var.get() else None,
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
        )
        if path:
            self.ffmpeg_var.set(path)

    def browse_audio(self):
        path = filedialog.askopenfilename(
            title="选择音频文件",
            initialdir=Path(self.audio_var.get()).parent if self.audio_var.get() else None,
            filetypes=AUDIO_EXTENSIONS
        )
        if path:
            self.audio_var.set(path)
            # 自动填充输出文件名（不含扩展名）
            if not self.filename_var.get():
                stem = Path(path).stem
                self.filename_var.set(stem)

    def browse_image(self):
        path = filedialog.askopenfilename(
            title="选择静态图片",
            initialdir=Path(self.image_var.get()).parent if self.image_var.get() else None,
            filetypes=IMAGE_EXTENSIONS
        )
        if path:
            self.image_var.set(path)

    def browse_output_dir(self):
        folder = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=self.output_dir_var.get() or None
        )
        if folder:
            self.output_dir_var.set(folder)

    def validate_inputs(self):
        """验证所有输入"""
        ffmpeg_path = self.ffmpeg_var.get().strip()
        audio_file = self.audio_var.get().strip()
        image_file = self.image_var.get().strip()
        output_dir = self.output_dir_var.get().strip()
        filename = self.filename_var.get().strip()

        if not ffmpeg_path:
            raise ValueError("请指定 FFmpeg 路径")
        if not Path(ffmpeg_path).exists():
            raise ValueError("FFmpeg 路径不存在")

        if not audio_file:
            raise ValueError("请选择音频文件")
        if not Path(audio_file).exists():
            raise ValueError("音频文件不存在")

        if not image_file:
            raise ValueError("请选择静态图片")
        if not Path(image_file).exists():
            raise ValueError("图片文件不存在")

        if not output_dir:
            raise ValueError("请指定输出目录")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if not filename:
            raise ValueError("请输入输出文件名")

        return ffmpeg_path, audio_file, image_file, output_dir, filename

    def start_conversion(self):
        try:
            ffmpeg_path, audio_file, image_file, output_dir, filename = self.validate_inputs()

            # 构建输出路径
            output_path = Path(output_dir) / f"{filename}.mp4"

            # 保存配置
            current_config = {
                "ffmpeg_path": ffmpeg_path,
                "audio_file": audio_file,
                "image_file": image_file,
                "output_dir": output_dir,
                "output_filename": filename
            }
            save_config(current_config)

            # 更新状态
            self.convert_btn.config(state=DISABLED)
            self.status_var.set("🔄 正在转换...")
            self.root.update()

            # 执行转换
            run_ffmpeg(ffmpeg_path, image_file, audio_file, output_path)

            # 转换成功
            self.status_var.set("✅ 转换成功！")
            logger.info(f"转换完成: {output_path}")

            # 弹出提示
            if messagebox.askyesno("成功", f"视频已生成！\n\n{output_path}\n\n是否打开所在文件夹？"):
                os.startfile(output_path.parent)

        except Exception as e:
            error_msg = str(e)
            self.status_var.set("❌ 转换失败")
            logger.error(f"转换失败: {error_msg}")
            messagebox.showerror("错误", error_msg)
        finally:
            self.convert_btn.config(state=NORMAL)

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    # 按要求引入 DB_CONFIG（即使不用）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)
        except Exception as e:
            pass  # 忽略 DB 加载错误

    root = Tk()
    app = AudioToVideoGUI(root)
    root.mainloop()
