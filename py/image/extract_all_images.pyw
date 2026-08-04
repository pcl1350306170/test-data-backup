import os
import json
import shutil
import threading
import queue
from PIL import Image
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "extract_all_images"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_FILE = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif')


class ExtractImagesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片提取工具")
        self.root.geometry("650x500")
        self._running = False  # 防止重复点击
        self._msg_queue = queue.Queue()

        self.config = {
            "source_dir": "",
            "target_dir": "",
            "enable_compress": True,
            "compress_threshold_kb": 700,
            "compress_target_kb": 300,
        }

        self.load_config()
        self.create_widgets()
        self._poll_queue()  # 启动队列轮询

    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ---- 配置页 ----
        frame_main = ttk.Frame(notebook)
        notebook.add(frame_main, text="配置")

        # 源目录
        ttk.Label(frame_main, text="源目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.source_dir_var = tk.StringVar(value=self.config["source_dir"])
        ttk.Entry(frame_main, textvariable=self.source_dir_var, width=50).grid(row=0, column=1, pady=5)
        ttk.Button(frame_main, text="浏览...", command=self.browse_source).grid(row=0, column=2, padx=5, pady=5)

        # 目标目录
        ttk.Label(frame_main, text="目标目录:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.target_dir_var = tk.StringVar(value=self.config["target_dir"])
        ttk.Entry(frame_main, textvariable=self.target_dir_var, width=50).grid(row=1, column=1, pady=5)
        ttk.Button(frame_main, text="浏览...", command=self.browse_target).grid(row=1, column=2, padx=5, pady=5)

        # 是否压缩
        self.enable_compress_var = tk.BooleanVar(value=self.config["enable_compress"])
        ttk.Checkbutton(frame_main, text="压缩超过阈值的图片", variable=self.enable_compress_var).grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=5)

        # 压缩阈值
        ttk.Label(frame_main, text="压缩阈值(KB):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.compress_threshold_var = tk.IntVar(value=self.config["compress_threshold_kb"])
        ttk.Entry(frame_main, textvariable=self.compress_threshold_var, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)
        ttk.Label(frame_main, text="超过此大小的图片将被压缩", foreground="gray").grid(row=3, column=2, sticky=tk.W, padx=5)

        # 压缩目标大小
        ttk.Label(frame_main, text="压缩目标大小(KB):").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.compress_target_var = tk.IntVar(value=self.config["compress_target_kb"])
        ttk.Entry(frame_main, textvariable=self.compress_target_var, width=10).grid(row=4, column=1, sticky=tk.W, pady=5)
        ttk.Label(frame_main, text="压缩后图片的目标大小", foreground="gray").grid(row=4, column=2, sticky=tk.W, padx=5)

        # 按钮
        btn_frame = ttk.Frame(frame_main)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        self.extract_btn = ttk.Button(btn_frame, text="开始提取", command=self.execute_extract)
        self.extract_btn.pack(side=tk.LEFT, padx=10)

        # ---- 进度/日志页 ----
        frame_status = ttk.Frame(notebook)
        notebook.add(frame_status, text="进度")

        # 进度条
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(frame_status, variable=self.progress_var, maximum=100, length=580)
        self.progress_bar.pack(padx=10, pady=(10, 2))

        self.progress_label = ttk.Label(frame_status, text="就绪")
        self.progress_label.pack(anchor=tk.W, padx=10)

        ttk.Label(frame_status, text="操作日志:").pack(anchor=tk.W, padx=5, pady=(8, 2))
        self.log_text = tk.Text(frame_status, height=14, width=70)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)

    # ---------- 工具方法 ----------
    def browse_source(self):
        d = filedialog.askdirectory()
        if d:
            self.source_dir_var.set(d)

    def browse_target(self):
        d = filedialog.askdirectory()
        if d:
            self.target_dir_var.set(d)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
            except Exception:
                pass

    def save_config(self):
        try:
            self.config = {
                "source_dir": self.source_dir_var.get(),
                "target_dir": self.target_dir_var.get(),
                "enable_compress": self.enable_compress_var.get(),
                "compress_threshold_kb": self.compress_threshold_var.get(),
                "compress_target_kb": self.compress_target_var.get(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.log("配置已保存")
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def log(self, message):
        """线程安全：通过队列发送日志消息"""
        self._msg_queue.put(("log", message))

    def set_progress(self, current, total):
        """线程安全：通过队列发送进度消息"""
        self._msg_queue.put(("progress", (current, total)))

    def _poll_queue(self):
        """主线程轮询消息队列，更新 UI"""
        try:
            while True:
                msg_type, data = self._msg_queue.get_nowait()
                if msg_type == "log":
                    self.log_text.config(state=tk.NORMAL)
                    self.log_text.insert(tk.END, data + "\n")
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
                elif msg_type == "progress":
                    current, total = data
                    pct = (current / total * 100) if total > 0 else 0
                    self.progress_var.set(pct)
                    self.progress_label.config(text=f"进度: {current}/{total}  ({pct:.1f}%)")
                elif msg_type == "done":
                    self._on_task_done(data)
                    break
        except Exception:
            pass
        self.root.after(50, self._poll_queue)

    def _on_task_done(self, result):
        """后台任务完成后在主线程中处理结果"""
        self._running = False
        self.extract_btn.config(text="开始提取", state=tk.NORMAL)
        copied, compressed, skipped, target_dir = result
        if copied == 0 and compressed == 0 and skipped == 0:
            messagebox.showinfo("提示", "源目录下未找到任何图片")
        else:
            messagebox.showinfo("完成", f"提取完成！\n复制: {copied} 张\n压缩: {compressed} 张\n跳过: {skipped} 张")

    # ---------- 压缩逻辑 ----------
    @staticmethod
    def compress_image(src_path, dst_path, target_kb, ext):
        """逐步降低 quality 直到文件大小 <= target_kb"""
        img = Image.open(src_path)
        # 转为 RGB（JPEG 不支持 RGBA/P）
        if ext.lower() in ('.jpg', '.jpeg') and img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        lo, hi = 10, 95
        best_quality = lo
        while lo <= hi:
            mid = (lo + hi) // 2
            img.save(dst_path, quality=mid, optimize=True)
            size_kb = os.path.getsize(dst_path) / 1024
            if size_kb <= target_kb:
                best_quality = mid
                lo = mid + 1
            else:
                hi = mid - 1

        img.save(dst_path, quality=best_quality, optimize=True)
        img.close()

    # ---------- 核心提取（后台线程） ----------
    def _extract_worker(self, source_dir, target_dir, enable_compress, threshold_kb, target_kb):
        """在后台线程中执行提取，通过队列与 UI 通信"""
        self.log("正在扫描目录...")
        all_images = []
        for root_dir, _dirs, files in os.walk(source_dir):
            for f in files:
                if f.lower().endswith(IMAGE_EXTS):
                    all_images.append(os.path.join(root_dir, f))

        total = len(all_images)
        if total == 0:
            self.log("未找到任何图片")
            self._msg_queue.put(("done", (0, 0, 0, target_dir)))
            return

        self.log(f"共找到 {total} 张图片，开始提取...")
        os.makedirs(target_dir, exist_ok=True)

        copied = 0
        compressed = 0
        skipped = 0

        for idx, img_path in enumerate(all_images, 1):
            filename = os.path.basename(img_path)
            dst_path = os.path.join(target_dir, filename)

            try:
                file_size_kb = os.path.getsize(img_path) / 1024

                if enable_compress and file_size_kb > threshold_kb:
                    _, ext = os.path.splitext(filename)
                    if ext.lower() in ('.png', '.bmp', '.gif', '.tiff', '.tif', '.webp'):
                        compress_dst = os.path.join(target_dir, os.path.splitext(filename)[0] + '.jpg')
                        try:
                            self.compress_image(img_path, compress_dst, target_kb, '.jpg')
                            compressed += 1
                            copied += 1
                            self.log(f"[{idx}/{total}] 压缩并转换: {filename} -> {os.path.basename(compress_dst)}")
                        except Exception as e:
                            shutil.copy2(img_path, dst_path)
                            copied += 1
                            self.log(f"[{idx}/{total}] 压缩失败，直接复制: {filename} ({e})")
                    else:
                        self.compress_image(img_path, dst_path, target_kb, ext)
                        compressed += 1
                        copied += 1
                        self.log(f"[{idx}/{total}] 压缩: {filename}")
                else:
                    shutil.copy2(img_path, dst_path)
                    copied += 1
                    self.log(f"[{idx}/{total}] 复制: {filename}")

                os.remove(img_path)

            except Exception as e:
                skipped += 1
                self.log(f"[{idx}/{total}] 处理失败: {filename} ({e})")

            self.set_progress(idx, total)

        self.log(f"\n✅ 提取完成！共处理 {copied} 张，压缩 {compressed} 张，跳过 {skipped} 张")
        self.log(f"📁 目标目录: {target_dir}")
        self._msg_queue.put(("done", (copied, compressed, skipped, target_dir)))

    def execute_extract(self):
        """校验参数后启动后台线程"""
        if self._running:
            return

        source_dir = self.source_dir_var.get()
        target_dir = self.target_dir_var.get()

        if not source_dir:
            messagebox.showerror("错误", "请选择源目录")
            return
        if not target_dir:
            messagebox.showerror("错误", "请选择目标目录")
            return
        if not os.path.isdir(source_dir):
            messagebox.showerror("错误", "源目录不存在")
            return

        enable_compress = self.enable_compress_var.get()
        threshold_kb = self.compress_threshold_var.get()
        target_kb = self.compress_target_var.get()

        # 重置进度
        self.progress_var.set(0)
        self.progress_label.config(text="处理中...")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

        self._running = True
        self.extract_btn.config(text="处理中...", state=tk.DISABLED)

        # 创建消息队列并启动后台线程
        self._msg_queue = queue.Queue()
        t = threading.Thread(
            target=self._extract_worker,
            args=(source_dir, target_dir, enable_compress, threshold_kb, target_kb),
            daemon=True,
        )
        t.start()


if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractImagesApp(root)
    root.mainloop()
