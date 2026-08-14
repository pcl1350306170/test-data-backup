# -*- coding: utf-8 -*-
import sys
import os
import json
import subprocess

parent_folder_path = os.path.abspath(os.path.dirname(__file__))
sys.path.append(parent_folder_path)

from flowlauncher import FlowLauncher


class ScriptRunner(FlowLauncher):
    """Flow Launcher 插件：通过命令快捷运行本地 Python 脚本"""

    def __init__(self):
        # 先加载配置，再调用基类 __init__（基类会立即分发 JSON-RPC 请求）
        self.commands = []
        self.python_exe = sys.executable
        self.script_dir = ""
        self._load_config()
        super().__init__()

    def _load_config(self):
        """从 commands.json 加载命令配置"""
        config_path = os.path.join(parent_folder_path, "commands.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.python_exe = config.get("python_exe", sys.executable)
            self.script_dir = config.get("script_dir", "")
            # 将相对脚本路径拼接为绝对路径
            for cmd in config.get("commands", []):
                script = cmd["script"]
                if not os.path.isabs(script) and self.script_dir:
                    cmd["script"] = os.path.join(self.script_dir, script)
            self.commands = config.get("commands", [])
        except Exception:
            self.commands = []

    def _match_command(self, query):
        """根据查询匹配命令，返回匹配的命令列表"""
        query = query.strip().lower()
        if not query:
            return self.commands  # 无输入时显示所有命令

        matched = []
        for cmd in self.commands:
            # 匹配命令名称
            if query in cmd["name"].lower():
                matched.append(cmd)
                continue
            # 匹配关键词
            for kw in cmd.get("keywords", []):
                if query in kw.lower():
                    matched.append(cmd)
                    break
        return matched

    def query(self, query):
        results = []
        matched = self._match_command(query)

        for cmd in matched:
            script_path = cmd["script"]
            script_name = os.path.basename(script_path)
            keywords_display = ", ".join(cmd.get("keywords", []))

            results.append({
                "Title": cmd["name"],
                "SubTitle": f"运行 {script_name}" + (f"  |  关键词: {keywords_display}" if keywords_display else ""),
                "IcoPath": "Images\\icon.png",
                "JsonRPCAction": {
                    "method": "run_script",
                    "parameters": [script_path]
                }
            })

        # 无匹配时提示
        if not results:
            results.append({
                "Title": "未找到匹配的命令",
                "SubTitle": f"查询: {query}  |  请在 commands.json 中添加命令配置",
                "IcoPath": "Images\\icon.png"
            })

        return results

    def run_script(self, script_path):
        """运行指定的 Python 脚本（由 JsonRPCAction 回调触发）"""
        if not os.path.exists(script_path):
            return

        try:
            subprocess.Popen(
                [self.python_exe, script_path],
                cwd=os.path.dirname(script_path),
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            pass


if __name__ == "__main__":
    ScriptRunner()
