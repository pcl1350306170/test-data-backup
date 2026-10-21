# -*- coding: utf-8 -*-
"""本地服务 Hub：统一入口，一键启停本机各 Web 服务。

- 端口 8700，绑定 0.0.0.0（局域网可见，暂不加口令）
- 服务注册表 services.json（新增服务只需加一条配置，无需改代码）
- 状态三态：Hub 启动中 / 外部占用（手动启动，Hub 不提供停止）/ 已停止
- 启动绕过 start.bat 的 pause：直接执行注册表里的 cmd，日志落盘 hub/logs/
- 停止 taskkill /F /T 杀进程树（覆盖 uvicorn 派生的 conda worker 子进程）
"""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ── 路径与常量 ────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICES_PATH = os.path.join(BASE_DIR, "services.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
STATIC_DIR = os.path.join(BASE_DIR, "static")

HUB_PORT = 8700
LOG_KEEP_PER_SERVICE = 10
_PROBE_POOL = ThreadPoolExecutor(max_workers=8)

_DETACHED = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
             if sys.platform == "win32" else 0)

app = FastAPI(title="Local Service Hub")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── 注册表 / 运行状态 ─────────────────────────────────

def load_registry() -> list:
    with open(SERVICES_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("services", [])


def load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def _find(sid: str) -> dict:
    for svc in load_registry():
        if svc.get("id") == sid:
            return svc
    raise HTTPException(404, "服务未注册: %s" % sid)


# ── 探测 ─────────────────────────────────────────────

def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def http_alive(port: int, path: str = "/", timeout: float = 2.0) -> bool:
    """HTTP 探测：能连上并返回任意状态码即视为存活（区分端口被 hang 死的进程占用）。"""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (port, path),
            headers={"User-Agent": "svc-hub"})
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # 有响应即存活
    except Exception:
        return False


def port_pid(port: int):
    """按监听端口反查 PID（netstat -ano）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             encoding="gbk", errors="replace").stdout or ""
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" \
                and parts[3].upper() == "LISTENING" \
                and parts[1].endswith(":%d" % port):
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def proc_cmdline(pid: int) -> str:
    """查进程命令行，供接管时人工确认。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             '(Get-CimInstance Win32_Process -Filter "ProcessId=%d").CommandLine' % pid],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _probe(svc: dict) -> str:
    """返回 running | unresponsive | external | stopped"""
    if not port_open(svc["port"]):
        return "stopped"
    rec = load_state().get(svc["id"])
    if rec:
        return "running" if http_alive(svc["port"], svc.get("health_path", "/")) \
            else "unresponsive"
    return "external"


# ── 日志管理 ─────────────────────────────────────────

def _log_path(sid: str) -> str:
    return os.path.join(LOGS_DIR, "%s.log" % sid)


def _rotate_logs(sid: str):
    """历史日志保留最近 LOG_KEEP_PER_SERVICE 份。"""
    cur = _log_path(sid)
    if os.path.isfile(cur):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        try:
            os.rename(cur, os.path.join(LOGS_DIR, "%s_%s.log" % (sid, stamp)))
        except OSError:
            open(cur, "w").close()
    histories = sorted(
        [f for f in os.listdir(LOGS_DIR)
         if f.startswith(sid + "_") and f.endswith(".log")],
        reverse=True)
    for old in histories[LOG_KEEP_PER_SERVICE:]:
        try:
            os.unlink(os.path.join(LOGS_DIR, old))
        except OSError:
            pass


def _tail_log(sid: str, lines: int = 200) -> str:
    path = _log_path(sid)
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 64 * 1024))
        data = f.read().decode("utf-8", errors="replace")
    return "\n".join(data.splitlines()[-lines:])


# ── 依赖预检 ───────────────────────────────────

def _resolve_check_target(svc: dict, target: str):
    """支持 "cfg:数据文件相对路径#配置键" 引用服务自己的配置，避免两处维护。"""
    if target.startswith("cfg:") and "#" in target:
        rel, key = target[4:].split("#", 1)
        cfg_path = os.path.join(svc["path"], rel.replace("/", os.sep))
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return None, "读取 %s 失败: %s" % (rel, e)
        val = data.get(key)
        if not val:
            return None, "配置键 %s 不存在或为空" % key
        return str(val), None
    return target, None


def _run_checks(svc: dict) -> list:
    results = []
    for chk in svc.get("checks", []):
        ctype = chk.get("type")
        item = {"type": ctype, "label": chk.get("label") or chk.get("target", ""),
                "ok": False, "detail": ""}
        target, err = _resolve_check_target(svc, chk.get("target", ""))
        if err:
            item["detail"] = err
        elif ctype == "exe":
            found = shutil.which(target)
            item["ok"] = bool(found)
            item["detail"] = found or "PATH 中未找到"
        elif ctype == "file":
            item["ok"] = bool(target) and os.path.isfile(target)
            item["detail"] = target or "(空)"
        elif ctype == "dir":
            item["ok"] = bool(target) and os.path.isdir(target)
            item["detail"] = target or "(空)"
        elif ctype == "url":
            try:
                urllib.request.urlopen(target, timeout=2)
                item["ok"] = True
                item["detail"] = target
            except Exception as e:
                item["detail"] = "%s (%s)" % (target, type(e).__name__)
        else:
            item["ok"] = True
            item["detail"] = "未知类型，跳过"
        results.append(item)
    return results


# ── 依赖保障（如 novel_agent 需要 Ollama） ────────────

def _ensure_deps(svc: dict):
    ensure = svc.get("ensure")
    if not ensure:
        return
    try:
        urllib.request.urlopen(ensure["probe_url"], timeout=2)
        return  # 依赖已在
    except Exception:
        pass
    subprocess.Popen(
        ensure["cmd"], cwd=ensure.get("cwd"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_DETACHED)
    time.sleep(ensure.get("wait_sec", 5))


# ── API ──────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/hub/info")
async def hub_info():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return {"port": HUB_PORT, "lan_ips": ips}


@app.get("/api/hub/export/quickfolder")
async def export_quickfolder():
    """生成 Flow Launcher QuickFolderOpen 配置片段（指向各服务自己的 start.bat）。"""
    entries = []
    for svc in load_registry():
        bat = os.path.join(svc["path"], "start.bat")
        entries.append({
            "name": "快速启动web页面-" + svc["name"],
            "keywords": [svc["id"]],
            "path": bat if os.path.isfile(bat) else svc["path"],
        })
    return {"entries": entries}


@app.get("/api/services")
async def services_status():
    reg = load_registry()
    state = load_state()
    loop = asyncio.get_event_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(_PROBE_POOL, lambda s=svc: _probe(s)) for svc in reg])
    out = []
    for svc, st in zip(reg, results):
        rec = state.get(svc["id"]) or {}
        alive = st in ("running", "unresponsive")
        out.append({
            "id": svc["id"],
            "name": svc["name"],
            "icon": svc.get("icon", "🖥"),
            "desc": svc.get("desc", ""),
            "port": svc["port"],
            "path": svc["path"],
            "status": st,
            "started_at": rec.get("started_at", "") if alive else "",
            "pid": rec.get("pid", 0) if alive else 0,
            "claimed": bool(rec.get("claimed")) if alive else False,
            "cmdline": rec.get("cmdline", "") if alive else "",
        })
    return {"services": out}


@app.post("/api/services/{sid}/start")
async def start_service(sid: str, force: bool = False):
    svc = _find(sid)
    loop = asyncio.get_event_loop()
    if await loop.run_in_executor(_PROBE_POOL, port_open, svc["port"]):
        raise HTTPException(409, "端口 %d 已被占用，无需重复启动" % svc["port"])

    checks = await loop.run_in_executor(_PROBE_POOL, _run_checks, svc)
    if not force and checks and not all(c["ok"] for c in checks):
        return {"ok": False, "need_confirm": True, "checks": checks}

    os.makedirs(LOGS_DIR, exist_ok=True)
    _rotate_logs(sid)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = svc["cmd"]
    resolved = [cmd[0]] if os.path.isabs(cmd[0]) else [_which_or_fail(cmd[0])]
    cmd = resolved + cmd[1:]
    
    # 自动将 python.exe 替换为 pythonw.exe（无窗口解释器）
    if cmd and cmd[0].lower().endswith(("python.exe", "python")):
        pythonw = cmd[0].replace("python.exe", "pythonw.exe").replace("python", "pythonw")
        if os.path.isfile(pythonw):
            cmd[0] = pythonw

    def _do_start():
        _ensure_deps(svc)
        logf = open(_log_path(sid), "ab")
        proc = subprocess.Popen(
            cmd, cwd=svc["path"], stdout=logf, stderr=subprocess.STDOUT,
            env=env, creationflags=_DETACHED)
        state = load_state()
        state[sid] = {"pid": proc.pid,
                      "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        save_state(state)
        return proc.pid

    pid = await loop.run_in_executor(_PROBE_POOL, _do_start)
    return {"ok": True, "pid": pid}


@app.post("/api/services/{sid}/claim")
async def claim_service(sid: str):
    """接管：把手动启动（外部）的服务认领为 Hub 管理，之后可停止/看状态。"""
    svc = _find(sid)
    loop = asyncio.get_event_loop()
    pid = await loop.run_in_executor(_PROBE_POOL, port_pid, svc["port"])
    if not pid:
        raise HTTPException(409, "端口 %d 当前没有监听进程" % svc["port"])
    state = load_state()
    if state.get(sid):
        raise HTTPException(409, "该服务已在 Hub 管理中，无需重复接管")
    cmdline = await loop.run_in_executor(_PROBE_POOL, proc_cmdline, pid)
    state[sid] = {"pid": pid,
                  "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "claimed": True, "cmdline": cmdline[:300]}
    save_state(state)
    return {"ok": True, "pid": pid, "cmdline": cmdline[:300]}


@app.post("/api/services/{sid}/open_folder")
async def open_folder(sid: str):
    """在 Hub 所在机器上打开服务目录（仅本机访问有意义）。"""
    svc = _find(sid)
    p = os.path.normpath(svc["path"])
    if not os.path.isdir(p):
        raise HTTPException(404, "目录不存在: %s" % p)
    subprocess.Popen(["explorer", "/select,", p], creationflags=_DETACHED)
    return {"ok": True}


@app.get("/api/services/{sid}/check")
async def service_check(sid: str):
    svc = _find(sid)
    checks = await asyncio.get_event_loop().run_in_executor(
        _PROBE_POOL, _run_checks, svc)
    return {"checks": checks, "passed": all(c["ok"] for c in checks)}


@app.post("/api/services/{sid}/stop")
async def stop_service(sid: str):
    svc = _find(sid)
    state = load_state()
    rec = state.get(sid)
    if not rec:
        raise HTTPException(409, "该服务不是 Hub 启动的，无法停止（可手动关闭其窗口）")
    pid = rec.get("pid")

    def _kill():
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, creationflags=_DETACHED)

    await asyncio.get_event_loop().run_in_executor(_PROBE_POOL, _kill)
    state.pop(sid, None)
    save_state(state)
    return {"ok": True}


@app.get("/api/services/{sid}/log")
async def service_log(sid: str, tail: int = 200):
    _find(sid)
    return {"text": _tail_log(sid, tail)}


def _which_or_fail(exe: str) -> str:
    import shutil
    found = shutil.which(exe)
    if not found:
        raise HTTPException(500, "找不到可执行文件: %s" % exe)
    return found


if __name__ == "__main__":
    import uvicorn
    print("=" * 52)
    print("  Local Service Hub — 本地服务大厅")
    print("  本机访问: http://127.0.0.1:%d" % HUB_PORT)
    print("=" * 52)
    uvicorn.run(app, host="0.0.0.0", port=HUB_PORT, log_level="info")
