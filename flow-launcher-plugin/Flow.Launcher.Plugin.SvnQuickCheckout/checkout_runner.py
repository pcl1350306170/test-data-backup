# -*- coding: utf-8 -*-
"""独立检出/新建执行器（脱离 Flow 插件短命进程，避免后台线程随进程退出被杀）。

用法：python checkout_runner.py <base64(json)>
json = {"resolution": {...}, "cfg": {...}, "create": bool}
"""
import base64
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import plugin_log
import notify
from svn_client import svn_info, svn_mkdir, svn_checkout, run_svn_command


def _svn_update(local_path, user, pwd):
    try:
        proc = subprocess.run(
            ["svn", "update", local_path,
             "--username", user, "--password", pwd, "--non-interactive"],
            capture_output=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        out = (proc.stdout or b"").decode("utf-8", errors="replace")
        return proc.returncode == 0, (err or out)
    except Exception as e:
        return False, str(e)


def _clear_pending(type_name, order_no):
    try:
        d = plugin_log.load_pending()
        d.pop("%s|%s" % (type_name, order_no), None)
        plugin_log.save_pending(d)
    except Exception as e:
        plugin_log.log("runner clear pending failed: %r" % e)


def run(resolution, cfg, create):
    user = cfg.get("username", "")
    pwd = cfg.get("password", "")
    type_name = resolution.get("type", "")
    target_url = resolution["target_url"]
    local_path = resolution["local_path"]
    order_name = resolution["order_name"]
    order_no = resolution.get("order_no", "")
    plugin_log.log(
        "runner START: create=%s type=%s target=%s local=%s"
        % (create, type_name, target_url, local_path)
    )
    ok, err, updated = False, "", False
    try:
        if not local_path:
            raise Exception("未配置本地检出目录 local_checkout_dir")

        if create:
            # 病房：先确保医院目录存在
            if resolution.get("need_hospital") and resolution.get("hospital_url"):
                if not svn_info(resolution["hospital_url"], user, pwd):
                    ok, err = svn_mkdir(
                        resolution["hospital_url"], user, pwd,
                        "Auto create hospital dir for %s" % resolution.get("hospital_name", ""),
                    )
                    if not ok:
                        raise Exception("创建医院目录失败: %s" % err)
            # 再确保订单目录存在
            if not svn_info(target_url, user, pwd):
                ok, err = svn_mkdir(target_url, user, pwd, "Auto create for %s" % order_name)
                if not ok:
                    raise Exception("创建订单目录失败: %s" % err)
        else:
            # 非新建：本地已检出则更新，否则检出
            if os.path.isdir(local_path):
                ok, err = _svn_update(local_path, user, pwd)
                updated = True

        if not updated:
            ok, err = svn_checkout(target_url, local_path, user, pwd)
            if ok:
                try:
                    os.makedirs(os.path.join(local_path, "前端"), exist_ok=True)
                except Exception:
                    pass
    except Exception as e:
        ok, err = False, str(e)
        plugin_log.log("runner EXCEPTION: %r" % e)
    finally:
        _clear_pending(type_name, order_no)

    verb = "更新" if updated else "检出"
    plugin_log.log("runner FINISH: ok=%s updated=%s err=%s" % (ok, updated, (err or "")[:200]))
    if ok:
        notify.open_folder(local_path)
        notify.show_toast(
            "✅ %s %s完成" % (type_name, verb), "已打开：%s" % local_path, on_click_path=local_path
        )
    else:
        notify.show_toast("❌ %s %s失败" % (type_name, verb), err or "未知错误")


def main():
    if len(sys.argv) < 2:
        plugin_log.log("runner: no payload arg")
        return
    try:
        payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
    except Exception as e:
        plugin_log.log("runner: payload decode failed: %r" % e)
        return
    run(payload["resolution"], payload["cfg"], bool(payload.get("create")))


if __name__ == "__main__":
    main()
