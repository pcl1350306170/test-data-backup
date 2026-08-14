# -*- coding: utf-8 -*-
"""从 state.vscdb 读取 Qoder 历史项目"""
import json
import os
import sqlite3
import time
from urllib.parse import unquote

from models import ProjectItem


def _uri_to_path(uri: str) -> str:
    r"""将 file:///d%3A/xxx 转为 D:\xxx"""
    if not uri.startswith("file:///"):
        return uri
    # 去掉 file:/// 前缀，URL 解码
    path = unquote(uri[8:])
    # Windows: d:/xxx → D:\\xxx
    if len(path) >= 2 and path[1] == ":":
        path = path[0].upper() + path[1:]
    return path.replace("/", "\\")


class QoderHistoryReader:
    """从 state.vscdb 读取 Qoder 历史项目"""

    def __init__(self, db_path: str, cache_minutes: int = 5):
        self._db_path = db_path
        self._cache_minutes = cache_minutes
        self._projects: list[ProjectItem] = []
        self._last_load_time: float = 0

    def _load_from_db(self) -> list[ProjectItem]:
        """从 state.vscdb 的 history.recentlyOpenedPathsList 读取"""
        if not os.path.isfile(self._db_path):
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT value FROM ItemTable WHERE key = 'history.recentlyOpenedPathsList'"
            )
            row = c.fetchone()
            conn.close()
            if not row:
                return []
            data = json.loads(row[0])
            items = []
            seen = set()
            for entry in data.get("entries", []):
                # folderUri → 文件夹项目
                uri = entry.get("folderUri", "")
                if uri:
                    path = _uri_to_path(uri)
                    if path not in seen:
                        seen.add(path)
                        items.append(ProjectItem(
                            name=os.path.basename(path),
                            path=path,
                        ))
                    continue
                # workspace → 工作区项目
                ws = entry.get("workspace")
                if ws:
                    cfg = ws.get("configPath", "")
                    if cfg:
                        path = _uri_to_path(cfg)
                        if path not in seen:
                            seen.add(path)
                            items.append(ProjectItem(
                                name=os.path.basename(path).replace(
                                    ".code-workspace", ""),
                                path=path,
                            ))
                    continue
                # fileUri → 单文件（取所在文件夹）
                uri = entry.get("fileUri", "")
                if uri:
                    path = _uri_to_path(uri)
                    folder = os.path.dirname(path)
                    if folder and folder not in seen:
                        seen.add(folder)
                        items.append(ProjectItem(
                            name=os.path.basename(folder),
                            path=folder,
                        ))
            return items
        except (json.JSONDecodeError, OSError, sqlite3.Error):
            return []

    def refresh(self):
        self._projects = self._load_from_db()
        self._last_load_time = time.time()

    def ensure_loaded(self):
        if (not self._projects
                or time.time() - self._last_load_time > self._cache_minutes * 60):
            self.refresh()

    def get_all(self) -> list[ProjectItem]:
        self.ensure_loaded()
        return list(self._projects)  # 已按打开顺序排列

    @staticmethod
    def fuzzy_match(query: str, target: str) -> bool:
        qi = 0
        for ch in target:
            if ch == query[qi]:
                qi += 1
                if qi == len(query):
                    return True
        return False

    def search(self, query: str) -> list[ProjectItem]:
        self.ensure_loaded()
        q_lower = query.lower()
        matched = []
        for proj in self._projects:
            name_lower = proj.name.lower()
            if q_lower in name_lower:
                matched.append(proj)
            elif self.fuzzy_match(q_lower, name_lower):
                matched.append(proj)
        return matched
