# -*- coding: utf-8 -*-
"""打包服务共用 FastAPI 路由工厂。

路由对齐本地服务大厅约定（/api/ping 探活、/api/config 白名单读写、SSE 进度推送）。
阻塞型接口（目录扫描、git 分支遍历、svn 提交）一律用同步 def 声明，
交给 FastAPI 线程池执行，不挡事件循环——否则 Hub 的健康检查会超时误判 unresponsive。
"""
import asyncio
import json
import os
import socket
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import browse, node_env
from .engine import PackEngine
from .store import HISTORY_LIMIT, Store

SSE_TIMEOUT = 30


def create_app(profile, service_dir):
    service_dir = Path(service_dir)
    static_dir = service_dir / "static"
    store = Store(service_dir, profile.DEFAULT_CONFIG, profile.LEGACY_CONFIG_PATHS,
                  allowed_keys=set(profile.DEFAULT_CONFIG.keys()),
                  reset_keys=getattr(profile, "MIGRATE_RESET_KEYS", ()))
    engine = PackEngine(profile, store)

    app = FastAPI(title=profile.TITLE)
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── 生命周期 ──────────────────────────────────────

    @app.on_event("startup")
    def _startup():
        engine.set_loop(asyncio.get_running_loop())
        cfg = store.load()
        if store.migrated_from:
            engine.log("📦 已从旧配置迁移：%s" % store.migrated_from)
        roots = [r for r in profile.roots(cfg) if r]
        for root in roots:
            engine.log("ℹ️ 可浏览根目录: %s%s" % (root, "" if Path(root).is_dir() else "（不存在）"))

    # ── 基础 ──────────────────────────────────────────

    @app.get("/")
    def index():
        page = static_dir / "index.html"
        if not page.is_file():
            raise HTTPException(404, "前端页面缺失: %s" % page)
        return FileResponse(str(page))

    @app.get("/api/ping")
    def ping():
        return {"ok": True, "service": profile.ID, "title": profile.TITLE,
                "status": engine.status, "ts": time.time()}

    # ── 配置 ──────────────────────────────────────────

    @app.get("/api/config")
    def get_config():
        cfg = store.load()
        return {"config": cfg, "meta": profile.meta(cfg),
                "legacy_migrated": store.migrated_from}

    @app.post("/api/config")
    def update_config(data: dict):
        result = store.update(data or {})
        return {"ok": True, **result}

    # ── 环境探测 ──────────────────────────────────────

    @app.get("/api/node/versions")
    def node_versions():
        return node_env.list_versions()

    # ── 搜索与目录浏览 ────────────────────────────────

    @app.post("/api/search")
    def search(data: dict):
        keyword = (data or {}).get("keyword", "").strip()
        if not keyword:
            raise HTTPException(400, "请输入关键字")
        cfg = store.load()
        result = profile.search(keyword, cfg, data)
        if not result.get("svn_dirs") and not result.get("projects"):
            result["notice"] = ("未匹配到目录。请检查关键字「%s」，或确认基础目录：%s"
                                % (keyword, "、".join(r for r in profile.roots(cfg) if r)))
        return result

    @app.post("/api/prefill")
    def prefill(data: dict):
        """点选列表项后的回填：输出目录 / 订单信息 / 基础包 / 版本。"""
        cfg = store.load()
        try:
            for key in ("svn_dir", "project_dir", "output_dir"):
                value = (data or {}).get(key) or ""
                if value:
                    browse.check_root(str(Path(value).parent if Path(value).is_file() else value),
                                      profile.roots(cfg))
        except browse.PathDenied as e:
            raise HTTPException(400, str(e))
        return profile.prefill(cfg, data or {})

    @app.get("/api/browse")
    def browse_dir(path: str = Query(...), exts: str = Query("")):
        cfg = store.load()
        ext_list = tuple(e for e in exts.split(",") if e) or None
        try:
            return browse.list_dir(path, profile.roots(cfg), exts=ext_list)
        except browse.PathDenied as e:
            raise HTTPException(400, str(e))

    @app.get("/api/output/files")
    def output_files(path: str = Query(...)):
        """列出成品目录里的文件（服务为本机专用，不开放下载，只呈现结果）。"""
        cfg = store.load()
        try:
            listing = browse.list_dir(path, profile.roots(cfg),
                                      exts=profile.PACKAGE_EXTS or None,
                                      include_dirs=False)
        except browse.PathDenied as e:
            raise HTTPException(400, str(e))
        return {"path": listing["path"], "files": listing["files"],
                "total": len(listing["files"])}

    # ── 打包任务 ──────────────────────────────────────

    @app.post("/api/package/start")
    def start_package(data: dict):
        ok, message, errors = engine.start(data or {})
        if not ok:
            # 校验不通过 → 400；已有任务在跑 → 409
            raise HTTPException(400 if errors else 409,
                                {"message": message, "errors": errors})
        return {"ok": True, "task_id": engine.task_id, "status": engine.status}

    @app.get("/api/package/status")
    def package_status():
        return engine.get_status()

    @app.post("/api/package/stop")
    def stop_package():
        if not engine.stop():
            raise HTTPException(409, "当前没有在进行的打包任务")
        return {"ok": True, "status": engine.status}

    @app.get("/api/package/progress")
    async def package_progress():
        """SSE：先补发日志快照，再实时推送；30s 无事件发心跳。"""
        queue = engine.subscribe()

        async def stream():
            try:
                init = {"type": "init", "status": engine.get_status()}
                yield "data: %s\n\n" % json.dumps(init, ensure_ascii=False)
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=SSE_TIMEOUT)
                    except asyncio.TimeoutError:
                        yield 'data: %s\n\n' % json.dumps({"type": "heartbeat"})
                        continue
                    yield "data: %s\n\n" % json.dumps(event, ensure_ascii=False)
                    if event.get("type") == "finish":
                        break
            except asyncio.CancelledError:
                pass
            finally:
                engine.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # ── SVN 单独提交 ──────────────────────────────────

    @app.post("/api/svn/commit")
    def svn_commit(data: dict):
        if engine.busy():
            raise HTTPException(409, "打包任务进行中，请完成后再提交")
        result = engine.last_result or {}
        package = (data or {}).get("path") or result.get("package_path") or ""
        work_dir = (data or {}).get("work_dir") or result.get("svn_work_dir") or ""
        if not package:
            raise HTTPException(400, "没有可提交的成品，请先完成一次打包")
        cfg = store.load()
        try:
            parent = str(Path(package).parent)
            browse.check_root(parent, profile.roots(cfg))
        except browse.PathDenied as e:
            raise HTTPException(400, str(e))
        if not Path(package).is_file():
            raise HTTPException(404, "成品文件不存在：%s" % package)

        ctx = engine.adhoc_context()
        ok = profile.commit(ctx, package, work_dir)
        return {"ok": ok, "path": package, "status": engine.last_result.get("svn_committed", ok)}

    # ── 历史记录 ──────────────────────────────────────

    @app.get("/api/history")
    def history():
        records = store.history()
        return {"records": records, "total": len(records), "limit": HISTORY_LIMIT}

    @app.delete("/api/history")
    def delete_history(index: int = Query(...)):
        result = store.delete_history(index)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "删除失败"))
        return result

    @app.post("/api/history/clear")
    def clear_history():
        return {"ok": True, "cleared": store.clear_history()}

    app.state.engine = engine
    app.state.store = store
    app.state.profile = profile
    return app


def service_port(store, default_port):
    cfg = store.load()
    try:
        return int(cfg.get("port", default_port))
    except (TypeError, ValueError):
        return default_port


def run_server(app, profile, service_dir, default_port):
    """启动入口：打印本机/局域网地址，非 Hub 托管时自动开浏览器。"""
    import uvicorn

    store = app.state.store
    port = service_port(store, default_port)
    print("=" * 56)
    print("  %s Web 服务已启动" % profile.TITLE)
    print("  本机访问:   http://127.0.0.1:%d" % port)
    try:
        host = socket.gethostbyname(socket.gethostname())
        print("  局域网访问: http://%s:%d" % (host, port))
    except Exception:
        pass
    if store.migrated_from:
        print("  旧配置迁移自: %s" % store.migrated_from)
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)

    if not os.environ.get("HUB_MANAGED"):
        import threading
        import webbrowser

        def _open():
            time.sleep(1.5)
            webbrowser.open("http://127.0.0.1:%d" % port)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
