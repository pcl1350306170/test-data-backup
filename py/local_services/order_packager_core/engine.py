# -*- coding: utf-8 -*-
"""打包任务引擎：后台线程跑构建，事件通过 SSE 广播给页面。

设计要点：
- 同一时刻只允许一个打包任务（构建会清空 dist、改 SVN 工作副本，并发必炸），忙时 start 返回 409
- 业务步骤放在 profile.run(params, ctx) 里，引擎只负责线程、日志、中止、状态、历史
- ctx.run_stream 边读子进程输出边推日志，替代 .pyw 里的 root.after + ScrolledText
- 中止用 taskkill /F /T 杀进程树：npm.cmd / bash 都会派生子进程
- 日志环形缓冲 2000 行，页面刷新后先取快照再接 SSE，不会丢日志
"""
import asyncio
import os
import subprocess
import threading
import time
import traceback
import uuid

from .util import NO_WINDOW, kill_tree

MAX_LOG_LINES = 2000


class Aborted(Exception):
    """任务被中止（用户点停止 / 服务退出）。"""


class RunContext:
    """传给 profile 的执行上下文：日志、阶段、中止检查、子进程调用、结果登记。"""

    def __init__(self, engine):
        self._engine = engine
        self.result = {}

    # ── 日志 / 阶段 ──────────────────────────────────

    def log(self, msg):
        self._engine.log(msg)

    def stage(self, name, index=0, total=0):
        self._engine._set_stage(name, index, total)

    # ── 中止 ─────────────────────────────────────────

    def stop_requested(self):
        return self._engine._stop_event.is_set()

    def check_stop(self):
        if self.stop_requested():
            raise Aborted("用户已停止任务")

    # ── 配置 / 结果 ──────────────────────────────────

    @property
    def cfg(self):
        return self._engine.store.load()

    def set_result(self, **kv):
        self.result.update(kv)
        self._engine.last_result.update(kv)
        self._engine._emit({"type": "result", "result": dict(self._engine.last_result)})

    # ── 子进程 ───────────────────────────────────────

    def run(self, argv, cwd=None, env=None, timeout=120, shell=None):
        """执行命令并等其结束，返回 (returncode, stdout, stderr)。"""
        proc = self._popen(argv, cwd=cwd, env=env, shell=shell, capture=True)
        try:
            out, err = proc.communicate(timeout=timeout)
            return proc.returncode, (out or "").strip(), (err or "").strip()
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid, self.log)
            return proc.returncode or 124, "", "命令超时(%ss)" % timeout

    def run_stream(self, argv, cwd=None, env=None, shell=None, label=""):
        """执行命令并实时把输出按行推给页面，返回退出码。

        Windows 下 npm.cmd / bash 脚本需要 shell=True（沿用 .pyw 的做法），
        非 Windows 直接执行 argv。
        """
        engine = self._engine
        if self.stop_requested():
            raise Aborted("用户已停止任务")
        self.log("▶ %s" % (label or " ".join(map(str, argv))))
        proc = self._popen(argv, cwd=cwd, env=env, shell=shell, capture=True)
        engine._proc = proc
        code = None
        try:
            for line in (proc.stdout or []):
                line = (line or "").rstrip()
                if line:
                    self.log("   " + line)
                if self.stop_requested():
                    self.log("🛑 收到停止请求，正在终止构建进程…")
                    kill_tree(proc.pid, self.log)
                    break
            proc.wait(timeout=30)
            code = proc.returncode
        except Exception as e:
            self.log("⚠️ 读取输出异常: %s" % e)
            try:
                proc.wait(timeout=30)
                code = proc.returncode
            except Exception:
                kill_tree(proc.pid, self.log)
                code = -1
        finally:
            engine._proc = None

        if self.stop_requested():
            raise Aborted("任务已停止")
        if code == 0:
            self.log("✅ 命令执行成功")
        else:
            self.log("❌ 命令执行失败，退出码 %s" % code)
        return code

    def _popen(self, argv, cwd=None, env=None, shell=None, capture=True):
        if shell is None:
            shell = os.name == "nt"
        return subprocess.Popen(
            argv, cwd=str(cwd) if cwd else None, env=env,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if capture else subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            shell=shell, creationflags=NO_WINDOW)


class PackEngine:
    def __init__(self, profile, store):
        self.profile = profile
        self.store = store

        self.status = "idle"      # idle|running|stopping|done|error|stopped
        self.task_id = ""
        self.started_at = ""
        self.finished_at = ""
        self.elapsed = 0
        self.error = ""
        self.params = {}
        self.stage = {"name": "", "index": 0, "total": 0}
        self.logs = []
        self.last_result = {}

        self._thread = None
        self._stop_event = threading.Event()
        self._proc = None
        self._loop = None
        self._subscribers = set()
        self._log_lock = threading.Lock()

    # ── SSE 订阅 ──────────────────────────────────────

    def set_loop(self, loop):
        self._loop = loop

    def subscribe(self):
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self._subscribers.discard(q)

    def _emit(self, event):
        if not self._loop:
            return
        try:
            self._loop.call_soon_threadsafe(self._dispatch, event)
        except (RuntimeError, ValueError):
            pass

    def _dispatch(self, event):
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    # ── 日志 ──────────────────────────────────────────

    def log(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        with self._log_lock:
            self.logs.append(line)
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[:len(self.logs) - MAX_LOG_LINES]
        self._emit({"type": "log", "line": line})
        try:
            print(line, flush=True)
        except Exception:
            pass

    def snapshot_logs(self, limit=400):
        with self._log_lock:
            return list(self.logs[-limit:])

    def _set_stage(self, name, index=0, total=0):
        self.stage = {"name": name, "index": index, "total": total}
        self.log("— 阶段 %s%s —" % (name,
                  "（%s/%s）" % (index, total) if total else ""))
        self._emit({"type": "stage", "stage": dict(self.stage)})

    # ── 任务控制 ──────────────────────────────────────

    def busy(self):
        return self.status in ("running", "stopping")

    def start(self, params):
        """校验并启动任务。返回 (ok, message, errors)。"""
        if self.busy():
            return False, "已有打包任务在进行中（%s），请等待完成或先停止" % self.status, []
        cfg = self.store.load()
        errors, normalized = self.profile.validate(params, cfg)
        if errors:
            return False, "参数校验未通过", errors

        self.status = "running"
        self.task_id = uuid.uuid4().hex[:8]
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.finished_at = ""
        self.elapsed = 0
        self.error = ""
        self.params = normalized
        self.stage = {"name": "", "index": 0, "total": 0}
        self.last_result = {"params": dict(normalized)}
        self._stop_event.clear()
        with self._log_lock:
            self.logs = []

        self._thread = threading.Thread(target=self._run, args=(normalized,), daemon=True)
        self._thread.start()
        self._emit({"type": "start", "task_id": self.task_id, "params": normalized})
        return True, "", []

    def stop(self):
        if not self.busy():
            return False
        self.status = "stopping"
        self._stop_event.set()
        self.log("🛑 正在停止任务…")
        if self._proc:
            kill_tree(self._proc.pid, self.log)
        self._emit({"type": "status", "status": self.status})
        return True

    def adhoc_context(self):
        """空闲时的临时上下文：给「单独提交 SVN」这类操作复用日志与 last_result。"""
        return RunContext(self)

    def _run(self, params):
        ctx = RunContext(self)
        start_ts = time.time()
        self.log("=" * 52)
        self.log("🚀 %s 任务 %s 开始" % (self.profile.TITLE, self.task_id))
        try:
            self.profile.run(params, ctx)
            if self.status == "stopping":
                raise Aborted("任务已停止")
            self.status = "done"
            self.log("🎉 打包完成，用时 %.1fs" % (time.time() - start_ts))
            record = self.profile.history_record(params, ctx.result)
            if record:
                count = self.store.add_history(record, self.profile.HISTORY_DEDUP_KEY)
                self.log("📚 已记入历史（当前 %d 条）" % count)
                ctx.set_result(history_count=count)
            self._emit({"type": "complete", "result": dict(self.last_result),
                        "elapsed": round(time.time() - start_ts, 1)})
        except Aborted as e:
            self.status = "stopped"
            self.error = str(e)
            self.log("🛑 任务已停止：%s" % e)
            self._emit({"type": "stopped", "error": self.error})
        except Exception as e:
            self.status = "error"
            self.error = "%s: %s" % (type(e).__name__, e)
            self.log("❌ 任务失败：%s" % self.error)
            for line in traceback.format_exc().splitlines()[-8:]:
                self.log("   " + line)
            self._emit({"type": "error", "error": self.error})
        finally:
            self.elapsed = round(time.time() - start_ts, 1)
            self.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self._proc = None
            self.log("=" * 52)
            self._emit({"type": "finish", "status": self.status,
                        "elapsed": self.elapsed})

    # ── 状态快照 ──────────────────────────────────────

    def get_status(self):
        return {
            "status": self.status,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": self.elapsed,
            "stage": dict(self.stage),
            "error": self.error,
            "params": dict(self.params),
            "result": dict(self.last_result),
            "busy": self.busy(),
            "logs": self.snapshot_logs(),
        }
