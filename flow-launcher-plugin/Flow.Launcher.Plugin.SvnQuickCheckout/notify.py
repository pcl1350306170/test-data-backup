# -*- coding: utf-8 -*-
"""Windows 原生通知 + 剪贴板（供 Flow 插件后台线程调用，任何失败都静默降级）

- toast 走 windows-toasts（WinRT），库没装/非 Windows/发送异常都不影响主流程
- 剪贴板修复了 x64 下 ctypes 句柄被截断的经典 bug（显式声明 restype/argtypes）
"""
import ctypes
import hashlib
import subprocess
import sys
import threading

import plugin_log

PLUGIN_DIR = __import__("os").path.abspath(__import__("os").path.dirname(__file__))
NOTIFY_ICON = PLUGIN_DIR + "\\Images\\icon.png"

_native_lock = threading.Lock()
_toasters = {}


# ── 剪贴板 ──────────────────────────────────────────────

def copy_to_clipboard(text: str) -> bool:
    """复制文本到剪贴板：ctypes(修正句柄位宽) → PowerShell Set-Clipboard 回退"""
    if _copy_ctypes(text):
        return True
    return _copy_powershell(text)


def _copy_ctypes(text: str) -> bool:
    try:
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # 关键：句柄/指针必须声明为 c_void_p，否则 x64 下被截断成 32 位而失败
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            data = (text + "\0").encode("utf-16-le")
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            # 成功后所有权移交系统，切勿 GlobalFree
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _copy_powershell(text: str) -> bool:
    try:
        # 通过 stdin 传文本避免引号转义问题；Set-Clipboard 对 Unicode 友好
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
            stdin=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        proc.communicate(text.encode("utf-8"), timeout=5)
        return proc.returncode == 0
    except Exception:
        return False


# ── 打开目录 ──────────────────────────────────────────────

def open_folder(path: str):
    if not path:
        return
    try:
        os_startfile = getattr(__import__("os"), "startfile", None)
        if os_startfile:
            os_startfile(path)
    except Exception:
        pass


# ── WinRT 原生通知 ───────────────────────────────────────

def show_toast(title_text: str, message: str, on_click_path: str = "", on_close=None):
    """发一条 Windows 原生 toast；带"打开目录"按钮（on_click_path 存在时）。

    在独立守护线程执行，失败仅打印告警。
    """
    if sys.platform != "win32":
        if on_close:
            on_close()
        return

    def _send():
        try:
            from windows_toasts import (
                InteractableWindowsToaster, Toast, ToastButton,
                ToastDisplayImage, ToastDuration,
            )
            aumid = "Yarward.SvnQuickCheckout." + hashlib.md5(
                "SVN快速检出".encode("utf-8")).hexdigest()[:10]
            with _native_lock:
                toaster = _toasters.get(aumid)
                if toaster is None:
                    _register_aumid(aumid)
                    toaster = InteractableWindowsToaster("SVN 快速检出", aumid)
                    _toasters[aumid] = toaster

            toast = Toast()
            toast.text_fields = [title_text, message]
            toast.duration = ToastDuration.Long
            # WinRT 要求 tag/group 为字母数字且 ≤16 字符
            key = hashlib.md5(message.encode("utf-8")).hexdigest()[:16]
            toast.tag = key
            toast.group = key
            try:
                toast.AddImage(ToastDisplayImage.fromPath(NOTIFY_ICON))
            except Exception:
                pass
            if on_click_path:
                toast.AddAction(ToastButton("打开目录", "open_dir"))

                def _activated(_args):
                    open_folder(on_click_path)

                toast.on_activated = _activated
            toaster.show_toast(toast)
        except Exception as e:
            # 绝不能 print 到 stdout（会污染 Flow 的 JSON-RPC 通道），只写文件日志
            plugin_log.log("toast send failed: %r" % e)
        finally:
            if on_close:
                on_close()

    threading.Thread(target=_send, daemon=True, name="svn-toast").start()


def _register_aumid(aumid: str):
    try:
        import winreg
        key_path = r"Software\Classes\AppUserModelId\%s" % aumid
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "SVN 快速检出")
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, NOTIFY_ICON)
    except Exception:
        pass
