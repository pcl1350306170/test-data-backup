# -*- coding: utf-8 -*-
"""从 IDEA 配置文件读取最近打开的项目"""
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from models import ProjectItem


class IdeaHistoryReader:
    """从 IDEA 的 recentProjects.xml 读取历史项目"""

    def __init__(self, jetbrains_dir: str, cache_minutes: int = 5):
        self._jetbrains_dir = jetbrains_dir
        self._cache_minutes = cache_minutes
        self._projects: list[ProjectItem] = []
        self._last_load_time: float = 0

    def _find_latest_idea_dir(self) -> str:
        """找到最新的 IntelliJ IDEA 配置目录"""
        if not os.path.isdir(self._jetbrains_dir):
            return ""

        # 查找 IntelliJIdea* 目录（如 IntelliJIdea2024.1）
        idea_dirs = []
        for entry in os.scandir(self._jetbrains_dir):
            if entry.is_dir() and entry.name.startswith("IntelliJIdea"):
                idea_dirs.append(entry.path)

        if not idea_dirs:
            return ""

        # 按目录名排序，取最新的
        idea_dirs.sort(reverse=True)
        return idea_dirs[0]

    def _find_recent_projects_xml(self) -> str:
        """找到 recentProjects.xml 文件路径"""
        idea_dir = self._find_latest_idea_dir()
        if not idea_dir:
            return ""

        xml_path = os.path.join(idea_dir, "options", "recentProjects.xml")
        if os.path.isfile(xml_path):
            return xml_path
        return ""

    def _parse_recent_projects(self, xml_path: str) -> list[ProjectItem]:
        """解析 recentProjects.xml 提取项目列表"""
        if not os.path.isfile(xml_path):
            return []

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            items = []
            seen = set()

            # 查找所有 entry 元素（项目路径在 key 属性中）
            for entry in root.iter("entry"):
                key = entry.get("key", "")
                if not key:
                    continue

                # 转换路径格式：$USER_HOME$ → 用户目录
                path = key.replace("$USER_HOME$", os.path.expanduser("~"))
                # Windows 路径标准化
                path = os.path.normpath(path)

                if path in seen:
                    continue
                seen.add(path)

                # 尝试获取打开时间戳
                timestamp = 0
                for option in entry.iter("option"):
                    if option.get("name") == "projectOpenTimestamp":
                        try:
                            timestamp = int(option.get("value", "0"))
                        except ValueError:
                            pass
                        break

                items.append(ProjectItem(
                    name=os.path.basename(path),
                    path=path,
                    last_opened=timestamp,
                ))

            # 按打开时间倒序排列
            items.sort(key=lambda p: p.last_opened, reverse=True)
            return items

        except (ET.ParseError, OSError, ValueError):
            return []

    def refresh(self):
        """重新从 XML 加载项目列表"""
        xml_path = self._find_recent_projects_xml()
        if xml_path:
            self._projects = self._parse_recent_projects(xml_path)
        else:
            self._projects = []
        self._last_load_time = time.time()

    def ensure_loaded(self):
        """确保数据已加载（带缓存）"""
        if (not self._projects
                or time.time() - self._last_load_time > self._cache_minutes * 60):
            self.refresh()

    def get_all(self) -> list[ProjectItem]:
        """获取所有历史项目"""
        self.ensure_loaded()
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

    def search(self, query: str) -> list[ProjectItem]:
        """在历史项目中搜索"""
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
