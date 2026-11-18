# -*- coding: utf-8 -*-
"""打包完成通知的后端支撑：默认通知图 + 在资源管理器里定位成品 + Windows 原生 toast。

通知统一用 assets/notify_default.jpeg（已随代码入库，不依赖外部路径）；
头像池 img/icons.json 的随机接口仍保留，但通知不再使用。
打开目录是本机动作，路径白名单校验在路由层（browse.check_root）做。

原生 toast 走 windows-toasts（WinRT）：不依赖浏览器开着，打包完成由引擎直接发；
库没装/非 Windows/发送失败都静默跳过，绝不影响打包本身。
"""
import hashlib
import random
import subprocess
import sys
import threading
from pathlib import Path

from . import util

ICONS_PATH = util.py_dir().parent / "img" / "icons.json"
LOGO_PATH = util.py_dir().parent / "img" / "logo.png"
DEFAULT_ICON_PATH = Path(__file__).resolve().parent / "assets" / "notify_default.jpeg"

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
    icon = DEFAULT_ICON_PATH if DEFAULT_ICON_PATH.is_file() else LOGO_PATH
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
        if icon.is_file():
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))


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


def _notify_icon():
    """toast 图标只认本地文件：默认通知图缺失时回落仓库 logo。"""
    if DEFAULT_ICON_PATH.is_file():
        return DEFAULT_ICON_PATH
    return LOGO_PATH if LOGO_PATH.is_file() else None


def native_done(title, result, cfg, title_text="✅ 打包完成"):
    """任务成功后发 Windows 原生通知；后台线程里跑，任何异常都不影响主任务。

    title_text 区分打包/升级等场景；定位的文件取 result.package_path。
    """
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
            toast.text_fields = [title_text, name]
            toast.duration = ToastDuration.Long
            # WinRT 要求 tag/group 为字母数字且 ≤16 字符，直接用包名会报
            # WinError -2143420138 整条丢弃；取 md5 前 16 位，同名包仍替换通知中心旧条目
            toast_key = hashlib.md5(name.encode("utf-8")).hexdigest()[:16]
            toast.tag = toast_key
            toast.group = toast_key
            icon = _notify_icon()
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
