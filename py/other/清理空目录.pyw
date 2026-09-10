# clean_empty_dirs.pyw

import os
import json
import logging
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import threading

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "clean_empty_dirs"  # 脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# DB_CONFIG_PATH 按规范定义（即使未使用）
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 日志路径
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# ================== 主应用类 ==================
class CleanEmptyDirsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("清理空文件夹工具")
        self.root.geometry("700x500")
        self.root.minsize(600, 400)

        # 变量
        self.target_dir = tk.StringVar()

        # 创建UI
        self._create_widgets()

        # 加载配置
        self._load_config()

    def _create_widgets(self):
        """创建图形界面"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 目录选择区
        dir_frame = ttk.LabelFrame(main_frame, text="目标目录", padding="10")
        dir_frame.pack(fill=tk.X, pady=5)

        ttk.Label(dir_frame, text="路径:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        ttk.Entry(dir_frame, textvariable=self.target_dir, width=50).grid(row=0, column=1, sticky=tk.EW, padx=(0, 10))
        ttk.Button(dir_frame, text="浏览...", command=self._browse_dir).grid(row=0, column=2)

        dir_frame.columnconfigure(1, weight=1)

        # 操作按钮区
        btn_frame = ttk.Frame(main_frame, padding="10")
        btn_frame.pack(fill=tk.X, pady=10)

        self.clean_btn = ttk.Button(btn_frame, text="开始清理空文件夹", command=self._start_cleaning, state=tk.NORMAL)
        self.clean_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side=tk.RIGHT, padx=5)

        # 日志显示区
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _browse_dir(self):
        """选择目标目录"""
        path = filedialog.askdirectory(title="请选择要清理的根目录")
        if path:
            self.target_dir.set(path)
            self._log(f"已选择目标目录: {path}")

    def _log(self, message, level=logging.INFO):
        """统一日志输出（写入文件 + UI）"""
        logging.log(level, message)

        # 安全地更新UI（在主线程中）
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, update)

    def _clear_log(self):
        """清空日志显示区域"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._log("日志显示已清空（日志文件仍保留）")

    def _save_config(self):
        """保存当前配置到 JSON"""
        config = {
            "target_dir": self.target_dir.get().strip()
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存至: {CONFIG_PATH}")
            messagebox.showinfo("成功", "配置保存成功！")
        except Exception as e:
            self._log(f"保存配置失败: {e}", logging.ERROR)
            messagebox.showerror("错误", f"无法保存配置:\n{e}")

    def _load_config(self):
        """从 JSON 加载配置"""
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if "target_dir" in config:
                    self.target_dir.set(config["target_dir"])
                self._log(f"配置已从 {CONFIG_PATH} 加载")
            except Exception as e:
                self._log(f"加载配置失败: {e}", logging.WARNING)

    def _start_cleaning(self):
        """启动清理任务（在子线程中执行）"""
        target = self.target_dir.get().strip()
        if not target:
            messagebox.showwarning("警告", "请先选择目标目录！")
            return
        if not os.path.isdir(target):
            messagebox.showerror("错误", "所选路径不是有效目录！")
            return

        confirm = messagebox.askyesno(
            "确认操作",
            f"确定要清理以下目录及其所有子目录中的空文件夹吗？\n\n{target}\n\n此操作不可逆！"
        )
        if not confirm:
            return

        self.clean_btn.config(state=tk.DISABLED)
        self._log(f"开始清理空文件夹: {target}")
        threading.Thread(target=self._clean_empty_dirs, args=(target,), daemon=True).start()

    def _clean_empty_dirs(self, root_path):
        """递归清理空文件夹（自底向上）"""
        deleted_count = 0
        error_count = 0

        try:
            # 自底向上遍历（确保先删子目录）
            for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
                # 跳过非空目录
                if dirnames or filenames:
                    continue

                # 尝试删除空目录
                try:
                    os.rmdir(dirpath)
                    self._log(f"已删除空文件夹: {dirpath}")
                    deleted_count += 1
                except OSError as e:
                    self._log(f"无法删除 {dirpath}: {e}", logging.WARNING)
                    error_count += 1

            msg = f"清理完成！共删除 {deleted_count} 个空文件夹"
            if error_count > 0:
                msg += f"，{error_count} 个失败（可能被占用或权限不足）"
            self._log(msg)
            messagebox.showinfo("完成", msg)

        except Exception as e:
            self._log(f"清理过程中发生异常: {e}", logging.ERROR)
            messagebox.showerror("错误", f"清理失败:\n{e}")

        finally:
            # 恢复按钮状态
            self.root.after(0, lambda: self.clean_btn.config(state=tk.NORMAL))

# ================== 启动程序 ==================
if __name__ == "__main__":
    root = tk.Tk()
    app = CleanEmptyDirsApp(root)
    root.mainloop()
