import os
import sys
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

# 可选依赖：统一日志模块（导入失败时静默降级，不影响功能）
sys.path.insert(0, str(SCRIPT_DIR.parent))
try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _Dummy:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _Dummy()

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
            "transfer_mode": "move",
            "image_formats": list(IMAGE_EXTS),
            "enable_compress": True,
            "compress_threshold_kb": 700,
            "compress_target_kb": 300,
        }

        self._format_vars = {}  # ext -> BooleanVar

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

        # 传输方式：移动 / 复制（移动模式下不压缩，直接移动文件）
        ttk.Label(frame_main, text="传输方式:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.transfer_mode_var = tk.StringVar(value=self.config["transfer_mode"])
        mode_frame = ttk.Frame(frame_main)
        mode_frame.grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=5)
        ttk.Radiobutton(mode_frame, text="移动（不压缩，直接移动）", variable=self.transfer_mode_var,
                        value="move", command=self._on_mode_change).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_frame, text="复制", variable=self.transfer_mode_var,
                        value="copy", command=self._on_mode_change).pack(side=tk.LEFT, padx=10)

        # 图片格式选择（默认全选）
        ttk.Label(frame_main, text="图片格式:").grid(row=3, column=0, sticky=tk.NW, pady=5)
        fmt_frame = ttk.Frame(frame_main)
        fmt_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=5)
        for i, ext in enumerate(IMAGE_EXTS):
            var = tk.BooleanVar(value=ext in self.config["image_formats"])
            self._format_vars[ext] = var
            ttk.Checkbutton(fmt_frame, text=ext, variable=var).grid(row=i // 4, column=i % 4, sticky=tk.W, padx=2)

        # 是否压缩（仅复制模式生效）
        self.enable_compress_var = tk.BooleanVar(value=self.config["enable_compress"])
        self.compress_cb = ttk.Checkbutton(frame_main, text="压缩超过阈值的图片（仅复制模式生效）", variable=self.enable_compress_var)
        self.compress_cb.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=5)

        # 压缩阈值
        ttk.Label(frame_main, text="压缩阈值(KB):").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.compress_threshold_var = tk.IntVar(value=self.config["compress_threshold_kb"])
        self.threshold_entry = ttk.Entry(frame_main, textvariable=self.compress_threshold_var, width=10)
        self.threshold_entry.grid(row=5, column=1, sticky=tk.W, pady=5)
        ttk.Label(frame_main, text="超过此大小的图片将被压缩", foreground="gray").grid(row=5, column=2, sticky=tk.W, padx=5)

        # 压缩目标大小
        ttk.Label(frame_main, text="压缩目标大小(KB):").grid(row=6, column=0, sticky=tk.W, pady=5)
        self.compress_target_var = tk.IntVar(value=self.config["compress_target_kb"])
        self.target_entry = ttk.Entry(frame_main, textvariable=self.compress_target_var, width=10)
        self.target_entry.grid(row=6, column=1, sticky=tk.W, pady=5)
        ttk.Label(frame_main, text="压缩后图片的目标大小", foreground="gray").grid(row=6, column=2, sticky=tk.W, padx=5)

        # 按钮
        btn_frame = ttk.Frame(frame_main)
        btn_frame.grid(row=7, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        self.extract_btn = ttk.Button(btn_frame, text="开始提取", command=self.execute_extract)
        self.extract_btn.pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="清空目标图片", command=self.clear_target_images).pack(side=tk.LEFT, padx=10)

        self._on_mode_change()  # 根据加载的模式初始化控件状态

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

    def _on_mode_change(self):
        """移动模式下禁用压缩相关控件"""
        state = tk.NORMAL if self.transfer_mode_var.get() == "copy" else tk.DISABLED
        self.compress_cb.config(state=state)
        self.threshold_entry.config(state=state)
        self.target_entry.config(state=state)

    def _show_toast(self, title, message, level="info", duration_ms=3500):
        """右下角 Toast 通知，duration_ms 毫秒后自动消失"""
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)

            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error":   ("#c62828", "#ffebee", "❌"),
                "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
                "warning": ("#e65100", "#fff3e0", "⚠️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)

            header = tk.Frame(toast, bg=bg)
            header.pack(fill=tk.X, padx=10, pady=8)
            tk.Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                     fg=fg, bg=bg).pack(side=tk.LEFT)
            close_btn = tk.Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())

            tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                     fg="#333", bg=bg, wraplength=320, justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)

            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            sx = toast.winfo_screenwidth()
            sy = toast.winfo_screenheight()
            x = sx - w - 20
            y = sy - h - 60
            toast.geometry(f"+{x}+{y}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    def clear_target_images(self):
        """一键清空目标目录下的所有图片"""
        if self._running:
            self._show_toast("提示", "正在处理中，请等待完成", "warning")
            return

        target_dir = self.target_dir_var.get()
        if not target_dir or not os.path.isdir(target_dir):
            self._show_toast("提示", "请先选择有效的目标目录", "warning")
            return

        images = [f for f in os.listdir(target_dir)
                  if os.path.isfile(os.path.join(target_dir, f)) and f.lower().endswith(IMAGE_EXTS)]
        if not images:
            self._show_toast("提示", "目标目录下没有图片", "info")
            return

        if not messagebox.askyesno("确认", f"确定要清空目标目录下的 {len(images)} 张图片吗？\n此操作不可恢复！"):
            return

        deleted, failed = 0, 0
        for f in images:
            try:
                os.remove(os.path.join(target_dir, f))
                deleted += 1
            except Exception as e:
                failed += 1
                logger.error(f"删除失败: {f} ({e})")

        self.log(f"已清空目标目录: 删除 {deleted} 张" + (f"，失败 {failed} 张" if failed else ""))
        logger.info(f"清空目标目录: 删除 {deleted} 张, 失败 {failed} 张 -> {target_dir}")
        if failed:
            self._show_toast("清空完成", f"删除 {deleted} 张，失败 {failed} 张", "warning")
        else:
            self._show_toast("清空完成", f"已删除 {deleted} 张图片", "success")

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
                "transfer_mode": self.transfer_mode_var.get(),
                "image_formats": [ext for ext, var in self._format_vars.items() if var.get()],
                "enable_compress": self.enable_compress_var.get(),
                "compress_threshold_kb": self.compress_threshold_var.get(),
                "compress_target_kb": self.compress_target_var.get(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.log("配置已保存")
            logger.info("配置已保存")
            self._show_toast("成功", "配置已保存", "success")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            self._show_toast("错误", f"保存配置失败: {e}", "error")

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
        moved, compressed, skipped, target_dir = result
        if moved == 0 and compressed == 0 and skipped == 0:
            self._show_toast("提示", "源目录下未找到任何图片", "info")
        elif skipped > 0:
            self._show_toast("提取完成", f"处理 {moved} 张，压缩 {compressed} 张，跳过 {skipped} 张", "warning")
        else:
            self._show_toast("提取完成", f"处理 {moved} 张，压缩 {compressed} 张", "success")

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

    @staticmethod
    def _unique_dst(target_dir, filename, used_names):
        """目标目录重名时自动追加序号: a.jpg -> a(1).jpg"""
        dst = os.path.join(target_dir, filename)
        if os.path.exists(dst) or filename.lower() in used_names:
            base, ext = os.path.splitext(filename)
            i = 1
            while True:
                new_name = f"{base}({i}){ext}"
                dst = os.path.join(target_dir, new_name)
                if not os.path.exists(dst) and new_name.lower() not in used_names:
                    filename = new_name
                    break
                i += 1
        used_names.add(filename.lower())
        return dst

    # ---------- 核心提取（后台线程） ----------
    def _extract_worker(self, source_dir, target_dir, transfer_mode, exts,
                        enable_compress, threshold_kb, target_kb):
        """在后台线程中执行提取，通过队列与 UI 通信"""
        self.log("正在扫描目录...")
        all_images = []
        for root_dir, _dirs, files in os.walk(source_dir):
            for f in files:
                if f.lower().endswith(tuple(exts)):
                    all_images.append(os.path.join(root_dir, f))

        total = len(all_images)
        if total == 0:
            self.log("未找到任何图片")
            logger.warning(f"源目录下未找到任何图片: {source_dir}")
            self._msg_queue.put(("done", (0, 0, 0, target_dir)))
            return

        mode_text = "移动" if transfer_mode == "move" else "复制"
        self.log(f"共找到 {total} 张图片，开始{mode_text}...")
        logger.info(f"源目录: {source_dir} | 目标目录: {target_dir} | 模式: {mode_text} | 共 {total} 张")
        os.makedirs(target_dir, exist_ok=True)

        moved = 0
        compressed = 0
        skipped = 0
        used_names = set()  # 已占用的目标文件名（小写），用于重名检测

        for idx, img_path in enumerate(all_images, 1):
            filename = os.path.basename(img_path)
            dst_path = self._unique_dst(target_dir, filename, used_names)

            try:
                if transfer_mode == "move":
                    # 移动模式：直接移动，不压缩，原文件不保留
                    shutil.move(img_path, dst_path)
                    moved += 1
                    if os.path.basename(dst_path) != filename:
                        self.log(f"[{idx}/{total}] 移动(重命名): {filename} -> {os.path.basename(dst_path)}")
                    else:
                        self.log(f"[{idx}/{total}] 移动: {filename}")
                    continue

                # 复制模式：可选压缩，完成后删除原文件（等效移动）
                file_size_kb = os.path.getsize(img_path) / 1024

                if enable_compress and file_size_kb > threshold_kb:
                    _, ext = os.path.splitext(os.path.basename(dst_path))
                    if ext.lower() in ('.png', '.bmp', '.gif', '.tiff', '.tif', '.webp'):
                        compress_name = os.path.splitext(os.path.basename(dst_path))[0] + '.jpg'
                        compress_dst = os.path.join(target_dir, compress_name)
                        used_names.add(compress_name.lower())
                        try:
                            self.compress_image(img_path, compress_dst, target_kb, '.jpg')
                            compressed += 1
                            moved += 1
                            self.log(f"[{idx}/{total}] 压缩并转换: {filename} -> {compress_name}")
                        except Exception as e:
                            shutil.copy2(img_path, dst_path)
                            moved += 1
                            self.log(f"[{idx}/{total}] 压缩失败，直接复制: {filename} ({e})")
                    else:
                        self.compress_image(img_path, dst_path, target_kb, ext)
                        compressed += 1
                        moved += 1
                        self.log(f"[{idx}/{total}] 压缩: {filename}")
                else:
                    shutil.copy2(img_path, dst_path)
                    moved += 1
                    self.log(f"[{idx}/{total}] 复制: {filename}")

                os.remove(img_path)

            except Exception as e:
                skipped += 1
                self.log(f"[{idx}/{total}] 处理失败: {filename} ({e})")
                logger.error(f"处理失败: {img_path} ({e})")

            self.set_progress(idx, total)

        self.log(f"\n✅ 提取完成！共处理 {moved} 张，压缩 {compressed} 张，跳过 {skipped} 张")
        self.log(f"📁 目标目录: {target_dir}")
        logger.info(f"提取完成: 处理 {moved} 张, 压缩 {compressed} 张, 跳过 {skipped} 张 -> {target_dir}")
        self._msg_queue.put(("done", (moved, compressed, skipped, target_dir)))

    def execute_extract(self):
        """校验参数后启动后台线程"""
        if self._running:
            return

        source_dir = self.source_dir_var.get()
        target_dir = self.target_dir_var.get()

        if not source_dir:
            self._show_toast("错误", "请选择源目录", "error")
            return
        if not target_dir:
            self._show_toast("错误", "请选择目标目录", "error")
            return
        if not os.path.isdir(source_dir):
            self._show_toast("错误", "源目录不存在", "error")
            return

        # 防止源目录与目标目录相同导致图片被误删/覆盖
        try:
            if os.path.abspath(source_dir).lower() == os.path.abspath(target_dir).lower() \
                    or os.path.samefile(source_dir, target_dir):
                self._show_toast("错误", "源目录与目标目录不能相同", "error")
                return
        except OSError:
            pass

        exts = [ext for ext, var in self._format_vars.items() if var.get()]
        if not exts:
            self._show_toast("错误", "请至少选择一种图片格式", "error")
            return

        transfer_mode = self.transfer_mode_var.get()
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
            args=(source_dir, target_dir, transfer_mode, exts,
                  enable_compress, threshold_kb, target_kb),
            daemon=True,
        )
        t.start()


if __name__ == "__main__":
    root = tk.Tk()
    app = ExtractImagesApp(root)
    root.mainloop()
