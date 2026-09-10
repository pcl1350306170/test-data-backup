# audio_mover.pyw （含「保留目录结构」功能｜已验证）
import traceback
import sys
sys.excepthook = lambda *args: traceback.print_exception(*args)

import os
import shutil
import json
import logging
import threading
import time
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, BooleanVar

# ============================== #
# 配置与常量
# ============================== #
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "audio_mover"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
PROCESS_LOG_FILE = CONFIG_DIR / "logs" / f"log_{SCRIPT_NAME}.log"

CONFIG_DIR.mkdir(exist_ok=True)
(CONFIG_DIR / "logs").mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "source_dir": "",
    "target_dir": "",
    "include_subdirs": True,
    "keep_directory_structure": False,  # ✅ 新增：默认不保留结构
    "audio_extensions": "mp3,wav,flac,ogg,m4a,aac,wma,opus"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding="utf-8"),
    ]
)
logger = logging.getLogger()

# ============================== #
# 工具函数
# ============================== #
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
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
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        messagebox.showerror("保存失败", f"配置写入出错：\n{e}")

def get_audio_files(source_dir: Path, include_subdirs: bool, extensions: list) -> list:
    files = []
    pattern = "**/*" if include_subdirs else "*"
    for ext in extensions:
        files.extend(list(source_dir.glob(f"{pattern}.{ext.lower()}")))
        files.extend(list(source_dir.glob(f"{pattern}.{ext.upper()}")))
    return list(set(files))

def move_audio_files(source_dir, target_dir, include_subdirs, extensions, keep_structure, on_progress):
    source_dir = Path(source_dir)
    target_dir = Path(target_dir)
    if not source_dir.is_dir():
        raise ValueError("源目录不存在")
    if not target_dir.exists():
        target_dir.mkdir(parents=True)

    audio_files = get_audio_files(source_dir, include_subdirs, extensions)
    total = len(audio_files)
    if total == 0:
        raise ValueError("未找到任何匹配的音频文件")

    moved_count = 0
    failed = []

    for i, file_path in enumerate(audio_files, 1):
        try:
            if keep_structure:
                rel_path = file_path.relative_to(source_dir)
                target_file = target_dir / rel_path
            else:
                target_file = target_dir / file_path.name
                # 平铺模式：防重名自动编号
                counter = 1
                original_target = target_file
                while target_file.exists():
                    stem = original_target.stem
                    suffix = original_target.suffix
                    target_file = original_target.parent / f"{stem}_{counter}{suffix}"
                    counter += 1

            if keep_structure:
                target_file.parent.mkdir(parents=True, exist_ok=True)

            shutil.move(str(file_path), str(target_file))
            moved_count += 1
            on_progress(f"✅ 已移动 [{i}/{total}]: {file_path.name}", moved_count, total)
        except Exception as e:
            failed.append(f"{file_path.name} → {e}")
            on_progress(f"❌ 失败: {file_path.name} ({e})", moved_count, total)

    return moved_count, failed

# ============================== #
# GUI 主类
# ============================== #
class AudioMoverGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🎧 音频文件批量移动工具")
        self.root.geometry("620x540")  # 高度+20适配新选项
        self.root.resizable(False, False)
        self.config = load_config()
        self.running = False
        self.setup_ui()

    def setup_ui(self):
        # === 源目录 ===
        frame_source = LabelFrame(self.root, text="📂 源目录（需含音频文件）", padx=10, pady=8)
        frame_source.pack(fill=X, padx=10, pady=5)

        Label(frame_source, text="路径:").grid(row=0, column=0, sticky=W, pady=3)
        self.source_var = StringVar(value=self.config.get("source_dir", ""))
        Entry(frame_source, textvariable=self.source_var, width=50).grid(row=0, column=1, padx=5, pady=3)
        Button(frame_source, text="📁 选择", command=self.select_source_dir).grid(row=0, column=2, padx=5)

        # === 目标目录 ===
        frame_target = LabelFrame(self.root, text="🎯 目标目录（移动到此）", padx=10, pady=8)
        frame_target.pack(fill=X, padx=10, pady=5)

        Label(frame_target, text="路径:").grid(row=0, column=0, sticky=W, pady=3)
        self.target_var = StringVar(value=self.config.get("target_dir", ""))
        Entry(frame_target, textvariable=self.target_var, width=50).grid(row=0, column=1, padx=5, pady=3)
        Button(frame_target, text="📁 选择", command=self.select_target_dir).grid(row=0, column=2, padx=5)

        # === 高级选项 ===
        frame_opts = LabelFrame(self.root, text="⚙️ 高级选项", padx=10, pady=8)
        frame_opts.pack(fill=X, padx=10, pady=5)

        self.subdir_var = BooleanVar(value=self.config.get("include_subdirs", True))
        Checkbutton(frame_opts, text="✅ 包含子目录中的文件", variable=self.subdir_var).pack(anchor=W)

        # --- ✅ 新增：保留目录结构选项 ---
        self.keep_struct_var = BooleanVar(value=self.config.get("keep_directory_structure", False))
        Checkbutton(frame_opts, text="📁 保留源目录结构（否则全部平铺到目标根目录）",
                    variable=self.keep_struct_var).pack(anchor=W, pady=(5,0))

        row_ext = Frame(frame_opts)
        row_ext.pack(fill=X, pady=5)
        Label(row_ext, text="音频后缀（英文逗号分隔）:", width=25, anchor=W).pack(side=LEFT)
        self.ext_var = StringVar(value=self.config.get("audio_extensions", DEFAULT_CONFIG["audio_extensions"]))
        Entry(row_ext, textvariable=self.ext_var, width=40).pack(side=LEFT, padx=5)

        # === 按钮区 ===
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        self.start_btn = Button(btn_frame, text="🚀 开始移动", command=self.start_move,
                                bg="#4CAF50", fg="white", width=12, height=2, font=("Arial", 10, "bold"))
        self.start_btn.pack(side=LEFT, padx=8)
        self.save_btn = Button(btn_frame, text="💾 保存配置", command=self.save_current_config,
                               bg="#2196F3", fg="white", width=12)
        self.save_btn.pack(side=LEFT, padx=8)
        self.reset_btn = Button(btn_frame, text="🔄 重置为默认", command=self.reset_to_default,
                                bg="#FF9800", fg="white", width=12)
        self.reset_btn.pack(side=LEFT, padx=8)

        # === 进度与日志 ===
        progress_frame = LabelFrame(self.root, text="📊 进度与状态", padx=5, pady=5)
        progress_frame.pack(fill=X, padx=10, pady=5)
        self.progress_var = StringVar(value="准备就绪（点击“开始移动”）")
        Label(progress_frame, textvariable=self.progress_var, anchor=W, fg="blue").pack(fill=X, padx=5)

        log_frame = LabelFrame(self.root, text="📋 操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.log_text = Text(log_frame, height=10, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # === 状态栏 ===
        self.status_var = StringVar(value="就绪 | 配置已加载")
        status_bar = Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="darkgreen")
        status_bar.pack(side=BOTTOM, fill=X)

    def log_to_gui(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def select_source_dir(self):
        path = filedialog.askdirectory(title="选择音频文件所在目录（包含子目录）")
        if path:
            self.source_var.set(path)

    def select_target_dir(self):
        path = filedialog.askdirectory(title="选择目标保存目录")
        if path:
            self.target_var.set(path)

    def save_current_config(self):
        cfg = {
            "source_dir": self.source_var.get().strip(),
            "target_dir": self.target_var.get().strip(),
            "include_subdirs": self.subdir_var.get(),
            "keep_directory_structure": self.keep_struct_var.get(),  # ✅ 新增
            "audio_extensions": self.ext_var.get().strip()
        }
        save_config(cfg)
        self.config = cfg
        self.status_var.set("✅ 配置已保存")
        self.log_to_gui("配置已保存到磁盘")

    def reset_to_default(self):
        self.source_var.set("")
        self.target_var.set("")
        self.subdir_var.set(True)
        self.keep_struct_var.set(False)  # ✅ 重置为默认：不保留结构
        self.ext_var.set(DEFAULT_CONFIG["audio_extensions"])
        self.status_var.set("🔄 已恢复默认配置")
        self.log_to_gui("已重置为初始默认配置")

    def start_move(self):
        if self.running:
            return

        src = self.source_var.get().strip()
        tgt = self.target_var.get().strip()
        if not src or not tgt:
            messagebox.showwarning("警告", "请填写【源目录】和【目标目录】！")
            return

        try:
            exts = [e.strip() for e in self.ext_var.get().split(",") if e.strip()]
            if not exts:
                raise ValueError("音频后缀不能为空")

            self.running = True
            self.start_btn.config(state=DISABLED)
            self.save_btn.config(state=DISABLED)
            self.reset_btn.config(state=DISABLED)
            self.status_var.set("⏳ 正在扫描并移动文件...")
            self.progress_var.set("正在初始化...")

            thread = threading.Thread(
                target=self._run_move_task,
                args=(src, tgt, self.subdir_var.get(), exts),
                daemon=True
            )
            thread.start()

        except Exception as e:
            self.log_to_gui(f"❌ 启动失败: {e}")
            self.status_var.set("❌ 启动异常")
            self.running = False

    def _run_move_task(self, src, tgt, include_subdirs, exts):
        try:
            def on_progress(msg, done, total):
                self.root.after(0, lambda: self.progress_var.set(f"[{done}/{total}] {msg}"))
                self.root.after(0, lambda: self.log_to_gui(msg))

            self.root.after(0, lambda: self.log_to_gui("=== 开始执行移动任务 ==="))
            moved, failed = move_audio_files(
                src, tgt, include_subdirs, exts,
                self.keep_struct_var.get(),  # ✅ 传入新参数
                on_progress
            )

            self.root.after(0, lambda: self.progress_var.set(f"✅ 全部完成！成功 {moved} 个，失败 {len(failed)} 个"))
            if failed:
                self.root.after(0, lambda: self.log_to_gui("⚠️ 以下文件移动失败：\n" + "\n".join(failed)))
            self.root.after(0, lambda: self.log_to_gui("=== 移动任务结束 ==="))
            self.root.after(0, lambda: messagebox.showinfo("完成", f"✅ 成功移动 {moved} 个文件\n❌ 失败 {len(failed)} 个"))

        except Exception as e:
            self.root.after(0, lambda: self.log_to_gui(f"💥 严重错误: {e}"))
            self.root.after(0, lambda: messagebox.showerror("执行异常", str(e)))

        finally:
            self.root.after(0, self._on_task_finished)

    def _on_task_finished(self):
        self.running = False
        self.start_btn.config(state=NORMAL)
        self.save_btn.config(state=NORMAL)
        self.reset_btn.config(state=NORMAL)
        self.status_var.set("✅ 移动任务已完成")

# ============================== #
# 主程序入口
# ============================== #
if __name__ == "__main__":
    root = Tk()
    app = AudioMoverGUI(root)
    root.mainloop()
