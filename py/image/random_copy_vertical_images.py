import os
import random
import json
import shutil
from PIL import Image
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import sys
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "random_copy_vertical_images"
CONFIG_DIR = SCRIPT_DIR / "json"

CONFIG_FILE = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
HISTORY_FILE = CONFIG_DIR / "logs" / "copy_history.log"
CONFIG_DIR.mkdir(exist_ok=True)


class ImageCopyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片复制工具")
        self.root.geometry("600x400")

        # 初始化配置
        self.config = {
            "source_dir": "",
            "target_dir": "",
            "copy_count": 60,
            "random_skip_rate": 0.5
        }

        # 加载配置
        self.load_config()

        # 加载历史记录
        self.history = self.load_history()

        # 创建界面
        self.create_widgets()

    def create_widgets(self):
        # 创建标签页
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 主配置页
        frame_main = ttk.Frame(notebook)
        notebook.add(frame_main, text="配置")

        # 源目录选择
        ttk.Label(frame_main, text="源目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.source_dir_var = tk.StringVar(value=self.config["source_dir"])
        ttk.Entry(frame_main, textvariable=self.source_dir_var, width=50).grid(row=0, column=1, pady=5)
        ttk.Button(frame_main, text="浏览...", command=self.browse_source).grid(row=0, column=2, padx=5, pady=5)

        # 目标目录选择
        ttk.Label(frame_main, text="目标目录:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.target_dir_var = tk.StringVar(value=self.config["target_dir"])
        ttk.Entry(frame_main, textvariable=self.target_dir_var, width=50).grid(row=1, column=1, pady=5)
        ttk.Button(frame_main, text="浏览...", command=self.browse_target).grid(row=1, column=2, padx=5, pady=5)

        # 复制数量
        ttk.Label(frame_main, text="复制数量:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.copy_count_var = tk.IntVar(value=self.config["copy_count"])
        ttk.Entry(frame_main, textvariable=self.copy_count_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=5)

        # 随机跳过比例
        ttk.Label(frame_main, text="随机跳过比例:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.skip_rate_var = tk.DoubleVar(value=self.config["random_skip_rate"])
        ttk.Scale(frame_main, variable=self.skip_rate_var, from_=0.0, to=0.99,
                  orient=tk.HORIZONTAL, length=200).grid(row=3, column=1, sticky=tk.W, pady=5)
        self.skip_rate_label = ttk.Label(frame_main, text=f"{self.skip_rate_var.get():.2f}")
        self.skip_rate_label.grid(row=3, column=2, padx=5)
        self.skip_rate_var.trace_add("write", self.update_skip_rate_label)

        # 操作按钮
        button_frame = ttk.Frame(frame_main)
        button_frame.grid(row=4, column=0, columnspan=3, pady=20)

        ttk.Button(button_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="清除历史", command=self.clear_history).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="执行复制", command=self.execute_copy).pack(side=tk.LEFT, padx=10)

        # 状态显示页
        self.frame_status = ttk.Frame(notebook)
        notebook.add(self.frame_status, text="状态")

        ttk.Label(self.frame_status, text="操作日志:").pack(anchor=tk.W, padx=5, pady=5)
        self.log_text = tk.Text(self.frame_status, height=15, width=60)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)

    def update_skip_rate_label(self, *args):
        self.skip_rate_label.config(text=f"{self.skip_rate_var.get():.2f}")

    def browse_source(self):
        directory = filedialog.askdirectory()
        if directory:
            self.source_dir_var.set(directory)

    def browse_target(self):
        directory = filedialog.askdirectory()
        if directory:
            self.target_dir_var.set(directory)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
            except Exception as e:
                self.log(f"加载配置失败: {str(e)}")

    def save_config(self):
        try:
            self.config = {
                "source_dir": self.source_dir_var.get(),
                "target_dir": self.target_dir_var.get(),
                "copy_count": self.copy_count_var.get(),
                "random_skip_rate": self.skip_rate_var.get()
            }

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.log("配置已保存")
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return set(json.load(f))
            except Exception as e:
                self.log(f"加载历史记录失败: {str(e)}")
        return set()

    def save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self.history), f, ensure_ascii=False, indent=2)
            self.log("历史记录已更新")
        except Exception as e:
            self.log(f"保存历史记录失败: {str(e)}")

    def clear_history(self):
        if messagebox.askyesno("确认", "确定要清除所有历史记录吗？"):
            self.history.clear()
            self.save_history()
            self.log("历史记录已清除")

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def clear_target_dir(self, target_dir):
        if os.path.exists(target_dir):
            for item in os.listdir(target_dir):
                path = os.path.join(target_dir, item)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                except Exception as e:
                    self.log(f"清除文件失败: {path}, 错误: {str(e)}")
        else:
            os.makedirs(target_dir, exist_ok=True)

    def find_vertical_images_fast(self, source_dir, needed):
        selected = []
        image_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

        if not os.path.exists(source_dir):
            self.log(f"源目录不存在: {source_dir}")
            return selected

        for root, _, files in os.walk(source_dir):
            random.shuffle(files)
            for file in files:
                if random.random() < self.skip_rate_var.get():
                    continue

                if not file.lower().endswith(image_ext):
                    continue

                full_path = os.path.join(root, file)
                if full_path in self.history:
                    continue

                try:
                    with Image.open(full_path) as img:
                        w, h = img.size
                        if h > w:
                            selected.append(full_path)
                            self.log(f"找到符合条件的图片: {os.path.basename(full_path)}")
                            if len(selected) >= needed:
                                return selected
                except Exception as e:
                    self.log(f"处理图片失败: {full_path}, 错误: {str(e)}")
                    continue

        return selected

    def execute_copy(self):
        source_dir = self.source_dir_var.get()
        target_dir = self.target_dir_var.get()
        copy_count = self.copy_count_var.get()

        # 验证输入
        if not source_dir:
            messagebox.showerror("错误", "请选择源目录")
            return

        if not target_dir:
            messagebox.showerror("错误", "请选择目标目录")
            return

        if copy_count <= 0:
            messagebox.showerror("错误", "复制数量必须大于0")
            return

        self.log("开始查找符合条件的图片...")
        selected = self.find_vertical_images_fast(source_dir, copy_count)

        if not selected:
            self.log("⚠️ 没找到符合条件的新图片（可能都复制过了）")
            messagebox.showwarning("警告", "没找到符合条件的新图片（可能都复制过了）")
            return

        self.log(f"找到 {len(selected)} 张符合条件的图片，开始复制...")

        try:
            self.clear_target_dir(target_dir)
            os.makedirs(target_dir, exist_ok=True)

            for img_path in selected:
                dest_path = os.path.join(target_dir, os.path.basename(img_path))
                shutil.copy2(img_path, dest_path)
                self.history.add(img_path)
                self.log(f"已复制: {os.path.basename(img_path)}")

            self.save_history()
            self.log(f"✅ 复制完成，共复制 {len(selected)} 张图片")
            self.log(f"📁 目标目录: {target_dir}")
            messagebox.showinfo("成功", f"复制完成，共复制 {len(selected)} 张图片到 {target_dir}")
        except Exception as e:
            self.log(f"复制过程出错: {str(e)}")
            messagebox.showerror("错误", f"复制过程出错: {str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCopyApp(root)
    root.mainloop()
