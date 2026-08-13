# -*- coding: utf-8 -*-
import os
import json
import time
import subprocess

from flowlauncher import FlowLauncher

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
ICON_PATH = os.path.join("Images", "icon.jpg")


class QuickFolderOpen(FlowLauncher):
    """Flow Launcher 插件：模糊搜索指定根目录下的子文件夹并快速打开"""

    def __init__(self):
        self.dirs = []          # [(dir_name_lower, full_path, root_label), ...]
        self.last_scan_time = 0
        self.root_dirs = []
        self.exclude_dirs = set()
        self.max_depth = 3
        self.max_results = 30
        self.cache_minutes = 10
        self._load_config()
        super().__init__()

    # ── 配置 ──────────────────────────────────────────────

    def _load_config(self):
        """从 config.json 加载根目录、过滤规则等配置"""
        config_path = os.path.join(PLUGIN_DIR, "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.root_dirs = cfg.get("root_dirs", [])
            self.exclude_dirs = set(
                d.lower() for d in cfg.get("exclude_dirs", [])
            )
            self.max_depth = cfg.get("max_depth", 3)
            self.max_results = cfg.get("max_results", 30)
            self.cache_minutes = cfg.get("cache_minutes", 10)
        except Exception:
            self.root_dirs = []

    # ── 目录扫描 ──────────────────────────────────────────

    def _scan_dirs(self):
        """扫描所有根目录下的子文件夹，建立索引"""
        self.dirs = []
        root_base = os.path.basename  # 局部引用，减少循环内属性查找

        for root_dir in self.root_dirs:
            if not os.path.isdir(root_dir):
                continue
            root_label = root_base(root_dir)
            root_depth = root_dir.rstrip(os.sep).count(os.sep)

            for dirpath, dirnames, _ in os.walk(root_dir):
                # 深度过滤
                current_depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
                if current_depth > self.max_depth:
                    dirnames.clear()
                    continue

                # 排除过滤（原地修改 dirnames 阻止 os.walk 递归进入）
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in self.exclude_dirs
                ]

                # 跳过根目录自身（只索引子文件夹）
                if dirpath == root_dir:
                    continue

                self.dirs.append((
                    os.path.basename(dirpath).lower(),
                    dirpath,
                    root_label,
                ))

        self.last_scan_time = time.time()

    def _ensure_index(self):
        """确保目录索引有效（过期则重新扫描）"""
        if (not self.dirs
                or time.time() - self.last_scan_time > self.cache_minutes * 60):
            self._scan_dirs()

    # ── 匹配 ──────────────────────────────────────────────

    @staticmethod
    def _fuzzy_match(query, target):
        """模糊匹配：query 的每个字符按顺序出现在 target 中"""
        qi = 0
        for ch in target:
            if ch == query[qi]:
                qi += 1
                if qi == len(query):
                    return True
        return False

    # ── 查询 ──────────────────────────────────────────────

    def query(self, query):
        query = query.strip()
        self._ensure_index()

        # 无输入 → 提示用法
        if not query:
            return [{
                "Title": "输入关键字搜索子文件夹",
                "SubTitle": f"已索引 {len(self.dirs)} 个目录  |  "
                            f"根目录: {', '.join(os.path.basename(r) for r in self.root_dirs)}",
                "IcoPath": ICON_PATH,
            }]

        results = []
        q_lower = query.lower()

        for name_lower, full_path, root_label in self.dirs:
            # 优先子串匹配，其次模糊匹配
            if q_lower in name_lower:
                score = 0   # 子串优先排前面
            elif self._fuzzy_match(q_lower, name_lower):
                score = 1
            else:
                continue

            results.append((score, name_lower, full_path, root_label))

        # 排序：子串匹配优先 → 名称字母序
        results.sort(key=lambda x: (x[0], x[1]))

        matched = results[:self.max_results]

        return [
            {
                "Title": os.path.basename(full_path),
                "SubTitle": full_path,
                "IcoPath": "Images\\icon.png",
                "JsonRPCAction": {
                    "method": "open_folder",
                    "parameters": [full_path],
                },
            }
            for _, _, full_path, _ in matched
        ]

    # ── 动作 ──────────────────────────────────────────────

    def open_folder(self, folder_path):
        """在资源管理器中打开文件夹"""
        if os.path.isdir(folder_path):
            subprocess.Popen(
                ["explorer", folder_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


if __name__ == "__main__":
    QuickFolderOpen()
