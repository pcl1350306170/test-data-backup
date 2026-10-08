# -*- coding: utf-8 -*-
import os
import re
import json
import time
import subprocess

from flowlauncher import FlowLauncher

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
ICON_PATH = os.path.join("Images", "icon.png")
CONFIG_PATH = os.path.join(PLUGIN_DIR, "config.json")

# Chrome 原始 JSON 书签路径（作为备选）
CHROME_JSON_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    r"Google\Chrome\User Data\Default\Bookmarks"
)


class ChromeBookmarks(FlowLauncher):
    """Flow Launcher 插件：快速搜索和打开 Chrome 浏览器书签
    支持从 HTML 导出文件读取（解决 Chrome 同步导致本地 Bookmarks 文件丢失的问题）
    """

    def __init__(self):
        self.bookmarks = []       # [{name, url, folder}, ...]
        self.last_load_time = 0
        self.last_file_mtime = 0
        self.cache_seconds = 300  # 5 分钟缓存
        self.max_results = 30
        self.bookmark_file = ""   # 实际使用的书签文件路径
        self._load_config()
        super().__init__()

    # ── 配置 ──────────────────────────────────────────────

    def _load_config(self):
        """从 config.json 加载配置"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.bookmark_file = cfg.get("bookmark_html_path", "")
            self.max_results = cfg.get("max_results", 30)
            self.cache_seconds = cfg.get("cache_seconds", 300)
        except Exception:
            pass

        # 如果未配置路径，回退到 Chrome JSON 文件
        if not self.bookmark_file:
            self.bookmark_file = CHROME_JSON_PATH
        # 相对路径 → 基于插件目录解析为绝对路径
        elif not os.path.isabs(self.bookmark_file):
            self.bookmark_file = os.path.join(PLUGIN_DIR, self.bookmark_file)

    # ── HTML 书签解析 ─────────────────────────────────────

    def _parse_html_bookmarks(self, html_content):
        """解析 Chrome 导出的 HTML 书签文件（Netscape Bookmark File Format）"""
        bookmarks = []
        folder_stack = []

        for line in html_content.splitlines():
            line = line.strip()

            # 检测文件夹开始 <DT><H3 ...>名称</H3>
            folder_match = re.match(
                r'<DT><H3[^>]*>(.+?)</H3>', line, re.IGNORECASE
            )
            if folder_match:
                folder_stack.append(folder_match.group(1))
                continue

            # 检测文件夹结束
            if re.match(r'</DL>', line, re.IGNORECASE):
                if folder_stack:
                    folder_stack.pop()
                continue

            # 检测书签 <A HREF="url">名称</A>
            link_match = re.match(
                r'<DT><A\s+HREF="([^"]*)"[^>]*>(.+?)</A>',
                line, re.IGNORECASE
            )
            if link_match:
                url = link_match.group(1)
                name = link_match.group(2)
                folder = "/".join(folder_stack) if folder_stack else ""
                bookmarks.append({
                    "name": name,
                    "url": url,
                    "folder": folder,
                })

        return bookmarks

    # ── JSON 书签解析（Chrome 原始格式） ──────────────────

    def _parse_json_node(self, node, folder_path=""):
        """递归解析 Chrome JSON 书签节点"""
        results = []
        node_type = node.get("type", "")

        if node_type == "url":
            results.append({
                "name": node.get("name", ""),
                "url": node.get("url", ""),
                "folder": folder_path,
            })
        elif node_type == "folder":
            current_path = (
                os.path.join(folder_path, node.get("name", ""))
                if folder_path
                else node.get("name", "")
            )
            for child in node.get("children", []):
                results.extend(self._parse_json_node(child, current_path))

        return results

    # ── 统一加载入口 ──────────────────────────────────────

    def _load_bookmarks(self):
        """根据文件类型自动选择解析方式加载书签"""
        self.bookmarks = []
        if not os.path.isfile(self.bookmark_file):
            return

        try:
            with open(self.bookmark_file, "r", encoding="utf-8") as f:
                content = f.read()

            if content.lstrip().startswith("<!DOCTYPE") or content.lstrip().startswith("<"):
                # HTML 格式
                self.bookmarks = self._parse_html_bookmarks(content)
            else:
                # JSON 格式（Chrome 原始格式）
                data = json.loads(content)
                roots = data.get("roots", {})
                for root_key in ("bookmark_bar", "other", "synced"):
                    root = roots.get(root_key)
                    if root:
                        self.bookmarks.extend(
                            self._parse_json_node(root)
                        )

            self.last_load_time = time.time()
            self.last_file_mtime = os.path.getmtime(self.bookmark_file)
        except Exception:
            pass

    def _ensure_bookmarks(self):
        """确保书签缓存有效（文件变化或过期则重新加载）"""
        need_reload = (
            not self.bookmarks
            or time.time() - self.last_load_time > self.cache_seconds
        )
        # 检查文件是否被更新
        if not need_reload and os.path.isfile(self.bookmark_file):
            try:
                current_mtime = os.path.getmtime(self.bookmark_file)
                if current_mtime > self.last_file_mtime:
                    need_reload = True
            except OSError:
                pass

        if need_reload:
            self._load_bookmarks()

    # ── 匹配 ──────────────────────────────────────────────

    @staticmethod
    def _fuzzy_match(query, target):
        """模糊匹配：query 的每个字符按顺序出现在 target 中"""
        qi = 0
        for ch in target:
            if ch == query[qi]:
                qi += 1
                if qi == len(query):
                    return True
        return False

    # ── 查询 ──────────────────────────────────────────────

    def query(self, query):
        query = query.strip()
        self._ensure_bookmarks()

        # 无输入 → 提示用法
        if not query:
            return [{
                "Title": "输入关键字搜索 Chrome 书签",
                "SubTitle": f"已加载 {len(self.bookmarks)} 个书签",
                "IcoPath": ICON_PATH,
            }]

        # 书签文件不存在
        if not os.path.isfile(self.bookmark_file):
            return [{
                "Title": "书签文件不存在",
                "SubTitle": f"请在 config.json 中配置 bookmark_html_path",
                "IcoPath": ICON_PATH,
            }]

        q_lower = query.lower()
        results = []

        for bm in self.bookmarks:
            name_lower = bm["name"].lower()
            url_lower = bm["url"].lower()

            # 名称子串匹配（最高优先级）
            if q_lower in name_lower:
                score = 0
            # URL 子串匹配
            elif q_lower in url_lower:
                score = 1
            # 名称模糊匹配
            elif self._fuzzy_match(q_lower, name_lower):
                score = 2
            else:
                continue

            results.append({
                "Title": bm["name"],
                "SubTitle": bm["url"]
                            + (f"  |  {bm['folder']}" if bm["folder"] else ""),
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {
                    "method": "open_url",
                    "parameters": [bm["url"]],
                },
                "ContextData": bm["url"],
                "_score": score,
                "_name": name_lower,
            })

        # 排序：子串匹配 > URL匹配 > 模糊匹配，同级别按名称字母序
        results.sort(key=lambda x: (x.pop("_score"), x.pop("_name")))

        if not results:
            return [{
                "Title": f"未找到匹配「{query}」的书签",
                "SubTitle": f"共 {len(self.bookmarks)} 个书签",
                "IcoPath": ICON_PATH,
            }]

        return results[:self.max_results]

    # ── 右键菜单 ──────────────────────────────────────────

    def context_menu(self, data):
        url = data or ""
        return [{
            "Title": "复制链接地址",
            "SubTitle": url,
            "IcoPath": ICON_PATH,
            "JsonRPCAction": {
                "method": "copy_url",
                "parameters": [url],
            },
        }]

    # ── 动作 ──────────────────────────────────────────────

    def open_url(self, url):
        """在默认浏览器中打开 URL"""
        if url:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    def copy_url(self, url):
        """复制 URL 到剪贴板"""
        if url:
            subprocess.run(
                ["clip"],
                input=url.encode("utf-16-le"),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


if __name__ == "__main__":
    ChromeBookmarks()
