import os
import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image

# 配置与常量（绝对路径引入）
import os
from pathlib import Path

# 获取脚本所在目录绝对路径
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
# 脚本名称
SCRIPT_NAME = "image_format_converter"
# 配置目录（绝对路径）
CONFIG_DIR = SCRIPT_DIR / "json"
# 配置文件路径（绝对路径）
CONFIG_PATH = CONFIG_DIR / f"{SCRIPT_NAME}_config.json"
# 确保配置目录存在
CONFIG_DIR.mkdir(exist_ok=True)

# 支持的输入输出图片格式
SUPPORTED_FORMATS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "BMP": ".bmp",
    "GIF": ".gif",
    "WEBP": ".webp",
    "ICO": ".ico"
}

# 支持的图片扩展名（用于文件夹模式递归扫描，含 .jpeg）
IMAGE_EXTS = tuple(SUPPORTED_FORMATS.values()) + (".jpeg",)

class ImageFormatConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("图片格式转换工具")
        self.root.geometry("700x500")
        self.root.resizable(True, True)

        # 加载配置
        self.config = self.load_config()

        # 选中的文件列表（元素为 {"abs": 绝对路径, "rel": 相对扫描根目录的路径}）
        self.selected_files = []
        # 文件夹扫描根目录（文件夹模式下用于保留目录结构）
        self.scan_root = None
        # 是否正在转换
        self._running = False
        # 转换日志消息队列（后台线程写入，主线程批量消费）
        self.msg_queue = queue.Queue()

        # 创建界面
        self.create_widgets()

    def load_config(self):
        """加载配置文件（默认配置+保存的配置）"""
        default_config = {
            "output_format": "PNG",
            "output_dir": str(SCRIPT_DIR / "converted_images")  # 默认输出目录
        }

        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    # 合并配置（确保默认配置项存在）
                    return {**default_config,** saved_config}
            except Exception as e:
                messagebox.showerror("配置加载失败", f"使用默认配置: {str(e)}")

        return default_config

    def save_config(self):
        """保存当前配置到文件"""
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("保存失败", f"配置保存出错: {str(e)}")

    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 文件选择区域
        file_frame = ttk.LabelFrame(main_frame, text="图片文件选择", padding="10")
        file_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        ttk.Button(file_frame, text="选择图片文件", command=self.select_files).pack(anchor=tk.W, pady=5)
        ttk.Button(file_frame, text="选择文件夹（含子目录）", command=self.select_folder).pack(anchor=tk.W, pady=(0, 5))

        # 选中文件列表
        self.file_listbox = tk.Listbox(file_frame, selectmode=tk.EXTENDED, height=8)
        self.file_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        # 列表滚动条
        scrollbar = ttk.Scrollbar(self.file_listbox, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        # 移除/清空文件按钮行
        btn_row = ttk.Frame(file_frame)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="移除选中文件", command=self.remove_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_row, text="一键清空", command=self.clear_all).pack(side=tk.LEFT)

        # 2. 转换配置区域
        config_frame = ttk.LabelFrame(main_frame, text="转换配置", padding="10")
        config_frame.pack(fill=tk.X, pady=5)

        # 输出格式选择
        ttk.Label(config_frame, text="目标格式:").grid(row=0, column=0, sticky=tk.W, pady=5, padx=5)
        self.format_var = tk.StringVar(value=self.config["output_format"])
        format_combobox = ttk.Combobox(
            config_frame,
            textvariable=self.format_var,
            values=list(SUPPORTED_FORMATS.keys()),
            state="readonly",
            width=10
        )
        format_combobox.grid(row=0, column=1, sticky=tk.W, pady=5, padx=5)

        # 输出目录选择
        ttk.Label(config_frame, text="输出目录:").grid(row=1, column=0, sticky=tk.W, pady=5, padx=5)
        self.output_dir_var = tk.StringVar(value=self.config["output_dir"])
        ttk.Entry(config_frame, textvariable=self.output_dir_var, width=40).grid(row=1, column=1, sticky=tk.EW, pady=5, padx=5)
        ttk.Button(config_frame, text="浏览...", command=self.select_output_dir).grid(row=1, column=2, pady=5, padx=5)

        # 保留目录结构选项（文件夹模式下生效）
        self.keep_structure_var = tk.BooleanVar(value=self.config.get("keep_structure", True))
        ttk.Checkbutton(
            config_frame,
            text="保留目录结构（文件夹模式下按原目录层级输出）",
            variable=self.keep_structure_var
        ).grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=5, padx=5)

        # 配置列权重（让输入框自适应宽度）
        config_frame.columnconfigure(1, weight=1)

        # 3. 转换按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="开始转换", command=self.start_conversion).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="保存当前配置", command=self.save_current_config).pack(side=tk.LEFT, padx=5)
        # 保存按钮引用，转换期间禁用防止重复点击（线程安全交互）
        self.convert_btn = btn_frame.winfo_children()[0]

        # 4. 转换状态区域
        status_frame = ttk.LabelFrame(main_frame, text="转换状态", padding="10")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.status_text = tk.Text(status_frame, wrap=tk.WORD, height=6)
        self.status_text.pack(fill=tk.BOTH, expand=True)
        self.status_text.config(state=tk.DISABLED)

    def select_files(self):
        """选择图片文件"""
        # 构建所有支持的扩展名列表（包含 .jpg 和 .jpeg）
        all_extensions = []
        for exts in SUPPORTED_FORMATS.values():
            all_extensions.extend(exts)

        files = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[("图片文件", all_extensions)]  # 同时显示所有支持的扩展名
        )

        if files:
            # 去重添加文件（单文件模式无相对路径）
            for file in files:
                self._add_file(file, None)

    def select_folder(self):
        """选择文件夹，递归扫描目录及子目录下的所有图片"""
        dir_path = filedialog.askdirectory(title="选择包含图片的文件夹")
        if not dir_path:
            return

        added = 0
        self.scan_root = dir_path
        for root, _dirs, files in os.walk(dir_path):
            for name in files:
                if name.lower().endswith(IMAGE_EXTS):
                    abs_path = os.path.join(root, name)
                    rel_path = os.path.relpath(abs_path, dir_path)
                    if self._add_file(abs_path, rel_path):
                        added += 1

        self._show_toast("扫描完成", f"文件夹 {dir_path} 共扫描到 {added} 张新图片", "success" if added else "info")

    def _add_file(self, abs_path, rel_path):
        """去重添加文件到列表，返回是否新增"""
        for item in self.selected_files:
            if item["abs"] == abs_path:
                return False
        self.selected_files.append({"abs": abs_path, "rel": rel_path})
        # 列表显示：文件夹模式显示相对路径，单文件模式显示文件名
        self.file_listbox.insert(tk.END, rel_path if rel_path else os.path.basename(abs_path))
        return True

    def remove_selected(self):
        """移除选中的文件"""
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            return

        # 从后往前删除（避免索引偏移）
        for i in sorted(selected_indices, reverse=True):
            self.file_listbox.delete(i)
            del self.selected_files[i]

    def clear_all(self):
        """一键清空已选中的图片列表"""
        if not self.selected_files:
            self._show_toast("提示", "列表中没有已选图片", "info")
            return
        if not messagebox.askyesno("确认", f"确定要清空已选的 {len(self.selected_files)} 张图片吗？"):
            return
        self.selected_files.clear()
        self.file_listbox.delete(0, tk.END)
        self.scan_root = None
        self._show_toast("已清空", "已清空所有选中图片", "success")

    def select_output_dir(self):
        """选择输出目录"""
        dir_path = filedialog.askdirectory(title="选择输出目录")
        if dir_path:
            self.output_dir_var.set(dir_path)

    def save_current_config(self):
        """保存当前配置"""
        self.config["output_format"] = self.format_var.get()
        self.config["output_dir"] = self.output_dir_var.get()
        self.config["keep_structure"] = self.keep_structure_var.get()
        self.save_config()
        self._show_toast("成功", "配置已保存", "success")

    def update_status(self, message):
        """更新状态文本框"""
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)

    def _conversion_worker(self, output_format, output_ext, output_dir, keep_structure):
        """后台线程：逐个转换图片，日志通过队列回传主线程，避免界面卡死"""
        success_count = 0
        fail_count = 0
        total = len(self.selected_files)

        for index, item in enumerate(self.selected_files, 1):
            file_path = item["abs"]
            try:
                # 确定输出目录：保留目录结构时按原相对目录层级创建子目录
                target_dir = output_dir
                if keep_structure and item["rel"]:
                    target_dir = os.path.join(output_dir, os.path.dirname(item["rel"]))
                    os.makedirs(target_dir, exist_ok=True)

                # 构建输出文件名（保留原文件名，更换扩展名）
                file_name = os.path.splitext(os.path.basename(file_path))[0]
                output_path = os.path.join(target_dir, f"{file_name}{output_ext}")

                # 处理图片
                with Image.open(file_path) as img:
                    # 特殊处理透明通道（PNG转JPG时）
                    if output_format == "JPEG" and img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")

                    # 特殊处理 ICO 格式
                    if output_format == "ICO":
                        # ICO 格式需要调整尺寸（最大 256x256）
                        max_size = 256
                        if img.width > max_size or img.height > max_size:
                            img.thumbnail((max_size, max_size), Image.LANCZOS)

                        # 确保有 alpha 通道以支持透明度
                        if img.mode != "RGBA":
                            img = img.convert("RGBA")

                        # 保存为 ICO 格式，可以包含多个尺寸
                        img.save(output_path, format="ICO", sizes=[(img.width, img.height)])
                    else:
                        img.save(output_path, format=output_format)

                success_count += 1
                self.msg_queue.put(("log", f"[{index}/{total}] 成功: {os.path.basename(file_path)} → {os.path.basename(output_path)}"))

            except Exception as e:
                fail_count += 1
                self.msg_queue.put(("log", f"[{index}/{total}] 失败: {os.path.basename(file_path)} - {str(e)}"))

        # 结束信号，附带统计结果，由主线程处理收尾（Toast 必须在主线程）
        self.msg_queue.put(("done", success_count, fail_count))

    def _poll_msg_queue(self):
        """主线程定时消费日志队列，批量写入状态文本框（每 150ms 一次，避免频繁刷新卡顿）"""
        messages = []
        while True:
            try:
                messages.append(self.msg_queue.get_nowait())
            except queue.Empty:
                break

        logs = [msg[1] for msg in messages if msg[0] == "log"]
        if logs:
            self.status_text.config(state=tk.NORMAL)
            self.status_text.insert(tk.END, "\n".join(logs) + "\n")
            self.status_text.see(tk.END)
            self.status_text.config(state=tk.DISABLED)

        done_msgs = [msg for msg in messages if msg[0] == "done"]
        if done_msgs:
            _, success_count, fail_count = done_msgs[-1]
            self._on_conversion_finished(success_count, fail_count)
        elif self._running:
            # 未完成时继续轮询
            self.root.after(150, self._poll_msg_queue)

    def _on_conversion_finished(self, success_count, fail_count):
        """转换完成：恢复界面、写汇总日志、弹 Toast、自动保存配置"""
        self._running = False
        self.convert_btn.config(state=tk.NORMAL, text="开始转换")
        self.update_status(f"\n转换完成 - 成功: {success_count} 个, 失败: {fail_count} 个")
        if fail_count:
            self._show_toast("转换完成", f"成功: {success_count} 个，失败: {fail_count} 个", "warning")
        else:
            self._show_toast("转换完成", f"共转换 {success_count} 张图片", "success")

        # 自动保存当前配置（不弹提示）
        self.config["output_format"] = self.format_var.get()
        self.config["output_dir"] = self.output_dir_var.get()
        self.config["keep_structure"] = self.keep_structure_var.get()
        self.save_config()

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


    def start_conversion(self):
        """开始转换图片格式"""
        if self._running:
            self._show_toast("提示", "正在转换中，请等待完成", "warning")
            return
        if not self.selected_files:
            self._show_toast("提示", "请先选择图片文件或文件夹", "warning")
            return

        output_format = self.format_var.get()
        output_ext = SUPPORTED_FORMATS[output_format].lower()
        output_dir = self.output_dir_var.get()
        keep_structure = self.keep_structure_var.get()

        # 确保输出目录存在
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            self._show_toast("目录错误", f"无法创建输出目录: {str(e)}", "error")
            return

        # 清空状态
        self.status_text.config(state=tk.NORMAL)
        self.status_text.delete(1.0, tk.END)
        self.status_text.config(state=tk.DISABLED)

        self.update_status(f"开始转换，目标格式: {output_format}，共 {len(self.selected_files)} 张图片")
        self._running = True
        self.convert_btn.config(state=tk.DISABLED, text="转换中...")
        self.msg_queue = queue.Queue()

        # 后台线程执行转换，主线程保持响应，日志通过队列批量回显
        worker = threading.Thread(
            target=self._conversion_worker,
            args=(output_format, output_ext, output_dir, keep_structure),
            daemon=True
        )
        worker.start()
        self.root.after(150, self._poll_msg_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = ImageFormatConverter(root)
    root.mainloop()
