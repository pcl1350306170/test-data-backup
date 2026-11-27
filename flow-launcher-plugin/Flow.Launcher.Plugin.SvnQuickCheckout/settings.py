# -*- coding: utf-8 -*-
"""插件配置管理"""
import json
import os

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))

# ── 默认配置 ──────────────────────────────────────────────

_DEFAULTS = {
    # SVN 分类配置，每项:
    # {"name": "病房", "svn_base_url": "...", "username": "...",
    #  "password": "...", "local_checkout_dir": "..."}
    "svn_types": [],
    # 最大显示数量
    "max_results": 40,
    # 目录列表缓存时间（秒）
    "cache_seconds": 300,
    # 匹配关键字时长关键字的权重（相对类型名）
    "score_name": 10,
}


class Settings:
    """读写插件本地配置（settings.json）"""

    def __init__(self):
        self._path = os.path.join(PLUGIN_DIR, "settings.json")
        self._data: dict = {}
        self.load()

    # ── 公共属性 ──────────────────────────────────────────

    @property
    def svn_types(self) -> list:
        return self._data.get("svn_types", _DEFAULTS["svn_types"])

    @property
    def max_results(self) -> int:
        return self._data.get("max_results", _DEFAULTS["max_results"])

    @property
    def cache_seconds(self) -> int:
        return self._data.get("cache_seconds", _DEFAULTS["cache_seconds"])

    # ── 读写 ──────────────────────────────────────────────

    def load(self):
        """从 settings.json 加载配置"""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {}

    def save(self):
        """将当前配置写回 settings.json"""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
