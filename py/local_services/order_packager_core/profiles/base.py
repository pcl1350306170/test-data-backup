# -*- coding: utf-8 -*-
"""Profile 基类：把「打包该做什么」与「服务怎么跑」分开。

引擎（engine/base_server）只认这套接口：
    roots(cfg)                     → 允许浏览的目录
    search(keyword, cfg)           → SVN/Git 匹配结果 + 自动填充建议
    validate(params, cfg)          → (errors, normalized)
    run(params, ctx)               → 执行打包，用 ctx.set_result 登记产物
    history_record(params, result) → 写历史用的记录
"""
import os
import re

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class Profile:
    ID = ""
    TITLE = ""
    ICON = "📦"
    DEFAULT_CONFIG = {}
    LEGACY_CONFIG_PATHS = ()
    HISTORY_DEDUP_KEY = ""
    VERSION_OPTIONS = ()
    NODE_DEFAULT = "14.19.1"
    PACKAGE_EXTS = ()          # 成品目录列文件时的后缀过滤
    # 从旧 .pyw 配置迁移时强制回默认值的键：服务里 SVN 提交默认关，
    # 不然页面一打开就是「自动提交」，一点开始打包就直接往仓库里提了
    MIGRATE_RESET_KEYS = ("auto_commit_svn",)

    # ── 子类必须实现 ──────────────────────────────────

    def roots(self, cfg):
        raise NotImplementedError

    def search(self, keyword, cfg, params=None):
        raise NotImplementedError

    def prefill(self, cfg, params):
        """选中某个 SVN/Git 目录后的自动回填（页面点击列表项时调用）。"""
        return {}

    def run(self, params, ctx):
        raise NotImplementedError

    def history_record(self, params, result):
        raise NotImplementedError

    def commit(self, ctx, package_path, work_dir=""):
        """把已生成的成品提交到 SVN（页面「提交到 SVN」按钮调用，打包时默认不走这里）。"""
        raise NotImplementedError

    # ── 通用校验 ──────────────────────────────────────

    NON_PARAM_KEYS = ("history_records", "port")

    def validate(self, params, cfg):
        """通用字段清洗，业务必填项由子类 _extra_validate 补充。"""
        errors = []
        normalized = {}
        for key, default in self.DEFAULT_CONFIG.items():
            if key in self.NON_PARAM_KEYS:
                continue
            value = (params or {}).get(key, default)
            if isinstance(default, bool):
                normalized[key] = bool(value)
            elif isinstance(default, str):
                normalized[key] = str(value or "").strip()
            else:
                normalized[key] = value

        proj = normalized.get("project_dir", "")
        if not proj:
            errors.append("请先选择项目目录（Git 项目）")
        elif not _is_dir(proj):
            errors.append("项目目录不存在：%s" % proj)

        ver = normalized.get("project_version", "")
        if ver and not _VERSION_RE.match(ver):
            errors.append("项目版本格式应为 x.y.z，当前为：%s" % ver)

        if not normalized.get("node_version"):
            errors.append("请选择 Node 版本")

        errors.extend(self._extra_validate(normalized))
        return errors, normalized

    def _extra_validate(self, normalized):
        return []

    # ── 元信息（给页面初始化用）──────────────────────

    def meta(self, cfg):
        from .. import node_env
        return {
            "id": self.ID,
            "title": self.TITLE,
            "icon": self.ICON,
            "version_options": list(self.VERSION_OPTIONS),
            "node_default": cfg.get("node_version") or node_env.DEFAULT_NODE_VERSION,
            "roots": self.roots(cfg),
        }


def _is_dir(path):
    return bool(path) and os.path.isdir(path)


def _is_file(path):
    return bool(path) and os.path.isfile(path)
