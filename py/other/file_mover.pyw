import os
import shutil
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime
from pathlib import Path
import threading

# 配置与常量
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "file_mover"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
LOG_DIR = SCRIPT_DIR / "json" / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

class FileMoverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文件快速移动工具")
        self.root.geometry("800x600")
        self.root.minsize(700, 500)

        # 初始化变量
        self.source_dir = tk.StringVar()
        self.target_dir = tk.StringVar()
        self.project_dir = tk.StringVar()  # 项目目录变量
        self.is_moving = False

        # 创建UI
        self._create_widgets()

        # 加载配置
        self._load_config()

    def _create_widgets(self):
        """创建UI组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 目录选择区域
        dir_frame = ttk.LabelFrame(main_frame, text="目录配置", padding="10")
        dir_frame.pack(fill=tk.X, pady=5)

        # 源目录选择
        ttk.Label(dir_frame, text="源目录:").grid(row=0, column=0, padx=5, pady=10, sticky=tk.W)
        ttk.Entry(dir_frame, textvariable=self.source_dir, width=50).grid(row=0, column=1, padx=5, pady=10, sticky=tk.EW)
        ttk.Button(dir_frame, text="浏览...", command=self._select_source_dir).grid(row=0, column=2, padx=5, pady=10)

        # 目标目录选择
        ttk.Label(dir_frame, text="目标目录:").grid(row=1, column=0, padx=5, pady=10, sticky=tk.W)
        ttk.Entry(dir_frame, textvariable=self.target_dir, width=50).grid(row=1, column=1, padx=5, pady=10, sticky=tk.EW)
        ttk.Button(dir_frame, text="浏览...", command=self._select_target_dir).grid(row=1, column=2, padx=5, pady=10)


        dir_frame.columnconfigure(1, weight=1)

        # 操作按钮区域
        btn_frame = ttk.Frame(main_frame, padding="10")
        btn_frame.pack(fill=tk.X, pady=5)

        self.move_btn = ttk.Button(btn_frame, text="开始移动文件", command=self._start_move, width=20)
        self.move_btn.pack(side=tk.LEFT, padx=10)

        ttk.Button(btn_frame, text="保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=10)
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side=tk.RIGHT, padx=10)

        # 日志显示区域
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _select_source_dir(self):
        """选择源目录"""
        dir_path = filedialog.askdirectory(title="选择需要移动的文件源目录")
        if dir_path:
            self.source_dir.set(dir_path)
            self._log(f"已选择源目录: {dir_path}")

    def _select_target_dir(self):
        """选择目标目录"""
        dir_path = filedialog.askdirectory(title="选择文件目标目录")
        if dir_path:
            self.target_dir.set(dir_path)
            self._log(f"已选择目标目录: {dir_path}")

    def _select_project_dir(self):
        """选择项目目录"""
        dir_path = filedialog.askdirectory(title="选择需要打包的项目目录")
        if dir_path:
            self.project_dir.set(dir_path)
            self._log(f"已选择项目目录: {dir_path}")

    def _start_move(self):
        """开始移动文件（在新线程中执行，避免UI卡顿）"""
        source = self.source_dir.get().strip()
        target = self.target_dir.get().strip()

        # 验证目录
        if not source:
            messagebox.showerror("错误", "请选择源目录")
            return
        if not target:
            messagebox.showerror("错误", "请选择目标目录")
            return
        if not os.path.exists(source):
            messagebox.showerror("错误", f"源目录不存在: {source}")
            return

        # 确认移动
        if not messagebox.askyesno("确认", f"确定要将\n{source}\n中的所有内容移动到\n{target}\n吗？"):
            return

        # 开始移动
        self.is_moving = True
        self.move_btn.config(state=tk.DISABLED)
        self._log("开始移动文件...")

        # 在新线程中执行移动操作
        threading.Thread(target=self._move_files, args=(source, target), daemon=True).start()

    def _move_files(self, source, target):
        """执行文件移动（保留目录结构）"""
        try:
            # 确保目标目录存在
            os.makedirs(target, exist_ok=True)

            # 统计文件总数
            total_files = 0
            for root, _, files in os.walk(source):
                total_files += len(files)

            moved_files = 0
            error_files = 0

            # 遍历源目录
            for root, dirs, files in os.walk(source):
                # 创建对应的目标子目录
                relative_path = os.path.relpath(root, source)
                target_subdir = os.path.join(target, relative_path)
                os.makedirs(target_subdir, exist_ok=True)

                # 移动文件
                for file in files:
                    source_file = os.path.join(root, file)
                    target_file = os.path.join(target_subdir, file)

                    # 处理文件已存在的情况
                    if os.path.exists(target_file):
                        self._log(f"文件已存在，跳过: {target_file}", logging.WARNING)
                        error_files += 1
                        continue

                    try:
                        shutil.move(source_file, target_file)
                        moved_files += 1
                        self._log(f"已移动: {source_file} → {target_file}")
                    except Exception as e:
                        self._log(f"移动失败: {source_file} - {str(e)}", logging.ERROR)
                        error_files += 1

            # 移动完成后清理空目录
            self._clean_empty_dirs(source)

            self._log(f"移动完成 - 成功: {moved_files} 个, 失败: {error_files} 个, 总计: {total_files} 个")
            messagebox.showinfo("完成", f"文件移动完成\n成功: {moved_files} 个\n失败: {error_files} 个")

        except Exception as e:
            self._log(f"移动过程出错: {str(e)}", logging.ERROR)
            messagebox.showerror("错误", f"移动文件失败: {str(e)}")

        finally:
            self.is_moving = False
            self.root.after(0, lambda: self.move_btn.config(state=tk.NORMAL))

    def _clean_empty_dirs(self, root_dir):
        """清理源目录中的空目录"""
        try:
            for dirpath, _, _ in os.walk(root_dir, topdown=False):
                if os.path.isdir(dirpath) and not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    self._log(f"删除空目录: {dirpath}")
        except Exception as e:
            self._log(f"清理空目录出错: {str(e)}", logging.WARNING)

    def _log(self, message, level=logging.INFO):
        """记录日志并更新UI"""
        logging.log(level, message)

        # 在主线程中更新UI
        def update_log():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        self.root.after(0, update_log)

    def _clear_log(self):
        """清空日志显示"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._log("日志已清空")

    def _save_config(self):
        """保存配置到文件"""
        config = {
            "source_dir": self.source_dir.get(),
            "target_dir": self.target_dir.get(),
            "project_dir": self.project_dir.get()
        }

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存到: {CONFIG_PATH}")
            messagebox.showinfo("成功", "配置保存成功")
        except Exception as e:
            self._log(f"保存配置失败: {str(e)}", logging.ERROR)
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def _load_config(self):
        """从文件加载配置"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if "source_dir" in config:
                    self.source_dir.set(config["source_dir"])
                if "target_dir" in config:
                    self.target_dir.set(config["target_dir"])
                if "project_dir" in config:
                    self.project_dir.set(config["project_dir"])

                self._log(f"已加载配置: {CONFIG_PATH}")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

if __name__ == "__main__":
    root = tk.Tk()
    app = FileMoverApp(root)
    root.mainloop()
