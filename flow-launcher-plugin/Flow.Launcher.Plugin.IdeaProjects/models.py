# -*- coding: utf-8 -*-
"""项目数据模型"""
import os
import time


class ProjectItem:
    """表示一个 IDEA 项目"""

    __slots__ = ("name", "path", "last_opened")

    def __init__(self, name: str, path: str, last_opened: int = 0):
        self.name = name
        self.path = path
        self.last_opened = last_opened  # 毫秒时间戳

    @property
    def last_opened_str(self) -> str:
        """将毫秒时间戳转为可读字符串"""
        if not self.last_opened:
            return "未知"
        try:
            return time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(self.last_opened / 1000),
            )
        except (OSError, ValueError):
            return "未知"

    @property
    def exists(self) -> bool:
        """项目路径是否仍存在"""
        return os.path.isdir(self.path)

    def to_dict(self) -> dict:
        """序列化为字典（用于写入 JSON）"""
        return {
            "name": self.name,
            "path": self.path,
            "lastOpened": self.last_opened,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectItem":
        """从字典反序列化"""
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            last_opened=data.get("lastOpened", 0),
        )
