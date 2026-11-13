# -*- coding: utf-8 -*-
"""门诊订单打包 profile。

流程（与桌面版 门诊打包.pyw 一致）：
  1. 锁定 Node 版本（PATH 注入，免 UAC）
  2. 清理 dist / lib-render-dist
  3. npm run build
  4. 1.5.5 以下再跑 npm run lib-render2
  5. 解压基础压缩包 → 用构建产物替换 design / resource → 生成成品 ZIP（同名直接覆盖）
  6. 按需 SVN 提交（服务里默认关闭，由页面「提交到 SVN」按钮单独触发）
"""
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .. import node_env, util, vcs
from .base import Profile, _is_dir, _is_file

try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False

SVN_BASE_DIR = Path(r"D:\CODE\Yarward\SVN\0门诊")
GIT_BASE_DIR = Path(r"D:\CODE\Yarward\门诊")
BASE_ZIP_PREFIX = "YM-801S-TLSS-"
BASE_ZIP_SUFFIX = "-FE.zip"
# 基础压缩包名里带的版本号：YM-801S-TLSS-V1.5.1.xxxx... → 1.5.1
_ZIP_VERSION_RE = re.compile(r"-V(\d+\.\d+\.\d+)\.")


def pinyin_initials(text):
    """医院名 → 拼音首字母大写，用于成品 ZIP 命名。"""
    if HAS_PINYIN:
        try:
            initials = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER))
            result = "".join(c for c in initials.upper() if c.isalpha())
            if result:
                return result
        except Exception:
            pass
    letters = [c for c in (text or "") if c.isalpha()]
    return "".join(letters).upper() or "UNKNOWN"


def build_zip_name(order_info, version, custom=""):
    """按桌面版规则生成 ZIP 文件名，返回 (文件名, 说明)。"""
    custom = (custom or "").strip()
    if custom:
        name = custom if custom.lower().endswith(".zip") else custom + ".zip"
        return name, "使用自定义名称"
    info = (order_info or "").strip()
    if len(info) < 9:
        return "%s.zip" % version, "订单信息不足 9 位，使用默认名称"
    order_id, hospital = info[:9], info[9:]
    parts = order_id.split("-")
    if len(parts) != 2:
        return "%s.zip" % version, "订单号格式不匹配（应为 2026-1234），使用默认名称"
    year_part, order_num = parts[0][-2:], parts[1]
    name = "YM-801S-TLSS-V%s.%s%s.01001-%s-FE.zip" % (
        version, year_part, order_num, pinyin_initials(hospital))
    return name, "订单号 %s，医院首字母 %s" % (order_id, pinyin_initials(hospital))


def _clear_dir(target):
    """清空目录内容（不删目录本身）。"""
    for item in target.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def _copy_tree(src, dst):
    """把 src 的内容拷进 dst（dst 需已存在）。"""
    for item in src.iterdir():
        dest = dst / item.name
        if item.is_file():
            shutil.copy2(item, dest)
        elif item.is_dir():
            shutil.copytree(item, dest)


def _strip_frontend_suffix(name):
    """SVN 目录名尾部若是「-前端」「前端」去掉，得到订单信息。"""
    if name.endswith("-前端"):
        return name[:-3]
    if name.endswith("前端"):
        return name[:-2]
    return name


class MenzProfile(Profile):
    ID = "menz_packager"
    TITLE = "门诊订单打包"
    ICON = "📦"
    HISTORY_DEDUP_KEY = "order_info"
    PACKAGE_EXTS = (".zip",)
    VERSION_OPTIONS = ("1.5.0", "1.5.1", "1.5.2", "1.5.3", "1.5.4", "1.5.5", "1.5.6")
    DEFAULT_CONFIG = {
        "port": 8802,
        "svn_base_dir": str(SVN_BASE_DIR),
        "git_base_dir": str(GIT_BASE_DIR),
        "keyword": "",
        "project_dir": "",
        "output_dir": "",
        "order_info": "",
        "project_version": "",
        "base_zip_path": "",
        "custom_zip_name": "",
        "auto_commit_svn": False,
        "is_version_155_plus": False,
        "node_version": node_env.DEFAULT_NODE_VERSION,
        "history_records": [],
    }
    LEGACY_CONFIG_PATHS = (util.py_dir() / "yarward" / "json" / "config_menz_order_packager.json",)

    def roots(self, cfg):
        return [cfg.get("svn_base_dir", ""), cfg.get("git_base_dir", "")]

    # ── 搜索 ──────────────────────────────────────────

    def search(self, keyword, cfg, params=None):
        keyword = (keyword or "").strip()
        svn_dirs = vcs.dirs_by_name(cfg.get("svn_base_dir", ""), keyword)
        projects = vcs.dirs_by_branch(cfg.get("git_base_dir", ""), keyword)

        suggestion = {}
        base_zips = []
        if svn_dirs:
            top = Path(svn_dirs[0]["path"])
            out_dir = vcs.frontend_subdir(top)
            suggestion["output_dir"] = str(out_dir)
            suggestion["order_info"] = _strip_frontend_suffix(top.name)
            base_zips = vcs.find_files(top, BASE_ZIP_PREFIX, BASE_ZIP_SUFFIX)
            if base_zips:
                suggestion["base_zip_path"] = base_zips[0]["path"]
                suggestion["base_zip_name"] = base_zips[0]["name"]
        if projects:
            suggestion["project_dir"] = projects[0]["path"]
            suggestion["project_version"] = projects[0]["version"]
            suggestion["git_branch"] = projects[0]["branch"]

        return {
            "keyword": keyword,
            "svn_dirs": svn_dirs,
            "projects": projects,
            "suggestion": suggestion,
            "base_zips": base_zips,
            "svn_base_dir": cfg.get("svn_base_dir", ""),
            "git_base_dir": cfg.get("git_base_dir", ""),
        }

    # ── 自动回填 ──────────────────────────────────────

    def prefill(self, cfg, params):
        """页面点选 SVN 目录 / Git 项目后的回填信息（等价于桌面版的双击自动填充）。"""
        out = {}
        svn_dir = (params or {}).get("svn_dir", "")
        if svn_dir and _is_dir(svn_dir):
            work_dir = vcs.frontend_subdir(Path(svn_dir))
            zips = vcs.find_files(Path(svn_dir), BASE_ZIP_PREFIX, BASE_ZIP_SUFFIX)
            out["output_dir"] = str(work_dir)
            out["has_frontend"] = work_dir != Path(svn_dir)
            out["order_info"] = _strip_frontend_suffix(Path(svn_dir).name)
            out["base_zips"] = zips
            out["base_zip_count"] = len(zips)
            if zips:
                out["base_zip_path"] = zips[0]["path"]
                out["base_zip_name"] = zips[0]["name"]
                # 成品 ZIP 的版本号必须跟基础包一致，否则命名会用错 V 段
                m = _ZIP_VERSION_RE.search(zips[0]["name"])
                if m:
                    out["project_version"] = m.group(1)
                    out["version_source"] = "base_zip"
                out["notice"] = ("已定位输出目录，基础压缩包 %d 个（最新 %s）"
                                 % (len(zips), zips[0]["name"]))
            else:
                out["notice"] = ("该 SVN 目录下未找到 %s****%s 格式的基础压缩包，"
                                 "请手动选择" % (BASE_ZIP_PREFIX, BASE_ZIP_SUFFIX))

        project_dir = (params or {}).get("project_dir", "")
        if project_dir and _is_dir(project_dir):
            branch = vcs.git_branch(project_dir)
            out["git_branch"] = branch
            version = vcs.version_from_branch(branch)
            # 分支推出来的版本优先（比包名更新，说明已经换分支）
            out["project_version"] = version
            out["version_source"] = "git_branch"
            if not version:
                out["version_notice"] = "无法从分支名 %s 提取版本号，请手动选择" % (branch or "(空)")
        return out

    # ── 校验 ──────────────────────────────────────────

    def _extra_validate(self, p):
        errors = []
        if not p.get("output_dir"):
            errors.append("请先选择输出目录（SVN 前端目录）")
        if not p.get("base_zip_path"):
            errors.append("请先选择基础压缩包")
        elif not _is_file(p["base_zip_path"]):
            errors.append("基础压缩包不存在：%s" % p["base_zip_path"])
        if not p.get("order_info"):
            errors.append("请填写订单信息（前 9 位订单号 + 医院名）")
        if not p.get("project_version"):
            errors.append("请选择或输入项目版本")
        return errors

    # ── 历史 / 提交 ───────────────────────────────────

    def history_record(self, params, result):
        """字段与桌面版 config_menz_order_packager.json 里的记录保持一致。"""
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_dir": params.get("project_dir", ""),
            "output_dir": params.get("output_dir", ""),
            "order_info": params.get("order_info", ""),
            "project_version": params.get("project_version", ""),
            "base_zip_path": params.get("base_zip_path", ""),
            "custom_zip_name": params.get("custom_zip_name", ""),
            "auto_commit_svn": bool(params.get("auto_commit_svn")),
            "is_version_155_plus": bool(params.get("is_version_155_plus")),
            "node_version": params.get("node_version", ""),
            "package_name": result.get("package_name", ""),
        }

    def commit(self, ctx, package_path, work_dir=""):
        return commit(ctx, package_path)

    # ── 执行 ──────────────────────────────────────────

    def run(self, params, ctx):
        project_dir = Path(params["project_dir"])
        output_dir = Path(params["output_dir"])
        base_zip = Path(params["base_zip_path"])
        is_155 = bool(params.get("is_version_155_plus"))
        version = params["project_version"]
        dist_dir = project_dir / "dist"
        lib_dir = project_dir / "lib-render-dist"

        total = 5 + (0 if is_155 else 1)
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx.set_result(output_dir=str(output_dir), project_dir=str(project_dir),
                       version=version, order_info=params.get("order_info", ""),
                       base_zip=str(base_zip))

        # 1. Node 版本
        ctx.stage("锁定 Node 版本", 1, total)
        env, info = node_env.build_env(params.get("node_version"), ctx.log)
        target = (params.get("node_version") or "").lstrip("v")
        actual = node_env.verify_env(env, target, ctx.log)
        if target and actual != target:
            raise RuntimeError(
                "构建需要 Node v%s，注入环境实际为 v%s。请在下拉里改选已安装的版本"
                "（nvm 根目录：%s）" % (target, actual or "未知", node_env.nvm_root() or "未检测到"))
        ctx.check_stop()

        # 2. 清理构建产物
        ctx.stage("清理 dist 目录", 2, total)
        for d in (dist_dir, lib_dir):
            if d.exists():
                shutil.rmtree(d)
                ctx.log("✅ 已删除目录: %s" % d)
        ctx.check_stop()

        # 3. npm run build
        ctx.stage("npm run build", 3, total)
        if ctx.run_stream(["npm", "run", "build"], cwd=project_dir, env=env,
                          label="npm run build（%s）" % project_dir.name) != 0:
            raise RuntimeError("npm run build 执行失败，详见上方构建日志")
        if not dist_dir.is_dir():
            raise RuntimeError("构建结束但未生成 dist 目录：%s" % dist_dir)

        # 4. lib-render2（1.5.5 以下）
        step = 4
        if not is_155:
            ctx.stage("npm run lib-render2", step, total)
            step += 1
            if ctx.run_stream(["npm", "run", "lib-render2"], cwd=project_dir, env=env,
                              label="npm run lib-render2") != 0:
                raise RuntimeError("npm run lib-render2 执行失败，详见上方构建日志")
            if not lib_dir.is_dir():
                raise RuntimeError("未生成 lib-render-dist 目录：%s" % lib_dir)
        else:
            ctx.log("ℹ️ 1.5.5+ 简化流程：跳过 lib-render2")

        # 5. 组装成品
        ctx.stage("组装基础压缩包并生成成品", step, total)
        self._assemble(ctx, base_zip, dist_dir, lib_dir if not is_155 else None,
                       is_155, output_dir, params, version)

    def _assemble(self, ctx, base_zip, dist_dir, lib_dir, is_155,
                  output_dir, params, version):
        with tempfile.TemporaryDirectory(prefix="menz_pack_") as td:
            temp = Path(td)
            with zipfile.ZipFile(str(base_zip), "r") as zf:
                zf.extractall(temp)
            ctx.log("✅ 基础压缩包解压完成: %s" % base_zip.name)
            ctx.check_stop()

            design_target = temp / "design"
            if is_155:
                src_design = dist_dir / "design"
                src_resource = dist_dir / "resource"
                if src_design.is_dir():
                    if design_target.exists():
                        _clear_dir(design_target)
                    else:
                        design_target.mkdir(parents=True, exist_ok=True)
                    _copy_tree(src_design, design_target)
                    ctx.log("✅ design 目录已替换/创建")
                else:
                    ctx.log("⚠️ dist/design 不存在，跳过")
                resource_target = temp / "resource"
                if src_resource.is_dir():
                    if resource_target.exists():
                        _clear_dir(resource_target)
                    else:
                        resource_target.mkdir(parents=True, exist_ok=True)
                    _copy_tree(src_resource, resource_target)
                    ctx.log("✅ resource 目录已替换/创建")
                else:
                    ctx.log("⚠️ dist/resource 不存在，跳过")
            else:
                if design_target.exists():
                    _clear_dir(design_target)
                    _copy_tree(dist_dir, design_target)
                    ctx.log("✅ design 目录内容已替换")
                else:
                    ctx.log("⚠️ 基础包内无 design 目录，跳过")
                render_target = temp / "resource" / "js" / "render-design"
                if render_target.exists():
                    _clear_dir(render_target)
                    _copy_tree(lib_dir, render_target)
                    ctx.log("✅ resource/js/render-design 目录内容已替换")
                else:
                    ctx.log("⚠️ 基础包内无 resource/js/render-design 目录，跳过")

            name, reason = build_zip_name(params.get("order_info", ""), version,
                                          params.get("custom_zip_name", ""))
            ctx.log("🏷️ ZIP 文件名: %s（%s）" % (name, reason))
            new_zip = output_dir / name
            if new_zip.exists():
                ctx.log("ℹ️ 同名成品已存在，将被覆盖: %s" % new_zip)

            with zipfile.ZipFile(str(new_zip), "w", zipfile.ZIP_DEFLATED) as zf:
                for cur, _dirs, files in os.walk(str(temp)):
                    for f in files:
                        fp = Path(cur) / f
                        zf.write(fp, fp.relative_to(temp).as_posix())
            ctx.log("✅ 新压缩包已生成: %s（%s）" % (new_zip, util.human_size(new_zip.stat().st_size)))

            ctx.set_result(package_path=str(new_zip), package_name=name,
                           size=new_zip.stat().st_size,
                           size_str=util.human_size(new_zip.stat().st_size),
                           svn_work_copy=vcs.svn_work_copy(output_dir) or "")

            # 桌面版默认打完就提交；服务里 auto_commit_svn 默认关闭，页面另有提交按钮
            if params.get("auto_commit_svn"):
                commit(ctx, new_zip)


def commit(ctx, package_path):
    """把成品提交到 SVN（供 run 尾部与 /api/svn/commit 共用）。"""
    package_path = Path(package_path)
    output_dir = package_path.parent
    wc = vcs.svn_work_copy(output_dir)
    if not wc:
        ctx.log("⚠️ 未找到 SVN 工作副本（已向上查找 5 层），跳过提交")
        return False
    if Path(wc) != output_dir:
        ctx.log("ℹ️ 在上级目录找到 SVN 工作副本: %s" % wc)
    message = "门诊订单打包：%s - %s" % (package_path.name,
                                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ok = vcs.svn_commit_file(package_path, wc, message, ctx.log)
    ctx.set_result(svn_committed=ok, svn_work_copy=wc, svn_message=message)
    return ok


profile = MenzProfile()
