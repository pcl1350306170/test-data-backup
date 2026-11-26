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
from mutagen.apev2 import APEv2, APEBinaryValue, BINARY as _APE_BINARY
from mutagen.flac import FLAC, Picture
from mutagen.asf import ASF, ASFUnicodeAttribute, ASFByteArrayAttribute

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


# ---------- APE（Monkey's Audio / APEv2 标签） ----------

APE_COVER_KEY = "Cover Art (Front)"


def _sniff_image_mime(data):
    """APE 不存 mime，按图片魔数判断（仅 jpeg/png）"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


class ApeAdapter(BaseAdapter):
    exts = (".ape",)
    supports_bg = False     # APE 只有封面(Cover Art (Front))，无背景图概念

    # 统一字段 -> APEv2 项名
    _ITEMS = (("title", "Title"), ("artist", "Artist"),
              ("album", "Album"), ("date", "Year"),
              ("comment", "Comment"))

    def read_info(self, path):
        info = {"title": "", "artist": "", "album": "",
                "date": "", "comment": "", "track": "",
                "cover": None, "bg": None}
        try:
            tag = APEv2(str(path))
        except Exception:
            return info
        for key, item in self._ITEMS:
            v = tag.get(item)
            if v is not None:
                info[key] = str(v).strip()
        trk = tag.get("Track")
        if trk is not None:
            info["track"] = str(trk).strip()      # APE Track 就是 "n/N" 字符串
        cv = tag.get(APE_COVER_KEY)
        if cv is not None:
            raw = bytes(cv)
            data = raw.split(b"\x00", 1)[1] if b"\x00" in raw else raw
            if data:
                info["cover"] = {"data": data, "mime": _sniff_image_mime(data),
                                 "desc": "", "type": PT_FRONT_COVER}
        return info     # bg 恒为 None

    def write_tags(self, tmp_path, meta, cover_op, bg_op):
        try:
            tag = APEv2(str(tmp_path))
        except Exception:
            tag = APEv2()      # 无标签（或不可解析）: 新建空标签，save 时追加页脚
        for key, item in self._ITEMS:
            if key not in meta:
                continue
            val = (meta[key] or "").strip()
            if val:
                tag[item] = val
            else:
                tag.pop(item, None)
        if "track" in meta:
            val = (meta["track"] or "").strip()
            if val:
                tag["Track"] = val
            else:
                tag.pop("Track", None)
        # 封面：写为 "文件名\x00 + 图片字节”的二进制项；bg_op 忽略
        if cover_op is not None:
            if cover_op[0] == "data":
                _, data, mime = cover_op
                ext = "png" if (mime or "").lower() == "image/png" else "jpg"
                tag[APE_COVER_KEY] = APEBinaryValue(
                    ("cover." + ext).encode() + b"\x00" + data, _APE_BINARY)
            else:
                tag.pop(APE_COVER_KEY, None)
        tag.save(str(tmp_path))


# ---------- FLAC（Vorbis Comment + Picture 块） ----------

class FlacAdapter(BaseAdapter):
    exts = (".flac",)
    supports_bg = False     # FLAC 的 Picture 只有类型语义，无“播放背景图”概念

    # 统一字段 -> Vorbis Comment 项名
    _ITEMS = (("title", "title"), ("artist", "artist"),
              ("album", "album"), ("date", "date"),
              ("comment", "comment"), ("track", "tracknumber"))

    def read_info(self, path):
        info = {"title": "", "artist": "", "album": "",
                "date": "", "comment": "", "track": "",
                "cover": None, "bg": None}
        try:
            flac = FLAC(str(path))
        except Exception:
            return info
        for key, field in self._ITEMS:
            vals = flac.get(field)
            if vals:
                info[key] = str(vals[0]).strip()
        for pic in flac.pictures:
            if pic.type == PT_FRONT_COVER and info["cover"] is None:
                info["cover"] = {"data": pic.data, "mime": pic.mime or "image/jpeg",
                                 "desc": pic.desc or "", "type": pic.type}
        return info     # bg 恒为 None

    def write_tags(self, tmp_path, meta, cover_op, bg_op):
        flac = FLAC(str(tmp_path))
        for key, field in self._ITEMS:
            if key not in meta:
                continue
            val = (meta[key] or "").strip()
            if val:
                flac[field] = val
            else:
                try:
                    if field in flac:       # tagless/无该项时跳过，避免 None 上删除
                        del flac[field]
                except (KeyError, AttributeError):
                    pass
        # 封面：type=3 的唯一槽位；其余类型图片原样保留；bg_op 忽略
        if cover_op is not None:
            kept = [p for p in flac.pictures if p.type != PT_FRONT_COVER]
            front = None
            if cover_op[0] == "data":
                _, data, mime = cover_op
                front = Picture()
                front.type = PT_FRONT_COVER
                front.mime = mime or "image/jpeg"
                front.data = data
            flac.clear_pictures()
            for p in kept + ([front] if front else []):
                flac.add_picture(p)
        flac.save()


# ---------- WMA（ASF 容器 / 扩展属性） ----------

class WmaAdapter(BaseAdapter):
    exts = (".wma",)
    supports_bg = False     # ASF 只有一个 WM/Picture 槽位，无背景图概念

    # 统一字段 -> ASF 属性名（列表形式，主键与 WM/ 别名同时写）
    _ITEMS = (("title", ("Title", "WM/Title")),
              ("artist", ("Artist", "WM/Artist")),
              ("album", ("Album", "WM/AlbumTitle")),
              ("date", ("Year", "WM/Year")),
              ("comment", ("Comment", "WM/Comments")),
              ("track", ("Track", "WM/TrackNumber")))

    @staticmethod
    def _pic_parse(raw):
        """WM/Picture 字节 -> (mime, data)：flags(1)+mime UTF-16LE(逐双字节直到空、终止)+len(4LE)+data
        注：UTF-16LE 每个 ASCII 高位字节均为 00，不能直接找 b"\\x00\\x00" 子串，必须按双字节对齐"""
        try:
            i = 1
            units = []
            while i + 1 < len(raw):
                u = raw[i] | (raw[i + 1] << 8)
                if u == 0:
                    break
                units.append(u)
                i += 2
            mime = "".join(chr(u) for u in units)
            off = i + 2                       # 跳过 2 字节终止符
            length = int.from_bytes(raw[off:off + 4], "little")
            data = raw[off + 4:off + 4 + length]
            return (mime or "image/jpeg"), data
        except Exception:
            return "image/jpeg", raw

    def read_info(self, path):
        info = {"title": "", "artist": "", "album": "",
                "date": "", "comment": "", "track": "",
                "cover": None, "bg": None}
        try:
            audio = ASF(str(path))
        except Exception:
            return info
        tags = audio.tags or {}
        for key, names in self._ITEMS:
            for name in names:
                vals = tags.get(name)
                if vals and str(vals[0]).strip():
                    info[key] = str(vals[0]).strip()
                    break
        pics = tags.get("WM/Picture")
        if pics:
            mime, data = self._pic_parse(bytes(pics[0]))
            if data:
                info["cover"] = {"data": data, "mime": mime or "image/jpeg",
                                 "desc": "", "type": PT_FRONT_COVER}
        return info     # bg 恒为 None

    def write_tags(self, tmp_path, meta, cover_op, bg_op):
        audio = ASF(str(tmp_path))
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        for key, names in self._ITEMS:
            if key not in meta:
                continue
            val = (meta[key] or "").strip()
            for name in names:
                if val:
                    tags[name] = [ASFUnicodeAttribute(val)]
                elif name in tags:
                    del tags[name]
        # 封面：写 WM/Picture（flags=3 FrontCover + UTF-16 mime + 长度 + 数据）；bg_op 忽略
        if cover_op is not None:
            if cover_op[0] == "data":
                _, data, mime = cover_op
                mime = mime or "image/jpeg"
                raw = (bytes([PT_FRONT_COVER])
                       + mime.encode("utf-16-le") + b"\x00\x00"
                       + len(data).to_bytes(4, "little") + data)
                tags["WM/Picture"] = [ASFByteArrayAttribute(raw)]
            elif "WM/Picture" in tags:
                del tags["WM/Picture"]
        audio.save()


# ---------- 注册表：扩展名 -> 适配器 ----------
_ADAPTERS = {}
for _cls in (Mp3Adapter, Mp4Adapter, ApeAdapter, FlacAdapter, WmaAdapter):
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