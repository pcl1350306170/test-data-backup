import os
import json
import shutil
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "duplicate_image_cleaner"
CONFIG_DIR = SCRIPT_DIR / "json"

CONFIG_FILE = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)


class DuplicateImageCleaner:
    def __init__(self, root):
        self.root = root
        self.root.title("重复图片清理工具")
        self.root.geometry("800x600")

        # 初始化配置
        self.config = {
            "source_dir": "",
            "threshold": 5
        }

        # 加载配置
        self.load_config()

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
        ttk.Entry(frame_main, textvariable=self.source_dir_var, width=60).grid(row=0, column=1, pady=5)
        ttk.Button(frame_main, text="浏览...", command=self.browse_source).grid(row=0, column=2, padx=5, pady=5)

        # 重复阈值
        ttk.Label(frame_main, text="重复阈值(相同文件名数量):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.threshold_var = tk.IntVar(value=self.config["threshold"])
        ttk.Entry(frame_main, textvariable=self.threshold_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=5)

        # 操作按钮
        button_frame = ttk.Frame(frame_main)
        button_frame.grid(row=2, column=0, columnspan=3, pady=20)

        ttk.Button(button_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="扫描重复", command=self.scan_duplicates).pack(side=tk.LEFT, padx=10)

        # 结果显示页
        self.frame_result = ttk.Frame(notebook)
        notebook.add(self.frame_result, text="扫描结果")

        ttk.Label(self.frame_result, text="重复文件信息:").pack(anchor=tk.W, padx=5, pady=5)

        # 创建Treeview显示结果
        tree_frame = ttk.Frame(self.frame_result)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ("subdir", "file_count", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)
        
        self.tree.heading("subdir", text="子目录名")
        self.tree.heading("file_count", text="图片数量")
        self.tree.heading("status", text="状态")
        
        self.tree.column("subdir", width=400)
        self.tree.column("file_count", width=100)
        self.tree.column("status", width=150)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 进度和删除按钮
        progress_frame = ttk.Frame(self.frame_result)
        progress_frame.pack(fill=tk.X, padx=5, pady=5)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=5)

        self.status_label = ttk.Label(progress_frame, text="就绪")
        self.status_label.pack(anchor=tk.W, pady=5)

        delete_button_frame = ttk.Frame(self.frame_result)
        delete_button_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(delete_button_frame, text="删除选中目录", command=self.delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(delete_button_frame, text="删除所有标记目录", command=self.delete_all_marked).pack(side=tk.LEFT, padx=5)

    def browse_source(self):
        directory = filedialog.askdirectory()
        if directory:
            self.source_dir_var.set(directory)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
            except Exception as e:
                print(f"加载配置失败: {str(e)}")

    def save_config(self):
        try:
            self.config = {
                "source_dir": self.source_dir_var.get(),
                "threshold": self.threshold_var.get()
            }

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def scan_duplicates(self):
        source_dir = self.source_dir_var.get()
        threshold = self.threshold_var.get()

        if not source_dir:
            messagebox.showerror("错误", "请选择源目录")
            return

        if not os.path.exists(source_dir):
            messagebox.showerror("错误", "源目录不存在")
            return

        if threshold <= 0:
            messagebox.showerror("错误", "重复阈值必须大于0")
            return

        # 清空之前的结果
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.status_label.config(text="正在扫描...")
        self.progress_var.set(0)
        self.root.update_idletasks()

        try:
            # 获取所有子目录
            subdirs = [d for d in os.listdir(source_dir) 
                      if os.path.isdir(os.path.join(source_dir, d))]
            
            if not subdirs:
                messagebox.showwarning("警告", "未找到任何子目录")
                return

            total_subdirs = len(subdirs)
            self.status_label.config(text=f"发现 {total_subdirs} 个子目录，开始分析...")

            # 构建文件名到子目录的映射
            filename_to_dirs = defaultdict(list)
            
            for idx, subdir in enumerate(subdirs):
                subdir_path = os.path.join(source_dir, subdir)
                
                # 获取该子目录下的所有图片文件名
                try:
                    files = [f for f in os.listdir(subdir_path) 
                            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'))]
                    
                    for filename in files:
                        filename_to_dirs[filename].append(subdir)
                except Exception as e:
                    print(f"访问子目录失败: {subdir_path}, 错误: {str(e)}")
                    continue

                # 更新进度
                progress = (idx + 1) / total_subdirs * 50  # 扫描阶段占50%
                self.progress_var.set(progress)
                self.status_label.config(text=f"扫描进度: {idx + 1}/{total_subdirs}")
                self.root.update_idletasks()

            self.status_label.config(text="分析重复文件...")
            self.root.update_idletasks()

            # 找出重复的子目录
            dir_file_counts = defaultdict(set)  # 记录每个子目录的文件集合
            for filename, dirs in filename_to_dirs.items():
                for subdir in dirs:
                    dir_file_counts[subdir].add(filename)

            # 计算每对子目录之间的相同文件数
            duplicate_groups = []
            processed_dirs = set()
            
            subdir_list = list(dir_file_counts.keys())
            
            for i in range(len(subdir_list)):
                dir1 = subdir_list[i]
                if dir1 in processed_dirs:
                    continue
                    
                group = [dir1]
                
                for j in range(i + 1, len(subdir_list)):
                    dir2 = subdir_list[j]
                    if dir2 in processed_dirs:
                        continue
                    
                    # 计算两个目录的相同文件数
                    common_files = dir_file_counts[dir1] & dir_file_counts[dir2]
                    
                    if len(common_files) >= threshold:
                        group.append(dir2)
                
                if len(group) > 1:
                    duplicate_groups.append(group)
                    processed_dirs.update(group)

            # 显示结果
            all_dirs_to_delete = set()
            
            for group in duplicate_groups:
                # 按目录名排序，保留最后一个（较晚创建的），删除其他的
                sorted_group = sorted(group)
                dirs_to_delete = sorted_group[:-1]  # 删除前面的，保留最后一个
                kept_dir = sorted_group[-1]
                
                all_dirs_to_delete.update(dirs_to_delete)
                
                # 在Treeview中显示
                for dir_name in dirs_to_delete:
                    file_count = len(dir_file_counts[dir_name])
                    self.tree.insert("", tk.END, values=(dir_name, file_count, "待删除"), tags=("delete",))
                
                # 标记保留的目录
                file_count = len(dir_file_counts[kept_dir])
                self.tree.insert("", tk.END, values=(kept_dir, file_count, "保留"), tags=("keep",))

            # 设置标签样式
            self.tree.tag_configure("delete", foreground="red")
            self.tree.tag_configure("keep", foreground="green")

            # 更新进度
            self.progress_var.set(100)
            
            if all_dirs_to_delete:
                self.status_label.config(text=f"发现 {len(all_dirs_to_delete)} 个待删除的重复目录")
                messagebox.showinfo("扫描完成", f"发现 {len(duplicate_groups)} 组重复目录\n共 {len(all_dirs_to_delete)} 个目录待删除")
            else:
                self.status_label.config(text="未发现重复目录")
                messagebox.showinfo("扫描完成", "未发现重复目录")

        except Exception as e:
            self.status_label.config(text="扫描出错")
            messagebox.showerror("错误", f"扫描过程出错: {str(e)}")

    def delete_selected(self):
        selected_items = self.tree.selection()
        
        if not selected_items:
            messagebox.showwarning("警告", "请先选择要删除的目录")
            return

        dirs_to_delete = []
        for item in selected_items:
            values = self.tree.item(item, "values")
            if values[2] == "待删除":
                dirs_to_delete.append(values[0])

        if not dirs_to_delete:
            messagebox.showwarning("警告", "选中的项目不是待删除状态")
            return

        self.confirm_and_delete(dirs_to_delete)

    def delete_all_marked(self):
        dirs_to_delete = []
        
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if values[2] == "待删除":
                dirs_to_delete.append(values[0])

        if not dirs_to_delete:
            messagebox.showwarning("警告", "没有标记为待删除的目录")
            return

        self.confirm_and_delete(dirs_to_delete)

    def confirm_and_delete(self, dirs_to_delete):
        source_dir = self.source_dir_var.get()
        
        # 显示确认对话框
        confirm_msg = f"确定要删除以下 {len(dirs_to_delete)} 个目录吗？\n\n"
        for dir_name in dirs_to_delete[:10]:  # 只显示前10个
            confirm_msg += f"- {dir_name}\n"
        
        if len(dirs_to_delete) > 10:
            confirm_msg += f"... 还有 {len(dirs_to_delete) - 10} 个目录\n"
        
        confirm_msg += "\n此操作不可恢复！"

        if not messagebox.askyesno("确认删除", confirm_msg):
            return

        deleted_count = 0
        failed_count = 0

        for idx, dir_name in enumerate(dirs_to_delete):
            dir_path = os.path.join(source_dir, dir_name)
            
            try:
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)
                    deleted_count += 1
                    
                    # 从Treeview中移除
                    for item in self.tree.get_children():
                        values = self.tree.item(item, "values")
                        if values[0] == dir_name:
                            self.tree.delete(item)
                            break
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                print(f"删除目录失败: {dir_path}, 错误: {str(e)}")

            # 更新进度
            progress = (idx + 1) / len(dirs_to_delete) * 100
            self.progress_var.set(progress)
            self.status_label.config(text=f"删除进度: {idx + 1}/{len(dirs_to_delete)}")
            self.root.update_idletasks()

        self.progress_var.set(100)
        self.status_label.config(text=f"删除完成: 成功 {deleted_count} 个, 失败 {failed_count} 个")
        messagebox.showinfo("删除完成", f"成功删除 {deleted_count} 个目录\n失败 {failed_count} 个")


if __name__ == "__main__":
    root = tk.Tk()
    app = DuplicateImageCleaner(root)
    root.mainloop()