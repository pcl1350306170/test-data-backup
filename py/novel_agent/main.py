# -*- coding: utf-8 -*-
"""
本地 AI 小说服务（FastAPI）
- 提供 Web 控制台（index.html），局域网可访问
- 任务队列：大纲生成 / 按大纲写正文 / 单章重写
- 单任务锁：同一时间只允许一个生成任务
- 可选口令鉴权（config.json 中设置 password）
启动：python main.py  或  python -m uvicorn main:app --host 0.0.0.0 --port 8000
"""
import json
import os
import threading
import time
import uuid
import datetime

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

import novel_writer as nw

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "config.json")
DEFAULT_CFG = {
    "password": "",
    "model": "mynovel:latest",
    "ollama_host": "http://127.0.0.1:11434",
    "num_ctx": 16384,
    "num_predict": 2048,
    "temperature": 0.9,
    "repeat_penalty": 1.3,
    "frequency_penalty": 0.4,
    "outline_predict": 1024,
    "chapter_chars": 2000,
    "port": 8000,
}

def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    nw.CONFIG.update({
        "ollama_host": cfg["ollama_host"], "model": cfg["model"],
        "num_ctx": cfg["num_ctx"], "num_predict": cfg["num_predict"],
        "temperature": cfg["temperature"], "repeat_penalty": cfg["repeat_penalty"],
        "frequency_penalty": cfg["frequency_penalty"],
        "outline_predict": cfg["outline_predict"], "chapter_chars": cfg["chapter_chars"],
        "books_dir": os.path.join(BASE, cfg.get("books_dir", "books")),
    })
    return cfg

CFG = load_cfg()
os.makedirs(nw.CONFIG["books_dir"], exist_ok=True)

app = FastAPI(title="本地AI小说服务")

# ---------------------------------------------------------------- 任务管理
JOBS = {}          # id -> job dict
CURRENT_JOB_ID = None
JOB_LOCK = threading.Lock()


def _ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _new_job(jtype: str) -> dict:
    job = {
        "id": uuid.uuid4().hex[:12],
        "type": jtype,
        "state": "queued",
        "log_lines": [],
        "cancel_event": threading.Event(),
        "pause_event": threading.Event(),
        "created_at": _ts(),
        "current_chapter": 0,
        "total": 0,
        "completed": 0,
        "chunk_chars": 0,
        "book_dir": None,
        "result": None,
        "message": "",
    }

    def log(msg):
        line = "[%s] %s" % (_ts(), msg)
        job["log_lines"].append(line)
        if len(job["log_lines"]) > 400:
            job["log_lines"] = job["log_lines"][-400:]

    job["log"] = log
    return job


def _start_job(job: dict, fn):
    def runner():
        try:
            fn()
        except Exception as e:
            job["state"] = "error"
            job["log"]("系统异常：%s" % e)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


def _job_view(job: dict) -> dict:
    return {
        "id": job["id"], "type": job["type"], "state": job["state"],
        "current_chapter": job["current_chapter"], "total": job["total"],
        "completed": job["completed"], "chunk_chars": job["chunk_chars"],
        "created_at": job["created_at"], "book_dir": job["book_dir"],
        "result": job["result"], "message": job["message"],
        "log": job["log_lines"][-60:],
    }


def _active_job():
    if CURRENT_JOB_ID:
        j = JOBS.get(CURRENT_JOB_ID)
        if j and j["state"] in ("queued", "running", "paused"):
            return j
    return None


# ---------------------------------------------------------------- 鉴权
def check_auth(request: Request):
    pw = CFG.get("password", "")
    if not pw:
        return
    token = request.headers.get("X-Auth-Token", "")
    if token != pw:
        raise HTTPException(status_code=401, detail="口令错误")


# ---------------------------------------------------------------- 数据模型
class OutlineSpec(BaseModel):
    genre: str = ""
    style: str = ""
    total_words: int = 0
    chapter_chars: int = 0
    extra: str = ""


class JobCreate(BaseModel):
    type: str                      # outline | novel | chapter
    spec: OutlineSpec | None = None
    book: str | None = None        # novel/chapter 用：books 下的目录名
    start_chapter: int = 0         # novel 用：0=从进度续写
    chapter: int = 0               # chapter 用：要重写的章节号


class JobAction(BaseModel):
    action: str                    # pause | resume | stop


class ModelChange(BaseModel):
    model: str                     # 要切换的模型名（需已安装）


# ---------------------------------------------------------------- 页面
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "index.html"))


# ---------------------------------------------------------------- API
@app.get("/api/health")
def health(request: Request):
    check_auth(request)
    return {"ok": True, "model": CFG["model"], "ollama_online": nw.check_ollama()}


# ---------------------------------------------------------------- 模型管理
def _ollama_tags():
    """读取 Ollama 已安装模型列表。"""
    try:
        r = requests.get(nw.CONFIG["ollama_host"].rstrip("/") + "/api/tags", timeout=8)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


@app.get("/api/models")
def list_models(request: Request):
    check_auth(request)
    models = _ollama_tags()
    return {"models": models, "current": CFG["model"]}


@app.post("/api/models")
def switch_model(body: ModelChange, request: Request):
    check_auth(request)
    model = (body.model or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名不能为空")
    models = _ollama_tags()
    if model not in models:
        raise HTTPException(status_code=404, detail="模型不存在：%s（已安装：%s）" % (model, "、".join(models) or "无"))
    # 立即生效（后续任务使用新模型）
    CFG["model"] = model
    nw.CONFIG["model"] = model
    # 持久化到 config.json，重启后仍生效
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["model"] = model
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail="切换已生效但写入 config.json 失败：%s" % e)
    return {"ok": True, "model": model}


@app.post("/api/jobs")
def create_job(body: JobCreate, request: Request):
    check_auth(request)
    global CURRENT_JOB_ID
    with JOB_LOCK:
        if _active_job():
            raise HTTPException(status_code=409, detail="已有任务在运行（%s），请先等待或停止。" % _active_job()["type"])
        job = _new_job(body.type)
        JOBS[job["id"]] = job
        CURRENT_JOB_ID = job["id"]

    if body.type == "outline":
        spec = {
            "genre": body.spec.genre if body.spec else "",
            "style": body.spec.style if body.spec else "",
            "total_words": body.spec.total_words if body.spec else 0,
            "chapter_chars": body.spec.chapter_chars if body.spec else 0,
            "extra": body.spec.extra if body.spec else "",
        }
        if not any([spec["genre"], spec["style"], spec["extra"]]):
            job["state"] = "error"
            job["log"]("请至少填写题材或补充要求。")
            CURRENT_JOB_ID = None
        else:
            _start_job(job, lambda: nw.run_outline_job(spec, job))

    elif body.type == "novel":
        if not body.book:
            job["state"] = "error"; job["log"]("缺少 book 参数。"); CURRENT_JOB_ID = None
        else:
            book = body.book
            start = body.start_chapter or 0
            _start_job(job, lambda: nw.run_novel_job(book, start, job))

    elif body.type == "chapter":
        if not body.book or body.chapter < 1:
            job["state"] = "error"; job["log"]("缺少 book 或 chapter 参数。"); CURRENT_JOB_ID = None
        else:
            _start_job(job, lambda: nw.run_chapter_job(body.book, body.chapter, job))

    else:
        job["state"] = "error"; job["log"]("未知任务类型：%s" % body.type); CURRENT_JOB_ID = None

    return {"job_id": job["id"]}


@app.post("/api/jobs/{job_id}/action")
def job_action(job_id: str, body: JobAction, request: Request):
    check_auth(request)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if body.action == "pause":
        job["pause_event"].set()
        if job["state"] in ("running", "queued"):
            job["state"] = "paused"
            job["log"]("已暂停（当前章节写完/下章开始前生效）。")
    elif body.action == "resume":
        job["pause_event"].clear()
        if job["state"] == "paused":
            job["state"] = "running"
            job["log"]("已继续。")
    elif body.action == "stop":
        job["cancel_event"].set()
        job["log"]("停止指令已发出，正在中断…")
    else:
        raise HTTPException(status_code=400, detail="未知动作")
    return _job_view(job)


@app.get("/api/jobs")
def list_jobs(request: Request):
    check_auth(request)
    jobs = sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)[:10]
    out = []
    for j in jobs:
        out.append({
            "id": j["id"], "type": j["type"], "state": j["state"],
            "completed": j["completed"], "total": j["total"],
            "created_at": j["created_at"], "result": j["result"], "message": j["message"],
        })
    return {"jobs": out}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    check_auth(request)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_view(job)


@app.get("/api/books")
def list_books(request: Request):
    check_auth(request)
    root = nw.CONFIG["books_dir"]
    books = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            if not os.path.exists(os.path.join(d, "大纲.json")):
                continue
            prog = nw.load_progress(d)
            chapters = []
            for c in prog.get("chapters", []):
                chapters.append({"n": c.get("n"), "title": c.get("title"), "file": os.path.basename(c.get("file", ""))})
            books.append({
                "name": name,
                "title": prog.get("book_title", name),
                "total": prog.get("total_chapters", 0),
                "completed": prog.get("completed", 0),
                "chapters": chapters,
                "updated_at": prog.get("updated_at", ""),
            })
    return {"books": books}


@app.get("/api/books/{book}/chapters/{n}")
def get_chapter(book: str, n: int, request: Request):
    check_auth(request)
    root = nw.CONFIG["books_dir"]
    d = os.path.join(root, book)
    files = nw._chapter_files(d)
    if n < 1 or n > len(files):
        raise HTTPException(status_code=404, detail="章节不存在")
    with open(files[n - 1], "r", encoding="utf-8") as f:
        content = f.read()
    return {"n": n, "title": os.path.basename(files[n - 1])[:-3], "content": content}


@app.get("/api/books/{book}/outline")
def get_outline(book: str, request: Request):
    check_auth(request)
    p = os.path.join(nw.CONFIG["books_dir"], book, "大纲.json")
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="未找到大纲")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/books/{book}/download")
def download_book(book: str, request: Request):
    check_auth(request)
    root = nw.CONFIG["books_dir"]
    d = os.path.join(root, book)
    files = nw._chapter_files(d)
    if not files:
        raise HTTPException(status_code=404, detail="还没有任何章节")
    parts = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            parts.append(fh.read().strip())
    prog = nw.load_progress(d)
    title = prog.get("book_title", book)
    text = "\n\n".join(parts)
    filename = "%s.txt" % title
    # 简单防注入：文件名转义
    import urllib.parse
    quoted = urllib.parse.quote(filename)
    return PlainTextResponse(
        text, media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename*=UTF-8\'\'%s' % quoted},
    )


if __name__ == "__main__":
    port = int(CFG.get("port", 8000))
    print("=" * 56)
    print("  本地 AI 小说服务已启动")
    print("  本机访问:  http://127.0.0.1:%d" % port)
    import socket
    try:
        host = socket.gethostbyname(socket.gethostname())
        print("  局域网访问: http://%s:%d（需防火墙放行 %d 端口）" % (host, port, port))
    except Exception:
        pass
    if CFG.get("password"):
        print("  已启用口令保护")
    else:
        print("  ⚠ 未设置口令，局域网内任何人都可访问。建议在 config.json 设置 password")
    print("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
