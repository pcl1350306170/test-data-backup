# -*- coding: utf-8 -*-
"""任务引擎：后台线程执行播客生成流水线，通过事件队列上报进度。

状态机：idle → parsing → generating → merging → validating → done/failed/cancelled
"""
import asyncio
import json
import os
import re
import threading
import time

from . import config, voice_manager, script_parser, audio_generator, audio_merger


class TaskEngine:
    """单任务引擎，管理播客生成的完整生命周期。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()  # set=运行, clear=暂停
        self._pause_event.set()
        self._thread = None
        self._subscribers = set()
        self._sub_lock = threading.Lock()

        # 任务状态
        self.status = "idle"
        self.script_path = None
        self.output_name = None
        self.blocks = []
        self.block_states = {}  # idx → pending/generating/done/skipped/failed
        self.failed_blocks = []
        self.current_block_idx = None
        self.start_time = None
        self.end_time = None
        self.output_path = None
        self.duration_sec = None
        self.error_message = None
        self.paused = False

        # 任务配置（用于重试）
        self._task_config = {}

        # 批量队列：多个脚本按顺序逐个执行
        self._jobs = []
        self._job_index = 0
        self._total_jobs = 1
        self._failed_jobs = []
        self._last_output = None

    # ── 事件订阅 ──────────────────────────────────────────

    def subscribe(self):
        """创建新的进度订阅队列，返回 (queue, loop)。"""
        q = asyncio.Queue()
        loop = asyncio.get_event_loop()
        with self._sub_lock:
            self._subscribers.add((q, loop))
        return q, loop

    def unsubscribe(self, q):
        """移除订阅。"""
        with self._sub_lock:
            self._subscribers = {(sq, loop) for sq, loop in self._subscribers if sq is not q}

    def _emit(self, event):
        """向所有订阅者发送事件（线程安全）。"""
        with self._sub_lock:
            subs = list(self._subscribers)
        for q, loop in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass

    # ── 任务控制 ──────────────────────────────────────────

    def start(self, script_paths, bgm_path=None,
              bgm_volume=30, lufs=-16, gap_ms=400, output_name=""):
        """启动任务队列（单个脚本也走队列），多个脚本按顺序逐个执行。"""
        if self.status not in ("idle", "done", "failed", "cancelled"):
            return False, "已有任务正在运行"

        paths = [p for p in (script_paths if isinstance(script_paths, list)
                             else [script_paths]) if p]
        if not paths:
            return False, "未选择脚本"

        self._reset_state()
        self._jobs = [{"script_path": p, "output_name": ""} for p in paths]
        # 单任务且指定了输出名时沿用，否则每个任务取脚本自带书名
        if len(paths) == 1 and output_name:
            self._jobs[0]["output_name"] = output_name
        self._total_jobs = len(self._jobs)
        self._job_index = 0
        self._cancel_event.clear()
        self.start_time = time.time()

        # 将启动参数存入 _task_config，供后续 _parse_job / _do_merge 使用
        self._task_config = {
            "bgm_path": bgm_path,
            "bgm_volume": bgm_volume,
            "lufs": lufs,
            "gap_ms": gap_ms,
        }

        # 解析第一个脚本（失败时由队列线程顺延到下一个）
        self._parse_job(self._jobs[0])

        # 启动后台线程
        self._thread = threading.Thread(target=self._run_queue_worker, daemon=True)
        self._thread.start()
        return True, None

    def _queue_ctx(self):
        """当前队列上下文（仅多任务时返回，事件带此字段供前端区分批次进度）。"""
        if self._total_jobs > 1:
            return {"job": self._job_index + 1, "total": self._total_jobs,
                    "script": os.path.basename(self.script_path or "")}
        return None

    def _parse_job(self, job):
        """解析队列中的一个脚本并重置块状态；失败时发送带队列上下文的错误事件。"""
        self.script_path = job["script_path"]
        self._emit({"type": "status", "status": "parsing",
                    "message": "正在解析脚本...", "queue": self._queue_ctx()})
        try:
            voices = voice_manager.get_all()
            info, blocks, warnings = script_parser.parse_script(
                job["script_path"], set(voices.keys())
            )
            self.blocks = blocks
            self.block_states = {b["idx"]: "pending" for b in blocks}
            self.failed_blocks = []
            if not job["output_name"]:
                job["output_name"] = info.get("书名") or os.path.splitext(
                    os.path.basename(job["script_path"]))[0]
            self.output_name = job["output_name"]
            self._task_config = {
                "script_path": job["script_path"],
                "output_name": job["output_name"],
                "bgm_path": self._task_config.get("bgm_path"),
                "bgm_volume": self._task_config.get("bgm_volume", 30),
                "lufs": self._task_config.get("lufs", -16),
                "gap_ms": self._task_config.get("gap_ms", 400),
            }
            total_chars = sum(len(b["text"]) for b in blocks)
            self._emit({
                "type": "parsed",
                "total_blocks": len(blocks),
                "total_chars": total_chars,
                "estimated_sec": script_parser.estimate_duration(blocks),
                "warnings": warnings,
                "queue": self._queue_ctx(),
            })
            return True
        except Exception as e:
            self.status = "failed"
            self.error_message = str(e)
            self._emit({"type": "error",
                        "message": "脚本解析失败: %s" % str(e),
                        "script": os.path.basename(job["script_path"]),
                        "queue": self._queue_ctx(),
                        "more": len(self._jobs) > 1})
            return False

    def cancel(self):
        """停止当前任务并清空待执行队列。"""
        if self.status in ("generating", "merging", "parsing", "paused", "cancelling"):
            # 队列线程已结束（取消晚于完成）：按实际结果落定，避免状态卡在 cancelling
            if self._thread is not None and not self._thread.is_alive():
                self.status = "cancelled" if self._cancel_event.is_set() else self.status
                return True
            self._cancel_event.set()
            self._pause_event.set()  # 解除暂停阻塞，让线程能退出
            self.status = "cancelling"
            self.paused = False
            self._emit({"type": "status", "status": "cancelling",
                        "message": "正在停止...（剩余队列将清空）" if len(self._jobs) > 1
                        else "正在停止...",
                        "queue": self._queue_ctx()})
            return True
        return False

    def pause(self):
        """暂停：当前块生成完后暂停后续块。"""
        if self.status == "generating":
            self.paused = True
            self._pause_event.clear()
            self.status = "paused"
            self._emit({"type": "status", "status": "paused",
                        "message": "已暂停（当前块完成后停止）", "queue": self._queue_ctx()})
            return True
        return False

    def resume(self):
        """继续：恢复后续块的生成。"""
        if self.status == "paused":
            self.paused = False
            self.status = "generating"
            self._pause_event.set()
            self._emit({"type": "status", "status": "generating", "message": "继续生成...",
                        "queue": self._queue_ctx()})
            return True
        return False

    def retry_failed(self):
        """仅重新生成失败的块。"""
        if self.status not in ("done", "failed") or not self.failed_blocks:
            return False, "没有可重试的失败块"
        if self._jobs:
            return False, "队列中还有待执行任务，完成后可重试当前任务失败块"

        # 重置失败块状态
        for idx in self.failed_blocks:
            self.block_states[idx] = "pending"
        self.failed_blocks = []
        self.status = "generating"
        self._cancel_event.clear()
        self.start_time = time.time()

        self._thread = threading.Thread(target=self._retry_worker, daemon=True)
        self._thread.start()
        return True, None

    # ── 内部工作线程 ──────────────────────────────────────

    def _reset_state(self):
        self.blocks = []
        self.block_states = {}
        self.failed_blocks = []
        self.current_block_idx = None
        self.start_time = None
        self.end_time = None
        self.output_path = None
        self.duration_sec = None
        self.error_message = None
        self._failed_jobs = []
        self._last_output = None

    def _get_voice_params(self):
        """获取音色参数和 worker 参数。"""
        voices = voice_manager.get_all()
        cfg = config.load()
        params = {
            "conda_python": cfg["conda_python"],
            "model_dir": cfg["model_dir"],
            "worker_script": cfg["worker_script"],
            "repo_dir": cfg["repo_dir"],
        }
        return voices, params

    def _task_audio_dir(self):
        """当前任务的中间产物子目录：audio_dir/{输出名}，避免任务间互相污染。"""
        cfg = config.load()
        safe_name = re.sub(r'[\\/:*?"<>|\s]', "_", self._task_config.get("output_name")
                           or self.output_name or "default")[:60].strip("._") or "default"
        task_dir = os.path.join(cfg["audio_dir"], safe_name)
        os.makedirs(task_dir, exist_ok=True)
        return task_dir

    def _run_queue_worker(self):
        """后台线程：按顺序逐个执行队列中的脚本，完成或失败后进入下一个。"""
        while self._jobs:
            job = self._jobs[0]
            if self._cancel_event.is_set():
                break
            # 队首非当前任务（如解析失败后顺延）时重新解析
            if job["script_path"] != self.script_path and not self._parse_job(job):
                self._failed_jobs.append({
                    "script": os.path.basename(job["script_path"]),
                    "error": (self.error_message or "解析失败")[:80],
                })
                self._jobs.pop(0)
                self._job_index += 1
                continue
            try:
                self._do_generate()
            except Exception as e:
                self.status = "failed"
                self.error_message = str(e)
                self._emit({"type": "error", "message": "任务异常: %s" % str(e),
                            "queue": self._queue_ctx(),
                            "more": len(self._jobs) > 1})
            # 当前任务终态：done/failed 都继续下一个；取消则中止整批
            if self.status == "cancelled":
                break
            if self.status == "failed":
                self._failed_jobs.append({
                    "script": os.path.basename(job["script_path"]),
                    "error": (self.error_message or "失败")[:100],
                })
            self._jobs.pop(0)
            self._job_index += 1

        self.end_time = time.time()
        if self.status == "cancelled" or (self._cancel_event.is_set() and not self._jobs):
            self.status = "cancelled"
            self._emit({"type": "cancelled", "message": "任务已取消，剩余队列已清空",
                        "queue": None})
        elif self._failed_jobs:
            self.status = "failed"
            self.error_message = "%d/%d 个任务失败" % (
                len(self._failed_jobs), self._total_jobs)
            self._emit({"type": "error",
                        "message": "%d/%d 个任务失败：%s" % (
                            len(self._failed_jobs), self._total_jobs,
                            "；".join(f["script"] for f in self._failed_jobs)),
                        "failed_jobs": self._failed_jobs, "queue": None})
        else:
            self.status = "done"
            if self._total_jobs > 1:
                self._emit({"type": "complete", "queue": None, "batch": True,
                            "output": os.path.basename(self._last_output or ""),
                            "message": "全部 %d 个任务完成，最后一部: %s" % (
                                self._total_jobs,
                                os.path.basename(self._last_output or ""))})

    def _do_generate(self):
        audio_dir = self._task_audio_dir()

        voices, params = self._get_voice_params()

        # 回调函数
        def on_start(idx, voice, text):
            self.current_block_idx = idx
            self.block_states[idx] = "generating"
            self._emit({"type": "block_status", "idx": idx, "status": "generating",
                         "voice": voice, "text": text[:50]})

        def on_done(idx, wav_path):
            self.block_states[idx] = "done"
            dur = audio_merger.probe_duration(wav_path)
            self._emit({"type": "block_status", "idx": idx, "status": "done",
                         "duration_sec": round(dur, 1) if dur else None})
            self._emit_progress()

        def on_failed(idx, error):
            self.block_states[idx] = "failed"
            self._emit({"type": "block_status", "idx": idx, "status": "failed",
                         "error": error[:100]})

        # 逐块生成
        self.status = "generating"
        self._emit({"type": "status", "status": "generating",
                    "message": "开始生成音频...", "queue": self._queue_ctx()})

        for block in self.blocks:
            if self._cancel_event.is_set():
                break

            # 暂停检查：在块间等待（可被 resume 或 cancel 唤醒）
            while not self._pause_event.is_set():
                if self._cancel_event.is_set():
                    break
                self._pause_event.wait(timeout=1.0)
            if self._cancel_event.is_set():
                break

            idx = block["idx"]
            out_wav = os.path.join(audio_dir, "%03d.wav" % idx)

            # 断点续转
            if os.path.isfile(out_wav) and os.path.getsize(out_wav) > 0:
                self.block_states[idx] = "skipped"
                self._emit({"type": "block_status", "idx": idx, "status": "skipped"})
                self._emit_progress()
                continue

            voice_info = voices.get(block["voice"])
            if not voice_info:
                self.block_states[idx] = "failed"
                self.failed_blocks.append(idx)
                self._emit({"type": "block_status", "idx": idx, "status": "failed",
                             "error": "未知音色: %s" % block["voice"]})
                continue

            vi = (voice_info["audio"], voice_info["prompt_text"])
            result = audio_generator.generate_block(
                block, audio_dir, vi, params,
                on_start=on_start, on_done=on_done, on_failed=on_failed,
                check_cancel=lambda: self._cancel_event.is_set(),
            )
            if result is None and idx not in [b["idx"] for b in self.blocks
                                               if self.block_states.get(b["idx"]) == "done"]:
                if self.block_states.get(idx) == "failed":
                    self.failed_blocks.append(idx)

        # 检查取消
        if self._cancel_event.is_set():
            self.status = "cancelled"
            self._emit({"type": "status", "status": "cancelled",
                        "message": "任务已取消", "queue": self._queue_ctx()})
            return

        # 检查失败块
        self.failed_blocks = [idx for idx, s in self.block_states.items() if s == "failed"]
        if self.failed_blocks:
            self.status = "failed"
            self._emit({"type": "error",
                         "message": "%d 个块生成失败" % len(self.failed_blocks),
                         "failed_blocks": self.failed_blocks,
                         "queue": self._queue_ctx(), "more": len(self._jobs) > 1})
            return

        # 合并
        self._do_merge()

    def _retry_worker(self):
        """后台线程：仅重新生成失败块，然后合并。"""
        try:
            audio_dir = self._task_audio_dir()
            voices, params = self._get_voice_params()

            retry_blocks = [b for b in self.blocks
                            if self.block_states.get(b["idx"]) == "pending"]

            def on_start(idx, voice, text):
                self.current_block_idx = idx
                self.block_states[idx] = "generating"
                self._emit({"type": "block_status", "idx": idx, "status": "generating",
                             "voice": voice, "text": text[:50]})

            def on_done(idx, wav_path):
                self.block_states[idx] = "done"
                dur = audio_merger.probe_duration(wav_path)
                self._emit({"type": "block_status", "idx": idx, "status": "done",
                             "duration_sec": round(dur, 1) if dur else None})
                self._emit_progress()

            def on_failed(idx, error):
                self.block_states[idx] = "failed"
                self._emit({"type": "block_status", "idx": idx, "status": "failed",
                             "error": error[:100]})

            self._emit({"type": "status", "status": "generating",
                         "message": "重试 %d 个失败块..." % len(retry_blocks),
                        "queue": self._queue_ctx()})

            for block in retry_blocks:
                if self._cancel_event.is_set():
                    break
                # 暂停检查
                while not self._pause_event.is_set():
                    if self._cancel_event.is_set():
                        break
                    self._pause_event.wait(timeout=1.0)
                if self._cancel_event.is_set():
                    break
                voice_info = voices.get(block["voice"])
                if not voice_info:
                    self.block_states[block["idx"]] = "failed"
                    self.failed_blocks.append(block["idx"])
                    continue
                vi = (voice_info["audio"], voice_info["prompt_text"])
                result = audio_generator.generate_block(
                    block, audio_dir, vi, params,
                    on_start=on_start, on_done=on_done, on_failed=on_failed,
                    check_cancel=lambda: self._cancel_event.is_set(),
                    force=True,
                )
                if result is None:
                    self.failed_blocks.append(block["idx"])

            if self._cancel_event.is_set():
                self.status = "cancelled"
                self._emit({"type": "status", "status": "cancelled", "message": "已取消",
                            "queue": self._queue_ctx()})
                return

            self.failed_blocks = [idx for idx, s in self.block_states.items() if s == "failed"]
            if self.failed_blocks:
                self.status = "failed"
                self._emit({"type": "error",
                             "message": "%d 个块仍然失败" % len(self.failed_blocks),
                             "failed_blocks": self.failed_blocks,
                             "queue": self._queue_ctx(), "more": not self._jobs})
                return

            self._do_merge()
        except Exception as e:
            self.status = "failed"
            self.error_message = str(e)
            self._emit({"type": "error", "message": "重试异常: %s" % str(e),
                        "queue": self._queue_ctx(), "more": not self._jobs})
        finally:
            if self.status not in ("cancelled", "failed"):
                self.status = "done"
            self.end_time = time.time()

    def _do_merge(self):
        """合并步骤。"""
        self.status = "merging"
        self._emit({"type": "status", "status": "merging",
                    "message": "正在合并音频...", "queue": self._queue_ctx()})

        cfg = config.load()
        tc = self._task_config
        output_path = os.path.join(cfg["output_dir"], tc["output_name"] + ".mp3")

        try:
            def on_merge_progress(current, total, message):
                self._emit({"type": "merge_progress", "current": current,
                             "total": total, "message": message})

            result_path, dur = audio_merger.merge(
                self._task_audio_dir(), output_path,
                bgm_path=tc.get("bgm_path"),
                bgm_volume=tc.get("bgm_volume", 30),
                lufs=tc.get("lufs", -16),
                gap_ms=tc.get("gap_ms", 400),
                on_progress=on_merge_progress,
            )
            self.output_path = result_path
            self.duration_sec = dur
            self._last_output = result_path
            self.status = "validating"

            # 时长校验
            est_sec = script_parser.estimate_duration(self.blocks)
            diff_pct = abs(dur - est_sec) / est_sec * 100 if est_sec > 0 else 0
            warning = None
            if diff_pct > 10:
                warning = ("时长偏差 %.0f%%（实际 %.1f 分钟，预估 %.1f 分钟）"
                           % (diff_pct, dur / 60, est_sec / 60))

            self.status = "done"
            self._emit({
                "type": "complete",
                "output": os.path.basename(result_path),
                "duration_sec": round(dur, 1) if dur else None,
                "duration_min": round(dur / 60, 1) if dur else None,
                "warning": warning,
                "queue": self._queue_ctx(),
                "more": not (self._cancel_event.is_set() and not self._jobs) and len(self._jobs) > 1,
            })
        except Exception as e:
            self.status = "failed"
            self.error_message = "合并失败: %s" % str(e)
            self._emit({"type": "error", "message": self.error_message,
                        "queue": self._queue_ctx(), "more": len(self._jobs) > 1})

    def _emit_progress(self):
        """发送总进度事件。"""
        total = len(self.blocks)
        done = sum(1 for s in self.block_states.values() if s in ("done", "skipped"))
        failed = sum(1 for s in self.block_states.values() if s == "failed")
        elapsed = time.time() - self.start_time if self.start_time else 0
        eta = 0
        if done > 0 and done < total:
            avg = elapsed / done
            eta = avg * (total - done)

        self._emit({
            "type": "progress",
            "done": done,
            "failed": failed,
            "total": total,
            "percent": round(done / total * 100) if total > 0 else 0,
            "eta_sec": round(eta),
            "elapsed_sec": round(elapsed),
        })

    # ── 独立合并（更换 BGM） ─────────────────────────────────

    def remerge(self, audio_task, bgm_path=None, bgm_volume=30,
                lufs=-16, gap_ms=400, output_name=None):
        """独立合并：用已有音频块目录重新合并（可更换 BGM）。

        Args:
            audio_task: audio_dir 下的子目录名
            bgm_path: BGM 文件路径（可选）
            bgm_volume: BGM 音量 0-100
            lufs: 目标响度
            gap_ms: 块间静音毫秒
            output_name: 输出文件名（不含扩展名），默认沿用 audio_task
        """
        if self.status in ("generating", "merging", "parsing", "paused", "cancelling"):
            return False, "已有任务正在运行，请等待完成后再合并"

        cfg = config.load()
        input_dir = os.path.join(cfg["audio_dir"], audio_task)
        if not os.path.isdir(input_dir):
            return False, "音频目录不存在: %s" % audio_task

        # 检查目录中是否有 wav 文件
        import re as _re
        has_wav = any(_re.match(r"^\d+\.wav$", f, _re.IGNORECASE)
                      for f in os.listdir(input_dir))
        if not has_wav:
            return False, "目录中没有 001.wav…NNN.wav 格式的音频块"

        out_name = output_name or audio_task
        output_path = os.path.join(cfg["output_dir"], out_name + ".mp3")

        self._reset_state()
        self.status = "merging"
        self.output_name = out_name
        self.start_time = time.time()
        self._cancel_event.clear()
        self._pause_event.set()
        self._total_jobs = 1
        self._job_index = 0
        self._jobs = []

        self._emit({"type": "status", "status": "merging",
                    "message": "正在重新合并（BGM: %s）..." % (
                        os.path.basename(bgm_path) if bgm_path else "无"),
                    "remerge": True})

        self._thread = threading.Thread(
            target=self._remerge_worker,
            args=(input_dir, output_path, bgm_path, bgm_volume, lufs, gap_ms),
            daemon=True)
        self._thread.start()
        return True, None

    def _remerge_worker(self, input_dir, output_path, bgm_path, bgm_volume, lufs, gap_ms):
        """后台线程：执行独立合并。"""
        try:
            def on_progress(current, total, message):
                if self._cancel_event.is_set():
                    raise RuntimeError("用户取消")
                self._emit({"type": "merge_progress", "current": current,
                            "total": total, "message": message, "remerge": True})

            result_path, dur = audio_merger.merge(
                input_dir, output_path,
                bgm_path=bgm_path,
                bgm_volume=bgm_volume,
                lufs=lufs,
                gap_ms=gap_ms,
                on_progress=on_progress,
            )
            self.output_path = result_path
            self.duration_sec = dur
            self.status = "done"
            self._emit({
                "type": "complete",
                "output": os.path.basename(result_path),
                "duration_sec": round(dur, 1) if dur else None,
                "duration_min": round(dur / 60, 1) if dur else None,
                "remerge": True,
            })
        except RuntimeError as e:
            if "取消" in str(e):
                self.status = "cancelled"
                self._emit({"type": "cancelled", "message": "合并已取消", "remerge": True})
            else:
                self.status = "failed"
                self.error_message = "合并失败: %s" % str(e)
                self._emit({"type": "error", "message": self.error_message, "remerge": True})
        except Exception as e:
            self.status = "failed"
            self.error_message = "合并失败: %s" % str(e)
            self._emit({"type": "error", "message": self.error_message, "remerge": True})
        finally:
            self.end_time = time.time()

    # ── 状态查询 ──────────────────────────────────────────

    def get_status(self):
        """返回当前状态快照。"""
        return {
            "status": self.status,
            "script_path": self.script_path,
            "output_name": self.output_name,
            "total_jobs": self._total_jobs,
            "job_index": self._job_index,
            "pending_scripts": [os.path.basename(j["script_path"]) for j in self._jobs[1:]],
            "failed_jobs": list(self._failed_jobs),
            "total_blocks": len(self.blocks),
            "block_states": dict(self.block_states),
            "failed_blocks": list(self.failed_blocks),
            "current_block_idx": self.current_block_idx,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "output_path": self.output_path,
            "duration_sec": self.duration_sec,
            "error_message": self.error_message,
            "paused": self.paused,
        }
