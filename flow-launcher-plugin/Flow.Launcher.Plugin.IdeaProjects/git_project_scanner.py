# -*- coding: utf-8 -*-
"""扫描指定目录下的 Git 项目"""
import os
import subprocess
import time

from models import ProjectItem


class GitProjectScanner:
    """扫描配置的目录，识别其中的 Git 项目（含 .git 文件夹）"""

    def __init__(self, cache_minutes: int = 5):
        self._cache_minutes = cache_minutes
        self._projects: list[ProjectItem] = []
        self._last_load_time: float = 0
        # 分支缓存: {project_path: {"branches": [...], "time": float}}
        self._branch_cache: dict = {}

    def _scan_dir(self, root: str, depth: int) -> list[ProjectItem]:
        """递归扫描目录，查找 Git 项目"""
        items = []
        if not os.path.isdir(root):
            return items

        try:
            for entry in os.scandir(root):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                # 跳过隐藏目录和常见非项目目录
                name = entry.name
                if name.startswith(".") or name in ("node_modules", "__pycache__", ".venv", "venv"):
                    continue

                path = entry.path
                # 检查是否为项目（含 .git 目录的 Git 仓库，或含 .idea 目录的 IDEA 工作区）
                if os.path.isdir(os.path.join(path, ".git")) or os.path.isdir(os.path.join(path, ".idea")):
                    items.append(ProjectItem(
                        name=name,
                        path=path,
                        last_opened=0,  # 扫描项目无打开时间
                    ))
                elif depth > 1:
                    # 继续递归扫描子目录
                    items.extend(self._scan_dir(path, depth - 1))
        except PermissionError:
            pass  # 跳过无权限的目录
        return items

    def refresh(self, scan_dirs: list):
        """重新扫描所有配置的目录"""
        items = []
        seen_paths = set()

        for entry in scan_dirs:
            if isinstance(entry, dict):
                root = entry.get("path", "")
                depth = entry.get("depth", 1)
            else:
                # 兼容直接传路径字符串
                root = str(entry)
                depth = 1

            if not os.path.isdir(root):
                continue

            for proj in self._scan_dir(root, depth):
                if proj.path not in seen_paths:
                    seen_paths.add(proj.path)
                    items.append(proj)

        self._projects = items
        self._last_load_time = time.time()

    def ensure_loaded(self, scan_dirs: list):
        """确保数据已加载（带缓存）"""
        if (not self._projects
                or time.time() - self._last_load_time > self._cache_minutes * 60):
            self.refresh(scan_dirs)

    def get_all(self, scan_dirs: list) -> list[ProjectItem]:
        """获取所有扫描到的 Git 项目"""
        if not scan_dirs:
            return []
        self.ensure_loaded(scan_dirs)
        return list(self._projects)

    @staticmethod
    def fuzzy_match(query: str, target: str) -> bool:
        """模糊匹配：query 的字符按顺序出现在 target 中"""
        qi = 0
        for ch in target:
            if ch == query[qi]:
                qi += 1
                if qi == len(query):
                    return True
        return False

    def search(self, query: str, scan_dirs: list) -> list[ProjectItem]:
        """在扫描结果中搜索匹配的项目"""
        if not scan_dirs:
            return []
        self.ensure_loaded(scan_dirs)

        q_lower = query.lower()
        matched = []
        for proj in self._projects:
            name_lower = proj.name.lower()
            # 优先子串匹配
            if q_lower in name_lower:
                matched.append(proj)
            elif self.fuzzy_match(q_lower, name_lower):
                matched.append(proj)
        return matched

    # ── Git 分支操作 ─────────────────────────────────────

    def get_branches(self, project_path: str) -> list[str]:
        """获取指定 Git 项目的本地分支列表（带缓存）"""
        now = time.time()
        cached = self._branch_cache.get(project_path)
        if cached and (now - cached["time"]) < self._cache_minutes * 60:
            return cached["branches"]

        branches = self._load_branches(project_path)
        self._branch_cache[project_path] = {
            "branches": branches,
            "time": now,
        }
        return branches

    @staticmethod
    def _load_branches(project_path: str) -> list[str]:
        """通过 git branch 命令获取本地分支列表"""
        if not os.path.isdir(os.path.join(project_path, ".git")):
            return []
        try:
            result = subprocess.run(
                ["git", "-C", project_path, "branch", "--list", "--format=%(refname:short)"],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0 or not result.stdout:
                return []
            return [b.strip() for b in result.stdout.splitlines() if b.strip()]
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
            return []

    def search_branches(
        self, branch_query: str, projects: list[ProjectItem]
    ) -> list[dict]:
        """在多个项目中搜索包含关键字的分支

        返回列表: [{"project": ProjectItem, "branches": [str]}, ...]
        仅包含有匹配分支的项目
        """
        q_lower = branch_query.lower()
        results = []
        for proj in projects:
            branches = self.get_branches(proj.path)
            matched = [b for b in branches if q_lower in b.lower()]
            if matched:
                results.append({"project": proj, "branches": matched})
        return results
