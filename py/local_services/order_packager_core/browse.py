# -*- coding: utf-8 -*-
"""受限目录浏览：替代 Tk 的 filedialog（服务端进程没有界面，也不能弹本机对话框）。

安全边界：所有路径必须落在配置里登记的根目录（SVN/Git 基础目录）之下，
避免页面被拿去浏览整块磁盘。服务定位是本机专用，但同一内网仍可能有人打开页面，
所以宁可收紧。
"""
import os
import string
from pathlib import Path

from .util import human_size, mtime_str

MAX_ENTRIES = 800


class PathDenied(Exception):
    """路径越界或非法。"""


def _norm(path):
    return os.path.normcase(os.path.abspath(str(path)))


def check_root(path, roots):
    """校验 path 是否位于任一 root 之下（含 root 自身）。返回规范化绝对路径。"""
    raw = (path or "").strip().strip('"')
    if not raw:
        raise PathDenied("路径为空")
    target = Path(raw)
    if not target.is_absolute():
        raise PathDenied("必须使用绝对路径: %s" % raw)
    if not target.is_dir():
        raise PathDenied("目录不存在: %s" % raw)
    t_norm = _norm(target)
    allowed = [r for r in (roots or []) if r]
    if not allowed:
        raise PathDenied("未配置可浏览的根目录")
    for root in allowed:
        r_norm = _norm(root)
        if t_norm == r_norm or t_norm.startswith(r_norm + os.sep):
            return str(target)
    raise PathDenied("路径不在允许范围内: %s（允许: %s）" % (raw, ", ".join(allowed)))


def list_dir(path, roots, exts=None, include_dirs=True, include_files=True):
    """列目录：返回 {path, parent, dirs, files}，dirs 带 git/svn 标记便于页面展示。"""
    target = check_root(path, roots)
    p = Path(target)
    dirs, files = [], []
    try:
        entries = sorted(p.iterdir(), key=lambda e: e.name.lower())
    except OSError as e:
        raise PathDenied("读取目录失败: %s" % e)

    for e in entries:
        try:
            is_dir = e.is_dir()
        except OSError:
            continue
        if is_dir:
            if not include_dirs or e.name.startswith("."):
                continue
            if len(dirs) >= MAX_ENTRIES:
                continue
            info = {
                "name": e.name,
                "path": str(e),
                "mtime_str": mtime_str(e),
                "is_git": (e / ".git").exists(),
                "is_svn": (e / ".svn").is_dir(),
            }
            if (e / ".git").exists():
                from .vcs import git_branch, version_from_branch
                branch = git_branch(e)
                info["branch"] = branch
                info["version"] = version_from_branch(branch)
            dirs.append(info)
        else:
            if not include_files:
                continue
            # 用 endswith 而不是 Path.suffix：tar.gz 这类复合后缀 suffix 只会取 .gz
            lower_name = e.name.lower()
            if exts and not any(lower_name.endswith(x.lower()) for x in exts):
                continue
            if len(files) >= MAX_ENTRIES:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            files.append({
                "name": e.name,
                "path": str(e),
                "size": st.st_size,
                "size_str": human_size(st.st_size),
                "mtime_str": mtime_str(e),
            })

    dirs.sort(key=lambda d: d["mtime_str"], reverse=True)
    files.sort(key=lambda d: d["mtime_str"], reverse=True)
    parent = str(p.parent) if p.parent != p else ""
    return {"path": target, "parent": parent, "roots": list(roots or []),
            "dirs": dirs, "files": files}


def drive_roots():
    """本机盘符列表（页面“换个根目录看看”时的起点提示）。"""
    out = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            cand = "%s:\\" % letter
            try:
                if os.path.isdir(cand):
                    out.append(cand)
            except OSError:
                continue
    return out
