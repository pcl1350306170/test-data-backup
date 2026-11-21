# -*- coding: utf-8 -*-
"""格式适配器层：按扩展名分派，屏蔽不同音频标签体系差异。

统一约定（与引擎层对接）：
  read_info(path) -> dict(title, artist, album, date, comment, track, cover, bg)
      cover/bg 为 None 或 {"data": bytes, "mime": str, "desc": str, "type": int}
  write_tags(tmp_path, meta, cover_op, bg_op)
      meta 只含“要修改”的键；值可为空串=删帧；未出现的键保持原样。
      cover_op/bg_op 取值：None=保留 / ("delete",)=删除 / ("data", bytes, mime)=替换。

新增格式（如 M4A）只需：实现一个 BaseAdapter 子类，注册到 _ADAPTERS 即可，
引擎层与前端无需改动。
"""
from pathlib import Path

from mutagen.id3 import (ID3, ID3NoHeaderError, APIC,
                         TALB, TIT2, TPE1, TRCK, TYER, TXXX)
from mutagen.mp4 import MP4, MP4Cover

# ID3 图片类型与描述（与音频合并工具 ffmpeg 写入的值一一对应）
PT_OTHER = 0            # APIC type 0x00 Other      <- 背景图
PT_FRONT_COVER = 3      # APIC type 0x03 FrontCover <- 封面
COVER_DESC = "Album cover"
BG_DESC = "Background"


class UnsupportedFormat(Exception):
    """扩展名不在支持列表内"""


class BaseAdapter:
    """格式适配器接口"""
    exts = ()
    supports_bg = True      # 是否支持背景图（m4a 仅封面，置 False）

    def read_info(self, path):
        raise NotImplementedError

    def write_tags(self, tmp_path, meta, cover_op, bg_op):
        raise NotImplementedError


def _make_apic(data, mime, ptype, desc):
    """构造 APIC 帧（兼容 mutagen 新旧参数名 desc/description）"""
    try:
        return APIC(encoding=3, mime=mime, type=ptype, data=data, desc=desc)
    except TypeError:
        return APIC(encoding=3, mime=mime, type=ptype, data=data, description=desc)


def _classify_apic(frame):
    """把 APIC 帧归类为 cover / bg（与合并工具写入的 desc、type 对应）"""
    desc = (frame.desc or "").lower()
    if "background" in desc:
        return "bg"
    if getattr(frame, "type", None) == PT_OTHER:
        return "bg"
    return "cover"


class Mp3Adapter(BaseAdapter):
    """MP3 / ID3v2.3 适配器"""
    exts = (".mp3",)

    def read_info(self, path):
        info = {"title": "", "artist": "", "album": "", "date": "",
                "comment": "", "track": "", "cover": None, "bg": None}
        try:
            id3 = ID3(str(path))
        except ID3NoHeaderError:
            return info
        except Exception:
            return info

        def _text(*frame_ids):
            for fid in frame_ids:
                f = id3.get(fid)
                if f is not None and str(f).strip():
                    return str(f).strip()
            return ""

        info["title"] = _text("TIT2")
        info["artist"] = _text("TPE1")
        info["album"] = _text("TALB")
        info["date"] = _text("TDRC", "TYER")       # ffmpeg 实际写 TDRC，回退 TYER
        info["track"] = _text("TRCK")
        # 备注：合并工具（ffmpeg）把 comment 写成 TXXX:comment，其次才是标准 COMM 帧
        txxx = id3.get("TXXX:comment")
        if txxx is not None and str(txxx).strip():
            info["comment"] = str(txxx).strip()
        else:
            for c in id3.getall("COMM"):
                if c.text:
                    info["comment"] = str(c.text).strip()
                    break
        for apic in id3.getall("APIC"):
            kind = _classify_apic(apic)
            if info[kind] is None:
                info[kind] = {"data": apic.data, "mime": apic.mime,
                              "desc": apic.desc or "", "type": apic.type}
        return info

    def _apply_text_frames(self, id3, meta):
        """按 meta 中出现的键写入文本帧（值可为空串=删帧）；未出现的键保持原样"""
        table = (("title", "TIT2", TIT2), ("artist", "TPE1", TPE1),
                 ("album", "TALB", TALB), ("date", "TYER", TYER),
                 ("track", "TRCK", TRCK))
        for key, fid, cls in table:
            if key not in meta:
                continue
            id3.delall(fid)
            if key == "date":
                id3.delall("TDRC")                 # TDRC/TYER 两帧都清，统一写 TYER
            val = (meta[key] or "").strip()
            if val:
                id3.add(cls(encoding=3, text=val))
        if "comment" in meta:
            # 与 ffmpeg 保持一致：写 TXXX:comment，同时清掉标准 COMM 帧避免残留
            id3.delall("TXXX")
            id3.delall("COMM")
            val = (meta["comment"] or "").strip()
            if val:
                id3.add(TXXX(encoding=3, desc="comment", text=val))

    def _rebuild_images(self, id3, cover_op, bg_op):
        """重建两张图片帧。op：None=保留 / ("delete",)=删除 / ("data",b,m)=替换"""
        keep = {"cover": None, "bg": None}
        for apic in id3.getall("APIC"):
            kind = _classify_apic(apic)
            if keep[kind] is None:
                keep[kind] = {"data": apic.data, "mime": apic.mime,
                              "desc": apic.desc or "", "type": apic.type}
        id3.delall("APIC")

        def _final(kind, op):
            if op is None:
                return keep[kind]
            if op[0] == "delete":
                return None
            _tag, data, mime = op
            if kind == "cover":
                return {"data": data, "mime": mime, "desc": COVER_DESC, "type": PT_FRONT_COVER}
            return {"data": data, "mime": mime, "desc": BG_DESC, "type": PT_OTHER}

        for kind, op in (("cover", cover_op), ("bg", bg_op)):
            spec = _final(kind, op)
            if spec:
                id3.add(_make_apic(spec["data"], spec["mime"], spec["type"], spec["desc"]))

    def write_tags(self, tmp_path, meta, cover_op, bg_op):
        try:
            id3 = ID3(str(tmp_path))
        except ID3NoHeaderError:
            id3 = ID3()
        self._apply_text_frames(id3, meta)
        self._rebuild_images(id3, cover_op, bg_op)
        id3.save(str(tmp_path), v2_version=3)


# ---------- M4A（iTunes MP4 原子） ----------

class Mp4Adapter(BaseAdapter):
    exts = (".m4a",)
    supports_bg = False     # m4a 标准只有封面 covr，无背景图概念

    # 统一字段 -> iTunes 原子
    _ATOMS = (("title", "\xa9nam"), ("artist", "\xa9ART"),
              ("album", "\xa9alb"), ("date", "\xa9day"),
              ("comment", "\xa9cmt"))

    def read_info(self, path):
        info = {"title": "", "artist": "", "album": "",
                "date": "", "comment": "", "track": "",
                "cover": None, "bg": None}
        try:
            audio = MP4(str(path))
        except Exception:
            return info
        tags = audio.tags or {}

        def _first(atom):
            v = tags.get(atom)
            return str(v[0]).strip() if v else ""

        for key, atom in self._ATOMS:
            info[key] = _first(atom)
        trkn = tags.get("trkn")
        if trkn:
            n, total = trkn[0]
            info["track"] = "%d/%d" % (n, total) if total else str(n)
        covr = tags.get("covr")
        if covr:
            c = covr[0]
            mime = ("image/png" if getattr(c, "imageformat", None) == MP4Cover.FORMAT_PNG
                    else "image/jpeg")
            info["cover"] = {"data": bytes(c), "mime": mime,
                             "desc": "", "type": PT_FRONT_COVER}
        return info     # bg 恒为 None

    @staticmethod
    def _parse_track(val):
        """"n/N" 或 "n" -> (n, total) 元组；非法抛 ValueError"""
        val = val.strip()
        if "/" in val:
            n, _, total = val.partition("/")
            return int(n.strip()), int(total.strip()) if total.strip() else 0
        return int(val), 0

    def write_tags(self, tmp_path, meta, cover_op, bg_op):
        audio = MP4(str(tmp_path))
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        for key, atom in self._ATOMS:
            if key not in meta:
                continue
            val = (meta[key] or "").strip()
            if val:
                tags[atom] = [val]
            else:
                tags.pop(atom, None)
        if "track" in meta:
            val = (meta["track"] or "").strip()
            if val:
                tags["trkn"] = [self._parse_track(val)]
            else:
                tags.pop("trkn", None)
        # 封面：covr 列表整体视为封面槽（m4a 仅封面）；bg_op 忽略
        if cover_op is not None:
            if cover_op[0] == "data":
                _, data, mime = cover_op
                fmt = (MP4Cover.FORMAT_PNG if (mime or "").lower() == "image/png"
                       else MP4Cover.FORMAT_JPEG)
                tags["covr"] = [MP4Cover(data, imageformat=fmt)]
            else:
                tags.pop("covr", None)
        audio.save()


# ---------- 注册表：扩展名 -> 适配器 ----------
_ADAPTERS = {}
for _cls in (Mp3Adapter, Mp4Adapter):
    _inst = _cls()
    for _ext in _cls.exts:
        _ADAPTERS[_ext] = _inst

SUPPORTED_EXTS = tuple(_ADAPTERS.keys())


def get_adapter(path):
    """按扩展名取适配器；不支持则抛 UnsupportedFormat"""
    ext = Path(path).suffix.lower()
    adapter = _ADAPTERS.get(ext)
    if adapter is None:
        raise UnsupportedFormat("暂不支持的格式: %s（当前支持 %s）"
                                % (ext or "无扩展名", "/".join(SUPPORTED_EXTS)))
    return adapter