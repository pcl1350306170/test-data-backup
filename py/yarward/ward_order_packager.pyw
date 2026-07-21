# ward_order_packager.pyw - 病房订单打包工具

import os
import json
import logging
import threading
import subprocess
import shutil
import glob
from pathlib import Path
from datetime import datetime
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "ward_order_packager"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"

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
# 基础目录
CODE_BASE_DIR = Path(r"D:\CODE\Yarward\病房")
SVN_BASE_DIR = Path(r"D:\CODE\Yarward\SVN\病房")

# 项目类型与子目录映射
PROJECT_TYPE_MAP = {
    "web": "web",
    "床头": "床头",
    "床旁": "床旁",
    "护理看板": "看板",
}

# 打包产物前缀
PACKAGE_PREFIX_MAP = {
    "web": "dist",
    "床头": "bedhead",
    "床旁": "bedside",
    "护理看板": "ntv",
}

# ==============================
# 配置函数
# ==============================
DEFAULT_CONFIG = {
    "project_type": "床旁",
    "keyword": "",
    "auto_commit_svn": True,
    "history_records": [],
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(data):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


# ==============================
# Git Bash 查找
# ==============================
def find_bash_executable():
    """
    查找 bash 可执行文件路径
    优先使用 PATH 中的 bash，否则查找常见 Git Bash 安装路径
    """
    # 1. 先尝试 PATH 中的 bash
    try:
        result = subprocess.run(
            ["bash", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return "bash"
    except (FileNotFoundError, OSError):
        pass

    # 2. 查找常见 Git Bash 安装路径
    common_paths = [
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
        Path(r"D:\Program Files\Git\bin\bash.exe"),
        Path(r"D:\Git\bin\bash.exe"),
        Path(os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe")),
    ]

    for p in common_paths:
        if p.exists():
            return str(p)

    # 3. 通过注册表查找 Git 安装路径
    try:
        import winreg
        for key_path in [
            r"SOFTWARE\GitForWindows",
            r"SOFTWARE\WOW6432Node\GitForWindows",
        ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                winreg.CloseKey(key)
                bash_path = Path(install_path) / "bin" / "bash.exe"
                if bash_path.exists():
                    return str(bash_path)
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        pass

    return None


# ==============================
# Git / SVN 工具函数
# ==============================
def get_git_branch(directory):
    """获取指定目录的当前git分支名"""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(directory),
            capture_output=True, text=True, encoding='utf-8', timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
        # 兼容旧版git
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(directory),
            capture_output=True, text=True, encoding='utf-8', timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"获取git分支失败 ({directory}): {e}")
    return ""


def find_project_dirs_by_keyword(base_dir, project_subdir, keyword):
    """
    遍历 base_dir/project_subdir 下的子目录，
    找出git分支名包含keyword的目录，返回 [(目录路径, 分支名), ...]
    """
    search_dir = base_dir / project_subdir
    results = []
    if not search_dir.exists():
        return results

    for item in search_dir.iterdir():
        if not item.is_dir():
            continue
        branch = get_git_branch(item)
        if keyword.lower() in branch.lower():
            results.append((item, branch))
    return results


def find_svn_dirs_by_keyword(base_dir, keyword):
    """
    在 SVN 病房目录下模糊匹配包含关键字的子目录
    返回匹配的目录路径列表
    """
    results = []
    if not base_dir.exists():
        return results

    for item in base_dir.iterdir():
        if not item.is_dir():
            continue
        if keyword.lower() in item.name.lower():
            results.append(item)
    return results


def find_deploy_script(project_dir):
    """查找项目目录下的 deploy.sh"""
    deploy_path = project_dir / "deploy.sh"
    if deploy_path.exists():
        return deploy_path
    return None


def find_built_package(project_dir, prefix):
    """
    在项目目录的 dist 子目录下查找打包产物
    返回匹配的文件路径
    """
    dist_dir = project_dir / "dist"
    if not dist_dir.exists():
        return None

    if prefix == "dist":
        # web 类型：查找 dist.tar.gz
        target = dist_dir / "dist.tar.gz"
        if target.exists():
            return target
        # 也尝试其他格式
        for f in dist_dir.iterdir():
            if f.name.endswith('.tar.gz') or f.name.endswith('.zip'):
                return f
    else:
        # 其他类型：查找 prefix-*.tar.gz
        pattern = f"{prefix}-*.tar.gz"
        matches = sorted(dist_dir.glob(pattern))
        if matches:
            return matches[-1]  # 取最新的
        # 兜底：查找任何 tar.gz
        for f in dist_dir.iterdir():
            if f.name.endswith('.tar.gz'):
                return f
    return None


def find_svn_working_copy(start_dir):
    """从指定目录向上查找SVN工作副本根目录"""
    check_dir = Path(start_dir)
    for _ in range(5):
        if (check_dir / ".svn").exists():
            return check_dir
        parent = check_dir.parent
        if parent == check_dir:
            break
        check_dir = parent
    return None


# ==============================
# GUI
# ==============================
class WardOrderPackagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📦 病房订单打包工具")
        self.root.geometry("900x900")
        self.root.minsize(800, 700)

        self.config = load_config()
        self.is_packaging = False

        # 变量
        self.project_type = StringVar(value=self.config.get("project_type", "床旁"))
        self.keyword = StringVar(value=self.config.get("keyword", ""))
        self.auto_commit_svn = BooleanVar(value=self.config.get("auto_commit_svn", True))

        # 匹配结果
        self.matched_project_dirs = []  # [(path, branch_name), ...]
        self.matched_svn_dirs = []      # [path, ...]
        self.selected_project_dir = None
        self.selected_svn_dir = None

        self.create_widgets()
        self._log("配置已加载")

    def create_widgets(self):
        # Notebook 双标签页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # ========== 标签页1：打包配置 ==========
        config_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(config_tab, text="⚙️ 打包配置")

        # --- 项目类型 ---
        type_frame = ttk.LabelFrame(config_tab, text="📋 项目类型", padding=8)
        type_frame.pack(fill=X, pady=(0, 8))
        type_combo = ttk.Combobox(
            type_frame, textvariable=self.project_type,
            values=["web", "床头", "床旁", "护理看板"],
            state="readonly", width=15
        )
        type_combo.pack(side=LEFT, padx=5)
        ttk.Label(type_frame, text="选择需要打包的项目类型", foreground="gray").pack(side=LEFT, padx=10)

        # --- 订单关键字 ---
        kw_frame = ttk.LabelFrame(config_tab, text="🔍 订单关键字", padding=8)
        kw_frame.pack(fill=X, pady=(0, 8))
        kw_entry = ttk.Entry(kw_frame, textvariable=self.keyword, width=30)
        kw_entry.pack(side=LEFT, padx=5)
        ttk.Label(kw_frame, text="输入关键字模糊匹配git分支名和SVN目录（如：济南）", foreground="gray").pack(side=LEFT, padx=10)

        # --- 扫描按钮 ---
        scan_frame = ttk.Frame(config_tab)
        scan_frame.pack(fill=X, pady=(0, 8))
        self.btn_scan = ttk.Button(scan_frame, text="🔍 扫描匹配", command=self._start_scan)
        self.btn_scan.pack(side=LEFT, padx=(0, 10))
        ttk.Label(scan_frame, text="根据项目类型和关键字扫描匹配的项目目录和SVN目录", foreground="gray").pack(side=LEFT)

        # --- 匹配到的项目目录 ---
        proj_frame = ttk.LabelFrame(config_tab, text="📁 匹配到的项目目录（选择要打包的目录）", padding=8)
        proj_frame.pack(fill=X, pady=(0, 8))

        self.proj_listbox = Listbox(proj_frame, height=4, width=80)
        proj_scroll = ttk.Scrollbar(proj_frame, orient=VERTICAL, command=self.proj_listbox.yview)
        self.proj_listbox.config(yscrollcommand=proj_scroll.set)
        self.proj_listbox.pack(side=LEFT, fill=X, expand=True)
        proj_scroll.pack(side=RIGHT, fill=Y)
        self.proj_listbox.bind("<<ListboxSelect>>", self._on_project_selected)

        # --- 匹配到的SVN目录 ---
        svn_frame = ttk.LabelFrame(config_tab, text="💾 匹配到的SVN目录（选择目标目录）", padding=8)
        svn_frame.pack(fill=X, pady=(0, 8))

        self.svn_listbox = Listbox(svn_frame, height=4, width=80)
        svn_scroll = ttk.Scrollbar(svn_frame, orient=VERTICAL, command=self.svn_listbox.yview)
        self.svn_listbox.config(yscrollcommand=svn_scroll.set)
        self.svn_listbox.pack(side=LEFT, fill=X, expand=True)
        svn_scroll.pack(side=RIGHT, fill=Y)
        self.svn_listbox.bind("<<ListboxSelect>>", self._on_svn_selected)

        # --- SVN选项 ---
        svn_opt_frame = ttk.LabelFrame(config_tab, text="🔗 SVN选项", padding=8)
        svn_opt_frame.pack(fill=X, pady=(0, 8))
        svn_check = ttk.Checkbutton(
            svn_opt_frame,
            text="打包完成后自动提交SVN",
            variable=self.auto_commit_svn
        )
        svn_check.pack(anchor=W, pady=3)
        ttk.Label(svn_opt_frame, text="提示：会自动查找SVN工作副本根目录进行提交", foreground="gray").pack(anchor=W)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(config_tab)
        btn_frame.pack(fill=X, pady=10)
        self.btn_start = ttk.Button(btn_frame, text="🚀 开始打包", command=self._start_package)
        self.btn_start.pack(side=LEFT, padx=(0, 10))
        self.btn_save = ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config)
        self.btn_save.pack(side=LEFT)

        # ========== 标签页2：日志与历史 ==========
        log_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(log_tab, text="📝 日志与历史")

        # 打包日志
        log_frame = ttk.LabelFrame(log_tab, text="📝 打包日志", padding=5)
        log_frame.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, wrap=WORD, height=14, font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

        # 历史记录
        history_frame = ttk.LabelFrame(log_tab, text="📚 打包历史记录（最近100次）", padding=5)
        history_frame.pack(fill=X, pady=5)

        listbox_frame = ttk.Frame(history_frame)
        listbox_frame.pack(fill=X, pady=5)
        self.history_listbox = Listbox(listbox_frame, height=5, width=80)
        hist_scroll = ttk.Scrollbar(listbox_frame, orient=VERTICAL, command=self.history_listbox.yview)
        self.history_listbox.config(yscrollcommand=hist_scroll.set)
        self.history_listbox.pack(side=LEFT, fill=X, expand=True)
        hist_scroll.pack(side=RIGHT, fill=Y)
        self.history_listbox.bind('<Double-Button-1>', self._load_history_record)

        btn_hist_frame = ttk.Frame(history_frame)
        btn_hist_frame.pack(fill=X, pady=5)
        ttk.Button(btn_hist_frame, text="📥 加载选中记录", command=self._load_history_record).pack(side=LEFT, padx=5)
        ttk.Button(btn_hist_frame, text="🗑️ 删除选中记录", command=self._delete_history_record).pack(side=LEFT, padx=5)
        ttk.Label(history_frame, text="💡 提示：双击记录可恢复配置", foreground="gray").pack(anchor=W)

        # 刷新历史记录显示
        self._refresh_history_listbox()

    # ---------- 日志 ----------
    def _log(self, message):
        logger.info(message)
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        self.root.update_idletasks()

    # ---------- 扫描匹配 ----------
    def _start_scan(self):
        project_type = self.project_type.get()
        keyword = self.keyword.get().strip()

        if not keyword:
            messagebox.showwarning("提示", "请输入订单关键字！")
            return

        self._log(f"开始扫描：项目类型={project_type}，关键字={keyword}")
        self.btn_scan.config(state=DISABLED)
        threading.Thread(target=self._do_scan, args=(project_type, keyword), daemon=True).start()

    def _do_scan(self, project_type, keyword):
        try:
            def log(msg):
                self.root.after(0, lambda: self._log(msg))

            # 1. 扫描项目目录
            subdir = PROJECT_TYPE_MAP.get(project_type, project_type)
            log(f"扫描项目目录: {CODE_BASE_DIR / subdir}")
            matched_projects = find_project_dirs_by_keyword(CODE_BASE_DIR, subdir, keyword)

            if matched_projects:
                log(f"✅ 找到 {len(matched_projects)} 个匹配的项目目录:")
                for p, b in matched_projects:
                    log(f"   📁 {p.name}  (分支: {b})")
            else:
                log(f"⚠️ 未找到分支名包含 '{keyword}' 的项目目录")

            self.root.after(0, lambda: self._update_project_list(matched_projects))

            # 2. 扫描SVN目录
            log(f"扫描SVN目录: {SVN_BASE_DIR}")
            matched_svn = find_svn_dirs_by_keyword(SVN_BASE_DIR, keyword)

            if matched_svn:
                log(f"✅ 找到 {len(matched_svn)} 个匹配的SVN目录:")
                for p in matched_svn:
                    log(f"   💾 {p.name}")
            else:
                log(f"⚠️ 未找到包含 '{keyword}' 的SVN目录，请手动选择")

            self.root.after(0, lambda: self._update_svn_list(matched_svn))

            if not matched_projects and not matched_svn:
                self.root.after(0, lambda: messagebox.showwarning(
                    "未匹配到结果",
                    f"未找到匹配的项目目录和SVN目录。\n\n"
                    f"请检查：\n"
                    f"1. 代码目录: {CODE_BASE_DIR / subdir}\n"
                    f"2. SVN目录: {SVN_BASE_DIR}\n"
                    f"3. 关键字: {keyword}"
                ))

        except Exception as e:
            self.root.after(0, lambda: self._log(f"❌ 扫描出错: {e}"))
        finally:
            self.root.after(0, lambda: self.btn_scan.config(state=NORMAL))

    def _update_project_list(self, matched_projects):
        self.matched_project_dirs = matched_projects
        self.selected_project_dir = None
        self.proj_listbox.delete(0, END)
        for p, b in matched_projects:
            self.proj_listbox.insert(END, f"{p}  (分支: {b})")

    def _update_svn_list(self, matched_svn):
        self.matched_svn_dirs = matched_svn
        self.selected_svn_dir = None
        self.svn_listbox.delete(0, END)
        for p in matched_svn:
            self.svn_listbox.insert(END, str(p))

    def _on_project_selected(self, event=None):
        sel = self.proj_listbox.curselection()
        if sel and sel[0] < len(self.matched_project_dirs):
            self.selected_project_dir = self.matched_project_dirs[sel[0]][0]
            branch = self.matched_project_dirs[sel[0]][1]
            self._log(f"选中项目目录: {self.selected_project_dir} (分支: {branch})")

    def _on_svn_selected(self, event=None):
        sel = self.svn_listbox.curselection()
        if sel and sel[0] < len(self.matched_svn_dirs):
            self.selected_svn_dir = self.matched_svn_dirs[sel[0]]
            self._log(f"选中SVN目录: {self.selected_svn_dir}")

    # ---------- 开始打包 ----------
    def _start_package(self):
        if not self.selected_project_dir:
            messagebox.showerror("错误", "请先扫描并选择要打包的项目目录！")
            return
        if not self.selected_svn_dir:
            messagebox.showerror("错误", "请先扫描并选择SVN目标目录！")
            return

        # 检查 deploy.sh
        deploy_script = find_deploy_script(self.selected_project_dir)
        if not deploy_script:
            messagebox.showerror("错误", f"项目目录下未找到 deploy.sh:\n{self.selected_project_dir}")
            return

        project_type = self.project_type.get()
        self.btn_start.config(state=DISABLED)
        self.btn_scan.config(state=DISABLED)
        self.is_packaging = True

        # 切换到日志标签页
        self.notebook.select(1)

        threading.Thread(target=self._do_package, args=(project_type,), daemon=True).start()

    def _do_package(self, project_type):
        try:
            def log(msg):
                self.root.after(0, lambda: self._log(msg))

            project_dir = self.selected_project_dir
            svn_dir = self.selected_svn_dir
            prefix = PACKAGE_PREFIX_MAP.get(project_type, "dist")

            log("=" * 50)
            log(f"🚀 开始打包：项目类型={project_type}")
            log(f"📁 项目目录: {project_dir}")
            log(f"💾 SVN目录: {svn_dir}")

            # 1. 检查 deploy.sh
            deploy_script = find_deploy_script(project_dir)
            if not deploy_script:
                log("❌ 未找到 deploy.sh，停止打包")
                return
            log(f"✅ 找到 deploy.sh: {deploy_script}")

            # 2. 确定SVN操作目录（如果存在"前端"子目录则进入）
            svn_work_dir = svn_dir
            frontend_dir = svn_dir / "前端"
            if frontend_dir.exists() and frontend_dir.is_dir():
                svn_work_dir = frontend_dir
                log(f"ℹ️ 检测到'前端'子目录，后续操作在: {svn_work_dir}")
            else:
                log(f"ℹ️ 未检测到'前端'子目录，直接在: {svn_work_dir}")

            # 3. 执行 deploy.sh
            log(f"🔄 执行 deploy.sh ...")
            success = self._run_deploy_script(project_dir, deploy_script, log)
            if not success:
                log("❌ deploy.sh 执行失败，停止打包")
                return
            log("✅ deploy.sh 执行完成")

            # 4. 查找打包产物
            package_file = find_built_package(project_dir, prefix)
            if not package_file:
                log(f"❌ 未在 dist 目录下找到打包产物 ({prefix}-*.tar.gz)")
                return
            log(f"✅ 找到打包产物: {package_file.name}")

            # 5. 处理SVN目录中的旧包
            self._clean_old_packages(svn_work_dir, prefix, log)

            # 6. 剪切包到SVN目录
            target_path = svn_work_dir / package_file.name
            shutil.move(str(package_file), str(target_path))
            log(f"✅ 已将打包产物剪切到: {target_path}")

            # 7. SVN提交
            if self.auto_commit_svn.get():
                self._commit_to_svn(target_path, svn_work_dir, log)

            # 8. 添加历史记录
            branch = ""
            for p, b in self.matched_project_dirs:
                if p == project_dir:
                    branch = b
                    break
            self.root.after(0, lambda: self._add_to_history(project_type, project_dir, svn_dir, package_file.name, branch))

            log("=" * 50)
            log("🎉 打包完成！")

            # 弹窗通知
            self.root.after(0, lambda: self._show_toast(
                "打包完成",
                f"项目: {project_type}\n产物: {package_file.name}"
            ))

        except Exception as e:
            self.root.after(0, lambda: self._log(f"❌ 打包过程中出错: {e}"))
            logger.exception("Package failed")
        finally:
            self.root.after(0, self._package_finished)

    def _run_deploy_script(self, project_dir, deploy_script, log):
        """执行 deploy.sh 脚本"""
        try:
            # 查找 bash 可执行文件
            bash_path = find_bash_executable()
            if not bash_path:
                log("❌ 未找到 bash，请确保已安装 Git Bash")
                log("   常见安装路径:")
                log("   - C:\\Program Files\\Git\\bin\\bash.exe")
                log("   - D:\\Program Files\\Git\\bin\\bash.exe")
                return False

            log(f"使用 bash: {bash_path}")

            # 使用 bash 执行 deploy.sh
            process = subprocess.Popen(
                [bash_path, str(deploy_script)],
                cwd=str(project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        log(line.strip())

            # 读取剩余输出
            if process.stdout:
                remaining = process.stdout.read()
                if remaining:
                    for line in remaining.strip().split('\n'):
                        if line.strip():
                            log(line.strip())

            if process.returncode == 0:
                return True
            else:
                log(f"❌ deploy.sh 返回码: {process.returncode}")
                return False

        except Exception as e:
            log(f"❌ 执行 deploy.sh 出错: {e}")
            return False

    def _clean_old_packages(self, svn_dir, prefix, log):
        """删除SVN目录中旧的打包产物，并使用 svn delete 标记删除"""
        if prefix == "dist":
            pattern = "dist.tar.gz"
        else:
            pattern = f"{prefix}-*.tar.gz"

        for f in Path(svn_dir).glob(pattern):
            try:
                # 先尝试 svn delete 标记删除（如果文件在SVN版本控制中）
                try:
                    result = subprocess.run(
                        ["svn", "delete", str(f)],
                        cwd=str(svn_dir),
                        capture_output=True, text=True, encoding='utf-8', timeout=15
                    )
                    if result.returncode == 0:
                        log(f"🗑️ SVN标记删除旧包: {f.name}")
                    else:
                        # 文件可能不在SVN控制中，直接删除
                        f.unlink()
                        log(f"🗑️ 删除旧包: {f.name}")
                except FileNotFoundError:
                    # svn命令不存在，直接删除
                    f.unlink()
                    log(f"🗑️ 删除旧包: {f.name}")
            except Exception as e:
                log(f"⚠️ 删除旧包失败 {f.name}: {e}")

    def _commit_to_svn(self, file_path, work_dir, log):
        """提交文件到SVN（包含新增文件和已删除文件）"""
        try:
            # 查找SVN工作副本根目录
            svn_root = find_svn_working_copy(work_dir)
            if not svn_root:
                log(f"⚠️ 未找到SVN工作副本（从 {work_dir} 向上查找），跳过提交")
                return

            if svn_root != work_dir:
                log(f"ℹ️ SVN工作副本根目录: {svn_root}")

            log(f"🔄 开始提交到SVN...")

            # svn add 新文件
            try:
                result = subprocess.run(
                    ["svn", "add", str(file_path)],
                    cwd=str(svn_root),
                    capture_output=True, text=True, encoding='utf-8', timeout=30
                )
                if result.returncode == 0:
                    log(f"✅ SVN Add 成功: {file_path.name}")
                elif "already under version control" in result.stderr.lower():
                    log(f"ℹ️ 文件已在版本控制中，跳过Add")
                else:
                    log(f"⚠️ SVN Add 警告: {result.stderr.strip()}")
            except Exception as e:
                log(f"⚠️ SVN Add 出错: {e}")

            # svn commit 整个工作目录（包含新增文件和已删除文件）
            commit_msg = f"病房订单打包：{file_path.name} - {datetime.now():%Y-%m-%d %H:%M:%S}"
            result = subprocess.run(
                ["svn", "commit", "-m", commit_msg, str(work_dir)],
                cwd=str(svn_root),
                capture_output=True, text=True, encoding='utf-8', timeout=60
            )

            if result.returncode == 0:
                log(f"✅ SVN 提交成功")
                if result.stdout:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            log(f"   {line}")
            else:
                log(f"❌ SVN 提交失败: {result.stderr.strip()}")

        except FileNotFoundError:
            log("❌ 未找到svn命令，请确保已安装SVN命令行工具")
        except subprocess.TimeoutExpired:
            log("❌ SVN操作超时")
        except Exception as e:
            log(f"❌ SVN提交出错: {e}")

    def _package_finished(self):
        self.is_packaging = False
        self.btn_start.config(state=NORMAL)
        self.btn_scan.config(state=NORMAL)

    # ---------- 历史记录 ----------
    def _add_to_history(self, project_type, project_dir, svn_dir, package_name, branch=""):
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_type": project_type,
            "project_dir": str(project_dir),
            "svn_dir": str(svn_dir),
            "package_name": package_name,
            "keyword": self.keyword.get().strip(),
            "auto_commit_svn": self.auto_commit_svn.get(),
            "branch": branch,
        }

        history = self.config.get("history_records", [])
        # 去重：按项目目录+SVN目录
        key = f"{record['project_dir']}_{record['svn_dir']}"
        history = [r for r in history if f"{r.get('project_dir', '')}_{r.get('svn_dir', '')}" != key]
        history.insert(0, record)
        history = history[:100]

        self.config["history_records"] = history
        save_config(self.config)
        self._refresh_history_listbox()
        self._log(f"✅ 已添加到历史记录（当前共 {len(history)} 条）")

    def _refresh_history_listbox(self):
        self.history_listbox.delete(0, END)
        history = self.config.get("history_records", [])
        for record in history:
            text = f"[{record.get('timestamp', '')}] {record.get('project_type', '')} - {record.get('package_name', '')}"
            self.history_listbox.insert(END, text)

    def _load_history_record(self, event=None):
        sel = self.history_listbox.curselection()
        if not sel:
            return
        history = self.config.get("history_records", [])
        if sel[0] >= len(history):
            return

        record = history[sel[0]]

        # 恢复完整配置
        self.project_type.set(record.get("project_type", "床旁"))
        self.keyword.set(record.get("keyword", ""))
        self.auto_commit_svn.set(record.get("auto_commit_svn", True))

        saved_proj = record.get("project_dir", "")
        saved_svn = record.get("svn_dir", "")

        # 恢复项目目录选中
        self.selected_project_dir = None
        if saved_proj:
            found = False
            for idx in range(self.proj_listbox.size()):
                if self.proj_listbox.get(idx).startswith(saved_proj):
                    self.proj_listbox.selection_clear(0, END)
                    self.proj_listbox.selection_set(idx)
                    self.proj_listbox.see(idx)
                    self.selected_project_dir = Path(saved_proj)
                    found = True
                    break
            if not found:
                # 列表中没有该目录，直接添加显示并选中
                branch_info = f"  (分支: {record.get('branch', '')})" if record.get('branch') else ""
                self.proj_listbox.delete(0, END)
                self.proj_listbox.insert(END, f"{saved_proj}{branch_info}")
                self.proj_listbox.selection_set(0)
                self.selected_project_dir = Path(saved_proj)
                self.matched_project_dirs = [(Path(saved_proj), record.get('branch', ''))]

        # 恢复SVN目录选中
        self.selected_svn_dir = None
        if saved_svn:
            found = False
            for idx in range(self.svn_listbox.size()):
                if self.svn_listbox.get(idx).startswith(saved_svn):
                    self.svn_listbox.selection_clear(0, END)
                    self.svn_listbox.selection_set(idx)
                    self.svn_listbox.see(idx)
                    self.selected_svn_dir = Path(saved_svn)
                    found = True
                    break
            if not found:
                self.svn_listbox.delete(0, END)
                self.svn_listbox.insert(END, saved_svn)
                self.svn_listbox.selection_set(0)
                self.selected_svn_dir = Path(saved_svn)
                self.matched_svn_dirs = [Path(saved_svn)]

        self._log(f"✅ 已加载历史记录: {record.get('timestamp', '')} | {record.get('project_type', '')} | {record.get('keyword', '')}")
        self._log("ℹ️ 配置已恢复，可直接点击『🚀 开始打包』或重新扫描匹配")
        self.notebook.select(0)

    def _delete_history_record(self):
        sel = self.history_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的记录")
            return
        history = self.config.get("history_records", [])
        if sel[0] >= len(history):
            return

        record = history[sel[0]]
        if messagebox.askyesno("确认删除", f"是否删除历史记录？\n{record.get('timestamp', '')} - {record.get('project_type', '')}"):
            del history[sel[0]]
            self.config["history_records"] = history
            save_config(self.config)
            self._refresh_history_listbox()
            self._log(f"✅ 已删除历史记录")

    # ---------- 配置 ----------
    def _save_config(self):
        self.config["project_type"] = self.project_type.get()
        self.config["keyword"] = self.keyword.get().strip()
        self.config["auto_commit_svn"] = self.auto_commit_svn.get()
        save_config(self.config)
        messagebox.showinfo("成功", "配置已保存！")

    # ---------- Toast ----------
    def _show_toast(self, title, message, duration_ms=60000):
        try:
            toast = Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)
            toast.configure(bg='#2b5797', padx=2, pady=2)

            close_btn = Label(toast, text="✕", bg='#2b5797', fg='white',
                              font=('Arial', 10, 'bold'), cursor='hand2')
            close_btn.place(relx=1.0, x=-20, y=5)
            close_btn.bind('<Button-1>', lambda e: toast.destroy())

            Label(toast, text=f"📦 {title}", bg='#2b5797', fg='white',
                  font=('Microsoft YaHei UI', 12, 'bold'), anchor=W).pack(fill=X, padx=(15, 30), pady=(12, 5))
            Label(toast, text=message, bg='#2b5797', fg='#e0e0e0',
                  font=('Microsoft YaHei UI', 9), anchor=W, justify=LEFT,
                  wraplength=280).pack(fill=X, padx=(15, 15), pady=(0, 12))

            for w in [toast]:
                w.bind('<Button-1>', lambda e: toast.destroy())

            toast.update_idletasks()
            sw = toast.winfo_screenwidth()
            sh = toast.winfo_screenheight()
            x = sw - 320 - 20
            y = sh - 100 - 60
            toast.geometry(f"320x100+{x}+{y}")
            toast.deiconify()
            toast.after(duration_ms, lambda: toast.destroy() if toast.winfo_exists() else None)
        except Exception as e:
            self._log(f"弹窗通知失败: {e}")


# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = WardOrderPackagerGUI(root)
    root.mainloop()
