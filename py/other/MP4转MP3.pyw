# mp4_to_mp3_converter.pyw

import os
import sys
import json
import logging
import threading
import subprocess
from pathlib import Path
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ================== 配置与常量 ==================
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "mp4_to_mp3_converter"  # 脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR = SCRIPT_DIR / "json" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

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
class MP4ToMP3Converter:
    def __init__(self, root):
        self.root = root
        self.root.title("MP4 转 MP3 转换器（支持多线程 + FFmpeg）")
        self.root.geometry("800x600")
        self.root.minsize(700, 550)

        # 控制变量
        self.is_converting = False
        self.cancel_flag = threading.Event()
        self.ffmpeg_path = ""

        # 加载配置
        self.config = self.load_config()

        # 创建界面
        self.create_widgets()
        self.apply_config()

        # 启动时检查 FFmpeg
        self.check_ffmpeg_on_start()

    def load_config(self):
        default_config = {
            "ffmpeg_path": "",
            "output_dir": "",
            "thread_count": 2,
            "last_input_files": []
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
            "ffmpeg_path": self.ffmpeg_path,
            "output_dir": self.output_dir_var.get().strip(),
            "thread_count": int(self.thread_var.get()),
            "last_input_files": self.input_files.copy()
        }
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def apply_config(self):
        self.ffmpeg_path = self.config.get("ffmpeg_path", "")
        self.output_dir_var.set(self.config.get("output_dir", ""))
        self.thread_var.set(str(self.config.get("thread_count", 2)))

    def check_ffmpeg_on_start(self):
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).exists():
            # 尝试自动查找
            auto_found = shutil.which("ffmpeg")
            if auto_found:
                self.ffmpeg_path = auto_found
                self.save_config()
                self.log(f"✅ 自动检测到 FFmpeg: {auto_found}")
            else:
                self.log("⚠️ 未检测到 FFmpeg，请手动指定路径。")

    def create_widgets(self):
        main_frame = Frame(self.root)
        main_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # 1. FFmpeg 路径
        ffmpeg_frame = LabelFrame(main_frame, text="FFmpeg 路径", padx=5, pady=5)
        ffmpeg_frame.pack(fill=X, pady=5)
        self.ffmpeg_path_var = StringVar()
        Entry(ffmpeg_frame, textvariable=self.ffmpeg_path_var, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(ffmpeg_frame, text="选择 FFmpeg", command=self.select_ffmpeg).pack(side=RIGHT)

        # 2. 输入文件
        input_frame = LabelFrame(main_frame, text="选择 MP4 文件（支持多选）", padx=5, pady=5)
        input_frame.pack(fill=X, pady=5)
        self.input_files = []
        Button(input_frame, text="添加 MP4 文件", command=self.add_files).pack(side=LEFT)
        Button(input_frame, text="清空列表", command=self.clear_files).pack(side=LEFT, padx=(5,0))
        self.file_listbox = Listbox(input_frame, height=6, selectmode=EXTENDED)
        self.file_listbox.pack(fill=BOTH, expand=True, pady=(5,0))

        # 3. 输出目录
        output_frame = Frame(main_frame)
        output_frame.pack(fill=X, pady=5)
        Label(output_frame, text="输出目录:").pack(side=LEFT)
        self.output_dir_var = StringVar()
        Entry(output_frame, textvariable=self.output_dir_var, width=60).pack(side=LEFT, fill=X, expand=True, padx=5)
        Button(output_frame, text="浏览", command=self.select_output_dir).pack(side=RIGHT)

        # 4. 线程设置
        thread_frame = Frame(main_frame)
        thread_frame.pack(fill=X, pady=5)
        Label(thread_frame, text="转换线程数:").pack(side=LEFT)
        self.thread_var = StringVar(value="2")
        Spinbox(thread_frame, from_=1, to=8, textvariable=self.thread_var, width=5).pack(side=LEFT, padx=5)

        # 5. 控制按钮
        btn_frame = Frame(main_frame)
        btn_frame.pack(fill=X, pady=10)
        self.start_btn = Button(btn_frame, text="开始转换", command=self.start_conversion, bg="#4CAF50", fg="white", height=2)
        self.start_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        self.cancel_btn = Button(btn_frame, text="取消", command=self.cancel_conversion, state=DISABLED, bg="#F44336", fg="white", height=2)
        self.cancel_btn.pack(side=LEFT, fill=X, expand=True, padx=(0,5))

        # 6. 进度条
        self.progress_label = Label(main_frame, text="就绪")
        self.progress_label.pack(pady=(0,5))
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=X, pady=(0,5))

        # 7. 日志
        log_frame = LabelFrame(main_frame, text="操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, height=10)
        self.log_text.pack(fill=BOTH, expand=True)

    def log(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def select_ffmpeg(self):
        path = filedialog.askopenfilename(
            title="选择 ffmpeg.exe",
            filetypes=[("Executable", "ffmpeg.exe"), ("All files", "*.*")]
        )
        if path:
            self.ffmpeg_path = path
            self.ffmpeg_path_var.set(path)
            self.save_config()
            self.log(f"✅ FFmpeg 路径已设置: {path}")

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 MP4 文件",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")]
        )
        for f in files:
            if f not in self.input_files:
                self.input_files.append(f)
                self.file_listbox.insert(END, os.path.basename(f))
        self.save_config()

    def clear_files(self):
        self.input_files.clear()
        self.file_listbox.delete(0, END)
        self.save_config()

    def select_output_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_dir_var.get() or os.path.expanduser("~"))
        if path:
            self.output_dir_var.set(path)
            self.save_config()

    def cancel_conversion(self):
        self.cancel_flag.set()
        self.log("🛑 用户已取消转换...")

    def start_conversion(self):
        if not self.input_files:
            messagebox.showwarning("警告", "请先添加 MP4 文件！")
            return
        if not self.ffmpeg_path or not Path(self.ffmpeg_path).exists():
            messagebox.showerror("错误", "FFmpeg 路径无效！请重新选择。")
            return
        if not self.output_dir_var.get().strip():
            messagebox.showwarning("警告", "请选择输出目录！")
            return

        self.save_config()

        self.is_converting = True
        self.cancel_flag.clear()
        self.start_btn.config(state=DISABLED)
        self.cancel_btn.config(state=NORMAL)
        self.progress['value'] = 0
        self.progress_label.config(text="正在转换...")

        threading.Thread(target=self.run_conversion, daemon=True).start()

    def run_conversion(self):
        files = self.input_files.copy()
        output_dir = Path(self.output_dir_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)
        thread_count = min(int(self.thread_var.get()), len(files), 8)

        total = len(files)
        completed = 0
        lock = threading.Lock()

        def worker(file_queue):
            nonlocal completed
            while not file_queue.empty() and not self.cancel_flag.is_set():
                try:
                    mp4_path = file_queue.get_nowait()
                except:
                    break

                mp3_path = output_dir / (Path(mp4_path).stem + ".mp3")
                try:
                    self.log(f"▶ 正在转换: {Path(mp4_path).name}")
                    cmd = [
                        self.ffmpeg_path,
                        "-i", str(mp4_path),
                        "-vn",
                        "-acodec", "libmp3lame",
                        "-b:a", "192k",
                        "-y",
                        str(mp3_path)
                    ]
                    result = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if result.returncode == 0:
                        with lock:
                            completed += 1
                            progress_val = (completed / total) * 100
                            self.root.after(0, lambda p=progress_val, c=completed: (
                                self.progress_label.config(text=f"进度: {c}/{total}"),
                                self.progress.config(value=p)
                            ))
                        self.log(f"✅ 转换完成: {mp3_path.name}")
                    else:
                        self.log(f"❌ 转换失败: {Path(mp4_path).name} - {result.stderr.decode('utf-8', errors='ignore')[:200]}")
                except Exception as e:
                    self.log(f"💥 异常: {e}")
                finally:
                    file_queue.task_done()

        from queue import Queue
        q = Queue()
        for f in files:
            q.put(f)

        threads = []
        for _ in range(thread_count):
            t = threading.Thread(target=worker, args=(q,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        # 完成后更新 UI
        def finish_ui():
            self.is_converting = False
            self.start_btn.config(state=NORMAL)
            self.cancel_btn.config(state=DISABLED)
            status = "✅ 转换完成！" if not self.cancel_flag.is_set() else "🛑 已取消"
            self.progress_label.config(text=status)
        self.root.after(0, finish_ui)

    def on_closing(self):
        if self.is_converting:
            if messagebox.askokcancel("退出", "转换正在进行，确定要退出吗？"):
                self.cancel_conversion()
                self.root.destroy()
        else:
            self.root.destroy()


# ================== 启动程序 ==================
if __name__ == "__main__":
    import shutil  # used in check_ffmpeg_on_start
    root = Tk()
    app = MP4ToMP3Converter(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
