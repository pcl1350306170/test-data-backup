# -*- coding: utf-8 -*-
"""
通用资产库保存工具
==================
封装 geeker/public/assets 资产库接口，供其他脚本 import 复用，也可命令行直接运行。

接口约定（与 md播客脚本保存到资产库.py 一致）:
    1. GET  {api_base}?keyword={标题}  → code==200 且 data.total>0 视为已存在
    2. POST {api_base} 提交 JSON       → code==200 视为保存成功

支持自定义 type、title 前缀、tags。

命令行示例:
    python asset_api.py "D:\\path\\to\\xxx.md" --type SOLUTION --prefix "AI播客脚本- " --tags AI播客脚本
    python asset_api.py "D:\\path\\to\\xxx.md" --check-only   # 仅查重，不保存
"""

import sys
import argparse
from pathlib import Path

import requests

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_NAME = "asset_api"
DEFAULT_API_BASE = "http://localhost/api/geeker/public/assets"
DEFAULT_TYPE = "SOLUTION"

# ---------- 日志（可选依赖，降级为空实现） ----------
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()


class AssetApiError(RuntimeError):
    """资产库接口业务异常（HTTP 失败或 code != 200）。"""


# ================== 工具函数 ==================
def extract_title(md_text: str) -> str:
    """从 md 内容中提取一级标题（第一个以 '# ' 开头的行），自动向下查找。"""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


# ================== 接口封装 ==================
def check_exists(api_base: str, keyword: str, timeout: int = 15) -> bool:
    """GET 查重：code==200 且 data.total>0 视为已存在。异常抛 AssetApiError。"""
    try:
        resp = requests.get(api_base, params={"keyword": keyword}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as e:
        raise AssetApiError(f"查重请求失败: {e}") from e
    if data.get("code") != 200:
        raise AssetApiError(f"查重接口返回异常 code={data.get('code')} msg={data.get('msg')}")
    total = (data.get("data") or {}).get("total", 0)
    return int(total) > 0


def save_asset(api_base: str, title: str, content: str, *,
               asset_type: str = DEFAULT_TYPE,
               title_prefix: str = "",
               tags=None,
               description: str = None,
               language: str = "",
               timeout: int = 30) -> dict:
    """POST 保存资产，成功返回响应 JSON；失败抛 AssetApiError。

    参数:
        title        : 资产原始标题（description 默认同值）
        content      : 资产正文（如 md 全文）
        asset_type   : 资产类型，默认 SOLUTION
        title_prefix : 标题前缀，最终 title = title_prefix + title
        tags         : 标签列表，默认 []
        description  : 描述，默认取原始 title
        language     : 语言字段，默认空串
    """
    payload = {
        "type": asset_type,
        "title": f"{title_prefix}{title}",
        "description": description if description is not None else title,
        "content": content,
        "language": language,
        "tags": list(tags) if tags else [],
    }
    try:
        resp = requests.post(api_base, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as e:
        raise AssetApiError(f"保存请求失败: {e}") from e
    if data.get("code") != 200:
        raise AssetApiError(f"保存接口返回异常 code={data.get('code')} msg={data.get('msg')}")
    logger.info("资产保存成功: %s" % payload["title"])
    return data


def save_md_file(md_path, api_base: str = DEFAULT_API_BASE, *,
                 asset_type: str = DEFAULT_TYPE,
                 title_prefix: str = "",
                 tags=None,
                 skip_if_exists: bool = True) -> dict:
    """读取 md 文件 → 提取一级标题 → 查重 → 保存，一站式入口。

    返回: {"status": "saved"|"skipped", "title": 原始标题, "file": 文件名}
    失败抛 AssetApiError / ValueError。
    """
    md_path = Path(md_path)
    content = md_path.read_text(encoding="utf-8")
    title = extract_title(content)
    if not title:
        raise ValueError(f"未找到一级标题（# xxx）: {md_path}")

    if skip_if_exists and check_exists(api_base, title):
        logger.info("远程已存在《%s》，跳过: %s" % (title, md_path.name))
        return {"status": "skipped", "title": title, "file": md_path.name}

    save_asset(api_base, title, content,
               asset_type=asset_type, title_prefix=title_prefix, tags=tags)
    return {"status": "saved", "title": title, "file": md_path.name}


# ================== 命令行入口 ==================
def main():
    parser = argparse.ArgumentParser(description="通用资产库保存工具（GET 查重 + POST 保存）")
    parser.add_argument("md_path", help="md 文件路径")
    parser.add_argument("--api", default=DEFAULT_API_BASE, help="资产库接口地址")
    parser.add_argument("--type", default=DEFAULT_TYPE, dest="asset_type", help="资产类型，默认 SOLUTION")
    parser.add_argument("--prefix", default="", help="标题前缀")
    parser.add_argument("--tags", default="", help="标签，逗号分隔，如: AI播客脚本,技术")
    parser.add_argument("--check-only", action="store_true", help="仅查重，不保存")
    parser.add_argument("--no-check", action="store_true", help="跳过查重直接保存")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    try:
        if args.check_only:
            content = Path(args.md_path).read_text(encoding="utf-8")
            title = extract_title(content)
            if not title:
                raise ValueError("未找到一级标题（# xxx）")
            exists = check_exists(args.api, title)
            print(f"查重结果: 《{title}》 {'已存在' if exists else '不存在'}")
            return
        result = save_md_file(args.md_path, args.api,
                              asset_type=args.asset_type,
                              title_prefix=args.prefix,
                              tags=tags,
                              skip_if_exists=not args.no_check)
        mark = "✅ 保存成功" if result["status"] == "saved" else "↪ 已存在，跳过"
        print(f"{mark}: 《{result['title']}》 ({result['file']})")
    except (AssetApiError, ValueError, OSError) as e:
        print(f"❌ 失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()