# -*- coding: utf-8 -*-
"""音频标签编辑 Web 服务（FastAPI）

迁移自 MP3信息编辑.pyw：单文件精修 / 多文件精修 / 批量处理 / JSON 清单套用 / 随机头像 / 清理备份。
引擎按格式适配器分层（MP3 / M4A / APE / FLAC / WMA）。本机原地编辑磁盘文件，
路径手动填写；进度通过 GET /api/task 轮询。
"""
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import engine, formats                     # noqa: E402
from core.config import (load_config, save_config, DEFAULT_CONFIG,  # noqa: E402
                         TUTORIAL, logger, CONFIG_PATH)
from core.tasks import (TaskManager, run_batch, run_fine,  # noqa: E402
                        run_manifest)

try:
    import mutagen
    MUTAGEN_VER = mutagen.version_string
except Exception:
    MUTAGEN_VER = None

try:
    from PIL import Image                          # noqa: F401
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

app = FastAPI(title="音频标签编辑")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
tm = TaskManager()


# ================== 基础 ==================

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/ping")
async def ping():
    return {"ok": True, "service": "audio_tag_editor",
            "mutagen": MUTAGEN_VER, "have_zhconv": engine.HAVE_ZHCONV,
            "have_pil": HAVE_PIL, "supported_exts": list(formats.SUPPORTED_EXTS)}


@app.get("/api/config")
async def get_config():
    return load_config()


@app.post("/api/config")
async def update_config(body: dict):
    cfg = load_config()
    for k in DEFAULT_CONFIG:
        if k in body:
            cfg[k] = body[k]
    save_config(cfg)
    return {"ok": True, "config": cfg}


@app.get("/api/tutorial")
async def tutorial():
    return {"text": TUTORIAL}


# ================== 文件列表 / 单文件 ==================

@app.get("/api/files")
async def list_files(dir: str = Query("")):
    d = Path(dir.strip())
    if not dir.strip() or not d.is_dir():
        return {"ok": False, "exists": False, "count": 0, "files": [],
                "message": "目录不存在或未填写"}
    files = engine.list_audio_files(d)
    rows = []
    for p in files:
        info = engine.read_info(p)
        rows.append({"name": p.name, "path": str(p),
                     "title": info["title"], "artist": info["artist"]})
    return {"ok": True, "exists": True, "count": len(rows), "files": rows}


def _img_meta(frame):
    if not frame:
        return None
    return {"mime": frame["mime"], "size": len(frame["data"])}


@app.get("/api/file")
async def get_file(path: str = Query(...)):
    p = Path(path)
    if not p.is_file():
        raise HTTPException(400, "文件不存在：%s" % path)
    try:
        info = engine.read_info(p)
    except formats.UnsupportedFormat as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "name": p.name, "path": str(p),
            "title": info["title"], "artist": info["artist"], "album": info["album"],
            "date": info["date"], "comment": info["comment"], "track": info["track"],
            "cover": _img_meta(info["cover"]), "bg": _img_meta(info["bg"]),
            "supports_bg": formats.get_adapter(path).supports_bg}


def _embedded_bytes(path, kind):
    p = Path(path)
    if not p.is_file():
        raise HTTPException(400, "文件不存在：%s" % path)
    if kind not in ("cover", "bg"):
        raise HTTPException(400, "kind 必须是 cover 或 bg")
    info = engine.read_info(p)
    frame = info[kind]
    if not frame:
        raise HTTPException(404, "该文件没有%s图" % ("封面" if kind == "cover" else "背景"))
    return p, frame


@app.get("/api/preview")
async def preview(path: str = Query(...), kind: str = Query("cover")):
    _p, frame = _embedded_bytes(path, kind)
    return Response(content=frame["data"], media_type=frame["mime"])


@app.get("/api/export")
async def export(path: str = Query(...), kind: str = Query("cover")):
    p, frame = _embedded_bytes(path, kind)
    ext = ".png" if frame["mime"] == "image/png" else ".jpg"
    fname = "%s_%s%s" % (p.stem, kind, ext)
    # 中文文件名须用 RFC 5987 编码，HTTP 头仅允许 latin-1
    disp = 'attachment; filename="audio_%s%s"; filename*=UTF-8\'\'%s' % (kind, ext, quote(fname))
    return Response(content=frame["data"], media_type=frame["mime"],
                    headers={"Content-Disposition": disp})


@app.get("/api/img")
async def disk_image(path: str = Query(...)):
    """预览磁盘上的图片文件（批量封面路径 / 随机头像推荐）"""
    p = Path(path)
    if not p.is_file() or p.suffix.lower() not in engine.IMAGE_EXTS:
        raise HTTPException(400, "图片文件不存在或格式不支持：%s" % path)
    return FileResponse(str(p))


@app.get("/api/avatar/random")
async def avatar_random(dir: str = Query("")):
    pick = engine.pick_random_image(dir.strip())
    if pick is None:
        return {"path": None, "name": None}
    return {"path": str(pick), "name": pick.name}


def _op_from_action(action, image_path):
    """界面图片动作 -> 引擎 op：keep=None / delete=("delete",) / set=读盘"""
    if action == "delete":
        return ("delete",)
    if action == "set":
        ip = Path((image_path or "").strip())
        if not ip.is_file():
            raise HTTPException(400, "图片文件不存在：%s" % (image_path or "（未填写）"))
        data = ip.read_bytes()
        return ("data", data, engine.sniff_image_mime(data))
    return None      # keep


@app.post("/api/file/save")
async def save_file(body: dict):
    path = (body.get("path") or "").strip()
    p = Path(path)
    if not p.is_file():
        raise HTTPException(400, "文件不存在：%s" % path)
    meta = {k: (body.get(k) or "").strip()
            for k in ("title", "artist", "album", "date", "comment", "track")}
    try:
        cover_op = _op_from_action(body.get("cover_action", "keep"), body.get("cover_path"))
        bg_op = _op_from_action(body.get("bg_action", "keep"), body.get("bg_path"))
        rename_title = meta["title"] if body.get("rename") else None
        final, notes = engine.apply_edits(p, meta, cover_op, bg_op,
                                          rename_title=rename_title)
    except formats.UnsupportedFormat as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, engine._short_err(e))
    logger.info("单文件保存成功: %s", final)
    return {"ok": True, "final_path": str(final), "name": final.name, "notes": notes}


# ================== 多文件精修列表 ==================

@app.get("/api/fine/list")
async def fine_list(dir: str = Query(""), t2s: bool = Query(True),
                    filter_words: str = Query("")):
    d = Path(dir.strip())
    if not dir.strip() or not d.is_dir():
        return {"ok": False, "count": 0, "rows": [], "message": "目录不存在或未填写"}
    files = engine.list_audio_files(d)
    rows = []
    for p in files:
        cleaned = engine.clean_title_from_filename(p.stem, t2s, filter_words)
        rows.append({"name": p.name, "path": str(p),
                     "title": cleaned or p.stem, "fallback": not cleaned})
    return {"ok": True, "count": len(rows), "rows": rows,
            "have_zhconv": engine.HAVE_ZHCONV}


# ================== 任务（批量 / 精修） ==================

def _merged_cfg(body):
    cfg = load_config()
    for k in DEFAULT_CONFIG:
        if k in body:
            cfg[k] = body[k]
    return cfg


@app.post("/api/batch/start")
async def batch_start(body: dict):
    cfg = _merged_cfg(body)
    d = Path(cfg["input_dir"])
    if not cfg["input_dir"] or not d.is_dir():
        raise HTTPException(400, "音频目录不存在，请先在“文件”页填写。")
    verr = engine.validate_images(cfg)
    if verr:
        raise HTTPException(400, "%s：%s" % (verr[0], verr[1]))
    save_config(cfg)
    try:
        tm.start(run_batch, "batch", cfg)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.post("/api/fine/start")
async def fine_start(body: dict):
    cfg = _merged_cfg(body.get("config", {}))
    d = Path(cfg["input_dir"])
    if not cfg["input_dir"] or not d.is_dir():
        raise HTTPException(400, "音频目录不存在，请先在“文件”页填写。")
    raw_items = body.get("items", [])
    items, skipped = [], []
    for it in raw_items:
        title = (it.get("title") or "").strip()
        path = (it.get("path") or "").strip()
        if not path:
            continue
        if not title:
            skipped.append(Path(path).name)
            continue
        items.append((path, title))
    if not items:
        raise HTTPException(400, "没有可处理的行：请勾选并填写标题。")
    verr = engine.validate_images(cfg, "fine")
    if verr:
        raise HTTPException(400, "%s：%s" % (verr[0], verr[1]))
    save_config(cfg)
    try:
        tm.start(run_fine, "fine", cfg, items)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "skipped": skipped}


# ================== JSON 歌曲清单 ==================

def _manifest_entries_or_400(body):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "清单内容为空：请粘贴 JSON 或选择 JSON 文件。")
    try:
        return engine.parse_manifest_text(text)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _um_entry_names(entries, um_indices):
    """未匹配条目 -> 展示名（file 优先，其次标题/歌名，兼无则序号）"""
    names = []
    for i in um_indices:
        e = entries[i]
        names.append(str(e.get("file") or e.get("name")
                       or engine._entry_field(e, "title", "标题", "歌名")
                       or "第%d项" % (i + 1)))
    return names


@app.post("/api/manifest/preview")
async def manifest_preview(body: dict):
    entries = _manifest_entries_or_400(body)
    dir_path = (body.get("dir") or "").strip() or load_config()["input_dir"]
    d = Path(dir_path)
    if not dir_path or not d.is_dir():
        raise HTTPException(400, "音频目录不存在：%s" % (dir_path or "（未填写）"))
    files = engine.list_audio_files(d)
    cfg = load_config()
    pairs, um_files, um_entries = engine.match_manifest(
        files, entries, cfg.get("fine_t2s", True), cfg.get("clean_filter_words", ""))
    rows = [{"file": p.name, "path": str(p),
             "title": engine._entry_field(e, "title", "标题", "歌名"),
             "artist": engine._entry_field(e, "artist", "作者", "歌手"),
             "album": engine._entry_field(e, "album", "专辑"),
             "weak": weak} for p, e, weak in pairs]
    return {"ok": True, "dir": str(d), "total_files": len(files),
            "total_entries": len(entries), "matched": len(pairs),
            "weak": sum(1 for r in rows if r["weak"]),
            "unmatched_files": um_files,
            "unmatched_entries": _um_entry_names(entries, um_entries),
            "rows": rows[:200]}


@app.post("/api/manifest/start")
async def manifest_start(body: dict):
    entries = _manifest_entries_or_400(body)
    cfg = _merged_cfg(body.get("config", {}))
    d = Path(cfg["input_dir"])
    if not cfg["input_dir"] or not d.is_dir():
        raise HTTPException(400, "音频目录不存在，请先在“文件”页填写。")
    files = engine.list_audio_files(d)
    pairs, um_files, um_entries = engine.match_manifest(
        files, entries, cfg.get("fine_t2s", True), cfg.get("clean_filter_words", ""))
    if not pairs:
        raise HTTPException(400, "没有匹配到任何文件（清单 %d 项 / 目录 %d 个音频），\n"
                                 "请先用“预览匹配”检查文件名。" % (len(entries), len(files)))
    save_config(cfg)
    try:
        tm.start(run_manifest, "manifest", cfg, pairs, bool(body.get("rename", True)))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "matched": len(pairs),
            "unmatched_files": um_files, "unmatched_entries": len(um_entries)}


@app.get("/api/task")
async def task_status():
    st = dict(tm.status)
    st["running"] = tm.is_running()
    return st


@app.post("/api/task/stop")
async def task_stop():
    tm.stop()
    return {"ok": True}


# ================== 备份清理 ==================

@app.get("/api/backup")
async def backup_info(dir: str = Query("")):
    bak = Path(dir.strip()) / engine.BACKUP_SUBDIR
    if not dir.strip() or not bak.is_dir():
        return {"exists": False, "count": 0, "path": str(bak)}
    count = sum(1 for p in bak.rglob("*") if p.is_file())
    return {"exists": True, "count": count, "path": str(bak)}


@app.post("/api/cleanup")
async def cleanup(body: dict):
    d = (body.get("dir") or "").strip()
    if not d or not Path(d).is_dir():
        raise HTTPException(400, "请先填写有效的音频目录。")
    try:
        count, path = engine.cleanup_backups(d)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, engine._short_err(e))
    logger.info("清理备份目录: %s (%d 个文件)", path, count)
    return {"ok": True, "count": count, "path": path}


# ================== 启动入口 ==================

if __name__ == "__main__":
    cfg = load_config()
    port = cfg.get("port", 8804)
    print("=" * 50)
    print("  音频标签编辑 Web 服务已启动")
    print("  本机访问:   http://127.0.0.1:%d" % port)
    print("  配置文件:   %s" % CONFIG_PATH)
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=port)