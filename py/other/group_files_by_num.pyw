import os
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import time

class FileGrouperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文件分组工具")
        self.root.geometry("700x500")
        self.root.resizable(True, True)

        # 基础配置
        self.base_dir = r"H:\NOVEL\Xbook\HH2025\txt"
        self.group_size = 800  # 每组文件数量

        # 创建界面
        self.create_widgets()

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 目录显示
        ttk.Label(main_frame, text="目标根目录:").pack(anchor=tk.W, pady=(0, 5))
        self.dir_var = tk.StringVar(value=self.base_dir)
        dir_frame = ttk.Frame(main_frame)
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(dir_frame, textvariable=self.dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(dir_frame, text="浏览", command=self.browse_dir).pack(side=tk.RIGHT, padx=5)

        # 分组大小设置
        ttk.Label(main_frame, text="每组文件数量:").pack(anchor=tk.W, pady=(0, 5))
        self.size_var = tk.IntVar(value=self.group_size)
        size_frame = ttk.Frame(main_frame)
        size_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Entry(size_frame, textvariable=self.size_var, width=10).pack(side=tk.LEFT)
        ttk.Label(size_frame, text="(文件数量少于此值不会分组)").pack(side=tk.LEFT, padx=5)

        # 操作按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 15))
        self.start_btn = ttk.Button(btn_frame, text="开始分组", command=self.start_grouping)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_grouping, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # 日志区域
        ttk.Label(main_frame, text="处理日志:").pack(anchor=tk.W, pady=(0, 5))
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        # 状态标签
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(main_frame, textvariable=self.status_var).pack(anchor=tk.W, pady=10)

        # 控制变量
        self.running = False

    def browse_dir(self):
        """浏览选择根目录"""
        dir_path = tk.filedialog.askdirectory(title="选择根目录")
        if dir_path:
            self.dir_var.set(dir_path)

    def log(self, message):
        """添加日志信息"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def stop_grouping(self):
        """停止分组操作"""
        self.running = False
        self.status_var.set("已停止")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.log("用户已停止操作")

    def process_directory(self, subdir_path):
        """处理单个子目录，按数量分组文件"""
        subdir_name = os.path.basename(subdir_path)
        self.log(f"开始处理子目录: {subdir_name}")

        # 获取目录中所有文件（排除已存在的分组目录）
        all_items = os.listdir(subdir_path)
        files = []
        for item in all_items:
            item_path = os.path.join(subdir_path, item)
            if os.path.isfile(item_path) and not item.startswith("group_"):
                files.append(item)

        file_count = len(files)
        self.log(f"发现 {file_count} 个文件")

        # 不足300个文件不分组
        if file_count < self.size_var.get():
            self.log(f"文件数量不足 {self.size_var.get()}，不进行分组")
            return True

        # 计算需要创建的分组数
        group_count = (file_count + self.size_var.get() - 1) // self.size_var.get()
        self.log(f"需要创建 {group_count} 个分组目录")

        # 按组移动文件
        for group_idx in range(group_count):
            if not self.running:  # 检查是否需要停止
                return False

            # 创建分组目录
            group_name = f"group_{group_idx + 1}"
            group_path = os.path.join(subdir_path, group_name)
            Path(group_path).mkdir(exist_ok=True)
            self.log(f"创建分组目录: {group_name}")

            # 计算当前组的文件范围
            start_idx = group_idx * self.size_var.get()
            end_idx = min((group_idx + 1) * self.size_var.get(), file_count)
            group_files = files[start_idx:end_idx]

            # 移动文件到分组目录
            for file in group_files:
                src = os.path.join(subdir_path, file)
                dst = os.path.join(group_path, file)
                try:
                    shutil.move(src, dst)
                except Exception as e:
                    self.log(f"移动文件 {file} 失败: {str(e)}")
                    return False

            self.log(f"分组 {group_name} 完成，包含 {len(group_files)} 个文件")

        self.log(f"子目录 {subdir_name} 处理完成")
        return True

    def start_grouping(self):
        """开始批量处理所有子目录"""
        self.base_dir = self.dir_var.get()
        self.group_size = self.size_var.get()

        # 验证参数
        if not os.path.exists(self.base_dir):
            messagebox.showerror("错误", f"目录不存在: {self.base_dir}")
            return

        if self.group_size <= 0:
            messagebox.showerror("错误", "分组大小必须大于0")
            return

        # 初始化状态
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("正在处理...")
        self.log("====== 开始文件分组操作 ======")

        # 获取所有子目录
        try:
            subdirs = [
                os.path.join(self.base_dir, d)
                for d in os.listdir(self.base_dir)
                if os.path.isdir(os.path.join(self.base_dir, d))
            ]
            self.log(f"发现 {len(subdirs)} 个子目录需要处理")
        except Exception as e:
            self.log(f"获取子目录失败: {str(e)}")
            self.stop_grouping()
            return

        # 逐个处理子目录
        success_count = 0
        fail_count = 0

        for subdir in subdirs:
            if not self.running:  # 检查是否需要停止
                break

            if self.process_directory(subdir):
                success_count += 1
            else:
                fail_count += 1

        # 处理完成
        self.stop_grouping()
        self.log(f"====== 处理结束 ======")
        self.log(f"成功处理: {success_count} 个子目录")
        self.log(f"处理失败: {fail_count} 个子目录")
        messagebox.showinfo("完成", f"处理结束\n成功: {success_count} 个\n失败: {fail_count} 个")

if __name__ == "__main__":
    root = tk.Tk()
    app = FileGrouperApp(root)
    root.mainloop()
