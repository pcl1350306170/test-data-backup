# -*- coding: utf-8 -*-
"""视频合并核心引擎：目录扫描 / 自然排序 / ffprobe 探测 / ffmpeg 拼接（无损直拷 + 重编码兜底）"""
import json
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
TMP_DIR = DATA_DIR / "tmp"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


# ── 自然排序 ─────────────────────────────────────────

def natural_key(text):
    """把字符串中的数字段按数值比较：第2集 < 第10集"""
    parts = re.split(r"(\d+)", text)
    return tuple((1, int(p)) if p.isdigit() else (0, p.lower()) for p in parts)


# ── 子进程工具 ───────────────────────────────────────

def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _norm_fps(rate: str):
    """'30000/1001' -> 29.97；异常返回 None"""
    try:
        num, _, den = rate.partition("/")
        den_v = float(den) if den else 1.0
        if den_v == 0:
            return None
        return round(float(num) / den_v, 3)
    except (ValueError, TypeError):
        return None


# ── 探测 ────────────────────────────────────────────

def probe_video(path: Path) -> dict:
    """ffprobe 单文件，返回时长/视频流/音频流摘要"""
    cmd = [
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    info = {
        "name": path.name,
        "path": str(path),
        "size": path.stat().st_size,
        "duration": 0.0,
        "vcodec": None, "width": 0, "height": 0, "fps": None, "pix_fmt": None,
        "acodec": None, "sample_rate": None, "channels": None,
        "error": None,
    }
    if result.returncode != 0:
        info["error"] = _decode(result.stderr).strip()[:300]
        return info
    try:
        data = json.loads(_decode(result.stdout))
    except json.JSONDecodeError as e:
        info["error"] = f"ffprobe 输出解析失败: {e}"
        return info

    fmt = data.get("format", {})
    try:
        info["duration"] = float(fmt.get("duration", 0) or 0)
    except ValueError:
        pass

    for st in data.get("streams", []):
        codec_type = st.get("codec_type")
        if codec_type == "video" and info["vcodec"] is None:
            info["vcodec"] = st.get("codec_name")
            info["width"] = int(st.get("width") or 0)
            info["height"] = int(st.get("height") or 0)
            info["fps"] = _norm_fps(st.get("avg_frame_rate") or "")
            info["pix_fmt"] = st.get("pix_fmt")
        elif codec_type == "audio" and info["acodec"] is None:
            info["acodec"] = st.get("codec_name")
            info["sample_rate"] = st.get("sample_rate")
            info["channels"] = st.get("channels")

    if info["vcodec"] is None:
        info["error"] = "未找到视频流"
    return info


def scan_directory(directory: str) -> dict:
    """扫描目录下 mp4 文件并按自然顺序排序 + 探测"""
    d = Path(directory)
    if not d.is_dir():
        return {"ok": False, "msg": f"目录不存在: {directory}"}

    files = sorted(
        [p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"],
        key=lambda p: natural_key(p.stem),
    )
    if not files:
        return {"ok": False, "msg": "目录下没有找到 .mp4 文件"}

    items = [probe_video(p) for p in files]
    analysis = analyze_compatibility(items)
    return {"ok": True, "directory": str(d), "items": items, "analysis": analysis}


def analyze_compatibility(items: list) -> dict:
    """判断能否无损直拷：视频编码/分辨率/帧率/像素格式 + 音频参数须一致"""
    valid = [it for it in items if not it.get("error")]
    if not valid:
        return {"compatible": False, "reasons": ["没有可探测成功的视频文件"], "target": None}
    if any(it.get("error") for it in items):
        bad = [it["name"] for it in items if it.get("error")]
        return {"compatible": False, "reasons": [f"以下文件探测失败: {'、'.join(bad)}"], "target": None}

    reasons = []
    first = valid[0]

    def _diff(field, label, fmt=str):
        vals = {fmt(it[field]) for it in valid}
        if len(vals) > 1:
            reasons.append(f"{label}不一致: {' / '.join(sorted(vals))}")

    _diff("vcodec", "视频编码")
    _diff("width", "宽度")
    _diff("height", "高度")
    _diff("pix_fmt", "像素格式")
    _diff("fps", "帧率", lambda v: str(v))

    has_audio = [it for it in valid if it["acodec"]]
    if has_audio and len(has_audio) != len(valid):
        reasons.append("部分文件没有音轨")
    elif has_audio:
        _diff("acodec", "音频编码")
        _diff("sample_rate", "音频采样率")
        _diff("channels", "音频声道数")

    target = {
        "width": first["width"],
        "height": first["height"],
        "fps": first["fps"] or 25.0,
        "duration_total": round(sum(it["duration"] for it in valid), 2),
    }
    return {"compatible": not reasons, "reasons": reasons, "target": target}


# ── 合并任务 ────────────────────────────────────────

TASKS: dict = {}
TASK_LOCK = threading.Lock()


def _fmt_time(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class MergeTask:
    def __init__(self, task_id, output, mode):
        self.id = task_id
        self.status = "running"      # running / done / error
        self.percent = 0.0
        self.message = "准备中..."
        self.output = str(output)
        self.mode = mode
        self.logs: list = []
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.error = None

    def log(self, line):
        self.logs.append(line)
        if len(self.logs) > 400:
            del self.logs[: len(self.logs) - 400]

    def to_dict(self):
        return {
            "id": self.id, "status": self.status, "percent": round(self.percent, 1),
            "message": self.message, "output": self.output, "mode": self.mode,
            "logs": self.logs[-60:], "error": self.error,
        }


def make_output_path(directory: str, output_name: str = "") -> Path:
    d = Path(directory)
    if output_name:
        if not output_name.lower().endswith(".mp4"):
            output_name += ".mp4"
        return d / output_name
    return d / f"合并输出_{datetime.now():%Y%m%d_%H%M%S}.mp4"


def start_merge(paths: list, output: Path, mode: str, items: list, analysis: dict) -> MergeTask:
    """mode: auto / copy / reencode；返回任务对象并后台执行"""
    actual = mode
    if mode == "auto":
        actual = "copy" if analysis.get("compatible") else "reencode"

    task = MergeTask(uuid.uuid4().hex[:12], output, actual)
    with TASK_LOCK:
        TASKS[task.id] = task
        # 只保留最近 20 个任务
        if len(TASKS) > 20:
            for old_id in list(TASKS)[: len(TASKS) - 20]:
                if TASKS[old_id].status != "running":
                    TASKS.pop(old_id, None)

    t = threading.Thread(
        target=_merge_worker, args=(task, paths, output, actual, items, analysis),
        daemon=True,
    )
    t.start()
    return task


def _merge_worker(task, paths, output, actual, items, analysis):
    try:
        if actual == "copy":
            _run_copy(task, paths, output, items)
        else:
            _run_reencode(task, paths, output, items, analysis)
        if task.status == "running":
            task.status = "done"
            task.percent = 100.0
            task.message = f"合并完成: {output.name}"
    except Exception as e:
        task.status = "error"
        task.error = str(e)[:500]
        task.message = f"合并失败: {e}"
        task.log(f"[error] {e}")


def _parse_progress_line(task, line, total_duration):
    line = line.strip()
    task.log(line)
    if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
        try:
            us = int(line.split("=", 1)[1])
            if total_duration > 0:
                task.percent = min(99.0, us / 1_000_000 / total_duration * 100)
                task.message = f"进度 {_fmt_time(us / 1_000_000)} / {_fmt_time(total_duration)}"
        except ValueError:
            pass


def _pump_output(task, proc, total_duration):
    for raw in iter(proc.stdout.readline, ""):
        _parse_progress_line(task, raw, total_duration)
    proc.stdout.close()
    return proc.wait()


def _run_copy(task, paths, output, items):
    """无损直拷：concat demuxer + -c copy"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    list_file = TMP_DIR / f"concat_{task.id}.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in paths:
            safe = str(p).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    total = sum(it["duration"] for it in items)
    task.message = f"无损直拷 {len(paths)} 个视频"
    cmd = [
        FFMPEG, "-y", "-v", "error", "-progress", "pipe:1",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart", str(output),
    ]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        code = _pump_output(task, proc, total)
        if code != 0:
            raise RuntimeError(f"ffmpeg 退出码 {code}，可能编码参数不一致，请改用重编码模式")
    finally:
        list_file.unlink(missing_ok=True)


def _run_reencode(task, paths, output, items, analysis):
    """重编码拼接：统一分辨率/帧率/音频参数后 concat filter"""
    target = analysis["target"]
    w, h = target["width"], target["height"]
    fps = target["fps"] or 25.0
    total = target["duration_total"]

    inputs = []          # ffmpeg -i 参数（按输入序号顺序追加）
    filter_parts = []
    concat_pairs = []
    idx = 0              # 下一个可用的输入序号

    for i, p in enumerate(paths):
        it = items[i]
        vlabel = f"v{i}"
        alabel = f"a{i}"
        inputs += ["-i", str(p)]
        filter_parts.append(
            f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}[{vlabel}]"
        )

        if it.get("acodec"):
            filter_parts.append(
                f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo[{alabel}]"
            )
            concat_pairs.append((vlabel, alabel))
            idx += 1
        else:
            # 无音轨：追加一个 lavfi 静音输入，序号为 idx+1
            null_idx = idx + 1
            inputs += ["-f", "lavfi", "-t", str(it["duration"] or 1),
                       "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            filter_parts.append(f"[{null_idx}:a]aresample=async=1[{alabel}]")
            concat_pairs.append((vlabel, alabel))
            idx += 2
    n = len(paths)
    pairs = "".join(f"[{v}][{a}]" for v, a in concat_pairs)
    filter_parts.append(f"{pairs}concat=n={n}:v=1:a=1[outv][outa]")
    filter_complex = ";".join(filter_parts)

    task.message = f"重编码拼接 {n} 个视频（统一 {w}x{h}@{fps}）"
    cmd = (
        [FFMPEG, "-y", "-v", "error", "-progress", "pipe:1"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output),
        ]
    )
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    code = _pump_output(task, proc, total)
    if code != 0:
        raise RuntimeError(f"ffmpeg 退出码 {code}，详见日志")


# ── 路径打开（本地图像目录定位） ─────────────────────

def reveal_in_explorer(file_path: str) -> bool:
    p = Path(file_path)
    if not p.exists():
        return False
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)], creationflags=_NO_WINDOW)
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])
    return True
