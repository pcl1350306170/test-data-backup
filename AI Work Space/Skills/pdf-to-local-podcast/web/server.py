# -*- coding: utf-8 -*-
"""本地播客制作 Web 系统 — FastAPI 主入口。

提供脚本管理、音色管理、任务执行（SSE 实时进度）、音频合并+BGM、在线播放等 API。
前端 HTML/JS/CSS 由本服务直接托管。
"""
import asyncio
import json
import os
import shutil
import time
import webbrowser

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import config, voice_manager, script_parser
from core.task_engine import TaskEngine

# ── 初始化 ──────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="本地播客制作系统")
engine = TaskEngine()

# 静态文件托管
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── 辅助函数 ──────────────────────────────────────────

def _safe_path(path, allowed_dirs):
    """检查路径是否在允许目录内（防路径穿越）。"""
    real = os.path.realpath(path)
    for d in allowed_dirs:
        if real.startswith(os.path.realpath(d)):
            return True
    return False


def _get_cfg():
    return config.load()


# ── 首页 ──────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── 脚本管理 ──────────────────────────────────────────

@app.get("/api/scripts")
async def list_scripts():
    cfg = _get_cfg()
    scripts = []
    seen = set()
    for d in cfg.get("script_dirs", []):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".md") and f not in seen:
                seen.add(f)
                fp = os.path.join(d, f)
                scripts.append({
                    "name": f,
                    "path": fp,
                    "size": os.path.getsize(fp),
                    "modified": time.ctime(os.path.getmtime(fp)),
                    "source": d,
                })
    return {"scripts": scripts}


@app.get("/api/scripts/content")
async def get_script_content(path: str = Query(...)):
    cfg = _get_cfg()
    allowed = cfg.get("script_dirs", []) + [cfg.get("output_dir", "")]
    if not _safe_path(path, allowed):
        raise HTTPException(403, "路径不在允许目录内")
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return {"path": path, "content": content}


@app.post("/api/scripts")
async def save_script(data: dict):
    path = data.get("path", "")
    content = data.get("content", "")
    name = data.get("name", "")
    cfg = _get_cfg()

    if not path:
        # 新建：放到第一个脚本目录
        base_dir = cfg["script_dirs"][0] if cfg["script_dirs"] else None
        if not base_dir:
            raise HTTPException(400, "未配置脚本目录")
        os.makedirs(base_dir, exist_ok=True)
        if not name.endswith(".md"):
            name += ".md"
        path = os.path.join(base_dir, name)

    if not name:
        name = os.path.basename(path)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True, "path": path, "name": name}


@app.post("/api/scripts/upload")
async def upload_script(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".md"):
        raise HTTPException(400, "仅支持 .md 文件")
    cfg = _get_cfg()
    base_dir = cfg["script_dirs"][0] if cfg["script_dirs"] else None
    if not base_dir:
        raise HTTPException(400, "未配置脚本目录")
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, file.filename)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    return {"ok": True, "path": path, "name": file.filename}


@app.post("/api/scripts/parse")
async def parse_script_api(data: dict):
    path = data.get("path", "")
    if not os.path.isfile(path):
        raise HTTPException(404, "脚本文件不存在")
    try:
        result = script_parser.parse_preview(path)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/scripts/delete")
async def delete_script(data: dict):
    path = data.get("path", "")
    cfg = _get_cfg()
    allowed = cfg.get("script_dirs", [])
    if not _safe_path(path, allowed):
        raise HTTPException(403, "路径不在允许目录内")
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在")
    os.remove(path)
    return {"ok": True}


# ── 音色管理 ──────────────────────────────────────────

@app.get("/api/voices")
async def list_voices():
    voices = voice_manager.get_all()
    result = []
    for name, info in voices.items():
        result.append({
            "name": name,
            "type": info.get("type", "未知"),
            "audio_file": os.path.basename(info["audio"]),
            "audio_path": info["audio"],
            "prompt_text": info.get("prompt_text", ""),
        })
    return {"voices": result}


@app.get("/api/voices/scan")
async def scan_voices():
    return {"unregistered": voice_manager.scan_tts_dir()}


@app.post("/api/voices")
async def add_voice(data: dict):
    name = data.get("name", "").strip()
    audio_file = data.get("audio_file", "").strip()
    prompt_text = data.get("prompt_text", "").strip() or None
    voice_type = data.get("type", "未知")
    if not name or not audio_file:
        raise HTTPException(400, "名称和音频文件必填")
    try:
        info = voice_manager.add_voice(name, audio_file, prompt_text, voice_type)
        return {"ok": True, "voice": {
            "name": name,
            "type": info["type"],
            "audio_file": os.path.basename(info["audio"]),
        }}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/voices/{name}")
async def delete_voice(name: str):
    try:
        voice_manager.remove_voice(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── 任务管理 ──────────────────────────────────────────

@app.post("/api/task/start")
async def start_task(data: dict):
    # 支持多选脚本：script_paths 数组（或兼容旧的 script_path 单脚本）
    paths = data.get("script_paths") or ([data["script_path"]] if data.get("script_path") else [])
    paths = [p for p in paths if p and os.path.isfile(p)]
    if not paths:
        raise HTTPException(400, "未找到有效的脚本文件")

    output_name = data.get("output_name", "").strip()
    if not output_name and len(paths) == 1:
        # 单任务未指定输出名时取脚本书名；多任务各自取书名
        try:
            info, _, _ = script_parser.parse_script(paths[0])
            output_name = info.get("书名", os.path.splitext(os.path.basename(paths[0]))[0])
        except Exception:
            output_name = os.path.splitext(os.path.basename(paths[0]))[0]

    ok, err = engine.start(
        script_paths=paths,
        output_name=output_name,
        bgm_path=data.get("bgm_path"),
        bgm_volume=data.get("bgm_volume", 30),
        lufs=data.get("lufs", -16),
        gap_ms=data.get("gap_ms", 400),
    )
    if not ok:
        raise HTTPException(409, err)
    return {"ok": True, "total_jobs": len(paths)}


@app.get("/api/task/status")
async def task_status():
    st = engine.get_status()
    # 取消进行中将队列拆掉，快照中直接反映为已取消
    if st["status"] == "cancelling" and not engine._jobs:
        st["status"] = "cancelled"
    return st


@app.post("/api/task/cancel")
async def cancel_task():
    ok = engine.cancel()
    return {"ok": ok}


@app.post("/api/task/pause")
async def pause_task():
    ok = engine.pause()
    return {"ok": ok}


@app.post("/api/task/resume")
async def resume_task():
    ok = engine.resume()
    return {"ok": ok}


@app.post("/api/task/retry-failed")
async def retry_failed():
    ok, err = engine.retry_failed()
    if not ok:
        raise HTTPException(400, err)
    return {"ok": True}


@app.get("/api/task/progress")
async def task_progress():
    """SSE 端点：实时推送任务进度。"""
    queue, loop = engine.subscribe()

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield "data: %s\n\n" % json.dumps(event, ensure_ascii=False)
                    if event.get("type") in ("complete", "error", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield "data: %s\n\n" % json.dumps({"type": "heartbeat"})
        except asyncio.CancelledError:
            pass
        finally:
            engine.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 音频管理 ──────────────────────────────────────────

@app.get("/api/audio/podcast")
async def list_podcasts():
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    podcasts = []
    if os.path.isdir(output_dir):
        for f in sorted(os.listdir(output_dir)):
            if f.lower().endswith(".mp3"):
                fp = os.path.join(output_dir, f)
                stat = os.stat(fp)
                podcasts.append({
                    "name": f,
                    "path": fp,
                    "size": stat.st_size,
                    "modified": time.ctime(stat.st_mtime),
                })
    return {"podcasts": podcasts}


@app.get("/api/audio/play")
async def play_audio(file: str = Query(...)):
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    fp = os.path.join(output_dir, os.path.basename(file))
    if not os.path.isfile(fp):
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(fp, media_type="audio/mpeg",
                        headers={"Accept-Ranges": "bytes"})


@app.get("/api/audio/download")
async def download_audio(file: str = Query(...)):
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    fp = os.path.join(output_dir, os.path.basename(file))
    if not os.path.isfile(fp):
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(fp, media_type="audio/mpeg",
                        filename=os.path.basename(fp),
                        headers={"Content-Disposition": "attachment"})


@app.post("/api/audio/clean")
async def clean_audio():
    """清理中间产物（任务子目录 audio_dir\\{输出名} 及旧布局的散wav）。"""
    cfg = _get_cfg()
    audio_dir = cfg.get("audio_dir", "")
    if not audio_dir or not os.path.isdir(audio_dir):
        return {"ok": True, "cleaned": 0}
    # 跳过正在运行任务的目录
    skip_dir = None
    if engine.status in ("parsing", "generating", "merging", "paused", "cancelling"):
        try:
            skip_dir = os.path.realpath(engine._task_audio_dir())
        except Exception:
            pass
    count = 0
    for f in os.listdir(audio_dir):
        fp = os.path.join(audio_dir, f)
        if os.path.isfile(fp) and f.lower().endswith(".wav"):
            os.remove(fp)
            count += 1
        elif os.path.isdir(fp):
            # 任务子目录（含内部 _norm）整体删除；旧布局的 _ 开头临时目录同样处理
            if os.path.realpath(fp) == skip_dir:
                continue
            shutil.rmtree(fp, ignore_errors=True)
            count += 1
    return {"ok": True, "cleaned": count}


# ── BGM 管理 ──────────────────────────────────────────

@app.post("/api/bgm/upload")
async def upload_bgm(file: UploadFile = File(...)):
    cfg = _get_cfg()
    bgm_dir = cfg.get("bgm_dir", os.path.join(BASE_DIR, "uploads"))
    os.makedirs(bgm_dir, exist_ok=True)
    path = os.path.join(bgm_dir, file.filename)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    return {"ok": True, "name": file.filename, "path": path}


@app.get("/api/bgm/list")
async def list_bgm():
    cfg = _get_cfg()
    bgm_dir = cfg.get("bgm_dir", os.path.join(BASE_DIR, "uploads"))
    bgms = []
    if os.path.isdir(bgm_dir):
        for f in sorted(os.listdir(bgm_dir)):
            ext = os.path.splitext(f)[1].lower()
            if ext in {".mp3", ".wav", ".ogg", ".m4a", ".flac"}:
                fp = os.path.join(bgm_dir, f)
                bgms.append({
                    "name": f,
                    "path": fp,
                    "size": os.path.getsize(fp),
                })
    return {"bgms": bgms}


# ── 独立合并（重新合并 / 更换 BGM） ────────────────────

@app.get("/api/audio/tasks")
async def list_audio_tasks():
    """列出 audio_dir 下可用的音频块任务目录。"""
    import re as _re
    cfg = _get_cfg()
    audio_dir = cfg.get("audio_dir", "")
    tasks = []
    if audio_dir and os.path.isdir(audio_dir):
        for name in sorted(os.listdir(audio_dir)):
            fp = os.path.join(audio_dir, name)
            if not os.path.isdir(fp) or name.startswith("_"):
                continue
            # 统计 wav 块数
            wav_count = sum(1 for f in os.listdir(fp)
                           if _re.match(r"^\d+\.wav$", f, _re.IGNORECASE))
            if wav_count > 0:
                tasks.append({
                    "name": name,
                    "blocks": wav_count,
                })
    return {"tasks": tasks}


@app.post("/api/task/remerge")
async def remerge_task(data: dict):
    """独立合并：用已有音频块重新合并，可更换 BGM。"""
    audio_task = data.get("audio_task", "").strip()
    if not audio_task:
        raise HTTPException(400, "未指定音频任务目录")

    ok, err = engine.remerge(
        audio_task=audio_task,
        bgm_path=data.get("bgm_path") or None,
        bgm_volume=data.get("bgm_volume", 30),
        lufs=data.get("lufs", -16),
        gap_ms=data.get("gap_ms", 400),
        output_name=data.get("output_name", "").strip() or None,
    )
    if not ok:
        raise HTTPException(409, err)
    return {"ok": True}


# ── 配置管理 ──────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return _get_cfg()


@app.post("/api/config")
async def update_config(data: dict):
    cfg = _get_cfg()
    cfg.update(data)
    config.save(cfg)
    return {"ok": True}


# ── 启动 ──────────────────────────────────────────────

def open_browser(port):
    """延迟打开浏览器。"""
    import threading
    def _open():
        time.sleep(1.5)
        webbrowser.open("http://localhost:%d" % port)
    threading.Thread(target=_open, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    PORT = 8642
    open_browser(PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
