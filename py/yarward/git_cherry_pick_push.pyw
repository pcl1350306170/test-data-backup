# git_cherry_pick_push.pyw

import os
import json
import logging
import subprocess
import sys
from pathlib import Path
from tkinter import *
from tkinter import messagebox, ttk, filedialog

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "git_cherry_pick_push"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOGS_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# 默认配置
DEFAULT_CONFIG = {
    "target_commit": "710548f5ed90a1d60123af04b45c061c642bee5f",
    "branch_keyword": "1.5.1"
}

# ==============================
# Git 工具函数（安全 UTF-8）
# ==============================
def run_git_command(args, cwd=None, check=False):
    """执行 git 命令，返回 (success: bool, output: str)"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        if result.returncode == 0:
            return True, (result.stdout.strip() if result.stdout else "")
        else:
            err = result.stderr.strip() if result.stderr else "Unknown error"
            if check:
                raise RuntimeError(err)
            return False, err
    except FileNotFoundError:
        return False, "❌ Git 未安装或不在系统 PATH 中"
    except subprocess.TimeoutExpired:
        return False, "⚠️ Git 命令超时"
    except Exception as e:
        return False, f"执行异常: {e}"

def get_matching_remote_branches(keyword, cwd=None):
    """获取远程包含 keyword 的分支名列表"""
    success, output = run_git_command(["ls-remote", "--heads", "origin"], cwd=cwd)
    if not success:
        logger.error(f"无法获取远程分支: {output}")
        return []
    branches = []
    for line in output.splitlines():
        if '\t' in line:
            _, ref = line.split('\t', 1)
            if ref.startswith("refs/heads/") and keyword in ref:
                branch_name = ref.replace("refs/heads/", "")
                branches.append(branch_name)
    return branches

def cherry_pick_to_branch(target_branch, commit_hash, cwd=None):
    """将 commit_hash cherry-pick 到 target_branch 并推送"""
    temp_branch = f"temp_cherry_{target_branch.replace('/', '_').replace('.', '_')}"

    try:
        # 1. 获取最新远程信息
        run_git_command(["fetch", "origin"], cwd=cwd, check=True)

        # 2. 检出目标分支的最新状态到临时分支
        run_git_command(["checkout", "-B", temp_branch, f"origin/{target_branch}"], cwd=cwd, check=True)

        # 3. 执行 cherry-pick
        success, output = run_git_command(["cherry-pick", commit_hash], cwd=cwd)
        if not success:
            if "conflict" in output.lower() or "CONFLICT" in output:
                raise RuntimeError(f"Cherry-pick 冲突，请手动解决后继续。错误:\n{output}")
            else:
                raise RuntimeError(f"Cherry-pick 失败: {output}")

        # 4. 推送到远程（直接指定 refspec，避免本地分支干扰）
        run_git_command(["push", "origin", f"{temp_branch}:{target_branch}"], cwd=cwd, check=True)

        return True, "推送成功"

    finally:
        # 5. 清理：尝试切回 main/master 并删除临时分支
        try:
            run_git_command(["checkout", "main"], cwd=cwd)
        except:
            try:
                run_git_command(["checkout", "master"], cwd=cwd)
            except:
                pass  # 忽略
        run_git_command(["branch", "-D", temp_branch], cwd=cwd)

# ==============================
# GUI 主类
# ==============================
class GitCherryPickGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🍒 Git 安全 Cherry-Pick 推送工具")
        self.root.geometry("580x380")
        self.root.resizable(False, False)

        self.config = self.load_config()
        self.setup_ui()

    def load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    for k, v in DEFAULT_CONFIG.items():
                        if k not in cfg:
                            cfg[k] = v
                    return cfg
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
        return DEFAULT_CONFIG.copy()

    def save_config(self, commit, keyword):
        self.config["target_commit"] = commit.strip()
        self.config["branch_keyword"] = keyword.strip()
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def setup_ui(self):
        frame_repo = LabelFrame(self.root, text="📂 Git 仓库路径", padx=10, pady=8)
        frame_repo.pack(fill=X, padx=10, pady=5)
        self.repo_path_var = StringVar(value=str(Path.cwd()))
        Entry(frame_repo, textvariable=self.repo_path_var, font=("Consolas", 9), state='readonly').pack(fill=X)
        Button(frame_repo, text="📁 选择仓库", command=self.select_repo).pack(pady=(5,0))

        frame_commit = LabelFrame(self.root, text="🔖 目标 Commit SHA（仅此一次变更）", padx=10, pady=8)
        frame_commit.pack(fill=X, padx=10, pady=5)
        self.commit_var = StringVar(value=self.config["target_commit"])
        Entry(frame_commit, textvariable=self.commit_var, font=("Consolas", 10)).pack(fill=X)

        frame_keyword = LabelFrame(self.root, text="🔍 分支关键词（包含此字符串的远程分支将被更新）", padx=10, pady=8)
        frame_keyword.pack(fill=X, padx=10, pady=5)
        self.keyword_var = StringVar(value=self.config["branch_keyword"])
        Entry(frame_keyword, textvariable=self.keyword_var, font=("Consolas", 10)).pack(fill=X)

        btn_frame = Frame(self.root)
        btn_frame.pack(pady=15)
        Button(btn_frame, text="💾 保存配置", command=self.save_config_action, bg="#4CAF50", fg="white", width=12).pack(side=LEFT, padx=5)
        self.exec_btn = Button(btn_frame, text="🍒 执行 Cherry-Pick", command=self.execute_cherry_pick, bg="#FF9800", fg="white", width=18, height=2)
        self.exec_btn.pack(side=LEFT, padx=5)

        log_frame = LabelFrame(self.root, text="📋 操作日志", padx=5, pady=5)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.log_text = Text(log_frame, height=8, state=DISABLED, wrap=WORD, font=("Consolas", 9))
        scrollbar = Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.status_var = StringVar(value="就绪")
        Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue").pack(side=BOTTOM, fill=X)

    def select_repo(self):
        folder = filedialog.askdirectory(title="选择 Git 仓库根目录", initialdir=self.repo_path_var.get())
        if folder:
            self.repo_path_var.set(folder)

    def log_msg(self, msg):
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        logger.info(msg)

    def save_config_action(self):
        commit = self.commit_var.get().strip()
        keyword = self.keyword_var.get().strip()
        if not commit or not keyword:
            messagebox.showwarning("输入错误", "Commit 和分支关键词不能为空！")
            return
        self.save_config(commit, keyword)
        self.log_msg("✅ 配置已保存")

    def execute_cherry_pick(self):
        repo_path = self.repo_path_var.get().strip()
        commit = self.commit_var.get().strip()
        keyword = self.keyword_var.get().strip()

        if not Path(repo_path).exists():
            messagebox.showerror("错误", "仓库路径不存在！")
            return
        if not commit or len(commit) < 7:
            messagebox.showerror("错误", "请提供有效的 Commit SHA！")
            return
        if not keyword:
            messagebox.showerror("错误", "分支关键词不能为空！")
            return

        self.save_config(commit, keyword)

        self.exec_btn.config(state=DISABLED)
        self.log_msg("开始执行 Cherry-Pick 推送...")

        try:
            remote_branches = get_matching_remote_branches(keyword, cwd=repo_path)
            if not remote_branches:
                self.log_msg("⚠️ 未找到匹配的远程分支")
                messagebox.showinfo("提示", "未找到包含关键词的远程分支。")
                return

            self.log_msg(f"🎯 将向以下分支 cherry-pick 提交 {commit[:8]}:")
            for b in remote_branches:
                self.log_msg(f"  - {b}")

            failed_branches = []
            for branch in remote_branches:
                self.status_var.set(f"处理 {branch} ...")
                self.log_msg(f"➡️ 开始处理 {branch}")
                try:
                    success, msg = cherry_pick_to_branch(branch, commit, cwd=repo_path)
                    if success:
                        self.log_msg(f"✅ {branch} 更新成功")
                    else:
                        raise RuntimeError(msg)
                except Exception as e:
                    err_msg = f"❌ {branch} 失败: {e}"
                    self.log_msg(err_msg)
                    failed_branches.append(branch)

            if failed_branches:
                messagebox.showerror("部分失败", f"以下分支处理失败:\n{', '.join(failed_branches)}\n\n详情见日志。")
            else:
                messagebox.showinfo("成功", f"✅ 所有匹配分支已成功应用提交 {commit[:8]}！")

        except Exception as e:
            self.log_msg(f"💥 全局错误: {e}")
            messagebox.showerror("错误", str(e))
        finally:
            self.exec_btn.config(state=NORMAL)
            self.status_var.set("操作完成")

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                _ = json.load(f)
        except:
            pass

    root = Tk()
    app = GitCherryPickGUI(root)
    root.mainloop()
