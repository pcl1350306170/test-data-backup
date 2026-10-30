# -*- coding: utf-8 -*-
"""合并引擎：按目标时长对成品音频分组，ffmpeg concat 合并，支持 BGM 叠加/元数据/封面。

核心逻辑移植自 py/other/音频合并工具.pyw（去 GUI、去 pydub，全部 ffmpeg 管道）：
- ffprobe 快速取时长 → 动态均值分组，各组时长均匀
- concat demuxer 拼接为统一格式临时 WAV（44100Hz/立体声）
- finalize 一次完成：BGM 循环混音+尾部淡出 + MP3 编码 + 元数据/封面/背景图嵌入
- SSE 事件推送复用 TaskEngine 模式（loop.call_soon_threadsafe）
"""
import asyncio
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import date
from typing import Optional

from . import tts_engine
from .config import load as load_config
from .task_engine import resolve_output_path

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_TARGET_SAMPLE_RATE = 44100
_TARGET_CHANNELS = 2

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ── ffmpeg 纯函数 ─────────────────────────────────────

def ffprobe_duration(filepath: str) -> float:
    """快速获取音频时长（秒），不解码音频数据。"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", filepath],
        capture_output=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("ffprobe 失败: %s" % (result.stderr or "").strip()[-300:])
    try:
        return float((result.stdout or "").strip())
    except (ValueError, TypeError):
        raise RuntimeError("无法解析时长: %s" % filepath)


def ffmpeg_concat_batch(file_paths: list, output_wav: str):
    """concat demuxer 合并文件列表为统一格式 WAV。"""
    import tempfile
    list_fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="tts_merge_concat_")
    try:
        with os.fdopen(list_fd, "w", encoding="utf-8") as f:
            for fp in file_paths:
                safe = fp.replace("\\", "/").replace("'", "'\\''")
                f.write("file '%s'\n" % safe)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin",
               "-f", "concat", "-safe", "0", "-i", list_path,
               "-ar", str(_TARGET_SAMPLE_RATE), "-ac", str(_TARGET_CHANNELS),
               "-acodec", "pcm_s16le", output_wav]
        result = subprocess.run(cmd, capture_output=True,
                                creationflags=_NO_WINDOW, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError("ffmpeg concat 失败: %s" % (
                (result.stderr or b"").decode("utf-8", errors="replace")[-500:]))
        if not os.path.isfile(output_wav) or os.path.getsize(output_wav) == 0:
            raise RuntimeError("ffmpeg concat 未生成有效文件")
    finally:
        try:
            os.unlink(list_path)
        except Exception:
            pass


def ffmpeg_finalize(input_wav, output_path, fmt="wav", bgm_path=None,
                    bgm_volume=30, total_duration=0.0, metadata=None,
                    cover_path=None, bg_image_path=None):
    """BGM 叠加 + 元数据/封面嵌入 + 格式转换，ffmpeg 一次完成。"""
    has_bgm = bool(bgm_path) and os.path.isfile(bgm_path) and bgm_volume > 0

    # 第一步：收集所有输入文件
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin", "-i", input_wav]
    next_input = 1
    if has_bgm:
        cmd += ["-i", bgm_path]
        next_input = 2

    # 图片嵌入（仅 MP3）- 先添加所有图片输入
    images = []
    if fmt == "mp3":
        if cover_path and os.path.isfile(cover_path):
            images.append((cover_path, "Album cover", "Cover (front)"))
        if bg_image_path and os.path.isfile(bg_image_path):
            images.append((bg_image_path, "Background", "Other"))
        for img_path, _t, _c in images:
            cmd += ["-i", img_path]

    # 第二步：添加滤镜和映射
    filter_parts = []
    if has_bgm:
        gain_db = -30.0 + (bgm_volume / 100.0) * 30.0
        fade_start = max(0.0, total_duration - 2.0)
        filter_parts.append(
            "[1:a]volume=%.2fdB,aloop=loop=-1:size=2147483647,"
            "atrim=duration=%.3f,afade=t=out:st=%.3f:d=2,"
            "aformat=sample_rates=%d:channel_layouts=stereo[bgm]" % (
                gain_db, total_duration, fade_start, _TARGET_SAMPLE_RATE))
        filter_parts.append(
            "[0:a][bgm]amix=inputs=2:duration=first:normalize=0[out]")

    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[out]"]
    else:
        cmd += ["-map", "0:a"]

    # 图片映射（在所有 -i 之后）
    if images:
        for idx in range(len(images)):
            cmd += ["-map", "%d:0" % (next_input + idx)]
        cmd += ["-c:v", "mjpeg", "-id3v2_version", "3"]
        for idx, (_p, title, comment) in enumerate(images):
            cmd += ["-metadata:s:v:%d" % idx, "title=%s" % title,
                    "-metadata:s:v:%d" % idx, "comment=%s" % comment]

    if fmt == "mp3":
        cmd += ["-acodec", "libmp3lame", "-q:a", "2"]
    else:
        cmd += ["-acodec", "pcm_s16le"]

    if metadata:
        for k, v in metadata.items():
            if v:
                cmd += ["-metadata", "%s=%s" % (k, v)]

    cmd += [output_path]
    result = subprocess.run(cmd, capture_output=True,
                            creationflags=_NO_WINDOW, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 最终处理失败: %s" % (
            (result.stderr or b"").decode("utf-8", errors="replace")[-500:]))


def group_files(file_paths: list, target_minutes: int):
    """动态均值分组。返回 (batches, total_ms, batches_ms)。"""
    target_ms = max(1, int(target_minutes)) * 60 * 1000
    durs = []
    for fp in file_paths:
        try:
            durs.append((fp, int(ffprobe_duration(fp) * 1000)))
        except Exception:
            continue
    if not durs:
        return [], 0, []
    total_ms = sum(d for _, d in durs)
    num_batches = max(1, math.ceil(total_ms / target_ms))

    batches, batches_ms = [], []
    cur, cur_dur = [], 0
    remaining_dur, remaining_batches = total_ms, num_batches
    for fp, d in durs:
        if cur:
            dynamic_avg = remaining_dur / remaining_batches
            if cur_dur + d > dynamic_avg:
                batches.append(cur)
                batches_ms.append(cur_dur)
                remaining_dur -= cur_dur
                remaining_batches -= 1
                cur, cur_dur = [fp], d
            else:
                cur.append(fp)
                cur_dur += d
        else:
            cur, cur_dur = [fp], d
    if cur:
        batches.append(cur)
        batches_ms.append(cur_dur)
    return batches, total_ms, batches_ms


def _sanitize_filename(name: str) -> str:
    """去除文件名中系统不允许的字符。"""
    invalid = '<>:"/\\|?*\x00'
    return "".join(c for c in name if c not in invalid).strip()


def build_metadata(meta: dict, part: int, total: int, start_num: str = "1") -> dict:
    """单组元数据：标题+序号，空值过滤。
    start_num: 起始序号字符串，如 "1" 或 "001"（前导零决定补零宽度）
    """
    title = (meta.get("title") or "").strip()
    # 解析起始序号
    raw = str(start_num).strip() or "1"
    try:
        start = int(raw)
        if start < 0:
            start = 1
            raw = "1"
    except (ValueError, TypeError):
        start = 1
        raw = "1"
    width = max(1, len(raw))
    seq_num = start + part - 1
    if title:
        title = "%s%0*d" % (title, width, seq_num)
    d = {
        "title": title,
        "artist": (meta.get("artist") or "").strip(),
        "album": (meta.get("album") or "").strip(),
        "date": (meta.get("date") or "").strip() or date.today().strftime("%Y"),
        "comment": (meta.get("comment") or "").strip(),
        "track": "%d/%d" % (part, total),
    }
    return {k: v for k, v in d.items() if v}


def scan_media_dir(dir_path: str, images: bool = False) -> list:
    """扫描媒体目录，返回 [{name, path}]。"""
    items = []
    exts = IMAGE_EXTS if images else tts_engine.AUDIO_EXTS
    if dir_path and os.path.isdir(dir_path):
        for f in sorted(os.listdir(dir_path)):
            fp = os.path.join(dir_path, f)
            ext = os.path.splitext(f)[1].lower()
            if os.path.isfile(fp) and ext in exts:
                items.append({"name": os.path.splitext(f)[0], "path": fp})
    return items


# ── 合并引擎 ──────────────────────────────────────────

class MergeEngine:
    """单活动合并引擎（与 TTS 生成任务互斥，由 server 层校验）。"""

    def __init__(self):
        self.status = "idle"  # idle|running|stopping|done|error|cancelled
        self.total = 0
        self.current = 0
        self.logs: list = []
        self.files: list = []
        self.error = ""
        self.source_name = ""
        self.started_at = ""
        self.out_dir = ""          # 本次合并的实际输出目录（根目录/标题）
        self.title = ""

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set = set()

    # ── SSE ─────────────────────────────────────────

    def set_loop(self, loop):
        self._loop = loop

    def subscribe(self):
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q, self._loop

    def unsubscribe(self, q):
        self._subscribers.discard(q)

    def _emit(self, event: dict):
        if not self._loop:
            return
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass

    def busy(self) -> bool:
        return self.status in ("running", "stopping")

    # ── 分组预览 ──────────────────────────────────────

    def preview(self, names: list, target_minutes: int) -> dict:
        cfg = load_config()
        out_dir = cfg.get("output_dir", "")
        paths = [resolve_output_path(out_dir, n) for n in names or []]
        paths = [p for p in paths if p and os.path.isfile(p)]
        batches, total_ms, batches_ms = group_files(paths, target_minutes)
        groups = [{
            "files": [os.path.basename(p) for p in b],
            "count": len(b),
            "seconds": round(ms / 1000, 1),
        } for b, ms in zip(batches, batches_ms)]
        return {"groups": groups, "total_seconds": round(total_ms / 1000, 1),
                "num_groups": len(batches), "skipped": len(names or []) - len(paths)}

    # ── 任务控制 ──────────────────────────────────────

    def start(self, names: list, params: dict, test: bool = False,
              source_name: str = "", confirm: bool = False) -> tuple:
        """返回 (ok, error_msg, need_confirm)。"""
        if self.busy():
            return False, "已有合并任务正在运行，请等待完成或停止", False
        if not shutil.which("ffmpeg"):
            return False, "缺少 ffmpeg，请确保已安装并添加到环境变量", False

        # 检查标题
        meta = params.get("metadata") or {}
        title = (meta.get("title") or "").strip()
        if not title:
            return False, "必须输入标题", False

        cfg = load_config()
        tts_out_dir = cfg.get("output_dir", "")
        paths = []
        for n in names or []:
            p = resolve_output_path(tts_out_dir, n)
            if p and os.path.isfile(p):
                paths.append(p)
        if not paths:
            return False, "没有可合并的音频文件", False

        target_minutes = int(params.get("target_duration") or 20)
        batches, _, _ = group_files(paths, target_minutes)
        if not batches:
            return False, "音频时长解析失败，无法分组", False
        if test:
            batches = [batches[0]]

        # 确定输出目录：merge_output_dir/标题
        merge_out_base = (params.get("output_dir") or "").strip()
        if not merge_out_base:
            merge_out_base = cfg.get("merge_output_dir", "")
        if not merge_out_base:
            return False, "未配置合并输出目录", False

        safe_title = _sanitize_filename(title)
        final_out_dir = os.path.join(merge_out_base, safe_title)

        # 目录已存在且未确认，返回需要确认
        if os.path.isdir(final_out_dir) and not confirm:
            return False, "", True  # need_confirm=True

        # 创建目录
        try:
            os.makedirs(final_out_dir, exist_ok=True)
        except Exception as e:
            return False, "创建输出目录失败: %s" % e, False

        self.status = "running"
        self.total = len(batches)
        self.current = 0
        self.logs = []
        self.files = []
        self.error = ""
        self.out_dir = final_out_dir
        self.title = safe_title
        self.source_name = tts_engine.safe_name(source_name) or "合并音频"
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run, args=(batches, final_out_dir, params), daemon=True)
        self._thread.start()
        return True, "", False

    def stop(self) -> bool:
        if not self.busy():
            return False
        self._stop_event.set()
        self.status = "stopping"
        return True

    def get_status(self) -> dict:
        return {
            "status": self.status,
            "total": self.total,
            "current": self.current,
            "progress": round(self.current / self.total * 100, 1) if self.total else 0,
            "logs": self.logs[-100:],
            "files": self.files,
            "error": self.error,
            "source_name": self.source_name,
            "started_at": self.started_at,
            "out_dir": self.out_dir,
        }

    def get_output_dir(self) -> dict:
        """返回合并输出的实际目录信息（供前端展示/一键打开）。"""
        cfg = load_config()
        root = (cfg.get("merge_output_dir") or "").strip()
        return {
            "out_dir": self.out_dir,
            "root_dir": root,
            "exists": bool(self.out_dir) and os.path.isdir(self.out_dir),
            "files": list(self.files),
            "status": self.status,
        }

    # ── 工作线程 ──────────────────────────────────────

    def _log(self, msg: str):
        self.logs.append(msg)
        if len(self.logs) > 500:
            self.logs = self.logs[-300:]
        self._emit({"type": "log", "message": msg})

    def _run(self, batches: list, out_dir: str, params: dict):
        temp_wav = os.path.join(out_dir, "_temp_merge_concat.wav")
        try:
            fmt = (params.get("format") or "mp3").lower()
            ext = "mp3" if fmt == "mp3" else "wav"
            bgm = (params.get("bgm_path") or "").strip()
            vol = int(params.get("bgm_volume") or 0)
            cover = (params.get("cover_path") or "").strip()
            bgimg = (params.get("bg_image_path") or "").strip()
            meta = params.get("metadata") or {}
            start_num = str(params.get("start_num") or "1").strip()
            total = self.total

            self._emit({"type": "started", "total": total, "out_dir": out_dir})
            self._log("开始合并：%d 组，格式=%s，来源=%s" % (total, ext.upper(), self.source_name))
            self._log("输出目录：%s" % out_dir)

            for i, batch in enumerate(batches):
                if self._stop_event.is_set():
                    self.status = "cancelled"
                    self._log("已在第 %d/%d 组后停止" % (i, total))
                    self._cleanup(temp_wav)
                    self._emit({"type": "cancelled"})
                    return

                part = i + 1
                self._log("[%d/%d] 拼接 %d 个文件..." % (part, total, len(batch)))
                self._emit({"type": "progress", "current": part, "total": total,
                            "percent": round((part - 1) / total * 100, 1)})
                try:
                    ffmpeg_concat_batch(batch, temp_wav)
                    dur = ffprobe_duration(temp_wav)
                except Exception as e:
                    self._log("[%d/%d] 合并失败: %s" % (part, total, e))
                    self._emit({"type": "group_error", "index": part, "error": str(e)})
                    continue

                # 输出文件名 = 标题+序号（与元数据标题一致）
                md = build_metadata(meta, part, total, start_num)
                title = (md.get("title") or "").strip()
                base = _sanitize_filename(title) if title else ""
                if not base:
                    base = "%s_%02d" % (self.source_name or "合并音频", part)
                filename = "%s.%s" % (base, ext)
                out_path = os.path.join(out_dir, filename)
                if os.path.exists(out_path):
                    filename = "%s_%s.%s" % (base, time.strftime("%H%M%S"), ext)
                    out_path = os.path.join(out_dir, filename)

                self._log("[%d/%d] 导出 %s (%.1f秒%s)" % (
                    part, total, filename, dur,
                    "，BGM %d%%" % vol if (bgm and vol > 0) else ""))
                try:
                    ffmpeg_finalize(
                        temp_wav, out_path, ext,
                        bgm_path=bgm or None, bgm_volume=vol,
                        total_duration=dur,
                        metadata=md,
                        cover_path=cover or None, bg_image_path=bgimg or None)
                except Exception as e:
                    self._log("[%d/%d] 导出失败: %s" % (part, total, e))
                    self._emit({"type": "group_error", "index": part, "error": str(e)})
                    continue

                self.current = part
                self.files.append(filename)
                self._emit({"type": "progress", "current": part, "total": total,
                            "percent": round(part / total * 100, 1), "file": filename})

            self._cleanup(temp_wav)
            if self._stop_event.is_set():
                self.status = "cancelled"
                self._emit({"type": "cancelled"})
            else:
                self.status = "done"
                self._log("合并完成，共输出 %d 个文件" % len(self.files))
                self._log("输出目录：%s" % out_dir)
                self._emit({"type": "complete", "files": self.files, "total": total,
                            "out_dir": out_dir})

        except Exception as e:
            self.status = "error"
            self.error = str(e)
            self._log("异常: %s" % e)
            self._cleanup(temp_wav)
            self._emit({"type": "error", "message": str(e)})
            traceback.print_exc()

    @staticmethod
    def _cleanup(path):
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except Exception:
            pass
