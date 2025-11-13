import os
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import configparser

class ScriptLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("脚本启动器")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        # 配置文件路径
        self.config_path = "script_launcher.ini"

        # 加载配置
        self.config = configparser.ConfigParser()
        self.load_config()

        # 创建UI
        self.create_widgets()

        # 加载脚本列表
        self.load_scripts()

    def load_config(self):
        """加载配置文件，获取Python路径和脚本目录"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding="utf-8")
            self.python_path = self.config.get("Settings", "python_path", fallback="python")
            self.script_dir = self.config.get("Settings", "script_dir", fallback=".")
        else:
            self.python_path = "python"
            self.script_dir = "."

        # 确保路径有效
        if not os.path.isfile(self.python_path) and not self.is_command_available(self.python_path):
            self.python_path = self.select_python_path()

        if not os.path.isdir(self.script_dir):
            self.script_dir = filedialog.askdirectory(title="选择脚本目录") or "."

        # 保存配置
        self.save_config()

    def save_config(self):
        """保存配置到文件"""
        if not self.config.has_section("Settings"):
            self.config.add_section("Settings")

        self.config.set("Settings", "python_path", self.python_path)
        self.config.set("Settings", "script_dir", self.script_dir)

        with open(self.config_path, "w", encoding="utf-8") as f:
            self.config.write(f)

    def is_command_available(self, cmd):
        """检查命令是否可在系统中执行"""
        try:
            subprocess.run([cmd, "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def select_python_path(self):
        """让用户选择Python解释器路径"""
        messagebox.showinfo("提示", "未找到有效的Python解释器，请选择Python.exe的路径")
        path = filedialog.askopenfilename(
            title="选择Python解释器",
            filetypes=[("Python Executable", "python.exe")]
        )
        return path if path else "python"

    def create_widgets(self):
        """创建UI组件"""
        # 顶部配置区域
        config_frame = ttk.Frame(self.root, padding="10")
        config_frame.pack(fill=tk.X)

        ttk.Label(config_frame, text="Python路径:").pack(side=tk.LEFT, padx=5)
        self.python_path_var = tk.StringVar(value=self.python_path)
        ttk.Entry(config_frame, textvariable=self.python_path_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(config_frame, text="浏览...", command=self.browse_python).pack(side=tk.LEFT, padx=5)

        ttk.Label(config_frame, text="脚本目录:").pack(side=tk.LEFT, padx=5)
        self.script_dir_var = tk.StringVar(value=self.script_dir)
        ttk.Entry(config_frame, textvariable=self.script_dir_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(config_frame, text="浏览...", command=self.browse_script_dir).pack(side=tk.LEFT, padx=5)

        ttk.Button(config_frame, text="刷新脚本列表", command=self.refresh_scripts).pack(side=tk.LEFT, padx=5)

        # 脚本列表区域
        list_frame = ttk.Frame(self.root, padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True)

        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 脚本列表
        self.script_tree = ttk.Treeview(list_frame, yscrollcommand=scrollbar.set, columns=("name", "path"), show="headings")
        self.script_tree.heading("name", text="脚本名称")
        self.script_tree.heading("path", text="脚本路径")
        self.script_tree.column("name", width=300)
        self.script_tree.column("path", width=400)
        self.script_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar.config(command=self.script_tree.yview)

        # 绑定双击事件
        self.script_tree.bind("<Double-1>", self.run_selected_script)

        # 底部按钮区域
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="执行选中脚本", command=self.run_selected_script).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="添加脚本描述", command=self.add_script_description).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="退出", command=self.root.quit).pack(side=tk.RIGHT, padx=5)

    def browse_python(self):
        """浏览选择Python路径"""
        path = filedialog.askopenfilename(
            title="选择Python解释器",
            filetypes=[("Python Executable", "python.exe")]
        )
        if path:
            self.python_path_var.set(path)
            self.python_path = path
            self.save_config()

    def browse_script_dir(self):
        """浏览选择脚本目录"""
        dir_path = filedialog.askdirectory(title="选择脚本目录")
        if dir_path:
            self.script_dir_var.set(dir_path)
            self.script_dir = dir_path
            self.save_config()
            self.load_scripts()

    def refresh_scripts(self):
        """刷新脚本列表"""
        self.python_path = self.python_path_var.get()
        self.script_dir = self.script_dir_var.get()
        self.save_config()
        self.load_scripts()

    def load_scripts(self):
        """加载脚本目录中的所有Python脚本（过滤包含【废弃】的描述）"""
        # 清空现有列表
        for item in self.script_tree.get_children():
            self.script_tree.delete(item)

        # 读取脚本描述配置
        script_descriptions = {}
        if self.config.has_section("Descriptions"):
            script_descriptions = dict(self.config.items("Descriptions"))

        # 遍历目录加载脚本
        try:
            for root, _, files in os.walk(self.script_dir):
                for file in files:
                    if file.endswith(".py"):
                        script_path = os.path.join(root, file)
                        relative_path = os.path.relpath(script_path, self.script_dir)

                        # 获取描述，如果没有则使用文件名
                        description = script_descriptions.get(relative_path, os.path.splitext(file)[0])

                        # 过滤包含【废弃】的描述
                        if "【废弃】" in description:
                            continue

                        self.script_tree.insert("", tk.END, values=(description, relative_path))
        except Exception as e:
            messagebox.showerror("错误", f"加载脚本失败: {str(e)}")

    def run_selected_script(self, event=None):
        """执行选中的脚本"""
        selected_items = self.script_tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先选择一个脚本")
            return

        selected_item = selected_items[0]
        script_name = self.script_tree.item(selected_item, "values")[0]
        script_relative_path = self.script_tree.item(selected_item, "values")[1]
        script_path = os.path.join(self.script_dir, script_relative_path)

        if not os.path.exists(script_path):
            messagebox.showerror("错误", f"脚本不存在: {script_path}")
            return

        try:
            # 打开新窗口显示脚本输出
            output_window = tk.Toplevel(self.root)
            output_window.title(f"执行: {script_name}")
            output_window.geometry("800x600")

            # 输出文本框
            output_text = tk.Text(output_window, wrap=tk.WORD)
            output_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # 滚动条
            scrollbar = ttk.Scrollbar(output_text, command=output_text.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            output_text.config(yscrollcommand=scrollbar.set)

            # 执行脚本
            output_text.insert(tk.END, f"正在执行脚本: {script_name}\n")
            output_text.insert(tk.END, f"脚本路径: {script_path}\n\n")
            output_text.update()

            process = subprocess.Popen(
                [self.python_path, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1
            )

            # 实时显示输出
            def update_output():
                if process.poll() is None:
                    line = process.stdout.readline()
                    if line:
                        output_text.insert(tk.END, line)
                        output_text.see(tk.END)
                    output_window.after(100, update_output)
                else:
                    output_text.insert(tk.END, f"\n脚本执行完成，退出代码: {process.returncode}")
                    output_text.see(tk.END)

            update_output()

        except Exception as e:
            messagebox.showerror("错误", f"执行脚本失败: {str(e)}")

    def add_script_description(self):
        """为选中的脚本添加描述"""
        selected_items = self.script_tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先选择一个脚本")
            return

        selected_item = selected_items[0]
        script_relative_path = self.script_tree.item(selected_item, "values")[1]
        current_desc = self.script_tree.item(selected_item, "values")[0]

        # 创建输入对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("添加脚本描述")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="请输入脚本描述:").pack(padx=10, pady=10, anchor=tk.W)

        desc_var = tk.StringVar(value=current_desc)
        desc_entry = ttk.Entry(dialog, textvariable=desc_var, width=50)
        desc_entry.pack(padx=10, pady=5, fill=tk.X)
        desc_entry.focus_set()

        def save_description():
            description = desc_var.get().strip()
            if description:
                if not self.config.has_section("Descriptions"):
                    self.config.add_section("Descriptions")
                self.config.set("Descriptions", script_relative_path, description)
                self.save_config()
                self.script_tree.item(selected_item, values=(description, script_relative_path))
                dialog.destroy()

        ttk.Button(dialog, text="保存", command=save_description).pack(pady=10)

        # 按Enter键保存
        dialog.bind("<Return>", lambda e: save_description())

if __name__ == "__main__":
    root = tk.Tk()
    app = ScriptLauncher(root)
    root.mainloop()
