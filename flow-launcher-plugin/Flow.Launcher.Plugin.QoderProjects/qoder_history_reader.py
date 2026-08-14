# -*- coding: utf-8 -*-
"""读取 Qoder 历史项目列表"""
import json
import os
import time

from models import ProjectItem


class QoderHistoryReader:
    """从 qoderProjects.json 读取 Qoder 历史项目"""

    def __init__(self, projects_json_path: str, cache_minutes: int = 5):
        self._path = projects_json_path
        self._cache_minutes = cache_minutes
        self._projects: list[ProjectItem] = []
        self._last_load_time: float = 0

    # ── 读取 ──────────────────────────────────────────────

    def _load_from_file(self) -> list[ProjectItem]:
        """从 qoderProjects.json 读取项目列表"""
        if not os.path.isfile(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = []
            for entry in data.get("projects", []):
                items.append(ProjectItem.from_dict(entry))
            return items
        except (json.JSONDecodeError, OSError, KeyError):
            return []

    def refresh(self):
        """强制重新加载"""
        self._projects = self._load_from_file()
        self._last_load_time = time.time()

    def ensure_loaded(self):
        """确保数据已加载（过期则自动刷新）"""
        if (not self._projects
                or time.time() - self._last_load_time > self._cache_minutes * 60):
            self.refresh()

    # ── 查询 ──────────────────────────────────────────────

    def get_all(self) -> list[ProjectItem]:
        """返回全部项目（按最近打开时间降序）"""
        self.ensure_loaded()
        return sorted(
            self._projects,
            key=lambda p: p.last_opened,
            reverse=True,
        )

    @staticmethod
    def fuzzy_match(query: str, target: str) -> bool:
        """模糊匹配：query 的每个字符按顺序出现在 target 中"""
        qi = 0
        for ch in target:
            if ch == query[qi]:
                qi += 1
                if qi == len(query):
                    return True
        return False

    def search(self, query: str) -> list[ProjectItem]:
        """按项目名称模糊搜索，返回匹配结果（按最近打开时间降序）"""
        self.ensure_loaded()
        q_lower = query.lower()
        matched = []
        for proj in self._projects:
            name_lower = proj.name.lower()
            # 子串匹配优先
            if q_lower in name_lower:
                matched.append(proj)
            elif self.fuzzy_match(q_lower, name_lower):
                matched.append(proj)
        # 按最近打开时间降序
        matched.sort(key=lambda p: p.last_opened, reverse=True)
        return matched

    # ── 写入（移除项目） ─────────────────────────────────

    def remove_project(self, path: str) -> bool:
        """从 qoderProjects.json 中移除指定路径的项目"""
        if not os.path.isfile(self._path):
            return False
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            projects = data.get("projects", [])
            original_len = len(projects)
            data["projects"] = [
                p for p in projects if p.get("path") != path
            ]
            if len(data["projects"]) == original_len:
                return False  # 未找到
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._projects = [
                ProjectItem.from_dict(p) for p in data["projects"]
            ]
            self._last_load_time = time.time()
            return True
        except (json.JSONDecodeError, OSError, KeyError):
            return False
