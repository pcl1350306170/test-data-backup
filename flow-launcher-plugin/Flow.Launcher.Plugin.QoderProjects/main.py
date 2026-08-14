# -*- coding: utf-8 -*-
import os
import subprocess
import time

from flowlauncher import FlowLauncher

from models import ProjectItem
from qoder_history_reader import QoderHistoryReader
from settings import Settings

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
ICON_PATH = os.path.join("Images", "icon.png")


class QoderProjects(FlowLauncher):
    """Flow Launcher 插件：快速打开 Qoder 曾经打开过的项目"""

    def __init__(self):
        self.settings = Settings()
        self.reader = QoderHistoryReader(
            db_path=self.settings.state_db_path,
            cache_minutes=self.settings.cache_minutes,
        )
        super().__init__()

    # ── 查询 ──────────────────────────────────────────────

    def query(self, query):
        query = query.strip()

        # 检查数据库是否存在
        if not os.path.isfile(self.settings.state_db_path):
            return [{
                "Title": "未找到 Qoder 数据库文件",
                "SubTitle": f"期望路径: {self.settings.state_db_path}",
                "IcoPath": ICON_PATH,
            }]

        # 搜索或列出全部
        if query:
            projects = self.reader.search(query)
        else:
            projects = self.reader.get_all()

        # 收藏项目（合并到列表头部，去重）
        favorites = self._get_favorite_projects()
        if favorites:
            existing_paths = {p.path for p in projects}
            for fav in favorites:
                if fav.path not in existing_paths:
                    projects.insert(0, fav)

        max_results = self.settings.max_results

        # 无匹配
        if not projects:
            return [{
                "Title": "未找到匹配的项目",
                "SubTitle": f"查询: {query}  |  输入 add 手动添加项目",
                "IcoPath": ICON_PATH,
            }]

        results = []
        for proj in projects[:max_results]:
            status_icon = "" if proj.exists else " [路径不存在]"
            results.append({
                "Title": f"{proj.name}{status_icon}",
                "SubTitle": f"{proj.path}  |  最近打开: {proj.last_opened_str}",
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {
                    "method": "open_project",
                    "parameters": [proj.path],
                },
                "ContextData": [proj.path, proj.name],
            })

        # 有输入时，追加"手动添加"入口
        if query and not query.startswith("add"):
            results.append({
                "Title": f"添加 \"{query}\" 为收藏项目",
                "SubTitle": "回车手动添加该项目路径到收藏列表",
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {
                    "method": "add_favorite_by_query",
                    "parameters": [query],
                },
            })

        return results

    # ── 打开项目 ──────────────────────────────────────────

    def open_project(self, project_path):
        """调用 Qoder CLI 打开项目"""
        cli = self.settings.qoder_cli
        try:
            # Windows 下 .cmd 文件需通过 cmd /c 调用
            subprocess.Popen(
                ["cmd", "/c", cli, project_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            # CLI 未安装时尝试直接用 explorer 打开
            try:
                subprocess.Popen(
                    ["explorer", project_path],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
        except Exception:
            pass

    # ── 右键菜单操作 ──────────────────────────────────────

    def copy_path(self, project_path):
        """复制项目路径到剪贴板（使用 Windows API）"""
        try:
            import ctypes
            CF_UNICODETEXT = 13
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            user32.OpenClipboard(0)
            user32.EmptyClipboard()
            # 分配全局内存（含终止符）
            data = (project_path + '\0').encode('utf-16-le')
            h = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
            p = kernel32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(CF_UNICODETEXT, h)
            user32.CloseClipboard()
        except Exception:
            pass

    def open_in_explorer(self, project_path):
        """在文件管理器中打开项目目录"""
        if os.path.isdir(project_path):
            try:
                subprocess.Popen(
                    ["explorer", project_path],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass


    # ── 收藏管理 ──────────────────────────────────────────

    def add_favorite_by_query(self, query):
        """通过查询文本添加收藏项目（弹出输入框让用户确认路径）"""
        # 如果 query 本身就是一个有效路径，直接添加
        if os.path.isdir(query):
            name = os.path.basename(query)
            self.settings.add_favorite(name, query)
            return

        # 否则尝试将 query 作为名称，让用户在 settings.json 中手动配置
        # 这里先添加到收藏，路径设为 query（用户后续可编辑 settings.json）
        self.settings.add_favorite(query, query)

    def add_favorite(self, name, path):
        """添加收藏项目"""
        self.settings.add_favorite(name, path)

    def remove_favorite(self, path):
        """移除收藏项目"""
        self.settings.remove_favorite(path)

    # ── 内部工具 ──────────────────────────────────────────

    def _get_favorite_projects(self) -> list:
        """从 settings.json 读取收藏项目，转为 ProjectItem 列表"""
        favs = self.settings.favorites
        result = []
        for fav in favs:
            result.append(ProjectItem(
                name=fav.get("name", ""),
                path=fav.get("path", ""),
                last_opened=int(time.time() * 1000),  # 收藏项目排最前
            ))
        return result


if __name__ == "__main__":
    QoderProjects()
