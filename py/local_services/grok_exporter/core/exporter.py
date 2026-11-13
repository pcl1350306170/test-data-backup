# -*- coding: utf-8 -*-
"""导出编排：文件命名、目录准备、单会话/合并、取消、进度回调。"""
import json
import threading
from pathlib import Path

from . import markdown_exporter as md
from . import txt_exporter as tx
from .utils import safe_filename, date_prefix


DEFAULT_EXPORT_DIRNAME = "Grok_Export"


def default_output_dir(json_path: str | Path) -> Path:
    return Path(json_path).parent / DEFAULT_EXPORT_DIRNAME


def _unique_path(out_dir: Path, base: str, ext: str) -> Path:
    """重名追加 _01/_02，避免覆盖用户已有文件。"""
    candidate = out_dir / f"{base}.{ext}"
    if not candidate.exists():
        return candidate
    for n in range(1, 10000):
        cand = out_dir / f"{base}_{n:02d}.{ext}"
        if not cand.exists():
            return cand
    raise RuntimeError(f"重名文件过多，无法生成 {base} 的唯一文件名")


def _build_base_name(session: dict) -> str:
    """日期前缀_标题"""
    date = date_prefix(session.get("create_time_raw"))
    title = safe_filename(session.get("title"), max_len=80)
    return f"{date}_{title}"


def _write_text(path: Path, text: str) -> None:
    """UTF-8 无 BOM 写入。"""
    path.write_text(text, encoding="utf-8")


class ExportOptions:
    def __init__(self, raw: dict):
        self.formats = [f.lower() for f in (raw.get("formats") or ["md"])]
        self.scope = raw.get("scope", "all")  # all / grok / user
        self.organization = raw.get("organization", "individual")  # individual / merged / both
        self.output_dir = raw.get("output_dir")
        # 渲染选项
        self.render = {
            "title": bool(raw.get("include_title", True)),
            "time_meta": bool(raw.get("include_time_meta", True)),
            "sender_label": bool(raw.get("include_sender_label", True)),
            "timestamp": bool(raw.get("include_timestamp", True)),
            "separator": bool(raw.get("include_separator", True)),
            "preserve_markdown": bool(raw.get("preserve_markdown", True)),
            "scope": self.scope,
        }

    def want(self, fmt: str) -> bool:
        return fmt in self.formats


class ExportResult:
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.cancelled = 0
        self.files = []   # 绝对路径列表
        self.errors = []  # [{title, error}]


def run_export(sessions: list, opts: ExportOptions,
               progress_cb=None, cancel_event: threading.Event | None = None) -> ExportResult:
    """批量导出。粒度=会话级：每条会话写完才检查 cancel_event。

    sessions 是 conversation_parser.parse_all 的返回。
    progress_cb(event_dict) 用于推送 {stage, current, total, title, ok, error, file}
    """
    result = ExportResult()

    # 输出目录
    out_dir = Path(opts.output_dir) if opts.output_dir else None
    if out_dir is None:
        raise ValueError("未指定导出目录")
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(sessions)
    individual = opts.organization in ("individual", "both")
    merge = opts.organization in ("merged", "both")
    merged_md_blocks = []
    merged_txt_blocks = []

    def emit(ev):
        if progress_cb:
            try:
                progress_cb(ev)
            except Exception:
                pass

    for i, sess in enumerate(sessions, 1):
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = total - i + 1
            emit({"stage": "cancelled", "current": i - 1, "total": total,
                  "title": sess["title"]})
            break

        emit({"stage": "processing", "current": i, "total": total,
              "title": sess["title"]})

        try:
            base = _build_base_name(sess)

            if individual:
                if "md" in opts.formats:
                    text = md.render_conversation_md(sess, opts.render)
                    if merge:
                        merged_md_blocks.append(text)
                    path = _unique_path(out_dir, base, "md")
                    _write_text(path, text)
                    result.files.append(str(path))

                if "txt" in opts.formats:
                    text = tx.render_conversation_txt(sess, opts.render)
                    if merge:
                        merged_txt_blocks.append(text)
                    path = _unique_path(out_dir, base, "txt")
                    _write_text(path, text)
                    result.files.append(str(path))
            else:
                # 仅合并模式：先生成块，不落单独文件
                if "md" in opts.formats:
                    merged_md_blocks.append(md.render_conversation_md(sess, opts.render))
                if "txt" in opts.formats:
                    merged_txt_blocks.append(tx.render_conversation_txt(sess, opts.render))

            result.success += 1
            emit({"stage": "ok", "current": i, "total": total,
                  "title": sess["title"]})
        except Exception as exc:
            result.failed += 1
            err = f"{type(exc).__name__}: {exc}"
            result.errors.append({"title": sess["title"], "error": err})
            emit({"stage": "error", "current": i, "total": total,
                  "title": sess["title"], "error": err})

    # 合并文件
    if merge:
        if "md" in opts.formats and merged_md_blocks:
            try:
                text = "\n\n\n".join(merged_md_blocks).rstrip() + "\n"
                path = _unique_path(out_dir, "全部Grok会话", "md")
                _write_text(path, text)
                result.files.append(str(path))
            except Exception as exc:
                result.errors.append({"title": "(合并 MD)", "error": str(exc)})
        if "txt" in opts.formats and merged_txt_blocks:
            try:
                text = "\n\n".join(merged_txt_blocks).rstrip() + "\n"
                path = _unique_path(out_dir, "全部Grok会话", "txt")
                _write_text(path, text)
                result.files.append(str(path))
            except Exception as exc:
                result.errors.append({"title": "(合并 TXT)", "error": str(exc)})

    emit({"stage": "done", "current": total, "total": total,
          "success": result.success, "failed": result.failed,
          "cancelled": result.cancelled, "files": len(result.files)})
    return result
