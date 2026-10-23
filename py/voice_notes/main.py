# -*- coding: utf-8 -*-
"""
语音速记本（FastAPI 本地服务）
- 手机/电脑浏览器访问 http://<本机IP>:8010
- 手机端用输入法语音键转文字后保存，电脑端查看/编辑/删除
- 记录支持分类（categories.json），手机/电脑两端同步
- 数据存本地 notes.json，无口令，局域网免密
启动：python main.py   或双击 start.bat
"""
import json
import os
import threading
import uuid
import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "notes.json")
CAT_PATH = os.path.join(BASE, "categories.json")
PORT = 8010

DEFAULT_CATS = [
    {"id": "cat_daily", "name": "日常记录"},
    {"id": "cat_xianjian4", "name": "仙剑四游戏同人小说大纲"},
]

app = FastAPI(title="语音速记本")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
LOCK = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 记录
def _load_notes() -> list:
    if not os.path.exists(DATA_PATH):
        return []
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_notes(notes: list):
    """先写临时文件再替换，避免写一半崩溃导致数据损坏。"""
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)


def _sort_notes(notes: list) -> list:
    """按录入时间倒序（新记录在最上）。"""
    return sorted(notes, key=lambda n: n.get("created_at", ""), reverse=True)


class NoteBody(BaseModel):
    content: str = ""
    created_at: str = ""    # 可选：客户端提供的录入时间（离线同步保留原时间）
    client_id: str = ""     # 可选：客户端唯一 ID（幂等去重，防止重复推送）
    category_id: str = ""   # 可选：所属分类


class BatchNotesBody(BaseModel):
    notes: list = []


# ---------------------------------------------------------------- 分类
def _load_categories() -> list:
    if not os.path.exists(CAT_PATH):
        return [dict(c) for c in DEFAULT_CATS]
    try:
        with open(CAT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
        return [dict(c) for c in DEFAULT_CATS]
    except Exception:
        return [dict(c) for c in DEFAULT_CATS]


def _save_categories(cats: list):
    tmp = CAT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cats, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CAT_PATH)


class CategoryBody(BaseModel):
    name: str = ""


# ---------------------------------------------------------------- 健康检测
@app.get("/api/ping")
def ping():
    return {"ok": True, "time": _now()}


# ---------------------------------------------------------------- 页面
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "index.html"))


# ---------------------------------------------------------------- 分类 API
@app.get("/api/categories")
def list_categories():
    with LOCK:
        cats = _load_categories()
        notes = _load_notes()
        counts = {}
        for n in notes:
            cid = n.get("category_id", "")
            counts[cid] = counts.get(cid, 0) + 1
        out = [{"id": c["id"], "name": c["name"], "count": counts.get(c["id"], 0)} for c in cats]
        out.append({"id": "", "name": "未分类", "count": counts.get("", 0)})
    return {"categories": out}


@app.post("/api/categories")
def create_category(body: CategoryBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名不能为空")
    if len(name) > 20:
        raise HTTPException(status_code=400, detail="分类名最长 20 字")
    with LOCK:
        cats = _load_categories()
        for c in cats:
            if c["name"] == name:
                raise HTTPException(status_code=400, detail="分类已存在：%s" % name)
        cat = {"id": uuid.uuid4().hex[:12], "name": name}
        cats.append(cat)
        _save_categories(cats)
    return cat


@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: str):
    with LOCK:
        cats = _load_categories()
        kept = [c for c in cats if c["id"] != cat_id]
        if len(kept) == len(cats):
            raise HTTPException(status_code=404, detail="分类不存在")
        _save_categories(kept)
        # 该分类下的记录归入"未分类"
        notes = _load_notes()
        changed = False
        for n in notes:
            if n.get("category_id", "") == cat_id:
                n["category_id"] = ""
                changed = True
        if changed:
            _save_notes(notes)
    return {"ok": True}


@app.delete("/api/categories/{cat_id}/notes")
def clear_category_notes(cat_id: str):
    """清空指定分类下的所有记录（保留分类本身）。"""
    with LOCK:
        cats = _load_categories()
        if not any(c["id"] == cat_id for c in cats):
            raise HTTPException(status_code=404, detail="分类不存在")
        notes = _load_notes()
        kept = [n for n in notes if n.get("category_id", "") != cat_id]
        removed = len(notes) - len(kept)
        if removed:
            _save_notes(kept)
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------- 记录 API
@app.get("/api/notes")
def list_notes():
    with LOCK:
        notes = _sort_notes(_load_notes())
    return {"notes": notes}


@app.post("/api/notes")
def create_note(body: NoteBody):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    created_at = (body.created_at or "").strip()
    if created_at:
        try:
            datetime.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            created_at = ""
    if not created_at:
        created_at = _now()
    note = {
        "id": uuid.uuid4().hex[:12],
        "content": content,
        "created_at": created_at,
        "updated_at": "",
        "category_id": (body.category_id or "").strip(),
        "copy_count": 0,
        "last_copied_at": "",
    }
    if body.client_id:
        note["client_id"] = body.client_id
    with LOCK:
        notes = _load_notes()
        if body.client_id:
            for n in notes:
                if n.get("client_id") == body.client_id:
                    return n  # 幂等：同一条记录重复推送时直接返回已有记录
        notes.append(note)
        _save_notes(notes)
    return note


@app.put("/api/notes/{note_id}")
def update_note(note_id: str, body: NoteBody):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    with LOCK:
        notes = _load_notes()
        for n in notes:
            if n.get("id") == note_id:
                n["content"] = content
                n["updated_at"] = _now()
                if body.category_id is not None:
                    n["category_id"] = (body.category_id or "").strip()
                _save_notes(notes)
                return n
    raise HTTPException(status_code=404, detail="记录不存在")


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    with LOCK:
        notes = _load_notes()
        kept = [n for n in notes if n.get("id") != note_id]
        if len(kept) == len(notes):
            raise HTTPException(status_code=404, detail="记录不存在")
        _save_notes(kept)
    return {"ok": True}


@app.post("/api/notes/{note_id}/copy")
def record_copy(note_id: str):
    """记录一次复制行为，更新复制次数和最近复制时间。"""
    with LOCK:
        notes = _load_notes()
        for n in notes:
            if n.get("id") == note_id:
                n["copy_count"] = n.get("copy_count", 0) + 1
                n["last_copied_at"] = _now()
                _save_notes(notes)
                return n
    raise HTTPException(status_code=404, detail="记录不存在")


@app.post("/api/notes/batch")
def batch_import(body: BatchNotesBody):
    """批量导入记录（按 client_id 去重，已存在的跳过）。"""
    added = 0
    with LOCK:
        notes = _load_notes()
        existing_ids = set()
        for n in notes:
            if n.get("client_id"):
                existing_ids.add(n["client_id"])
            if n.get("id"):
                existing_ids.add(n["id"])
        for item in body.notes:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            cid = (item.get("client_id") or "").strip()
            if cid and cid in existing_ids:
                continue
            created_at = (item.get("created_at") or "").strip()
            if created_at:
                try:
                    datetime.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    created_at = _now()
            else:
                created_at = _now()
            note = {
                "id": uuid.uuid4().hex[:12],
                "content": content,
                "created_at": created_at,
                "updated_at": "",
                "category_id": (item.get("category_id") or "").strip(),
                "copy_count": item.get("copy_count", 0),
                "last_copied_at": item.get("last_copied_at", ""),
            }
            if cid:
                note["client_id"] = cid
                existing_ids.add(cid)
            notes.append(note)
            added += 1
        if added:
            _save_notes(notes)
    return {"ok": True, "added": added}


if __name__ == "__main__":
    print("=" * 52)
    print("  语音速记本已启动")
    print("  本机访问:   http://127.0.0.1:%d" % PORT)
    import socket
    try:
        host = socket.gethostbyname(socket.gethostname())
        print("  手机访问:   http://%s:%d  （需同一 WiFi）" % (host, PORT))
    except Exception:
        pass
    print("  按 Ctrl+C 停止服务")
    print("=" * 52)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
