"""
图片方向分类工具
在每个子目录下新建 竖屏/横屏 文件夹，将图片按方向分类到对应子目录。
保持原有目录结构不变，1:1 比例的图片跳过。
支持撤销操作（回退）。
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import sys
import shutil
import json
import threading
from pathlib import Path

# ──────────── 公共日志模块（可选依赖）────────────
_PY_DIR = str(Path(__file__).resolve().parent.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger()
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

# 尝试导入拖拽支持
try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND2 = True
except ImportError:
    HAS_DND2 = False

# 支持的图片扩展名
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif'}

# 分类目录名
DIR_PORTRAIT = "竖屏"
DIR_LANDSCAPE = "横屏"

# 操作记录文件名（用于回退）
UNDO_LOG_FILE = "_classify_undo_log.json"


class ImageClassifierApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📂 图片方向分类工具")
        self.root.geometry("700x520")
        self.root.resizable(True, True)

        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))

        # 变量
        self.target_dir = tk.StringVar(value="")
        self.running = False
        self.move_mode = tk.StringVar(value="move")  # move / copy

        # 创建UI
        self._create_widgets()

        # 注册拖拽
        self._setup_dnd()

        logger.info("图片方向分类工具启动")

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── 目录选择区 ──
        dir_frame = ttk.LabelFrame(main_frame, text="目标目录", padding="8")
        dir_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Entry(dir_frame, textvariable=self.target_dir, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(dir_frame, text="选择目录", command=self._select_dir).pack(side=tk.LEFT, padx=2)
        ttk.Button(dir_frame, text="开始分类", command=self._start_classify).pack(side=tk.LEFT, padx=2)
        ttk.Button(dir_frame, text="↩ 撤销", command=self._undo_classify).pack(side=tk.LEFT, padx=2)

        # ── 选项区 ──
        opt_frame = ttk.Frame(main_frame, padding="5")
        opt_frame.pack(fill=tk.X)

        ttk.Radiobutton(opt_frame, text="移动文件", variable=self.move_mode, value="move").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(opt_frame, text="复制文件", variable=self.move_mode, value="copy").pack(side=tk.LEFT, padx=5)

        ttk.Label(opt_frame, text="（在各子目录下新建竖屏/横屏，1:1跳过，保持目录结构）",
                  foreground="gray").pack(side=tk.LEFT, padx=10)

        # ── 进度条 ──
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)

        self.status_label = ttk.Label(main_frame, text="请选择或拖拽一个目录")
        self.status_label.pack(anchor=tk.W)

        # ── 日志区 ──
        log_frame = ttk.LabelFrame(main_frame, text="处理日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.log_text = tk.Text(log_frame, height=15, font=("Consolas", 9), state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _setup_dnd(self):
        """设置拖拽支持"""
        if HAS_WINDND:
            windnd.hook_dropfiles(self.root, func=self._on_windnd_drop)
        elif HAS_DND2:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_dnd2_drop)
        else:
            # 命令行参数支持
            if len(sys.argv) > 1:
                dir_path = sys.argv[1]
                if os.path.isdir(dir_path):
                    self.target_dir.set(dir_path)

    def _on_windnd_drop(self, files):
        """windnd 拖拽回调"""
        if files:
            try:
                path = files[0].decode('gbk', errors='ignore')
                self._handle_drop(path)
            except Exception:
                pass

    def _on_dnd2_drop(self, event):
        """tkinterdnd2 拖拽回调"""
        path = event.data.strip()
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]
        self._handle_drop(path)

    def _handle_drop(self, path):
        """处理拖拽进来的路径"""
        if os.path.isdir(path):
            self.target_dir.set(path)
            self._log(f"已选择目录: {path}")
        elif os.path.isfile(path):
            # 如果拖入的是文件，取其所在目录
            dir_path = os.path.dirname(path)
            self.target_dir.set(dir_path)
            self._log(f"已选择文件所在目录: {dir_path}")

    def _select_dir(self):
        """选择目录"""
        dir_path = filedialog.askdirectory(title="选择要分类的图片目录")
        if dir_path:
            self.target_dir.set(dir_path)
            self._log(f"已选择目录: {dir_path}")

    def _start_classify(self):
        """开始分类"""
        dir_path = self.target_dir.get()
        if not dir_path or not os.path.isdir(dir_path):
            messagebox.showwarning("提示", "请先选择一个有效的目录")
            return
        if self.running:
            messagebox.showinfo("提示", "正在处理中，请稍候...")
            return

        # 在后台线程执行
        self.running = True
        thread = threading.Thread(target=self._classify_worker, args=(dir_path,), daemon=True)
        thread.start()

    def _undo_classify(self):
        """撤销上次分类操作"""
        dir_path = self.target_dir.get()
        if not dir_path or not os.path.isdir(dir_path):
            messagebox.showwarning("提示", "请先选择之前分类过的目录")
            return
        if self.running:
            messagebox.showinfo("提示", "正在处理中，请稍候...")
            return

        undo_file = os.path.join(dir_path, UNDO_LOG_FILE)
        if not os.path.exists(undo_file):
            messagebox.showinfo("提示", "未找到操作记录，无法撤销")
            return

        if not messagebox.askyesno("确认撤销", "将把所有已分类的图片移回原位置，确定继续？"):
            return

        self.running = True
        thread = threading.Thread(target=self._undo_worker, args=(dir_path, undo_file), daemon=True)
        thread.start()

    def _classify_worker(self, dir_path):
        """后台分类工作线程：在每个子目录下新建竖屏/横屏"""
        try:
            mode = self.move_mode.get()
            undo_records = []  # 记录操作，用于回退

            # 收集所有图片文件
            self._log("正在扫描图片文件...")
            image_files = self._collect_images(dir_path)
            total = len(image_files)

            if total == 0:
                self._log("未找到任何图片文件")
                self._update_status("未找到图片文件")
                return

            self._log(f"共找到 {total} 个图片文件，开始分类...")
            self._update_progress(0, total)

            count_portrait = 0
            count_landscape = 0
            count_square = 0
            count_error = 0

            for idx, img_path in enumerate(image_files, 1):
                try:
                    orientation = self._get_orientation(img_path)

                    if orientation == 'square':
                        count_square += 1
                        self._update_progress(idx, total)
                        continue

                    # 在图片所在目录下新建 竖屏/横屏 子目录
                    img_dir = os.path.dirname(img_path)
                    if orientation == 'portrait':
                        target_dir = os.path.join(img_dir, DIR_PORTRAIT)
                        count_portrait += 1
                    else:
                        target_dir = os.path.join(img_dir, DIR_LANDSCAPE)
                        count_landscape += 1

                    os.makedirs(target_dir, exist_ok=True)
                    dest = self._transfer(img_path, target_dir, mode)

                    # 记录操作（仅移动模式需要回退）
                    if mode == "move":
                        undo_records.append({"src": img_path, "dest": dest})

                except Exception as e:
                    count_error += 1
                    self._log(f"  ✗ 处理失败: {os.path.basename(img_path)} | {e}")

                self._update_progress(idx, total)

            # 保存操作记录（用于撤销）
            if undo_records:
                undo_file = os.path.join(dir_path, UNDO_LOG_FILE)
                with open(undo_file, 'w', encoding='utf-8') as f:
                    json.dump(undo_records, f, ensure_ascii=False, indent=2)
                self._log(f"操作记录已保存: {UNDO_LOG_FILE}（可用于撤销）")

            # 汇总
            summary = (f"分类完成！竖屏: {count_portrait} 张, 横屏: {count_landscape} 张, "
                       f"1:1跳过: {count_square} 张, 失败: {count_error} 张")
            self._log(f"\n{'='*40}")
            self._log(summary)
            self._update_status(summary)
            logger.info(summary)

        except Exception as e:
            self._log(f"发生错误: {e}")
            logger.error(f"分类过程出错: {e}")
        finally:
            self.running = False

    def _undo_worker(self, dir_path, undo_file):
        """撤销分类：把文件移回原位置"""
        try:
            with open(undo_file, 'r', encoding='utf-8') as f:
                records = json.load(f)

            total = len(records)
            self._log(f"\n开始撤销，共 {total} 条记录...")
            self._update_progress(0, total)

            success = 0
            fail = 0

            for idx, rec in enumerate(records, 1):
                src = rec["src"]   # 原始路径
                dest = rec["dest"]  # 分类后路径
                try:
                    if os.path.exists(dest):
                        # 确保原目录存在
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(dest, src)
                        success += 1
                    else:
                        self._log(f"  ⚠ 文件不存在，跳过: {os.path.basename(dest)}")
                        fail += 1
                except Exception as e:
                    self._log(f"  ✗ 还原失败: {os.path.basename(dest)} | {e}")
                    fail += 1

                self._update_progress(idx, total)

            # 删除操作记录文件
            os.remove(undo_file)

            # 清理空的竖屏/横屏目录
            self._cleanup_empty_dirs(dir_path)

            summary = f"撤销完成！还原: {success} 张, 失败: {fail} 张"
            self._log(f"\n{'='*40}")
            self._log(summary)
            self._update_status(summary)
            logger.info(summary)

        except Exception as e:
            self._log(f"撤销出错: {e}")
            logger.error(f"撤销过程出错: {e}")
        finally:
            self.running = False

    def _cleanup_empty_dirs(self, root_dir):
        """清理空的竖屏/横屏子目录"""
        for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
            basename = os.path.basename(dirpath)
            if basename in (DIR_PORTRAIT, DIR_LANDSCAPE):
                try:
                    if not os.listdir(dirpath):
                        os.rmdir(dirpath)
                        self._log(f"  已删除空目录: {os.path.relpath(dirpath, root_dir)}")
                except Exception:
                    pass

    def _collect_images(self, root_dir):
        """递归收集所有图片文件（排除竖屏/横屏分类目录）"""
        images = []
        skip_dirs = {DIR_PORTRAIT, DIR_LANDSCAPE}

        for dirpath, dirnames, filenames in os.walk(root_dir):
            # 排除分类目标子目录，避免重复处理
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]

            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMAGE_EXTS:
                    images.append(os.path.join(dirpath, fname))

        return images

    def _get_orientation(self, img_path):
        """
        获取图片方向:
        - 'portrait': 竖屏 (高 > 宽)
        - 'landscape': 横屏 (宽 > 高)
        - 'square': 1:1 比例
        """
        from PIL import Image
        with Image.open(img_path) as img:
            w, h = img.size

        if w == h:
            return 'square'
        elif h > w:
            return 'portrait'
        else:
            return 'landscape'

    def _transfer(self, src, dest_dir, mode):
        """移动或复制文件到目标目录，处理同名文件，返回目标路径"""
        filename = os.path.basename(src)
        dest = os.path.join(dest_dir, filename)

        # 处理同名文件
        if os.path.exists(dest):
            name, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(dest_dir, f"{name}_{counter}{ext}")
                counter += 1

        if mode == "move":
            shutil.move(src, dest)
        else:
            shutil.copy2(src, dest)

        self._log(f"  → {os.path.relpath(dest, os.path.dirname(os.path.dirname(dest)))}")
        return dest

    # ──────────── UI 更新（线程安全）────────────

    def _log(self, msg):
        """线程安全地写入日志"""
        def _do():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _do)

    def _update_progress(self, current, total):
        """线程安全地更新进度条"""
        def _do():
            self.progress['maximum'] = total
            self.progress['value'] = current
            self.status_label.config(text=f"处理中: {current}/{total}")
        self.root.after(0, _do)

    def _update_status(self, text):
        """线程安全地更新状态"""
        self.root.after(0, lambda: self.status_label.config(text=text))


if __name__ == "__main__":
    if HAS_DND2:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = ImageClassifierApp(root)
    root.mainloop()
