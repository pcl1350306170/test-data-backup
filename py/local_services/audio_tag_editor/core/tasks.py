# -*- coding: utf-8 -*-
"""任务运行层：单活动任务（批量/精修），后台线程执行，状态供前端轮询。

迁移自旧 GUI 的 queue + 线程模型：工作线程只写状态字典，不碰任何界面；
前端通过 GET /api/task 轮询 logs/progress/state。
"""
import threading
import time
from pathlib import Path

from . import engine
from .config import logger


class TaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.status = self._idle()

    @staticmethod
    def _idle():
        return {"state": "idle", "mode": None, "idx": 0, "total": 0,
                "logs": [], "done": 0, "failed": 0, "elapsed": 0.0,
                "dir": "", "message": ""}

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, target, mode, *args):
        """启动任务；已有任务在跑则抛 RuntimeError。target(tm, *args)"""
        with self._lock:
            if self.is_running():
                raise RuntimeError("已有任务正在运行，请等待完成或先停止。")
            self.status = self._idle()
            self.status["state"] = "running"
            self.status["mode"] = mode
            self._stop.clear()
            self._thread = threading.Thread(
                target=target, args=(self, *args), daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self.log("[停止] 已请求停止，当前文件处理完成后结束...")

    def stopped(self):
        return self._stop.is_set()

    # ---- 工作线程调用 ----
    def log(self, s):
        self.status["logs"].append(s)

    def progress(self, idx, total):
        self.status["idx"] = idx
        self.status["total"] = total

    def finish(self, state, **fields):
        self.status.update(fields)
        self.status["state"] = state


def _parse_start(raw):
    """起始序号解析：前导零决定补零宽度（与音频合并工具一致）"""
    raw = raw or "1"
    try:
        start = int(raw)
        if start < 0:
            start, raw = 1, "1"
    except ValueError:
        start, raw = 1, "1"
    width = max(1, len(raw))
    return start, width, raw


def run_batch(tm, cfg):
    """批量主流程：扫描 -> 逐项写标签（备份+原子替换） -> 汇总失败清单"""
    try:
        d = Path(cfg["input_dir"])
        files = engine.list_audio_files(d)
        total = len(files)
        if total == 0:
            tm.finish("empty", message="目录下没有受支持的音频文件:\n%s" % d)
            return

        start, width, raw = _parse_start(cfg["batch_start_num"])
        prefix = cfg["batch_title_prefix"]
        base_meta = engine.build_common_meta(cfg)
        cover_pool, bg_pool, cover_op, bg_op = engine.prepare_image_ops(cfg)

        tm.log("=" * 60)
        tm.log("批量目录: %s（%d 个音频）" % (d, total))
        tm.log("标题前缀: %s | 起始序号: %s | 作者: %s | 专辑: %s | 日期: %s | 备注: %s" % (
            prefix or "（不改）", raw, cfg["batch_artist"] or "（不改）",
            cfg["batch_album"] or "（不改）", cfg["batch_date"] or "（不改）",
            cfg["batch_comment"] or "（不改）"))
        tm.log("封面: %s | 背景图: %s | 同步重命名: %s" % (
            ("随机（头像 %d 张）" % len(cover_pool)) if cover_pool else (cfg["batch_cover_path"] or "（不改）"),
            ("随机（头像 %d 张）" % len(bg_pool)) if bg_pool else (cfg["batch_bg_image_path"] or "（不改）"),
            "开" if cfg["sync_rename"] else "关"))
        tm.log("=" * 60)

        done = failed = 0
        failed_list = []
        start_ts = time.time()
        for idx, path in enumerate(files, start=1):
            if tm.stopped():
                tm.finish("stopped", message="已在第 %d/%d 个文件后停止" % (idx - 1, total),
                          done=done, failed=failed, dir=str(d))
                return
            tm.progress(idx, total)
            meta = dict(base_meta)
            new_title = engine.batch_title_for(prefix, start, width, idx)
            if new_title:
                meta["title"] = new_title
            meta["track"] = "%d/%d" % (idx, total)
            try:
                final, notes = engine.apply_edits(
                    path, meta,
                    engine.random_image_op(cover_pool, cover_op),
                    engine.random_image_op(bg_pool, bg_op),
                    rename_title=new_title if cfg["sync_rename"] else None)
                done += 1
                tm.log("[%d/%d] 完成: %s%s" % (
                    idx, total, final.name,
                    ("  (%s)" % "；".join(notes)) if notes else ""))
                logger.info("批量编辑完成: %s", final)
            except Exception as e:
                failed += 1
                brief = engine._short_err(e)
                failed_list.append((path.name, brief))
                tm.log("      [警告] 失败已跳过: %s\n             原因: %s" % (path.name, brief))
                logger.error("批量编辑失败 %s: %s", path.name, brief)

        elapsed = time.time() - start_ts
        for note in engine.write_fail_list(d, failed_list):
            tm.log(note)
        tm.finish("done", done=done, failed=failed, elapsed=elapsed, dir=str(d))
    except Exception as e:
        tm.finish("error", message="任务异常：%s" % e)
        logger.exception("批量标签编辑异常")


def run_fine(tm, cfg, items):
    """多文件精修主流程：逐行标题 + 通用字段 -> 写标签（备份+原子替换）"""
    try:
        d = Path(cfg["input_dir"])
        total = len(items)
        base_meta = engine.build_common_meta(cfg, "fine")
        cover_pool, bg_pool, cover_op, bg_op = engine.prepare_image_ops(cfg, "fine")

        tm.log("=" * 60)
        tm.log("多文件精修: %s（%d 个文件）" % (d, total))
        tm.log("作者: %s | 专辑: %s | 日期: %s | 备注: %s" % (
            cfg["fine_artist"] or "（不改）", cfg["fine_album"] or "（不改）",
            cfg["fine_date"] or "（不改）", cfg["fine_comment"] or "（不改）"))
        tm.log("封面: %s | 背景图: %s | 按标题重命名: %s" % (
            ("随机（头像 %d 张）" % len(cover_pool)) if cover_pool else "（不改）",
            ("随机（头像 %d 张）" % len(bg_pool)) if bg_pool else "（不改）",
            "开" if cfg["fine_rename"] else "关"))
        tm.log("=" * 60)

        done = failed = 0
        failed_list = []
        start_ts = time.time()
        for idx, (path, title) in enumerate(items, start=1):
            if tm.stopped():
                tm.finish("stopped", message="已在第 %d/%d 个文件后停止" % (idx - 1, total),
                          done=done, failed=failed, dir=str(d))
                return
            tm.progress(idx, total)
            meta = dict(base_meta)
            meta["title"] = title
            meta["track"] = "%d/%d" % (idx, total)
            try:
                final, notes = engine.apply_edits(
                    Path(path), meta,
                    engine.random_image_op(cover_pool, cover_op),
                    engine.random_image_op(bg_pool, bg_op),
                    rename_title=title if cfg["fine_rename"] else None)
                done += 1
                tm.log("[%d/%d] 完成: %s%s" % (
                    idx, total, final.name,
                    ("  (%s)" % "；".join(notes)) if notes else ""))
                logger.info("精修编辑完成: %s", final)
            except Exception as e:
                failed += 1
                brief = engine._short_err(e)
                failed_list.append((Path(path).name, brief))
                tm.log("      [警告] 失败已跳过: %s\n             原因: %s" % (Path(path).name, brief))
                logger.error("精修编辑失败 %s: %s", Path(path).name, brief)

        elapsed = time.time() - start_ts
        for note in engine.write_fail_list(d, failed_list):
            tm.log(note)
        tm.finish("done", done=done, failed=failed, elapsed=elapsed, dir=str(d))
    except Exception as e:
        tm.finish("error", message="任务异常：%s" % e)
        logger.exception("多文件精修异常")