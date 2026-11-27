# -*- coding: utf-8 -*-
import base64
import json
import os
import subprocess
import sys
import threading
import time

from flowlauncher import FlowLauncher

import notify
from models import SvnDirItem
from svn_client import SvnBrowser, extract_order_no, svn_info, svn_mkdir, svn_checkout
from settings import Settings
import plugin_log

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
ICON_PATH = os.path.join("Images", "icon.png")
# 新建（svn mkdir）二次确认的有效时长（秒）
_ARM_TTL = 180


class SvnQuickCheckout(FlowLauncher):
    """Flow Launcher 插件：快速检索在线 SVN 目录（病房/门诊）

    - 普通浏览行：已检出 → 打开本地目录；未检出 → 复制 SVN URL
    - 输入带编号（YYYY-NNNN）时置顶一行：编号已存在→回车检出；
      不存在→回车一次“准备新建”，再回车确认“新建并检出”
    - 检出/新建在后台线程执行，完成后弹 Windows 通知并打开目录
    """

    def __init__(self):
        self.settings = Settings()
        self.browser = SvnBrowser(cache_seconds=self.settings.cache_seconds)
        # 待确认新建状态：从磁盘恢复，扛得住 Flow 重启插件进程
        self._pending_create = plugin_log.load_pending()
        super().__init__()

    # ── 查询 ──────────────────────────────────────────────

    def query(self, query):
        query = query.strip()
        plugin_log.log("query: %r" % query)

        # 特殊命令：刷新缓存
        if query.lower() == "refresh":
            self.browser.invalidate()
            return [{
                "Title": "✅ 已清空 SVN 目录缓存",
                "SubTitle": "再次输入 svn + 类型关键字将重新拉取最新目录",
                "IcoPath": ICON_PATH,
            }]

        types = {t.get("name", ""): t for t in self.settings.svn_types if t.get("name")}
        if not types:
            return [{
                "Title": "未配置 SVN 分类",
                "SubTitle": "请编辑插件 settings.json 的 svn_types",
                "IcoPath": ICON_PATH,
            }]

        # 解析：查询中出现类型名（如 病房/门诊）则限定该类型
        type_name, sub_query = self._parse_query(query, types)

        # 无关键字：列出所有分类，回车浏览该分类目录
        if not query:
            return self._list_types(types)

        # 未指定类型：仅用已缓存目录匹配 + 提示用法（不触发网络）
        if not type_name:
            pooled = []
            for name, cfg in types.items():
                pooled.extend(self._collect_items(name, cfg, sub_query, fetch=False))
            pooled.sort(key=lambda it: self._sort_key(it, sub_query.lower()))
            results = [self._build_result(it) for it in pooled[:self.settings.max_results]]
            hint = [self._type_hint_result(list(types)[0], query, bool(results))]
            return results + hint

        cfg = types[type_name]
        items = self._collect_items(type_name, cfg, sub_query, fetch=True)
        results = [self._build_result(it) for it in items[:self.settings.max_results]]

        # 带编号时，置顶一条“检出 / 新建并检出”动作行
        order_row = self._build_order_row(type_name, cfg, sub_query)
        if order_row:
            results.insert(0, order_row)
            return results

        if not results:
            return [{
                "Title": f"未找到匹配 \"{sub_query}\" 的{type_name}目录" if sub_query
                         else f"{type_name} 目录获取失败或为空",
                "SubTitle": f"{cfg.get('svn_base_url', '')}  |  检查网络/凭据后输入 svn refresh 重试",
                "IcoPath": ICON_PATH,
            }]
        return results

    def _build_order_row(self, type_name: str, cfg: dict, sub_query: str):
        """若 sub_query 包含合法编号，返回置顶的检出/新建动作行，否则 None"""
        order_no = extract_order_no(sub_query)
        if not order_no:
            return None
        resolution = self.browser.resolve_order(type_name, cfg, sub_query)
        res_json = json.dumps(
            {"type": type_name, **resolution}, ensure_ascii=False
        )
        key = f"{type_name}|{order_no}"
        pending = self._get_pending(key)
        plugin_log.log(
            "order_row: type=%s no=%s exists=%s need_hospital=%s pending=%s"
            % (type_name, order_no, resolution["exists"],
               resolution.get("need_hospital"), bool(pending))
        )

        if resolution["exists"]:
            # 已存在：单次回车直接检出
            return {
                "Title": f"🚀 检出【{type_name}】{resolution['order_name']}",
                "SubTitle": f"编号 {order_no} 已存在 → 回车检出到本地并创建“前端”",
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {"method": "do_checkout", "parameters": [res_json, "0"]},
            }

        if resolution["need_hospital"]:
            scope = f"将新建医院目录“{resolution['hospital_name']}”及订单“{resolution['order_name']}”"
        else:
            scope = f"将新建目录“{resolution['order_name']}”"

        if pending:
            # 二次确认：真正新建并检出
            return {
                "Title": f"⚠️ 再次回车确认：新建并检出【{type_name}】{resolution['order_name']}",
                "SubTitle": f"{scope}（{order_no} 在服务器上不存在）",
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {"method": "do_checkout", "parameters": [res_json, "1"]},
            }

        # 首次回车：仅“准备新建”，不写盘
        return {
            "Title": f"🆕 新建并检出【{type_name}】{resolution['order_name']}",
            "SubTitle": f"{scope}—回车一次准备，再回车才执行",
            "IcoPath": ICON_PATH,
            "JsonRPCAction": {"method": "arm_create", "parameters": [key, res_json]},
        }

    def _get_pending(self, key: str):
        item = self._pending_create.get(key)
        if not item:
            return None
        if time.time() > item["expire"]:
            self._pending_create.pop(key, None)
            plugin_log.save_pending(self._pending_create)
            return None
        return item

    def _type_hint_result(self, first_type: str, query: str, has_results: bool) -> dict:
        """未命中类型名时的引导行"""
        if has_results:
            sub = "以上为已缓存目录的匹配结果，输入类型关键字可拉取全部分类"
        else:
            sub = "尚未缓存目录数据，输入类型关键字开始首次拉取"
        return {
            "Title": f"输入类型关键字缩小范围，如 \"svn {first_type} {query}\"",
            "SubTitle": sub,
            "IcoPath": ICON_PATH,
        }

    def _collect_items(self, type_name: str, cfg: dict, sub_query: str, fetch: bool = True) -> list:
        """收集某分类目录条目（懒加载两层）

        - fetch=True：拉取一级目录（走缓存）；有关键字时再对命中的
          一级目录（最多 max_expand 个）展开二级
        - fetch=False：仅使用已缓存数据，不触发网络
        """
        from models import SvnDirItem
        if fetch:
            l1_names = self.browser.get_level1(type_name, cfg)
        else:
            l1_names = self.browser.peek_level1(type_name)
            if l1_names is None:
                return []

        kw = sub_query.lower()
        base_url = cfg.get("svn_base_url", "").rstrip("/")
        local_dir = cfg.get("local_checkout_dir", "")

        items = []
        hit_l1 = []
        for name in l1_names:
            item = SvnDirItem(type_name, name, f"{base_url}/{name}", local_dir)
            if not kw or kw in name.lower():
                items.append(item)
                hit_l1.append(name)

        # 仅 fetch 且有关键字时才展开二级（无关键字时一级全部展示，不展开）
        if kw and fetch:
            for name in hit_l1[:self.browser.max_expand]:
                l2_names = self.browser.get_level2(type_name, name, cfg)
                for d2 in l2_names:
                    rel = f"{name}/{d2}"
                    items.append(SvnDirItem(type_name, rel, f"{base_url}/{rel}", local_dir))
        # 已检出优先 → 名称前缀 → 名称包含 → 路径顺序
        items.sort(key=lambda it: self._sort_key(it, kw))
        return items

    def _parse_query(self, query: str, types: dict) -> tuple:
        """从查询中识别类型名，返回 (type_name, 剩余关键字)

        - "病房 济南"     → ("病房", "济南")
        - "门诊 0123"     → ("门诊", "0123")
        - "济南"          → ("", "济南")
        """
        for name in types:
            idx = query.find(name)
            if idx >= 0:
                rest = (query[:idx] + " " + query[idx + len(name):]).strip()
                return (name, rest)
        return ("", query)

    def _list_types(self, types: dict) -> list:
        """无关键字时列出全部分类"""
        results = []
        for name, cfg in types.items():
            results.append({
                "Title": f"浏览 {name} 目录",
                "SubTitle": cfg.get("svn_base_url", ""),
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {
                    "method": "copy_to_clipboard",
                    "parameters": [f"svn {name}"],
                },
            })
        results.append({
            "Title": "刷新全部 SVN 目录缓存",
            "SubTitle": "清空缓存后重新拉取最新目录",
            "IcoPath": ICON_PATH,
            "JsonRPCAction": {
                "method": "refresh_cache",
                "parameters": [],
            },
        })
        return results

    @staticmethod
    def _sort_key(item: SvnDirItem, kw: str) -> tuple:
        name = item.name.lower()
        if not kw:
            hit = 1
        elif name.startswith(kw):
            hit = 0
        elif kw in name:
            hit = 1
        else:
            hit = 2
        return (0 if item.checked_out else 1, hit, item.rel_path)

    def _build_result(self, item: SvnDirItem) -> dict:
        """构造单条 Flow 结果"""
        mark = " ✔" if item.checked_out else ""
        status = "已检出，回车打开本地目录" if item.checked_out else "未检出，回车复制 SVN URL"
        subtitle = f"{item.type_name}/{item.rel_path}  |  {status}"
        if item.checked_out:
            action = {
                "method": "open_local_dir",
                "parameters": [item.local_path],
            }
        else:
            action = {
                "method": "copy_to_clipboard",
                "parameters": [item.url],
            }

        contexts = [
            {
                "Title": "复制 SVN URL",
                "ActionParameter": [item.url],
                "ActionKeyword": "copy_to_clipboard",
                "JsonRPCAction": {
                    "method": "copy_to_clipboard",
                    "parameters": [item.url],
                },
            },
            {
                "Title": "打开 SVN 所在目录（网页）",
                "ActionKeyword": "",
                "JsonRPCAction": {
                    "method": "open_url_in_browser",
                    "parameters": [item.url],
                },
            },
            {
                "Title": "刷新该分类目录",
                "ActionKeyword": "",
                "JsonRPCAction": {
                    "method": "refresh_type",
                    "parameters": [item.type_name],
                },
            },
        ]
        if item.checked_out:
            contexts.insert(1, {
                "Title": "打开本地父目录",
                "ActionParameter": [os.path.dirname(item.local_path)],
                "ActionKeyword": "",
                "JsonRPCAction": {
                    "method": "open_local_dir",
                    "parameters": [os.path.dirname(item.local_path)],
                },
            })

        return {
            "Title": f"[{item.type_name}] {item.rel_path}{mark}",
            "SubTitle": subtitle,
            "IcoPath": ICON_PATH,
            "ToolTipData": {"Title": "SVN 目录", "Description": item.url},
            "JsonRPCAction": action,
            "ContextData": [item.url, item.local_path],
            "ContextMenu": contexts,
        }

    # ── 动作 ──────────────────────────────────────────────

    def copy_to_clipboard(self, text):
        """复制文本到剪贴板（修复 x64 句柄截断），成功/失败都反馈通知"""
        ok = notify.copy_to_clipboard(text)
        if ok:
            notify.show_toast("✅ 已复制 SVN URL", text)
        else:
            notify.show_toast("❌ 复制失败", f"未能写入剪贴板：{text}")

    # ── 检出 / 新建 ──────────────────────────

    def arm_create(self, key, res_json):
        """首次回车：登记“准备新建”，不执行任何写操作"""
        try:
            resolution = json.loads(res_json)
        except Exception as e:
            plugin_log.log("arm_create json failed: %r" % e)
            return
        self._pending_create[key] = {"resolution": resolution, "expire": time.time() + _ARM_TTL}
        plugin_log.save_pending(self._pending_create)
        plugin_log.log("arm_create: key=%s (未写盘，等待二次确认)" % key)
        notify.show_toast(
            "⚠️ 已准备新建（未执行）",
            f"请重新输入相同内容，会变成确认行，再回车才真正执行：{resolution.get('order_name', '')}",
        )

    def do_checkout(self, res_json, need_create):
        """启动脱离式子进程执行（可选新建）+ 检出。

        Flow 的 python 插件是一次性进程（flowlauncher 执行完方法即退出），
        因此绝不能用后台线程（会随进程被杀），必须 spawn 独立子进程。
        """
        plugin_log.log("do_checkout ENTER: need_create=%r" % (need_create,))
        try:
            resolution = json.loads(res_json)
        except Exception as e:
            plugin_log.log("do_checkout json failed: %r" % e)
            return
        create = str(need_create) == "1"
        cfg = self._cfg_for(resolution.get("type", ""))
        if not cfg:
            plugin_log.log("do_checkout: NO CFG for %s" % resolution.get("type"))
            notify.show_toast("❌ 无法检出", "未找到对应分类配置")
            return
        payload = base64.b64encode(json.dumps(
            {"resolution": resolution, "cfg": cfg, "create": create},
            ensure_ascii=False,
        ).encode("utf-8")).decode("ascii")
        runner = os.path.join(PLUGIN_DIR, "checkout_runner.py")
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        try:
            subprocess.Popen(
                [sys.executable, runner, payload],
                creationflags=flags,
                close_fds=True,
            )
        except Exception as e:
            plugin_log.log("do_checkout spawn failed: %r" % e)
            notify.show_toast("❌ 无法启动检出", str(e))
            return
        notify.show_toast("⏳ 正在处理…", f"{resolution.get('order_name', '')} 后台执行中")

    def _cfg_for(self, type_name):
        for t in self.settings.svn_types:
            if t.get("name") == type_name:
                return t
        return None

    def open_local_dir(self, path):
        """在资源管理器中打开本地目录"""
        if path and os.path.isdir(path):
            try:
                subprocess.Popen(
                    ["explorer", path],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass

    def open_url_in_browser(self, url):
        """用默认浏览器打开 SVN URL（TortoiseSVN 等已注册 http handler 时可直接唤起）"""
        try:
            os.startfile(url)
        except Exception:
            pass

    def refresh_cache(self):
        """清空全部缓存"""
        self.browser.invalidate()

    def refresh_type(self, type_name):
        """清空指定分类缓存"""
        self.browser.invalidate(type_name)


if __name__ == "__main__":
    SvnQuickCheckout()
