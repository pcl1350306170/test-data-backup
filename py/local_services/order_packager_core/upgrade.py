# -*- coding: utf-8 -*-
"""门诊前端 / 服务端升级：SFTP 上传包 → 执行 publish 脚本，逻辑迁自 门诊升级.pyw。

前端升级传 zip 跑 publish_front.sh，服务端升级传 war 跑 publish_server.sh，
两者共用同一套骨架，差异全部收敛为 UpgradeEngine 的类属性，ServerUpgradeEngine 只改属性：

与打包服务共用同一套骨架：
- UpgradeEngine 继承 PackEngine，线程 / SSE / 日志环形缓冲 / 停止 / 状态快照全部复用，
  只重写 start 校验与 _run 业务流程（升级不走 profile.validate / run）
- 服务器凭据共用 py/yarward/json/testServer.json（桌面版 门诊升级.pyw / 病房升级.pyw
  也在读写同一文件，保持单一数据源；每次现读现写 + 原子替换，不长期缓存）
- 凭据自愈流程与桌面版一致：先验证当前密码 → 失效则清空旧密码 →
  root/yahua × 默认密码轮试 → 都失败让页面引导手动输入 → 成功后写回 json
- 上传走 sftp.put(callback)，比桌面版多了真实字节级进度；停止直接关 SSH 连接
"""
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Query
from fastapi.responses import StreamingResponse

from . import browse, notify, util, vcs
from .engine import Aborted, PackEngine

try:
    import paramiko
except ImportError:
    paramiko = None

# 与桌面版 门诊升级.pyw 保持一致的远程路径 / 发布脚本 / 默认凭据
FRONT_REMOTE_DIR = "/home/ym_clinic/ym801s_setup/application/webapps/front"
PUBLISH_FRONT_SCRIPT = "publish_front.sh"
SERVER_REMOTE_DIR = "/home/ym_clinic/ym801s_setup/application/webapps/server"
PUBLISH_SERVER_SCRIPT = "publish_server.sh"
DEFAULT_PASSWORDS = ("Yahua3585668", "yh123456", "Huawei@123")
ZIP_PREFIX = "YM-801S-"
WAR_PREFIX = "YM-801S-OSCS-"
TEST_SERVER_PATH = util.py_dir() / "yarward" / "json" / "testServer.json"
LEGACY_UPGRADE_CONFIG = util.py_dir() / "yarward" / "json" / "config_yarward_upgrade.json"

_servers_lock = threading.Lock()


# ── testServer.json 读写（共用原文件）─────────────────────────────

def load_servers():
    data = util.read_json(TEST_SERVER_PATH, default={})
    return data if isinstance(data, dict) else {}


def save_server(host, username, password):
    """写入/更新一台服务器的凭据；password 传空串即清空旧密码。"""
    with _servers_lock:
        data = load_servers()
        entry = data.get(host)
        if not isinstance(entry, dict):
            entry = {"link": host}
        entry["name"] = username or "root"
        entry["password"] = password or ""
        data[host] = entry
        util.write_json(TEST_SERVER_PATH, data)
    return entry


def _connect(host, username, password, timeout=8):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=username, password=password, timeout=timeout)
    return client


def resolve_auth(host, username="", password="", log=None):
    """验证凭据并按桌面版流程自愈。返回 {status, host, username, password, message}。

    status: ok | need_password（默认密码全失败，请页面引导输入）|
            auth_failed（给了密码但认证失败，旧密码已清空）| error（网络等其他异常）
    """
    host = (host or "").strip()
    if not host:
        return {"status": "error", "message": "请输入服务器地址"}
    if paramiko is None:
        return {"status": "error", "message": "缺少 paramiko 依赖，请先 pip install paramiko"}
    log = log or (lambda msg: None)
    saved = load_servers().get(host) or {}
    username = (username or "").strip() or saved.get("name") or "root"
    password = (password or "").strip()

    def _try(user, pwd, timeout=8):
        """返回 (ok, auth_failed)；网络不通等非认证异常向上抛。"""
        try:
            client = _connect(host, user, pwd, timeout=timeout)
            client.close()
            return True
        except paramiko.AuthenticationException:
            return False

    try:
        # 1. 当前密码（页面传入优先，其次已保存的）
        current = password or saved.get("password") or ""
        if current:
            log("🔑 验证 %s@%s 的当前密码…" % (username, host))
            if _try(username, current):
                return {"status": "ok", "host": host, "username": username, "password": current}
            if password:
                # 用户刚输入的密码也不对：不再轮试，直接让页面重新输入
                return {"status": "auth_failed", "host": host, "username": username,
                        "message": "密码认证失败，请重新输入"}
            # 已保存的旧密码失效：清空后走默认密码轮试（桌面版同款流程）
            log("⚠️ 已保存的密码认证失败（服务器密码可能已更改），尝试默认凭据…")
            save_server(host, username, "")

        # 2. 默认用户名 × 默认密码轮试
        usernames = [username] + (["yahua"] if username != "yahua" else [])
        for user in usernames:
            for pwd in DEFAULT_PASSWORDS:
                log("🔑 尝试 %s / %s" % (user, pwd))
                if _try(user, pwd, timeout=5):
                    save_server(host, user, pwd)
                    log("✅ 凭据生效并已保存到 testServer.json")
                    return {"status": "ok", "host": host, "username": user, "password": pwd}
        return {"status": "need_password", "host": host, "username": username,
                "message": "默认密码均无法连接 %s，请手动输入密码" % host}
    except Exception as e:
        return {"status": "error", "host": host,
                "message": "无法连接服务器 %s：%s" % (host, e)}


# ── 升级引擎 ──────────────────────────────────────────────────────

class UpgradeEngine(PackEngine):
    """前端升级任务：复用父类线程 / SSE / 日志 / 停止，业务在 _run 里。"""

    # 差异点全部做成类属性，服务端升级子类只覆写这些（前端默认值保持原行为）
    TITLE = "门诊前端升级"
    REMOTE_DIR = FRONT_REMOTE_DIR
    PUBLISH_SCRIPT = PUBLISH_FRONT_SCRIPT
    FILE_SUFFIX = ".zip"
    FILE_WORD = "ZIP 包"
    SEARCH_PREFIX = ZIP_PREFIX
    SEARCH_RESULT_KEY = "zips"
    FILES_KEY = "zip_paths"
    NAMES_KEY = "zip_names"
    HISTORY_KEY = "upgrade_history_records"
    LAST_SERVER_KEY = "upgrade_last_server"
    TIMEOUT_KEY = "upgrade_timeout"
    DONE_TITLE = "✅ 升级完成"
    LEGACY_HISTORY_FIELD = "history_frontend"
    ROUTE_PREFIX = "/api/upgrade"
    STATE_ATTR = "upgrade_engine"
    DEDUP_FIELD = "_dedup_key"

    def __init__(self, profile, store):
        super().__init__(profile, store)
        self._ssh = None
        self._migrate_legacy()

    def _migrate_legacy(self):
        """一次性只读迁移桌面版升级历史与上次服务器；旧文件保持不动。"""
        cfg = self.store.load()
        if cfg.get(self.HISTORY_KEY) or cfg.get(self.LAST_SERVER_KEY):
            return
        legacy = util.read_json(LEGACY_UPGRADE_CONFIG, default={})
        if not isinstance(legacy, dict) or not legacy:
            return
        patch = {}
        history = legacy.get(self.LEGACY_HISTORY_FIELD)
        if isinstance(history, list) and history:
            patch[self.HISTORY_KEY] = history
        if legacy.get("last_server"):
            patch[self.LAST_SERVER_KEY] = legacy["last_server"]
        if patch:
            self.store.update(patch)
            self.log("📦 已迁移桌面版升级配置：%s" % LEGACY_UPGRADE_CONFIG)

    # ── 任务控制 ──────────────────────────────────────

    def start(self, params):
        if self.busy():
            return False, "已有升级任务在进行中，请等待完成或先停止", []
        if paramiko is None:
            return False, "参数校验未通过", ["缺少 paramiko 依赖，请先 pip install paramiko"]
        host = str((params or {}).get("host") or "").strip()
        username = str((params or {}).get("username") or "").strip() or "root"
        password = str((params or {}).get("password") or "")
        files = (params or {}).get(self.FILES_KEY) or []
        errors = []
        if not host:
            errors.append("请填写服务器地址")
        if not isinstance(files, list) or not files:
            errors.append("请先选择要升级的%s" % self.FILE_WORD)
        else:
            for z in files:
                if not Path(str(z)).is_file():
                    errors.append("文件不存在：%s" % z)
                elif not str(z).lower().endswith(self.FILE_SUFFIX):
                    errors.append("不是 %s 文件：%s" % (self.FILE_SUFFIX, z))
        if errors:
            return False, "参数校验未通过", errors

        normalized = {"host": host, "username": username, "password": password,
                      self.FILES_KEY: [str(z) for z in files]}
        self.status = "running"
        self.task_id = uuid.uuid4().hex[:8]
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.finished_at = ""
        self.elapsed = 0
        self.error = ""
        self.params = normalized
        self.stage = {"name": "", "index": 0, "total": 0}
        self.last_result = {"host": host}
        self._stop_event.clear()
        with self._log_lock:
            self.logs = []
        self.store.update({self.LAST_SERVER_KEY: host})
        self._thread = threading.Thread(target=self._run, args=(normalized,), daemon=True)
        self._thread.start()
        self._emit({"type": "start", "task_id": self.task_id,
                    "params": {k: v for k, v in normalized.items() if k != "password"}})
        return True, "", []

    def stop(self):
        ok = super().stop()
        if ok and self._ssh:
            try:
                self._ssh.close()   # 断开连接以中断阻塞中的上传 / 命令读取
            except Exception:
                pass
        return ok

    # ── 执行 ──────────────────────────────────────────

    def _check_stop(self):
        if self._stop_event.is_set():
            raise Aborted("用户已停止任务")

    def _ensure_remote_dir(self, sftp, remote):
        try:
            sftp.stat(remote)
            self.log("✅ 远程目录已存在: %s" % remote)
            return
        except FileNotFoundError:
            pass
        self.log("📁 创建远程目录: %s" % remote)
        parent = remote.rsplit("/", 1)[0]
        if parent and parent != remote:
            self._ensure_remote_dir(sftp, parent)
        sftp.mkdir(remote)

    def _upload(self, sftp, local, remote, index, total):
        size = local.stat().st_size
        state = {"last": 0.0}

        def _cb(sent, total_bytes):
            self._check_stop()
            now = time.time()
            if now - state["last"] < 0.4 and sent < total_bytes:
                return
            state["last"] = now
            self._emit({"type": "progress", "file": local.name,
                        "index": index, "total": total, "sent": sent,
                        "size": total_bytes,
                        "percent": round(sent * 100.0 / (total_bytes or 1), 1)})

        self.log("⬆️ 正在上传: %s（%s）" % (local.name, util.human_size(size)))
        sftp.put(str(local), remote, callback=_cb)
        self.log("✅ 已上传: %s" % local.name)

    def _publish(self, ssh, file_name, timeout):
        cmd = "cd %s && sh %s %s" % (self.REMOTE_DIR, self.PUBLISH_SCRIPT, file_name)
        self.log("▶ %s" % cmd)
        stdin, stdout, stderr = ssh.exec_command(cmd)
        stdout.channel.settimeout(timeout)
        try:
            for line in iter(stdout.readline, ""):
                self._check_stop()
                line = (line or "").strip()
                if line:
                    self.log("   " + line)
        except Aborted:
            raise
        except Exception as e:
            if self._stop_event.is_set():
                raise Aborted("用户已停止任务")
            raise RuntimeError("执行 %s 超时或读取输出失败（%ss）：%s"
                               % (self.PUBLISH_SCRIPT, timeout, e))
        code = stdout.channel.recv_exit_status()
        err = (stderr.read() or b"").decode("utf-8", "replace").strip()
        if err:
            self.log("[STDERR] %s" % err)
        if code != 0:
            raise RuntimeError("%s %s 执行失败，返回码: %s"
                               % (self.PUBLISH_SCRIPT, file_name, code))
        self.log("✅ %s 升级完成！" % file_name)

    def _run(self, params):
        start_ts = time.time()
        host, username, password = params["host"], params["username"], params["password"]
        files = [Path(z) for z in params[self.FILES_KEY]]
        timeout = int(self.store.load().get(self.TIMEOUT_KEY) or 300)
        self.log("=" * 52)
        self.log("🚀 %s 任务 %s 开始" % (self.TITLE, self.task_id))
        try:
            self._set_stage("连接服务器", 1, 1 + len(files) * 2)
            self.log("正在连接服务器 %s（%s）…" % (host, username))
            ssh = _connect(host, username, password, timeout=10)
            self._ssh = ssh
            try:
                self._check_stop()
                sftp = ssh.open_sftp()
                self._ensure_remote_dir(sftp, self.REMOTE_DIR)
                step = 2
                for i, local in enumerate(files, 1):
                    self._check_stop()
                    self._set_stage("上传 %s" % local.name, step, 1 + len(files) * 2)
                    step += 1
                    self._upload(sftp, local, "%s/%s" % (self.REMOTE_DIR, local.name),
                                 i, len(files))
                    self._set_stage("发布 %s" % local.name, step, 1 + len(files) * 2)
                    step += 1
                    self._publish(ssh, local.name, timeout)
                sftp.close()
            finally:
                self._ssh = None
                try:
                    ssh.close()
                except Exception:
                    pass
            if self.status == "stopping":
                raise Aborted("任务已停止")

            self.status = "done"
            names = ", ".join(z.name for z in files)
            self.last_result.update({
                "host": host, "username": username,
                self.FILES_KEY: [str(z) for z in files], self.NAMES_KEY: names,
                "package_path": str(files[0]),
                "package_name": "%s ← %s" % (host, names),
            })
            self.log("🎉 服务器 %s %s完成，用时 %.1fs" % (host, self.TITLE, time.time() - start_ts))
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "server": host, "username": username,
                self.FILES_KEY: [str(z) for z in files], self.NAMES_KEY: names,
                "svn_dir": files[0].parent.name,
                "_dedup_key": "%s_%s" % (host, names),
            }
            count = self.store.add_history(record, self.DEDUP_FIELD, key=self.HISTORY_KEY)
            self.log("📚 已记入升级历史（当前 %d 条）" % count)
            self._emit({"type": "complete", "result": dict(self.last_result),
                        "elapsed": round(time.time() - start_ts, 1)})
            notify.native_done(self.profile.TITLE, dict(self.last_result),
                               self.store.load(), title_text=self.DONE_TITLE)
        except Aborted as e:
            self.status = "stopped"
            self.error = str(e)
            self.log("🛑 任务已停止：%s" % e)
            self._emit({"type": "stopped", "error": self.error})
        except Exception as e:
            if self.status == "stopping":
                self.status = "stopped"
                self.error = "任务已停止"
                self.log("🛑 任务已停止（连接已断开）")
                self._emit({"type": "stopped", "error": self.error})
            else:
                self.status = "error"
                self.error = "%s: %s" % (type(e).__name__, e)
                self.log("❌ 升级失败：%s" % self.error)
                for line in traceback.format_exc().splitlines()[-8:]:
                    self.log("   " + line)
                self._emit({"type": "error", "error": self.error})
        finally:
            self.elapsed = round(time.time() - start_ts, 1)
            self.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self._ssh = None
            self.log("=" * 52)
            self._emit({"type": "finish", "status": self.status, "elapsed": self.elapsed})


class ServerUpgradeEngine(UpgradeEngine):
    """服务端升级：传 war 到 webapps/server 跑 publish_server.sh，只改差异属性。"""

    TITLE = "门诊服务端升级"
    REMOTE_DIR = SERVER_REMOTE_DIR
    PUBLISH_SCRIPT = PUBLISH_SERVER_SCRIPT
    FILE_SUFFIX = ".war"
    FILE_WORD = "WAR 包"
    SEARCH_PREFIX = WAR_PREFIX
    SEARCH_RESULT_KEY = "wars"
    FILES_KEY = "war_paths"
    NAMES_KEY = "war_names"
    HISTORY_KEY = "server_upgrade_history_records"
    LAST_SERVER_KEY = "server_upgrade_last_server"
    TIMEOUT_KEY = "server_upgrade_timeout"
    DONE_TITLE = "✅ 服务端升级完成"
    LEGACY_HISTORY_FIELD = "history_server"
    ROUTE_PREFIX = "/api/server-upgrade"
    STATE_ATTR = "server_upgrade_engine"


# ── 路由（只由门诊服务挂载，前端 / 服务端各挂一套）─────────────────

def attach_upgrade_routes(app, profile, store, engine, sse_timeout=30):
    import asyncio
    import json

    prefix = engine.ROUTE_PREFIX

    @app.get(prefix + "/servers")
    def upgrade_servers():
        """testServer.json 全量列表（含密码，与桌面版一致的单机明文约定）。"""
        data = load_servers()
        servers = [{"host": h, "name": (v or {}).get("name") or "root",
                    "password": (v or {}).get("password") or ""}
                   for h, v in data.items()]
        servers.sort(key=lambda s: s["host"])
        return {"servers": servers, "path": str(TEST_SERVER_PATH),
                "last_server": store.load().get(engine.LAST_SERVER_KEY, "")}

    @app.post(prefix + "/server/save")
    def upgrade_server_save(data: dict):
        host = str((data or {}).get("host") or "").strip()
        password = str((data or {}).get("password") or "").strip()
        username = str((data or {}).get("username") or "").strip() or "root"
        if not host or not password:
            raise HTTPException(400, "请填写服务器地址和密码")
        save_server(host, username, password)
        store.update({engine.LAST_SERVER_KEY: host})
        return {"ok": True, "host": host}

    @app.post(prefix + "/auth")
    def upgrade_auth(data: dict):
        """验证凭据 + 默认密码轮试；阻塞型（最多 6 次 SSH），同步 def 走线程池。"""
        data = data or {}
        return resolve_auth(data.get("host"), data.get("username"),
                            data.get("password"), log=engine.log)

    @app.post(prefix + "/search")
    def upgrade_search(data: dict):
        """关键字搜 SVN 目录（自动选最新并列出包），或列指定目录下的包。"""
        cfg = store.load()
        base = cfg.get("svn_base_dir", "")
        rk = engine.SEARCH_RESULT_KEY
        directory = str((data or {}).get("dir") or "").strip()
        if directory:
            try:
                target = browse.check_root(directory, [base])
            except browse.PathDenied as e:
                raise HTTPException(400, str(e))
            files = vcs.find_files(Path(target), engine.SEARCH_PREFIX, engine.FILE_SUFFIX)
            return {"dir": target, rk: files, "total": len(files)}
        keyword = str((data or {}).get("keyword") or "").strip()
        if not keyword:
            raise HTTPException(400, "请输入关键字")
        dirs = vcs.dirs_by_name(base, keyword)
        selected, files = "", []
        if dirs:
            selected = dirs[0]["path"]   # dirs_by_name 已按 mtime 倒序，首个即最新
            files = vcs.find_files(Path(selected), engine.SEARCH_PREFIX, engine.FILE_SUFFIX)
        return {"keyword": keyword, "dirs": dirs, "selected": selected,
                rk: files, "base": base,
                "notice": "" if dirs else "未找到包含「%s」的目录（基础目录：%s）" % (keyword, base)}

    @app.post(prefix + "/start")
    def upgrade_start(data: dict):
        ok, message, errors = engine.start(data or {})
        if not ok:
            raise HTTPException(400 if errors else 409,
                                {"message": message, "errors": errors})
        return {"ok": True, "task_id": engine.task_id, "status": engine.status}

    @app.get(prefix + "/status")
    def upgrade_status():
        return engine.get_status()

    @app.post(prefix + "/stop")
    def upgrade_stop():
        if not engine.stop():
            raise HTTPException(409, "当前没有在进行的升级任务")
        return {"ok": True, "status": engine.status}

    @app.get(prefix + "/progress")
    async def upgrade_progress():
        """SSE：与打包进度同款——先补发日志快照，再实时推送，30s 心跳。"""
        queue = engine.subscribe()

        async def stream():
            try:
                init = {"type": "init", "status": engine.get_status()}
                yield "data: %s\n\n" % json.dumps(init, ensure_ascii=False)
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=sse_timeout)
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

    @app.get(prefix + "/history")
    def upgrade_history():
        records = store.history(engine.HISTORY_KEY)
        return {"records": records, "total": len(records)}

    @app.delete(prefix + "/history")
    def upgrade_history_delete(index: int = Query(...)):
        result = store.delete_history(index, key=engine.HISTORY_KEY)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "删除失败"))
        return result

    setattr(app.state, engine.STATE_ATTR, engine)