# -*- coding: utf-8 -*-
"""favicon 挑选器：从 img/icons.json 随机挑一个「未被占用」的图标给新建 HTML 页面。

用法：
    python img/pick_icon.py                      打印一个可用图标 URL 与可直接粘贴的 <link> 行
    python img/pick_icon.py --html 页面.html      直接写入该页面（已有 icon 则替换，没有则插入）
    python img/pick_icon.py --used               列出当前已被各页面占用的图标
    python img/pick_icon.py --scan 额外目录       追加占用扫描目录（可重复，用于跨仓库避免撞图）

占用判定按「文件名」而非完整 URL，因此同一张图的 raw / jsDelivr 双地址算同一个图标。
默认扫描 py/local_services 下所有 HTML；前端仓库可用 --scan 追加。
"""
import argparse
import random
import re
import sys
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ICONS_PATH = BASE_DIR / "icons.json"
DEFAULT_SCAN = [BASE_DIR.parent / "py" / "local_services"]

# rel="icon" / rel="shortcut icon"，[^>]* 可跨行，兼容 href 换行写法
LINK_RE = re.compile(r'<link\b[^>]*\brel\s*=\s*["\'](?:shortcut\s+)?icon["\'][^>]*>', re.I)
HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
TITLE_RE = re.compile(r'<title\b[^>]*>.*?</title>', re.I | re.S)

MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def icon_key(url):
    """图标唯一键：取文件名 → URL 解码 → 小写。

    解码是为了让同一张图的 percent-encoded 与中文原文写法归为同一个图标，
    否则换个编码写法就能绕过占用去重。
    """
    return urllib.parse.unquote(url.rsplit("/", 1)[-1]).lower()


def load_pool():
    """读图标池，按文件名去重（同图双地址只保留第一条）。"""
    import json
    with open(ICONS_PATH, encoding="utf-8") as f:
        urls = json.load(f)
    pool, seen = [], set()
    for u in urls:
        key = icon_key(u)
        if key in seen:
            continue
        seen.add(key)
        pool.append(u)
    return pool


def collect_used(scan_roots):
    """扫描 HTML，返回 {文件名: [(页面路径, 完整URL), ...]}。"""
    used = {}
    for root in scan_roots:
        root = Path(root)
        if not root.exists():
            print("[warn] 扫描目录不存在，已跳过: %s" % root, file=sys.stderr)
            continue
        for path in sorted(root.rglob("*.html")):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for tag in LINK_RE.findall(text):
                m = HREF_RE.search(tag)
                if not m:
                    continue
                url = m.group(1)
                used.setdefault(icon_key(url), []).append((path, url))
    return used


def pick_url(pool, used):
    """优先挑未占用的；池子被占满时退回全池随机并告警。"""
    free = [u for u in pool if icon_key(u) not in used]
    if not free:
        print("[warn] 图标池已全部被占用，退回全池随机（可能出现重复图标）", file=sys.stderr)
        free = pool
    return random.choice(free)


def build_link(url, indent=""):
    ext = "." + url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
    mime = MIME.get(ext, "image/jpeg")
    return '%s<link rel="icon" type="%s" href="%s">' % (indent, mime, url)


def inject(html_path, url):
    """写入 favicon：已有则原位替换（保留缩进），没有则插到 <title> 之后。"""
    path = Path(html_path)
    # newline="" 读写，保留原有 CRLF/LF，避免整文件行尾变更
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()

    m = LINK_RE.search(text)
    if m:
        # text[:m.start()] 已含行首缩进，此处不能再补 indent，否则缩进翻倍
        new = text[:m.start()] + build_link(url) + text[m.end():]
        action = "替换"
    else:
        t = TITLE_RE.search(text)
        if t:
            pos = t.end()
            line_start = text.rfind("\n", 0, t.start()) + 1
            indent = re.match(r"[ \t]*", text[line_start:t.start()]).group(0)
        else:
            h = re.search(r"</head>", text, re.I)
            pos = h.start() if h else 0
            line_start = text.rfind("\n", 0, pos) + 1
            indent = re.match(r"[ \t]*", text[line_start:pos]).group(0)
        nl = "\r\n" if "\r\n" in text else "\n"
        new = text[:pos] + nl + build_link(url, indent) + text[pos:]
        action = "插入"

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return action


def main():
    ap = argparse.ArgumentParser(description="从 img/icons.json 挑一个未被占用的 favicon")
    ap.add_argument("--html", help="直接写入/替换该 HTML 页面的 favicon")
    ap.add_argument("--used", action="store_true", help="列出当前图标占用情况")
    ap.add_argument("--scan", action="append", default=[], help="追加占用扫描目录（可重复）")
    args = ap.parse_args()

    if not ICONS_PATH.exists():
        print("[error] 找不到图标池: %s" % ICONS_PATH, file=sys.stderr)
        return 1

    pool = load_pool()
    roots = DEFAULT_SCAN + [Path(p) for p in args.scan]
    used = collect_used(roots)

    if args.used:
        print("图标池: %d 张（按文件名去重）  已占用: %d 张  可用: %d 张"
              % (len(pool), len(used), len(pool) - len(used)))
        for name, hits in sorted(used.items()):
            for path, url in hits:
                print("  %-14s %s" % (name, path))
        return 0

    # 写入模式下，目标页面自身占用的图标不算冲突（替换后旧图即释放）
    target = Path(args.html).resolve() if args.html else None
    effective = {n: hits for n, hits in used.items()
                 if not (target and all(p.resolve() == target for p, _ in hits))}
    url = pick_url(pool, effective)

    if target:
        if not target.exists():
            print("[error] 页面不存在: %s" % target, file=sys.stderr)
            return 1
        action = inject(target, url)
        print("%s favicon -> %s" % (action, target))
        print("  %s" % url)
    else:
        print(url)
        print(build_link(url))
    return 0


if __name__ == "__main__":
    sys.exit(main())