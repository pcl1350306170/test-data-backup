# -*- coding: utf-8 -*-
"""公共小工具：子进程调用、JSON 原子写、时间/大小格式化。"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0


def py_dir():
    """仓内 py/ 根目录（用于定位旧 .pyw 的 json/ 配置做迁移）。"""
    return Path(__file__).resolve().parents[2]


def read_json(path, default=None):
    """读 JSON，失败返回 default（不抛异常，配置缺失属正常情况）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    """原子写 JSON：先写 .tmp 再 replace，避免中途断电留下半截文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def run_capture(argv, cwd=None, timeout=30, env=None):
    """执行命令并返回 (returncode, stdout, stderr)；命令不存在返回 (None, '', 错误)。"""
    try:
        r = subprocess.run(
            argv, cwd=str(cwd) if cwd else None, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=NO_WINDOW)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError as e:
        return None, "", "命令不存在: %s" % e
    except subprocess.TimeoutExpired:
        return None, "", "命令超时(%ss): %s" % (timeout, " ".join(map(str, argv)))
    except Exception as e:
        return None, "", "%s: %s" % (type(e).__name__, e)


def kill_tree(pid, log=None):
    """终止进程树（npm.cmd / bash 会派生子进程，只杀父进程杀不干净）。"""
    if not pid:
        return False
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, creationflags=NO_WINDOW, timeout=15)
        else:
            os.killpg(pid, 15)
        if log:
            log("🛑 已终止子进程树 PID=%s" % pid)
        return True
    except Exception as e:
        if log:
            log("⚠️ 终止进程失败 PID=%s: %s" % (pid, e))
        return False


def mtime_str(path):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(str(path))))
    except OSError:
        return ""


def dir_mtime(path):
    """目录自身 mtime，用于“多个匹配结果默认选最近更新的那个”。"""
    try:
        return os.path.getmtime(str(path))
    except OSError:
        return 0


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f%s" % (n, unit) if unit != "B" else "%d%s" % (n, unit)
        n /= 1024
    return "%.1fTB" % n
