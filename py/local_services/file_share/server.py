# -*- coding: utf-8 -*-
"""file_share - 局域网共享文件服务

平铺共享目录 + 浏览器上传/下载，流式直写磁盘（大文件不进内存）。
纳入本地服务大厅 Hub 管理，端口 8800。
"""
import asyncio
import json
import os
import shutil
import socket
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── 路径与常量 ────────────────────────────────────────

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "port": 8800,
    "shared_dir": r"D:\FILES\共享",
}

UPLOAD_CHUNK = 1024 * 1024  # 1MB 流式缓冲


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


CFG = load_config()


def shared_root():
    root = Path(CFG["shared_dir"])
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
    return root


def safe_target(name):
    """把文件名解析为共享目录内的安全路径，禁止子目录/逃逸。"""
    name = (name or "").strip().strip("/\\")
    if not name or "/" in name or "\\" in name or ".." in name or ":" in name:
        raise HTTPException(400, "非法文件名: %s" % name)
    root = shared_root()
    p = (root / name).resolve()
    if p.parent != root.resolve():
        raise HTTPException(400, "路径越界")
    return p


def unique_path(root, name):
    """同名冲突：在扩展名前追加 _HHMMSS，再冲突继续加序号。"""
    stem, ext = os.path.splitext(name)
    candidate = root / name
    if not candidate.exists():
        return candidate
    for _ in range(100):
        new_name = "%s_%s%s" % (stem, time.strftime("%H%M%S"), ext)
        candidate = root / new_name
        if not candidate.exists():
            return candidate
        time.sleep(0.01)
    raise HTTPException(500, "同名文件过多，请重命名后上传")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ── 同步文件操作（跑在线程池里，不阻塞事件循环） ──────

def _list_files():
    root = shared_root()
    items = []
    for e in root.iterdir():
        if e.is_file() and not e.name.startswith(".") and not e.name.endswith(".part"):
            st = e.stat()
            items.append({
                "name": e.name,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {
        "shared_dir": str(root),
        "total_size": sum(i["size"] for i in items),
        "files": items,
    }


def _write_upload(filename, src, dst_part, dst_final):
    """流式落盘：先写 .part，完成后原子改名，避免半截文件被取到。"""
    try:
        with open(dst_part, "wb") as out:
            shutil.copyfileobj(src, out, length=UPLOAD_CHUNK)
        os.replace(dst_part, dst_final)
    finally:
        if dst_part.exists():
            try:
                dst_part.unlink()
            except OSError:
                pass


# ── FastAPI 应用 ──────────────────────────────────────

app = FastAPI(title="局域网共享文件")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/ping")
async def ping():
    return {"ok": True}


@app.get("/api/info")
async def info():
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _list_files)
    return {
        "shared_dir": data["shared_dir"],
        "total_size": data["total_size"],
        "file_count": len(data["files"]),
        "lan_ip": lan_ip(),
        "port": CFG["port"],
    }


@app.get("/api/files")
async def list_files():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _list_files)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), rename: str = Form("") ):
    name = (rename or "").strip() or os.path.basename(file.filename or "")
    target = safe_target(name)
    root = target.parent
    final = unique_path(root, target.name)
    part = Path(str(final) + ".part")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_upload, name, file.file, part, final)
    return {"ok": True, "name": final.name, "size": final.stat().st_size}


@app.get("/api/download")
async def download(name: str):
    p = safe_target(name)
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    # 中文名走 RFC 5987，filename 给 ASCII 兜底
    dispo = "attachment; filename*=UTF-8''%s" % quote(p.name)
    return FileResponse(str(p), media_type="application/octet-stream",
                        headers={"Content-Disposition": dispo})


@app.post("/api/delete")
async def delete(body: dict):
    p = safe_target(body.get("name", ""))
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    p.unlink()
    return {"ok": True}


@app.post("/api/rename")
async def rename(body: dict):
    src = safe_target(body.get("name", ""))
    dst = safe_target(body.get("new_name", ""))
    if not src.is_file():
        raise HTTPException(404, "文件不存在")
    if dst.exists():
        raise HTTPException(409, "目标名称已存在")
    src.rename(dst)
    return {"ok": True, "name": dst.name}


@app.get("/api/config")
async def get_config():
    return CFG


@app.post("/api/config")
async def update_config(body: dict):
    if "shared_dir" in body and body["shared_dir"].strip():
        new_dir = Path(body["shared_dir"].strip())
        if not new_dir.is_dir():
            raise HTTPException(400, "目录不存在或不可访问: %s" % new_dir)
        CFG["shared_dir"] = str(new_dir)
    save_config(CFG)
    return {"ok": True, "config": CFG}


# ── 启动入口 ──────────────────────────────────────────

if __name__ == "__main__":
    port = CFG.get("port", 8800)
    print("=" * 52)
    print("  局域网共享文件服务已启动")
    print("  本机访问:   http://127.0.0.1:%d" % port)
    print("  局域网访问: http://%s:%d" % (lan_ip(), port))
    print("  共享目录:   %s" % CFG["shared_dir"])
    print("=" * 52)
    uvicorn.run(app, host="0.0.0.0", port=port)
