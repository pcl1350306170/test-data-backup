# menz_order_packager.pyw - 门诊订单打包工具

import os
import json
import logging
import threading
import subprocess
import shutil
import zipfile
import re
from pathlib import Path
from datetime import datetime
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "menz_order_packager"
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

# ================== 尝试导入 pypinyin ==================
try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False

# 基础目录（可修改）
SVN_BASE_DIR = Path(r"D:\CODE\Yarward\SVN\0门诊")
GIT_BASE_DIR = Path(r"D:\CODE\Yarward\门诊")

DEFAULT_CONFIG = {
    "svn_base_dir": str(SVN_BASE_DIR),
    "git_base_dir": str(GIT_BASE_DIR),
    "keyword": "",
    "auto_commit_svn": True,
    "is_version_155_plus": False,
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
# Git / SVN 工具函数
# ==============================
def get_git_branch(directory):
    """获取指定目录的当前git分支名"""
    _no_window = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(directory),
            capture_output=True, text=True, encoding='utf-8', timeout=10,
            creationflags=_no_window
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(directory),
            capture_output=True, text=True, encoding='utf-8', timeout=10,
            creationflags=_no_window
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"获取git分支失败 ({directory}): {e}")
    return ""


def find_svn_dirs_by_keyword(base_dir, keyword):
    """在SVN目录下模糊匹配包含关键字的子目录（含子目录的子目录）"""
    results = []
    if not base_dir.exists():
        return results
    for item in base_dir.iterdir():
        if item.is_dir() and keyword.lower() in item.name.lower():
            results.append(item)
    return results


def find_git_dirs_by_keyword(base_dir, keyword):
    """遍历Git基础目录的子目录，找出git分支名包含keyword的项目目录"""
    results = []
    if not base_dir.exists():
        return results
    for item in base_dir.iterdir():
        if not item.is_dir():
            continue
        branch = get_git_branch(item)
        if keyword.lower() in branch.lower():
            results.append((item, branch))
    return results


def find_base_zip_in_svn_dir(svn_dir):
    """在SVN目录及其子目录中查找 YM-801S-TLSS-****-FE.zip 格式的基础压缩包"""
    results = []
    for root, dirs, files in os.walk(svn_dir):
        for f in files:
            if f.startswith("YM-801S-TLSS-") and f.endswith("-FE.zip"):
                results.append(Path(root) / f)
    return results


def extract_version_from_branch(branch_name):
    """从分支名中提取版本号，分支格式: dev_xxxx_医院名称，如 dev_1.5.1_某某医院 -> 1.5.1"""
    match = re.search(r'dev_(\d+\.\d+\.\d+)_', branch_name)
    if match:
        return match.group(1)
    return ""


# ==============================
# GUI
# ==============================
class MenzOrderPackagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📦 门诊订单打包工具")
        self.root.state('zoomed')  # 启动时最大化
        self.root.minsize(800, 800)

        self.config = load_config()
        self.is_packaging = False

        # 匹配结果
        self.matched_svn_dirs = []       # [path, ...]
        self.matched_git_dirs = []       # [(path, branch_name), ...]
        self.selected_svn_dir = None
        self.selected_git_dir = None
        self.selected_git_branch = ""

        # 变量
        self.keyword = StringVar(value=self.config.get("keyword", ""))
        self.svn_base_dir = StringVar(value=self.config.get("svn_base_dir", str(SVN_BASE_DIR)))
        self.git_base_dir = StringVar(value=self.config.get("git_base_dir", str(GIT_BASE_DIR)))
        self.project_dir = StringVar()
        self.output_dir = StringVar()
        self.order_info = StringVar()
        self.project_version = StringVar()
        self.base_zip_path = StringVar()
        self.custom_zip_name = StringVar()
        self.auto_commit_svn = BooleanVar(value=self.config.get("auto_commit_svn", True))
        self.is_version_155_plus = BooleanVar(value=self.config.get("is_version_155_plus", False))
        self.history_records = self.config.get("history_records", [])

        self.create_widgets()
        self._refresh_history_listbox()
        self._log("配置已加载")

    def create_widgets(self):
        # Notebook 双标签页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # ========== 标签页1：打包配置（可滚动） ==========
        config_tab = ttk.Frame(self.notebook, padding="0")
        self.notebook.add(config_tab, text="⚙️ 打包配置")

        # 可滚动画布
        self.config_canvas = Canvas(config_tab, highlightthickness=0)
        config_scrollbar = ttk.Scrollbar(config_tab, orient=VERTICAL, command=self.config_canvas.yview)
        self.config_canvas.configure(yscrollcommand=config_scrollbar.set)
        config_scrollbar.pack(side=RIGHT, fill=Y)
        self.config_canvas.pack(side=LEFT, fill=BOTH, expand=True)

        self.config_inner = ttk.Frame(self.config_canvas, padding="10")
        self.config_canvas_window = self.config_canvas.create_window((0, 0), window=self.config_inner, anchor=NW)

        def _on_config_inner_configure(event):
            self.config_canvas.configure(scrollregion=self.config_canvas.bbox('all'))
        self.config_inner.bind('<Configure>', _on_config_inner_configure)

        def _on_canvas_configure(event):
            self.config_canvas.itemconfig(self.config_canvas_window, width=event.width)
        self.config_canvas.bind('<Configure>', _on_canvas_configure)

        self.config_canvas.bind_all('<MouseWheel>', lambda e: self.config_canvas.yview_scroll(-1 * (e.delta // 120), 'units'))

        config_tab = self.config_inner

        # --- 基础目录设置 ---
        dir_frame = ttk.LabelFrame(config_tab, text="📂 基础目录设置", padding=8)
        dir_frame.pack(fill=X, pady=(0, 8))
        ttk.Label(dir_frame, text="门诊SVN目录:").grid(row=0, column=0, sticky=W, padx=(0, 5))
        ttk.Entry(dir_frame, textvariable=self.svn_base_dir, width=60).grid(row=0, column=1, sticky=EW, padx=5)
        ttk.Label(dir_frame, text="门诊Git目录:").grid(row=1, column=0, sticky=W, padx=(0, 5))
        ttk.Entry(dir_frame, textvariable=self.git_base_dir, width=60).grid(row=1, column=1, sticky=EW, padx=5)
        dir_frame.columnconfigure(1, weight=1)

        # --- 关键字搜索 ---
        kw_frame = ttk.LabelFrame(config_tab, text="🔍 关键字搜索", padding=8)
        kw_frame.pack(fill=X, pady=(0, 8))
        kw_entry = ttk.Entry(kw_frame, textvariable=self.keyword, width=20)
        kw_entry.pack(side=LEFT, padx=(0, 5))
        self.btn_search = ttk.Button(kw_frame, text="🔍 搜索", command=self._start_search)
        self.btn_search.pack(side=LEFT, padx=(0, 10))
        ttk.Label(kw_frame, text="输入关键字搜索SVN目录和Git项目（如：阳泉）", foreground="gray").pack(side=LEFT)

        # --- 匹配到的SVN目录 ---
        svn_frame = ttk.LabelFrame(config_tab, text="💾 匹配到的SVN目录（双击选中）", padding=8)
        svn_frame.pack(fill=X, pady=(0, 8))
        svn_list_frame = ttk.Frame(svn_frame)
        svn_list_frame.pack(fill=X, expand=True)
        self.svn_listbox = Listbox(svn_list_frame, height=4, width=80)
        svn_scroll = ttk.Scrollbar(svn_list_frame, orient=VERTICAL, command=self.svn_listbox.yview)
        self.svn_listbox.config(yscrollcommand=svn_scroll.set)
        self.svn_listbox.pack(side=LEFT, fill=X, expand=True)
        svn_scroll.pack(side=RIGHT, fill=Y)
        self.svn_listbox.bind('<Double-Button-1>', self._on_svn_double_click)
        self.svn_listbox.bind('<MouseWheel>', self._on_svn_listbox_mousewheel)

        # --- 匹配到的Git项目目录 ---
        git_frame = ttk.LabelFrame(config_tab, text="📁 匹配到的Git项目目录（双击选中）", padding=8)
        git_frame.pack(fill=X, pady=(0, 8))
        git_list_frame = ttk.Frame(git_frame)
        git_list_frame.pack(fill=X, expand=True)
        self.git_listbox = Listbox(git_list_frame, height=4, width=80)
        git_scroll = ttk.Scrollbar(git_list_frame, orient=VERTICAL, command=self.git_listbox.yview)
        self.git_listbox.config(yscrollcommand=git_scroll.set)
        self.git_listbox.pack(side=LEFT, fill=X, expand=True)
        git_scroll.pack(side=RIGHT, fill=Y)
        self.git_listbox.bind('<Double-Button-1>', self._on_git_double_click)
        self.git_listbox.bind('<MouseWheel>', self._on_git_listbox_mousewheel)

        # --- 项目目录 ---
        proj_frame = ttk.LabelFrame(config_tab, text="📁 项目目录（Git项目目录）", padding=5)
        proj_frame.pack(fill=X, pady=5)
        ttk.Entry(proj_frame, textvariable=self.project_dir, width=70).pack(
            side=LEFT, fill=X, expand=True, padx=(0, 5))
        ttk.Button(proj_frame, text="浏览...", command=self._select_project_dir).pack(side=RIGHT)

        # --- 输出目录 ---
        output_frame = ttk.LabelFrame(config_tab, text="💾 输出目录", padding=5)
        output_frame.pack(fill=X, pady=5)
        ttk.Entry(output_frame, textvariable=self.output_dir, width=70).pack(
            side=LEFT, fill=X, expand=True, padx=(0, 5))
        ttk.Button(output_frame, text="浏览...", command=self._select_output_dir).pack(side=RIGHT)

        # --- 订单信息 ---
        order_frame = ttk.LabelFrame(config_tab, text="📋 订单信息", padding=5)
        order_frame.pack(fill=X, pady=5)
        ttk.Label(order_frame, text="格式: 前9个字符为订单号，其余为医院名").pack(anchor=W)
        ttk.Entry(order_frame, textvariable=self.order_info, width=70).pack(fill=X, pady=5)

        # --- 项目版本 ---
        version_frame = ttk.LabelFrame(config_tab, text="🔄 项目版本", padding=5)
        version_frame.pack(fill=X, pady=5)
        versions = ["1.5.0", "1.5.1", "1.5.2", "1.5.3", "1.5.4", "1.5.5", "1.5.6"]
        self.version_combo = ttk.Combobox(
            version_frame, textvariable=self.project_version,
            values=versions + ["手动输入"], width=10, state="readonly"
        )
        self.version_combo.grid(row=0, column=0, padx=5, pady=5)
        self.version_combo.bind("<<ComboboxSelected>>", self._on_version_selected)
        self.manual_version_var = StringVar()
        self.manual_version_var.trace_add("write", self._sync_manual_version)
        self.manual_version_entry = ttk.Entry(version_frame, textvariable=self.manual_version_var, width=10)
        self.manual_version_entry.grid(row=0, column=1, padx=5, pady=5)
        self.manual_version_entry.grid_remove()

        # --- 基础压缩包 ---
        zip_frame = ttk.LabelFrame(config_tab, text="📦 基础压缩包", padding=5)
        zip_frame.pack(fill=X, pady=5)
        ttk.Entry(zip_frame, textvariable=self.base_zip_path, width=70).pack(
            side=LEFT, fill=X, expand=True, padx=(0, 5))
        ttk.Button(zip_frame, text="浏览...", command=self._select_base_zip).pack(side=RIGHT)

        # --- 自定义ZIP名称 ---
        custom_frame = ttk.LabelFrame(config_tab, text="🏷️ 自定义ZIP名称", padding=5)
        custom_frame.pack(fill=X, pady=5)
        ttk.Label(custom_frame, text="（留空则自动生成）").pack(anchor=W)
        ttk.Entry(custom_frame, textvariable=self.custom_zip_name, width=70).pack(fill=X, pady=5)

        # --- 版本类型 ---
        vt_frame = ttk.LabelFrame(config_tab, text="📌 版本类型", padding=5)
        vt_frame.pack(fill=X, pady=5)
        ttk.Checkbutton(vt_frame, text="是 1.5.5 及以上版本（仅执行 npm run build）",
                        variable=self.is_version_155_plus).pack(anchor=W, pady=5)
        ttk.Label(vt_frame, text="提示：勾选后仅执行 build，不执行 lib-render2", foreground="gray").pack(anchor=W)

        # --- SVN自动提交 ---
        svn_opt_frame = ttk.LabelFrame(config_tab, text="🔗 SVN自动提交", padding=5)
        svn_opt_frame.pack(fill=X, pady=5)
        ttk.Checkbutton(svn_opt_frame, text="打包完成后自动提交到SVN",
                        variable=self.auto_commit_svn).pack(anchor=W, pady=5)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(config_tab)
        btn_frame.pack(fill=X, pady=10)
        self.btn_start = ttk.Button(btn_frame, text="🚀 开始打包", command=self._start_packaging)
        self.btn_start.pack(side=LEFT, padx=(0, 10))
        self.btn_save = ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config)
        self.btn_save.pack(side=LEFT)

        # ========== 标签页2：日志与历史 ==========
        log_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(log_tab, text="📝 日志与历史")

        # 打包日志
        log_frame = ttk.LabelFrame(log_tab, text="📝 打包日志", padding=5)
        log_frame.pack(fill=BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, wrap=WORD, height=12,
                                                   font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)

        # 历史记录
        history_frame = ttk.LabelFrame(log_tab, text="📚 打包历史记录（最近100次）", padding=5)
        history_frame.pack(fill=X, pady=5)

        listbox_frame = ttk.Frame(history_frame)
        listbox_frame.pack(fill=X, pady=5)
        self.history_listbox = Listbox(listbox_frame, height=6, width=80)
        hist_scroll = ttk.Scrollbar(listbox_frame, orient=VERTICAL, command=self.history_listbox.yview)
        self.history_listbox.config(yscrollcommand=hist_scroll.set)
        self.history_listbox.pack(side=LEFT, fill=X, expand=True)
        hist_scroll.pack(side=RIGHT, fill=Y)
        self.history_listbox.bind('<Double-Button-1>', self._load_history_record)
        self.history_listbox.bind('<MouseWheel>', self._on_history_listbox_mousewheel)

        btn_hist_frame = ttk.Frame(history_frame)
        btn_hist_frame.pack(fill=X, pady=5)
        ttk.Button(btn_hist_frame, text="📥 加载选中记录", command=self._load_history_record).pack(side=LEFT, padx=5)
        ttk.Button(btn_hist_frame, text="🗑️ 删除选中记录", command=self._delete_history_record).pack(side=LEFT, padx=5)
        ttk.Label(history_frame, text="💡 提示：双击记录可恢复配置", foreground="gray").pack(anchor=W)

    # ==================== 滚轮处理 ====================
    def _on_svn_listbox_mousewheel(self, event):
        self.svn_listbox.yview_scroll(-1 * (event.delta // 120), 'units')
        return 'break'

    def _on_git_listbox_mousewheel(self, event):
        self.git_listbox.yview_scroll(-1 * (event.delta // 120), 'units')
        return 'break'

    def _on_history_listbox_mousewheel(self, event):
        self.history_listbox.yview_scroll(-1 * (event.delta // 120), 'units')
        return 'break'

    # ==================== 搜索逻辑 ====================
    def _start_search(self):
        keyword = self.keyword.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入关键字！")
            return
        self.btn_search.config(state=DISABLED)
        threading.Thread(target=self._do_search, args=(keyword,), daemon=True).start()

    def _do_search(self, keyword):
        try:
            def log(msg):
                self.root.after(0, lambda: self._log(msg))

            svn_base = Path(self.svn_base_dir.get())
            git_base = Path(self.git_base_dir.get())

            # 1. 搜索SVN目录
            log(f"搜索SVN目录: {svn_base}")
            matched_svn = find_svn_dirs_by_keyword(svn_base, keyword)
            if matched_svn:
                log(f"✅ 找到 {len(matched_svn)} 个匹配的SVN目录:")
                for p in matched_svn:
                    log(f"   💾 {p.name}")
            else:
                log(f"⚠️ 未找到包含 '{keyword}' 的SVN目录")

            self.root.after(0, lambda: self._update_svn_list(matched_svn))

            # 2. 搜索Git项目目录
            log(f"搜索Git目录: {git_base}")
            matched_git = find_git_dirs_by_keyword(git_base, keyword)
            if matched_git:
                log(f"✅ 找到 {len(matched_git)} 个匹配的Git项目:")
                for p, b in matched_git:
                    log(f"   📁 {p.name}  (分支: {b})")
            else:
                log(f"⚠️ 未找到分支名包含 '{keyword}' 的Git项目目录")

            self.root.after(0, lambda: self._update_git_list(matched_git))

            if not matched_svn and not matched_git:
                self.root.after(0, lambda: messagebox.showwarning(
                    "未匹配到结果",
                    f"未找到匹配结果。\n\n"
                    f"请检查：\n"
                    f"1. SVN目录: {svn_base}\n"
                    f"2. Git目录: {git_base}\n"
                    f"3. 关键字: {keyword}"
                ))

        except Exception as e:
            self.root.after(0, lambda: self._log(f"❌ 搜索出错: {e}"))
        finally:
            self.root.after(0, lambda: self.btn_search.config(state=NORMAL))

    def _update_svn_list(self, matched_svn):
        self.matched_svn_dirs = matched_svn
        self.selected_svn_dir = None
        self.svn_listbox.delete(0, END)
        for p in matched_svn:
            self.svn_listbox.insert(END, str(p))

        # 自动选中：1条直接选中，多条选最近更新的
        if matched_svn:
            if len(matched_svn) == 1:
                auto_idx = 0
            else:
                auto_idx = max(range(len(matched_svn)),
                               key=lambda i: os.path.getmtime(matched_svn[i]))
                latest_time = datetime.fromtimestamp(os.path.getmtime(matched_svn[auto_idx]))
                self._log(f"ℹ️ 共 {len(matched_svn)} 条结果，自动选中最近更新的: {matched_svn[auto_idx].name} ({latest_time:%Y-%m-%d %H:%M})")
            self.svn_listbox.selection_set(auto_idx)
            self.svn_listbox.see(auto_idx)
            self._on_svn_double_click()

    def _update_git_list(self, matched_git):
        self.matched_git_dirs = matched_git
        self.selected_git_dir = None
        self.selected_git_branch = ""
        self.git_listbox.delete(0, END)
        for p, b in matched_git:
            self.git_listbox.insert(END, f"{p}  (分支: {b})")

        # 自动选中：1条直接选中，多条选最近更新的
        if matched_git:
            if len(matched_git) == 1:
                auto_idx = 0
            else:
                auto_idx = max(range(len(matched_git)),
                               key=lambda i: os.path.getmtime(matched_git[i][0]))
                latest_time = datetime.fromtimestamp(os.path.getmtime(matched_git[auto_idx][0]))
                self._log(f"ℹ️ 共 {len(matched_git)} 条结果，自动选中最近更新的: {matched_git[auto_idx][0].name} ({latest_time:%Y-%m-%d %H:%M})")
            self.git_listbox.selection_set(auto_idx)
            self.git_listbox.see(auto_idx)
            self._on_git_double_click()

    # ==================== 双击选中处理 ====================
    def _on_svn_double_click(self, event=None):
        """双击选中SVN目录，自动填充输出目录、订单信息、基础压缩包"""
        sel = self.svn_listbox.curselection()
        if not sel or sel[0] >= len(self.matched_svn_dirs):
            return
        svn_dir = self.matched_svn_dirs[sel[0]]
        self.selected_svn_dir = svn_dir
        self._log(f"选中SVN目录: {svn_dir}")

        # 自动填写输出目录：如果有"前端"子目录则使用，否则使用当前目录
        frontend_dir = svn_dir / "前端"
        if frontend_dir.exists() and frontend_dir.is_dir():
            self.output_dir.set(str(frontend_dir))
            self._log(f"✅ 自动设置输出目录: {frontend_dir}")
        else:
            self.output_dir.set(str(svn_dir))
            self._log(f"✅ 自动设置输出目录（无前端子目录）: {svn_dir}")

        # 自动匹配订单信息：过滤掉"前端"或"-前端"后缀
        dir_name = svn_dir.name
        order_text = dir_name
        if order_text.endswith("-前端"):
            order_text = order_text[:-3]
        elif order_text.endswith("前端"):
            order_text = order_text[:-2]
        self.order_info.set(order_text)
        self._log(f"✅ 自动匹配订单信息: {order_text}")

        # 自动查找基础压缩包
        base_zips = find_base_zip_in_svn_dir(svn_dir)
        if base_zips:
            self.base_zip_path.set(str(base_zips[0]))
            self._log(f"✅ 自动匹配基础压缩包: {base_zips[0].name}")
            if len(base_zips) > 1:
                self._log(f"ℹ️ 共找到 {len(base_zips)} 个压缩包，已选择第一个，可手动切换")
        else:
            self._log(f"⚠️ 未在SVN目录中找到 YM-801S-TLSS-****-FE.zip 格式的基础压缩包")

    def _on_git_double_click(self, event=None):
        """双击选中Git项目目录，自动填充项目目录、项目版本"""
        sel = self.git_listbox.curselection()
        if not sel or sel[0] >= len(self.matched_git_dirs):
            return
        git_dir, branch = self.matched_git_dirs[sel[0]]
        self.selected_git_dir = git_dir
        self.selected_git_branch = branch
        self.project_dir.set(str(git_dir))
        self._log(f"✅ 自动设置项目目录: {git_dir}")

        # 从分支名提取版本号
        version = extract_version_from_branch(branch)
        if version:
            self.project_version.set(version)
            self._log(f"✅ 从分支 '{branch}' 提取版本号: {version}")
        else:
            self._log(f"⚠️ 无法从分支名 '{branch}' 提取版本号，请手动选择")

    # ==================== 手动选择 ====================
    def _select_project_dir(self):
        initial_dir = self.project_dir.get() or self.config.get("git_base_dir", str(GIT_BASE_DIR))
        dir_path = filedialog.askdirectory(title="选择项目目录", initialdir=initial_dir)
        if dir_path:
            self.project_dir.set(dir_path)
            self._log(f"选择项目目录: {dir_path}")

    def _select_output_dir(self):
        initial_dir = self.output_dir.get() or self.config.get("svn_base_dir", str(SVN_BASE_DIR))
        dir_path = filedialog.askdirectory(title="选择输出目录", initialdir=initial_dir)
        if dir_path:
            self.output_dir.set(dir_path)
            self._log(f"选择输出目录: {dir_path}")

    def _select_base_zip(self):
        file_path = filedialog.askopenfilename(
            title="选择基础压缩包",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            initialdir=self.base_zip_path.get() or self.config.get("svn_base_dir", str(SVN_BASE_DIR))
        )
        if file_path:
            self.base_zip_path.set(file_path)
            self._log(f"选择基础压缩包: {file_path}")

    def _on_version_selected(self, event=None):
        if self.version_combo.get() == "手动输入":
            self.manual_version_entry.grid()
            self.manual_version_entry.focus()
        else:
            self.manual_version_entry.grid_remove()
            self.project_version.set(self.version_combo.get())

    def _sync_manual_version(self, *args):
        val = self.manual_version_var.get().strip()
        if val:
            self.project_version.set(val)

    # ==================== 打包逻辑 ====================
    def _start_packaging(self):
        if not self.project_dir.get():
            messagebox.showerror("错误", "请先选择项目目录")
            return
        if not Path(self.project_dir.get()).exists():
            messagebox.showerror("错误", f"项目目录不存在：\n{self.project_dir.get()}")
            return
        if not self.output_dir.get():
            messagebox.showerror("错误", "请先选择输出目录")
            return
        if not self.base_zip_path.get():
            messagebox.showerror("错误", "请先选择基础压缩包")
            return
        if not Path(self.base_zip_path.get()).exists():
            messagebox.showerror("错误", f"基础压缩包不存在：\n{self.base_zip_path.get()}")
            return
        if not self.project_version.get():
            messagebox.showerror("错误", "请选择或输入项目版本")
            return

        self.notebook.select(1)
        self.is_packaging = True
        self.btn_start.config(state=DISABLED)
        self.btn_search.config(state=DISABLED)
        threading.Thread(target=self._do_packaging, daemon=True).start()

    def _do_packaging(self):
        try:
            import platform as plat
            project_dir = Path(self.project_dir.get())
            output_dir = Path(self.output_dir.get())
            output_dir.mkdir(parents=True, exist_ok=True)

            def log(msg):
                self.root.after(0, lambda: self._log(msg))

            log("=" * 50)
            log(f"🚀 开始门诊订单打包")
            log(f"📁 项目目录: {project_dir}")
            log(f"💾 输出目录: {output_dir}")
            log(f"📋 订单信息: {self.order_info.get()}")
            log(f"🔄 项目版本: {self.project_version.get()}")

            # 1. 检查Node版本
            if not self._check_node_version(log):
                return

            # 2. 清理 dist 目录
            if not self._clean_dist_dirs(project_dir, log):
                return

            # 3. 执行 npm run build
            log("🔄 开始执行 npm run build...")
            if not self._run_npm_command(project_dir, "run build", log):
                log("❌ build 命令执行失败")
                return

            # 4. 根据版本类型决定是否执行 lib-render2
            if self.is_version_155_plus.get():
                log("🔄 1.5.5+ 版本，简化打包流程")
                dist_dir = project_dir / "dist"
                if not dist_dir.exists():
                    log("❌ 打包后未找到 dist 目录")
                    return
                log("✅ 项目打包完成")
                self._process_base_zip(log, dist_dir, lib_render_dir=None)
            else:
                log("🔄 开始执行 npm run lib-render2...")
                if not self._run_npm_command(project_dir, "run lib-render2", log):
                    log("❌ lib-render2 命令执行失败")
                    return
                dist_dir = project_dir / "dist"
                lib_render_dir = project_dir / "lib-render-dist"
                if not dist_dir.exists():
                    log("❌ 打包后未找到 dist 目录")
                    return
                if not lib_render_dir.exists():
                    log("❌ 打包后未找到 lib-render-dist 目录")
                    return
                log("✅ 项目打包完成")
                self._process_base_zip(log, dist_dir, lib_render_dir)

        except Exception as e:
            self.root.after(0, lambda: self._log(f"❌ 打包过程中出错: {e}"))
            logger.exception("Package failed")
        finally:
            self.is_packaging = False
            self.root.after(0, self._update_button_states)

    def _check_node_version(self, log):
        """检查当前Node版本"""
        try:
            result = subprocess.check_output(
                ["node", "-v"], text=True, encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            current_version = result.strip()
            log(f"当前Node版本: {current_version}")
            version_match = re.search(r'v(\d+)', current_version)
            if version_match:
                major_version = int(version_match.group(1))
                if major_version < 14:
                    self.root.after(0, lambda: messagebox.showwarning(
                        "Node版本过低",
                        f"当前Node版本为 {current_version}，建议使用 v14 或更高版本"
                    ))
            return True
        except Exception as e:
            log(f"⚠️ 检查Node版本失败: {e}")
            return True

    def _clean_dist_dirs(self, project_dir, log):
        """清理 dist 和 lib-render-dist 目录"""
        for dir_name in ["dist", "lib-render-dist"]:
            dir_path = project_dir / dir_name
            if dir_path.exists():
                try:
                    shutil.rmtree(dir_path)
                    log(f"✅ 删除目录: {dir_path}")
                except Exception as e:
                    log(f"❌ 删除目录失败 {dir_path}: {e}")
                    return False
        return True

    def _run_npm_command(self, project_dir, command, log):
        """执行npm命令"""
        try:
            import platform as plat
            log(f"开始执行命令: npm {command}")
            process = subprocess.Popen(
                ["npm"] + command.split(),
                cwd=str(project_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                shell=plat.system() == "Windows",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        log(line.strip())
            if process.stdout:
                remaining = process.stdout.read()
                if remaining:
                    for l in remaining.strip().split('\n'):
                        if l.strip():
                            log(l.strip())
            if process.returncode == 0:
                log(f"✅ 命令 'npm {command}' 执行成功")
                return True
            else:
                log(f"❌ 命令 'npm {command}' 执行失败，返回码: {process.returncode}")
                return False
        except Exception as e:
            log(f"❌ 执行命令出错: {e}")
            return False

    def _process_base_zip(self, log, dist_dir, lib_render_dir=None):
        """处理基础压缩包，生成最终ZIP文件"""
        try:
            base_zip_path = Path(self.base_zip_path.get())
            output_dir = Path(self.output_dir.get())
            output_dir.mkdir(parents=True, exist_ok=True)

            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                with zipfile.ZipFile(base_zip_path, 'r') as zipf:
                    zipf.extractall(temp_path)
                log("✅ 基础压缩包解压完成")

                if lib_render_dir:
                    # 老版本流程：替换 design 和 resource/js/render-design
                    design_target = temp_path / "design"
                    if design_target.exists():
                        for item in design_target.iterdir():
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                        for item in dist_dir.iterdir():
                            dest = design_target / item.name
                            if item.is_file():
                                shutil.copy2(item, dest)
                            elif item.is_dir():
                                shutil.copytree(item, dest)
                        log("✅ design 目录内容已替换")

                    render_target = temp_path / "resource" / "js" / "render-design"
                    if render_target.exists():
                        for item in render_target.iterdir():
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                        for item in lib_render_dir.iterdir():
                            dest = render_target / item.name
                            if item.is_file():
                                shutil.copy2(item, dest)
                            elif item.is_dir():
                                shutil.copytree(item, dest)
                        log("✅ resource/js/render-design 目录内容已替换")
                else:
                    # 1.5.5+ 版本流程：替换 design 和 resource
                    design_source = dist_dir / "design"
                    resource_source = dist_dir / "resource"

                    design_target = temp_path / "design"
                    if design_source.exists():
                        if design_target.exists():
                            for item in design_target.iterdir():
                                if item.is_file():
                                    item.unlink()
                                elif item.is_dir():
                                    shutil.rmtree(item)
                        else:
                            design_target.mkdir(parents=True, exist_ok=True)
                        for item in design_source.iterdir():
                            dest = design_target / item.name
                            if item.is_file():
                                shutil.copy2(item, dest)
                            elif item.is_dir():
                                shutil.copytree(item, dest)
                        log("✅ design 目录内容已替换/创建")
                    else:
                        log("⚠️ dist/design 目录不存在，跳过")

                    resource_target = temp_path / "resource"
                    if resource_source.exists():
                        if resource_target.exists():
                            for item in resource_target.iterdir():
                                if item.is_file():
                                    item.unlink()
                                elif item.is_dir():
                                    shutil.rmtree(item)
                        else:
                            resource_target.mkdir(parents=True, exist_ok=True)
                        for item in resource_source.iterdir():
                            dest = resource_target / item.name
                            if item.is_file():
                                shutil.copy2(item, dest)
                            elif item.is_dir():
                                shutil.copytree(item, dest)
                        log("✅ resource 目录内容已替换/创建")
                    else:
                        log("⚠️ dist/resource 目录不存在，跳过")

                # 生成ZIP文件名
                order_info = self.order_info.get()
                version = self.project_version.get()
                custom_name = self.custom_zip_name.get().strip()

                if custom_name:
                    new_zip_name = custom_name
                    if not new_zip_name.lower().endswith('.zip'):
                        new_zip_name += '.zip'
                else:
                    if len(order_info) >= 9:
                        order_id = order_info[:9]
                        hospital_name = order_info[9:]
                        log(f"解析订单号: {order_id}, 医院名: {hospital_name}")
                        order_parts = order_id.split('-')
                        if len(order_parts) == 2:
                            year_part = order_parts[0][-2:]
                            order_num = order_parts[1]
                            pinyin_initials = self._get_pinyin_initials(hospital_name)
                            new_zip_name = f"YM-801S-TLSS-V{version}.{year_part}{order_num}.01001-{pinyin_initials}-FE.zip"
                        else:
                            log(f"⚠️ 订单号格式不匹配: '{order_id}'，使用默认名称")
                            new_zip_name = f"{version}.zip"
                    else:
                        log(f"⚠️ 订单信息长度不足9位: '{order_info}'，使用默认名称")
                        new_zip_name = f"{version}.zip"

                new_zip_path = output_dir / new_zip_name

                with zipfile.ZipFile(new_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(temp_path):
                        for file in files:
                            file_path = Path(root) / file
                            arc_name = file_path.relative_to(temp_path).as_posix()
                            zipf.write(file_path, arc_name)

                log(f"✅ 新压缩包已生成: {new_zip_path}")

                # 添加到历史记录
                self.root.after(0, self._add_to_history)

                # SVN提交
                if self.auto_commit_svn.get():
                    self._commit_to_svn(new_zip_path, log)

                # 弹窗通知
                self.root.after(0, lambda: self._show_toast(
                    "打包完成",
                    f"订单: {self.order_info.get()}\n文件: {new_zip_name}"
                ))

                log("🎉 打包完成！")

        except Exception as e:
            log(f"❌ 处理基础压缩包时出错: {e}")

    def _get_pinyin_initials(self, text):
        """获取中文文本的拼音首字母"""
        if HAS_PINYIN:
            try:
                initials = lazy_pinyin(text, style=Style.FIRST_LETTER)
                result = ''.join(initials).upper()
                result = ''.join(c for c in result if c.isalpha())
                return result or 'UNKNOWN'
            except Exception as e:
                self._log(f"pypinyin 处理失败，回退到简化逻辑: {e}")

        # 回退逻辑
        result = []
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                result.append('Z')
            else:
                result.append(char)
        letters = [c for c in result if c.isalpha()]
        fallback = ''.join(letters).upper()
        self._log(f"⚠️ 使用简化拼音逻辑生成医院首字母: {fallback}")
        return fallback or 'UNKNOWN'

    # ==================== SVN提交 ====================
    def _commit_to_svn(self, zip_path, log):
        """将生成的ZIP文件提交到SVN"""
        try:
            output_dir = Path(self.output_dir.get())
            svn_working_copy = None
            check_dir = output_dir
            max_depth = 5

            for _ in range(max_depth):
                if (check_dir / ".svn").exists():
                    svn_working_copy = check_dir
                    break
                parent = check_dir.parent
                if parent == check_dir:
                    break
                check_dir = parent

            if not svn_working_copy:
                log(f"⚠️ 未找到SVN工作副本（已向上查找{max_depth}层），跳过提交")
                return

            if svn_working_copy != output_dir:
                log(f"ℹ️ 在上级目录找到SVN工作副本: {svn_working_copy}")

            log(f"🔄 开始提交到SVN: {zip_path.name}")

            # svn add
            try:
                result = subprocess.run(
                    ["svn", "add", str(zip_path)],
                    cwd=svn_working_copy,
                    capture_output=True, text=True, encoding='utf-8', timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode == 0:
                    log(f"✅ SVN Add成功: {result.stdout.strip()}")
                elif "already under version control" in result.stderr.lower():
                    log(f"ℹ️ 文件已在版本控制中，跳过Add")
                else:
                    log(f"⚠️ SVN Add警告: {result.stderr.strip()}")
            except Exception as e:
                log(f"⚠️ SVN Add出错: {e}")

            # svn commit
            commit_message = f"门诊订单打包：{zip_path.name} - {datetime.now():%Y-%m-%d %H:%M:%S}"
            result = subprocess.run(
                ["svn", "commit", "-m", commit_message, str(zip_path)],
                cwd=svn_working_copy,
                capture_output=True, text=True, encoding='utf-8', timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0:
                log(f"✅ SVN提交成功")
                if result.stdout:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            log(f"   {line}")
            else:
                log(f"❌ SVN提交失败: {result.stderr.strip()}")

        except FileNotFoundError:
            log("❌ 未找到svn命令，请确保已安装SVN命令行工具")
        except subprocess.TimeoutExpired:
            log("❌ SVN操作超时")
        except Exception as e:
            log(f"❌ SVN提交出错: {e}")

    # ==================== 历史记录 ====================
    def _add_to_history(self):
        """添加当前打包配置到历史记录（按订单信息去重）"""
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_dir": self.project_dir.get(),
            "output_dir": self.output_dir.get(),
            "order_info": self.order_info.get(),
            "project_version": self.project_version.get(),
            "base_zip_path": self.base_zip_path.get(),
            "custom_zip_name": self.custom_zip_name.get(),
            "auto_commit_svn": self.auto_commit_svn.get(),
            "is_version_155_plus": self.is_version_155_plus.get(),
        }

        order_info = self.order_info.get()
        self.history_records = [r for r in self.history_records if r.get('order_info') != order_info]
        self.history_records.insert(0, record)

        if len(self.history_records) > 100:
            self.history_records = self.history_records[:100]

        self._refresh_history_listbox()
        self._save_config()
        self._log(f"✅ 已添加到历史记录（当前共 {len(self.history_records)} 条，已去重）")

    def _refresh_history_listbox(self):
        self.history_listbox.delete(0, END)
        for record in self.history_records:
            display_text = f"[{record.get('timestamp', '')}] {record.get('order_info', '')} - V{record.get('project_version', '')}"
            self.history_listbox.insert(END, display_text)

    def _load_history_record(self, event=None):
        sel = self.history_listbox.curselection()
        if not sel:
            return
        index = sel[0]
        if 0 <= index < len(self.history_records):
            record = self.history_records[index]
            self.project_dir.set(record.get('project_dir', ''))
            self.output_dir.set(record.get('output_dir', ''))
            self.order_info.set(record.get('order_info', ''))
            self.project_version.set(record.get('project_version', ''))
            self.base_zip_path.set(record.get('base_zip_path', ''))
            self.custom_zip_name.set(record.get('custom_zip_name', ''))
            self.auto_commit_svn.set(record.get('auto_commit_svn', True))
            self.is_version_155_plus.set(record.get('is_version_155_plus', False))
            self._log(f"✅ 已加载历史记录: {record.get('timestamp', '')} - {record.get('order_info', '')}")
            self._log("ℹ️ 配置已恢复，请点击「🚀 开始打包」执行打包")
            self.notebook.select(0)

    def _delete_history_record(self):
        sel = self.history_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的记录")
            return
        index = sel[0]
        if 0 <= index < len(self.history_records):
            record = self.history_records[index]
            if messagebox.askyesno("确认删除",
                                   f"是否删除以下历史记录？\n\n"
                                   f"时间: {record.get('timestamp', '')}\n"
                                   f"订单: {record.get('order_info', '')}"):
                del self.history_records[index]
                self._refresh_history_listbox()
                self._save_config()
                self._log(f"✅ 已删除历史记录")

    # ==================== 配置 ====================
    def _save_config(self):
        config = {
            "svn_base_dir": self.svn_base_dir.get(),
            "git_base_dir": self.git_base_dir.get(),
            "keyword": self.keyword.get().strip(),
            "auto_commit_svn": self.auto_commit_svn.get(),
            "is_version_155_plus": self.is_version_155_plus.get(),
            "history_records": self.history_records,
        }
        save_config(config)

    # ==================== Toast ====================
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

    # ==================== 日志 ====================
    def _log(self, message):
        logger.info(message)
        self.log_text.config(state=NORMAL)
        self.log_text.insert(END, f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see(END)
        self.log_text.config(state=DISABLED)
        self.root.update_idletasks()

    def _update_button_states(self):
        state = DISABLED if self.is_packaging else NORMAL
        for btn in [self.btn_start, self.btn_search, self.btn_save]:
            btn.config(state=state)


# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = MenzOrderPackagerGUI(root)
    root.mainloop()
