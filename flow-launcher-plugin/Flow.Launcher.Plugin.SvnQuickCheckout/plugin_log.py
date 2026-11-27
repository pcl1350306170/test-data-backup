# -*- coding: utf-8 -*-
"""插件文件日志 + 待确认状态持久化。

绝不写 stdout（Flow python 插件的 stdout 是 JSON-RPC 通道，print 会污染协议）。
"""
import datetime
import json
import os
import tempfile

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
# 运行期文件放在插件目录之外：Flow 会监听插件目录变动并重载进程，
# 若把日志/待确认状态写在插件目录里，一写入就可能触发重载、杀死后台检出线程。
_DATA_DIR = os.path.join(tempfile.gettempdir(), "svn_quick_checkout")
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:
    _DATA_DIR = tempfile.gettempdir()
LOG_PATH = os.path.join(_DATA_DIR, "plugin_debug.log")
PENDING_PATH = os.path.join(_DATA_DIR, "pending_create.json")


def log(msg):
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s | %s\n" % (ts, msg))
    except Exception:
        pass


# ── 待确认状态持久化（扛 Flow 进程重启）──────────────────

def load_pending():
    try:
        with open(PENDING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_pending(d):
    try:
        with open(PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        log("save_pending failed: %s" % e)


def clear_pending_file():
    try:
        if os.path.exists(PENDING_PATH):
            os.remove(PENDING_PATH)
    except Exception:
        pass
