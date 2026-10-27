# -*- coding: utf-8 -*-
"""任务引擎：管理 TTS 生成任务，支持 SSE 实时进度推送、多任务持久化、断点续跑。

设计要点：
- 同一时刻只运行一个活动任务；其他任务保留在 tasks.json 中待恢复
- worker 输出到 `output/_temp/{task_id}/{idx}.wav`（原始）
- 后处理（语速/淡出/格式）后 copy 到 `output/{base}-{idx:03d}.{ext}`（成品）
- 每完成一段就 upsert 到 tasks.json，重启后可跳过已完成段
- 通过 loop.call_soon_threadsafe(q.put_nowait, event) 投递事件到 SSE
"""
import asyncio
import os
import shutil
import threading
import time
import traceback
import uuid
from typing import Optional

from . import task_store, tts_engine
from .config import load as load_config


class TaskEngine:
    """任务队列引擎：支持追加任务，按顺序依次执行。"""

    def __init__(self):
        self.status = "idle"  # idle|running|paused|stopping|done|error|cancelled|interrupted
        self.task_id: Optional[str] = None
        self.task_name: str = ""
        self.total = 0
        self.completed = 0
        self.logs: list = []
        self.files: list = []
        self.error = ""
        self.text = ""
        self.segments: list = []
        self.base_prefix = ""
        self.completed_segments: set = set()  # 已完成的段号集合
        self.cfg: dict = {}
        self.created_at = ""

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set = set()
        self._queue: list = []  # 待执行的任务队列

    # ── SSE 订阅管理 ──────────────────────────────────

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def subscribe(self):
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q, self._loop

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    def _emit(self, event: dict):
        if not self._loop:
            return
        event.setdefault("task_id", self.task_id)
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass

    # ── 任务控制 ──────────────────────────────────────

    def _busy(self) -> bool:
        return self.status in ("running", "paused", "stopping")

    def start(self, text: str, params: dict, task_name: str = "") -> tuple:
        """启动新任务或加入队列。返回 (ok, task_id, error_msg, queued)。"""
        text = (text or "").strip()
        if not text:
            return False, None, "文本不能为空", False

        cfg = load_config()
        for key in ("spk", "style", "speed", "format", "seg_len",
                    "fade", "fade_ms", "tail_ms", "prompt_audio", "prompt_text", "prefix"):
            if key in params and params[key] is not None:
                cfg[key] = params[key]

        ok, err = self._validate_env(cfg)
        if not ok:
            return False, None, err, False

        segments = tts_engine.split_text(text, cfg.get("seg_len", 500))
        if not segments:
            return False, None, "文本切段后为空", False

        task_id = uuid.uuid4().hex[:12]
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = self._build_base(cfg, ts)
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 默认任务名：文本前 20 字
        if not task_name:
            task_name = (text[:20] + "…") if len(text) > 20 else text

        task = {
            "id": task_id,
            "name": task_name,
            "text": text,
            "segments": segments,
            "params": {k: cfg.get(k) for k in (
                "spk", "style", "speed", "format", "seg_len", "fade",
                "fade_ms", "tail_ms", "prompt_audio", "prompt_text", "prefix",
                "model_dir", "repo_dir", "conda_python", "worker_script", "output_dir")},
            "base_prefix": base,
            "status": "pending" if self._busy() else "running",
            "total": len(segments),
            "completed_segments": [],
            "output_files": [],
            "created_at": created_at,
            "error": "",
        }
        task_store.upsert(task)

        # 如果当前有任务在运行，加入队列
        if self._busy():
            self._queue.append(task)
            self._emit({"type": "queued", "task_id": task_id, "task_name": task_name,
                        "queue_size": len(self._queue)})
            return True, task_id, "", True

        # 否则立即执行
        self._bind_running(task, segments, cfg, base)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True, task_id, "", False

    def resume_task(self, task_id: str) -> tuple:
        """从磁盘任务恢复执行（跳过已完成段）。返回 (ok, error_msg)。"""
        if self._busy():
            return False, "已有任务正在运行，请先暂停/停止当前任务"

        task = task_store.get(task_id)
        if not task:
            return False, "任务不存在"
        if task.get("status") == "done":
            return False, "任务已完成，无需继续"
        if task.get("status") in ("running", "paused", "stopping"):
            return False, "任务当前正在活动，请使用暂停/继续按钮"

        cfg = load_config()
        # 用保存的 params 覆盖运行环境参数（保证一致性）
        for k, v in (task.get("params") or {}).items():
            if v is not None:
                cfg[k] = v

        ok, err = self._validate_env(cfg)
        if not ok:
            return False, err

        segments = task.get("segments") or []
        if not segments:
            return False, "任务段列表为空，无法恢复"

        base = task.get("base_prefix") or self._build_base(cfg, time.strftime("%Y%m%d_%H%M%S"))
        done = set(task.get("completed_segments") or [])
        task["status"] = "running"
        task["base_prefix"] = base
        task_store.upsert(task)

        self._bind_running(task, segments, cfg, base, initial_completed=done)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True, ""

    def stop(self) -> bool:
        if self.status not in ("running", "paused"):
            return False
        self._stop_event.set()
        self._pause_event.clear()
        self.status = "stopping"
        return True

    def pause(self) -> bool:
        if self.status != "running":
            return False
        self._pause_event.set()
        self.status = "paused"
        self._persist_status("paused")
        self._emit({"type": "paused"})
        return True

    def resume(self) -> bool:
        if self.status != "paused":
            return False
        self._pause_event.clear()
        self.status = "running"
        self._persist_status("running")
        self._emit({"type": "resumed"})
        return True

    def get_status(self) -> dict:
        return {
            "status": self.status,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "total": self.total,
            "completed": self.completed,
            "progress": round(self.completed / self.total * 100, 1) if self.total > 0 else 0,
            "logs": self.logs[-100:],
            "files": self.files,
            "error": self.error,
            "created_at": self.created_at,
            "queue_size": len(self._queue),
        }

    def get_queue(self) -> list:
        """返回队列中的待执行任务列表。"""
        return [{"id": t["id"], "name": t.get("name", ""),
                 "total": t.get("total", 0), "text": t.get("text", "")[:50]}
                for t in self._queue]

    # ── 内部辅助 ──────────────────────────────────────

    def _validate_env(self, cfg: dict) -> tuple:
        if not os.path.isdir(cfg.get("model_dir", "")):
            return False, f"模型目录不存在: {cfg.get('model_dir')}"
        if not os.path.isfile(cfg.get("conda_python", "")):
            return False, f"conda python 不存在: {cfg.get('conda_python')}"
        if not os.path.isfile(cfg.get("worker_script", "")):
            return False, f"Worker 脚本不存在: {cfg.get('worker_script')}"
        return True, ""

    def _build_base(self, cfg: dict, ts: str) -> str:
        prompt_audio = (cfg.get("prompt_audio") or "").strip()
        if prompt_audio:
            spk_name = tts_engine.safe_name(
                os.path.splitext(os.path.basename(prompt_audio))[0])
        else:
            spk_name = tts_engine.safe_name(cfg.get("spk") or "中文女")
        style_name = tts_engine.safe_name(cfg.get("style") or "")
        prefix = tts_engine.safe_name(cfg.get("prefix") or "")
        base_parts = [p for p in (prefix or spk_name, style_name, ts) if p]
        return "_".join(base_parts)

    def _bind_running(self, task, segments, cfg, base, initial_completed=None):
        self.task_id = task["id"]
        self.task_name = task.get("name", "")
        self.text = task.get("text", "")
        self.segments = segments
        self.cfg = cfg
        self.base_prefix = base
        self.status = "running"
        self.total = len(segments)
        self.completed_segments = set(initial_completed or task.get("completed_segments") or [])
        self.completed = len(self.completed_segments)
        self.files = list(task.get("output_files") or [])
        self.logs = []
        self.error = ""
        self.created_at = task.get("created_at", "")
        self._stop_event.clear()
        self._pause_event.clear()

    def _persist_snapshot(self, status: str = None, error: str = ""):
        if not self.task_id:
            return
        task = task_store.get(self.task_id) or {}
        task.update({
            "id": self.task_id,
            "name": self.task_name,
            "text": self.text,
            "segments": self.segments,
            "params": {k: self.cfg.get(k) for k in (
                "spk", "style", "speed", "format", "seg_len", "fade",
                "fade_ms", "tail_ms", "prompt_audio", "prompt_text", "prefix",
                "model_dir", "repo_dir", "conda_python", "worker_script", "output_dir")},
            "base_prefix": self.base_prefix,
            "status": status or self.status,
            "total": self.total,
            "completed_segments": sorted(self.completed_segments),
            "output_files": self.files,
            "error": error or self.error,
        })
        task.setdefault("created_at", self.created_at or time.strftime("%Y-%m-%d %H:%M:%S"))
        task_store.upsert(task)

    def _persist_status(self, status: str):
        task = task_store.get(self.task_id) if self.task_id else None
        if task:
            task["status"] = status
            task_store.upsert(task)

    def _segment_final_name(self, idx: int, ext: str) -> str:
        if self.total == 1:
            return f"{self.base_prefix}.{ext}"
        return f"{self.base_prefix}-{idx:03d}.{ext}"

    def _segment_temp_path(self, idx: int) -> str:
        tmp_dir = os.path.join(self.cfg.get("output_dir", ""), "_temp", self.task_id)
        os.makedirs(tmp_dir, exist_ok=True)
        return os.path.join(tmp_dir, f"{idx:03d}.wav")

    def _cleanup_temp_dir(self) -> bool:
        """删除本任务的中间产物目录 output/_temp/{task_id}/。"""
        tmp_dir = os.path.join(self.cfg.get("output_dir", ""), "_temp", self.task_id)
        if os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
                return True
            except Exception:
                return False
        return False

    def _remove_output_files(self) -> int:
        """删除本任务已生成的成品文件，返回删除数量。"""
        output_dir = self.cfg.get("output_dir", "")
        n = 0
        for name in self.files:
            fp = os.path.join(output_dir, os.path.basename(name))
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                    n += 1
                except Exception:
                    pass
        return n

    # ── 工作线程 ──────────────────────────────────────

    def _log(self, msg: str):
        self.logs.append(msg)
        if len(self.logs) > 500:
            self.logs = self.logs[-300:]
        self._emit({"type": "log", "message": msg})

    def _run(self):
        try:
            cfg = self.cfg
            segments = self.segments
            speed = float(cfg.get("speed") or 1.0)
            fmt = (cfg.get("format") or "wav").lower()
            output_dir = cfg.get("output_dir", "")
            os.makedirs(output_dir, exist_ok=True)

            self._emit({"type": "started", "total": self.total,
                        "resumed": len(self.completed_segments)})
            if self.completed_segments:
                self._log(f"继续任务：共 {self.total} 段，已完成 {len(self.completed_segments)} 段")
            else:
                self._log(f"开始生成：共 {self.total} 段，格式={fmt.upper()}")

            for idx, seg_text in enumerate(segments, start=1):
                # 停止
                if self._stop_event.is_set():
                    self._finalize_cancelled(idx - 1)
                    return
                # 暂停
                while self._pause_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.3)
                if self._stop_event.is_set():
                    self._finalize_cancelled(idx - 1)
                    return

                # 已完成则跳过（断点续跑）
                if idx in self.completed_segments:
                    self._emit({"type": "progress", "current": idx, "total": self.total,
                                "percent": round(idx / self.total * 100, 1),
                                "skipped": True})
                    continue

                final_name = self._segment_final_name(idx, fmt if fmt == "mp3" else "wav")
                final_path = os.path.join(output_dir, final_name)
                raw_wav = self._segment_temp_path(idx)

                self._log(f"[{idx}/{self.total}] 生成中...")
                self._emit({"type": "progress", "current": idx, "total": self.total,
                            "percent": round((idx - 1) / self.total * 100, 1)})

                # 1) worker 输出（若原始 wav 已存在则复用，节省时间）
                if not os.path.isfile(raw_wav):
                    try:
                        tts_engine.call_worker(seg_text, raw_wav, cfg)
                    except Exception as e:
                        self._log(f"[{idx}/{self.total}] 失败: {e}")
                        self._emit({"type": "segment_error", "index": idx, "error": str(e)})
                        continue
                else:
                    self._log(f"[{idx}/{self.total}] 复用原始 wav")

                # 2) 后处理（在临时目录上做，避免污染成品）
                if abs(speed - 1.0) >= 0.01:
                    tts_engine.apply_speed(raw_wav, speed)
                if cfg.get("fade", True) and tts_engine.HAS_PYDUB:
                    fade_ms = int(cfg.get("fade_ms", 0) or 0)
                    tail_ms = int(cfg.get("tail_ms", 900) or 900)
                    tts_engine.apply_fade_out(raw_wav, fade_ms, tail_ms)

                # 3) 落到成品目录（wav 用 move，mp3 转换后 wav 留在 _temp）
                produced_name = final_name
                try:
                    if fmt == "mp3":
                        mp3_final = os.path.join(output_dir, self._segment_final_name(idx, "mp3"))
                        if tts_engine.wav_to_mp3(raw_wav, mp3_final):
                            produced_name = os.path.basename(mp3_final)
                        else:
                            wav_final = os.path.join(output_dir, self._segment_final_name(idx, "wav"))
                            shutil.copyfile(raw_wav, wav_final)
                            produced_name = os.path.basename(wav_final)
                            self._log(f"[{idx}/{self.total}] MP3 失败，保留 WAV")
                    else:
                        shutil.copyfile(raw_wav, final_path)
                        produced_name = os.path.basename(final_path)
                except Exception as e:
                    self._log(f"[{idx}/{self.total}] 输出失败: {e}")
                    self._emit({"type": "segment_error", "index": idx, "error": str(e)})
                    continue

                self.completed_segments.add(idx)
                self.completed = idx
                if produced_name not in self.files:
                    self.files.append(produced_name)
                self._log(f"[{idx}/{self.total}] 完成: {produced_name}")
                self._persist_snapshot()
                self._emit({"type": "progress", "current": idx, "total": self.total,
                            "percent": round(idx / self.total * 100, 1),
                            "file": produced_name})

            # 全部完成
            self.status = "done"
            self._persist_snapshot(status="done")
            # 自动清理中间文件，只保留成品音频（取消/失败时保留以便断点复用）
            if self._cleanup_temp_dir():
                self._log(f"已清理中间文件目录 _temp/{self.task_id}")
            self._log(f"全部完成，共生成 {len(self.files)} 个文件")
            self._emit({"type": "complete", "files": self.files, "total": self.total})
            # 启动队列中的下一个任务
            self._start_next()

        except Exception as e:
            self.status = "error"
            self.error = str(e)
            self._log(f"异常: {e}")
            self._persist_snapshot(status="error", error=str(e))
            self._emit({"type": "error", "message": str(e)})
            traceback.print_exc()
            # 出错也启动下一个
            self._start_next()

    def _finalize_cancelled(self, done_idx: int):
        self.status = "cancelled"
        self._log(f"已在第 {done_idx}/{self.total} 段后停止")
        # 已取消的任务不再续跑：直接删除成品 + 清理中间文件
        removed = self._remove_output_files()
        if removed:
            self._log(f"已删除 {removed} 个成品文件")
        if self._cleanup_temp_dir():
            self._log(f"已清理中间文件目录 _temp/{self.task_id}")
        self.files = []
        self.completed_segments = set()
        self._persist_snapshot(status="cancelled")
        self._emit({"type": "cancelled"})
        # 取消后也启动下一个
        self._start_next()

    def _start_next(self):
        """从队列中取出下一个任务执行。"""
        if not self._queue:
            self.status = "idle"
            return
        next_task = self._queue.pop(0)
        cfg = load_config()
        for k, v in (next_task.get("params") or {}).items():
            if v is not None:
                cfg[k] = v
        segments = next_task.get("segments") or []
        base = next_task.get("base_prefix") or self._build_base(cfg, time.strftime("%Y%m%d_%H%M%S"))
        next_task["status"] = "running"
        task_store.upsert(next_task)
        self._bind_running(next_task, segments, cfg, base)
        self._log(f"自动启动队列任务: {self.task_name} ({self.task_id})")
        self._emit({"type": "auto_start", "task_id": self.task_id, "task_name": self.task_name})
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ── 测试生成（同步，不入任务列表） ────────────────

    def test_generate(self, params: dict) -> dict:
        import random
        TEST_SENTENCES = [
            "清晨的阳光洒在窗台上，鸟儿在枝头欢快地歌唱，新的一天开始了。",
            "春天的田野里，油菜花金灿灿的一片，微风吹过，带来阵阵清香。",
            "夜幕降临，繁星点点，月亮悄悄爬上了树梢，一切都安静了下来。",
            "小溪潺潺流过石桥，鱼儿在水中自由自在地游来游去。",
            "秋天的果园里，红彤彤的苹果挂满枝头，空气中弥漫着丰收的喜悦。",
        ]
        if self._busy():
            return {"ok": False, "error": "有任务正在运行，测试已跳过"}

        cfg = load_config()
        for key in ("spk", "style", "speed", "format", "prompt_audio", "prompt_text"):
            if key in params and params[key] is not None:
                cfg[key] = params[key]

        ok, err = self._validate_env(cfg)
        if not ok:
            return {"ok": False, "error": err}

        test_text = random.choice(TEST_SENTENCES)
        output_dir = cfg.get("output_dir", "")
        os.makedirs(output_dir, exist_ok=True)
        fmt = (cfg.get("format") or "wav").lower()
        ts = time.strftime("%Y%m%d_%H%M%S")
        spk_name = self._build_base(cfg, ts)

        out_name = f"测试_{spk_name}.wav"
        out_path = os.path.join(output_dir, out_name)

        try:
            tts_engine.call_worker(test_text, out_path, cfg)
            speed = float(cfg.get("speed") or 1.0)
            if abs(speed - 1.0) >= 0.01:
                tts_engine.apply_speed(out_path, speed)
            if fmt == "mp3":
                mp3_name = f"测试_{spk_name}.mp3"
                mp3_path = os.path.join(output_dir, mp3_name)
                if tts_engine.wav_to_mp3(out_path, mp3_path):
                    os.remove(out_path)
                    out_name = mp3_name
            return {"ok": True, "filename": out_name, "text": test_text}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── 任务清理 ──────────────────────────────────────

    @staticmethod
    def cleanup_task_files(task: dict, clean_temp: bool, clean_output: bool) -> dict:
        """按选项清理任务的中间/成品文件。"""
        removed = {"temp": 0, "output": 0}
        output_dir = (task.get("params") or {}).get("output_dir") or load_config().get("output_dir", "")
        if clean_temp and task.get("id"):
            tmp_dir = os.path.join(output_dir, "_temp", task["id"])
            if os.path.isdir(tmp_dir):
                try:
                    shutil.rmtree(tmp_dir)
                    removed["temp"] += 1
                except Exception:
                    pass
        if clean_output:
            for name in task.get("output_files") or []:
                fp = os.path.join(output_dir, os.path.basename(name))
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        removed["output"] += 1
                    except Exception:
                        pass
        return removed
