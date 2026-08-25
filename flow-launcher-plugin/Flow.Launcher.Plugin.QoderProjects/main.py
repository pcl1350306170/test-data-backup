# -*- coding: utf-8 -*-
import os
import subprocess
import time

from flowlauncher import FlowLauncher

from models import ProjectItem
from qoder_history_reader import QoderHistoryReader
from git_project_scanner import GitProjectScanner
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
        self.scanner = GitProjectScanner(
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

        # 解析两段式查询："项目关键字 分支关键字"
        project_query, branch_query = self._parse_query(query)

        # ── 分支搜索模式 ──
        if branch_query:
            return self._query_branches(project_query, branch_query)

        # ── 普通项目搜索模式（三个数据源合并）──
        if project_query:
            projects = self.reader.search(project_query)
            # 合并扫描的 Git 项目
            projects.extend(self.scanner.search(project_query, self.settings.scan_dirs))
        else:
            projects = self.reader.get_all()
            # 合并扫描的 Git 项目
            projects.extend(self.scanner.get_all(self.settings.scan_dirs))

        # 收藏项目（合并到列表头部，去重）
        favorites = self._get_favorite_projects()
        if favorites:
            existing_paths = {p.path for p in projects}
            for fav in favorites:
                if fav.path not in existing_paths:
                    projects.insert(0, fav)

        # 按路径去重（保留首次出现的）
        projects = self._deduplicate(projects)

        max_results = self.settings.max_results

        # 无匹配
        if not projects:
            return [{
                "Title": "未找到匹配的项目",
                "SubTitle": f"查询: {project_query}  |  输入 add 手动添加项目",
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
        if project_query and not project_query.startswith("add"):
            results.append({
                "Title": f"添加 \"{project_query}\" 为收藏项目",
                "SubTitle": "回车手动添加该项目路径到收藏列表",
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {
                    "method": "add_favorite_by_query",
                    "parameters": [project_query],
                },
            })

        return results

    def _parse_query(self, query: str) -> tuple[str, str]:
        """解析查询字符串，拆分为 (项目关键字, 分支关键字)

        规则：最后一个空格作为分隔符
        - "template"      → ("template", "")
        - "template 济南" → ("template", "济南")
        """
        if not query:
            return ("", "")
        # 从右侧找最后一个空格
        idx = query.rfind(" ")
        if idx < 0:
            return (query, "")
        project_part = query[:idx].strip()
        branch_part = query[idx + 1:].strip()
        return (project_part, branch_part)

    def _query_branches(self, project_query: str, branch_query: str) -> list:
        """分支搜索模式：先定位项目，再搜分支"""
        # 从扫描结果中匹配项目
        projects = self.scanner.search(project_query, self.settings.scan_dirs)
        # 也从历史记录和收藏中匹配
        projects.extend(self.reader.search(project_query))
        projects.extend(self._get_favorite_projects())
        projects = self._deduplicate(projects)

        if not projects:
            return [{
                "Title": f"未找到匹配 \"{project_query}\" 的项目",
                "SubTitle": "请确认项目关键字是否正确",
                "IcoPath": ICON_PATH,
            }]

        # 在匹配到的项目中搜索分支
        branch_results = self.scanner.search_branches(branch_query, projects)

        if not branch_results:
            return [{
                "Title": f"未在匹配项目中找到包含 \"{branch_query}\" 的分支",
                "SubTitle": f"已搜索 {len(projects)} 个项目",
                "IcoPath": ICON_PATH,
            }]

        # 构建结果列表
        results = []
        for item in branch_results:
            proj = item["project"]
            for branch in item["branches"]:
                results.append({
                    "Title": f"{proj.name}  →  {branch}",
                    "SubTitle": proj.path,
                    "IcoPath": ICON_PATH,
                    "JsonRPCAction": {
                        "method": "open_project_with_branch",
                        "parameters": [proj.path, branch],
                    },
                })
        return results

    # ── 打开项目 ──────────────────────────────────────────

    def open_project(self, project_path):
        """调用 Qoder 打开项目"""
        cli = self.settings.qoder_cli
        try:
            subprocess.Popen(
                [cli, project_path],
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

    def open_project_with_branch(self, project_path: str, branch: str):
        """打开项目并可选自动 checkout 分支"""
        if self.settings.auto_checkout:
            self._checkout_branch(project_path, branch)
        self.open_project(project_path)

    @staticmethod
    def _checkout_branch(project_path: str, branch: str):
        """在指定项目中 checkout 到目标分支"""
        try:
            subprocess.run(
                ["git", "-C", project_path, "checkout", branch],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
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

    @staticmethod
    def _deduplicate(projects: list) -> list:
        """按路径去重，保留首次出现的项目"""
        seen = set()
        result = []
        for proj in projects:
            if proj.path not in seen:
                seen.add(proj.path)
                result.append(proj)
        return result


if __name__ == "__main__":
    QoderProjects()
