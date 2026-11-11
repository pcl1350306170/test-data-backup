# -*- coding: utf-8 -*-
"""
语音速记本（本地服务 · MySQL 版）
- 访问 http://127.0.0.1:8010 （局域网内手机/电脑同网段可访问）
- 存储：MySQL（config.json → mysql，默认库 test，表前缀 vn_）
- 备份来源：GitHub 仓库里的 notes.json（支持静态页的 AES-GCM 密文），单向拉取
- 合并策略：本地为准——远端永不覆盖本地正文；远端删除只在本地打标记；本地删除不复活
- 定时：服务启动拉一次（可配），之后每天 00:00 自动拉一次，其余时间手动拉取
启动：python main.py 或双击 start.bat
"""
import datetime
import json
import os
import socket
import threading
import time
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import db
import ghsync

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = 8010

app = FastAPI(title="语音速记本（MySQL）")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PULL_LOCK = threading.Lock()
PULL_STATE = {"running": False}


# ---------------------------------------------------------------- 请求体
class NoteBody(BaseModel):
    content: str = ""
    category_id: Optional[str] = None
    client_id: str = ""
    created_at: str = ""
    tags: Optional[List[str]] = None


class NameBody(BaseModel):
    name: str = ""


class TagBindBody(BaseModel):
    tags: Optional[List[str]] = None
    name: str = ""


class ConfigBody(BaseModel):
    token: Optional[str] = None
    repo: Optional[str] = None
    path: Optional[str] = None
    branch: Optional[str] = None
    password: Optional[str] = None
    pull_on_start: Optional[bool] = None
    daily_at: Optional[str] = None


# ---------------------------------------------------------------- 基础
@app.get("/api/ping")
def ping():
    ok, err = True, ""
    try:
        conn = db.get_conn()
        conn.close()
    except Exception as e:
        ok, err = False, str(e)
    return {"ok": ok, "time": db.now(), "db": ok, "error": err,
            "last_pull_at": db.meta_get("last_pull_at", "")}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "index.html"))


# ---------------------------------------------------------------- 记录
@app.get("/api/notes")
def list_notes(kw: str = Query(""), category_id: Optional[str] = Query(None),
               tag_ids: str = Query(""), tag_match: str = Query("any"),
               remote: str = Query(""), start: str = Query(""), end: str = Query(""),
               limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
               order: str = Query("desc")):
    tids = [int(x) for x in tag_ids.split(",") if x.strip().isdigit()]
    rstat = [x for x in remote.split(",") if x in ("local", "synced", "deleted")] or None
    try:
        return db.list_notes(kw=kw, category_id=category_id, tag_ids=tids or None,
                             tag_match=tag_match if tag_match in ("any", "all") else "any",
                             remote_status=rstat, start=start, end=end,
                             limit=limit, offset=offset, order=order)
    except Exception as e:
        raise HTTPException(status_code=500, detail="查询失败：%s" % e)


@app.post("/api/notes")
def create_note(body: NoteBody):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    note = db.create_note(content, category_id=(body.category_id or ""), client_id=body.client_id,
                          created_at=body.created_at, source="local", tags=body.tags)
    if not note:
        raise HTTPException(status_code=500, detail="保存失败")
    return note


@app.get("/api/notes/{note_id}")
def get_note(note_id: str):
    note = db.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="记录不存在")
    return note


@app.put("/api/notes/{note_id}")
def update_note(note_id: str, body: NoteBody):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    note = db.update_note(note_id, content=content, category_id=body.category_id, tags=body.tags)
    if not note:
        raise HTTPException(status_code=404, detail="记录不存在")
    return note


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    if not db.delete_note(note_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True, "tombstoned": True}


@app.post("/api/notes/{note_id}/copy")
def record_copy(note_id: str):
    if not db.record_copy(note_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return db.get_note(note_id)


@app.put("/api/notes/{note_id}/tags")
def bind_tags(note_id: str, body: TagBindBody):
    if not db.get_note(note_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    db.set_note_tags(note_id, body.tags or [])
    return db.get_note(note_id)


# ---------------------------------------------------------------- 分类
@app.get("/api/categories")
def list_categories():
    return {"categories": db.list_categories()}


@app.post("/api/categories")
def create_category(body: NameBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(name) > 20:
        raise HTTPException(status_code=400, detail="分类名最长 20 字")
    return db.create_category(name)


@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: str):
    if not db.delete_category(cat_id):
        raise HTTPException(status_code=404, detail="分类不存在")
    return {"ok": True}


# ---------------------------------------------------------------- 标签（仅本地）
@app.get("/api/tags")
def list_tags():
    return {"tags": db.list_tags()}


@app.post("/api/tags")
def create_tag(body: NameBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    ids = db.ensure_tags([name])
    return {"id": ids[0] if ids else None, "name": name}


@app.put("/api/tags/{tag_id}")
def rename_tag(tag_id: int, body: NameBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    if not db.rename_tag(tag_id, name):
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"ok": True}


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int):
    if not db.delete_tag(tag_id):
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"ok": True}


# ---------------------------------------------------------------- 统计 / 导出
@app.get("/api/stats")
def stats():
    out = db.stats()
    out["sync"] = ghsync.status()
    out["pulling"] = PULL_STATE["running"]
    return out


@app.get("/api/export")
def export():
    data = db.export_all()
    body = json.dumps(data, ensure_ascii=False, indent=2)
    fname = "voice_notes_mysql_%s.json" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(content=body, media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % fname})


# ---------------------------------------------------------------- GitHub 拉取
def _do_pull():
    if not PULL_LOCK.acquire(blocking=False):
        return {"ok": False, "skipped": True, "reason": "已有拉取任务在进行中"}
    PULL_STATE["running"] = True
    try:
        return ghsync.pull()
    except ghsync.SyncError as e:
        db.meta_set("last_pull_result", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return {"ok": False, "error": str(e)}
    except Exception as e:
        db.meta_set("last_pull_result", json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return {"ok": False, "error": "拉取异常：%s" % e}
    finally:
        PULL_STATE["running"] = False
        PULL_LOCK.release()


@app.post("/api/sync/pull")
def sync_pull():
    res = _do_pull()
    if not res.get("ok") and not res.get("skipped"):
        raise HTTPException(status_code=502, detail=res.get("error", "拉取失败"))
    return res


@app.get("/api/sync/status")
def sync_status():
    out = ghsync.status()
    out["pulling"] = PULL_STATE["running"]
    return out


@app.put("/api/config")
def update_config(body: ConfigBody):
    cfg = db.load_config()
    for key in ("token", "repo", "path", "branch", "password"):
        val = getattr(body, key)
        if val is not None:
            cfg["github"][key] = val.strip() if isinstance(val, str) else val
    if body.pull_on_start is not None:
        cfg["sync"]["pull_on_start"] = bool(body.pull_on_start)
    if body.daily_at is not None:
        if not _valid_hhmm(body.daily_at):
            raise HTTPException(status_code=400, detail="定时格式应为 HH:MM")
        cfg["sync"]["daily_at"] = body.daily_at
    db.save_config(cfg)
    return ghsync.status()


def _valid_hhmm(s):
    try:
        datetime.datetime.strptime((s or "").strip(), "%H:%M")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 定时器（后台线程，无第三方依赖）
def _next_run(at):
    hh, mm = 0, 0
    if _valid_hhmm(at):
        hh, mm = int(at[:2]), int(at[3:5])
    now_dt = datetime.datetime.now()
    nxt = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nxt <= now_dt:
        nxt += datetime.timedelta(days=1)
    return nxt


def _scheduler_loop():
    cfg = db.load_config()["sync"]
    if cfg.get("pull_on_start"):
        time.sleep(2)
        res = _do_pull()
        print("[sync] 启动拉取：%s" % json.dumps(res, ensure_ascii=False))
    while True:
        nxt = _next_run(db.load_config()["sync"].get("daily_at", "00:00"))
        wait = max(1.0, (nxt - datetime.datetime.now()).total_seconds())
        print("[sync] 下次自动拉取：%s（%.0f 分钟后）" % (nxt.strftime("%Y-%m-%d %H:%M"), wait / 60))
        time.sleep(wait)
        res = _do_pull()
        print("[sync] 定时拉取：%s" % json.dumps(res, ensure_ascii=False))


def _bootstrap():
    try:
        n = db.init_db()
        print("[db] MySQL 就绪（库：%s）%s" % (db.load_config()["mysql"]["database"],
                                          "，导入旧记录 %d 条" % n if n else ""))
    except Exception as e:
        print("[db] 初始化失败：%s" % e)
    threading.Thread(target=_scheduler_loop, daemon=True).start()


if __name__ == "__main__":
    _bootstrap()
    print("=" * 52)
    print("  语音速记本（MySQL 版）已启动")
    print("  本机访问:   http://127.0.0.1:%d" % PORT)
    try:
        host = socket.gethostbyname(socket.gethostname())
        print("  手机访问:   http://%s:%d  （需同一 WiFi）" % (host, PORT))
    except Exception:
        pass
    print("  按 Ctrl+C 停止服务")
    print("=" * 52)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
