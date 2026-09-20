#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
D:\CODE 仓库批量克隆管理器（双模式，零依赖，仅标准库）

┌───────────────────────────────────────────────────────────┐
│ 模式一 · 导出清单（在旧电脑上运行）                          │
│   扫描根目录（默认 D:\CODE）→ 勾选要迁移的仓库 → 导出清单     │
│   生成 clone_manifest.json（仅含勾选的仓库及远程地址/分支）    │
│                                                             │
│ 模式二 · 克隆（在新电脑上运行）                              │
│   选择 clone_manifest.json → 勾选要克隆的仓库 → 一键克隆      │
│   按清单中的相对路径原样重建目录结构，目标根目录默认 D:\CODE   │
└───────────────────────────────────────────────────────────┘

用法：
    python clone_manager.py          # 启动图形界面
    python clone_manager.py --scan D:\CODE --json   # 命令行扫描（排障用）

依赖：Python 3.8+（自带 tkinter）+ 系统已安装 git（在 PATH 中）。
"""

import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# 常量与全局
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = SCRIPT_DIR / "clone_manifest.json"

CHECKED_PREFIX = "☑  "
UNCHECKED_PREFIX = "☐  "

# 扫描时跳过的目录（避免钻入依赖/构建目录浪费时间）
SKIP_DIRS = {
    ".git", ".idea", ".vscode", "__pycache__",
    "node_modules", ".venv", "venv", "env",
    "dist", "build", "target", ".gradle", ".mvn", ".next", ".nuxt",
}

SCAN_CACHE_FILE = SCRIPT_DIR / "scan_cache.json"

SCRIPT_NAME = "git_repo_backup"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# ---------- 日志（可选依赖） ----------
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


def save_scan_cache(repos):
    """缓存扫描结果到本地 JSON，下次启动秒加载。"""
    data = {
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repos": repos,
    }
    try:
        with open(SCAN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_scan_cache():
    """读取缓存的扫描结果，不存在或解析失败返回 None。"""
    if not SCAN_CACHE_FILE.exists():
        return None
    try:
        with open(SCAN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("repos", [])
    except (json.JSONDecodeError, OSError):
        return None


def run_git(args, cwd=None, timeout=1800):
    """执行 git 命令，返回 (returncode, stdout, stderr)，不弹出黑窗口。"""
    kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace", **kwargs,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("git %s 失败: %s", args, exc)
        return -1, "", str(exc)


# ---------------------------------------------------------------------------
# 扫描 / 清单读写
# ---------------------------------------------------------------------------
def scan_repos(root):
    """递归扫描 root 下所有含 .git 的仓库，返回仓库 dict 列表。"""
    root = Path(root)
    repos = []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        p = Path(dirpath)
        if (p / ".git").exists():
            rel = p.relative_to(root).as_posix()
            rc, url, _ = run_git(["remote", "get-url", "origin"], cwd=str(p))
            rc2, branch, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=str(p))
            repos.append({
                "rel": rel,
                "url": url if rc == 0 else "",
                "branch": branch if rc2 == 0 else "",
            })
    repos.sort(key=lambda r: r["rel"])
    logger.info("扫描 %s → %d 个仓库", root, len(repos))
    return repos


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    repos = [r for r in data.get("repos", []) if r.get("rel")]
    return data.get("source_root", ""), repos


def save_manifest(path, source_root, repos):
    data = {
        "version": 1,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": source_root,
        "repo_count": len(repos),
        "repos": repos,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_tree(repos):
    """把仓库列表按相对路径分层，返回嵌套节点。"""
    # 用 path -> node 的扁平映射构建树，避免 setdefault 层级错误
    nodes_by_path = {}

    def get_or_create(path, name):
        if path not in nodes_by_path:
            nodes_by_path[path] = {"name": name, "repo": None, "children": {}}
        return nodes_by_path[path]

    for r in repos:
        parts = r["rel"].split("/")
        for i, seg in enumerate(parts):
            path = "/".join(parts[:i + 1])
            node = get_or_create(path, seg)
            if i > 0:
                parent_path = "/".join(parts[:i])
                parent = get_or_create(parent_path, parts[i - 1])
                parent["children"][seg] = node
        nodes_by_path[r["rel"]]["repo"] = r

    # 顶层节点：路径中不含 "/" 的
    top = {node["name"]: node for path, node in nodes_by_path.items() if "/" not in path}

    def convert(d):
        result = []
        for name in sorted(d.keys()):
            n = d[name]
            result.append({
                "name": name,
                "repo": n["repo"],
                "children": convert(n["children"]) if n["children"] else [],
            })
        return result

    return convert(top)


# ---------------------------------------------------------------------------
# GUI 应用
# ---------------------------------------------------------------------------
class CloneManagerApp:
    def __init__(self, root):
        self.root = root
        root.title("代码仓库批量克隆管理器（导出清单 / 一键克隆）")
        root.geometry("900x640")
        root.minsize(760, 520)

        self.mode = tk.StringVar(value="clone" if DEFAULT_MANIFEST.exists() else "export")
        self.source_root = tk.StringVar(value=r"D:\CODE")
        self.manifest_path = tk.StringVar(value=str(DEFAULT_MANIFEST))
        self.target_root = tk.StringVar(value=r"D:\CODE")
        self.search_var = tk.StringVar()
        self.concurrency = tk.IntVar(value=3)

        self.all_repos = []          # 全部仓库 dict（当前模式）
        self.checked = {}            # rel -> True/False（勾选状态，跨重建保留）
        self.item_map = {}           # tree item id -> {"kind": "group"/"repo", "rel": ...}
        self.repo_by_rel = {}        # rel -> repo dict
        self.scanning = False          # 是否正在扫描
        self.worker_running = False      # 克隆任务是否运行中
        self.msg_queue = queue.Queue()
        self._tree_build_count = 0

        self._build_ui()
        self._load_config()
        self.root.after(50, self._initial_load)
        self.root.after(100, self._poll_queue)

    # ---------------- 界面搭建 ----------------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}

        # 顶部：模式
        top = ttk.LabelFrame(self.root, text="运行模式")
        top.pack(fill="x", **pad)
        ttk.Radiobutton(top, text="导出清单（旧电脑：扫描本机 → 勾选 → 导出清单）",
                        variable=self.mode, value="export", command=lambda: self.set_mode("export")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Radiobutton(top, text="克隆（新电脑：读取清单 → 勾选 → 一键克隆）",
                        variable=self.mode, value="clone", command=lambda: self.set_mode("clone")).grid(row=0, column=1, sticky="w", **pad)

        # 路径区
        cfg = ttk.LabelFrame(self.root, text="路径设置")
        cfg.pack(fill="x", **pad)

        self.lbl_source = ttk.Label(cfg, text="扫描根目录（旧电脑的代码目录）")
        self.lbl_source.grid(row=0, column=0, sticky="e", **pad)
        self.ent_source = ttk.Entry(cfg, textvariable=self.source_root)
        self.ent_source.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(cfg, text="浏览…", command=self._browse_source).grid(row=0, column=2, **pad)
        self.btn_scan = ttk.Button(cfg, text="扫描仓库", command=self._on_scan_click)
        self.btn_scan.grid(row=0, column=3, padx=(8, 0), pady=pad["pady"])

        self.lbl_manifest = ttk.Label(cfg, text="清单文件")
        self.lbl_manifest.grid(row=1, column=0, sticky="e", **pad)
        self.ent_manifest = ttk.Entry(cfg, textvariable=self.manifest_path)
        self.ent_manifest.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(cfg, text="浏览…", command=self._browse_manifest).grid(row=1, column=2, **pad)

        self.lbl_target = ttk.Label(cfg, text="克隆目标根目录（新电脑）")
        self.lbl_target.grid(row=2, column=0, sticky="e", **pad)
        self.ent_target = ttk.Entry(cfg, textvariable=self.target_root)
        self.ent_target.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(cfg, text="浏览…", command=self._browse_target).grid(row=2, column=2, **pad)
        cfg.columnconfigure(1, weight=1)

        # 搜索与操作
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", **pad)
        ttk.Label(bar, text="搜索：").pack(side="left")
        self.ent_search = ttk.Entry(bar, textvariable=self.search_var)
        self.ent_search.pack(side="left", fill="x", expand=True, padx=4)
        self.ent_search.bind("<KeyRelease>", lambda e: self._rebuild_tree())
        self.btn_all = ttk.Button(bar, text="全选", command=lambda: self._set_all(True))
        self.btn_all.pack(side="left", padx=2)
        self.btn_none = ttk.Button(bar, text="全不选", command=lambda: self._set_all(False))
        self.btn_none.pack(side="left", padx=2)

        # 仓库树
        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill="both", expand=True, **pad)
        columns = ("url",)
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings")
        self.tree.heading("#0", text="仓库（单击勾选/取消，点击箭头展开目录，空格键切换）")
        self.tree.heading("url", text="远程地址")
        self.tree.column("#0", width=520, stretch=True)
        self.tree.column("url", width=340, stretch=True)
        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)

        # 底部：状态 + 并发 + 动作按钮
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", **pad)
        self.lbl_count = ttk.Label(bottom, text="已选 0 / 0")
        self.lbl_count.pack(side="left")
        ttk.Label(bottom, text="  并发数：").pack(side="left")
        ttk.Spinbox(bottom, from_=1, to=8, textvariable=self.concurrency, width=4).pack(side="left")
        self.btn_action = ttk.Button(bottom, text="导出清单文件", command=self.on_action)
        self.btn_action.pack(side="right", padx=2)
        self.btn_cancel = ttk.Button(bottom, text="取消", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="right", padx=2)

        # 进度与日志
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", **pad)
        log_frame = ttk.LabelFrame(self.root, text="日志")
        log_frame.pack(fill="both", expand=False, **pad)
        self.log_text = tk.Text(log_frame, height=9, state="disabled", wrap="none")
        log_ysb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_ysb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_ysb.pack(side="right", fill="y")

    # ---------------- 浏览按钮 ----------------
    def _browse_source(self):
        p = filedialog.askdirectory(title="选择旧电脑代码根目录", initialdir=self.source_root.get() or "D:\\")
        if p:
            self.source_root.set(p)
            # 换了目录，旧缓存失效
            try:
                SCAN_CACHE_FILE.unlink()
            except OSError:
                pass
            self.set_mode("export")

    def _browse_manifest(self):
        p = filedialog.askopenfilename(title="选择清单文件", initialdir=str(SCRIPT_DIR),
                                       filetypes=[("JSON 清单", "*.json")])
        if p:
            self.manifest_path.set(p)
            self.set_mode("clone")

    def _browse_target(self):
        p = filedialog.askdirectory(title="选择克隆目标根目录", initialdir=self.target_root.get() or "D:\\")
        if p:
            self.target_root.set(p)

    # ---------- 配置持久化 ----------
    def _save_config(self):
        config = {
            "source_root": self.source_root.get(),
            "target_root": self.target_root.get(),
            "manifest_path": self.manifest_path.get(),
            "concurrency": self.concurrency.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s" % CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s" % e)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("source_root"):
                    self.source_root.set(cfg["source_root"])
                if cfg.get("target_root"):
                    self.target_root.set(cfg["target_root"])
                if cfg.get("manifest_path"):
                    self.manifest_path.set(cfg["manifest_path"])
                if cfg.get("concurrency"):
                    self.concurrency.set(cfg["concurrency"])
                logger.info("已加载配置: %s" % CONFIG_PATH)
        except Exception as e:
            logger.error("加载配置失败: %s" % e)

    # ---------------- 模式切换与数据加载 ----------------
    def _initial_load(self):
        """启动时：导出模式读缓存（秒开），克隆模式读清单文件。不自动扫描。"""
        mode = self.mode.get()
        self._apply_mode_ui(mode)
        if mode == "export":
            repos = load_scan_cache()
            if repos:
                self.log(f"从缓存加载了 {len(repos)} 个仓库（点击「扫描仓库」可刷新）")
                logger.info("从缓存加载 %d 个仓库", len(repos))
                self._finish_scan(repos, from_cache=True)
            else:
                self.log("请点击「扫描仓库」按钮开始扫描。")
                logger.info("无扫描缓存，等待用户操作")
        else:
            self._start_bg_load("clone", initial=True)

    def _apply_mode_ui(self, mode):
        """仅刷新 UI 控件可见性（主线程调用）。"""
        if mode == "export":
            self.lbl_source.config(text="扫描根目录（旧电脑的代码目录）")
            self.lbl_manifest.config(text="清单文件（导出到）")
            self.lbl_target.grid_remove()
            self.ent_target.grid_remove()
            self.btn_action.config(text="导出清单文件")
            self.btn_scan.grid()
        else:
            self.lbl_source.config(text="清单来源目录（导出时的代码根目录，仅参考）")
            self.lbl_manifest.config(text="清单文件")
            self.lbl_target.grid()
            self.ent_target.grid()
            self.btn_action.config(text="开始克隆")
            self.btn_scan.grid_remove()

    def _start_bg_load(self, mode, initial=False):
        """启动后台线程加载数据，完成后回主线程刷新 UI。"""
        def _work():
            repos, checked, logs = self._load_data(mode, initial)
            self.root.after(0, lambda: self._on_load_done(mode, (repos, checked, logs)))
        threading.Thread(target=_work, daemon=True).start()

    def _load_data(self, mode, initial=False):
        """纯数据加载（后台线程调用），不触碰任何 tkinter 控件。
        返回 (repos, logs)，logs 为 [(msg,)] 列表，由主线程写入日志。"""
        logs = []
        if mode == "export":
            root = self.source_root.get().strip().rstrip("\\/") or "D:"
            logs.append((f"正在扫描：{root} …",))
            repos = scan_repos(root)
            if not repos:
                logs.append((f"未在 {root} 下发现任何 Git 仓库（含 .git 的目录）。",))
            else:
                logs.append((f"扫描完成，发现 {len(repos)} 个仓库。",))
        else:
            path = self.manifest_path.get().strip()
            if not path or not Path(path).exists():
                if not initial:
                    logs.append(("__WARN_MISSING__",))
                repos = []
            else:
                src_root, repos = load_manifest(path)
                logs.append((f"已加载清单：{path}（{len(repos)} 个仓库）", src_root))
        # 设置勾选状态
        checked = {}
        for r in repos:
            if mode == "export":
                checked[r["rel"]] = bool(r.get("url"))
            else:
                checked[r["rel"]] = True
        return repos, checked, logs

    def _on_load_done(self, mode, load_result):
        """后台加载完成后，在主线程更新状态并刷新 UI。"""
        repos, checked, logs = load_result
        self.all_repos = repos
        self.repo_by_rel = {r["rel"]: r for r in repos}
        self.checked = checked
        # 主线程写日志
        for entry in logs:
            if entry[0] == "__WARN_MISSING__":
                messagebox.showwarning("缺少清单",
                    "清单文件不存在，请选择 clone_manifest.json。\n"
                    "在旧电脑上运行本脚本并勾选仓库后导出，再把脚本和清单文件一起拷贝过来。")
            elif len(entry) == 2 and entry[1]:
                # 克隆模式带 src_root
                self.log(entry[0])
                if self.source_root.get().strip() in ("", "D:\\CODE"):
                    self.source_root.set(entry[1])
            else:
                self.log(entry[0])
        self._rebuild_tree()

    def set_mode(self, mode, initial=False):
        """切换模式：同步刷新 UI 控件可见性；克隆模式自动加载清单，导出模式不自动扫描。"""
        self.mode.set(mode)
        self._apply_mode_ui(mode)
        if mode == "clone":
            self._start_bg_load(mode, initial)

    # ---------------- 扫描（导出模式） ----------------
    def _on_scan_click(self):
        """点击「扫描仓库」按钮。"""
        if self.scanning:
            return
        self.scanning = True
        self.btn_scan.config(state="disabled", text="扫描中…")
        self.log(f"正在扫描：{self.source_root.get().strip() or 'D:'} …")
        logger.info("开始扫描: %s", self.source_root.get().strip() or "D:")
        def _work():
            root = self.source_root.get().strip().rstrip("\\/") or "D:"
            repos = scan_repos(root)
            self.root.after(0, lambda: self._finish_scan(repos))
        threading.Thread(target=_work, daemon=True).start()

    def _finish_scan(self, repos, from_cache=False):
        """扫描/加载完成后的收尾（主线程调用）。"""
        self.scanning = False
        self.btn_scan.config(state="normal", text="扫描仓库")
        self.all_repos = repos
        self.repo_by_rel = {r["rel"]: r for r in repos}
        self.checked = {r["rel"]: bool(r.get("url")) for r in repos}
        if not from_cache:
            if not repos:
                self.log(f"未在 {self.source_root.get().strip() or 'D:'} 下发现任何 Git 仓库。")
            else:
                self.log(f"扫描完成，发现 {len(repos)} 个仓库。")
                save_scan_cache(repos)
                self.log("扫描结果已缓存，下次启动自动加载。")
                self._save_config()
                logger.info("扫描完成: %d 个仓库，配置已保存", len(repos))
        self._rebuild_tree()

    def _visible_filter(self):
        kw = self.search_var.get().strip().lower()
        if not kw:
            return None
        return kw

    def _rebuild_tree(self):
        """按搜索词重建树（勾选状态保留）。"""
        self.tree.delete(*self.tree.get_children())
        self.item_map = {}
        kw = self._visible_filter()

        def matches(node):
            if node["repo"] is not None and node["repo"]["rel"].lower().find(kw) >= 0:
                return True
            return False

        def visible_children(children):
            if kw is None:
                return children
            return [c for c in children if _subtree_visible(c)]

        def _subtree_visible(node):
            if matches(node):
                return True
            return any(_subtree_visible(c) for c in node["children"])

        def insert(parent_iid, node):
            if node["repo"] is not None and not node["children"]:
                # 叶子仓库节点（无嵌套仓库）
                iid = f"r{self._tree_build_count}"; self._tree_build_count += 1
                repo = node["repo"]
                text = (CHECKED_PREFIX if self.checked.get(repo["rel"]) else UNCHECKED_PREFIX) + repo["rel"]
                url = repo.get("url") or "（无远程，不可克隆）"
                self.tree.insert(parent_iid, "end", iid=iid, text=text, values=(url,))
                self.item_map[iid] = {"kind": "repo", "rel": repo["rel"]}
                return
            # 组节点（或自身也是仓库但包含嵌套仓库）
            iid = f"g{self._tree_build_count}"; self._tree_build_count += 1
            label = node["name"]
            if node["repo"] is not None:
                repo = node["repo"]
                prefix = CHECKED_PREFIX if self.checked.get(repo["rel"]) else UNCHECKED_PREFIX
                label = f"{prefix}{label}  [仓库]"
            self.tree.insert(parent_iid, "end", iid=iid, text=label, open=True)
            self.item_map[iid] = {"kind": "group", "rel": node["repo"]["rel"] if node["repo"] else None, "name": node["name"]}
            for child in visible_children(node["children"]):
                insert(iid, child)

        nodes = make_tree(self.all_repos)
        for node in visible_children(nodes):
            insert("", node)
        self._update_count()

    def _update_count(self):
        total = len(self.all_repos)
        checked = sum(1 for r in self.all_repos if self.checked.get(r["rel"]))
        self.lbl_count.config(text=f"已选 {checked} / {total}（导出/克隆均只处理勾选项）")

    # ---------------- 勾选交互 ----------------
    def _on_tree_click(self, event):
        """单击：仓库行切换勾选，组节点切换整棵子树。"""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        info = self.item_map.get(iid)
        if info is None:
            return
        if info["kind"] == "repo":
            rel = info["rel"]
            self.checked[rel] = not self.checked.get(rel, False)
            new_text = (CHECKED_PREFIX if self.checked[rel] else UNCHECKED_PREFIX) + rel
            self.tree.item(iid, text=new_text)
        else:
            # 组节点：切换自身仓库（如有）+ 所有子节点
            if info.get("rel"):
                rel = info["rel"]
                self.checked[rel] = not self.checked.get(rel, False)
                prefix = CHECKED_PREFIX if self.checked[rel] else UNCHECKED_PREFIX
                self.tree.item(iid, text=f"{prefix}{info['name']}  [仓库]")
            children = self.tree.get_children(iid)
            self._toggle_subtree(children, force=None)
        self._update_count()

    def _on_tree_space(self, event):
        """空格键：切换当前选中行的勾选状态。"""
        iid = self.tree.focus()
        if not iid:
            return
        info = self.item_map.get(iid)
        if info is None:
            return
        if info["kind"] == "repo":
            rel = info["rel"]
            self.checked[rel] = not self.checked.get(rel, False)
            new_text = (CHECKED_PREFIX if self.checked[rel] else UNCHECKED_PREFIX) + rel
            self.tree.item(iid, text=new_text)
        else:
            if info.get("rel"):
                rel = info["rel"]
                self.checked[rel] = not self.checked.get(rel, False)
                prefix = CHECKED_PREFIX if self.checked[rel] else UNCHECKED_PREFIX
                self.tree.item(iid, text=f"{prefix}{info['name']}  [仓库]")
            children = self.tree.get_children(iid)
            self._toggle_subtree(children, force=None)
        self._update_count()

    def _toggle_subtree(self, child_ids, force):
        for cid in child_ids:
            info = self.item_map.get(cid)
            if info is None:
                continue
            if info["kind"] == "repo":
                rel = info["rel"]
                if force is None:
                    self.checked[rel] = not self.checked.get(rel, False)
                else:
                    self.checked[rel] = force
                self.tree.item(cid, text=(CHECKED_PREFIX if self.checked[rel] else UNCHECKED_PREFIX) + rel)
            else:
                # 组节点：如果自身也是仓库，同步切换
                if info.get("rel"):
                    rel = info["rel"]
                    if force is None:
                        self.checked[rel] = not self.checked.get(rel, False)
                    else:
                        self.checked[rel] = force
                    prefix = CHECKED_PREFIX if self.checked[rel] else UNCHECKED_PREFIX
                    self.tree.item(cid, text=f"{prefix}{info['name']}  [仓库]")
                self._toggle_subtree(self.tree.get_children(cid), force)

    def _set_all(self, value):
        for r in self.all_repos:
            if self.mode.get() == "export" and not r.get("url"):
                continue  # 无远程的仓库不可克隆，不参与全选
            self.checked[r["rel"]] = value
        self._rebuild_tree()

    # ---------------- 主操作 ----------------
    def on_action(self):
        if self.worker_running:
            return
        selected = [self.repo_by_rel[r["rel"]] for r in self.all_repos
                    if self.checked.get(r["rel"])]
        if self.mode.get() == "export":
            self._do_export(selected)
        else:
            self._do_clone(selected)

    def _do_export(self, selected):
        if not selected:
            messagebox.showwarning("未勾选", "请先勾选需要迁移的仓库。")
            return
        no_url = [r for r in selected if not r.get("url")]
        if no_url:
            messagebox.showwarning("存在无远程仓库",
                                   f"有 {len(no_url)} 个仓库没有 origin 远程地址，无法克隆，已自动排除：\n" +
                                   "\n".join(r["rel"] for r in no_url[:10]))
            selected = [r for r in selected if r.get("url")]
            if not selected:
                return
        path = self.manifest_path.get().strip() or str(DEFAULT_MANIFEST)
        try:
            save_manifest(path, self.source_root.get().strip().rstrip("\\/") or "D:\\", selected)
        except OSError as exc:
            messagebox.showerror("导出失败", f"无法写入清单文件：\n{exc}")
            logger.error("导出清单失败: %s", exc)
            return
        self.log(f"已导出清单：{path}（{len(selected)} 个仓库）")
        self._save_config()
        logger.info("导出清单: %s (%d 个仓库)", path, len(selected))
        self.log("下一步：把本脚本和该清单文件一起拷贝到新电脑，运行脚本后切到「克隆」模式。")
        messagebox.showinfo("导出完成",
                            f"清单已导出：\n{path}\n\n包含 {len(selected)} 个仓库。\n"
                            "请把脚本和清单文件拷贝到新电脑，再运行本脚本切到「克隆」模式。")

    def _do_clone(self, selected):
        if not selected:
            messagebox.showwarning("未勾选", "请先勾选需要克隆的仓库。")
            return
        target = self.target_root.get().strip().rstrip("\\/")
        if not target:
            messagebox.showwarning("缺少目标目录", "请填写克隆目标根目录（例如 D:\\CODE）。")
            return
        if shutil.which("git") is None:
            messagebox.showerror("缺少 git", "未找到 git，请先安装 Git 并加入 PATH。")
            return
        # 无远程的仓库不可能出现在清单里，但做一次防御
        selected = [r for r in selected if r.get("url")]
        if not selected:
            return

        self.worker_running = True
        self.btn_action.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress.config(maximum=len(selected), value=0)
        self._cancel_event = threading.Event()
        max_workers = max(1, min(8, self.concurrency.get()))
        self.log(f"开始克隆 {len(selected)} 个仓库 → {target}（并发 {max_workers}）")
        self._save_config()
        logger.info("开始克隆: %d 个仓库 → %s (并发 %d)", len(selected), target, max_workers)
        threading.Thread(target=self._clone_worker,
                         args=(selected, target, max_workers), daemon=True).start()

    def _clone_worker(self, selected, target, max_workers):
        report = []
        done = 0
        results = {"ok": 0, "skip": 0, "fail": 0}

        def work(repo):
            if self._cancel_event.is_set():
                return repo["rel"], "cancelled", ""
            rel, url = repo["rel"], repo["url"]
            dest = Path(target) / rel
            try:
                if (dest / ".git").exists():
                    return rel, "skip", "目录已存在且是 Git 仓库"
                if dest.exists() and any(dest.iterdir()):
                    return rel, "fail", "目标目录已存在且非空（非 Git 仓库），已跳过"
                dest.parent.mkdir(parents=True, exist_ok=True)
                rc, _out, err = run_git(["clone", url, str(dest)])
                if rc != 0:
                    return rel, "fail", (err or "git clone 失败").strip()[:300]
                branch = repo.get("branch") or ""
                if branch and branch != "HEAD":
                    run_git(["checkout", branch], cwd=str(dest))  # 非致命：切不回就保留默认分支
                return rel, "ok", ""
            except Exception as exc:  # noqa: BLE001
                return rel, "fail", str(exc)[:300]

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(work, r) for r in selected]
            for fut in as_completed(futures):
                if self._cancel_event.is_set():
                    # 停止等待剩余任务，直接结算
                    continue
                rel, status, msg = fut.result()
                done += 1
                results[status] += 1
                report.append((rel, status, msg))
                self.msg_queue.put(("done", rel, status, msg, done, len(selected)))
        self.msg_queue.put(("finish", results, report))

    def on_cancel(self):
        if self.worker_running and not self._cancel_event.is_set():
            self._cancel_event.set()
            self.log("已请求取消：正在执行中的克隆完成后停止，不再启动新任务。")

    # ---------------- 队列轮询（UI 线程） ----------------
    def _poll_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]
                if kind == "done":
                    _k, rel, status, msg, done, total = item
                    mark = {"ok": "✓", "skip": "⏭", "fail": "✗", "cancelled": "⏹"}.get(status, "?")
                    self.log(f"{mark} [{done}/{total}] {rel}  {msg if msg else ''}")
                    self.progress.config(value=done)
                elif kind == "finish":
                    _k, results, report = item
                    self.worker_running = False
                    self.btn_action.config(state="normal")
                    self.btn_cancel.config(state="disabled")
                    self.progress.config(value=0)
                    summary = (f"克隆结束：成功 {results['ok']}，跳过 {results['skip']}，"
                               f"失败 {results['fail']}，共 {len(report)} 个。")
                    self.log(summary)
                    report_path = SCRIPT_DIR / f"克隆报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    try:
                        lines = [summary, ""]
                        lines += [f"{st.upper():8s} {rel}  {msg}" for rel, st, msg in report if msg]
                        report_path.write_text("\n".join(lines), encoding="utf-8")
                        self.log(f"报告已保存：{report_path}")
                    except OSError as exc:
                        self.log(f"报告写入失败：{exc}")
                    messagebox.showinfo("完成", summary)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ---------------- 日志 ----------------
    def log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    if "--scan" in sys.argv:
        # 命令行排障模式：--scan <dir> [--json]
        idx = sys.argv.index("--scan")
        root = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else r"D:\CODE"
        repos = scan_repos(root)
        print(f"扫描 {root} → {len(repos)} 个仓库")
        for r in repos:
            print(f"{r['rel']}\t{r['url'] or '(no origin)'}\t{r['branch']}")
        if "--json" in sys.argv:
            print(json.dumps(repos, ensure_ascii=False, indent=2))
        return

    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高分屏清晰
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    CloneManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
