import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import chardet
from datetime import datetime
import threading

# 配置路径设置
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "txt_merge"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"

# 确保配置目录存在
CONFIG_DIR.mkdir(exist_ok=True)

# ──────────── 公共日志模块（可选依赖）────────────
import sys
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

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
# ────────────────────────────────────────────────


class TxtMergerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TXT文件合并工具")
        self.root.geometry("900x750")

        # 初始化配置
        self.config = {
            "last_input_dir": "",
            "last_output_dir": "",
            "last_output_filename": "",
        }

        # 数据存储
        self.selected_files = []
        self.is_running = False

        # 创建界面
        self.create_widgets()

        # 加载配置
        self.load_config()

    def create_widgets(self):
        # 主布局
        main_notebook = ttk.Notebook(self.root)
        main_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ===== 1. 文件选择标签页 =====
        file_frame = ttk.Frame(main_notebook)
        main_notebook.add(file_frame, text="文件选择与排序")

        # 说明
        ttk.Label(file_frame, text="选择TXT文件（按列表顺序合并，可拖拽调整顺序）:",
                  font=("Microsoft YaHei", 9)).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)

        # 文件列表区域
        list_frame = ttk.Frame(file_frame)
        list_frame.grid(row=1, column=0, columnspan=4, sticky=tk.NSEW, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_listbox = tk.Listbox(list_frame, width=80, height=15,
                                       yscrollcommand=scrollbar.set, selectmode=tk.EXTENDED)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_listbox.yview)

        # 按钮区域
        btn_frame = ttk.Frame(file_frame)
        btn_frame.grid(row=2, column=0, columnspan=4, pady=5)

        ttk.Button(btn_frame, text="添加文件...", command=self.add_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="添加目录...", command=self.add_directory).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="移除选中", command=self.remove_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="上移", command=self.move_up).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="下移", command=self.move_down).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空列表", command=self.clear_file_list).pack(side=tk.LEFT, padx=5)

        # 文件统计
        self.file_stats_label = ttk.Label(file_frame, text="已选择 0 个文件")
        self.file_stats_label.grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)

        # 章节目录预览
        ttk.Label(file_frame, text="章节目录预览（合并后自动生成）:",
                  font=("Microsoft YaHei", 9)).grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)

        preview_frame = ttk.Frame(file_frame)
        preview_frame.grid(row=5, column=0, columnspan=4, sticky=tk.NSEW, padx=5, pady=5)

        preview_scrollbar = ttk.Scrollbar(preview_frame, orient="vertical")
        preview_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.chapter_preview = tk.Text(preview_frame, height=8, width=80,
                                       yscrollcommand=preview_scrollbar.set, state=tk.DISABLED)
        self.chapter_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        preview_scrollbar.config(command=self.chapter_preview.yview)

        # 配置权重
        file_frame.grid_rowconfigure(1, weight=2)
        file_frame.grid_rowconfigure(5, weight=1)
        file_frame.grid_columnconfigure(0, weight=1)

        # ===== 2. 输出设置标签页 =====
        settings_frame = ttk.Frame(main_notebook)
        main_notebook.add(settings_frame, text="输出设置")

        # 输出目录
        ttk.Label(settings_frame, text="输出目录:", font=("Microsoft YaHei", 9)).grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=15)
        self.output_dir_var = tk.StringVar(value=self.config["last_output_dir"])
        ttk.Entry(settings_frame, textvariable=self.output_dir_var, width=60).grid(
            row=0, column=1, padx=5, pady=15)
        ttk.Button(settings_frame, text="浏览...", command=self.select_output_dir).grid(
            row=0, column=2, padx=5, pady=15)

        # 输出文件名
        ttk.Label(settings_frame, text="输出文件名:", font=("Microsoft YaHei", 9)).grid(
            row=1, column=0, sticky=tk.W, padx=5, pady=15)
        self.output_filename_var = tk.StringVar(value=self.config["last_output_filename"])
        ttk.Entry(settings_frame, textvariable=self.output_filename_var, width=40).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=15)
        ttk.Label(settings_frame, text="（留空则使用日期时间作为文件名）", foreground="gray").grid(
            row=1, column=2, sticky=tk.W, padx=5, pady=15)

        # 文件名预览
        ttk.Label(settings_frame, text="最终文件名预览:", font=("Microsoft YaHei", 9)).grid(
            row=2, column=0, sticky=tk.W, padx=5, pady=15)
        self.filename_preview_label = ttk.Label(settings_frame, text="", foreground="blue",
                                                 font=("Microsoft YaHei", 10, "bold"))
        self.filename_preview_label.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=5, pady=15)

        # 绑定文件名变化事件
        self.output_filename_var.trace_add("write", self.update_filename_preview)
        self.output_dir_var.trace_add("write", self.update_filename_preview)

        # 章节格式说明
        info_frame = ttk.LabelFrame(settings_frame, text="说明")
        info_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=15)

        ttk.Label(info_frame, text=(
            "• 每个TXT文件的文件名将作为合并后的章节目录\n"
            "• 目录格式：第0001章 文件名（不含.txt后缀）\n"
            "• 文件按列表中的顺序进行合并\n"
            "• 输出文件编码为 UTF-8"
        ), justify=tk.LEFT, foreground="gray").pack(padx=10, pady=10)

        # ===== 3. 日志标签页 =====
        log_frame = ttk.Frame(main_notebook)
        main_notebook.add(log_frame, text="操作日志")

        ttk.Label(log_frame, text="执行日志:").pack(anchor=tk.W, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, height=20, width=80)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)

        # ===== 底部操作区域 =====
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        # 进度条
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(bottom_frame, variable=self.progress_var,
                                            maximum=100, length=400)
        self.progress_bar.pack(fill=tk.X, padx=5, pady=5)

        # 进度文字
        self.progress_label = ttk.Label(bottom_frame, text="就绪")
        self.progress_label.pack(anchor=tk.W, padx=5)

        # 按钮
        btn_bottom_frame = ttk.Frame(self.root)
        btn_bottom_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(btn_bottom_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_bottom_frame, text="开始合并", command=self.start_merge).pack(side=tk.RIGHT, padx=10)

    def log(self, message):
        """添加日志信息"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, "[" + timestamp + "] " + message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def update_progress(self, value, text=""):
        """更新进度"""
        self.progress_var.set(value)
        if text:
            self.progress_label.config(text=text)
        self.root.update_idletasks()

    def update_file_stats(self):
        """更新文件统计和章节预览"""
        count = len(self.selected_files)
        total_size = 0
        for f in self.selected_files:
            try:
                total_size += os.path.getsize(f)
            except OSError:
                pass

        size_str = self.format_size(total_size)
        self.file_stats_label.config(text=f"已选择 {count} 个文件，总大小: {size_str}")

        # 更新章节预览
        self.chapter_preview.config(state=tk.NORMAL)
        self.chapter_preview.delete(1.0, tk.END)
        for i, file_path in enumerate(self.selected_files, 1):
            name = os.path.splitext(os.path.basename(file_path))[0]
            chapter_title = f"第{i:04d}章 {name}"
            self.chapter_preview.insert(tk.END, f"{chapter_title}\n")
        self.chapter_preview.config(state=tk.DISABLED)

        self.update_filename_preview()

    def format_size(self, size_bytes):
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def update_filename_preview(self, *args):
        """更新文件名预览"""
        filename = self.output_filename_var.get().strip()
        if not filename:
            filename = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not filename.endswith(".txt"):
            filename += ".txt"

        output_dir = self.output_dir_var.get().strip()
        if output_dir:
            full_path = os.path.join(output_dir, filename)
            self.filename_preview_label.config(text=full_path)
        else:
            self.filename_preview_label.config(text=f"（请先选择输出目录）{filename}")

    def add_files(self):
        """添加TXT文件"""
        initial_dir = self.config["last_input_dir"] if self.config["last_input_dir"] else str(SCRIPT_DIR)

        files = filedialog.askopenfilenames(
            title="选择TXT文件",
            filetypes=[("TXT文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=initial_dir
        )

        if files:
            self.config["last_input_dir"] = os.path.dirname(files[0])
            added = 0
            for file in files:
                if file not in self.selected_files:
                    self.selected_files.append(file)
                    self.file_listbox.insert(tk.END, os.path.basename(file))
                    added += 1

            self.log(f"已添加 {added} 个文件")
            self.update_file_stats()

    def add_directory(self):
        """添加目录下所有TXT文件"""
        initial_dir = self.config["last_input_dir"] if self.config["last_input_dir"] else str(SCRIPT_DIR)

        dir_path = filedialog.askdirectory(title="选择包含TXT文件的目录", initialdir=initial_dir)

        if dir_path:
            self.config["last_input_dir"] = dir_path
            added = 0
            txt_files = sorted([
                os.path.join(dir_path, f)
                for f in os.listdir(dir_path)
                if f.lower().endswith(".txt")
            ])

            for file in txt_files:
                if file not in self.selected_files:
                    self.selected_files.append(file)
                    self.file_listbox.insert(tk.END, os.path.basename(file))
                    added += 1

            self.log(f"从目录添加 {added} 个TXT文件: {os.path.basename(dir_path)}")
            self.update_file_stats()

    def remove_selected(self):
        """移除选中的文件"""
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            return

        for i in sorted(selected_indices, reverse=True):
            del self.selected_files[i]
            self.file_listbox.delete(i)

        self.log(f"已移除 {len(selected_indices)} 个文件")
        self.update_file_stats()

    def move_up(self):
        """上移选中文件"""
        selected_indices = list(self.file_listbox.curselection())
        if not selected_indices or selected_indices[0] == 0:
            return

        for i in selected_indices:
            self.selected_files[i - 1], self.selected_files[i] = \
                self.selected_files[i], self.selected_files[i - 1]

        # 刷新列表显示
        self.refresh_listbox()
        # 重新选中
        for i in selected_indices:
            self.file_listbox.selection_set(i - 1)
        self.update_file_stats()

    def move_down(self):
        """下移选中文件"""
        selected_indices = list(self.file_listbox.curselection())
        if not selected_indices or selected_indices[-1] == len(self.selected_files) - 1:
            return

        for i in reversed(selected_indices):
            self.selected_files[i + 1], self.selected_files[i] = \
                self.selected_files[i], self.selected_files[i + 1]

        self.refresh_listbox()
        for i in selected_indices:
            self.file_listbox.selection_set(i + 1)
        self.update_file_stats()

    def refresh_listbox(self):
        """刷新列表显示"""
        self.file_listbox.delete(0, tk.END)
        for file in self.selected_files:
            self.file_listbox.insert(tk.END, os.path.basename(file))

    def clear_file_list(self):
        """清空文件列表"""
        if self.selected_files:
            self.selected_files.clear()
            self.file_listbox.delete(0, tk.END)
            self.log("已清空文件列表")
            self.update_file_stats()

    def select_output_dir(self):
        """选择输出目录"""
        initial_dir = self.config["last_output_dir"] if self.config["last_output_dir"] else str(SCRIPT_DIR)

        dir_path = filedialog.askdirectory(title="选择输出目录", initialdir=initial_dir)

        if dir_path:
            self.output_dir_var.set(dir_path)
            self.config["last_output_dir"] = dir_path
            self.log(f"已选择输出目录: {dir_path}")

    def detect_encoding(self, file_path):
        """检测文件编码格式"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(10240)

            result = chardet.detect(raw_data)
            encoding = result['encoding']

            if encoding is None:
                encoding = 'utf-8'
            elif encoding.lower() in ['gb2312', 'gbk', 'gb18030']:
                encoding = 'gb18030'

            return encoding
        except Exception:
            return 'utf-8'

    def read_file_content(self, file_path):
        """读取文件内容，自动检测编码"""
        encoding = self.detect_encoding(file_path)

        try:
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='gb18030', errors='replace') as f:
                    return f.read()
            except Exception:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()

    def start_merge(self):
        """开始合并（在新线程中执行）"""
        if self.is_running:
            messagebox.showwarning("提示", "正在执行合并，请等待完成")
            return

        if not self.selected_files:
            messagebox.showerror("错误", "请先添加TXT文件")
            return

        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showerror("错误", "请选择输出目录")
            return

        # 在新线程中执行，避免UI卡死
        self.is_running = True
        thread = threading.Thread(target=self.execute_merge, daemon=True)
        thread.start()

    def execute_merge(self):
        """执行合并操作"""
        try:
            output_dir = self.output_dir_var.get().strip()

            # 确保输出目录存在
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                self.log(f"创建输出目录: {output_dir}")

            # 确定输出文件名
            filename = self.output_filename_var.get().strip()
            if not filename:
                filename = datetime.now().strftime("%Y%m%d_%H%M%S")
            if not filename.endswith(".txt"):
                filename += ".txt"

            output_path = os.path.join(output_dir, filename)
            total_files = len(self.selected_files)

            self.log(f"===== 开始合并操作 =====")
            self.log(f"共 {total_files} 个文件，输出到: {output_path}")

            merged_content = []
            success_count = 0
            failed_files = []

            for i, file_path in enumerate(self.selected_files):
                file_name = os.path.basename(file_path)
                chapter_name = os.path.splitext(file_name)[0]
                chapter_title = f"第{i + 1:04d}章 {chapter_name}"

                # 更新进度
                progress = (i / total_files) * 100
                self.root.after(0, self.update_progress, progress, f"正在处理: {file_name} ({i + 1}/{total_files})")

                self.log(f"[{i + 1}/{total_files}] 读取: {file_name}")

                try:
                    content = self.read_file_content(file_path)
                    line_count = len(content.splitlines())

                    # 添加章节标题
                    merged_content.append(f"\n\n{'=' * 40}\n")
                    merged_content.append(f"{chapter_title}\n")
                    merged_content.append(f"{'=' * 40}\n\n")

                    # 添加文件内容
                    merged_content.append(content)

                    success_count += 1
                    self.log(f"  - {chapter_title} ({line_count} 行)")

                except Exception as e:
                    self.log(f"  - 读取失败: {str(e)}")
                    failed_files.append(file_name)

            # 写入合并后的文件
            self.root.after(0, self.update_progress, 95, "正在写入合并文件...")
            self.log("正在写入合并后的文件...")

            with open(output_path, 'w', encoding='utf-8') as f:
                for chunk in merged_content:
                    f.write(chunk)

            # 完成
            self.root.after(0, self.update_progress, 100, "合并完成!")

            output_size = os.path.getsize(output_path)
            self.log(f"===== 合并完成 =====")
            self.log(f"成功合并 {success_count}/{total_files} 个文件")
            self.log(f"输出文件: {output_path}")
            self.log(f"文件大小: {self.format_size(output_size)}")

            if failed_files:
                self.log(f"失败文件: {', '.join(failed_files)}")

            # 保存配置
            self.root.after(0, self.save_config)

            # 弹出完成提示
            msg = f"成功合并 {success_count}/{total_files} 个文件\n输出: {output_path}\n大小: {self.format_size(output_size)}"
            if failed_files:
                msg += f"\n\n失败文件: {', '.join(failed_files)}"
            self.root.after(0, lambda: messagebox.showinfo("完成", msg))

        except Exception as e:
            self.log(f"合并失败: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("错误", f"合并失败: {str(e)}"))
        finally:
            self.is_running = False

    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)

                # 恢复UI状态
                self.output_dir_var.set(self.config.get("last_output_dir", ""))
                self.output_filename_var.set(self.config.get("last_output_filename", ""))
                self.log(f"已加载配置文件: {CONFIG_PATH}")
        except Exception as e:
            self.log(f"加载配置文件失败: {str(e)}")

    def save_config(self):
        """保存配置文件"""
        try:
            self.config = {
                "last_input_dir": self.config["last_input_dir"],
                "last_output_dir": self.output_dir_var.get(),
                "last_output_filename": self.output_filename_var.get(),
            }

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.log(f"配置已保存到: {CONFIG_PATH}")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")


if __name__ == "__main__":
    try:
        import chardet
    except ImportError:
        print("请先安装chardet: pip install chardet")
        exit(1)

    root = tk.Tk()
    app = TxtMergerApp(root)
    root.mainloop()
