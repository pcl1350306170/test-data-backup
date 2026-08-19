# -*- coding: utf-8 -*-
"""插件配置管理"""
import json
import os

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))

# ── 默认配置 ──────────────────────────────────────────────

_DEFAULTS = {
    # 要扫描前端项目的目录列表
    # 每项: {"path": "D:\\CODE", "depth": 1}
    # depth: 扫描子目录深度，默认 1（仅直接子目录）
    "scan_dirs": [],
    # 默认使用的 node 版本（项目未单独配置时使用）
    "default_node": "14.19.1",
    # 包管理器："auto"（按 pnpm-lock.yaml 自动判断）/ "pnpm" / "npm"
    "package_manager": "auto",
    # nvm 安装目录（为空则自动取环境变量 NVM_HOME 或 %APPDATA%\nvm）
    "nvm_home": "",
    # 自动打开的浏览器可执行文件路径（通过 BROWSER 环境变量生效，尽力而为）
    "chrome_path": "",
    # 未识别到 dev/serve/start 时使用的默认脚本
    "default_script": "dev",
    # 最大显示数量
    "max_results": 30,
    # 扫描缓存刷新间隔（分钟）
    "cache_minutes": 5,
    # 每个项目的个性化配置
    # 结构: {"项目绝对路径": {"node": "14.19.1", "script": "dev"}}
    "projects": {},
}


class Settings:
    """读写插件本地配置（settings.json）"""

    def __init__(self):
        self._path = os.path.join(PLUGIN_DIR, "settings.json")
        self._data: dict = {}
        self.load()

    # ── 公共属性 ──────────────────────────────────────────

    @property
    def scan_dirs(self) -> list:
        return self._data.get("scan_dirs", _DEFAULTS["scan_dirs"])

    @property
    def default_node(self) -> str:
        return self._data.get("default_node", _DEFAULTS["default_node"])

    @property
    def package_manager(self) -> str:
        return self._data.get("package_manager", _DEFAULTS["package_manager"])

    @property
    def nvm_home(self) -> str:
        return self._data.get("nvm_home", _DEFAULTS["nvm_home"])

    @property
    def chrome_path(self) -> str:
        return self._data.get("chrome_path", _DEFAULTS["chrome_path"])

    @property
    def default_script(self) -> str:
        return self._data.get("default_script", _DEFAULTS["default_script"])

    @property
    def max_results(self) -> int:
        return self._data.get("max_results", _DEFAULTS["max_results"])

    @property
    def cache_minutes(self) -> int:
        return self._data.get("cache_minutes", _DEFAULTS["cache_minutes"])

    @property
    def projects(self) -> dict:
        return self._data.get("projects", _DEFAULTS["projects"])

    # ── 项目级配置 ────────────────────────────────────────

    def node_for(self, project_path: str) -> str:
        """返回指定项目应使用的 node 版本（未配置则用默认版本）"""
        cfg = self.projects.get(project_path) or {}
        return cfg.get("node") or self.default_node

    def script_for(self, project_path: str) -> str:
        """返回指定项目配置的默认脚本（未配置则返回空串）"""
        cfg = self.projects.get(project_path) or {}
        return cfg.get("script") or ""

    def pm_for(self, project_path: str) -> str:
        """返回指定项目应使用的包管理器（'pnpm' 或 'npm'）

        优先级：项目级 pm 配置 > 全局 package_manager（pnpm/npm）> auto 自动判断。
        auto 时：存在 pnpm-lock.yaml 则用 pnpm，否则用 npm。
        """
        cfg = self.projects.get(project_path) or {}
        pm = cfg.get("pm")
        if pm in ("pnpm", "npm"):
            return pm

        g = self.package_manager
        if g in ("pnpm", "npm"):
            return g

        # auto：根据锁文件自动判断，优先 pnpm
        if os.path.isfile(os.path.join(project_path, "pnpm-lock.yaml")):
            return "pnpm"
        return "npm"

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
