# git_branch_creator.pyw

import os
import subprocess
import json
import re
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime

# 配置与常量
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "git_branch_creator"
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

class GitBranchCreator:
    def __init__(self, root):
        self.root = root
        self.root.title("Git分支快速创建工具")
        self.root.geometry("800x600")
        self.root.minsize(700, 500)

        # 初始化变量
        self.git_path = self._find_git()
        self.project_path = tk.StringVar()
        self.base_branch = tk.StringVar()
        self.new_branch_name = tk.StringVar()
        self.remote_name = tk.StringVar(value="origin")
        self.current_branch = tk.StringVar()  # 新增：跟踪当前分支

        # 创建UI
        self._create_widgets()

        # 加载配置（先加载基础配置，延迟执行网络操作）
        self._load_config()
        
        # 界面显示后再执行网络操作
        self.root.after(200, self._do_initial_git_operations)

    def _find_git(self):
        """自动查找Git可执行文件路径"""
        try:
            # 尝试直接运行git命令
            subprocess.run(["git", "--version"], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return "git"
        except (subprocess.SubprocessError, FileNotFoundError):
            # 在常见路径中查找
            common_paths = [
                "C:/Program Files/Git/bin/git.exe",
                "C:/Program Files (x86)/Git/bin/git.exe",
                "/usr/bin/git",
                "/usr/local/bin/git"
            ]

            for path in common_paths:
                if os.path.exists(path):
                    return path
            return ""

    def _select_git_path(self):
        """手动选择Git路径"""
        path = filedialog.askopenfilename(
            title="选择Git可执行文件",
            filetypes=[("可执行文件", "git.exe;git"), ("所有文件", "*.*")]
        )
        if path:
            self.git_path = path
            self.git_path_var.set(path)
            self._log(f"手动选择Git路径: {path}")

    def _select_project_dir(self):
        """选择项目目录并自动拉取最新代码"""
        dir_path = filedialog.askdirectory(title="选择Git项目目录")
        if dir_path:
            if not os.path.exists(os.path.join(dir_path, ".git")):
                messagebox.showerror("错误", "所选目录不是Git仓库!")
                return

            self.project_path.set(dir_path)
            self._log(f"选择项目目录: {dir_path}")

            # 新增：选择目录后拉取最新代码
            if self._pull_latest_code():
                self._load_branches()
                self._update_current_branch()
            else:
                # 拉取失败仍加载分支，但提示用户
                self._load_branches()
                self._update_current_branch()
                messagebox.showwarning("警告", "拉取最新代码失败，但仍加载分支信息，请检查网络或仓库状态")

    def _pull_latest_code(self):
        """拉取当前分支最新代码"""
        if not self.git_path or not self.project_path.get():
            return False

        try:
            # 先获取当前分支
            current_branch = self._run_git_command(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                "获取当前分支"
            ).strip()

            if current_branch:
                # 拉取当前分支最新代码
                self._run_git_command(
                    ["pull", self.remote_name.get(), current_branch],
                    f"拉取当前分支 {current_branch} 最新代码"
                )
                self._log(f"成功拉取 {current_branch} 分支最新代码")
                return True
            else:
                self._log("无法确定当前分支，跳过拉取操作", logging.WARNING)
                return False

        except Exception as e:
            self._log(f"拉取最新代码失败: {str(e)}", logging.ERROR)
            return False

    def _load_branches(self):
        """加载分支列表"""
        if not self.git_path or not self.project_path.get():
            return

        try:
            # 先拉取最新分支信息
            self._run_git_command(["fetch"], "获取远程分支信息")

            # 获取所有本地和远程分支
            result = self._run_git_command(
                ["branch", "-a"],
                "获取分支列表"
            )

            # 解析分支信息
            branches = []
            for line in result.splitlines():
                line = line.strip()
                # 过滤掉HEAD引用和重复项
                if line.startswith("*"):
                    current_branch = line[1:].strip()
                    line = current_branch
                if "->" in line:
                    continue
                # 处理远程分支
                if line.startswith("remotes/"):
                    line = line.split("/", 2)[-1]
                if line not in branches:
                    branches.append(line)

            # 更新下拉列表
            self.branch_combobox['values'] = sorted(branches)
            if branches:
                # 优先选择当前分支作为基础分支
                if current_branch in branches:
                    self.base_branch.set(current_branch)
                else:
                    self.base_branch.set(branches[0])

        except Exception as e:
            messagebox.showerror("错误", f"加载分支失败: {str(e)}")
            self._log(f"加载分支失败: {str(e)}", logging.ERROR)

    def _update_current_branch(self):
        """更新当前分支显示"""
        if not self.git_path or not self.project_path.get():
            return

        try:
            current_branch = self._run_git_command(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                "获取当前分支"
            ).strip()
            self.current_branch.set(f"当前分支: {current_branch}")
        except Exception as e:
            self.current_branch.set("当前分支: 未知")
            self._log(f"获取当前分支失败: {str(e)}", logging.WARNING)

    def _check_existing_branches(self):
        """检查是否存在类似的分支"""
        if not self.git_path or not self.project_path.get():
            return []

        try:
            result = self._run_git_command(
                ["branch", "-a"],
                "检查已有分支"
            )

            new_branch_base = self.new_branch_name.get().strip()
            if not new_branch_base:
                return []

            similar_branches = []
            pattern = re.compile(re.escape(new_branch_base), re.IGNORECASE)

            for line in result.splitlines():
                line = line.strip().lstrip("* ")
                if "->" in line:
                    continue
                if pattern.search(line):
                    similar_branches.append(line)

            return similar_branches

        except Exception as e:
            self._log(f"检查分支失败: {str(e)}", logging.ERROR)
            return []

    def _create_branch(self):
        """创建新分支并自动切换"""
        if not self._validate_inputs():
            return

        base_branch = self.base_branch.get()
        new_branch_base = self.new_branch_name.get().strip()
        new_branch = f"{base_branch}_{new_branch_base}"

        # 检查是否有类似分支
        similar_branches = self._check_existing_branches()
        if similar_branches:
            msg = f"发现以下类似分支:\n{chr(10).join(similar_branches)}\n\n是否继续创建新分支?"
            if not messagebox.askyesno("确认", msg):
                return

        try:
            # 切换到基础分支并拉取最新代码
            self._run_git_command(["checkout", base_branch], f"切换到基础分支 {base_branch}")
            self._run_git_command(["pull", self.remote_name.get(), base_branch], f"拉取 {base_branch} 最新代码")

            # 创建并切换到新分支（新增：自动切换）
            self._run_git_command(["checkout", "-b", new_branch], f"创建并切换到新分支 {new_branch}")

            # 更新当前分支显示
            self._update_current_branch()

            messagebox.showinfo("成功", f"分支 {new_branch} 创建成功并已自动切换到此分支!")
            self._log(f"分支 {new_branch} 创建成功并切换")
            self.new_branch_name.set("")

        except Exception as e:
            messagebox.showerror("错误", f"创建分支失败: {str(e)}")
            self._log(f"创建分支失败: {str(e)}", logging.ERROR)

    def _push_branch(self):
        """推送分支到远程"""
        if not self.project_path.get():
            messagebox.showerror("错误", "请先选择项目目录!")
            return

        try:
            # 获取当前分支
            current_branch = self._run_git_command(
                ["rev-parse", "--abbrev-ref", "HEAD"],
                "获取当前分支"
            ).strip()

            if not current_branch:
                messagebox.showerror("错误", "无法获取当前分支信息!")
                return

            # 推送分支
            self._run_git_command(
                ["push", "-u", self.remote_name.get(), current_branch],
                f"推送分支 {current_branch} 到远程"
            )

            messagebox.showinfo("成功", f"分支 {current_branch} 已成功推送到远程!")
            self._log(f"分支 {current_branch} 已推送到远程")

        except Exception as e:
            messagebox.showerror("错误", f"推送分支失败: {str(e)}")
            self._log(f"推送分支失败: {str(e)}", logging.ERROR)

    def _run_git_command(self, args, action_desc):
        """运行Git命令"""
        if not self.git_path:
            raise Exception("未找到Git可执行文件，请先配置Git路径")

        try:
            result = subprocess.run(
                [self.git_path] + args,
                cwd=self.project_path.get(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or "未知错误"
                self._log(f"{action_desc} 失败: {error_msg}", logging.ERROR)
                raise Exception(error_msg)

            self._log(f"{action_desc} 成功")
            return result.stdout

        except Exception as e:
            self._log(f"{action_desc} 出错: {str(e)}", logging.ERROR)
            raise

    def _validate_inputs(self):
        """验证输入"""
        if not self.git_path:
            messagebox.showerror("错误", "请先配置Git路径!")
            return False

        if not self.project_path.get():
            messagebox.showerror("错误", "请选择项目目录!")
            return False

        if not self.base_branch.get():
            messagebox.showerror("错误", "请选择基础分支!")
            return False

        if not self.new_branch_name.get().strip():
            messagebox.showerror("错误", "请输入新分支名称!")
            return False

        return True

    def _log(self, message, level=logging.INFO):
        """记录日志并更新UI"""
        logging.log(level, message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _save_config(self):
        """保存配置"""
        config = {
            "git_path": self.git_path,
            "last_project_path": self.project_path.get(),
            "remote_name": self.remote_name.get()
        }

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log("配置已保存")
        except Exception as e:
            self._log(f"保存配置失败: {str(e)}", logging.ERROR)

    def _do_initial_git_operations(self):
        """界面显示后执行初始Git操作（避免阻塞界面）"""
        if self.project_path.get() and os.path.exists(os.path.join(self.project_path.get(), ".git")):
            self._log("开始拉取最新代码...")
            if self._pull_latest_code():
                self._load_branches()
                self._update_current_branch()
            else:
                self._load_branches()
                self._update_current_branch()
                self._log("拉取最新代码失败，请检查网络或仓库状态", logging.WARNING)

    def _load_config(self):
        """加载配置（仅加载本地配置，不执行网络操作）"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if "git_path" in config:
                    self.git_path = config["git_path"]
                    self.git_path_var.set(self.git_path)

                if "last_project_path" in config and os.path.exists(config["last_project_path"]):
                    self.project_path.set(config["last_project_path"])
                    # 不在这里执行拉取操作，由 _do_initial_git_operations 延迟执行

                if "remote_name" in config:
                    self.remote_name.set(config["remote_name"])

                self._log("配置已加载")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

    def _create_widgets(self):
        """创建UI组件"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Git路径配置
        git_frame = ttk.LabelFrame(main_frame, text="Git配置", padding="5")
        git_frame.pack(fill=tk.X, pady=5)

        self.git_path_var = tk.StringVar(value=self.git_path)
        ttk.Label(git_frame, text="Git路径:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(git_frame, textvariable=self.git_path_var, width=50).grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(git_frame, text="浏览...", command=self._select_git_path).grid(row=0, column=2, padx=5, pady=5)

        git_frame.columnconfigure(1, weight=1)

        # 项目路径选择
        project_frame = ttk.LabelFrame(main_frame, text="项目配置", padding="5")
        project_frame.pack(fill=tk.X, pady=5)

        ttk.Label(project_frame, text="项目目录:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(project_frame, textvariable=self.project_path, width=50).grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(project_frame, text="浏览...", command=self._select_project_dir).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(project_frame, text="远程仓库名:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(project_frame, textvariable=self.remote_name, width=20).grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        # 新增：显示当前分支
        ttk.Label(project_frame, textvariable=self.current_branch).grid(row=1, column=2, padx=5, pady=5, sticky=tk.E)

        project_frame.columnconfigure(1, weight=1)

        # 分支配置
        branch_frame = ttk.LabelFrame(main_frame, text="分支配置", padding="5")
        branch_frame.pack(fill=tk.X, pady=5)

        ttk.Label(branch_frame, text="基础分支:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.branch_combobox = ttk.Combobox(branch_frame, textvariable=self.base_branch, width=47)
        self.branch_combobox.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(branch_frame, text="刷新分支", command=self._load_branches).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(branch_frame, text="新分支名称:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Entry(branch_frame, textvariable=self.new_branch_name, width=50).grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(branch_frame, text="检查类似分支", command=self._check_and_show_similar).grid(row=1, column=2, padx=5, pady=5)

        branch_frame.columnconfigure(1, weight=1)

        # 操作按钮
        button_frame = ttk.Frame(main_frame, padding="5")
        button_frame.pack(fill=tk.X, pady=5)

        ttk.Button(button_frame, text="创建分支", command=self._create_branch).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="推送分支到远程", command=self._push_branch).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="拉取最新代码", command=self._pull_latest_code_and_refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=5)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _check_and_show_similar(self):
        """检查并显示类似分支"""
        similar = self._check_existing_branches()
        if similar:
            messagebox.showinfo("类似分支", f"发现以下类似分支:\n{chr(10).join(similar)}")
        else:
            messagebox.showinfo("检查结果", "未发现类似分支")

    def _pull_latest_code_and_refresh(self):
        """拉取最新代码并刷新分支列表"""
        if self._pull_latest_code():
            self._load_branches()
            self._update_current_branch()
            messagebox.showinfo("成功", "已拉取最新代码并刷新分支列表")
        else:
            messagebox.showerror("失败", "拉取最新代码失败，请查看日志")

if __name__ == "__main__":
    root = tk.Tk()
    app = GitBranchCreator(root)
    root.mainloop()
