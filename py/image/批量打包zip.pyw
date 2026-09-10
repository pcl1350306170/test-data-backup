# batch_zipper_enhanced.py

import os
import subprocess
import json
import platform
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime
import threading
import time

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "batch_zipper"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
STATE_FILE = CONFIG_DIR / f"state_{SCRIPT_NAME}.json"  # 断点续压状态文件
CONFIG_DIR.mkdir(exist_ok=True, parents=True)
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

DEFAULT_CONFIG = {
    "source_dir": r"H:\NOVEL\合集\old\HH",
    "output_dir": r"D:\bak",
    "archive_format": "zip",
    "enable_password": True,
    "password": "123456",
    "files_per_archive": 1000,
    "archive_prefix": "HH_Collection",
    "seven_zip_path": "7z",
    "enable_size_limit": True,
    "max_archive_size_mb": 3072  # 默认3GB
}

class BatchZipperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("批量打包压缩工具（支持暂停 & 断点续压）")
        self.root.geometry("950x700")
        self.root.minsize(850, 650)

        # 控制变量
        self.source_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.archive_format = tk.StringVar(value="zip")
        self.enable_password = tk.BooleanVar(value=True)
        self.password = tk.StringVar(value="123456")
        self.files_per_archive = tk.IntVar(value=1000)
        self.archive_prefix = tk.StringVar(value="HH_Collection")
        self.seven_zip_path = tk.StringVar(value="7z")
        self.enable_size_limit = tk.BooleanVar(value=True)
        self.max_archive_size_mb = tk.IntVar(value=3072)

        # 运行控制
        self.is_running = False
        self.pause_event = threading.Event()  # 用于暂停/继续
        self.pause_event.set()  # 初始为运行状态
        self.current_batch = 0
        self.total_batches = 0

        self._create_widgets()
        self._load_config()

    def _check_7z(self):
        try:
            subprocess.run([self.seven_zip_path.get(), "h"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            self._log("✅ 7-Zip 可用")
        except Exception as e:
            self._log(f"⚠️ 7-Zip 检测失败: {e}", logging.WARNING)
            messagebox.showwarning("警告", "未检测到 7-Zip，请检查路径设置")

    def _show_toast(self, title, message, level="info", duration_ms=60000):
        """屏幕右下角弹出消息提醒，duration_ms 后自动消失（默认1分钟）"""
        toast = tk.Toplevel(self.root)
        toast.withdraw()
        toast.overrideredirect(True)
        toast.attributes('-topmost', True)

        colors = {
            "success": ("#2e7d32", "#e8f5e9", "✅"),
            "error":   ("#c62828", "#ffebee", "❌"),
            "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
        }
        fg, bg, icon = colors.get(level, colors["info"])
        toast.configure(bg=bg)

        # 标题行
        header = tk.Frame(toast, bg=bg)
        header.pack(fill=tk.X, padx=10, pady=(8, 0))
        tk.Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                 fg=fg, bg=bg).pack(side=tk.LEFT)
        close_lbl = tk.Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
        close_lbl.pack(side=tk.RIGHT)
        close_lbl.bind("<Button-1>", lambda e: toast.destroy())

        # 消息内容
        tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                 fg="#333", bg=bg, wraplength=320, justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)

        # 屏幕右下角位置
        toast.update_idletasks()
        w, h = toast.winfo_width(), toast.winfo_height()
        sx = toast.winfo_screenwidth()
        sy = toast.winfo_screenheight()
        x = sx - w - 20
        y = sy - h - 60
        toast.geometry(f"+{x}+{y}")
        toast.deiconify()

        toast.after(duration_ms, toast.destroy)

    def _select_source_dir(self):
        d = filedialog.askdirectory(title="选择源文件夹")
        if d: self.source_dir.set(d)

    def _select_output_dir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d: self.output_dir.set(d)

    def _toggle_size_limit(self):
        """切换大小限制启用状态，联动控制文件数输入框"""
        if self.enable_size_limit.get():
            self.files_spinbox.config(state=tk.DISABLED)
            self.size_limit_spinbox.config(state=tk.NORMAL)
        else:
            self.files_spinbox.config(state=tk.NORMAL)
            self.size_limit_spinbox.config(state=tk.DISABLED)

    def _select_7z_path(self):
        f = filedialog.askopenfilename(title="选择 7z.exe", filetypes=[("7z.exe", "7z.exe")])
        if f: self.seven_zip_path.set(f)

    def _toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.config(text="继续")
            self._log("⏸ 打包已暂停")
        else:
            self.pause_event.set()
            self.pause_btn.config(text="暂停")
            self._log("▶ 继续打包...")

    def _run_packaging(self):
        if not self.source_dir.get() or not Path(self.source_dir.get()).exists():
            messagebox.showerror("错误", "源目录无效")
            return
        if not self.output_dir.get():
            messagebox.showerror("错误", "请设置输出目录")
            return
        if self.enable_password.get() and not self.password.get():
            messagebox.showerror("错误", "密码不能为空")
            return

        self.is_running = True
        self._update_ui_state()
        threading.Thread(target=self._do_packaging, daemon=True).start()

    def _do_packaging(self):
        try:
            source = Path(self.source_dir.get())
            output = Path(self.output_dir.get())
            output.mkdir(parents=True, exist_ok=True)

            # 获取所有文件（保留结构）
            all_files = []
            for fp in source.rglob("*"):
                if fp.is_file():
                    rel = fp.relative_to(source)
                    file_size = fp.stat().st_size
                    all_files.append((fp, rel, file_size))
            if not all_files:
                self._log("❌ 源目录无文件", logging.WARNING)
                return

            prefix = self.archive_prefix.get().strip() or "batch"
            ext = self.archive_format.get()

            if self.enable_size_limit.get():
                self._do_packaging_by_size(source, output, all_files, prefix, ext)
            else:
                self._do_packaging_by_count(source, output, all_files, prefix, ext)

            self._log("🎉 打包全部完成！")
            self.root.after(0, lambda: self._show_toast("打包完成", "所有文件已成功打包！", "success"))

        except Exception as e:
            self._log(f"💥 打包异常: {e}", logging.ERROR)
            self.root.after(0, lambda: self._show_toast("打包失败", str(e), "error"))
        finally:
            self.is_running = False
            self.root.after(0, self._update_ui_state)

    def _do_packaging_by_count(self, source, output, all_files, prefix, ext):
        """按文件数量分批打包（原有逻辑）"""
        batch_size = self.files_per_archive.get()
        total = len(all_files)
        total_batches = (total + batch_size - 1) // batch_size
        self.total_batches = total_batches

        # === 断点续压：检查已有压缩包 ===
        completed_batches = set()
        for i in range(1, total_batches + 1):
            name = f"{prefix}_batch_{i:03d}.{ext}"
            if (output / name).exists():
                completed_batches.add(i)
        start_batch = min(completed_batches) if completed_batches else 1
        if completed_batches:
            start_batch = max(completed_batches) + 1
            if start_batch > total_batches:
                self._log("✅ 所有批次已完成，无需继续")
                return
            self._log(f"🔁 检测到 {len(completed_batches)} 个已完成压缩包，从第 {start_batch} 批开始")

        # === 主循环 ===
        for i in range(start_batch, total_batches + 1):
            self.current_batch = i
            self.root.after(0, lambda i=i: self.progress_label.config(text=f"正在处理第 {i}/{total_batches} 批..."))

            while not self.pause_event.is_set():
                time.sleep(0.5)
                if not self.is_running:
                    return

            start_idx = (i - 1) * batch_size
            end_idx = min(start_idx + batch_size, total)
            batch_files = all_files[start_idx:end_idx]

            archive_name = f"{prefix}_batch_{i:03d}.{ext}"
            archive_path = output / archive_name

            self._log(f"📦 创建: {archive_name} ({len(batch_files)} 文件)")

            list_file = CONFIG_DIR / f"tmp_filelist_{i}.txt"
            try:
                with open(list_file, 'w', encoding='utf-8') as f:
                    for _, rel, _ in batch_files:
                        f.write(str(rel).replace('/', '\\') + '\n')

                cmd = [
                    self.seven_zip_path.get(),
                    "a", "-t" + ext, "-mx=1", "-mmt=on",
                    f"-w{output}",
                ]
                if self.enable_password.get():
                    cmd.append(f"-p{self.password.get()}")
                cmd += [str(archive_path), f"@{list_file}"]

                proc = subprocess.Popen(
                    cmd,
                    cwd=str(source),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8'
                )

                while proc.poll() is None:
                    time.sleep(0.1)
                if proc.returncode != 0:
                    self._log(f"❌ 压缩失败: {archive_name}", logging.ERROR)
                else:
                    self._log(f"✅ 成功: {archive_name}")

            finally:
                if list_file.exists():
                    list_file.unlink(missing_ok=True)

    def _do_packaging_by_size(self, source, output, all_files, prefix, ext):
        """按压缩包大小限制分批打包"""
        max_bytes = self.max_archive_size_mb.get() * 1024 * 1024
        total_files = len(all_files)

        # 按大小切分批次
        batches = []  # list of (start_idx, end_idx)
        current_size = 0
        batch_start = 0
        for idx, (fp, rel, fsize) in enumerate(all_files):
            if current_size + fsize > max_bytes and idx > batch_start:
                batches.append((batch_start, idx))
                current_size = fsize
                batch_start = idx
            else:
                current_size += fsize
        # 最后一批
        if batch_start < total_files:
            batches.append((batch_start, total_files))

        total_batches = len(batches)
        self.total_batches = total_batches
        self._log(f"📊 按大小限制分为 {total_batches} 批（每批上限 {self.max_archive_size_mb.get()}MB）")

        # === 断点续压：检查已有压缩包 ===
        completed_batches = set()
        for i in range(1, total_batches + 1):
            name = f"{prefix}_batch_{i:03d}.{ext}"
            if (output / name).exists():
                completed_batches.add(i)
        start_batch = min(completed_batches) if completed_batches else 1
        if completed_batches:
            start_batch = max(completed_batches) + 1
            if start_batch > total_batches:
                self._log("✅ 所有批次已完成，无需继续")
                return
            self._log(f"🔁 检测到 {len(completed_batches)} 个已完成压缩包，从第 {start_batch} 批开始")

        # === 主循环 ===
        for i in range(start_batch, total_batches + 1):
            self.current_batch = i
            self.root.after(0, lambda i=i: self.progress_label.config(text=f"正在处理第 {i}/{total_batches} 批..."))

            while not self.pause_event.is_set():
                time.sleep(0.5)
                if not self.is_running:
                    return

            start_idx, end_idx = batches[i - 1]
            batch_files = all_files[start_idx:end_idx]
            batch_size_mb = sum(fsize for _, _, fsize in batch_files) / (1024 * 1024)

            archive_name = f"{prefix}_batch_{i:03d}.{ext}"
            archive_path = output / archive_name

            self._log(f"📦 创建: {archive_name} ({len(batch_files)} 文件, 原始大小 {batch_size_mb:.1f}MB)")

            list_file = CONFIG_DIR / f"tmp_filelist_{i}.txt"
            try:
                with open(list_file, 'w', encoding='utf-8') as f:
                    for _, rel, _ in batch_files:
                        f.write(str(rel).replace('/', '\\') + '\n')

                cmd = [
                    self.seven_zip_path.get(),
                    "a", "-t" + ext, "-mx=1", "-mmt=on",
                    f"-w{output}",
                ]
                if self.enable_password.get():
                    cmd.append(f"-p{self.password.get()}")
                cmd += [str(archive_path), f"@{list_file}"]

                proc = subprocess.Popen(
                    cmd,
                    cwd=str(source),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8'
                )

                while proc.poll() is None:
                    time.sleep(0.1)
                if proc.returncode != 0:
                    self._log(f"❌ 压缩失败: {archive_name}", logging.ERROR)
                else:
                    self._log(f"✅ 成功: {archive_name}")

            finally:
                if list_file.exists():
                    list_file.unlink(missing_ok=True)

    def _save_config(self):
        cfg = {
            "source_dir": self.source_dir.get(),
            "output_dir": self.output_dir.get(),
            "archive_format": self.archive_format.get(),
            "enable_password": self.enable_password.get(),
            "password": self.password.get(),
            "files_per_archive": self.files_per_archive.get(),
            "archive_prefix": self.archive_prefix.get(),
            "seven_zip_path": self.seven_zip_path.get(),
            "enable_size_limit": self.enable_size_limit.get(),
            "max_archive_size_mb": self.max_archive_size_mb.get()
        }
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self._log("💾 配置已保存")
        except Exception as e:
            self._log(f"❌ 保存配置失败: {e}", logging.ERROR)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            else:
                cfg = DEFAULT_CONFIG.copy()
                self._log("ℹ️ 使用默认配置")
            for k, v in cfg.items():
                if hasattr(self, k):
                    getattr(self, k).set(v)
            self._log("✅ 配置加载完成")
        except Exception as e:
            self._log(f"⚠️ 加载配置失败: {e}", logging.WARNING)

    def _log(self, msg, level=logging.INFO):
        logging.log(level, msg)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def _update_ui_state(self):
        state = tk.DISABLED if self.is_running else tk.NORMAL
        for w in [self.source_btn, self.output_btn, self.browse_7z_btn, self.save_btn, self.start_btn]:
            w.config(state=state)
        self.pause_btn.config(state=tk.NORMAL if self.is_running else tk.DISABLED)
        if not self.is_running:
            self.pause_btn.config(text="暂停")

    def _create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 源目录
        f1 = ttk.LabelFrame(main, text="源文件夹", padding=5)
        f1.pack(fill=tk.X, pady=5)
        ttk.Entry(f1, textvariable=self.source_dir, width=80).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.source_btn = ttk.Button(f1, text="浏览...", command=self._select_source_dir)
        self.source_btn.pack(side=tk.RIGHT)

        # 输出目录
        f2 = ttk.LabelFrame(main, text="输出目录", padding=5)
        f2.pack(fill=tk.X, pady=5)
        ttk.Entry(f2, textvariable=self.output_dir, width=80).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.output_btn = ttk.Button(f2, text="浏览...", command=self._select_output_dir)
        self.output_btn.pack(side=tk.RIGHT)

        # 高级设置
        f3 = ttk.LabelFrame(main, text="高级设置", padding=10)
        f3.pack(fill=tk.X, pady=5)

        # 第一行
        ttk.Label(f3, text="压缩格式:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Combobox(f3, textvariable=self.archive_format, values=["zip", "7z"], width=8, state="readonly").grid(row=0, column=1, padx=5)
        ttk.Checkbutton(f3, text="启用密码", variable=self.enable_password).grid(row=0, column=2, padx=10)
        ttk.Label(f3, text="密码:").grid(row=0, column=3, padx=5)
        ttk.Entry(f3, textvariable=self.password, width=12).grid(row=0, column=4, padx=5)

        # 第二行
        ttk.Label(f3, text="每包文件数:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.files_spinbox = ttk.Spinbox(f3, from_=1, to=10000, textvariable=self.files_per_archive, width=10)
        self.files_spinbox.grid(row=1, column=1, padx=5)
        ttk.Label(f3, text="压缩包前缀:").grid(row=1, column=2, padx=10, pady=5)
        ttk.Entry(f3, textvariable=self.archive_prefix, width=15).grid(row=1, column=3, columnspan=2, padx=5, sticky=tk.EW)

        # 第三行：大小限制
        ttk.Checkbutton(f3, text="限制压缩包大小(MB):", variable=self.enable_size_limit,
                        command=self._toggle_size_limit).grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.size_limit_spinbox = ttk.Spinbox(f3, from_=100, to=102400, increment=512,
                                               textvariable=self.max_archive_size_mb, width=10)
        self.size_limit_spinbox.grid(row=2, column=1, padx=5)

        # 第四行：7z路径
        ttk.Label(f3, text="7z路径:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(f3, textvariable=self.seven_zip_path, width=40).grid(row=3, column=1, columnspan=3, padx=5, sticky=tk.EW)
        self.browse_7z_btn = ttk.Button(f3, text="浏览", command=self._select_7z_path, width=6)
        self.browse_7z_btn.grid(row=3, column=4, padx=(5,0))

        f3.columnconfigure(4, weight=1)

        # 初始化大小限制UI状态
        self._toggle_size_limit()

        # 操作区
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=10)

        self.start_btn = ttk.Button(btn_frame, text="开始打包", command=self._run_packaging)
        self.start_btn.pack(side=tk.LEFT, padx=(0,10))

        self.pause_btn = ttk.Button(btn_frame, text="暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(0,10))

        self.save_btn = ttk.Button(btn_frame, text="保存配置", command=self._save_config)
        self.save_btn.pack(side=tk.LEFT)

        self.progress_label = ttk.Label(btn_frame, text="", foreground="blue")
        self.progress_label.pack(side=tk.RIGHT)

        # 日志
        log_frame = ttk.LabelFrame(main, text="日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

if __name__ == "__main__":
    if platform.system() != "Windows":
        messagebox.showerror("错误", "仅支持 Windows（依赖 7-Zip）")
    else:
        root = tk.Tk()
        app = BatchZipperApp(root)
        root.mainloop()
