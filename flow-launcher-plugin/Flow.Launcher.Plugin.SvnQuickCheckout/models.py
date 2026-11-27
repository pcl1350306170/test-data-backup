# -*- coding: utf-8 -*-
"""数据模型：SVN 在线目录条目"""
import os


class SvnDirItem:
    """一条 SVN 在线目录记录（已按本地检出情况标注）"""

    __slots__ = ("type_name", "rel_path", "url", "local_path", "checked_out")

    def __init__(self, type_name: str, rel_path: str, url: str, local_dir: str):
        self.type_name = type_name        # 分类名：病房 / 门诊
        self.rel_path = rel_path          # 相对 base_url 的路径：一级 / 二级
        self.url = url                    # 完整 SVN URL
        # 本地检出路径 = local_dir / rel_path
        self.local_path = os.path.join(local_dir, *rel_path.split("/")) if local_dir else ""
        # Windows 路径大小写不敏感，直接 exists 判断即可
        self.checked_out = bool(self.local_path) and os.path.isdir(self.local_path)

    @property
    def name(self) -> str:
        """显示名：取最末一级目录名"""
        return self.rel_path.rsplit("/", 1)[-1]
