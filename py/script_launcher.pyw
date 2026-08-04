# script_launcher.py
import os
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import configparser
import sys

class ScriptLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("脚本启动器")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        # 配置文件路径（基于脚本所在目录，避免运行目录不同导致读错文件）
        self.script_dir_base = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.script_dir_base, "script_launcher.ini")

        # 加载配置
        self.config = configparser.ConfigParser()
        self.load_config()

        # 创建UI
        self.create_widgets()

        # Java服务状态
        self.java_service_running = False
        self.java_service_process = None

        # 加载脚本列表
        self.load_scripts()

        # 定时检查Java服务状态
        self.check_java_service_status()

    def load_config(self):
        """加载配置文件，获取Python路径和脚本目录"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding="utf-8")
            self.python_path = self.config.get("Settings", "python_path", fallback="python")
            self.script_dir = self.config.get("Settings", "script_dir", fallback=".")
        else:
            self.python_path = "python"
            self.script_dir = "."

        # 加载使用频率统计，规范化key
        self.usage_counts = {}
        if self.config.has_section("UsageCount"):
            for key, value in self.config.items("UsageCount"):
                try:
                    self.usage_counts[key.replace("/", "\\").lower()] = int(value)
                except ValueError:
                    self.usage_counts[key.replace("/", "\\").lower()] = 0

        # 确保路径有效
        if not os.path.isabs(self.script_dir):
            self.script_dir = os.path.normpath(os.path.join(self.script_dir_base, self.script_dir))
        if not os.path.isfile(self.python_path) and not self.is_command_available(self.python_path):
            self.python_path = self.select_python_path()
        if not os.path.isdir(self.script_dir):
            self.script_dir = filedialog.askdirectory(title="选择脚本目录") or self.script_dir_base

        # 保存配置
        self.save_config()

    def save_config(self):
        """保存配置到文件"""
        if not self.config.has_section("Settings"):
            self.config.add_section("Settings")
        self.config.set("Settings", "python_path", self.python_path)
        self.config.set("Settings", "script_dir", self.script_dir)
        # 保存使用频率
        if not self.config.has_section("UsageCount"):
            self.config.add_section("UsageCount")
        for key, value in self.usage_counts.items():
            self.config.set("UsageCount", key, str(value))
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

        # 使用 Treeview 的分层模式
        self.script_tree = ttk.Treeview(list_frame, yscrollcommand=scrollbar.set, columns=("path", "type"), show="tree headings")
        self.script_tree.heading("#0", text="脚本名称")
        self.script_tree.heading("path", text="脚本路径")
        self.script_tree.heading("type", text="类型")

        self.script_tree.column("#0", width=300)
        self.script_tree.column("path", width=350)
        self.script_tree.column("type", width=80)

        self.script_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.script_tree.yview)

        # 绑定双击事件
        self.script_tree.bind("<Double-1>", self.run_selected_script)

        # 底部按钮区域
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="执行选中脚本", command=self.run_selected_script).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="添加脚本描述", command=self.add_script_description).pack(side=tk.LEFT, padx=5)
        self.java_service_btn = ttk.Button(btn_frame, text="启动Java服务", command=self.start_java_service)
        self.java_service_btn.pack(side=tk.LEFT, padx=5)
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

    def parse_category_and_name(self, desc):
        """从描述中解析大类和名称，例如 '【爬虫：爬取v】' -> ('爬虫', '爬取v')"""
        if desc.startswith("【") and "：" in desc and desc.endswith("】"):
            inner = desc[1:-1]  # 去掉首尾【】
            if "：" in inner:
                parts = inner.split("：", 1)
                category = parts[0].strip()
                name = parts[1].strip()
                return category, name
        # 默认归为未分类，名称用原描述
        return "未分类", desc

    def load_scripts(self):
        """加载脚本目录中的所有Python脚本（.py 和 .pyw），过滤包含【废弃】的描述，并按大类分组"""
        # 清空现有列表
        for item in self.script_tree.get_children():
            self.script_tree.delete(item)

        # 读取脚本描述配置，规范化key（统一为小写+反斜杠）
        script_descriptions = {}
        if self.config.has_section("Descriptions"):
            for key, value in self.config.items("Descriptions"):
                script_descriptions[key.replace("/", "\\").lower()] = value

        # 收集所有脚本并分组
        scripts_by_category = {}

        try:
            for root, _, files in os.walk(self.script_dir):
                for file in files:
                    if file.endswith((".py", ".pyw")):
                        script_path = os.path.join(root, file)
                        relative_path = os.path.relpath(script_path, self.script_dir)
                        # 规范化路径用于匹配描述
                        norm_path = relative_path.replace("/", "\\").lower()
                        description = script_descriptions.get(norm_path, os.path.splitext(file)[0])

                        # 过滤包含【废弃】的描述
                        if "【废弃】" in description:
                            continue

                        # 获取文件类型
                        file_type = "PYW" if file.endswith(".pyw") else "PY"

                        # 解析大类和显示名
                        category, display_name = self.parse_category_and_name(description)

                        if category not in scripts_by_category:
                            scripts_by_category[category] = []
                        scripts_by_category[category].append((display_name, relative_path, file_type))
        except Exception as e:
            messagebox.showerror("错误", f"加载脚本失败: {str(e)}")
            return

        # 按使用频率排序分类（频率高的靠前），同频率按名称排序
        category_freq = {}
        for category, scripts in scripts_by_category.items():
            total_freq = sum(self.usage_counts.get(rel_path.replace("/", "\\").lower(), 0) for _, rel_path, _ in scripts)
            category_freq[category] = total_freq

        sorted_categories = sorted(scripts_by_category.keys(), key=lambda c: (-category_freq[c], c))

        # 插入分组节点和子项
        for category in sorted_categories:
            category_id = self.script_tree.insert("", tk.END, text=category, open=True)
            # 分类内按使用频率排序（频率高的靠前），同频率按名称排序
            sorted_scripts = sorted(scripts_by_category[category], key=lambda x: (-self.usage_counts.get(x[1].replace("/", "\\").lower(), 0), x[0]))
            for display_name, rel_path, ftype in sorted_scripts:
                count = self.usage_counts.get(rel_path.replace("/", "\\").lower(), 0)
                suffix = f"  [{count}次]" if count > 0 else ""
                self.script_tree.insert(category_id, tk.END, values=(rel_path, ftype), text=display_name + suffix)

    def run_selected_script(self, event=None):
        """执行选中的脚本（隐藏黑框）"""
        selected_items = self.script_tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先选择一个脚本")
            return

        selected_item = selected_items[0]
        parent = self.script_tree.parent(selected_item)

        # 如果选中的是分类节点（父节点），不执行
        if not parent:
            messagebox.showwarning("提示", "请选择具体的脚本，而非分类")
            return

        script_name = self.script_tree.item(selected_item, "text")
        script_relative_path = self.script_tree.item(selected_item, "values")[0]
        script_type = self.script_tree.item(selected_item, "values")[1]

        script_path = os.path.join(self.script_dir, script_relative_path)
        if not os.path.exists(script_path):
            messagebox.showerror("错误", f"脚本不存在: {script_path}")
            return

        try:
            # 构建 Popen 参数
            popen_args = [self.python_path, script_path]

            # Windows 下隐藏控制台窗口
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            # 记录使用频率
            norm_path = script_relative_path.replace("/", "\\").lower()
            if norm_path not in self.usage_counts:
                self.usage_counts[norm_path] = 0
            self.usage_counts[norm_path] += 1
            self.save_config()

            # 直接后台执行，不显示任何窗口
            subprocess.Popen(
                popen_args,
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # 刷新列表以反映最新使用频率排序
            self.load_scripts()
            self.root.update()

        except Exception as e:
            messagebox.showerror("错误", f"执行脚本失败: {str(e)}")

    def check_java_service_status(self):
        """定时检查Java服务是否正在运行（通过检测cmd.exe是否运行start-base-service.bat）"""
        try:
            result = subprocess.run(
                ['wmic', 'process', 'where',
                 "name='cmd.exe' and commandline like '%start-base-service.bat%'",
                 'get', 'processid'],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            # 如果输出中包含数字PID（排除空行和标题行），说明服务正在运行
            lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip() and line.strip() != 'ProcessId']
            is_running = len(lines) > 0
        except Exception:
            is_running = False

        self.java_service_running = is_running
        if is_running:
            self.java_service_btn.config(text="停止Java服务")
        else:
            self.java_service_btn.config(text="启动Java服务")

        # 每3秒检查一次
        self.root.after(3000, self.check_java_service_status)

    def start_java_service(self):
        """根据当前状态直接启动或停止Java服务"""
        if self.java_service_running:
            self.stop_java_service()
        else:
            self.launch_java_service()

    def launch_java_service(self):
        """启动Java服务"""
        bat_path = r"C:\Users\PCL13\Desktop\start-base-service.bat"
        if not os.path.exists(bat_path):
            messagebox.showerror("错误", f"批处理文件不存在: {bat_path}")
            return
        try:
            self.java_service_process = subprocess.Popen(
                [bat_path],
                cwd=os.path.dirname(bat_path),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            self.java_service_running = True
            self.java_service_btn.config(text="停止Java服务")
        except Exception as e:
            messagebox.showerror("错误", f"启动Java服务失败: {str(e)}")

    def stop_java_service(self):
        """停止Java服务（终止运行start-base-service.bat的cmd.exe进程树）"""
        try:
            # 先尝试终止我们通过Popen启动的进程
            if self.java_service_process and self.java_service_process.poll() is None:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(self.java_service_process.pid)],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.java_service_process = None

            # 通过wmic查找运行start-base-service.bat的cmd.exe进程并终止
            result = subprocess.run(
                ['wmic', 'process', 'where',
                 "name='cmd.exe' and commandline like '%start-base-service.bat%'",
                 'get', 'processid'],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.strip().split('\n'):
                pid = line.strip()
                if pid and pid.isdigit():
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', pid],
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )

            self.java_service_running = False
            self.java_service_btn.config(text="启动Java服务")
        except Exception as e:
            messagebox.showerror("错误", f"停止Java服务失败: {str(e)}")

    def add_script_description(self):
        """为选中的脚本添加描述"""
        selected_items = self.script_tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先选择一个脚本")
            return

        selected_item = selected_items[0]
        parent = self.script_tree.parent(selected_item)
        if not parent:
            messagebox.showwarning("提示", "请选择具体的脚本，而非分类")
            return

        script_relative_path = self.script_tree.item(selected_item, "values")[0]
        current_desc = self.script_tree.item(selected_item, "text")
        # 去掉使用频率后缀 如 "  [3次]"
        if "  [" in current_desc and current_desc.endswith("次]"):
            current_desc = current_desc[:current_desc.rfind("  [")]

        # 尝试还原原始描述（含大类）
        original_desc = current_desc
        category_node_text = self.script_tree.item(parent, "text")
        if category_node_text != "未分类":
            original_desc = f"【{category_node_text}：{current_desc}】"

        # 创建输入对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("添加脚本描述")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="请输入脚本描述（支持【大类：名称】格式）:").pack(padx=10, pady=10, anchor=tk.W)
        desc_var = tk.StringVar(value=original_desc)
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
                dialog.destroy()
                self.load_scripts()  # 重新加载以反映新分组

        ttk.Button(dialog, text="保存", command=save_description).pack(pady=10)
        dialog.bind("<Return>", lambda e: save_description())

if __name__ == "__main__":
    root = tk.Tk()
    app = ScriptLauncher(root)
    root.mainloop()
