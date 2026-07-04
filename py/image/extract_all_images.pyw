import os
import json
import shutil
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

        self.config = {
            "source_dir": "",
            "target_dir": "",
            "enable_compress": True,
            "compress_threshold_kb": 700,
            "compress_target_kb": 300,
        }

        self.load_config()
        self.create_widgets()

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
        ttk.Button(btn_frame, text="开始提取", command=self.execute_extract).pack(side=tk.LEFT, padx=10)

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
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def set_progress(self, current, total):
        pct = (current / total * 100) if total > 0 else 0
        self.progress_var.set(pct)
        self.progress_label.config(text=f"进度: {current}/{total}  ({pct:.1f}%)")
        self.root.update_idletasks()

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

    # ---------- 核心提取 ----------
    def execute_extract(self):
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

        # 收集所有图片
        self.log("正在扫描目录...")
        all_images = []
        for root_dir, _dirs, files in os.walk(source_dir):
            for f in files:
                if f.lower().endswith(IMAGE_EXTS):
                    all_images.append(os.path.join(root_dir, f))

        total = len(all_images)
        if total == 0:
            self.log("未找到任何图片")
            messagebox.showinfo("提示", "源目录下未找到任何图片")
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
                    # 需要压缩
                    _, ext = os.path.splitext(filename)
                    # 如果目标格式不支持压缩(JPEG)，仍然尝试保存为原格式
                    if ext.lower() in ('.png', '.bmp', '.gif', '.tiff', '.tif', '.webp'):
                        # PNG 等无损格式，先尝试转 JPEG 压缩
                        compress_dst = os.path.join(target_dir, os.path.splitext(filename)[0] + '.jpg')
                        try:
                            self.compress_image(img_path, compress_dst, target_kb, '.jpg')
                            compressed += 1
                            copied += 1
                            self.log(f"[{idx}/{total}] 压缩并转换: {filename} -> {os.path.basename(compress_dst)}")
                        except Exception as e:
                            # 转换失败则直接复制原文件
                            shutil.copy2(img_path, dst_path)
                            copied += 1
                            self.log(f"[{idx}/{total}] 压缩失败，直接复制: {filename} ({e})")
                    else:
                        # JPEG 格式直接压缩
                        self.compress_image(img_path, dst_path, target_kb, ext)
                        compressed += 1
                        copied += 1
                        self.log(f"[{idx}/{total}] 压缩: {filename}")
                else:
                    # 直接剪切(复制覆盖)
                    shutil.copy2(img_path, dst_path)
                    copied += 1
                    self.log(f"[{idx}/{total}] 复制: {filename}")

                # 剪切：删除原文件
                os.remove(img_path)

            except Exception as e:
                skipped += 1
                self.log(f"[{idx}/{total}] 处理失败: {filename} ({e})")

            self.set_progress(idx, total)

        self.log(f"\n✅ 提取完成！共处理 {copied} 张，压缩 {compressed} 张，跳过 {skipped} 张")
        self.log(f"📁 目标目录: {target_dir}")
        messagebox.showinfo("完成", f"提取完成！\n复制: {copied} 张\n压缩: {compressed} 张\n跳过: {skipped} 张")


if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractImagesApp(root)
    root.mainloop()
