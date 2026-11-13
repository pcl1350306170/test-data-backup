# -*- coding: utf-8 -*-
"""Node 版本管理：探测 nvm-windows / Volta，用 PATH 注入锁定版本（免 UAC）。

原 .pyw 用 `ShellExecuteW("runas") + nvm use` 提权切换全局版本，服务场景下不可行：
- 服务是 Hub 拉起的后台进程，弹 UAC 会阻塞任务，授权框也出现在服务器本机
- `nvm use` 改的是全局符号链接，一次打包会影响机器上其他项目

改为按需注入：把 `nvm_root/v{version}` 目录前置到子进程 PATH，只影响本次构建，
不动系统状态，也不需要管理员权限。经验证各版本目录内自带 node.exe / npm.cmd，
以及该版本安装的全局包（pnpm/yarn/sass），与手动 nvm use 的构建环境等价。

PATH 中的 Volta 通常排在 nvm 之前，因此当前 `node -v` 可能由 Volta 解析——
注入目标版本目录同样排在 Volta 之前，顺带消除了这层歧义。
"""
import os
import re
import shutil
import sys
from pathlib import Path

from .util import run_capture

IS_WIN = sys.platform == "win32"

DEFAULT_NODE_VERSION = "14.19.1"

_VERSION_LINE_RE = re.compile(r"(\d+\.\d+\.\d+)")
_SETTINGS_ROOT_RE = re.compile(r"^\s*root\s*[:=]\s*(.+?)\s*$", re.M)


def _ver_key(ver):
    try:
        return tuple(int(x) for x in ver.split("."))
    except ValueError:
        return (0, 0, 0)


def nvm_root():
    """定位 nvm-windows 根目录，返回 Path 或 None。"""
    cands = []
    env_home = os.environ.get("NVM_HOME") or os.environ.get("NVM_ROOT")
    if env_home:
        cands.append(Path(env_home))

    nvm_exe = shutil.which("nvm")
    if nvm_exe:
        nvm_dir = Path(nvm_exe).parent
        cands.append(nvm_dir)
        settings = nvm_dir / "settings.txt"
        if settings.is_file():
            try:
                text = settings.read_text(encoding="utf-8", errors="replace")
                m = _SETTINGS_ROOT_RE.search(text)
                if m:
                    cands.insert(0, Path(m.group(1).strip('"')))
            except OSError:
                pass

    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(Path(appdata) / "nvm")
    cands.append(Path(r"D:\dev\nvm"))
    cands.append(Path(r"C:\Program Files\nvm"))

    for p in cands:
        try:
            if p.is_dir() and ((p / "nvm.exe").is_file() or any(p.glob("v*"))):
                return p
        except OSError:
            continue
    return None


def volta_home():
    """Volta 安装目录（其 bin 下有 node.exe 垫片），未安装返回 ''。"""
    volta_exe = shutil.which("volta")
    if volta_exe:
        return str(Path(volta_exe).parent)
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    cands = []
    if local_appdata:
        cands += [Path(local_appdata) / "Volta" / "bin", Path(local_appdata) / "Volta"]
    if user_profile:
        cands.append(Path(user_profile) / ".volta" / "bin")
    cands.append(Path(program_files) / "Volta")
    for p in cands:
        try:
            if (p / "volta.exe").is_file():
                return str(p)
        except OSError:
            continue
    return ""


def version_bin_dir(version):
    """目标版本的 node 目录（含 node.exe / npm.cmd），找不到返回 ''。"""
    version = (version or "").lstrip("v")
    root = nvm_root()
    if not root or not version:
        return ""
    for name in ("v" + version, version):
        d = root / name
        try:
            if (d / "node.exe").is_file():
                return str(d)
        except OSError:
            continue
    return ""


def _versions_from_dir(root):
    out = []
    try:
        for d in root.glob("v*"):
            if (d / "node.exe").is_file():
                m = _VERSION_LINE_RE.search(d.name)
                if m:
                    out.append(m.group(1))
    except OSError:
        return []
    return sorted(set(out), key=_ver_key, reverse=True)


def _versions_from_cli():
    """解析 `nvm list`，返回 (versions, current)。"""
    rc, out, _ = run_capture(["nvm", "list"], timeout=10)
    if rc != 0 or not out:
        return [], ""
    versions, current = [], ""
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _VERSION_LINE_RE.search(stripped)
        if not m:
            continue
        ver = m.group(1)
        if stripped.startswith("*"):
            current = ver
        if ver not in versions:
            versions.append(ver)
    return sorted(versions, key=_ver_key, reverse=True), current


def list_versions():
    """版本列表：目录扫描为主（不依赖 nvm CLI 输出格式），CLI 解析兜底补 current。"""
    root = nvm_root()
    versions = _versions_from_dir(root) if root else []
    cli_versions, current = _versions_from_cli()
    for v in cli_versions:
        if v not in versions:
            versions.append(v)
    versions = sorted(set(versions), key=_ver_key, reverse=True)
    if not current:
        cur = node_version()
        if cur in versions:
            current = cur
    return {
        "versions": versions,
        "current": current,
        "node_current": node_version(),
        "nvm_root": str(root) if root else "",
        "volta_home": volta_home(),
        "default": DEFAULT_NODE_VERSION,
    }


def node_version(env=None):
    """当前生效的 node 版本（不带 v 前缀），失败返回 ''。"""
    rc, out, _ = run_capture(["node", "-v"], env=env, timeout=10)
    return out.strip().lstrip("v") if rc == 0 else ""


def _prepend(env_parts, target):
    """大小写不敏感去重后前置，返回新列表。"""
    norm = {p.rstrip("\\/").lower() for p in env_parts if p}
    key = (target or "").rstrip("\\/").lower()
    if not key:
        return env_parts
    if key in norm:
        env_parts = [p for p in env_parts if p.rstrip("\\/").lower() != key]
    env_parts.insert(0, target)
    return env_parts


def build_env(target_version, log=None):
    """构造子进程 env：目标版本目录前置 PATH（+ Volta 目录，供脚本内部调用 volta）。

    返回 (env, info)。info 供上层记日志与校验：
      {mode: injected|system, node_dir, target, current, volta_home}
    """
    def _log(msg):
        if log:
            log(msg)

    env = os.environ.copy()
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    target = (target_version or "").lstrip("v")
    info = {"mode": "system", "node_dir": "", "target": target,
            "current": node_version(), "volta_home": volta_home()}

    node_dir = version_bin_dir(target)
    if node_dir:
        parts = _prepend(parts, node_dir)
        info["mode"] = "injected"
        info["node_dir"] = node_dir
        _log("🔧 已注入 Node 版本目录（免管理员权限）: %s" % node_dir)
    else:
        _log("ℹ️ nvm 未安装 v%s 或未找到 nvm 根目录，沿用系统 PATH 中的 node"
             "（当前 v%s）" % (target or "-", info["current"] or "-"))
        # 未注入时保留病房脚本原有做法：确保 volta 可执行（deploy 脚本内部会调 volta）
        if info["volta_home"]:
            parts = _prepend(parts, info["volta_home"])

    env["PATH"] = os.pathsep.join(parts)
    env["PYTHONIOENCODING"] = "utf-8"
    return env, info


def verify_env(env, target, log=None):
    """用注入后的 env 实际跑一次 node -v，确认版本真的生效。"""
    actual = node_version(env=env)
    if log:
        if not actual:
            log("❌ 注入环境中无法执行 node -v，请确认 Node.js 已安装")
        elif actual == (target or "").lstrip("v"):
            log("✅ 构建用 Node 版本: v%s" % actual)
        else:
            log("⚠️ 期望 v%s，注入环境实际为 v%s（将继续使用该环境构建）"
                % ((target or "").lstrip("v"), actual))
    return actual
