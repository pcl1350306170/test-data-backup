# -*- coding: utf-8 -*-
"""Git / SVN 相关操作：分支扫描、工作副本查找、提交。

从门诊/病房两个 .pyw 里抽取出来的公共部分，行为保持一致：
- 分支名匹配关键字的项目目录（而不是目录名匹配）
- 匹配到多条时由调用方按 mtime 选“最近更新”的那条
- svn add 遇到 already under version control 视为正常，继续 commit
"""
import os
import re
import shutil
from pathlib import Path

from .util import dir_mtime, mtime_str, run_capture

_SKIP_DIRS = {".svn", "node_modules", "dist", ".git"}

_VERSION_RE = re.compile(r"dev_(\d+\.\d+\.\d+)_")
_ANY_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def git_branch(directory):
    """获取目录当前分支名；旧版 git 不支持 --show-current 时回退 rev-parse。"""
    rc, out, _ = run_capture(["git", "branch", "--show-current"],
                             cwd=directory, timeout=10)
    if rc == 0 and out:
        return out
    rc, out, _ = run_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=directory, timeout=10)
    return out if rc == 0 else ""


def git_tool_available():
    return shutil.which("git") is not None


def svn_tool_available():
    return shutil.which("svn") is not None


def version_from_branch(branch):
    """分支 dev_1.5.1_某某医院 → 1.5.1；病房分支 3.1.6_某某 → 3.1.6。"""
    m = _VERSION_RE.search(branch or "")
    if m:
        return m.group(1)
    m = _ANY_VERSION_RE.match(branch or "")
    return m.group(1) if m else ""


def dirs_by_branch(base_dir, keyword, sub_dir=""):
    """base_dir[/sub_dir] 下所有 git 分支名含 keyword 的目录。

    返回 [{path,name,branch,version,mtime,mtime_str}]，按 mtime 倒序。
    """
    search = Path(base_dir) / sub_dir if sub_dir else Path(base_dir)
    out = []
    if not search.is_dir():
        return out
    kw = (keyword or "").lower()
    for item in search.iterdir():
        if not item.is_dir():
            continue
        branch = git_branch(item)
        if not branch or (kw and kw not in branch.lower()):
            continue
        out.append({
            "path": str(item),
            "name": item.name,
            "branch": branch,
            "version": version_from_branch(branch),
            "mtime": dir_mtime(item),
            "mtime_str": mtime_str(item),
        })
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def dirs_by_name(base_dir, keyword, sub_dir=""):
    """base_dir[/sub_dir] 下目录名含 keyword 的子目录（SVN 侧用名称匹配）。"""
    search = Path(base_dir) / sub_dir if sub_dir else Path(base_dir)
    out = []
    if not search.is_dir():
        return out
    kw = (keyword or "").lower()
    for item in search.iterdir():
        if not item.is_dir():
            continue
        if kw and kw not in item.name.lower():
            continue
        out.append({
            "path": str(item),
            "name": item.name,
            "mtime": dir_mtime(item),
            "mtime_str": mtime_str(item),
        })
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def find_files(root, prefix="", suffix="", max_depth=4):
    """递归找文件名匹配 prefix/suffix 的文件（基础压缩包等），按 mtime 倒序。

    跳过 .svn/node_modules/dist/.git，避免扫到无关目录拖慢搜索。
    """
    root = Path(root)
    if not root.is_dir():
        return []
    root_str = str(root)
    hits = []
    for cur, dirs, files in os.walk(root_str):
        rel_depth = Path(cur).relative_to(root).parts if cur != root_str else ()
        if len(rel_depth) > max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if prefix and not f.startswith(prefix):
                continue
            if suffix and not f.endswith(suffix):
                continue
            p = Path(cur) / f
            try:
                st = p.stat()
            except OSError:
                continue
            hits.append({
                "path": str(p),
                "name": f,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "mtime_str": mtime_str(p),
            })
    hits.sort(key=lambda d: d["mtime"], reverse=True)
    return hits


def svn_work_copy(start_dir, depth=5):
    """从目录向上找 .svn，返回工作副本根路径；找不到返回 ''。"""
    cur = Path(start_dir)
    for _ in range(depth):
        if (cur / ".svn").is_dir():
            return str(cur)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return ""


def frontend_subdir(svn_dir):
    """SVN 订单目录下若有“前端”子目录则用它，否则用目录本身（两个脚本同规则）。"""
    p = Path(svn_dir) / "前端"
    return p if p.is_dir() else Path(svn_dir)


def svn_commit_file(file_path, working_copy, message, log=None, target=None):
    """add 单个文件 + commit。

    target 为提交目标路径：病房需要提交整个工作目录（让 svn delete 的旧包一起生效），
    门诊留空即只提交该文件。
    """
    def _log(msg):
        if log:
            log(msg)

    if not svn_tool_available():
        _log("❌ 未找到 svn 命令，请确保已安装 SVN 命令行工具")
        return False

    rc, out, err = run_capture(["svn", "add", str(file_path)],
                               cwd=working_copy, timeout=30)
    if rc == 0:
        _log("✅ SVN Add 成功: %s" % (out or "已加入版本控制"))
    elif "already under version control" in (err or "").lower() or \
            "already under version control" in (out or "").lower():
        _log("ℹ️ 文件已在版本控制中，跳过 Add")
    else:
        _log("⚠️ SVN Add 警告: %s" % (err or out))

    rc, out, err = run_capture(["svn", "commit", "-m", message, str(target or file_path)],
                               cwd=working_copy, timeout=180)
    if rc == 0:
        _log("✅ SVN 提交成功")
        for line in (out or "").splitlines():
            if line.strip():
                _log("   %s" % line.strip())
        return True
    _log("❌ SVN 提交失败: %s" % (err or out))
    return False
