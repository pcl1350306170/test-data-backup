# junction_creator.pyw

import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import threading

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "junction_creator"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()


class JunctionCreatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("目录联接（Junction）创建工具")
        self.root.geometry("850x620")
        self.root.minsize(750, 550)

        self.source_dir = tk.StringVar()
        self.target_dir = tk.StringVar()
        self.check_vars = []   # [(dir_name, BooleanVar), ...]
        self.is_running = False

        self._create_widgets()
        self._load_config()

    # ── UI ────────────────────────────────────────────────

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── 目录配置 ──
        dir_frame = ttk.LabelFrame(main_frame, text="目录配置", padding="10")
        dir_frame.pack(fill=tk.X, pady=5)

        ttk.Label(dir_frame, text="开发目录:").grid(
            row=0, column=0, padx=5, pady=8, sticky=tk.W)
        ttk.Entry(dir_frame, textvariable=self.source_dir, width=55).grid(
            row=0, column=1, padx=5, pady=8, sticky=tk.EW)
        ttk.Button(dir_frame, text="浏览...", command=self._select_source_dir).grid(
            row=0, column=2, padx=5, pady=8)

        ttk.Label(dir_frame, text="目标目录:").grid(
            row=1, column=0, padx=5, pady=8, sticky=tk.W)
        ttk.Entry(dir_frame, textvariable=self.target_dir, width=55).grid(
            row=1, column=1, padx=5, pady=8, sticky=tk.EW)
        ttk.Button(dir_frame, text="浏览...", command=self._select_target_dir).grid(
            row=1, column=2, padx=5, pady=8)

        dir_frame.columnconfigure(1, weight=1)

        # ── 子目录列表 ──
        list_frame = ttk.LabelFrame(main_frame, text="子目录列表（勾选要创建联接的目录）", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 全选/取消全选
        select_bar = ttk.Frame(list_frame)
        select_bar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(select_bar, text="全选", command=self._select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(select_bar, text="取消全选", command=self._deselect_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(select_bar, text="刷新列表", command=self._scan_source_dirs).pack(side=tk.LEFT, padx=5)

        # 可滚动的复选框列表
        canvas_frame = ttk.Frame(list_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.check_frame = ttk.Frame(self.canvas)

        self.check_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.check_frame, anchor=tk.NW)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮支持
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))

        # ── 按钮 ──
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X, pady=5)

        self.run_btn = ttk.Button(btn_frame, text="创建联接", command=self._start_create, width=15)
        self.run_btn.pack(side=tk.LEFT, padx=10)

        ttk.Button(btn_frame, text="保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=10)
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side=tk.RIGHT, padx=10)

        # ── 日志 ──
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ── 目录选择 ──────────────────────────────────────────

    def _select_source_dir(self):
        path = filedialog.askdirectory(title="选择开发插件目录")
        if path:
            self.source_dir.set(path)
            self._log(f"已选择开发目录: {path}")
            self._scan_source_dirs()

    def _select_target_dir(self):
        path = filedialog.askdirectory(title="选择 Flow Launcher Plugins 目录")
        if path:
            self.target_dir.set(path)
            self._log(f"已选择目标目录: {path}")

    # ── 扫描子目录 ────────────────────────────────────────

    def _scan_source_dirs(self):
        """扫描开发目录下的子目录，填充复选框列表"""
        source = self.source_dir.get().strip()
        if not source or not os.path.isdir(source):
            self._log("开发目录无效或不存在，无法扫描", tk.WORD)
            return

        # 清空现有复选框
        for widget in self.check_frame.winfo_children():
            widget.destroy()
        self.check_vars.clear()

        # 扫描子目录
        subdirs = sorted([
            d for d in os.listdir(source)
            if os.path.isdir(os.path.join(source, d)) and not d.startswith(".")
        ])

        target = self.target_dir.get().strip()

        for name in subdirs:
            src_path = os.path.join(source, name)
            is_junction = False
            status = ""

            # 检查目标目录中是否已存在同名联接
            if target:
                tgt_path = os.path.join(target, name)
                if os.path.exists(tgt_path):
                    try:
                        item = Path(tgt_path)
                        if item.is_dir() and not item.is_symlink():
                            # 普通目录
                            status = "  ⚠ 已有普通目录"
                        elif item.is_dir():
                            link_target = str(item.resolve())
                            if link_target == os.path.abspath(src_path):
                                is_junction = True
                                status = "  ✓ 已是联接"
                            else:
                                status = f"  ⚠ 已联接至其他位置"
                    except Exception:
                        pass

            var = tk.BooleanVar(value=not is_junction)  # 已有联接的默认不勾选
            cb = ttk.Checkbutton(
                self.check_frame,
                text=f"{name}{status}",
                variable=var,
            )
            cb.pack(anchor=tk.W, pady=1)
            self.check_vars.append((name, var))

        self._log(f"扫描完成，发现 {len(subdirs)} 个子目录")

    def _select_all(self):
        for _, var in self.check_vars:
            var.set(True)

    def _deselect_all(self):
        for _, var in self.check_vars:
            var.set(False)

    # ── 创建联接 ──────────────────────────────────────────

    def _start_create(self):
        source = self.source_dir.get().strip()
        target = self.target_dir.get().strip()

        if not source or not os.path.isdir(source):
            messagebox.showerror("错误", "请选择有效的开发目录")
            return
        if not target:
            messagebox.showerror("错误", "请选择目标目录")
            return
        if not os.path.isdir(target):
            messagebox.showerror("错误", f"目标目录不存在: {target}")
            return

        # 收集勾选的目录
        selected = [name for name, var in self.check_vars if var.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个子目录")
            return

        msg = f"将在目标目录中为以下 {len(selected)} 个目录创建联接:\n\n"
        msg += "\n".join(f"  • {name}" for name in selected)
        msg += f"\n\n目标目录: {target}\n\n继续？"

        if not messagebox.askyesno("确认", msg):
            return

        self.is_running = True
        self.run_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._create_junctions, args=(source, target, selected), daemon=True).start()

    def _create_junctions(self, source, target, selected):
        """在目标目录中为选中的子目录创建联接"""
        success_count = 0
        skip_count = 0
        fail_count = 0

        for name in selected:
            src_path = os.path.join(source, name)
            tgt_path = os.path.join(target, name)

            try:
                # 检查目标是否已存在
                if os.path.exists(tgt_path) or os.path.islink(tgt_path):
                    tgt_item = Path(tgt_path)
                    # 如果已经是指向正确位置的联接，跳过
                    try:
                        if tgt_item.is_dir() and str(tgt_item.resolve()) == os.path.abspath(src_path):
                            self._log(f"跳过 {name}（已是正确的联接）")
                            skip_count += 1
                            continue
                    except Exception:
                        pass

                    # 已存在普通目录 → 重命名为 _bak
                    bak_path = tgt_path + "_bak"
                    if os.path.exists(bak_path):
                        self._log(f"备份目录已存在: {bak_path}，无法备份 {name}", "error")
                        fail_count += 1
                        continue
                    os.rename(tgt_path, bak_path)
                    self._log(f"已备份: {name} → {name}_bak")

                # 使用 mklink /J 创建联接（无需管理员权限）
                ret = os.system(f'mklink /J "{tgt_path}" "{src_path}" >nul 2>&1')
                if ret == 0:
                    self._log(f"✓ 已创建联接: {name}")
                    success_count += 1
                else:
                    self._log(f"✗ 创建失败: {name}", "error")
                    fail_count += 1

            except Exception as e:
                self._log(f"✗ 创建失败: {name} - {e}", "error")
                fail_count += 1

        summary = f"完成 — 成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}"
        self._log(summary)
        logger.info(summary)

        self.is_running = False
        self.root.after(0, lambda: self.run_btn.config(state=tk.NORMAL))
        self.root.after(0, lambda: messagebox.showinfo("完成", summary))

    # ── 日志 ──────────────────────────────────────────────

    def _log(self, message, level=None):
        """记录日志并更新 UI"""
        if level == "error":
            logger.error(message)
        else:
            logger.info(message)

        def update():
            self.log_text.config(state=tk.NORMAL)
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{ts}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        self.root.after(0, update)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ── 配置 ──────────────────────────────────────────────

    def _save_config(self):
        config = {
            "source_dir": self.source_dir.get(),
            "target_dir": self.target_dir.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            self._log(f"保存配置失败: {e}", "error")

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if "source_dir" in cfg:
                    self.source_dir.set(cfg["source_dir"])
                if "target_dir" in cfg:
                    self.target_dir.set(cfg["target_dir"])
                self._log(f"已加载配置: {CONFIG_PATH}")
                # 自动扫描子目录
                if self.source_dir.get() and os.path.isdir(self.source_dir.get()):
                    self._scan_source_dirs()
        except Exception as e:
            self._log(f"加载配置失败: {e}", "error")


if __name__ == "__main__":
    root = tk.Tk()
    app = JunctionCreatorApp(root)
    root.mainloop()
