# -*- coding: utf-8 -*-
"""打包完成通知的后端支撑：随机头像 + 在资源管理器里定位成品。

头像池直接用仓库里的 img/icons.json（一串远程图片 URL），进程内只读一次；
池子读不到就返回空 URL，由前端回落到默认头像，不让通知因为断网/缺文件而弹不出来。
打开目录是本机动作，路径白名单校验在路由层（browse.check_root）做。
"""
import random
import subprocess
import sys
import threading
from pathlib import Path

from . import util

ICONS_PATH = util.py_dir().parent / "img" / "icons.json"

_lock = threading.Lock()
_pool = None


def avatar_pool():
    """icons.json 里的 URL 列表（缓存）；文件缺失/格式不对都当空池处理。"""
    global _pool
    with _lock:
        if _pool is None:
            data = util.read_json(ICONS_PATH, default=[])
            _pool = [u.strip() for u in data
                     if isinstance(u, str) and u.strip().startswith("http")] \
                if isinstance(data, list) else []
        return list(_pool)


def random_avatar():
    """随机一个头像 URL；total 供前端判断池子是否为空。"""
    pool = avatar_pool()
    if not pool:
        return {"url": "", "total": 0}
    return {"url": random.choice(pool), "total": len(pool)}


def reveal(path):
    """资源管理器打开所在目录并选中该文件，返回 (ok, 说明)。"""
    target = Path(path)
    if not target.is_file():
        return False, "成品文件不存在：%s" % target
    if sys.platform != "win32":
        return False, "打开资源管理器仅支持 Windows"
    # explorer 自己解析命令行：/select, 与带引号的路径要写在同一个字符串里才认
    cmd = 'explorer /select,"%s"' % str(target).replace('"', "")
    try:
        subprocess.Popen(cmd, creationflags=util.NO_WINDOW)
    except OSError as e:
        return False, "拉起资源管理器失败：%s" % e
    return True, str(target.parent)
