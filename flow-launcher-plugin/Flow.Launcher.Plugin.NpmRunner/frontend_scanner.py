# -*- coding: utf-8 -*-
"""扫描指定目录下的前端项目（含 package.json 的目录）"""
import os
import time

# 扫描时跳过的目录名
SKIP_DIRS = {
    "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".git", ".idea", ".vscode", "public", "static", "coverage", ".nuxt",
}


class ProjectItem:
    """表示一个前端项目"""

    __slots__ = ("name", "path")

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path


class FrontendScanner:
    """扫描配置的目录，识别其中的前端项目（含 package.json 的目录）"""

    def __init__(self, cache_minutes: int = 5):
        self._cache_minutes = cache_minutes
        self._projects: list[ProjectItem] = []
        self._last_load_time: float = 0

    def _scan_dir(self, root: str, depth: int) -> list[ProjectItem]:
        """递归扫描目录，查找含 package.json 的项目"""
        items = []
        if not os.path.isdir(root):
            return items

        try:
            for entry in os.scandir(root):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                name = entry.name
                # 跳过隐藏目录和常见非项目目录
                if name.startswith(".") or name in SKIP_DIRS:
                    continue

                path = entry.path
                if os.path.isfile(os.path.join(path, "package.json")):
                    items.append(ProjectItem(name=name, path=path))
                    # 已是项目根目录，不再深入（避免扫到 node_modules / 子包）
                    continue

                if depth > 1:
                    items.extend(self._scan_dir(path, depth - 1))
        except (PermissionError, OSError):
            pass  # 跳过无权限 / 异常目录
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
                root = str(entry)
                depth = 1

            if not os.path.isdir(root):
                continue

            for proj in self._scan_dir(root, depth):
                if proj.path not in seen_paths:
                    seen_paths.add(proj.path)
                    items.append(proj)

        # 按名称排序，便于浏览
        items.sort(key=lambda p: p.name.lower())
        self._projects = items
        self._last_load_time = time.time()

    def ensure_loaded(self, scan_dirs: list):
        """确保数据已加载（带缓存）"""
        if (not self._projects
                or time.time() - self._last_load_time > self._cache_minutes * 60):
            self.refresh(scan_dirs)

    def get_all(self, scan_dirs: list) -> list[ProjectItem]:
        """获取所有扫描到的前端项目"""
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
        """在扫描结果中搜索匹配的项目（子串优先，其次模糊匹配）"""
        if not scan_dirs:
            return []
        self.ensure_loaded(scan_dirs)

        q_lower = query.lower()
        substr_matched = []
        fuzzy_matched = []
        for proj in self._projects:
            name_lower = proj.name.lower()
            path_lower = proj.path.lower()
            # 优先子串匹配（名称或完整路径）
            if q_lower in name_lower or q_lower in path_lower:
                substr_matched.append(proj)
            elif self.fuzzy_match(q_lower, name_lower):
                fuzzy_matched.append(proj)
        return substr_matched + fuzzy_matched
