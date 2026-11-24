# -*- coding: utf-8 -*-
"""门诊订单打包 profile。

一个服务打三种成品，差别只在「去哪些 Git 目录 / 拿哪个基础包 / 跑哪条 npm 脚本」：
  模板       template*（1.3~1.6 各版本目录）    YM-801S-TLSS-   npm run build (+lib-render2)
  播报机     clinic-kiosks-web                 YM-801S-KIOSKS- npm run build
  web运维端  web-frontEn / web-frontEn1.5.4    YM-801S-OSCS-   npm run build:local（无 build 脚本）

流程（与桌面版 门诊打包.pyw 一致）：
  1. 锁定 Node 版本（PATH 注入，免 UAC）
  2. 清理 dist / lib-render-dist
  3. npm run <该类型的构建脚本>
  4. 仅模板且 1.5.5 以下再跑 npm run lib-render2
  5. 解压基础压缩包 → 用构建产物覆盖同名内容 → 生成成品 ZIP（同名直接覆盖）
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
BASE_ZIP_SUFFIX = "-FE.zip"
# 基础压缩包名里带的版本号：YM-801S-TLSS-V1.5.1.xxxx... → 1.5.1
_ZIP_VERSION_RE = re.compile(r"-V(\d+\.\d+\.\d+)\.")

# 打包项目类型：决定 Git 目录范围、基础包前缀与构建命令。
#   dir_prefixes   项目目录名前缀（播报机只有一个固定目录，用全名当前缀即可）
#   zip_prefix     基础压缩包与成品的文件名中缀
#   build_script   该类型跑哪条 npm script（运维端没有 build，只有 build:local）
#   node_version   该类型建议的 Node 版本，留空则用页面当前所选
#   render_lib     是否走 lib-render2（只有模板的 resource/js/render-design 需要）
DEFAULT_KIND = "模板"
PROJECT_KINDS = {
    "模板": {"id": "template", "dir_prefixes": ("template",),
               "zip_prefix": "YM-801S-TLSS-", "build_script": "build",
               "node_version": "", "render_lib": True},
    "播报机": {"id": "kiosks", "dir_prefixes": ("clinic-kiosks-web",),
                 "zip_prefix": "YM-801S-KIOSKS-", "build_script": "build",
                 "node_version": "", "render_lib": False},
    "web运维端": {"id": "oscs", "dir_prefixes": ("web-frontEn",),
                    "zip_prefix": "YM-801S-OSCS-", "build_script": "build:local",
                    "node_version": "16.20.2", "render_lib": False},
}


def kind_rule(name):
    """取类型规则，非法/缺失都回落到默认类型（校验层会另外报错）。"""
    return PROJECT_KINDS.get(name) or PROJECT_KINDS[DEFAULT_KIND]


def kind_of_dir_name(dir_name):
    """从项目目录名反推类型；认不出返回 ''（手工浏览选目录时用来自动切类型）。"""
    lower = (dir_name or "").lower()
    for label, rule in PROJECT_KINDS.items():
        if any(lower.startswith(p.lower()) for p in rule["dir_prefixes"]):
            return label
    return ""


def kind_of_zip_name(zip_name):
    """从基础压缩包名反推类型（报「拿错了别的类型的包」时用它说清是谁的）。"""
    for label, rule in PROJECT_KINDS.items():
        if (zip_name or "").startswith(rule["zip_prefix"]):
            return label
    return ""


def dir_name_matcher(rule):
    """给 vcs.dirs_by_branch 用的目录名过滤器。"""
    prefixes = tuple(p.lower() for p in rule["dir_prefixes"])
    return lambda name: name.lower().startswith(prefixes)


def read_npm_scripts(project_dir):
    """读项目 package.json 的 scripts，读不到返回 {}。"""
    import json
    pkg = Path(project_dir) / "package.json"
    if not pkg.is_file():
        return {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return {}
    scripts = data.get("scripts") or {}
    return scripts if isinstance(scripts, dict) else {}


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


def build_zip_name(order_info, version, custom="", prefix="YM-801S-TLSS-"):
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
    name = "%sV%s.%s%s.01001-%s-FE.zip" % (
        prefix, version, year_part, order_num, pinyin_initials(hospital))
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
    HISTORY_DEDUP_KEY = "_dedup_key"
    PACKAGE_EXTS = (".zip",)
    PROJECT_TYPES = tuple(PROJECT_KINDS.keys())
    VERSION_OPTIONS = ("1.5.0", "1.5.1", "1.5.2", "1.5.3", "1.5.4", "1.5.5", "1.5.6")
    DEFAULT_CONFIG = {
        "port": 8802,
        "project_kind": DEFAULT_KIND,
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
        "native_notify": True,
        "node_version": node_env.DEFAULT_NODE_VERSION,
        "history_records": [],
        # 前端升级（upgrade.py）专用：上次服务器 / 发布脚本超时 / 独立历史
        "upgrade_last_server": "",
        "upgrade_timeout": 300,
        "upgrade_history_records": [],
        # 服务端升级（ServerUpgradeEngine）专用：与前端升级各自独立
        "server_upgrade_last_server": "",
        "server_upgrade_timeout": 300,
        "server_upgrade_history_records": [],
        # 升级说明生成（docgen.py）：模板 docx 路径，弹窗里可临时改
        "upgrade_doc_template": r"D:\CODE\Python\test-data\门诊\801S-订单\前端\前端升级说明-1.5.1.docx",
    }
    LEGACY_CONFIG_PATHS = (util.py_dir() / "yarward" / "json" / "config_menz_order_packager.json",)

    def roots(self, cfg):
        return [cfg.get("svn_base_dir", ""), cfg.get("git_base_dir", "")]

    def _kind_name(self, cfg, params=None):
        """本次用的类型名：请求参数优先，其次配置，都没有则默认类型。"""
        return ((params or {}).get("project_kind") or cfg.get("project_kind")
                or DEFAULT_KIND)

    # ── 搜索 ──────────────────────────────────────────

    def search(self, keyword, cfg, params=None):
        keyword = (keyword or "").strip()
        rule = kind_rule(self._kind_name(cfg, params))
        svn_dirs = vcs.dirs_by_name(cfg.get("svn_base_dir", ""), keyword)
        # 只在属于该类型的目录里找分支：避免 web-frontEn / todonew 这类不相干仓库干扰
        projects = vcs.dirs_by_branch(cfg.get("git_base_dir", ""), keyword,
                                      name_match=dir_name_matcher(rule))

        suggestion = {}
        base_zips = []
        if svn_dirs:
            top = Path(svn_dirs[0]["path"])
            out_dir = vcs.frontend_subdir(top)
            suggestion["output_dir"] = str(out_dir)
            suggestion["order_info"] = _strip_frontend_suffix(top.name)
            base_zips = vcs.find_files(top, rule["zip_prefix"], BASE_ZIP_SUFFIX)
            if base_zips:
                suggestion["base_zip_path"] = base_zips[0]["path"]
                suggestion["base_zip_name"] = base_zips[0]["name"]
        if projects:
            suggestion["project_dir"] = projects[0]["path"]
            suggestion["project_version"] = projects[0]["version"]
            suggestion["git_branch"] = projects[0]["branch"]

        return {
            "keyword": keyword,
            "project_kind": self._kind_name(cfg, params),
            "zip_prefix": rule["zip_prefix"],
            "build_script": rule["build_script"],
            "render_lib": rule["render_lib"],
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
        kind = self._kind_name(cfg, params)
        rule = kind_rule(kind)
        out["project_kind"] = kind
        svn_dir = (params or {}).get("svn_dir", "")
        if svn_dir and _is_dir(svn_dir):
            work_dir = vcs.frontend_subdir(Path(svn_dir))
            zips = vcs.find_files(Path(svn_dir), rule["zip_prefix"], BASE_ZIP_SUFFIX)
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
                out["notice"] = ("已定位输出目录，「%s」基础压缩包 %d 个（最新 %s）"
                                 % (kind, len(zips), zips[0]["name"]))
            else:
                out["notice"] = ("该 SVN 目录下未找到 %s****%s 格式的「%s」基础压缩包，"
                                 "请确认类型选对或手动选择"
                                 % (rule["zip_prefix"], BASE_ZIP_SUFFIX, kind))

        project_dir = (params or {}).get("project_dir", "")
        if project_dir and _is_dir(project_dir):
            branch = vcs.git_branch(project_dir)
            out["git_branch"] = branch
            version = vcs.version_from_branch(branch)
            # 分支推出来的版本优先（比包名更新，说明已经换分支）
            if version:
                out["project_version"] = version
                out["version_source"] = "git_branch"
            if not version:
                out["version_notice"] = "无法从分支名 %s 提取版本号，请手动选择" % (branch or "(空)")

            # 手工浏览选了一个其他类型的目录，告诉页面该切哪个类型
            dir_kind = kind_of_dir_name(Path(project_dir).name)
            out["dir_kind"] = dir_kind
            if dir_kind and dir_kind != kind:
                out["kind_notice"] = ("目录 %s 属于「%s」，与当前类型「%s」不一致，已自动切换"
                                      % (Path(project_dir).name, dir_kind, kind))
            scripts = read_npm_scripts(project_dir)
            out["build_script"] = rule["build_script"]
            out["has_build_script"] = (rule["build_script"] in scripts) if scripts else True
            if scripts and rule["build_script"] not in scripts:
                out["available_scripts"] = [k for k in scripts
                                            if k.startswith("build") or k.startswith("lib-render")]
        return out

    # ── 校验 ──────────────────────────────────────────

    def _extra_validate(self, p):
        errors = []
        kind = p.get("project_kind", "")
        if kind not in PROJECT_KINDS:
            errors.append("打包项目非法：%s（可选 %s）" % (kind or "(空)", "、".join(PROJECT_KINDS)))
            return errors
        rule = kind_rule(kind)

        if not p.get("output_dir"):
            errors.append("请先选择输出目录（SVN 前端目录）")
        if not p.get("base_zip_path"):
            errors.append("请先选择「%s」的基础压缩包（%s****%s）"
                          % (kind, rule["zip_prefix"], BASE_ZIP_SUFFIX))
        elif not _is_file(p["base_zip_path"]):
            errors.append("基础压缩包不存在：%s" % p["base_zip_path"])
        else:
            zip_name = Path(p["base_zip_path"]).name
            if not zip_name.startswith(rule["zip_prefix"]):
                errors.append("基础压缩包 %s 是「%s」的包，与所选类型「%s」不配（应以 %s 开头）"
                              % (zip_name, kind_of_zip_name(zip_name) or "其他",
                                 kind, rule["zip_prefix"]))
        if not p.get("order_info"):
            errors.append("请填写订单信息（前 9 位订单号 + 医院名）")
        if not p.get("project_version"):
            errors.append("请选择或输入项目版本")

        # 构建脚本必须真在 package.json 里（运维端只有 build:local，没有 build）
        proj = p.get("project_dir", "")
        scripts = read_npm_scripts(proj) if proj else {}
        if scripts and rule["build_script"] not in scripts:
            errors.append("项目 package.json 里没有 npm run %s（「%s」的构建命令），现有：%s"
                          % (rule["build_script"], kind, "、".join(sorted(scripts)) or "(空)"))
        if (rule["render_lib"] and not p.get("is_version_155_plus")
                and scripts and "lib-render2" not in scripts):
            errors.append("项目 package.json 里没有 npm run lib-render2，"
                          "请勾选「1.5.5 及以上」或确认分支")
        return errors

    # ── 历史 / 提交 ───────────────────────────────────

    def history_record(self, params, result):
        """字段与桌面版 config_menz_order_packager.json 一致，新增 project_kind。

        去重键带上类型，否则同一订单打三种成品会互相顶掉历史记录。
        """
        kind = params.get("project_kind", DEFAULT_KIND)
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_kind": kind,
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
            "_dedup_key": "%s_%s" % (kind, params.get("order_info", "")),
        }

    def commit(self, ctx, package_path, work_dir=""):
        return commit(ctx, package_path)

    def meta(self, cfg):
        base = super().meta(cfg)
        base["project_kinds"] = [
            {"name": label, "zip_prefix": r["zip_prefix"], "build_script": r["build_script"],
             "node_version": r["node_version"], "render_lib": r["render_lib"],
             "dirs": list(r["dir_prefixes"])}
            for label, r in PROJECT_KINDS.items()]
        base["project_kind"] = cfg.get("project_kind") or DEFAULT_KIND
        return base

    # ── 执行 ──────────────────────────────────────────

    def run(self, params, ctx):
        project_dir = Path(params["project_dir"])
        output_dir = Path(params["output_dir"])
        base_zip = Path(params["base_zip_path"])
        kind = params.get("project_kind", DEFAULT_KIND)
        rule = kind_rule(kind)
        build_script = rule["build_script"]
        is_155 = bool(params.get("is_version_155_plus"))
        need_render = bool(rule["render_lib"]) and not is_155
        version = params["project_version"]
        dist_dir = project_dir / "dist"
        lib_dir = project_dir / "lib-render-dist"

        total = 4 + (1 if need_render else 0)
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx.set_result(output_dir=str(output_dir), project_dir=str(project_dir),
                       project_kind=kind, build_script=build_script,
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

        # 2. 清理构建产物（只有模板会产生 lib-render-dist）
        ctx.stage("清理 dist 目录", 2, total)
        for d in ((dist_dir, lib_dir) if rule["render_lib"] else (dist_dir,)):
            if d.exists():
                shutil.rmtree(d)
                ctx.log("✅ 已删除目录: %s" % d)
        ctx.check_stop()

        # 3. npm run <该类型的构建脚本>
        ctx.stage("npm run %s" % build_script, 3, total)
        code = ctx.run_stream(["npm", "run", build_script], cwd=project_dir, env=env,
                              label="npm run %s（%s・%s）" % (build_script, kind, project_dir.name))
        if code != 0:
            # 运维端 build:local 尾部带 vue-tsc 类型检查：类型报错不该挡打包，但 dist 必须真出东西
            built = [p for p in dist_dir.iterdir()] if dist_dir.is_dir() else []
            if built:
                newest = max(built, key=lambda p: p.stat().st_mtime)
                ctx.log("⚠️ npm run %s 退出码 %s，但 dist 已产出，继续打包"
                        "（多为 vue-tsc 类型检查报错；dist 内最新修改 %s・%s）"
                        % (build_script, code, newest.name,
                           datetime.fromtimestamp(newest.stat().st_mtime)
                           .strftime("%Y-%m-%d %H:%M:%S")))
            else:
                raise RuntimeError("npm run %s 执行失败（退出码 %s）且未生成 dist，详见上方构建日志"
                                   % (build_script, code))
        if not dist_dir.is_dir():
            raise RuntimeError("构建结束但未生成 dist 目录：%s" % dist_dir)

        # 4. lib-render2（仅模板且 1.5.5 以下）
        step = 4
        if need_render:
            ctx.stage("npm run lib-render2", step, total)
            step += 1
            if ctx.run_stream(["npm", "run", "lib-render2"], cwd=project_dir, env=env,
                              label="npm run lib-render2") != 0:
                raise RuntimeError("npm run lib-render2 执行失败，详见上方构建日志")
            if not lib_dir.is_dir():
                raise RuntimeError("未生成 lib-render-dist 目录：%s" % lib_dir)
        elif not rule["render_lib"]:
            ctx.log("ℹ️ 「%s」不用 lib-render2，成品组装只覆盖 dist 内容" % kind)
        else:
            ctx.log("ℹ️ 1.5.5+ 简化流程：跳过 lib-render2")

        # 5. 组装成品
        ctx.stage("组装基础压缩包并生成成品", step, total)
        self._assemble(ctx, base_zip, dist_dir, lib_dir if need_render else None,
                       rule, is_155, output_dir, params, version)

    @staticmethod
    def _merge_template(ctx, temp, dist_dir, lib_dir, is_155):
        """模板：基础包内是 design/ + resource/，按版本走两套替换规则。"""
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
            return

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

    @staticmethod
    def _merge_overlay(ctx, temp, dist_dir):
        """播报机 / 运维端：基础包顶层结构与 dist 一致，按同名顶层项整项覆盖。

        dist 里有的 → 先删基础包同名项再整体放入；dist 里没有的（如运维端基础包的
        update.html）→ 原样保留；dist 多出来的 → 直接新增。
        """
        base_tops = {p.name for p in temp.iterdir()}
        replaced, added = [], []
        for item in sorted(dist_dir.iterdir(), key=lambda p: p.name.lower()):
            target = temp / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                replaced.append(item.name)
            else:
                added.append(item.name)
            if item.is_dir():
                shutil.copytree(str(item), str(target))
            else:
                shutil.copy2(str(item), str(target))
        ctx.log("✅ dist 覆盖基础包 %d 项: %s" % (len(replaced), "、".join(replaced) or "(无)"))
        if added:
            ctx.log("ℹ️ dist 新增 %d 项: %s" % (len(added), "、".join(added)))
        kept = sorted(base_tops - set(replaced))
        if kept:
            ctx.log("ℹ️ 保留基础包内 dist 没有的 %d 项: %s" % (len(kept), "、".join(kept)))

    def _assemble(self, ctx, base_zip, dist_dir, lib_dir, rule, is_155,
                  output_dir, params, version):
        with tempfile.TemporaryDirectory(prefix="menz_pack_") as td:
            temp = Path(td)
            with zipfile.ZipFile(str(base_zip), "r") as zf:
                zf.extractall(temp)
            ctx.log("✅ 基础压缩包解压完成: %s" % base_zip.name)
            ctx.check_stop()

            if rule["render_lib"]:
                self._merge_template(ctx, temp, dist_dir, lib_dir, is_155)
            else:
                self._merge_overlay(ctx, temp, dist_dir)

            name, reason = build_zip_name(params.get("order_info", ""), version,
                                          params.get("custom_zip_name", ""),
                                          rule["zip_prefix"])
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
