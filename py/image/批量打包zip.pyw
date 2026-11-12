# batch_zipper_enhanced.py
# 批量打包压缩工具：单人单任务使用，支持暂停/断点续压
# 四种打包模式：按每包文件数分批 / 按压缩包大小分批 / 源目录下每个一级子目录独立包 / 手动选中的每个文件夹独立包

import json
import logging
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "batch_zipper"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"
TMP_FILELIST_PATTERN = "tmp_filelist_*.txt"  # 传给 7z 的临时文件清单

CONFIG_DIR.mkdir(exist_ok=True, parents=True)
LOG_DIR.mkdir(exist_ok=True, parents=True)

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
    "pack_mode": "size",  # files / size / subdir / selected
    "selected_dirs": [],  # “选中文件夹独立打包”模式下的文件夹列表
    "max_archive_size_mb": 3072,  # 默认3GB
    "encrypt_header": False  # 加密文件名（仅 7z 格式支持）
}

MAX_LOG_LINES = 3000  # 界面日志保留行数，避免长时间运行内存膨胀
UI_POLL_MS = 120  # 主线程拉取 UI 队列的间隔

# 本脚本以 .pyw（pythonw.exe）运行，本身没有控制台；一旦派生 7z.exe 这类控制台程序，
# Windows 会为其新建一个黑窗口（即使输重定向到 DEVNULL 也照样弹），因此禁止分配控制台
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0

RESULT_DONE = "done"
RESULT_ABORTED = "aborted"

# 打包模式（互斥，界面用单选按钮组）
MODE_BATCH_FILES = "files"      # 全部文件按每包文件数分批
MODE_BATCH_SIZE = "size"        # 全部文件按压缩包大小上限分批
MODE_SUBDIR = "subdir"          # 源目录下每个一级子目录一个包
MODE_SELECTED = "selected"      # 手动添加的每个文件夹一个包
PACK_MODES = (MODE_BATCH_FILES, MODE_BATCH_SIZE, MODE_SUBDIR, MODE_SELECTED)
LARGE_WARN_MB = 8192  # 单个压缩包原始大小超过该值时日志提醒，不弹框打断


class BatchZipperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("批量打包压缩工具（支持暂停 & 断点续压）")
        self.root.geometry("980x800")
        self.root.minsize(880, 700)

        # 控制变量（名称与配置文件 key 一一对应）
        self.source_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.archive_format = tk.StringVar(value="zip")
        self.enable_password = tk.BooleanVar(value=True)
        self.password = tk.StringVar(value="123456")
        self.files_per_archive = tk.IntVar(value=1000)
        self.archive_prefix = tk.StringVar(value="HH_Collection")
        self.seven_zip_path = tk.StringVar(value="7z")
        self.pack_mode = tk.StringVar(value=MODE_BATCH_SIZE)
        self.max_archive_size_mb = tk.IntVar(value=3072)
        self.encrypt_header = tk.BooleanVar(value=False)
        self.new_dir_path = tk.StringVar()
        # “选中文件夹独立打包”模式的目录列表：路径字符串，界面与打包任务的唯一数据源
        self._selected_dirs = []

        # 运行控制：同一时刻只允许一个打包任务
        self.is_running = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # 初始为运行（未暂停）状态

        # 工作线程只写队列，所有控件操作都在主线程完成
        self._ui_queue = queue.Queue()

        self._cleanup_stale_tmp_files()
        self._create_widgets()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(UI_POLL_MS, self._poll_ui_queue)

    # ==================== 主线程 UI ====================

    def _poll_ui_queue(self):
        """主线程定时消费队列，保证控件操作只发生在主线程"""
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1])
                elif kind == "progress":
                    self.progress_label.config(text=msg[1])
                elif kind == "toast":
                    self._show_toast(*msg[1])
                elif kind == "ui_state":
                    self._update_ui_state()
        except queue.Empty:
            pass
        self.root.after(UI_POLL_MS, self._poll_ui_queue)

    def _append_log(self, line):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        last = int(self.log_text.index("end-1c").split(".")[0])
        if last > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{last - MAX_LOG_LINES}.0")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _log(self, msg, level=logging.INFO):
        """任意线程可调用的日志：落盘 + 投递到界面队列"""
        logging.log(level, msg)
        self._ui_queue.put(("log", f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}"))

    def _set_progress(self, text):
        self._ui_queue.put(("progress", text))

    def _toast(self, title, message, level="info"):
        self._ui_queue.put(("toast", (title, message, level)))

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
        toast.geometry(f"+{sx - w - 20}+{sy - h - 60}")
        toast.deiconify()

        toast.after(duration_ms, toast.destroy)

    def _update_ui_state(self):
        """任务运行中锁定全部参数，避免中途改参数造成歧义"""
        running_state = tk.DISABLED if self.is_running else tk.NORMAL
        for w in [self.source_btn, self.output_btn, self.browse_7z_btn, self.save_btn, self.start_btn]:
            w.config(state=running_state)
        for w in self._param_widgets:
            w.config(state=running_state)
        self.pause_btn.config(state=tk.NORMAL if self.is_running else tk.DISABLED)
        if not self.is_running:
            self.pause_btn.config(text="暂停")
            self._sync_widget_states()  # 再按当前模式恢复各控件可用性

    def _sync_widget_states(self):
        """按当前打包模式联动控件可用性与“选中文件夹”列表的显示"""
        if self.is_running:
            return
        mode = self.pack_mode.get()

        # 数量/大小限制只在对应的分批模式下可编辑，前缀只用于分批模式的包名
        self.files_spinbox.config(state=tk.NORMAL if mode == MODE_BATCH_FILES else tk.DISABLED)
        self.size_limit_spinbox.config(state=tk.NORMAL if mode == MODE_BATCH_SIZE else tk.DISABLED)
        self.prefix_entry.config(state=tk.NORMAL if mode in (MODE_BATCH_FILES, MODE_BATCH_SIZE) else tk.DISABLED)

        # 选中文件夹模式不依赖“源目录”，其他三种模式反之
        need_source = mode != MODE_SELECTED
        self.source_entry.config(state=tk.NORMAL if need_source else tk.DISABLED)
        self.source_btn.config(state=tk.NORMAL if need_source else tk.DISABLED)
        if mode == MODE_SELECTED:
            self._dirs_frame.pack(after=self._source_frame, fill=tk.X, pady=5)
        else:
            self._dirs_frame.pack_forget()

        # 文件名加密只有 7z 格式支持（zip 只能加密内容），且必须启用密码
        if self.archive_format.get() == "7z" and self.enable_password.get():
            self.header_check.config(state=tk.NORMAL)
        else:
            self.header_check.config(state=tk.DISABLED)

    def _toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.config(text="继续")
            self._log("⏸ 打包已暂停")
        else:
            self.pause_event.set()
            self.pause_btn.config(text="暂停")
            self._log("▶ 继续打包...")

    def _on_close(self):
        if self.is_running and not messagebox.askokcancel("退出", "打包任务正在进行，确定要退出吗？"):
            return
        self.is_running = False
        self.pause_event.set()  # 唤醒可能处于暂停等待中的工作线程
        self.root.destroy()

    # ==================== 目录选择 ====================

    def _select_source_dir(self):
        d = filedialog.askdirectory(title="选择源文件夹")
        if d: self.source_dir.set(d)

    def _select_output_dir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d: self.output_dir.set(d)

    def _select_7z_path(self):
        f = filedialog.askopenfilename(title="选择 7z.exe", filetypes=[("7z.exe", "7z.exe")])
        if f: self.seven_zip_path.set(f)

    # ==================== 选中文件夹列表维护 ====================

    def _add_selected_dir(self):
        """系统对话框每次只能选一个文件夹，因此采用“多次添加累加到列表”"""
        d = filedialog.askdirectory(title="选择一个要独立打包的文件夹")
        if d: self._append_selected_dir(d)

    def _add_selected_dir_by_path(self):
        raw = self.new_dir_path.get().strip().strip('"')
        if not raw:
            return
        if not Path(raw).is_dir():
            messagebox.showerror("错误", f"文件夹不存在：{raw}")
            return
        self._append_selected_dir(raw)
        self.new_dir_path.set("")

    def _append_selected_dir(self, path):
        resolved = self._norm_dir(path)
        if resolved in self._selected_dirs:
            self._log(f"ℹ️ 已在列表中，不重复添加: {resolved}")
            return
        self._selected_dirs.append(resolved)
        self._refresh_dir_listbox()

    def _remove_selected_dirs(self):
        for i in reversed(self.dir_listbox.curselection()):
            del self._selected_dirs[int(i)]
        self._refresh_dir_listbox()

    def _clear_selected_dirs(self):
        self._selected_dirs.clear()
        self._refresh_dir_listbox()

    def _refresh_dir_listbox(self):
        self.dir_listbox.delete(0, tk.END)
        for d in self._selected_dirs:
            self.dir_listbox.insert(tk.END, d)

    @staticmethod
    def _norm_dir(path):
        """统一路径写法，便于列表去重；解析失败时保留原样"""
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(path)

    # ==================== 任务启动校验 ====================

    def _resolve_7z(self):
        """返回可用的 7z 可执行文件路径，找不到返回 None"""
        configured = self.seven_zip_path.get().strip()
        if not configured:
            return None
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        return shutil.which(configured)

    def _get_positive_int(self, var, label):
        """读取 Spinbox 数值，非法输入返回 None"""
        try:
            value = var.get()
        except tk.TclError:
            messagebox.showerror("错误", f"“{label}”必须是数字")
            return None
        if value <= 0:
            messagebox.showerror("错误", f"“{label}”必须大于 0")
            return None
        return value

    def _validate_inputs(self):
        """主线程完成全部校验并快照配置，返回 (源目录, 输出目录, 配置快照)

        选中文件夹模式下 source 为 None，待打包目录列表放在 cfg.selected_dirs。
        """
        mode = self.pack_mode.get()
        selected_dirs = []
        source = None

        if mode == MODE_SELECTED:
            for raw in self._selected_dirs:
                if Path(raw).is_dir():
                    selected_dirs.append(Path(raw))
                else:
                    self._log(f"⚠️ 忽略已不存在的文件夹: {raw}", logging.WARNING)
            if not selected_dirs:
                messagebox.showerror("错误", "请先添加至少一个存在的文件夹")
                return None
        else:
            source = Path(self.source_dir.get())
            if not self.source_dir.get() or not source.is_dir():
                messagebox.showerror("错误", "源目录无效")
                return None

        if not self.output_dir.get():
            messagebox.showerror("错误", "请设置输出目录")
            return None
        output = Path(self.output_dir.get())
        try:
            out_res = output.resolve()
            src_res = source.resolve() if source is not None else None
            sel_res = [p.resolve() for p in selected_dirs]
        except OSError as e:
            messagebox.showerror("错误", f"路径解析失败: {e}")
            return None
        if src_res is not None and (out_res == src_res or src_res in out_res.parents):
            # 输出目录在源目录内部会把压缩包再次打包进去
            messagebox.showerror("错误", "输出目录不能是源目录本身或其子目录")
            return None
        for p in sel_res:
            # 同理：输出目录落在待打包文件夹内会无限套娃
            if out_res == p or p in out_res.parents:
                messagebox.showerror("错误", f"输出目录不能是被打包文件夹本身或其子目录：{p}")
                return None

        if self.enable_password.get() and not self.password.get():
            messagebox.showerror("错误", "密码不能为空")
            return None

        seven_zip = self._resolve_7z()
        if seven_zip is None:
            messagebox.showerror("错误", f"未找到 7-Zip：{self.seven_zip_path.get()}\n请检查“7z路径”设置")
            return None

        files_per_archive = max_mb = None
        if mode == MODE_BATCH_FILES:
            files_per_archive = self._get_positive_int(self.files_per_archive, "每包文件数")
            if files_per_archive is None:
                return None
        elif mode == MODE_BATCH_SIZE:
            max_mb = self._get_positive_int(self.max_archive_size_mb, "限制压缩包大小")
            if max_mb is None:
                return None

        cfg = SimpleNamespace(
            mode=mode,
            ext=self.archive_format.get(),
            size_limited=mode == MODE_BATCH_SIZE,
            files_per_archive=files_per_archive,
            max_archive_size_mb=max_mb,
            prefix=self.archive_prefix.get().strip() or "batch",
            seven_zip=seven_zip,
            enable_password=self.enable_password.get(),
            password=self.password.get(),
            encrypt_header=self.encrypt_header.get(),
            selected_dirs=selected_dirs
        )
        return source, output, cfg

    def _run_packaging(self):
        if self.is_running:
            messagebox.showinfo("提示", "已有打包任务在进行")
            return
        checked = self._validate_inputs()
        if not checked:
            return

        self.is_running = True
        self.pause_event.set()
        self._update_ui_state()
        threading.Thread(target=self._do_packaging, args=checked, daemon=True).start()

    # ==================== 打包主流程（工作线程，只读 cfg 快照，不触碰 tk 对象） ====================

    def _do_packaging(self, source, output, cfg):
        try:
            output.mkdir(parents=True, exist_ok=True)

            if cfg.enable_password and cfg.ext == "zip" and cfg.encrypt_header:
                self._log("ℹ️ zip 格式不支持加密文件名，仅加密文件内容（需加密文件名请选 7z）", logging.WARNING)

            if cfg.mode == MODE_SUBDIR:
                status, success, skipped, empty, failed = self._pack_by_subdir(source, output, cfg)
            elif cfg.mode == MODE_SELECTED:
                status, success, skipped, empty, failed = self._pack_by_selected(cfg.selected_dirs, output, cfg)
            else:
                all_files = self._scan_files(source)
                if all_files is None:
                    return
                if not all_files:
                    self._log("❌ 源目录无文件", logging.WARNING)
                    return
                status, success, skipped, empty, failed = self._pack_by_batches(source, output, all_files, cfg)

            detail = f"成功 {success}，跳过 {skipped}，空目录 {empty}，失败 {failed}"
            if status == RESULT_ABORTED:
                self._log("⏹ 任务已中止，已生成的压缩包保留，可再次“开始打包”续压", logging.WARNING)
                self._toast("任务已中止", detail, "info")
            else:
                self._log("🎉 打包全部完成！")
                self._toast("打包完成", detail, "error" if failed else "success")

        except Exception as e:
            self._log(f"💥 打包异常: {e}", logging.ERROR)
            self._toast("打包失败", str(e), "error")
        finally:
            self.is_running = False
            self._set_progress("")
            self._ui_queue.put(("ui_state",))

    def _scan_files(self, source):
        """递归收集源目录文件，返回 (绝对路径, 相对路径, 大小)；排序保证分批结果可复现"""
        all_files = []
        try:
            for fp in source.rglob("*"):
                try:
                    if fp.is_file():
                        all_files.append((fp, fp.relative_to(source), fp.stat().st_size))
                except OSError as e:
                    self._log(f"⚠️ 跳过无法读取的文件: {fp} - {e}", logging.WARNING)
        except OSError as e:
            self._log(f"❌ 扫描源目录失败: {e}", logging.ERROR)
            return None
        all_files.sort(key=lambda item: str(item[1]).casefold())
        return all_files

    def _make_batches(self, all_files, cfg):
        """按快照配置把文件切分为批次，返回 (批次数组, 规则说明)"""
        if cfg.size_limited:
            max_bytes = cfg.max_archive_size_mb * 1024 * 1024
            batches, current, current_size = [], [], 0
            for item in all_files:
                fsize = item[2]
                if current and current_size + fsize > max_bytes:
                    batches.append(current)
                    current, current_size = [], 0
                current.append(item)
                current_size += fsize
            if current:
                batches.append(current)
            return batches, f"按大小限制分为 {len(batches)} 批（每批上限 {cfg.max_archive_size_mb}MB）"

        batches = [all_files[i:i + cfg.files_per_archive] for i in range(0, len(all_files), cfg.files_per_archive)]
        return batches, f"按每包 {cfg.files_per_archive} 个文件分为 {len(batches)} 批"

    def _pack_by_batches(self, source, output, all_files, cfg):
        """按数量或大小分批打包；已存在的批次跳过（续压）"""
        batches, rule = self._make_batches(all_files, cfg)
        total = len(batches)
        self._log(f"📊 共 {len(all_files)} 个文件，{rule}")

        def items():
            for i, batch in enumerate(batches, 1):
                def prepare(batch=batch):
                    return source, [rel for _, rel, _ in batch], sum(f for _, _, f in batch)
                yield i, output / f"{cfg.prefix}_batch_{i:03d}.{cfg.ext}", f"第 {i}/{total} 批", prepare

        return self._pack_loop(output, cfg, total, items())

    def _plan_flat_archives(self, dirs, output, cfg):
        """平铺输出计划：文件夹名即包名，同名（来自不同位置）时追加序号避免互相覆盖"""
        used_names, plans = set(), []
        for sd in dirs:
            stem = self._safe_archive_stem(sd.name)
            archive_name = f"{stem}.{cfg.ext}"
            seq = 1
            while archive_name.casefold() in used_names:
                archive_name = f"{stem}_{seq}.{cfg.ext}"
                seq += 1
            used_names.add(archive_name.casefold())
            plans.append((sd, output / archive_name))
        return plans

    def _pack_by_subdir(self, source, output, cfg):
        """每个一级子目录打包为一个独立压缩包（忽略文件数量/压缩包大小限制）"""
        try:
            entries = list(source.iterdir())
        except OSError as e:
            self._log(f"❌ 读取源目录失败: {e}", logging.ERROR)
            return RESULT_DONE, 0, 0, 0, 0
        subdirs = sorted((p for p in entries if p.is_dir()), key=lambda p: p.name.casefold())
        if not subdirs:
            self._log("❌ 源目录下没有子目录（此模式仅处理一级子目录）", logging.WARNING)
            return RESULT_DONE, 0, 0, 0, 0

        loose = sum(1 for p in entries if p.is_file())
        if loose:
            self._log(f"⚠️ 源目录根下有 {loose} 个散文件不会被打包（此模式仅处理一级子目录）", logging.WARNING)

        plans = self._plan_flat_archives(subdirs, output, cfg)
        total = len(plans)
        self._log(f"📊 子目录独立打包模式：共 {total} 个一级子目录（已忽略数量/大小限制）")

        def items():
            # 只有确认需要打包时才扫描子目录，避免为已存在的压缩包白扫一遍
            for idx, (sd, archive_path) in enumerate(plans, 1):
                def prepare(sd=sd, idx=idx, total=total):
                    files, size_bytes = self._collect_subdir_files(sd, idx, total)
                    return source, [fp.relative_to(source) for fp in files], size_bytes
                yield idx, archive_path, f"第 {idx}/{total} 个子目录: {sd.name}", prepare

        return self._pack_loop(output, cfg, total, items())

    def _pack_by_selected(self, dirs, output, cfg):
        """手动选中的每个文件夹打包为一个独立压缩包（忽略数量/大小限制）

        各文件夹可以位于不同盘符，因此相对路径基准逐个取自己的父目录，
        包内保留顶层文件夹名，解压得到“文件夹名/...”。
        """
        plans = self._plan_flat_archives(dirs, output, cfg)
        total = len(plans)
        self._log(f"📊 选中文件夹独立打包模式：共 {total} 个文件夹（已忽略数量/大小限制，包内保留顶层文件夹名）")

        def items():
            for idx, (sd, archive_path) in enumerate(plans, 1):
                def prepare(sd=sd, idx=idx, total=total):
                    files, size_bytes = self._collect_subdir_files(sd, idx, total)
                    rel_paths = [Path(sd.name) / fp.relative_to(sd) for fp in files]
                    return sd.parent, rel_paths, size_bytes
                yield idx, archive_path, f"第 {idx}/{total} 个文件夹: {sd.name}", prepare

        return self._pack_loop(output, cfg, total, items())

    def _collect_subdir_files(self, sd, idx, total):
        files, size_bytes = [], 0
        try:
            for fp in sd.rglob("*"):
                try:
                    if fp.is_file():
                        files.append(fp)
                        size_bytes += fp.stat().st_size
                except OSError:
                    pass
        except OSError as e:
            self._log(f"⚠️ [{idx}/{total}] 扫描子目录异常（已扫描部分继续打包）: {sd.name} - {e}", logging.WARNING)
        if not files:
            self._log(f"🈳 [{idx}/{total}] 子目录内没有文件，不生成压缩包: {sd.name}", logging.WARNING)
        return files, size_bytes

    def _pack_loop(self, output, cfg, total, items):
        """四种模式共用的主循环：续压跳过 -> 暂停检查 -> 生成清单 -> 压缩 -> 计数汇总

        items 逐项产出 (序号, 压缩包路径, 进度描述, 文件清单生成函数)
        清单生成函数返回 (相对路径基准目录, 相对路径列表, 原始字节数)，
        基准目录逐包给定是为了支持不同盘符的文件夹共用一个输出目录。
        返回 (状态, 成功数, 已存在跳过数, 空目录数, 失败数)
        """
        success = skipped = empty = failed = 0
        for idx, archive_path, desc, prepare in items:
            archive_name = archive_path.name
            if archive_path.exists():
                skipped += 1
                self._log(f"⏭ [{idx}/{total}] 已存在，跳过: {archive_name}")
                continue

            if self._wait_if_paused():
                self._log_summary(success, skipped, empty, failed, total)
                return RESULT_ABORTED, success, skipped, empty, failed

            base_dir, rel_paths, size_bytes = prepare()
            if not rel_paths:
                empty += 1
                continue

            if size_bytes > LARGE_WARN_MB * 1024 * 1024:
                self._log(f"⚠️ [{idx}/{total}] 原始大小 {size_bytes / (1024 * 1024):.1f}MB 超过 "
                          f"{LARGE_WARN_MB}MB，单包较大（需要控制包体请改用分批模式）", logging.WARNING)

            self._set_progress(f"正在打包 {desc}")
            self._log(f"📦 [{idx}/{total}] 创建: {archive_name} "
                      f"({len(rel_paths)} 文件, 原始大小 {size_bytes / (1024 * 1024):.1f}MB)")
            ok, err = self._compress(base_dir, output, archive_path, rel_paths, cfg, idx)
            # 压缩过程中被中止：子进程已 kill、半成品已清理，不计入成功/失败批次
            if not self.is_running:
                self._log(f"⏹ [{idx}/{total}] 任务已中断，残包已清理: {archive_name}", logging.WARNING)
                self._log_summary(success, skipped, empty, failed, total)
                return RESULT_ABORTED, success, skipped, empty, failed
            if ok:
                success += 1
                self._log(f"✅ [{idx}/{total}] 成功: {archive_name}")
            else:
                failed += 1
                self._log(f"❌ [{idx}/{total}] 压缩失败: {archive_name} - {err}", logging.ERROR)

        self._log_summary(success, skipped, empty, failed, total)
        return RESULT_DONE, success, skipped, empty, failed

    def _log_summary(self, success, skipped, empty, failed, total):
        self._log(f"📋 汇总：成功 {success}，已存在跳过 {skipped}，空目录 {empty}，失败 {failed}（计划 {total}）")

    def _wait_if_paused(self):
        """暂停时阻塞等待；返回 True 表示任务需要中止"""
        while not self.pause_event.is_set():
            if not self.is_running:
                return True
            time.sleep(0.5)
        return not self.is_running

    def _compress(self, base_dir, output, archive_path, rel_paths, cfg, tag):
        """写文件清单并调用 7-Zip 生成一个压缩包，返回 (是否成功, 错误信息)

        base_dir 是 rel_paths 的相对路径基准，同时作为 7z 子进程的 cwd，
        清单里的路径决定压缩包内部结构。
        """
        if not rel_paths:
            return False, "没有待打包的文件"
        list_file = CONFIG_DIR / f"tmp_filelist_{os.getpid()}_{tag}.txt"
        try:
            with open(list_file, 'w', encoding='utf-8') as f:
                for rel in rel_paths:
                    f.write(str(rel).replace('/', '\\') + '\n')

            cmd = [
                cfg.seven_zip,
                "a", "-t" + cfg.ext, "-mx=1", "-mmt=on",
                f"-w{output}",
            ]
            if cfg.enable_password:
                cmd.append(f"-p{cfg.password}")
                if cfg.ext == "7z" and cfg.encrypt_header:
                    cmd.append("-mhe=on")
            cmd += [str(archive_path), f"@{list_file}"]

            # 输出直接丢弃：使用 PIPE 又不在主线程读取，缓冲区写满会让父子进程互相等待死锁
            # creationflags：不弹 7z 控制台黑窗
            proc = subprocess.Popen(
                cmd,
                cwd=str(base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW
            )
            while proc.poll() is None:
                if not self.is_running:
                    proc.kill()
                    self._discard_broken(archive_path)
                    return False, "任务被中止"
                time.sleep(0.1)
            if proc.returncode == 0:
                return True, ""
            # 半成品压缩包必须删除，否则下次续压会被误认为已完成
            self._discard_broken(archive_path)
            return False, f"7z 返回码 {proc.returncode}"

        except Exception as e:
            self._discard_broken(archive_path)
            return False, str(e)
        finally:
            list_file.unlink(missing_ok=True)

    @staticmethod
    def _discard_broken(archive_path):
        """7z 失败或被中断时可能残留不可用的压缩包，删除以便下次重新打包"""
        try:
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _safe_archive_stem(name):
        """将子目录名转为合法压缩包名主体（替换非法字符，去首尾空格/圆点）"""
        stem = re.sub(r'[\\/:*?"<>|]+', '_', name).strip(' .')
        return stem or "archive"

    def _cleanup_stale_tmp_files(self):
        """启动时清理上次异常退出残留的文件清单"""
        for p in CONFIG_DIR.glob(TMP_FILELIST_PATTERN):
            try:
                p.unlink()
            except OSError:
                pass

    # ==================== 配置读写 ====================

    def _save_config(self):
        mode = self.pack_mode.get()
        cfg = {
            "source_dir": self.source_dir.get(),
            "output_dir": self.output_dir.get(),
            "archive_format": self.archive_format.get(),
            "enable_password": self.enable_password.get(),
            "password": self.password.get(),
            "files_per_archive": self.files_per_archive.get(),
            "archive_prefix": self.archive_prefix.get(),
            "seven_zip_path": self.seven_zip_path.get(),
            "pack_mode": mode,
            "selected_dirs": list(self._selected_dirs),
            "max_archive_size_mb": self.max_archive_size_mb.get(),
            "encrypt_header": self.encrypt_header.get(),
            # 旧版本字段：由 pack_mode 推导写出，保证旧脚本读到同一份配置仍可用
            "enable_size_limit": mode == MODE_BATCH_SIZE,
            "one_archive_per_subdir": mode == MODE_SUBDIR
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
                attr = getattr(self, k, None)
                if attr is not None:
                    attr.set(v)

            if cfg.get("pack_mode") not in PACK_MODES:
                # 旧配置只有“限制大小 / 子目录独立”两个开关，按它们推导模式
                if cfg.get("one_archive_per_subdir"):
                    self.pack_mode.set(MODE_SUBDIR)
                elif cfg.get("enable_size_limit"):
                    self.pack_mode.set(MODE_BATCH_SIZE)
                else:
                    self.pack_mode.set(MODE_BATCH_FILES)
                self._log("ℹ️ 旧配置已映射为打包模式选择")

            # 选中文件夹列表不是 tk 变量，需单独回填（去重并保持添加顺序）
            seen, dirs = set(), []
            for raw in cfg.get("selected_dirs") or []:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                p = self._norm_dir(raw)
                if p not in seen:
                    seen.add(p)
                    dirs.append(p)
            self._selected_dirs = dirs
            self._refresh_dir_listbox()
            missing = [d for d in dirs if not Path(d).is_dir()]
            if missing:
                self._log(f"⚠️ 上次保存的 {len(missing)} 个文件夹当前不存在，开始打包时会被忽略", logging.WARNING)
            self._log("✅ 配置加载完成")
        except Exception as e:
            self._log(f"⚠️ 加载配置失败: {e}", logging.WARNING)
        self._sync_widget_states()

    # ==================== 界面构建 ====================

    def _create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 源目录
        f1 = ttk.LabelFrame(main, text="源文件夹", padding=5)
        f1.pack(fill=tk.X, pady=5)
        self._source_frame = f1
        self.source_entry = ttk.Entry(f1, textvariable=self.source_dir, width=80)
        self.source_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.source_btn = ttk.Button(f1, text="浏览...", command=self._select_source_dir)
        self.source_btn.pack(side=tk.RIGHT)

        # 选中文件夹列表：只在“选中文件夹独立打包”模式下显示（可见性由 _sync_widget_states 控制）
        self._dirs_frame = ttk.LabelFrame(
            main, text="选中的文件夹（每个文件夹单独成一个包，包名取文件夹名，同名自动加序号）", padding=5)
        dir_ops = ttk.Frame(self._dirs_frame)
        dir_ops.pack(fill=tk.X, pady=(0, 5))
        self.dir_add_btn = ttk.Button(dir_ops, text="添加文件夹...", command=self._add_selected_dir)
        self.dir_add_btn.pack(side=tk.LEFT)
        self.dir_remove_btn = ttk.Button(dir_ops, text="移除选中", command=self._remove_selected_dirs)
        self.dir_remove_btn.pack(side=tk.LEFT, padx=6)
        self.dir_clear_btn = ttk.Button(dir_ops, text="清空", command=self._clear_selected_dirs)
        self.dir_clear_btn.pack(side=tk.LEFT)
        self.dir_add_path_btn = ttk.Button(dir_ops, text="添加该路径", command=self._add_selected_dir_by_path)
        self.dir_add_path_btn.pack(side=tk.RIGHT)
        self.dir_path_entry = ttk.Entry(dir_ops, textvariable=self.new_dir_path)
        self.dir_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 5))
        self.dir_path_entry.bind("<Return>", lambda e: self._add_selected_dir_by_path())

        dir_list_row = ttk.Frame(self._dirs_frame)
        dir_list_row.pack(fill=tk.X)
        self.dir_listbox = tk.Listbox(dir_list_row, selectmode=tk.EXTENDED, height=6, exportselection=False)
        self.dir_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dir_scroll = ttk.Scrollbar(dir_list_row, command=self.dir_listbox.yview)
        dir_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.dir_listbox.config(yscrollcommand=dir_scroll.set)

        # 输出目录
        f2 = ttk.LabelFrame(main, text="输出目录", padding=5)
        f2.pack(fill=tk.X, pady=5)
        self.output_entry = ttk.Entry(f2, textvariable=self.output_dir, width=80)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.output_btn = ttk.Button(f2, text="浏览...", command=self._select_output_dir)
        self.output_btn.pack(side=tk.RIGHT)

        # 高级设置
        f3 = ttk.LabelFrame(main, text="高级设置", padding=10)
        f3.pack(fill=tk.X, pady=5)

        # 第一行：打包模式（四选一，取代旧版“限制大小 / 子目录独立”两个勾选框）
        mode_frame = ttk.Frame(f3)
        mode_frame.grid(row=0, column=0, columnspan=5, sticky=tk.W, padx=5, pady=(0, 8))
        ttk.Label(mode_frame, text="打包模式:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        mode_options = [
            (MODE_BATCH_FILES, "按每包文件数分批"),
            (MODE_BATCH_SIZE, "按压缩包大小分批"),
            (MODE_SUBDIR, "源目录每个一级子目录一包"),
            (MODE_SELECTED, "选中的每个文件夹一包"),
        ]
        for i, (value, text) in enumerate(mode_options):
            rb = ttk.Radiobutton(mode_frame, text=text, value=value, variable=self.pack_mode,
                                 command=self._sync_widget_states)
            rb.grid(row=i // 2, column=1 + (i % 2), sticky=tk.W, padx=(0, 16))

        # 第二行：格式与密码
        ttk.Label(f3, text="压缩格式:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.format_combo = ttk.Combobox(f3, textvariable=self.archive_format, values=["zip", "7z"],
                                         width=8, state="readonly")
        self.format_combo.grid(row=1, column=1, padx=5)
        self.format_combo.bind("<<ComboboxSelected>>", lambda e: self._sync_widget_states())
        self.password_check = ttk.Checkbutton(f3, text="启用密码", variable=self.enable_password,
                                              command=self._sync_widget_states)
        self.password_check.grid(row=1, column=2, padx=10)
        ttk.Label(f3, text="密码:").grid(row=1, column=3, padx=5)
        self.password_entry = ttk.Entry(f3, textvariable=self.password, width=12)
        self.password_entry.grid(row=1, column=4, padx=5)

        # 第三行：每包文件数与前缀
        ttk.Label(f3, text="每包文件数:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.files_spinbox = ttk.Spinbox(f3, from_=1, to=10000, textvariable=self.files_per_archive, width=10)
        self.files_spinbox.grid(row=2, column=1, padx=5)
        ttk.Label(f3, text="压缩包前缀:").grid(row=2, column=2, padx=10, pady=5)
        self.prefix_entry = ttk.Entry(f3, textvariable=self.archive_prefix, width=15)
        self.prefix_entry.grid(row=2, column=3, columnspan=2, padx=5, sticky=tk.EW)

        # 第四行：大小限制
        ttk.Label(f3, text="每包上限(MB):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.size_limit_spinbox = ttk.Spinbox(f3, from_=100, to=102400, increment=512,
                                              textvariable=self.max_archive_size_mb, width=10)
        self.size_limit_spinbox.grid(row=3, column=1, padx=5)

        # 第五行：文件名加密
        self.header_check = ttk.Checkbutton(f3, text="加密文件名（仅 .7z 格式支持）",
                                            variable=self.encrypt_header, command=self._sync_widget_states)
        self.header_check.grid(row=4, column=0, columnspan=4, sticky=tk.W, padx=5, pady=5)

        # 第六行：7z路径
        ttk.Label(f3, text="7z路径:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        self.seven_zip_entry = ttk.Entry(f3, textvariable=self.seven_zip_path, width=40)
        self.seven_zip_entry.grid(row=5, column=1, columnspan=3, padx=5, sticky=tk.EW)
        self.browse_7z_btn = ttk.Button(f3, text="浏览", command=self._select_7z_path, width=6)
        self.browse_7z_btn.grid(row=5, column=4, padx=(5, 0))

        f3.columnconfigure(4, weight=1)

        # 运行期间需要统一锁定的参数控件
        self._param_widgets = [
            self.source_entry, self.output_entry, self.format_combo,
            self.password_check, self.password_entry, self.prefix_entry,
            self.files_spinbox, self.size_limit_spinbox,
            self.header_check, self.seven_zip_entry,
            self.dir_add_btn, self.dir_remove_btn, self.dir_clear_btn,
            self.dir_path_entry, self.dir_add_path_btn, self.dir_listbox,
        ]

        # 操作区
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=10)

        self.start_btn = ttk.Button(btn_frame, text="开始打包", command=self._run_packaging)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.pause_btn = ttk.Button(btn_frame, text="暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.save_btn = ttk.Button(btn_frame, text="保存配置", command=self._save_config)
        self.save_btn.pack(side=tk.LEFT)

        self.progress_label = ttk.Label(btn_frame, text="", foreground="blue")
        self.progress_label.pack(side=tk.RIGHT)

        # 日志
        log_frame = ttk.LabelFrame(main, text="日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self._sync_widget_states()


if __name__ == "__main__":
    if platform.system() != "Windows":
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("错误", "仅支持 Windows（依赖 7-Zip）")
        root.destroy()
    else:
        root = tk.Tk()
        app = BatchZipperApp(root)
        root.mainloop()
