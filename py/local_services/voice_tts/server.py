# -*- coding: utf-8 -*-
"""CosyVoice TTS Web 服务 — FastAPI 主入口。

局域网内通过浏览器访问，提供语音合成功能。
前端 HTML/JS/CSS 由本服务直接托管。

启动：python server.py   或双击 start.bat
访问：http://<本机IP>:8020
"""
import asyncio
import json
import os
import socket
import time
import webbrowser

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core import config, task_store, tts_engine
from core.merge_engine import MergeEngine, scan_media_dir
from core.task_engine import TaskEngine, resolve_output_path, migrate_outputs_to_subdirs

# ── 初始化 ──────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="CosyVoice TTS Web")
engine = TaskEngine()
merge_engine = MergeEngine()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── 启动钩子 ────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_event_loop()
    engine.set_loop(loop)
    merge_engine.set_loop(loop)
    changed = task_store.mark_interrupted()
    if changed:
        print("[startup] 标记 %d 个任务为 interrupted: %s" % (
            len(changed), ", ".join(t.get("name", t.get("id", "?")) for t in changed)))
    try:
        mig = migrate_outputs_to_subdirs()
        if mig.get("moved") or mig.get("tasks"):
            print("[startup] 成品归位：%d 个任务、移动 %d 个文件到任务子目录%s" % (
                mig.get("tasks", 0), mig.get("moved", 0),
                ("，%d 个文件缺失" % mig["missing"]) if mig.get("missing") else ""))
    except Exception as e:
        print("[startup] 成品归位失败（已跳过）: %s" % e)
    n = engine.restore_queue()
    if n:
        print("[startup] 恢复 %d 个排队任务到队列（需手动开始或等当前任务完成后自动执行）" % n)


def _get_cfg():
    return config.load()


# ── 首页 ──────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── 配置 API ──────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    cfg = _get_cfg()
    return {
        "config": cfg,
        "spk_options": config.SPK_OPTIONS,
        "style_options": config.STYLE_OPTIONS,
        "speed_options": config.SPEED_OPTIONS,
        "has_pydub": tts_engine.HAS_PYDUB,
        "has_ffmpeg": tts_engine.shutil.which("ffmpeg") is not None,
    }


@app.post("/api/config")
async def update_config(data: dict):
    cfg = _get_cfg()
    allowed_keys = set(config.DEFAULTS.keys())
    for k, v in data.items():
        if k in allowed_keys:
            cfg[k] = v
    config.save(cfg)
    return {"ok": True}


# ── 参考音频 API ──────────────────────────────────────

@app.get("/api/prompt_audios")
async def list_prompt_audios():
    cfg = _get_cfg()
    return {"audios": tts_engine.scan_prompt_audios(cfg.get("tts_dir", ""))}


# ── 当前活动任务 API ──────────────────────────────────

@app.post("/api/task/start")
async def start_task(data: dict):
    if merge_engine.busy():
        raise HTTPException(409, "合并任务正在运行，请等待完成或停止后再生成")
    text = data.get("text", "")
    task_name = data.get("task_name", "")
    params = {k: v for k, v in data.items() if k not in ("text", "task_name")}
    ok, task_id, err, queued = engine.start(text, params, task_name)
    if not ok:
        raise HTTPException(409, err)
    return {"ok": True, "task_id": task_id, "total": engine.total, "queued": queued}


@app.get("/api/task/status")
async def task_status():
    return engine.get_status()


@app.get("/api/task/queue")
async def task_queue():
    return {"queue": engine.get_queue()}


@app.post("/api/task/stop")
async def stop_task():
    return {"ok": engine.stop()}


@app.post("/api/task/pause")
async def pause_task():
    return {"ok": engine.pause()}


@app.post("/api/task/resume")
async def resume_task():
    return {"ok": engine.resume()}


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
                    # 队列还有后续任务时不断开，让前端能继续收到 auto_start
                    if event.get("type") == "queue_done":
                        break
                    if event.get("type") in ("complete", "error", "cancelled") and engine.queue_empty():
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


# ── 任务列表 API ──────────────────────────────────────

@app.get("/api/tasks")
async def list_tasks():
    """列出所有历史任务（含进行中/中断/完成）。"""
    tasks = task_store.load_all()
    summary = []
    for t in tasks:
        summary.append({
            "id": t.get("id"),
            "name": t.get("name", ""),
            "status": t.get("status", "unknown"),
            "total": t.get("total", 0),
            "completed": len(t.get("completed_segments") or []),
            "created_at": t.get("created_at", ""),
            "updated_at": t.get("updated_at", ""),
            "text_preview": (t.get("text") or "")[:60],
            "output_count": len(t.get("output_files") or []),
            "error": t.get("error", ""),
        })
    return {"tasks": summary, "active_task_id": engine.task_id, "active_status": engine.status}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    t = task_store.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


@app.post("/api/tasks/{task_id}/resume")
async def resume_task_by_id(task_id: str):
    ok, err = engine.resume_task(task_id)
    if not ok:
        raise HTTPException(409, err)
    return {"ok": True, "task_id": task_id, "total": engine.total}


@app.post("/api/tasks/{task_id}/clean_temp")
async def clean_task_temp(task_id: str):
    """清理指定任务的中间文件（不删除成品）。"""
    t = task_store.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    removed = TaskEngine.cleanup_task_files(t, clean_temp=True, clean_output=False)
    return {"ok": True, "removed": removed}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str,
                     clean_temp: bool = Query(False),
                     clean_output: bool = Query(False)):
    """删除任务记录，并按选项清理磁盘文件。"""
    t = task_store.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.get("status") in ("running", "paused", "stopping"):
        raise HTTPException(409, "任务正在活动，请先停止后再删除")
    removed = engine.cleanup_task_files(t, clean_temp, clean_output)
    task_store.delete(task_id)
    return {"ok": True, "removed": removed}


# ── 合并任务 API ────────────────────────────────

@app.post("/api/merge/preview")
async def merge_preview(data: dict):
    names = data.get("files") or []
    target = int(data.get("target_duration") or 20)
    return merge_engine.preview(names, target)


@app.post("/api/merge/start")
async def merge_start(data: dict):
    if engine._busy():
        raise HTTPException(409, "语音生成任务正在运行，请先停止后再合并")
    names = data.get("files") or []
    test = bool(data.get("test"))
    confirm = bool(data.get("confirm"))
    ok, err, need_confirm = merge_engine.start(
        names, data, test=test,
        source_name=data.get("source_name", ""),
        confirm=confirm)
    if need_confirm:
        return {"ok": False, "need_confirm": True,
                "message": "输出目录已存在，是否继续使用？"}
    if not ok:
        raise HTTPException(409, err)
    return {"ok": True, "total": merge_engine.total}


@app.post("/api/merge/stop")
async def merge_stop():
    return {"ok": merge_engine.stop()}


@app.get("/api/merge/status")
async def merge_status():
    return merge_engine.get_status()


@app.get("/api/merge/output_dir")
async def merge_output_dir():
    """返回合并输出的实际目录（根目录/标题）及已输出文件。"""
    return merge_engine.get_output_dir()


@app.post("/api/system/open_dir")
async def open_dir(data: dict):
    """在文件管理器中打开目录（仅允许已存在的目录）。"""
    path = (data.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "路径为空")
    if not os.path.isdir(path):
        raise HTTPException(404, "目录不存在: %s" % path)
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        raise HTTPException(500, "打开目录失败: %s" % e)
    return {"ok": True, "path": path}


@app.get("/api/merge/progress")
async def merge_progress():
    """SSE 端点：实时推送合并进度。"""
    queue, loop = merge_engine.subscribe()

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
            merge_engine.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 媒体目录扫描（BGM/图片选择） ────────────────────

@app.get("/api/media_files")
async def list_media_files(kind: str = Query("audio")):
    cfg = _get_cfg()
    if kind == "image":
        d = cfg.get("image_dir", "")
        files = scan_media_dir(d, images=True)
    else:
        d = cfg.get("bgm_dir", "")
        files = scan_media_dir(d, images=False)
    return {"dir": d, "files": files}


@app.get("/api/image_preview")
async def image_preview(path: str = Query(...)):
    """按绝对路径返回图片文件，供前端弹窗预览缩略图。"""
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "图片不存在: %s" % path)
    ext = os.path.splitext(path)[1].lower()
    media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png", ".gif": "image/gif",
                 ".webp": "image/webp", ".bmp": "image/bmp"}
    return FileResponse(path, media_type=media_map.get(ext, "application/octet-stream"))


# ── 测试生成 ──────────────────────────────────────────

@app.post("/api/test")
async def test_generate(data: dict):
    result = engine.test_generate(data)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "测试失败"))
    return result


# ── 音频文件 API ──────────────────────────────────────

@app.get("/api/audio/list")
async def list_audio(limit: int = 200):
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    files = []
    if os.path.isdir(output_dir):
        for root, dirs, fnames in os.walk(output_dir):
            dirs[:] = [d for d in dirs if d != "_temp"]   # 跳过中间产物
            for f in fnames:
                ext = os.path.splitext(f)[1].lower()
                if ext not in (".wav", ".mp3", ".flac", ".ogg", ".m4a"):
                    continue
                fp = os.path.join(root, f)
                try:
                    stat = os.stat(fp)
                except OSError:
                    continue
                rel = os.path.relpath(fp, output_dir).replace("\\", "/")
                rel_dir = os.path.relpath(root, output_dir).replace("\\", "/")
                files.append({
                    "name": rel,          # 相对路径（含任务子目录），唯一标识
                    "base": f,            # 纯文件名，用于展示
                    "dir": "" if rel_dir == "." else rel_dir,
                    "size": stat.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                })
        files.sort(key=lambda x: x["name"], reverse=True)
    total = len(files)
    # limit<=0 表示不限制（合并页需要完整列表，否则任务成品会被截断而漏选）
    if limit and limit > 0:
        files = files[:limit]
    return {"files": files, "total": total, "limit": limit}


@app.get("/api/audio/play")
async def play_audio(file: str = Query(...)):
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    fp = resolve_output_path(output_dir, file)
    if not fp or not os.path.isfile(fp):
        raise HTTPException(404, "音频文件不存在")
    ext = os.path.splitext(fp)[1].lower()
    media_map = {".wav": "audio/wav", ".mp3": "audio/mpeg",
                 ".flac": "audio/flac", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}
    return FileResponse(fp, media_type=media_map.get(ext, "audio/wav"),
                        headers={"Accept-Ranges": "bytes"})


@app.get("/api/audio/download")
async def download_audio(file: str = Query(...)):
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    fp = resolve_output_path(output_dir, file)
    if not fp or not os.path.isfile(fp):
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(fp, filename=os.path.basename(fp),
                        headers={"Content-Disposition": "attachment"})


@app.post("/api/audio/delete")
async def delete_audio(data: dict):
    filename = data.get("filename", "")
    if not filename:
        raise HTTPException(400, "文件名不能为空")
    cfg = _get_cfg()
    output_dir = cfg.get("output_dir", "")
    fp = resolve_output_path(output_dir, filename)
    if not fp or not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    os.remove(fp)
    return {"ok": True}


# ── 启动 ──────────────────────────────────────────────

def open_browser(port):
    import threading
    def _open():
        time.sleep(1.5)
        webbrowser.open("http://localhost:%d" % port)
    threading.Thread(target=_open, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    PORT = 8020
    print("=" * 56)
    print("  CosyVoice TTS Web 服务已启动")
    print(f"  本机访问:   http://127.0.0.1:{PORT}")
    try:
        host = socket.gethostbyname(socket.gethostname())
        print(f"  局域网访问: http://{host}:{PORT}")
    except Exception:
        pass
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)
    # 仅在非 Hub 托管模式下自动打开浏览器（避免远程启动时弹本地浏览器）
    if not os.environ.get("HUB_MANAGED"):
        open_browser(PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
