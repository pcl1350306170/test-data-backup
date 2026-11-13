# -*- coding: utf-8 -*-
"""病房订单打包 profile。

流程（与桌面版 病房打包.pyw 一致）：
  1. 定位 Git Bash（必须排除 WSL 转发器，它会吃掉 Windows 路径的反斜杠）
  2. 锁定 Node 版本（PATH 注入；未装 nvm 时退回 Volta 注入）
  3. bash deploy.sh / deploy-micro.sh（web 3.4.4+ 用 micro 脚本）
  4. 在 dist 目录找产物 tar.gz，并用 mtime 防误判旧包
  5. 清理 SVN 目录里的同系列旧包（优先 svn delete，让删除也进同一次提交）
  6. 产物剪切到 SVN 目录，按需提交
"""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from .. import node_env, util, vcs
from .base import Profile, _is_dir

CODE_BASE_DIR = Path(r"D:\CODE\Yarward\病房")
SVN_BASE_DIR = Path(r"D:\CODE\Yarward\SVN\病房")

PROJECT_TYPE_MAP = {"web": "web", "床头": "床头", "床旁": "床旁", "护理看板": "看板"}
PACKAGE_PREFIX_MAP = {"web": "dist", "床头": "bedhead", "床旁": "bedside", "护理看板": "ntv"}

_TS_STEM_RE = re.compile(r"^(.*[_-])\d{10,14}$")


def find_bash_executable():
    """找 Git Bash：优先 PATH 中的 bash（排除 WSL 转发器），再查常见安装路径与注册表。"""
    path_bash = shutil.which("bash")
    if path_bash and _is_git_bash(path_bash):
        return path_bash

    candidates = [
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
        Path(r"D:\Program Files\Git\bin\bash.exe"),
        Path(r"D:\Git\bin\bash.exe"),
        Path(os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\bash.exe")),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)

    try:
        import winreg
        for key_path in (r"SOFTWARE\GitForWindows", r"SOFTWARE\WOW6432Node\GitForWindows"):
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                winreg.CloseKey(key)
                bash = Path(install_path) / "bin" / "bash.exe"
                if bash.is_file():
                    return str(bash)
            except OSError:
                continue
    except Exception:
        pass
    return ""


def _is_git_bash(bash_cmd):
    """True 表示是 Git Bash（mingw/msys），False 表示 WSL 转发器。"""
    if "windowsapps" in Path(bash_cmd).parent.as_posix().lower():
        return False
    rc, out, _ = util.run_capture([bash_cmd, "--version"], timeout=5)
    if rc != 0:
        return False
    text = (out or "").lower()
    return "mingw" in text or "msys" in text


def deploy_script_name(project_type, is_new_version):
    if project_type == "web" and is_new_version:
        return "deploy-micro.sh"
    return "deploy.sh"


def find_built_package(project_dir, prefix):
    """dist 目录下找打包产物：web 找 dist.tar.gz，其他找 {prefix}-*.tar.gz（取最新）。"""
    dist = Path(project_dir) / "dist"
    if not dist.is_dir():
        return None
    if prefix == "dist":
        target = dist / "dist.tar.gz"
        if target.is_file():
            return target
        for f in sorted(dist.iterdir()):
            if f.name.endswith((".tar.gz", ".zip")):
                return f
        return None
    matches = sorted(dist.glob("%s-*.tar.gz" % prefix))
    if matches:
        return matches[-1]
    for f in sorted(dist.iterdir()):
        if f.name.endswith(".tar.gz"):
            return f
    return None


def old_package_pattern(package_name):
    """从新包名提取「时间戳前的前缀」，得到同系列旧包的 glob；无时间戳则同名匹配。"""
    stem = package_name
    for ext in (".tar.gz", ".tgz", ".zip"):
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break
    else:
        stem = Path(stem).stem
    m = _TS_STEM_RE.match(stem)
    return "%s*.tar.gz" % m.group(1) if m else package_name


class WardProfile(Profile):
    ID = "ward_packager"
    TITLE = "病房订单打包"
    ICON = "🏥"
    HISTORY_DEDUP_KEY = "_dedup_key"
    PACKAGE_EXTS = (".tar.gz", ".tgz", ".zip")
    VERSION_OPTIONS = ("3.1.4", "3.1.6", "3.4.0", "3.4.3", "3.4.4")
    PROJECT_TYPES = tuple(PROJECT_TYPE_MAP.keys())
    DEFAULT_CONFIG = {
        "port": 8803,
        "project_type": "床旁",
        "keyword": "",
        "code_base_dir": str(CODE_BASE_DIR),
        "svn_base_dir": str(SVN_BASE_DIR),
        "project_dir": "",
        "svn_dir": "",
        "auto_commit_svn": False,
        "is_new_version": False,
        "node_version": node_env.DEFAULT_NODE_VERSION,
        "history_records": [],
    }
    LEGACY_CONFIG_PATHS = (util.py_dir() / "yarward" / "json" / "config_ward_order_packager.json",)

    def roots(self, cfg):
        return [cfg.get("svn_base_dir", ""), cfg.get("code_base_dir", "")]

    # ── 搜索 ──────────────────────────────────────────

    def search(self, keyword, cfg, params=None):
        keyword = (keyword or "").strip()
        ptype = (params or {}).get("project_type") or cfg.get("project_type", "床旁")
        sub = PROJECT_TYPE_MAP.get(ptype, "")
        svn_dirs = vcs.dirs_by_name(cfg.get("svn_base_dir", ""), keyword)
        projects = vcs.dirs_by_branch(cfg.get("code_base_dir", ""), keyword, sub_dir=sub)

        suggestion = {}
        if projects:
            suggestion["project_dir"] = projects[0]["path"]
            suggestion["project_version"] = projects[0]["version"]
            suggestion["git_branch"] = projects[0]["branch"]
        if svn_dirs:
            suggestion["svn_dir"] = svn_dirs[0]["path"]
            suggestion["svn_work_dir"] = str(vcs.frontend_subdir(Path(svn_dirs[0]["path"])))

        return {
            "keyword": keyword,
            "project_type": ptype,
            "project_types": list(self.PROJECT_TYPES),
            "svn_dirs": svn_dirs,
            "projects": projects,
            "suggestion": suggestion,
            "deploy_script": deploy_script_name(ptype, (params or {}).get("is_new_version",
                                                     cfg.get("is_new_version", False))),
            "code_base_dir": cfg.get("code_base_dir", ""),
            "svn_base_dir": cfg.get("svn_base_dir", ""),
        }

    # ── 自动回填 ──────────────────────────────────────

    def prefill(self, cfg, params):
        out = {}
        svn_dir = (params or {}).get("svn_dir", "")
        if svn_dir and _is_dir(svn_dir):
            work_dir = vcs.frontend_subdir(Path(svn_dir))
            out["svn_work_dir"] = str(work_dir)
            out["has_frontend"] = work_dir != Path(svn_dir)
            out["svn_work_copy"] = vcs.svn_work_copy(work_dir) or ""

        project_dir = (params or {}).get("project_dir", "")
        if project_dir and _is_dir(project_dir):
            branch = vcs.git_branch(project_dir)
            out["git_branch"] = branch
            out["project_version"] = vcs.version_from_branch(branch)
            ptype = (params or {}).get("project_type") or cfg.get("project_type", "床旁")
            script = deploy_script_name(ptype, (params or {}).get("is_new_version"))
            out["deploy_script"] = script
            out["has_deploy_script"] = (Path(project_dir) / script).is_file()
            pkg = find_built_package(project_dir, PACKAGE_PREFIX_MAP.get(ptype, "dist"))
            out["current_package"] = pkg.name if pkg else ""
        return out

    # ── 校验 ──────────────────────────────────────────

    def _extra_validate(self, p):
        errors = []
        ptype = p.get("project_type", "")
        if ptype not in PROJECT_TYPE_MAP:
            errors.append("项目类型非法：%s（可选 %s）" % (ptype, "、".join(self.PROJECT_TYPES)))
        if not p.get("svn_dir"):
            errors.append("请先选择 SVN 目录")
        elif not _is_dir(p["svn_dir"]):
            errors.append("SVN 目录不存在：%s" % p["svn_dir"])
        script = deploy_script_name(ptype, p.get("is_new_version"))
        if p.get("project_dir") and not (Path(p["project_dir"]) / script).is_file():
            errors.append("项目目录下未找到 %s：%s" % (script, p["project_dir"]))
        return errors

    # ── 执行 ──────────────────────────────────────────

    def run(self, params, ctx):
        project_dir = Path(params["project_dir"])
        svn_dir = Path(params["svn_dir"])
        ptype = params["project_type"]
        prefix = PACKAGE_PREFIX_MAP.get(ptype, "dist")
        script = deploy_script_name(ptype, params.get("is_new_version"))
        work_dir = vcs.frontend_subdir(svn_dir)

        ctx.set_result(project_dir=str(project_dir), svn_dir=str(svn_dir),
                       svn_work_dir=str(work_dir), project_type=ptype,
                       deploy_script=script)

        # 1. bash
        ctx.stage("定位 Git Bash", 1, 5)
        bash_path = find_bash_executable()
        if not bash_path:
            raise RuntimeError("未找到 Git Bash，请确认已安装 Git for Windows")
        ctx.log("✅ 使用 bash: %s" % bash_path)

        # 2. Node
        ctx.stage("锁定 Node 版本", 2, 5)
        env, info = node_env.build_env(params.get("node_version"), ctx.log)
        target = (params.get("node_version") or "").lstrip("v")
        actual = node_env.verify_env(env, target, ctx.log)
        if target and actual != target and info.get("mode") != "injected":
            raise RuntimeError(
                "构建需要 Node v%s，系统当前为 v%s，且未找到可注入的 nvm 版本目录。"
                "请在下拉里改选已安装的版本，或先 nvm install %s"
                % (target, actual or "未知", target))
        ctx.check_stop()

        # 3. 部署脚本
        ctx.stage("执行 %s" % script, 3, 5)
        build_start = datetime.now()
        script_path = project_dir / script
        if not script_path.is_file():
            raise RuntimeError("未找到部署脚本：%s" % script_path)
        rc = ctx.run_stream([bash_path, script_path.as_posix()], cwd=project_dir, env=env,
                            shell=False, label="bash %s（%s）" % (script, project_dir.name))
        if rc != 0:
            ctx.log("⚠️ 部署脚本返回码 %s（脚本内部常有非致命报错，继续检查产物）" % rc)

        # 4. 产物
        ctx.stage("查找打包产物", 4, 5)
        package_file = find_built_package(project_dir, prefix)
        if not package_file:
            raise RuntimeError("dist 目录下未找到打包产物（%s-*.tar.gz）" % prefix)
        pkg_mtime = datetime.fromtimestamp(package_file.stat().st_mtime)
        if (build_start - pkg_mtime).total_seconds() > 2:
            raise RuntimeError(
                "找到的是本次执行之前的旧包（%s：%s），本次未产出新包"
                % (package_file.name, pkg_mtime.strftime("%Y-%m-%d %H:%M:%S")))
        ctx.log("✅ 打包产物: %s（%s）" % (package_file.name,
                                   util.human_size(package_file.stat().st_size)))

        # 5. 旧包清理 + 剪切
        ctx.stage("归位到 SVN 目录", 5, 5)
        self._clean_old_packages(work_dir, package_file.name, ctx)
        target_path = work_dir / package_file.name
        if target_path.exists():
            target_path.unlink()
        shutil.move(str(package_file), str(target_path))
        ctx.log("✅ 产物已剪切到: %s" % target_path)
        ctx.set_result(package_path=str(target_path), package_name=package_file.name,
                       size=target_path.stat().st_size,
                       size_str=util.human_size(target_path.stat().st_size),
                       svn_work_copy=vcs.svn_work_copy(work_dir) or "")

        if params.get("auto_commit_svn"):
            commit(ctx, target_path, work_dir)

    # ── 旧包清理 ──────────────────────────────────────

    def _clean_old_packages(self, work_dir, new_name, ctx):
        if not work_dir.is_dir():
            return
        pattern = old_package_pattern(new_name)
        olds = [f for f in sorted(work_dir.glob(pattern)) if f.name != new_name]
        if not olds:
            ctx.log("ℹ️ 未发现同系列旧包（pattern: %s）" % pattern)
            return
        ctx.log("🔍 匹配到 %d 个同系列旧包（pattern: %s）" % (len(olds), pattern))
        for f in olds:
            try:
                rc, out, err = util.run_capture(["svn", "delete", str(f)],
                                                cwd=work_dir, timeout=15)
                if rc == 0:
                    ctx.log("🗑️ SVN 标记删除旧包: %s" % f.name)
                    continue
                if err and "not under version control" in err.lower():
                    ctx.log("ℹ️ 旧包未纳入 SVN，稍后随文件一并处理: %s" % f.name)
                else:
                    ctx.log("⚠️ svn delete 未生效: %s（%s）" % (f.name, (err or out)[:120]))
            except Exception as e:
                ctx.log("⚠️ 处理旧包失败 %s: %s" % (f.name, e))

    # ── 历史 ──────────────────────────────────────────

    def history_record(self, params, result):
        project_dir = params.get("project_dir", "")
        svn_dir = params.get("svn_dir", "")
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_type": params.get("project_type", ""),
            "project_dir": project_dir,
            "svn_dir": svn_dir,
            "package_name": result.get("package_name", ""),
            "keyword": params.get("keyword", ""),
            "auto_commit_svn": bool(params.get("auto_commit_svn")),
            "node_version": params.get("node_version", ""),
            "is_new_version": bool(params.get("is_new_version")),
            "branch": result.get("git_branch", ""),
            "_dedup_key": "%s_%s" % (project_dir, svn_dir),
        }

    def commit(self, ctx, package_path, work_dir=""):
        return commit(ctx, package_path, work_dir or "")

    def meta(self, cfg):
        base = super().meta(cfg)
        base["project_types"] = list(self.PROJECT_TYPES)
        base["prefix_map"] = dict(PACKAGE_PREFIX_MAP)
        return base


def commit(ctx, package_path, work_dir=None):
    """add 新包 + commit 整个工作目录（这样 svn delete 的旧包也一起提交）。"""
    package_path = Path(package_path)
    work_dir = Path(work_dir) if work_dir else package_path.parent
    wc = vcs.svn_work_copy(work_dir)
    if not wc:
        ctx.log("⚠️ 未找到 SVN 工作副本（从 %s 向上查找），跳过提交" % work_dir)
        return False
    if Path(wc) != work_dir:
        ctx.log("ℹ️ SVN 工作副本根目录: %s" % wc)
    message = "病房订单打包：%s - %s" % (package_path.name,
                                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ok = vcs.svn_commit_file(package_path, wc, message, ctx.log, target=work_dir)
    ctx.set_result(svn_committed=ok, svn_work_copy=wc, svn_message=message)
    return ok


profile = WardProfile()
