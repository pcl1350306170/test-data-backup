# -*- coding: utf-8 -*-
"""打包完成通知的后端支撑：随机头像 + 在资源管理器里定位成品 + Windows 原生 toast。

头像池直接用仓库里的 img/icons.json（一串远程图片 URL），进程内只读一次；
池子读不到就返回空 URL，由前端回落到默认头像，不让通知因为断网/缺文件而弹不出来。
打开目录是本机动作，路径白名单校验在路由层（browse.check_root）做。

原生 toast 走 windows-toasts（WinRT）：不依赖浏览器开着，打包完成由引擎直接发；
库没装/非 Windows/发送失败都静默跳过，绝不影响打包本身。
"""
import hashlib
import random
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

from . import util

ICONS_PATH = util.py_dir().parent / "img" / "icons.json"
LOGO_PATH = util.py_dir().parent / "img" / "logo.png"
AVATAR_CACHE_DIR = Path(__file__).resolve().parent.parent / ".avatar_cache"

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


# ── Windows 原生 toast（不依赖浏览器，引擎完成时直接发）──────────────

_native_lock = threading.Lock()
_toasters = {}      # AUMID → toaster，常驻；WinRT 激活回调挂在 toast 上，不能丢引用
_live_toasts = []   # 已发出的 toast 保活，防回调对象被 GC


def _register_aumid(aumid, display_name):
    """HKCU 注册自定义 AUMID，通知中心才会显示独立应用名而不是 cmd.exe。"""
    import winreg
    key_path = r"Software\Classes\AppUserModelId\%s" % aumid
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
        if LOGO_PATH.is_file():
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(LOGO_PATH))


def _get_toaster(title):
    from windows_toasts import InteractableWindowsToaster
    aumid = "Yarward.OrderPackager." + hashlib.md5(title.encode("utf-8")).hexdigest()[:10]
    with _native_lock:
        toaster = _toasters.get(aumid)
        if toaster is None:
            _register_aumid(aumid, title)
            toaster = InteractableWindowsToaster(title, aumid)
            _toasters[aumid] = toaster
        return toaster


def _local_avatar():
    """toast 图标只认本地文件：随机头像下载到缓存目录，失败回落仓库 logo。"""
    url = random_avatar().get("url") or ""
    if url:
        try:
            AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            suffix = Path(url.split("?")[0]).suffix or ".jpg"
            cache = AVATAR_CACHE_DIR / (hashlib.md5(url.encode("utf-8")).hexdigest() + suffix)
            if not cache.is_file():
                # URL 里有中文路径（头像/），urllib 只认 ASCII，先百分号编码
                safe_url = quote(url, safe=":/?&=%#@")
                with urllib.request.urlopen(safe_url, timeout=4) as resp:
                    cache.write_bytes(resp.read())
            if cache.is_file() and cache.stat().st_size > 0:
                return cache
        except Exception:
            pass
    return LOGO_PATH if LOGO_PATH.is_file() else None


def native_done(title, result, cfg):
    """打包成功后发 Windows 原生通知；后台线程里跑，任何异常都不影响打包。"""
    if sys.platform != "win32" or not (cfg or {}).get("native_notify", True):
        return
    pkg = (result or {}).get("package_path") or ""
    if not pkg:
        return

    def _send():
        try:
            from windows_toasts import Toast, ToastButton, ToastDisplayImage, ToastDuration
            name = (result or {}).get("package_name") or Path(pkg).name
            toaster = _get_toaster(title)
            toast = Toast()
            toast.text_fields = ["✅ 打包完成", name]
            toast.duration = ToastDuration.Long
            toast.tag = name
            toast.group = name   # 同一包名在通知中心里替换旧条目
            icon = _local_avatar()
            if icon:
                toast.AddImage(ToastDisplayImage.fromPath(str(icon)))
            toast.AddAction(ToastButton("打开包目录", "open_dir"))

            def _activated(args):
                # 点按钮或点通知本体都定位成品（白名单校验已在出包时做过）
                reveal(pkg)

            toast.on_activated = _activated
            toaster.show_toast(toast)
            with _native_lock:
                _live_toasts.append(toast)
                del _live_toasts[:-20]
        except Exception as e:
            try:
                print("⚠️ 原生通知发送失败（不影响打包）：%s" % e, flush=True)
            except Exception:
                pass

    threading.Thread(target=_send, daemon=True, name="native-toast").start()
