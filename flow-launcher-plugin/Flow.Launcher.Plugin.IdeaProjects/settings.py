# -*- coding: utf-8 -*-
"""插件配置管理"""
import json
import os

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))

# ── 默认配置 ──────────────────────────────────────────────

_DEFAULTS = {
    # IDEA 最近项目配置文件路径（相对于 %APPDATA%）
    # IDEA 2024+ 使用此路径格式
    "idea_recent_rel": r"JetBrains",
    # IDEA CLI 命令（需确保在 PATH 中或使用完整路径）
    "idea_cli": "idea.bat",
    # 最大显示数量
    "max_results": 30,
    # 缓存刷新间隔（分钟）
    "cache_minutes": 5,
    # 收藏项目（手动添加，永久保留）
    "favorites": [],
    # 要扫描 Git 项目的目录列表
    # 每项: {"path": "D:\\CODE", "depth": 1}
    # depth: 扫描子目录深度，默认 1（仅直接子目录）
    "scan_dirs": [],
    # 选中分支后是否自动 checkout
    "auto_checkout": False,
}


class Settings:
    """读写插件本地配置（settings.json）"""

    def __init__(self):
        self._path = os.path.join(PLUGIN_DIR, "settings.json")
        self._data: dict = {}
        self.load()

    # ── 公共属性 ──────────────────────────────────────────

    @property
    def idea_recent_path(self) -> str:
        """JetBrains 配置目录的绝对路径"""
        rel = self._data.get("idea_recent_rel", _DEFAULTS["idea_recent_rel"])
        if os.path.isabs(rel):
            return rel
        return os.path.join(os.environ.get("APPDATA", ""), rel)

    @property
    def idea_cli(self) -> str:
        return self._data.get("idea_cli", _DEFAULTS["idea_cli"])

    @property
    def max_results(self) -> int:
        return self._data.get("max_results", _DEFAULTS["max_results"])

    @property
    def cache_minutes(self) -> int:
        return self._data.get("cache_minutes", _DEFAULTS["cache_minutes"])

    @property
    def favorites(self) -> list:
        """收藏项目列表（每项为 {"name": ..., "path": ...}）"""
        return self._data.get("favorites", _DEFAULTS["favorites"])

    @property
    def scan_dirs(self) -> list:
        """要扫描 Git 项目的目录列表（每项为 {"path": ..., "depth": ...}）"""
        return self._data.get("scan_dirs", _DEFAULTS["scan_dirs"])

    @property
    def auto_checkout(self) -> bool:
        """选中分支后是否自动 checkout"""
        return self._data.get("auto_checkout", _DEFAULTS["auto_checkout"])

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

    # ── 收藏管理 ─────────────────────────────────────────

    def add_favorite(self, name: str, path: str):
        """添加收藏项目（去重）"""
        favs = self.favorites
        for fav in favs:
            if fav.get("path") == path:
                return  # 已存在
        favs.append({"name": name, "path": path})
        self._data["favorites"] = favs
        self.save()

    def remove_favorite(self, path: str):
        """按路径移除收藏项目"""
        favs = self.favorites
        self._data["favorites"] = [f for f in favs if f.get("path") != path]
        self.save()
