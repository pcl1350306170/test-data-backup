# -*- coding: utf-8 -*-
"""
语音速记本（FastAPI 本地服务）
- 手机/电脑浏览器访问 http://<本机IP>:8010
- 手机端用输入法语音键转文字后保存，电脑端查看/编辑/删除
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

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE, "notes.json")
PORT = 8010

app = FastAPI(title="语音速记本")
LOCK = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


# ---------------------------------------------------------------- 页面
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "index.html"))


# ---------------------------------------------------------------- API
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
    note = {
        "id": uuid.uuid4().hex[:12],
        "content": content,
        "created_at": _now(),
        "updated_at": "",
    }
    with LOCK:
        notes = _load_notes()
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
