# -*- coding: utf-8 -*-
"""Grok 会话导出工具 - 本地 Web 服务（端口 8801）"""
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from core import json_loader, conversation_parser, exporter
from core.exporter import ExportOptions, default_output_dir

# ── 路径与常量 ────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "port": 8801,
    "last_json_path": "",
    "last_output_dir": "",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "grok_exporter.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("grok_exporter")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except Exception as exc:
        logger.warning("配置读取失败，使用默认值：%s", exc)
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ── 全局状态 ─────────────────────────────────────────
_state_lock = threading.Lock()
_loaded: Dict[str, Any] = {
    "path": None,
    "size": 0,
    "sessions": [],
    "summary": {},
}

_tasks: Dict[str, Dict[str, Any]] = {}
# { task_id: { events: [...], cancel_event: Event, done: bool, result: {...} } }


# ── FastAPI ─────────────────────────────────────────
app = FastAPI(title="Grok 会话导出工具")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/ping")
def ping():
    return {"ok": True, "service": "grok_exporter", "ts": time.time()}


@app.get("/api/config")
def get_config():
    return load_config()


@app.post("/api/config")
def update_config(cfg: dict):
    cur = load_config()
    cur.update(cfg or {})
    save_config(cur)
    return {"ok": True}


# ── 文件选择（服务端弹出原生对话框） ─────────────────
@app.post("/api/pick_file")
def pick_file():
    """在桌面会话中弹出系统文件选择框。WSL/无显示环境会返回错误。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"tkinter 不可用：{exc}")

    def _do():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="选择 Grok 导出的 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        root.destroy()
        return path

    try:
        path = _do()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开文件对话框失败：{exc}")
    return {"path": path or ""}


@app.post("/api/pick_dir")
def pick_dir():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"tkinter 不可用：{exc}")

    def _do():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="选择导出目录")
        root.destroy()
        return path

    try:
        path = _do()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开目录对话框失败：{exc}")
    return {"path": path or ""}


# ── 加载与解析 ───────────────────────────────────────
def _sessions_payload(sessions: list) -> list:
    """前端列表所需字段（不含消息正文，避免一次返回过大）。"""
    out = []
    for s in sessions:
        humans = sum(1 for m in s["messages"] if m["sender"] == "human")
        groks = sum(1 for m in s["messages"] if m["sender"] == "assistant")
        out.append({
            "index": s["index"],
            "id": s["id"],
            "title": s["title"],
            "create_time": s["create_time"],
            "modify_time": s["modify_time"],
            "summary": s["summary"],
            "message_count": len(s["messages"]),
            "human_count": humans,
            "grok_count": groks,
            "total_response_count": s["total_response_count"],
            "ordering_strategy": s["ordering_strategy"],
        })
    return out


@app.post("/api/load")
def load_payload(body: dict):
    path = (body or {}).get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="缺少 path 参数")
    try:
        data = json_loader.load_json(path)
    except json_loader.JsonLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    sessions = conversation_parser.parse_all(data)
    summary = conversation_parser.summarize(sessions)

    p = Path(path)
    size = p.stat().st_size if p.exists() else 0

    with _state_lock:
        _loaded["path"] = str(p.resolve())
        _loaded["size"] = size
        _loaded["sessions"] = sessions
        _loaded["summary"] = summary

    # 写入上次路径配置
    cfg = load_config()
    cfg["last_json_path"] = str(p.resolve())
    cfg["last_output_dir"] = str(default_output_dir(p))
    save_config(cfg)

    return {
        "ok": True,
        "path": str(p.resolve()),
        "size": size,
        "summary": summary,
        "sessions": _sessions_payload(sessions),
        "default_output_dir": str(default_output_dir(p)),
    }


@app.get("/api/state")
def get_state():
    """页面刷新后恢复使用。"""
    with _state_lock:
        if not _loaded["sessions"]:
            return {"loaded": False}
        return {
            "loaded": True,
            "path": _loaded["path"],
            "size": _loaded["size"],
            "summary": _loaded["summary"],
            "sessions": _sessions_payload(_loaded["sessions"]),
            "default_output_dir": str(default_output_dir(_loaded["path"])) if _loaded["path"] else None,
        }


# ── 预览 ────────────────────────────────────────────
@app.post("/api/preview")
def preview(body: dict):
    """返回单会话的 MD 与 TXT 预览文本（不写文件）。"""
    idx = int((body or {}).get("index", 0))
    scope = (body or {}).get("scope", "all")
    fmt = (body or {}).get("format", "md")
    with _state_lock:
        sess = next((s for s in _loaded["sessions"] if s["index"] == idx), None)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在或未加载数据")

    render_opts = {
        "title": True,
        "time_meta": True,
        "sender_label": True,
        "timestamp": True,
        "separator": True,
        "preserve_markdown": (fmt == "md"),
        "scope": scope,
    }
    from core import markdown_exporter, txt_exporter
    if fmt == "txt":
        text = txt_exporter.render_conversation_txt(sess, render_opts)
    else:
        text = markdown_exporter.render_conversation_md(sess, render_opts)

    return {"ok": True, "title": sess["title"], "format": fmt, "text": text,
            "message_count": len(sess["messages"])}


# ── 导出（后台线程 + 取消） ─────────────────────────
@app.post("/api/export")
def start_export(body: dict):
    options = (body or {}).get("options") or {}
    selected = (body or {}).get("selected") or []
    if not isinstance(selected, list) or not selected:
        raise HTTPException(status_code=400, detail="未选择要导出的会话")

    with _state_lock:
        sessions_all = list(_loaded["sessions"])
    if not sessions_all:
        raise HTTPException(status_code=400, detail="尚未加载 JSON 数据")

    sel_set = set(int(x) for x in selected)
    sessions = [s for s in sessions_all if s["index"] in sel_set]
    if not sessions:
        raise HTTPException(status_code=400, detail="所选会话都不存在")

    opts = ExportOptions(options)
    if not opts.output_dir:
        opts.output_dir = str(default_output_dir(_loaded["path"]))

    task_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    record = {
        "events": [],
        "cancel_event": cancel_event,
        "done": False,
        "result": None,
        "started_at": time.time(),
    }
    _tasks[task_id] = record

    def push(ev):
        record["events"].append({**ev, "ts": time.time()})

    def worker():
        try:
            res = exporter.run_export(sessions, opts, progress_cb=push,
                                       cancel_event=cancel_event)
            record["result"] = {
                "success": res.success,
                "failed": res.failed,
                "cancelled": res.cancelled,
                "files": res.files,
                "errors": res.errors,
                "output_dir": str(opts.output_dir),
            }
        except Exception as exc:
            logger.exception("导出线程异常")
            record["result"] = {"error": f"{type(exc).__name__}: {exc}"}
            record["events"].append({"stage": "fatal", "error": str(exc)})
        finally:
            record["done"] = True

    th = threading.Thread(target=worker, daemon=True, name=f"grok-export-{task_id[:8]}")
    th.start()
    return {"task_id": task_id, "output_dir": str(opts.output_dir)}


@app.get("/api/progress")
def progress(task_id: str, since: int = 0):
    rec = _tasks.get(task_id)
    if not rec:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = rec["events"][since:]
    return {
        "ok": True,
        "done": rec["done"],
        "events": events,
        "next": since + len(events),
        "result": rec["result"],
    }


@app.post("/api/cancel")
def cancel(body: dict):
    task_id = (body or {}).get("task_id", "")
    rec = _tasks.get(task_id)
    if not rec:
        raise HTTPException(status_code=404, detail="任务不存在")
    rec["cancel_event"].set()
    return {"ok": True}


@app.post("/api/open_dir")
def open_dir(body: dict):
    """在 Windows 资源管理器中打开导出目录。"""
    path = (body or {}).get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="缺少 path")
    p = Path(path)
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"目录无法创建：{exc}")
    if sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]
    else:
        import subprocess
        subprocess.Popen(["xdg-open", str(p)])
    return {"ok": True}


UPLOAD_DIR = DATA_DIR / "uploads"


@app.post("/api/upload")
async def upload_json(file: UploadFile = File(...)):
    """浏览器拖拽 / 文件上传：保存到 data/uploads/ 并解析。"""
    name = (file.filename or "upload.json").strip()
    safe = "".join(c for c in name if c.isalnum() or c in "._-") or "upload.json"
    if not safe.lower().endswith(".json"):
        safe += ".json"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_DIR / f"{int(time.time())}_{safe}"
    try:
        with save_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存上传文件失败：{exc}")
    return load_payload({"path": str(save_path)})


# ── 启动入口 ─────────────────────────────────────────
if __name__ == "__main__":
    cfg = load_config()
    port = int(cfg.get("port", 8801))
    print("=" * 56)
    print("  Grok 会话导出工具 已启动")
    print(f"  本机访问：http://127.0.0.1:{port}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
