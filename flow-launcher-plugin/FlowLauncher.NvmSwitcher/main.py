# -*- coding: utf-8 -*-
import ctypes
import os
import re
import subprocess
import tempfile
import time

from flowlauncher import FlowLauncher
from flowlauncher.FlowLauncherAPI import FlowLauncherAPI

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
ICON_PATH = os.path.join("Images", "icon.png")


class NvmSwitcher(FlowLauncher):
    """Flow Launcher 插件：快速切换 Node.js 版本（基于 nvm-windows）"""

    def __init__(self):
        self._versions = None
        self._current = None
        super().__init__()

    # ── 获取 & 解析 nvm list ─────────────────────────────

    def _fetch_versions(self):
        """调用 nvm list 获取已安装版本并解析"""
        try:
            result = subprocess.run(
                ["nvm", "list"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
            output = result.stdout
        except Exception:
            output = ""

        versions = []
        current = None

        for line in output.strip().splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            # 当前版本行: * 18.17.0 (Currently using 64-bit executable)
            if stripped.startswith("*"):
                m = re.search(r'\*\s+([\d.]+)', stripped)
                if m:
                    current = m.group(1)
                    versions.append((current, True))
            else:
                m = re.search(r'([\d.]+)', stripped)
                if m:
                    versions.append((m.group(1), False))

        self._versions = versions
        self._current = current

    def _ensure_versions(self):
        """确保版本列表已加载"""
        if self._versions is None:
            self._fetch_versions()

    # ── 查询 ──────────────────────────────────────────────

    def query(self, query):
        query = query.strip()
        self._ensure_versions()

        # 获取失败
        if not self._versions:
            return [{
                "Title": "无法获取 Node 版本列表",
                "SubTitle": "请确认 nvm 已正确安装并添加到 PATH",
                "IcoPath": ICON_PATH,
            }]

        versions = self._versions

        # 有输入时按版本号过滤
        if query:
            versions = [(v, cur) for v, cur in versions if query in v]

        if not versions:
            return [{
                "Title": "未找到匹配的版本",
                "SubTitle": f"查询: {query}",
                "IcoPath": ICON_PATH,
            }]

        results = []
        for version, is_current in versions:
            if is_current:
                title = f"v{version}  ★ 当前使用"
                subtitle = "当前正在使用的 Node.js 版本（无需切换）"
                action = None
            else:
                title = f"v{version}"
                subtitle = f"点击切换到 Node.js v{version}"
                action = {
                    "method": "switch_version",
                    "parameters": [version],
                }

            item = {
                "Title": title,
                "SubTitle": subtitle,
                "IcoPath": ICON_PATH,
            }
            if action:
                item["JsonRPCAction"] = action

            results.append(item)

        return results

    # ── 切换版本 ──────────────────────────────────────────

    def switch_version(self, version):
        """以管理员权限切换 Node 版本，完成后弹出通知（由 JsonRPCAction 回调触发）"""
        temp_dir = tempfile.gettempdir()
        result_file = os.path.join(temp_dir, f"nvm_switch_{os.getpid()}.txt")
        bat_file = os.path.join(temp_dir, f"nvm_switch_{os.getpid()}.bat")

        # 包装脚本：提权执行 nvm use，将结果写入临时文件
        bat_content = (
            f'@echo off\n'
            f'nvm use {version}\n'
            f'if %errorlevel% equ 0 (\n'
            f'    echo OK>{result_file}\n'
            f') else (\n'
            f'    echo FAIL>{result_file}\n'
            f')\n'
        )
        try:
            with open(bat_file, "w", encoding="gbk") as f:
                f.write(bat_content)

            # 以管理员权限执行
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "cmd.exe",
                f"/c \"{bat_file}\"", None, 1,  # SW_SHOWNORMAL
            )
        except Exception:
            FlowLauncherAPI.show_msg(
                "NVM Switcher", "无法启动提权进程，请确认 nvm 已安装", ICON_PATH)
            self._cleanup(result_file, bat_file)
            return

        # 轮询等待结果（最长 15 秒）
        success = False
        for _ in range(30):
            time.sleep(0.5)
            if os.path.exists(result_file):
                try:
                    with open(result_file, "r") as f:
                        success = f.read().strip() == "OK"
                except Exception:
                    pass
                break

        if success:
            self._current = version
            self._versions = None  # 下次查询时刷新列表
            FlowLauncherAPI.show_msg(
                "NVM Switcher", f"已切换到 Node.js v{version}", ICON_PATH)
        else:
            FlowLauncherAPI.show_msg(
                "NVM Switcher",
                f"切换到 Node.js v{version} 失败，请检查权限或重试",
                ICON_PATH)

        self._cleanup(result_file, bat_file)

    @staticmethod
    def _cleanup(*paths):
        """清理临时文件"""
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    NvmSwitcher()
