# -*- coding: utf-8 -*-
"""视频合并 Web 服务 - 目录下 mp4 按命名顺序拼接为一个视频"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from core import engine

# ── 路径与常量 ────────────────────────────────────────

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"

# ── 配置管理 ─────────────────────────────────────────

DEFAULT_CONFIG = {
    "port": 8805,
    "recent_dirs": [],
}

def load_config():
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    merged = DEFAULT_CONFIG.copy()
    merged.update(cfg)
    return merged

def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)

def _push_recent_dir(directory: str):
    cfg = load_config()
    recent = [d for d in cfg.get("recent_dirs", []) if d != directory]
    recent.insert(0, directory)
    cfg["recent_dirs"] = recent[:10]
    save_config(cfg)

# ── FastAPI 应用 ─────────────────────────────────────

app = FastAPI(title="视频合并")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/ping")
async def ping():
    return {"ok": True, "service": "video_merger"}

@app.get("/api/config")
async def get_config():
    return load_config()

@app.post("/api/config")
async def update_config(cfg: dict):
    current = load_config()
    current.update(cfg)
    save_config(current)
    return {"ok": True}

@app.post("/api/scan")
async def scan(body: dict):
    directory = (body.get("directory") or "").strip().strip('"')
    if not directory:
        raise HTTPException(400, "请填写目录路径")
    result = engine.scan_directory(directory)
    if not result["ok"]:
        return result
    _push_recent_dir(directory)
    return result

@app.post("/api/merge")
async def merge(body: dict):
    files = body.get("files") or []          # 绝对路径列表，顺序即拼接顺序
    mode = body.get("mode") or "auto"        # auto / copy / reencode
    directory = (body.get("directory") or "").strip()
    output_name = (body.get("output_name") or "").strip()

    if len(files) < 2:
        raise HTTPException(400, "至少选择 2 个视频文件")
    if mode not in ("auto", "copy", "reencode"):
        raise HTTPException(400, f"未知合并模式: {mode}")

    paths = [Path(p) for p in files]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise HTTPException(400, f"文件不存在: {'、'.join(missing[:3])}")

    items = [engine.probe_video(p) for p in paths]
    bad = [it["name"] for it in items if it.get("error")]
    if bad:
        raise HTTPException(400, f"探测失败: {'、'.join(bad)}")

    analysis = engine.analyze_compatibility(items)
    if mode == "copy" and not analysis["compatible"]:
        raise HTTPException(400, "视频参数不一致，无法无损直拷：" + "；".join(analysis["reasons"]))

    base_dir = directory or str(paths[0].parent)
    output = engine.make_output_path(base_dir, output_name)
    if output in paths:
        raise HTTPException(400, "输出文件名不能与源文件相同")

    task = engine.start_merge(paths, output, mode, items, analysis)
    return {
        "ok": True,
        "task_id": task.id,
        "actual_mode": task.mode,
        "output": task.output,
        "analysis": analysis,
    }

@app.get("/api/merge/status/{task_id}")
async def merge_status(task_id: str):
    task = engine.TASKS.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在或已过期")
    return task.to_dict()

@app.post("/api/reveal")
async def reveal(body: dict):
    path = (body.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "缺少 path")
    if not engine.reveal_in_explorer(path):
        raise HTTPException(404, "文件不存在")
    return {"ok": True}

# ── 启动入口 ─────────────────────────────────────────

if __name__ == "__main__":
    cfg = load_config()
    port = cfg.get("port", 8805)

    print("=" * 50)
    print("  视频合并 Web 服务已启动")
    print(f"  本机访问:   http://127.0.0.1:{port}")
    print(f"  ffmpeg:     {engine.FFMPEG}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=port)
