import os
import json
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
    "WEBP": ".webp"
}

class ImageFormatConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("图片格式转换工具")
        self.root.geometry("700x500")
        self.root.resizable(True, True)

        # 加载配置
        self.config = self.load_config()

        # 选中的文件列表
        self.selected_files = []

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

        # 选中文件列表
        self.file_listbox = tk.Listbox(file_frame, selectmode=tk.EXTENDED, height=8)
        self.file_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        # 列表滚动条
        scrollbar = ttk.Scrollbar(self.file_listbox, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        # 移除选中文件按钮
        ttk.Button(file_frame, text="移除选中文件", command=self.remove_selected).pack(anchor=tk.W)

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

        # 配置列权重（让输入框自适应宽度）
        config_frame.columnconfigure(1, weight=1)

        # 3. 转换按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="开始转换", command=self.start_conversion).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="保存当前配置", command=self.save_current_config).pack(side=tk.LEFT, padx=5)

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
            # 去重添加文件
            for file in files:
                if file not in self.selected_files:
                    self.selected_files.append(file)
                    self.file_listbox.insert(tk.END, os.path.basename(file))

    def remove_selected(self):
        """移除选中的文件"""
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            return

        # 从后往前删除（避免索引偏移）
        for i in sorted(selected_indices, reverse=True):
            self.file_listbox.delete(i)
            del self.selected_files[i]

    def select_output_dir(self):
        """选择输出目录"""
        dir_path = filedialog.askdirectory(title="选择输出目录")
        if dir_path:
            self.output_dir_var.set(dir_path)

    def save_current_config(self):
        """保存当前配置"""
        self.config["output_format"] = self.format_var.get()
        self.config["output_dir"] = self.output_dir_var.get()
        self.save_config()
        messagebox.showinfo("成功", "配置已保存")

    def update_status(self, message):
        """更新状态文本框"""
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)
        self.root.update_idletasks()  # 实时刷新

    def start_conversion(self):
        """开始转换图片格式"""
        if not self.selected_files:
            messagebox.showwarning("提示", "请先选择图片文件")
            return

        output_format = self.format_var.get()
        output_ext = SUPPORTED_FORMATS[output_format].lower()
        output_dir = self.output_dir_var.get()

        # 确保输出目录存在
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("目录错误", f"无法创建输出目录: {str(e)}")
            return

        # 清空状态
        self.status_text.config(state=tk.NORMAL)
        self.status_text.delete(1.0, tk.END)
        self.status_text.config(state=tk.DISABLED)

        self.update_status(f"开始转换，目标格式: {output_format}")
        success_count = 0
        fail_count = 0

        for file_path in self.selected_files:
            try:
                # 构建输出文件名（保留原文件名，更换扩展名）
                file_name = os.path.splitext(os.path.basename(file_path))[0]
                output_path = os.path.join(output_dir, f"{file_name}{output_ext}")

                # 处理图片
                with Image.open(file_path) as img:
                    # 特殊处理透明通道（PNG转JPG时）
                    if output_format == "JPEG" and img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")

                    img.save(output_path, format=output_format)

                success_count += 1
                self.update_status(f"成功: {os.path.basename(file_path)} → {os.path.basename(output_path)}")

            except Exception as e:
                fail_count += 1
                self.update_status(f"失败: {os.path.basename(file_path)} - {str(e)}")

        # 转换完成
        self.update_status(f"\n转换完成 - 成功: {success_count} 个, 失败: {fail_count} 个")
        messagebox.showinfo("完成", f"转换完成\n成功: {success_count} 个\n失败: {fail_count} 个")

        # 自动保存当前配置
        self.save_current_config()

if __name__ == "__main__":
    root = tk.Tk()
    app = ImageFormatConverter(root)
    root.mainloop()
