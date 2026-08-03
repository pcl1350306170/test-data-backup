"""
图片按方向重命名工具
遍历所选目录及所有子目录，根据图片分辨率判断横屏/竖屏/头像，
重命名为 "{方向}-{子目录名}-{随机字符}{扩展名}" 格式。
支持一键撤销本次重命名操作。
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import sys
import json
import string
import random
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

# 方向标签
LABEL_LANDSCAPE = "横屏"
LABEL_PORTRAIT = "竖屏"
LABEL_AVATAR = "头像"

# 撤销记录文件名（保存在所选根目录下）
UNDO_LOG_FILE = "_rename_undo_log.json"

# 随机字符长度
RAND_LEN = 6


def random_suffix(length=RAND_LEN):
    """生成指定长度的随机字母数字字符串"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))


class ImageRenameApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片按方向重命名工具")
        self.root.geometry("720x540")
        self.root.resizable(True, True)

        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))

        # 变量
        self.target_dir = tk.StringVar(value="")
        self.running = False

        # 内存中的撤销记录（仅保留本次运行的一次操作）
        # 格式: [{"old_path": ..., "new_path": ...}, ...]
        self._undo_records = None

        # 监听相关
        self.monitoring = False          # 是否正在监听
        self._monitor_thread = None      # 监听线程
        self._known_files = set()        # 已知文件集合（用于检测新增文件）

        # 创建UI
        self._create_widgets()

        # 注册拖拽
        self._setup_dnd()

        logger.info("图片按方向重命名工具启动")

    # ──────────────── UI 构建 ────────────────

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── 目录选择区 ──
        dir_frame = ttk.LabelFrame(main_frame, text="目标目录", padding="8")
        dir_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Entry(dir_frame, textvariable=self.target_dir, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(dir_frame, text="选择目录", command=self._select_dir).pack(side=tk.LEFT, padx=2)
        ttk.Button(dir_frame, text="开始重命名", command=self._start_rename).pack(side=tk.LEFT, padx=2)
        ttk.Button(dir_frame, text="↩ 一键撤销", command=self._undo_rename).pack(side=tk.LEFT, padx=2)
        self.monitor_btn = ttk.Button(dir_frame, text="▶ 开始监听", command=self._toggle_monitor)
        self.monitor_btn.pack(side=tk.LEFT, padx=2)

        # ── 说明区 ──
        hint_frame = ttk.Frame(main_frame, padding="5")
        hint_frame.pack(fill=tk.X)
        ttk.Label(hint_frame,
                  text="规则：横屏图 → 横屏-目录名-随机串  |  竖屏图 → 竖屏-目录名-随机串  |  近似方形 → 头像-目录名-随机串",
                  foreground="gray").pack(anchor=tk.W)
        ttk.Label(hint_frame,
                  text="撤销仅限本次运行内的操作，关闭脚本后无法撤销。",
                  foreground="gray").pack(anchor=tk.W)

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

    # ──────────────── 拖拽支持 ────────────────

    def _setup_dnd(self):
        if HAS_WINDND:
            windnd.hook_dropfiles(self.root, func=self._on_windnd_drop)
        elif HAS_DND2:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_dnd2_drop)
        else:
            if len(sys.argv) > 1:
                dir_path = sys.argv[1]
                if os.path.isdir(dir_path):
                    self.target_dir.set(dir_path)

    def _on_windnd_drop(self, files):
        if files:
            try:
                path = files[0].decode('gbk', errors='ignore')
                self._handle_drop(path)
            except Exception:
                pass

    def _on_dnd2_drop(self, event):
        path = event.data.strip()
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]
        self._handle_drop(path)

    def _handle_drop(self, path):
        if os.path.isdir(path):
            self.target_dir.set(path)
            self._log(f"已选择目录: {path}")
        elif os.path.isfile(path):
            dir_path = os.path.dirname(path)
            self.target_dir.set(dir_path)
            self._log(f"已选择文件所在目录: {dir_path}")

    # ──────────────── 目录选择 ────────────────

    def _select_dir(self):
        dir_path = filedialog.askdirectory(title="选择图片所在目录（含子目录）")
        if dir_path:
            self.target_dir.set(dir_path)
            self._log(f"已选择目录: {dir_path}")

    # ──────────────── 开始重命名 ────────────────

    def _start_rename(self):
        dir_path = self.target_dir.get()
        if not dir_path or not os.path.isdir(dir_path):
            messagebox.showwarning("提示", "请先选择一个有效的目录")
            return
        if self.running:
            messagebox.showinfo("提示", "正在处理中，请稍候...")
            return

        # 如果内存中已有上一次的撤销记录，提示用户已失效
        if self._undo_records is not None:
            self._log("注意：之前的撤销记录已失效（每次运行仅支持撤销一次）")

        if not messagebox.askyesno("确认",
                                   f"将对目录及其子目录下的所有图片进行重命名，\n"
                                   f"确定继续吗？\n\n目录：{dir_path}"):
            return

        self.running = True
        thread = threading.Thread(target=self._rename_worker, args=(dir_path,), daemon=True)
        thread.start()

    # ──────────────── 重命名工作线程 ────────────────

    def _rename_worker(self, dir_path):
        try:
            from PIL import Image

            # 收集所有图片
            self._log("正在扫描图片文件...")
            image_files = self._collect_images(dir_path)
            total = len(image_files)

            if total == 0:
                self._log("未找到任何图片文件")
                self._update_status("未找到图片文件")
                return

            self._log(f"共找到 {total} 个图片文件，开始重命名...")
            self._update_progress(0, total)

            undo_records = []
            count_landscape = 0
            count_portrait = 0
            count_avatar = 0
            count_error = 0
            count_skipped = 0

            for idx, img_path in enumerate(image_files, 1):
                try:
                    # 检查是否已经重命名过（文件名以 横屏-/竖屏-/头像- 开头）
                    if self._is_already_renamed(img_path):
                        count_skipped += 1
                        self._update_progress(idx, total)
                        continue

                    # 获取图片方向
                    orientation = self._get_orientation(img_path)

                    if orientation == 'landscape':
                        label = LABEL_LANDSCAPE
                        count_landscape += 1
                    elif orientation == 'portrait':
                        label = LABEL_PORTRAIT
                        count_portrait += 1
                    else:
                        label = LABEL_AVATAR
                        count_avatar += 1

                    # 获取图片所在子目录名（相对于根目录的最近一级目录名）
                    img_dir = os.path.dirname(img_path)
                    folder_name = os.path.basename(img_dir)
                    if not folder_name:
                        folder_name = "root"

                    # 构建新文件名
                    _, ext = os.path.splitext(img_path)
                    ext = ext.lower()
                    new_name = f"{label}-{folder_name}-{random_suffix()}{ext}"
                    new_path = os.path.join(img_dir, new_name)

                    # 如果新文件名已存在，加随机后缀重试
                    retry = 0
                    while os.path.exists(new_path) and retry < 10:
                        new_name = f"{label}-{folder_name}-{random_suffix()}{ext}"
                        new_path = os.path.join(img_dir, new_name)
                        retry += 1

                    if os.path.exists(new_path):
                        self._log(f"  ⚠ 文件名冲突过多，跳过: {os.path.basename(img_path)}")
                        count_error += 1
                        self._update_progress(idx, total)
                        continue

                    # 执行重命名
                    os.rename(img_path, new_path)

                    # 记录撤销信息
                    undo_records.append({
                        "old_path": img_path,
                        "new_path": new_path
                    })

                    self._log(f"  → {os.path.basename(img_path)}  ➜  {new_name}")

                except Exception as e:
                    count_error += 1
                    self._log(f"  ✗ 处理失败: {os.path.basename(img_path)} | {e}")

                self._update_progress(idx, total)

            # 将撤销记录保存到内存（仅本次运行有效）
            self._undo_records = undo_records

            # 同时写入文件，以便在同一个会话中意外崩溃时仍可尝试恢复
            undo_file = os.path.join(dir_path, UNDO_LOG_FILE)
            try:
                with open(undo_file, 'w', encoding='utf-8') as f:
                    json.dump(undo_records, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            # 汇总
            summary = (f"重命名完成！横屏: {count_landscape}, 竖屏: {count_portrait}, "
                       f"头像: {count_avatar}, 跳过已重命名: {count_skipped}, 失败: {count_error}")
            self._log(f"\n{'='*40}")
            self._log(summary)
            self._log("提示：点击 [↩ 一键撤销] 可还原本次操作，关闭脚本后失效。")
            self._update_status(summary)
            logger.info(summary)

        except Exception as e:
            self._log(f"发生错误: {e}")
            logger.error(f"重命名过程出错: {e}")
        finally:
            self.running = False

    # ──────────────── 撤销重命名 ────────────────

    def _undo_rename(self):
        if self.running:
            messagebox.showinfo("提示", "正在处理中，请稍候...")
            return

        # 优先使用内存中的记录
        records = self._undo_records

        # 如果内存中没有，尝试从文件读取（同一次运行期间）
        if not records:
            dir_path = self.target_dir.get()
            if dir_path:
                undo_file = os.path.join(dir_path, UNDO_LOG_FILE)
                if os.path.exists(undo_file):
                    try:
                        with open(undo_file, 'r', encoding='utf-8') as f:
                            records = json.load(f)
                    except Exception:
                        records = None

        if not records:
            messagebox.showinfo("提示",
                                "没有可撤销的记录。\n\n"
                                "撤销仅对本次运行有效，关闭脚本后无法还原。")
            return

        if not messagebox.askyesno("确认撤销",
                                   f"将还原 {len(records)} 个文件的重命名，\n"
                                   f"确定继续吗？"):
            return

        self.running = True
        thread = threading.Thread(target=self._undo_worker, args=(records,), daemon=True)
        thread.start()

    def _undo_worker(self, records):
        try:
            total = len(records)
            self._log(f"\n开始撤销，共 {total} 条记录...")
            self._update_progress(0, total)

            success = 0
            fail = 0

            for idx, rec in enumerate(records, 1):
                old_path = rec["old_path"]
                new_path = rec["new_path"]
                try:
                    if os.path.exists(new_path):
                        os.rename(new_path, old_path)
                        success += 1
                        self._log(f"  ↩ {os.path.basename(new_path)}  ➜  {os.path.basename(old_path)}")
                    else:
                        self._log(f"  ⚠ 文件不存在，跳过: {os.path.basename(new_path)}")
                        fail += 1
                except Exception as e:
                    self._log(f"  ✗ 还原失败: {os.path.basename(new_path)} | {e}")
                    fail += 1

                self._update_progress(idx, total)

            # 清除内存和文件中的撤销记录
            self._undo_records = None
            dir_path = self.target_dir.get()
            if dir_path:
                undo_file = os.path.join(dir_path, UNDO_LOG_FILE)
                if os.path.exists(undo_file):
                    try:
                        os.remove(undo_file)
                    except Exception:
                        pass

            summary = f"撤销完成！还原: {success}, 失败: {fail}"
            self._log(f"\n{'='*40}")
            self._log(summary)
            self._update_status(summary)
            logger.info(summary)

        except Exception as e:
            self._log(f"撤销出错: {e}")
            logger.error(f"撤销过程出错: {e}")
        finally:
            self.running = False

    # ──────────────── 目录监听 ────────────────

    def _toggle_monitor(self):
        """切换监听状态"""
        if self.monitoring:
            # 停止监听
            self.monitoring = False
            self.monitor_btn.config(text="▶ 开始监听")
            self._log("已停止目录监听")
            self._update_status("监听已停止")
        else:
            # 开始监听
            dir_path = self.target_dir.get()
            if not dir_path or not os.path.isdir(dir_path):
                messagebox.showwarning("提示", "请先选择一个有效的目录")
                return
            self.monitoring = True
            self.monitor_btn.config(text="■ 停止监听")
            self._known_files = set()
            self._log(f"开始监听目录: {dir_path}")
            self._log("将检查所有已有文件及新增文件，不符合命名规则的自动重命名")
            self._update_status(f"正在监听: {dir_path}")
            # 启动监听线程
            self._monitor_thread = threading.Thread(
                target=self._monitor_worker, args=(dir_path,), daemon=True)
            self._monitor_thread.start()

    def _snapshot_files(self, dir_path):
        """快照目录下所有图片文件路径"""
        files = []
        for dirpath, _, filenames in os.walk(dir_path):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMAGE_EXTS:
                    files.append(os.path.join(dirpath, fname))
        return files

    def _monitor_worker(self, dir_path):
        """监听工作线程：先扫描所有已有文件，再持续监听新增文件，不符合命名规则的自动重命名"""
        from PIL import Image

        poll_interval = 2  # 轮询间隔（秒）
        rename_count = 0

        self._log(f"监听线程已启动（每 {poll_interval} 秒检查一次）")

        # ── 第一轮：扫描目录下所有已有文件，不符合规则的全部重命名 ──
        self._log("正在扫描目录下所有已有文件...")
        try:
            all_files = self._snapshot_files(dir_path)
            to_check = [f for f in all_files if not self._is_already_renamed(f)]
            self._log(f"共 {len(all_files)} 个图片，其中 {len(to_check)} 个不符合命名规则，开始处理...")

            for img_path in to_check:
                if not self.monitoring:
                    break
                if not self._wait_file_stable(img_path):
                    continue
                try:
                    new_path = self._do_rename(img_path)
                    if new_path:
                        rename_count += 1
                except Exception as e:
                    self._log(f"  ✗ [扫描] 处理失败: {os.path.basename(img_path)} | {e}")

            if rename_count > 0:
                self._log(f"[扫描阶段] 共重命名 {rename_count} 个文件")
            else:
                self._log("[扫描阶段] 所有文件均已符合命名规则，无需处理")
        except Exception as e:
            self._log(f"  ✗ [扫描] 出错: {e}")

        # 扫描完成后，快照当前文件集合，后续只处理新增
        self._known_files = set(self._snapshot_files(dir_path))

        # ── 后续轮询：只监听新增文件 ──
        while self.monitoring:
            try:
                current_files = self._snapshot_files(dir_path)
                current_set = set(current_files)

                # 找出新增的文件
                new_files = current_set - self._known_files

                for new_file in new_files:
                    if not self.monitoring:
                        break

                    # 跳过已按规则命名的文件
                    if self._is_already_renamed(new_file):
                        continue

                    # 等待文件写入完成（文件大小不再变化）
                    if not self._wait_file_stable(new_file):
                        continue

                    try:
                        new_path = self._do_rename(new_file)
                        if new_path:
                            rename_count += 1
                    except Exception as e:
                        self._log(f"  ✗ [监听] 处理失败: {os.path.basename(new_file)} | {e}")

                # 重新快照以包含重命名后的新文件
                self._known_files = set(self._snapshot_files(dir_path))

            except Exception as e:
                self._log(f"  ✗ [监听] 扫描出错: {e}")

            # 等待下一次轮询
            for _ in range(poll_interval * 10):
                if not self.monitoring:
                    break
                threading.Event().wait(0.1)

        self._log(f"监听线程已停止，本次共自动重命名 {rename_count} 个文件")

    def _wait_file_stable(self, file_path, timeout=5):
        """等待文件写入完成（文件大小稳定），返回 True 表示稳定"""
        try:
            prev_size = -1
            for _ in range(timeout * 10):
                if not os.path.isfile(file_path):
                    return False
                curr_size = os.path.getsize(file_path)
                if curr_size == prev_size and curr_size > 0:
                    return True
                prev_size = curr_size
                threading.Event().wait(0.1)
            return prev_size > 0
        except Exception:
            return False

    def _do_rename(self, img_path):
        """对单个图片文件执行重命名，返回新路径；失败或跳过返回 None"""
        orientation = self._get_orientation(img_path)

        if orientation == 'landscape':
            label = LABEL_LANDSCAPE
        elif orientation == 'portrait':
            label = LABEL_PORTRAIT
        else:
            label = LABEL_AVATAR

        img_dir = os.path.dirname(img_path)
        folder_name = os.path.basename(img_dir) or "root"
        _, ext = os.path.splitext(img_path)
        ext = ext.lower()

        new_name = f"{label}-{folder_name}-{random_suffix()}{ext}"
        new_path = os.path.join(img_dir, new_name)

        retry = 0
        while os.path.exists(new_path) and retry < 10:
            new_name = f"{label}-{folder_name}-{random_suffix()}{ext}"
            new_path = os.path.join(img_dir, new_name)
            retry += 1

        if os.path.exists(new_path):
            self._log(f"  ⚠ 文件名冲突过多，跳过: {os.path.basename(img_path)}")
            return None

        os.rename(img_path, new_path)
        self._log(f"  [监听] → {os.path.basename(img_path)}  ➜  {new_name}")
        return new_path

    # ──────────────── 工具方法 ────────────────

    def _collect_images(self, root_dir):
        """递归收集所有图片文件路径"""
        images = []
        for dirpath, _, filenames in os.walk(root_dir):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMAGE_EXTS:
                    images.append(os.path.join(dirpath, fname))
        return images

    def _is_already_renamed(self, img_path):
        """检查文件名是否已经是重命名后的格式：{横屏/竖屏/头像}-xxx-随机字符.ext"""
        filename = os.path.basename(img_path)
        for label in (LABEL_LANDSCAPE, LABEL_PORTRAIT, LABEL_AVATAR):
            prefix = f"{label}-"
            if filename.startswith(prefix):
                return True
        return False

    def _get_orientation(self, img_path):
        """
        根据图片分辨率判断方向：
        - 'landscape': 横屏（宽 > 高，且宽高比 > 1.15）
        - 'portrait':  竖屏（高 > 宽，且高宽比 > 1.15）
        - 'avatar':    头像（近似方形，宽高比在 0.87~1.15 之间）
        """
        from PIL import Image
        with Image.open(img_path) as img:
            w, h = img.size

        if w == 0 or h == 0:
            return 'avatar'

        ratio = w / h

        if ratio > 1.15:
            return 'landscape'
        elif ratio < 0.87:
            return 'portrait'
        else:
            return 'avatar'

    # ──────────── UI 更新（线程安全）────────────

    def _log(self, msg):
        def _do():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _do)

    def _update_progress(self, current, total):
        def _do():
            self.progress['maximum'] = total
            self.progress['value'] = current
            self.status_label.config(text=f"处理中: {current}/{total}")
        self.root.after(0, _do)

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_label.config(text=text))


if __name__ == "__main__":
    if HAS_DND2:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = ImageRenameApp(root)
    root.mainloop()
