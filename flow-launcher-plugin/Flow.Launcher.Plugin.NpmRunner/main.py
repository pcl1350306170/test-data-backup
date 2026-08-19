# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import tempfile
import time

if sys.platform == "win32":
    import ctypes

parent_folder_path = os.path.abspath(os.path.dirname(__file__))
sys.path.append(parent_folder_path)

from flowlauncher import FlowLauncher
from flowlauncher import FlowLauncherAPI

from frontend_scanner import FrontendScanner
from settings import Settings

ICON_PATH = os.path.join("Images", "icon.png")

# 查询末尾允许直接指定的脚本关键字 → 实际 npm script
# 例如 "npm template build" → 项目关键字 "template"，脚本 "build"
SCRIPT_TOKENS = {
    "dev": "dev", "d": "dev",
    "build": "build", "b": "build",
    "serve": "serve", "s": "serve",
    "start": "start",
}


class NpmRunner(FlowLauncher):
    """Flow Launcher 插件：快速运行/打包前端项目，自动切换 node 版本"""

    def __init__(self):
        # 先加载配置与扫描器，再调用基类 __init__（基类会立即分发 JSON-RPC 请求）
        self.settings = Settings()
        self.scanner = FrontendScanner(cache_minutes=self.settings.cache_minutes)
        super().__init__()

    # ── 查询 ──────────────────────────────────────────────

    def query(self, query):
        query = query.strip()

        # 命令选择模式：查询本身就是一个前端项目路径（由 select_project 切换而来）
        selected = self._match_selected_project(query)
        if selected:
            return self._command_results(selected)

        script_override, project_query = self._parse_query(query)

        if project_query:
            projects = self.scanner.search(project_query, self.settings.scan_dirs)
        else:
            projects = self.scanner.get_all(self.settings.scan_dirs)

        if not projects:
            return [{
                "Title": "未找到匹配的前端项目（需包含 package.json）",
                "SubTitle": f"查询: {project_query or '(空)'}  |  请检查 settings.json 的 scan_dirs",
                "IcoPath": ICON_PATH,
            }]

        results = []
        for proj in projects[:self.settings.max_results]:
            node_ver = self.settings.node_for(proj.path)
            pm = self.settings.pm_for(proj.path)

            if script_override:
                # 已键入脚本（如 "npm template build"）→ 回车直接执行
                results.append({
                    "Title": proj.name,
                    "SubTitle": f"node {node_ver}  |  {pm} run {script_override}  |  {proj.path}",
                    "IcoPath": ICON_PATH,
                    "ContextData": [proj.path],
                    "JsonRPCAction": {
                        "method": "run_project",
                        "parameters": [proj.path, node_ver, script_override, pm],
                    },
                })
            else:
                # 回车进入命令选择列表（dontHideAfterAction 防止执行后窗口隐藏）
                results.append({
                    "Title": proj.name,
                    "SubTitle": f"node {node_ver}  |  {pm}  |  {proj.path}  |  回车选择命令",
                    "IcoPath": ICON_PATH,
                    "ContextData": [proj.path],
                    "JsonRPCAction": {
                        "method": "select_project",
                        "parameters": [proj.path],
                        "dontHideAfterAction": True,
                    },
                })
        return results

    def context_menu(self, data):
        """右键 / 上下文菜单：选择具体的 npm 脚本"""
        path = data[0]
        node_ver = self.settings.node_for(path)
        pm = self.settings.pm_for(path)
        name = os.path.basename(path)
        scripts = self._read_scripts(path)

        if not scripts:
            return [{
                "Title": "package.json 中未找到 scripts",
                "SubTitle": path,
                "IcoPath": ICON_PATH,
            }]

        results = []
        for s in scripts:
            results.append({
                "Title": f"{pm} run {s}",
                "SubTitle": f"node {node_ver}  |  {name}",
                "IcoPath": ICON_PATH,
                "JsonRPCAction": {
                    "method": "run_project",
                    "parameters": [path, node_ver, s, pm],
                },
            })
        return results

    # ── 两级回车导航 ──────────────────────────────────────

    def select_project(self, project_path):
        """回车选中项目 → 把查询切换为该项目路径，进入命令选择列表"""
        FlowLauncherAPI.change_query("npm " + project_path, requery=True)

    def back_to_list(self):
        """从命令列表返回项目列表"""
        FlowLauncherAPI.change_query("npm ", requery=True)

    def _match_selected_project(self, query):
        """若查询是一个前端项目路径则返回该路径，否则返回 None"""
        candidates = [query]
        # 兼容 change_query 后带关键字前缀的情况
        if query.lower().startswith("npm "):
            candidates.append(query[4:].strip())
        for c in candidates:
            c = c.strip()
            if c and os.path.isdir(c) and os.path.isfile(os.path.join(c, "package.json")):
                return c
        return None

    def _command_results(self, project_path):
        """构建指定项目的命令选择列表（默认脚本置顶，返回项置底）"""
        node_ver = self.settings.node_for(project_path)
        pm = self.settings.pm_for(project_path)
        name = os.path.basename(project_path)
        scripts = self._read_scripts(project_path)

        results = []
        if not scripts:
            results.append({
                "Title": "package.json 中未找到 scripts",
                "SubTitle": project_path,
                "IcoPath": ICON_PATH,
            })
        else:
            # 优先置顶配置的脚本，其次 dev/serve/start，方便连续两次回车直接运行
            cfg_script = self.settings.script_for(project_path)
            pref = cfg_script if cfg_script in scripts else next(
                (p for p in ("dev", "serve", "start") if p in scripts), None)
            ordered = ([pref] + [s for s in scripts if s != pref]) if pref else scripts
            for s in ordered:
                results.append({
                    "Title": f"{pm} run {s}",
                    "SubTitle": f"node {node_ver}  |  {name}  |  回车执行",
                    "IcoPath": ICON_PATH,
                    "JsonRPCAction": {
                        "method": "run_project",
                        "parameters": [project_path, node_ver, s, pm],
                    },
                })

        # 返回项放最后，避免误触
        results.append({
            "Title": "↩ 返回项目列表",
            "SubTitle": f"node {node_ver}  |  {pm}  |  {name}",
            "IcoPath": ICON_PATH,
            "JsonRPCAction": {
                "method": "back_to_list",
                "parameters": [],
                "dontHideAfterAction": True,
            },
        })
        return results

    # ── 查询解析与脚本读取 ────────────────────────────────

    def _parse_query(self, query: str):
        """拆分查询为 (脚本覆盖, 项目关键字)

        - "template"       → ("", "template")
        - "template build" → ("build", "template")
        """
        if not query:
            return ("", "")
        tokens = query.split()
        last = tokens[-1].lower()
        if len(tokens) > 1 and last in SCRIPT_TOKENS:
            return (SCRIPT_TOKENS[last], " ".join(tokens[:-1]))
        return ("", query)

    @staticmethod
    def _read_scripts(project_path: str) -> list:
        """读取 package.json 中的 scripts 名称列表"""
        pkg = os.path.join(project_path, "package.json")
        try:
            with open(pkg, "r", encoding="utf-8") as f:
                data = json.load(f)
            return list(data.get("scripts", {}).keys())
        except (OSError, json.JSONDecodeError):
            return []

    def _pick_default(self, scripts: list) -> str:
        """挑选默认脚本：dev > serve > start > 配置的默认脚本"""
        for pref in ("dev", "serve", "start"):
            if pref in scripts:
                return pref
        return self.settings.default_script

    # ── 运行项目 ──────────────────────────────────────────

    def run_project(self, project_path: str, node_version: str, script: str, pm: str = "npm"):
        """生成 PowerShell 脚本并启动一个可见窗口运行项目"""
        if not os.path.isdir(project_path):
            return
        script = script or self.settings.default_script or "dev"
        pm = pm if pm in ("pnpm", "npm") else "npm"
        node_dir = self._resolve_node_dir(node_version)

        ps1 = self._build_ps1(project_path, node_dir, node_version, script, pm)
        ps1_path = os.path.join(
            tempfile.gettempdir(),
            f"npm_runner_{int(time.time() * 1000)}.ps1",
        )
        try:
            # 用 utf-8-sig（带 BOM）写入，确保 PowerShell 正确识别中文路径
            with open(ps1_path, "w", encoding="utf-8-sig") as f:
                f.write(ps1)
            self._open_visible_console([
                "powershell.exe",
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-File", ps1_path,
            ])
        except OSError:
            pass

    @staticmethod
    def _open_visible_console(argv):
        """启动一个「可见」的控制台窗口。

        Flow Launcher 用 pythonw.exe（无控制台宿主）运行插件，此时
        subprocess 直接拉起的控制台窗口默认是隐藏的（进程在跑但看不见）。
        改用 CreateProcessW + CREATE_NEW_CONSOLE 强制分配新的可见控制台。"""
        if sys.platform != "win32":
            subprocess.Popen(argv)
            return

        # 按 Win32 命令行转义规则拼接（subprocess.list2cmdline 即此规则）
        cmd_line = subprocess.list2cmdline(argv)

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("lpReserved", ctypes.c_wchar_p),
                ("lpDesktop", ctypes.c_wchar_p),
                ("lpTitle", ctypes.c_wchar_p),
                ("dwX", ctypes.c_ulong), ("dwY", ctypes.c_ulong),
                ("dwXSize", ctypes.c_ulong), ("dwYSize", ctypes.c_ulong),
                ("dwXCountChars", ctypes.c_ulong), ("dwYCountChars", ctypes.c_ulong),
                ("dwFillAttribute", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("wShowWindow", ctypes.c_ushort),
                ("cbReserved2", ctypes.c_ushort),
                ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", ctypes.c_void_p),
                ("hStdOutput", ctypes.c_void_p),
                ("hStdError", ctypes.c_void_p),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", ctypes.c_void_p),
                ("hThread", ctypes.c_void_p),
                ("dwProcessId", ctypes.c_ulong),
                ("dwThreadId", ctypes.c_ulong),
            ]

        CREATE_NEW_CONSOLE = 0x00000010
        STARTF_USESHOWWINDOW = 0x00000001
        SW_SHOW = 5
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOW
        pi = PROCESS_INFORMATION()
        ok = ctypes.windll.kernel32.CreateProcessW(
            None, cmd_line, None, None, False,
            CREATE_NEW_CONSOLE, None, None,
            ctypes.byref(si), ctypes.byref(pi),
        )
        if ok:
            # 关闭句柄，子进程继续运行
            ctypes.windll.kernel32.CloseHandle(pi.hProcess)
            ctypes.windll.kernel32.CloseHandle(pi.hThread)
        else:
            # 兜底：普通方式启动
            subprocess.Popen(argv)

    def _resolve_node_dir(self, version: str):
        """解析指定 node 版本在 nvm 中的安装目录；找不到返回 None"""
        nvm_home = (self.settings.nvm_home
                    or os.environ.get("NVM_HOME")
                    or os.path.join(os.environ.get("APPDATA", ""), "nvm"))

        # 常见命名：vX.Y.Z 或 X.Y.Z
        for cand in (f"v{version}", version):
            p = os.path.join(nvm_home, cand)
            if os.path.isfile(os.path.join(p, "node.exe")):
                return p

        # 兜底：扫描 nvm 目录中名称包含版本号的子目录
        try:
            for entry in os.scandir(nvm_home):
                if (entry.is_dir() and version in entry.name
                        and os.path.isfile(os.path.join(entry.path, "node.exe"))):
                    return entry.path
        except OSError:
            pass
        return None

    def _build_ps1(self, project_path: str, node_dir, node_version: str, script: str, pm: str = "npm") -> str:
        """构建要执行的 PowerShell 脚本内容"""

        def q(s):  # PowerShell 单引号字符串（转义内部单引号）
            return "'" + str(s).replace("'", "''") + "'"

        name = os.path.basename(project_path)
        # 窗口标题：目录名置顶，方便在任务栏区分多个窗口
        title = f"{name} - {pm} run {script}"
        lines = [
            f"$Host.UI.RawUI.WindowTitle = {q(title)}",
        ]

        # 切换 node：把目标版本目录前置到 PATH（免提权、不影响全局）
        if node_dir:
            lines.append(f"$env:Path = {q(node_dir)} + ';' + $env:Path")
        else:
            lines.append(
                f"Write-Host '警告: 未找到 node {node_version} 的安装目录，"
                f"将使用当前 PATH 中的 node' -ForegroundColor Yellow"
            )

        # 尽力而为：把自动打开的浏览器指向指定 Chrome
        chrome = self.settings.chrome_path
        if chrome and os.path.isfile(chrome):
            lines.append(f"$env:BROWSER = {q(chrome)}")

        lines.append(f"Set-Location -LiteralPath {q(project_path)}")

        # 优先直接用目标版本的 node.exe 调 CLI 脚本，绕开 npm.cmd/pnpm.cmd：
        # 批处理壳会改写窗口标题（pnpm.cmd 甚至有 title %COMSPEC%），导致多窗口无法区分
        node_exe = os.path.join(node_dir, "node.exe") if node_dir else None
        cli_js = None
        if node_dir:
            if pm == "pnpm":
                p = os.path.join(node_dir, "node_modules", "pnpm", "bin", "pnpm.cjs")
                cli_js = p if os.path.isfile(p) else None
            else:
                p = os.path.join(node_dir, "node_modules", "npm", "bin", "npm-cli.js")
                cli_js = p if os.path.isfile(p) else None

        if node_exe and cli_js:
            lines.append(
                'Write-Host "==> Node: $(node -v)  |  ' + pm + ' run ' + script + '" -ForegroundColor Cyan'
            )
            lines.append(f"& {q(node_exe)} {q(cli_js)} run {script}")
        elif pm == "pnpm":
            # 兜底：找不到 pnpm CLI 脚本时回退命令方式（含未安装检测）
            lines.append("$pm = 'pnpm'")
            lines.append(
                "if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { "
                "Write-Host '警告: 当前 node 环境未安装 pnpm，回退使用 npm' -ForegroundColor Yellow; "
                "$pm = 'npm' }"
            )
            lines.append(
                'Write-Host "==> Node: $(node -v)  |  $($pm) run ' + script + '" -ForegroundColor Cyan'
            )
            lines.append("& $pm run " + script)
        else:
            lines.append(
                'Write-Host "==> Node: $(node -v)  |  npm run ' + script + '" -ForegroundColor Cyan'
            )
            lines.append(f"npm run {script}")

        # dev/build 结束后重新设置标题（保险：防止任何子进程改写过标题）
        lines.append(f"$Host.UI.RawUI.WindowTitle = {q(title)}")
        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    NpmRunner()
