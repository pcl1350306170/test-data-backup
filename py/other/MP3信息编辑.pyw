# -*- coding: utf-8 -*-
"""
MP3 信息编辑（GUI）
==================
功能：
  1. 单文件精修：读取/编辑 ID3 标签（标题、作者、专辑、日期、备注、音轨），
     预览、替换、删除、导出【封面图】与【播放背景图】
  2. 批量处理：目录内全部 MP3 统一套用作者/专辑/日期/备注/封面/背景图（留空 = 不修改），
     标题 = 前缀 + 前导零序号（与音频合并工具规则一致），音轨自动写 n/N
  3. 只改标签不动音频数据（无损、不重新编码）；保存前自动备份原文件到
     源目录下的 _backup_标签编辑\\ 子目录（同名覆盖，只留最近一份）
  4. 可选开关：标题修改后同步重命名文件（默认关闭）
  5. 批量时单文件失败不中断整批，失败明细写『标签编辑失败清单.txt』
  6. 随机头像：选图对话框默认从「头像目录」预选一张随机图；批量可勾选
     随机封面/随机背景，每个文件独立随机一张（完全随机）
  7. 多文件精修：文件名清洗成标题（去标点/英文/开头序号、繁转简），
     逐行编辑后一键保存，默认按标题重命名文件

运行方式：
  双击运行（.pyw 不弹控制台），进度和结果显示在“日志”页

依赖：
  pip install mutagen        （纯 Python 读写 ID3，无需 ffmpeg）
"""

import json
import os
import queue
import random
import re
import shutil
import sys
import threading
import time
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "mp3_tag_editor"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# ---------- 日志（可选依赖） ----------
_PY_DIR = str(SCRIPT_DIR.parent)          # 指向 py/ 目录
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()

# ---------- mutagen 依赖探测 ----------
try:
    from mutagen.id3 import (ID3, ID3NoHeaderError, APIC, COMM,
                             TALB, TIT2, TPE1, TRCK, TYER, TXXX)
    HAVE_MUTAGEN = True
except Exception:
    HAVE_MUTAGEN = False

# ---------- 可选依赖：PIL（仅用于图片预览缩略） ----------
try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    Image = None
    HAVE_PIL = False

# ---------- 可选依赖：zhconv（繁转简，多文件精修标题清洗用） ----------
try:
    import zhconv
    HAVE_ZHCONV = True
except Exception:
    zhconv = None
    HAVE_ZHCONV = False

# ---------- 默认配置（每个键一行注释） ----------
DEFAULT_CONFIG = {
    "input_dir": r"D:\AUDIO\mp3",       # MP3 所在目录（批量处理对象）
    "batch_title_prefix": "",           # 批量标题前缀，留空 = 不修改标题
    "batch_start_num": "1",             # 起始序号，前导零决定宽度（055 -> 三位，与合并工具一致）
    "batch_artist": "",                 # 批量作者，留空 = 不修改
    "batch_album": "",                  # 批量专辑，留空 = 不修改
    "batch_date": "",                   # 批量日期（年份），留空 = 不修改
    "batch_comment": "",                # 批量备注，留空 = 不修改
    "batch_cover_path": "",             # 批量封面图路径，留空 = 不修改
    "batch_bg_image_path": "",          # 批量播放背景图路径，留空 = 不修改
    "avatar_dir": r"D:\CODE\Miscellaneous\GPT-IMG\头像",  # 随机头像目录（选图预选/批量随机共用）
    "batch_random_cover": False,        # 批量随机封面：每个文件独立随机一张（勾选后忽略固定封面路径）
    "batch_random_bg": False,           # 批量随机背景图：每个文件独立随机一张（勾选后忽略固定背景路径）
    "fine_t2s": True,                   # 多文件精修：标题清洗时繁转简（需 zhconv）
    "fine_rename": True,                # 多文件精修：保存后默认按标题重命名文件
    "clean_filter_words": "",           # 标题清洗过滤词（逗号分隔，如网站名水印），空 = 不启用
    "fine_artist": "",                  # 多文件精修：通用作者，留空 = 不修改
    "fine_album": "",                   # 多文件精修：通用专辑，留空 = 不修改
    "fine_date": "",                    # 多文件精修：通用日期（年份），留空 = 不修改
    "fine_comment": "",                 # 多文件精修：通用备注，留空 = 不修改
    "fine_random_cover": False,         # 多文件精修：随机封面（头像目录，每首不同）
    "fine_random_bg": False,            # 多文件精修：随机背景图（头像目录，每首不同）
    "sync_rename": False,               # 标题修改后同步重命名文件（默认关闭）
}

# 备份子目录名 / 失败清单文件名
BACKUP_SUBDIR = "_backup_标签编辑"
FAIL_LIST_NAME = "标签编辑失败清单.txt"

# ID3 图片类型与描述（与音频合并工具 ffmpeg 写入的值一一对应）
PT_OTHER = 0            # APIC type 0x00 Other          <- ffmpeg comment=Other（背景图）
PT_FRONT_COVER = 3      # APIC type 0x03 FrontCover     <- ffmpeg comment=Cover (front)（封面）
COVER_DESC = "Album cover"
BG_DESC = "Background"

# 头像目录扫描的图片扩展名（与选图框过滤一致）
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

# 「说明」页正文
TUTORIAL = """
【一、pip 安装命令】

  pip install mutagen zhconv

  国内网络较慢时可用镜像：
  pip install mutagen zhconv -i https://pypi.tuna.tsinghua.edu.cn/simple

  注意：包名是 mutagen（变形虫），不要装成 mutate / mutation 等同名近似库。
  zhconv 仅用于多文件精修的繁转简，未安装时该功能降级为保留繁体。
  验证安装：python -c "import mutagen; print(mutagen.version_string)"

【二、外部依赖（Windows）】

  本工具是纯 Python 读写 ID3 标签，不需要 ffmpeg。
  图片预览需要 Pillow（pip install pillow），没有也能用，只是不显示缩略图。

【三、使用说明】

  1. “文件”页选择 MP3 目录并“刷新列表”，列表显示每个文件的当前标题/作者，
     便于核对音频合并工具写错的信息。
  2. 单文件精修：在列表中点选一个 MP3，下方编辑区自动载入现有标签与图片；
     改完点“保存当前文件”。封面/背景图可 更换、删除、导出。
  3. 多文件精修：在“多文件精修”页点“加载列表”，每行显示 原文件名 -> 清洗后标题，
     标题可逐行手改（红色=清洗为空已回退原文件名，橙色=标题重复）；清洗规则：
     去开头序号、只留中文+数字、繁转简（可关）、可配过滤词。页内可设通用作者/专辑/
     日期/备注（留空=不改），可选随机封面/背景图（头像目录，每首不同）；
     音轨自动 n/N；保存后默认按标题重命名文件。
  4. 批量处理：在“参数”页填好要统一套用的信息（留空 = 不修改该项），
     底部点“开始批量应用”。标题 = 前缀 + 序号（起始序号 055 表示三位补零，
     与音频合并工具规则一致），音轨自动写 序号/总数。
  5. 随机头像：所有选图对话框默认从「头像目录」预选一张随机图（双击即选中，
     也可换选别的文件）；批量页勾选“随机封面/随机背景”后，每个文件从该目录
     独立随机一张（完全随机，可能重复），勾选时忽略左侧固定图片路径。
  6. 保存前自动把原文件备份到 源目录\\_backup_标签编辑\\（同名覆盖，只留最近一份），
     改错了可从备份恢复。确认无误后，可用“文件”页目录栏的“清理备份”一键删除该备份文件夹。
  7. “标题修改后同步重命名文件”默认关闭（仅批量模式）；勾选后文件名随标题变化
     （非法字符自动过滤，目标重名则跳过重命名只改标签）。
  8. 只修改 ID3 标签，不重新编码音频，音质零损失；批量中单个文件失败只记警告
     不中断，结尾汇总并写『标签编辑失败清单.txt』，本轮无失败会自动删除旧清单。
  9. 所有设置都会记住（json/config_mp3_tag_editor.json），下次打开自动回填。

【四、参数微调（“参数”页，键名对应配置）】

    batch_title_prefix      批量标题前缀；留空则不动标题
    batch_start_num         起始序号；前导零决定补零宽度（1 -> 055 三位从 55 起）
    batch_artist/album      作者/专辑；留空 = 不修改
    batch_date              年份，如 2026；留空 = 不修改
    batch_comment           备注；留空 = 不修改
    batch_cover_path        封面图（jpg/png），写入 APIC type=Front Cover；留空 = 不动封面
    batch_bg_image_path     播放背景图，写入 APIC type=Other；留空 = 不动背景图
    avatar_dir              随机头像目录；选图框随机预选与批量随机都取自此目录
    batch_random_cover      批量随机封面（true/false）：勾选后每个文件独立随机一张
    batch_random_bg         批量随机背景图（true/false）：同上
    fine_t2s                多文件精修：标题清洗繁转简（默认开，需 zhconv）
    fine_rename             多文件精修：保存后按标题重命名文件（默认开）
    clean_filter_words      标题清洗过滤词，逗号分隔（如网站名水印），空 = 不启用
    fine_artist/album       精修通用作者/专辑；留空 = 不修改
    fine_date/comment       精修通用日期/备注；留空 = 不修改
    fine_random_cover/bg    精修随机封面/背景图（true/false）：每首独立随机一张
    sync_rename             标题修改后同步重命名文件（默认关闭，仅批量模式）

【五、提醒】

  · 批量目录里放什么处理什么：目录下所有 .mp3（含合并工具输出和其它来源）都会被套用。
  · 备份目录与 MP3 同级，整个目录拷走/删除时注意一起处理。
  · 写标签为 ID3v2.3（与音频合并工具输出版本一致），车载音响/老播放器兼容性更好。
  · 图片会被内嵌进 MP3，单张建议控制在 1MB 以内，避免文件明显变大。
"""


# ================== 环境检查 ==================

def check_mutagen():
    """mutagen 是否可用；缺失时所有读写都无法进行。"""
    return HAVE_MUTAGEN


# ================== 纯函数区（不碰界面） ==================

def _sanitize_filename(name):
    """去除文件名中系统不允许的字符（与音频合并工具一致）"""
    invalid = '<>:"/\\|?*\x00'
    return "".join(c for c in name if c not in invalid).strip()


def _short_err(err, limit=300):
    """异常信息压成一行简短描述，避免刷屏日志与失败清单"""
    text = " ".join(str(err).split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…（已截断，共 %d 字）" % len(text)


def sniff_image_mime(data):
    """按文件头魔数判断图片 MIME；MP3 封面兼容性最好的是 JPEG，兜底按 JPEG 处理"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


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


def read_media_info(path):
    """
    读取 MP3 的标签与内嵌图片。
    :return: dict(title, artist, album, date, comment, track, cover, bg)
             cover/bg 为 None 或 {"data","mime","desc","type"}
    """
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


def _apply_text_frames(id3, meta):
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


def _rebuild_images(id3, cover_op, bg_op):
    """
    重建两张图片帧。op 取值：
      None            -> 保留原有帧（沿用原 desc/type）
      ("delete",)     -> 删除
      ("data", b, m)  -> 用新数据替换（写合并工具的规范 desc/type）
    """
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


def apply_edits(src_path, meta, cover_op=None, bg_op=None,
                rename_title=None, backup=True):
    """
    编辑单个 MP3：备份 → 副本写标签 → 原子替换 → 可选重命名。
    :param meta: 只包含“要修改”的键（title/artist/album/date/comment/track）
    :return: (最终路径 Path, 提示语列表)
    """
    src = Path(src_path)
    notes = []

    if backup:
        bak_dir = src.parent / BACKUP_SUBDIR
        bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, bak_dir / src.name)
        notes.append("已备份 %s" % (bak_dir.name + "\\" + src.name))

    tmp = src.parent / (src.name + ".tmp")
    try:
        shutil.copy2(src, tmp)
        try:
            id3 = ID3(str(tmp))
        except ID3NoHeaderError:
            id3 = ID3()
        _apply_text_frames(id3, meta)
        _rebuild_images(id3, cover_op, bg_op)
        id3.save(str(tmp), v2_version=3)
        os.replace(str(tmp), str(src))
    finally:
        if tmp.exists():
            try:
                os.unlink(str(tmp))
            except OSError:
                pass

    final = src
    if rename_title:
        safe = _sanitize_filename(rename_title)
        if safe and safe.lower() != src.stem.lower():
            dst = src.parent / (safe + ".mp3")
            if dst.exists():
                notes.append("重命名跳过（目标已存在）: %s" % dst.name)
            else:
                os.rename(str(src), str(dst))
                final = dst
                notes.append("已重命名: %s" % dst.name)
    return final, notes


def batch_title_for(prefix, start, width, idx):
    """批量标题：前缀 + 补零序号（与音频合并工具的序号规则一致）"""
    if not prefix:
        return None
    return "%s%0*d" % (prefix, width, start + idx - 1)


# 开头序号模式：055_ / 01. / 第01集 等（音轨号由 n/N 单独写）
_LEADING_NUM_RE = re.compile(r"^(?:第\s*)?\d+\s*[集章回节期]?\s*[\s._\-、．:：]*")


def clean_title_from_filename(stem, t2s=True, filter_words=""):
    """文件名 -> 候选标题：繁转简 -> 过滤词 -> 去开头序号 -> 只保留中文+数字
    返回空串表示清洗后无内容，由调用方决定兜底策略"""
    s = stem
    if t2s and HAVE_ZHCONV:
        s = zhconv.convert(s, "zh-cn")
    for w in filter_words.replace("，", ",").split(","):
        w = w.strip()
        if w:
            s = s.replace(w, "")
    while True:
        s2 = _LEADING_NUM_RE.sub("", s, count=1)
        if s2 == s:
            break
        s = s2
    return "".join(ch for ch in s if "\u4e00" <= ch <= "\u9fff" or ch in "0123456789")


def build_common_meta(cfg, prefix="batch"):
    """通用文本字段（留空 = 不修改）；prefix 区分批量(batch)/精修(fine)"""
    meta = {}
    for key in ("artist", "album", "date", "comment"):
        val = cfg.get(prefix + "_" + key, "")
        if val:
            meta[key] = val
    return meta


def list_avatar_images(avatar_dir):
    """头像目录顶层的候选图片（按名排序；目录无效/无图返回空列表）"""
    try:
        d = Path(avatar_dir)
        if not d.is_dir():
            return []
        return sorted(p for p in d.iterdir()
                      if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    except Exception:
        return []


def pick_random_image(avatar_dir):
    """随机取一张头像图路径（选图对话框预选用）；无候选返回 None"""
    pool = list_avatar_images(avatar_dir)
    return random.choice(pool) if pool else None


def random_image_op(pool, fallback=None):
    """批量随机图片操作：从池随机读一张 -> ("data", bytes, mime)；池空或读取失败回退 fallback"""
    if not pool:
        return fallback
    try:
        data = random.choice(pool).read_bytes()
        return ("data", data, sniff_image_mime(data))
    except Exception:
        return fallback


def cleanup_backups(input_dir):
    """删除 MP3 目录下的 _backup_标签编辑 备份子目录（仅限该固定名称，不做越界删除）
    :return: (删除文件数, 备份目录路径字符串)
    :raises FileNotFoundError: 备份目录不存在时抛出
    """
    bak_dir = Path(input_dir) / BACKUP_SUBDIR
    if not bak_dir.is_dir():
        raise FileNotFoundError("备份目录不存在: %s" % bak_dir)
    count = sum(1 for p in bak_dir.rglob("*") if p.is_file())
    shutil.rmtree(str(bak_dir))
    return count, str(bak_dir)


# ================== GUI 主程序 ==================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("MP3 信息编辑")
        root.geometry("860x720")
        root.minsize(760, 620)
        try:
            root.state("zoomed")
        except Exception:
            pass

        # 线程通信
        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self._stop_event = threading.Event()

        # 当前载入精修的 MP3 路径 与 两张图片的编辑状态
        self._loaded_path = None
        # 图片状态：{"action": keep|set|delete, "data": bytes|None, "mime": str}
        self._cover = {"action": "keep", "data": None, "mime": "image/jpeg"}
        self._bg = {"action": "keep", "data": None, "mime": "image/jpeg"}
        self._cover_photo = None
        self._bg_photo = None
        self._files = []                     # 当前目录的 mp3 路径列表
        self._fine_rows = []                 # 多文件精修行状态列表
        self._fine_dir = None                # 精修列表加载时的目录（防目录变更后误保存）
        self._last_mode = "batch"            # 最近一次任务模式：batch / fine

        # 界面变量（与 DEFAULT_CONFIG 键一一对应）
        self.input_dir_var = tk.StringVar(value=DEFAULT_CONFIG["input_dir"])
        self.batch_title_prefix_var = tk.StringVar(value=DEFAULT_CONFIG["batch_title_prefix"])
        self.batch_start_num_var = tk.StringVar(value=DEFAULT_CONFIG["batch_start_num"])
        self.batch_artist_var = tk.StringVar(value=DEFAULT_CONFIG["batch_artist"])
        self.batch_album_var = tk.StringVar(value=DEFAULT_CONFIG["batch_album"])
        self.batch_date_var = tk.StringVar(value=DEFAULT_CONFIG["batch_date"])
        self.batch_comment_var = tk.StringVar(value=DEFAULT_CONFIG["batch_comment"])
        self.batch_cover_path_var = tk.StringVar(value=DEFAULT_CONFIG["batch_cover_path"])
        self.batch_bg_image_path_var = tk.StringVar(value=DEFAULT_CONFIG["batch_bg_image_path"])
        self.avatar_dir_var = tk.StringVar(value=DEFAULT_CONFIG["avatar_dir"])
        self.batch_random_cover_var = tk.BooleanVar(value=DEFAULT_CONFIG["batch_random_cover"])
        self.batch_random_bg_var = tk.BooleanVar(value=DEFAULT_CONFIG["batch_random_bg"])
        self.fine_t2s_var = tk.BooleanVar(value=DEFAULT_CONFIG["fine_t2s"])
        self.fine_rename_var = tk.BooleanVar(value=DEFAULT_CONFIG["fine_rename"])
        self.clean_filter_words_var = tk.StringVar(value=DEFAULT_CONFIG["clean_filter_words"])
        self.fine_artist_var = tk.StringVar(value=DEFAULT_CONFIG["fine_artist"])
        self.fine_album_var = tk.StringVar(value=DEFAULT_CONFIG["fine_album"])
        self.fine_date_var = tk.StringVar(value=DEFAULT_CONFIG["fine_date"])
        self.fine_comment_var = tk.StringVar(value=DEFAULT_CONFIG["fine_comment"])
        self.fine_random_cover_var = tk.BooleanVar(value=DEFAULT_CONFIG["fine_random_cover"])
        self.fine_random_bg_var = tk.BooleanVar(value=DEFAULT_CONFIG["fine_random_bg"])
        self.sync_rename_var = tk.BooleanVar(value=DEFAULT_CONFIG["sync_rename"])
        # 单文件编辑区变量
        self.s_title_var = tk.StringVar()
        self.s_artist_var = tk.StringVar()
        self.s_album_var = tk.StringVar()
        self.s_date_var = tk.StringVar()
        self.s_comment_var = tk.StringVar()
        self.s_track_var = tk.StringVar()
        # 状态栏
        self.list_count_var = tk.StringVar(value="尚未刷新")
        self.fine_count_var = tk.StringVar(value="尚未加载")
        self.loaded_var = tk.StringVar(value="未载入文件")
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)

        self._build_ui()
        self._load_config_to_ui()
        self._refresh_file_list()
        self._after_poll()

        if not HAVE_MUTAGEN:
            self.root.after(300, self._warn_no_mutagen)

    # ---------- 依赖缺失提示 ----------
    def _warn_no_mutagen(self):
        messagebox.showwarning(
            "缺少依赖",
            "未检测到 mutagen 库，无法读写 MP3 标签。\n\n"
            "请在命令行执行：\n  pip install mutagen\n\n"
            "安装后重启本程序。", parent=self.root)

    # ---------- UI 构建 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, **pad)

        # ===== 文件页 =====
        file_tab = ttk.Frame(self.notebook)
        self.notebook.add(file_tab, text=" 文件 ")

        frm_dir = ttk.LabelFrame(file_tab, text="1. MP3 目录")
        frm_dir.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_dir)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Entry(row, textvariable=self.input_dir_var).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_input_dir).pack(side="right", padx=4)
        ttk.Button(row, text="清理备份", command=self._cleanup_backups).pack(side="right", padx=4)
        self.input_dir_var.trace_add("write", lambda *a: self._debounce_refresh())

        frm_list = ttk.LabelFrame(file_tab, text="2. 文件列表（点选一个文件自动载入下方编辑区）")
        frm_list.pack(fill="both", expand=True, padx=10, pady=4)
        row = ttk.Frame(frm_list)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Button(row, text="刷新列表", command=self._refresh_file_list).pack(side="left")
        ttk.Label(row, textvariable=self.list_count_var, foreground="#555").pack(side="left", padx=10)
        list_frame = ttk.Frame(frm_list)
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)
        self.file_list = tk.Listbox(list_frame, font=("Consolas", 9), height=9)
        self.file_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, command=self.file_list.yview)
        sb.pack(side="right", fill="y")
        self.file_list.config(yscrollcommand=sb.set)
        self.file_list.bind("<<ListboxSelect>>", self._on_select_file)

        # ----- 单文件精修区 -----
        frm_edit = ttk.LabelFrame(file_tab, text="3. 单文件精修")
        frm_edit.pack(fill="x", padx=10, pady=4)
        head = ttk.Frame(frm_edit)
        head.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Label(head, text="当前文件:", foreground="#555").pack(side="left")
        ttk.Label(head, textvariable=self.loaded_var, foreground="#1565c0").pack(side="left", padx=6)
        ttk.Button(head, text="重新载入", command=self._reload_current).pack(side="right")

        grid = ttk.Frame(frm_edit)
        grid.pack(fill="x", padx=6, pady=4)
        for i in range(2):
            grid.columnconfigure(i * 2, weight=0)
            grid.columnconfigure(i * 2 + 1, weight=1)
        fields = [("标题:", self.s_title_var, 0, 0), ("作者:", self.s_artist_var, 0, 2),
                  ("专辑:", self.s_album_var, 1, 0), ("日期:", self.s_date_var, 1, 2),
                  ("音轨(n/N):", self.s_track_var, 2, 0)]
        for label, var, r, c in fields:
            ttk.Label(grid, text=label).grid(row=r, column=c, sticky="e", padx=(0, 4), pady=2)
            ttk.Entry(grid, textvariable=var, width=22).grid(
                row=r, column=c + 1, sticky="ew", padx=(0, 12), pady=2)
        ttk.Label(grid, text="备注:").grid(row=2, column=3, sticky="e", padx=(8, 4))
        ttk.Entry(grid, textvariable=self.s_comment_var, width=22).grid(
            row=2, column=4, sticky="ew", pady=2)
        grid.columnconfigure(4, weight=1)

        # 图片预览与操作
        img_row = ttk.Frame(frm_edit)
        img_row.pack(fill="x", padx=6, pady=4)
        self._build_image_box(img_row, "cover")
        self._build_image_box(img_row, "bg")

        btn_row = ttk.Frame(frm_edit)
        btn_row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(btn_row, text="保存当前文件", command=self._save_current).pack(side="left")
        ttk.Label(btn_row, foreground="#888",
                  text="保存前自动备份到 %s\\（同名覆盖）；勾选全局开关才会重命名文件" % BACKUP_SUBDIR
                  ).pack(side="left", padx=10)
        ttk.Checkbutton(btn_row, text="标题修改后同步重命名文件",
                        variable=self.sync_rename_var).pack(side="right")

        # ===== 多文件精修页 =====
        fine_tab = ttk.Frame(self.notebook)
        self.notebook.add(fine_tab, text=" 多文件精修 ")

        top = ttk.Frame(fine_tab)
        top.pack(fill="x", padx=10, pady=4)
        ttk.Label(top, text="目录:", foreground="#555").pack(side="left")
        ttk.Label(top, textvariable=self.input_dir_var, foreground="#1565c0").pack(side="left", padx=4)
        self.fine_load_btn = ttk.Button(top, text="加载列表", command=self._load_fine_list)
        self.fine_load_btn.pack(side="left", padx=6)
        self.fine_reclean_btn = ttk.Button(top, text="重新清洗", command=self._reclean_fine)
        self.fine_reclean_btn.pack(side="left")
        ttk.Label(top, textvariable=self.fine_count_var, foreground="#555").pack(side="left", padx=8)

        opt = ttk.Frame(fine_tab)
        opt.pack(fill="x", padx=10, pady=2)
        ttk.Checkbutton(opt, text="繁转简", variable=self.fine_t2s_var).pack(side="left")
        ttk.Checkbutton(opt, text="保存后按标题重命名文件", variable=self.fine_rename_var).pack(side="left", padx=10)
        ttk.Label(opt, text="过滤词:").pack(side="left", padx=(10, 2))
        ttk.Entry(opt, textvariable=self.clean_filter_words_var, width=22).pack(side="left")
        ttk.Label(opt, text="逗号分隔", foreground="#888").pack(side="left", padx=2)

        frm_common = ttk.LabelFrame(fine_tab, text="通用信息（留空 = 不修改该项）")
        frm_common.pack(fill="x", padx=10, pady=2)
        crow = ttk.Frame(frm_common)
        crow.pack(fill="x", padx=6, pady=3)
        for label, var in (("作者:", self.fine_artist_var), ("专辑:", self.fine_album_var),
                           ("日期:", self.fine_date_var), ("备注:", self.fine_comment_var)):
            ttk.Label(crow, text=label).pack(side="left")
            ttk.Entry(crow, textvariable=var, width=14).pack(side="left", padx=(2, 8))
        irow = ttk.Frame(frm_common)
        irow.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Checkbutton(irow, text="随机封面图", variable=self.fine_random_cover_var).pack(side="left")
        ttk.Checkbutton(irow, text="随机背景图", variable=self.fine_random_bg_var).pack(side="left", padx=10)
        ttk.Label(irow, foreground="#888",
                  text="每个文件独立随机一张，取自“参数”页头像目录").pack(side="left", padx=6)

        ttk.Label(fine_tab, foreground="#888",
                  text="音轨自动 n/N；红色=清洗为空已回退原文件名，橙色=标题重复；"
                       "手改过的行不会被重新清洗覆盖"
                  ).pack(anchor="w", padx=12)

        wrap = ttk.Frame(fine_tab)
        wrap.pack(fill="both", expand=True, padx=10, pady=4)
        self.fine_canvas = tk.Canvas(wrap, highlightthickness=0)
        fine_sb = ttk.Scrollbar(wrap, orient="vertical", command=self.fine_canvas.yview)
        self.fine_inner = ttk.Frame(self.fine_canvas)
        self.fine_inner.bind("<Configure>", lambda e: self.fine_canvas.configure(
            scrollregion=self.fine_canvas.bbox("all")))
        self._fine_win = self.fine_canvas.create_window((0, 0), window=self.fine_inner, anchor="nw")
        self.fine_canvas.bind("<Configure>", lambda e: self.fine_canvas.itemconfig(
            self._fine_win, width=e.width))
        self.fine_canvas.configure(yscrollcommand=fine_sb.set)
        self.fine_canvas.pack(side="left", fill="both", expand=True)
        fine_sb.pack(side="right", fill="y")
        self.fine_canvas.bind("<Enter>", lambda e: self.fine_canvas.bind_all("<MouseWheel>", self._on_fine_wheel))
        self.fine_canvas.bind("<Leave>", lambda e: self.fine_canvas.unbind_all("<MouseWheel>"))

        fbtn = ttk.Frame(fine_tab)
        fbtn.pack(fill="x", padx=10, pady=6)
        self.fine_save_btn = ttk.Button(fbtn, text="保存精修结果", command=self._save_fine)
        self.fine_save_btn.pack(side="left")
        ttk.Label(fbtn, foreground="#888",
                  text="只处理勾选行；保存前自动备份到 %s\\" % BACKUP_SUBDIR).pack(side="left", padx=10)

        # ===== 参数页 =====
        param_tab = ttk.Frame(self.notebook)
        self.notebook.add(param_tab, text=" 参数 ")
        outer = ttk.Frame(param_tab)
        outer.pack(fill="both", expand=True, padx=10, pady=6)

        frm_gen = ttk.LabelFrame(outer, text="批量文本信息（留空 = 不修改该项）")
        frm_gen.pack(fill="x", pady=4)
        g = ttk.Frame(frm_gen)
        g.pack(fill="x", padx=6, pady=4)
        pairs = [("标题前缀", self.batch_title_prefix_var, "留空=不动标题；标题=前缀+序号"),
                 ("起始序号", self.batch_start_num_var, "前导零定宽度，如 055"),
                 ("作者", self.batch_artist_var, ""),
                 ("专辑", self.batch_album_var, ""),
                 ("日期(年)", self.batch_date_var, "如 2026"),
                 ("备注", self.batch_comment_var, "")]
        for i, (label, var, hint) in enumerate(pairs):
            r, c = divmod(i, 2)
            cell = ttk.Frame(g)
            cell.grid(row=r, column=c, sticky="w", padx=6, pady=3)
            g.columnconfigure(0, weight=1)
            g.columnconfigure(1, weight=1)
            ttk.Label(cell, text=label + ":").pack(side="left")
            ttk.Entry(cell, textvariable=var, width=18).pack(side="left", padx=4)
            if hint:
                ttk.Label(cell, text=hint, foreground="#888").pack(side="left")
        ttk.Label(frm_gen, foreground="#888",
                  text="说明：批量处理会始终重写音轨号为 序号/总数；标题前缀非空时按序号规则重新生成标题"
                  ).pack(anchor="w", padx=8, pady=(0, 4))

        frm_img = ttk.LabelFrame(outer, text="批量图片（留空 = 不修改该项；勾选随机 = 每个文件不同图）")
        frm_img.pack(fill="x", pady=4)
        for label, var, browse, rnd in (
                ("封面图:", self.batch_cover_path_var, self._pick_batch_cover, self.batch_random_cover_var),
                ("背景图:", self.batch_bg_image_path_var, self._pick_batch_bg, self.batch_random_bg_var)):
            row = ttk.Frame(frm_img)
            row.pack(fill="x", padx=6, pady=3)
            ttk.Label(row, text=label).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=4)
            ttk.Button(row, text="浏览…", command=browse).pack(side="left", padx=2)
            ttk.Button(row, text="清除", width=5,
                       command=lambda v=var: v.set("")).pack(side="left", padx=2)
            ttk.Checkbutton(row, text="随机", variable=rnd).pack(side="left", padx=4)
        row = ttk.Frame(frm_img)
        row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="头像目录:").pack(side="left")
        ttk.Entry(row, textvariable=self.avatar_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_avatar_dir).pack(side="left", padx=2)
        ttk.Label(frm_img, foreground="#888",
                  text="说明：勾选随机后每个文件从头像目录独立随机一张（完全随机可能重复，忽略左侧固定路径）；"
                       "未勾选时选图对话框也会默认预选该目录的一张随机图"
                  ).pack(anchor="w", padx=8, pady=(0, 4))

        frm_opt = ttk.LabelFrame(outer, text="保存选项")
        frm_opt.pack(fill="x", pady=4)
        row = ttk.Frame(frm_opt)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Checkbutton(row, text="标题修改后同步重命名文件",
                        variable=self.sync_rename_var).pack(side="left")
        ttk.Label(row, foreground="#888",
                  text="备份始终自动开启：源目录\\%s" % BACKUP_SUBDIR).pack(side="left", padx=12)

        # ===== 日志页 =====
        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text=" 日志 ")
        frm_log = ttk.Frame(self.log_tab)
        frm_log.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(frm_log, wrap="word", state="disabled",
                                font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        log_sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=log_sb.set)

        # ===== 说明页 =====
        help_tab = ttk.Frame(self.notebook)
        self.notebook.add(help_tab, text=" 说明 ")
        frm_help = ttk.Frame(help_tab)
        frm_help.pack(fill="both", expand=True, padx=6, pady=6)
        self.help_text = tk.Text(frm_help, wrap="word", state="disabled",
                                 font=("Microsoft YaHei UI", 10))
        self.help_text.pack(side="left", fill="both", expand=True)
        help_sb = ttk.Scrollbar(frm_help, command=self.help_text.yview)
        help_sb.pack(side="right", fill="y")
        self.help_text.config(yscrollcommand=help_sb.set)
        self.help_text.config(state="normal")
        self.help_text.insert("1.0", TUTORIAL)
        self.help_text.config(state="disabled")

        # ===== 底部操作栏 =====
        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(fill="x", padx=10, pady=6)
        self.start_btn = ttk.Button(btn_bar, text="开始批量应用", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(btn_bar, text="停止", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.progress_bar = ttk.Progressbar(btn_bar, variable=self.progress_var,
                                            maximum=100, length=240)
        self.progress_bar.pack(side="left", padx=16)
        self.lbl_status = ttk.Label(btn_bar, textvariable=self.status_var, foreground="#333")
        self.lbl_status.pack(side="left", padx=8)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_image_box(self, parent, which):
        box = ttk.Frame(parent)
        box.pack(side="left", expand=True, fill="x")
        title = "封面图（Cover front）" if which == "cover" else "播放背景图（Other）"
        ttk.Label(box, text=title, anchor="center").pack()
        label = ttk.Label(box, text="未载入", anchor="center", foreground="#888")
        label.pack(pady=8)
        btns = ttk.Frame(box)
        btns.pack(pady=2)
        if which == "cover":
            self.cover_preview = label
            cmds = (self._replace_cover, self._delete_cover, self._export_cover)
        else:
            self.bg_preview = label
            cmds = (self._replace_bg, self._delete_bg, self._export_bg)
        for text, cmd in zip(("更换", "删除", "导出"), cmds):
            ttk.Button(btns, text=text, width=5, command=cmd).pack(side="left", padx=2)

    # ---------- 浏览/目录 ----------
    def _pick_input_dir(self):
        p = filedialog.askdirectory(title="选择 MP3 目录")
        if p:
            self.input_dir_var.set(p)
            self._refresh_file_list()

    def _cleanup_backups(self):
        """一键删除当前 MP3 目录下的 _backup_标签编辑 备份子目录"""
        d = self.input_dir_var.get().strip()
        if not d or not Path(d).is_dir():
            self._show_toast("提示", "请先在上方选择 MP3 目录。", "warning")
            return
        bak_dir = Path(d) / BACKUP_SUBDIR
        if not bak_dir.is_dir():
            self._show_toast("提示", "该目录下没有备份文件夹：%s" % BACKUP_SUBDIR, "info")
            return
        files = [p for p in bak_dir.rglob("*") if p.is_file()]
        if not files:
            self._show_toast("提示", "备份文件夹已空，无需清理。", "info")
            return
        if not messagebox.askyesno(
                "确认清理备份",
                "将永久删除备份文件夹及其中的 %d 个文件：\n%s\n\n"
                "这些是编辑标签前的原始备份，删除后无法通过本工具回退。\n\n确定继续吗？"
                % (len(files), bak_dir), parent=self.root, icon="warning"):
            return
        try:
            count, path = cleanup_backups(d)
            self._log("[清理备份] 已删除 %d 个文件: %s" % (count, path))
            logger.info("清理备份目录: %s (%d 个文件)", path, count)
            self._show_toast("已清理", "删除 %d 个备份文件" % count, "success")
        except Exception as e:
            self._log("[清理备份失败] %s" % _short_err(e))
            self._show_toast("清理失败", _short_err(e), "error", 6000)

    def _pick_avatar_dir(self):
        p = filedialog.askdirectory(title="选择随机头像目录")
        if p:
            self.avatar_dir_var.set(p)

    def _ask_image(self, title, fallback_dir):
        """统一图片选择框：头像目录可用时随机预选其中一张（可换选），否则按 fallback 目录打开"""
        filetypes = [("图片文件", "*.jpg;*.jpeg;*.png"), ("所有文件", "*.*")]
        avatar_dir = self.avatar_dir_var.get().strip()
        pick = pick_random_image(avatar_dir) if avatar_dir else None
        if pick is not None:
            return filedialog.askopenfilename(title=title, initialdir=str(pick.parent),
                                              initialfile=pick.name, filetypes=filetypes)
        return filedialog.askopenfilename(title=title, initialdir=fallback_dir or None,
                                          filetypes=filetypes)

    def _pick_batch_cover(self):
        p = self._ask_image("选择封面图", self.input_dir_var.get())
        if p:
            self.batch_cover_path_var.set(p)

    def _pick_batch_bg(self):
        p = self._ask_image("选择播放背景图", self.input_dir_var.get())
        if p:
            self.batch_bg_image_path_var.set(p)

    # ---------- 多文件精修 ----------
    def _load_fine_list(self):
        d = self.input_dir_var.get().strip()
        if not d or not Path(d).is_dir():
            self._show_toast("提示", "请先在“文件”页选择 MP3 目录。", "warning")
            return
        files = sorted(p for p in Path(d).iterdir()
                       if p.is_file() and p.suffix.lower() == ".mp3")
        for child in self.fine_inner.winfo_children():
            child.destroy()
        self._fine_rows = []
        self._fine_dir = Path(d)
        ttk.Label(self.fine_inner, text="纳入", foreground="#555").grid(row=0, column=0, padx=4, pady=2)
        ttk.Label(self.fine_inner, text="原文件名", foreground="#555").grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(self.fine_inner, text="标题（可编辑）", foreground="#555").grid(row=0, column=2, sticky="w", padx=4)
        self.fine_inner.columnconfigure(2, weight=1)
        t2s = self.fine_t2s_var.get()
        fw = self.clean_filter_words_var.get()
        if t2s and not HAVE_ZHCONV:
            self._show_toast("缺少依赖", "繁转简需要 zhconv：\npip install zhconv\n本次加载将保留繁体。",
                             "warning", 6000)
        for i, p in enumerate(files, start=1):
            cleaned = clean_title_from_filename(p.stem, t2s, fw)
            row = {"path": p, "check": tk.BooleanVar(value=True),
                   "title": tk.StringVar(value=cleaned or p.stem),
                   "dirty": False, "fallback": not cleaned}
            ttk.Checkbutton(self.fine_inner, variable=row["check"]).grid(row=i, column=0, padx=4, pady=1)
            ttk.Label(self.fine_inner, text=p.name, foreground="#666", anchor="w").grid(
                row=i, column=1, sticky="w", padx=4)
            ent = tk.Entry(self.fine_inner, textvariable=row["title"])
            ent.grid(row=i, column=2, sticky="ew", padx=4, pady=1)
            row["entry"] = ent
            row["title"].trace_add("write", lambda *a, r=row: self._on_fine_title_edit(r))
            self._fine_rows.append(row)
        self._refresh_fine_marks()
        self.fine_count_var.set("%d 个文件" % len(files))
        self._log("[多文件精修] 已加载 %d 个 MP3: %s" % (len(files), d))

    def _on_fine_title_edit(self, row):
        row["dirty"] = True
        row["fallback"] = False
        self._refresh_fine_marks()

    def _refresh_fine_marks(self):
        counts = {}
        for r in self._fine_rows:
            t = r["title"].get().strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
        for r in self._fine_rows:
            t = r["title"].get().strip()
            if r["fallback"] and not r["dirty"]:
                bg = "#ffd6d6"      # 红：清洗为空已回退原文件名
            elif t and counts.get(t, 0) > 1:
                bg = "#ffe8cc"      # 橙：标题重复
            else:
                bg = "white"
            try:
                r["entry"].configure(background=bg)
            except Exception:
                pass

    def _reclean_fine(self):
        if not self._fine_rows:
            self._show_toast("提示", "请先点“加载列表”。", "warning")
            return
        t2s = self.fine_t2s_var.get()
        fw = self.clean_filter_words_var.get()
        n = 0
        for r in self._fine_rows:
            if r["dirty"]:
                continue
            cleaned = clean_title_from_filename(r["path"].stem, t2s, fw)
            r["title"].set(cleaned or r["path"].stem)
            r["dirty"] = False      # 程序 set 会触发 trace，这里重置
            r["fallback"] = not cleaned
            n += 1
        self._refresh_fine_marks()
        self._show_toast("已重新清洗", "重算 %d 行（手改过的行已保留）" % n, "success")

    def _save_fine(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        if not HAVE_MUTAGEN:
            self._show_toast("缺少依赖", "请先安装 mutagen：\npip install mutagen", "error")
            return
        if not self._fine_rows:
            self._show_toast("提示", "请先点“加载列表”。", "warning")
            return
        cfg = self._collect_config_from_ui()
        if self._fine_dir is None or Path(cfg["input_dir"]) != self._fine_dir:
            self._show_toast("提示", "目录已变化，请重新加载列表后再保存。", "warning")
            return
        items, skipped = [], []
        for r in self._fine_rows:
            if not r["check"].get():
                continue
            t = r["title"].get().strip()
            if not t:
                skipped.append(r["path"].name)
                continue
            items.append((r["path"], t))
        if skipped:
            self._log("[多文件精修] 跳过 %d 个空标题文件: %s" % (
                len(skipped), ", ".join(skipped)))
        if not items:
            self._show_toast("提示", "没有可处理的行：请勾选并填写标题。", "warning")
            return
        verr = self._validate_images(cfg, "fine")
        if verr:
            self._show_toast(*verr)
            return
        self._save_config_file(cfg)
        self._last_mode = "fine"
        self._stop_event.clear()
        self.progress_var.set(0)
        self.status_var.set("准备中...")
        self._set_running(True)
        self.notebook.select(self.log_tab)
        self.worker_thread = threading.Thread(target=self._work_fine, args=(cfg, items), daemon=True)
        self.worker_thread.start()

    # ---------- 配置读写 ----------
    def _load_config_to_ui(self):
        cfg = self._read_config_file()
        self.input_dir_var.set(cfg.get("input_dir", DEFAULT_CONFIG["input_dir"]))
        self.batch_title_prefix_var.set(cfg.get("batch_title_prefix", "") or "")
        self.batch_start_num_var.set(cfg.get("batch_start_num", "1") or "1")
        self.batch_artist_var.set(cfg.get("batch_artist", "") or "")
        self.batch_album_var.set(cfg.get("batch_album", "") or "")
        self.batch_date_var.set(cfg.get("batch_date", "") or "")
        self.batch_comment_var.set(cfg.get("batch_comment", "") or "")
        self.batch_cover_path_var.set(cfg.get("batch_cover_path", "") or "")
        self.batch_bg_image_path_var.set(cfg.get("batch_bg_image_path", "") or "")
        self.avatar_dir_var.set(cfg.get("avatar_dir", DEFAULT_CONFIG["avatar_dir"]))
        self.batch_random_cover_var.set(bool(cfg.get("batch_random_cover", False)))
        self.batch_random_bg_var.set(bool(cfg.get("batch_random_bg", False)))
        self.fine_t2s_var.set(bool(cfg.get("fine_t2s", True)))
        self.fine_rename_var.set(bool(cfg.get("fine_rename", True)))
        self.clean_filter_words_var.set(cfg.get("clean_filter_words", "") or "")
        self.fine_artist_var.set(cfg.get("fine_artist", "") or "")
        self.fine_album_var.set(cfg.get("fine_album", "") or "")
        self.fine_date_var.set(cfg.get("fine_date", "") or "")
        self.fine_comment_var.set(cfg.get("fine_comment", "") or "")
        self.fine_random_cover_var.set(bool(cfg.get("fine_random_cover", False)))
        self.fine_random_bg_var.set(bool(cfg.get("fine_random_bg", False)))
        self.sync_rename_var.set(bool(cfg.get("sync_rename", False)))

    def _collect_config_from_ui(self):
        return {
            "input_dir": self.input_dir_var.get().strip(),
            "batch_title_prefix": self.batch_title_prefix_var.get().strip(),
            "batch_start_num": self.batch_start_num_var.get().strip() or "1",
            "batch_artist": self.batch_artist_var.get().strip(),
            "batch_album": self.batch_album_var.get().strip(),
            "batch_date": self.batch_date_var.get().strip(),
            "batch_comment": self.batch_comment_var.get().strip(),
            "batch_cover_path": self.batch_cover_path_var.get().strip(),
            "batch_bg_image_path": self.batch_bg_image_path_var.get().strip(),
            "avatar_dir": self.avatar_dir_var.get().strip(),
            "batch_random_cover": bool(self.batch_random_cover_var.get()),
            "batch_random_bg": bool(self.batch_random_bg_var.get()),
            "fine_t2s": bool(self.fine_t2s_var.get()),
            "fine_rename": bool(self.fine_rename_var.get()),
            "clean_filter_words": self.clean_filter_words_var.get().strip(),
            "fine_artist": self.fine_artist_var.get().strip(),
            "fine_album": self.fine_album_var.get().strip(),
            "fine_date": self.fine_date_var.get().strip(),
            "fine_comment": self.fine_comment_var.get().strip(),
            "fine_random_cover": bool(self.fine_random_cover_var.get()),
            "fine_random_bg": bool(self.fine_random_bg_var.get()),
            "sync_rename": bool(self.sync_rename_var.get()),
        }

    @staticmethod
    def _read_config_file():
        """读 json 配置，缺失字段用默认值补齐（向后兼容旧配置文件）"""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(saved if isinstance(saved, dict) else {})
                logger.info("已加载配置: %s", CONFIG_PATH)
                return merged
        except Exception as e:
            logger.error("加载配置失败，使用默认配置: %s", e)
        return DEFAULT_CONFIG.copy()

    @staticmethod
    def _save_config_file(cfg):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    # ---------- 文件列表 ----------
    def _debounce_refresh(self):
        """输入目录文本变化后防抖刷新（800ms）"""
        if getattr(self, "_refresh_after", None):
            self.root.after_cancel(self._refresh_after)
        self._refresh_after = self.root.after(800, self._refresh_file_list)

    def _refresh_file_list(self):
        self.file_list.delete(0, tk.END)
        self._files = []
        d = Path(self.input_dir_var.get().strip())
        if not d.is_dir():
            self.list_count_var.set("目录不存在")
            return
        self._files = sorted(p for p in d.iterdir()
                             if p.is_file() and p.suffix.lower() == ".mp3")
        if not self._files:
            self.list_count_var.set("共 0 个 MP3")
            return
        for p in self._files:
            info = read_media_info(p)
            self.file_list.insert(
                tk.END, "%s    ｜ 标题: %s ｜ 作者: %s" % (
                    p.name, info["title"] or "（空）", info["artist"] or "（空）"))
        self.list_count_var.set("共 %d 个 MP3" % len(self._files))

    def _on_select_file(self, event=None):
        sel = self.file_list.curselection()
        if not sel or sel[0] >= len(self._files):
            return
        self._load_file_for_edit(self._files[sel[0]])

    def _reload_current(self):
        if self._loaded_path:
            self._load_file_for_edit(self._loaded_path)

    def _load_file_for_edit(self, path):
        if not HAVE_MUTAGEN:
            self._show_toast("缺少依赖", "请先安装 mutagen：pip install mutagen", "error")
            return
        path = Path(path)
        if not path.is_file():
            self._show_toast("提示", "文件已不存在，请刷新列表", "warning")
            return
        info = read_media_info(path)
        self._loaded_path = path
        self.loaded_var.set(path.name)
        self.s_title_var.set(info["title"])
        self.s_artist_var.set(info["artist"])
        self.s_album_var.set(info["album"])
        self.s_date_var.set(info["date"])
        self.s_comment_var.set(info["comment"])
        self.s_track_var.set(info["track"])
        for key, slot in (("cover", "_cover"), ("bg", "_bg")):
            state = getattr(self, slot)
            frame = info[key]
            if frame:
                state["action"] = "keep"
                state["data"] = frame["data"]
                state["mime"] = frame["mime"]
            else:
                state["action"] = "keep"
                state["data"] = None
                state["mime"] = "image/jpeg"
        self._render_preview("cover")
        self._render_preview("bg")

    # ---------- 图片操作（单文件区） ----------
    def _replace_cover(self):
        self._pick_image_for_slot("cover")

    def _replace_bg(self):
        self._pick_image_for_slot("bg")

    def _pick_image_for_slot(self, which):
        if not self._loaded_path:
            self._show_toast("提示", "请先在列表中选择一个 MP3 文件", "warning")
            return
        title = "选择封面图" if which == "cover" else "选择播放背景图"
        p = self._ask_image(title, str(self._loaded_path.parent))
        if not p:
            return
        try:
            data = Path(p).read_bytes()
        except Exception as e:
            self._show_toast("读取失败", str(e), "error")
            return
        state = self._cover if which == "cover" else self._bg
        state["action"] = "set"
        state["data"] = data
        state["mime"] = sniff_image_mime(data)
        self._render_preview(which)

    def _delete_cover(self):
        self._set_image_action("cover", "delete")

    def _delete_bg(self):
        self._set_image_action("bg", "delete")

    def _set_image_action(self, which, action):
        state = self._cover if which == "cover" else self._bg
        if not self._loaded_path:
            return
        state["action"] = action
        if action == "delete":
            state["data"] = None
        self._render_preview(which)

    def _export_cover(self):
        self._export_image("cover")

    def _export_bg(self):
        self._export_image("bg")

    def _export_image(self, which):
        state = self._cover if which == "cover" else self._bg
        if not state["data"]:
            self._show_toast("提示", "当前没有可导出的%s图" % ("封面" if which == "cover" else "背景"),
                             "warning")
            return
        ext = ".png" if state["mime"] == "image/png" else ".jpg"
        default_name = ("cover" if which == "cover" else "background") + ext
        if self._loaded_path:
            default_name = "%s_%s%s" % (self._loaded_path.stem,
                                        which, ext)
        p = filedialog.asksaveasfilename(
            title="导出图片", initialdir=str((self._loaded_path or Path(".")).parent),
            initialfile=default_name, defaultextension=ext,
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")])
        if not p:
            return
        try:
            Path(p).write_bytes(state["data"])
            self._log("[导出] %s -> %s" % (which, p))
            self._show_toast("已导出", Path(p).name, "success")
        except Exception as e:
            self._show_toast("导出失败", _short_err(e), "error")

    def _render_preview(self, which):
        label = self.cover_preview if which == "cover" else self.bg_preview
        state = self._cover if which == "cover" else self._bg
        photo_attr = "_cover_photo" if which == "cover" else "_bg_photo"
        if state["action"] == "delete":
            setattr(self, photo_attr, None)
            label.config(image="", text="（保存后将删除）")
            return
        data = state["data"]
        if not data:
            setattr(self, photo_attr, None)
            label.config(image="", text="（无图片）")
            return
        if HAVE_PIL:
            try:
                img = Image.open(BytesIO(data))
                img.thumbnail((140, 110))
                buf = BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                photo = tk.PhotoImage(data=buf.getvalue())
                setattr(self, photo_attr, photo)
                label.config(image=photo, text="")
                return
            except Exception:
                pass
        setattr(self, photo_attr, None)
        label.config(image="", text="[%d KB，无 PIL 无法预览]" % (len(data) // 1024))

    # ---------- 单文件保存（主线程，mutagen 毫秒级） ----------
    def _save_current(self):
        if not HAVE_MUTAGEN:
            self._show_toast("缺少依赖", "请先安装 mutagen：pip install mutagen", "error")
            return
        if not self._loaded_path or not self._loaded_path.is_file():
            self._show_toast("提示", "请先在列表中选择一个 MP3 文件", "warning")
            return
        meta = {
            "title": self.s_title_var.get().strip(),
            "artist": self.s_artist_var.get().strip(),
            "album": self.s_album_var.get().strip(),
            "date": self.s_date_var.get().strip(),
            "comment": self.s_comment_var.get().strip(),
            "track": self.s_track_var.get().strip(),
        }
        cover_op = self._state_to_op(self._cover)
        bg_op = self._state_to_op(self._bg)
        rename_title = meta["title"] if self.sync_rename_var.get() else None
        try:
            final, notes = apply_edits(self._loaded_path, meta, cover_op, bg_op,
                                       rename_title=rename_title)
            self._loaded_path = final
            self.loaded_var.set(final.name)
            for n in notes:
                self._log("[保存] %s: %s" % (final.name, n))
            self._log("[保存] 标签已写入: %s" % final)
            logger.info("单文件保存成功: %s", final)
            self._show_toast("保存成功", "已写入标签\n%s" % final.name, "success")
            self._refresh_file_list()
        except Exception as e:
            self._log("[保存失败] %s: %s" % (self._loaded_path.name, _short_err(e)))
            self._show_toast("保存失败", _short_err(e), "error", 6000)

    @staticmethod
    def _state_to_op(state):
        """界面图片状态 -> apply_edits 的 op 参数"""
        if state["action"] == "delete":
            return ("delete",)
        if state["action"] == "set" and state["data"]:
            return ("data", state["data"], state["mime"])
        return None      # keep

    # ---------- 日志 ----------
    def _log(self, s):
        self.log_text.config(state="normal")
        self.log_text.insert("end", s + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _thread_log(self, s):
        """工作线程里只能走队列，不能直接碰 tkinter 控件"""
        self.msg_queue.put(("log", s))

    # ---------- Toast ----------
    def _show_toast(self, title, message, level="info", duration_ms=3500):
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)
            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error": ("#c62828", "#ffebee", "❌"),
                "info": ("#1565c0", "#e3f2fd", "ℹ️"),
                "warning": ("#e65100", "#fff3e0", "⚠️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)
            header = tk.Frame(toast, bg=bg)
            header.pack(fill=tk.X, padx=10, pady=8)
            tk.Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                     fg=fg, bg=bg).pack(side=tk.LEFT)
            close_btn = tk.Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())
            tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                     fg="#333", bg=bg, wraplength=360, justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)
            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            sx, sy = toast.winfo_screenwidth(), toast.winfo_screenheight()
            toast.geometry(f"+{sx - w - 20}+{sy - h - 60}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    # ---------- 控制 ----------
    def _start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        if not HAVE_MUTAGEN:
            self._show_toast("缺少依赖", "请先安装 mutagen：\npip install mutagen", "error")
            return
        cfg = self._collect_config_from_ui()
        d = Path(cfg["input_dir"])
        if not cfg["input_dir"] or not d.is_dir():
            self._show_toast("提示", "MP3 目录不存在，请先在“文件”页选择。", "warning")
            return
        # 批量图片配置校验（与多文件精修共用）
        verr = self._validate_images(cfg)
        if verr:
            self._show_toast(*verr)
            return
        has_any = any([cfg["batch_title_prefix"], cfg["batch_artist"], cfg["batch_album"],
                       cfg["batch_date"], cfg["batch_comment"],
                       cfg["batch_cover_path"], cfg["batch_bg_image_path"],
                       cfg["batch_random_cover"], cfg["batch_random_bg"]])
        if not has_any:
            if not messagebox.askyesno(
                    "没有填写任何批量项",
                    "“参数”页全部留空：不会修改任何文本标签和图片，\n"
                    "但会重写音轨号 n/N 并备份原文件。\n\n确定继续吗？", parent=self.root):
                return
        self._save_config_file(cfg)
        self._last_mode = "batch"
        self._stop_event.clear()
        self.progress_var.set(0)
        self.status_var.set("准备中...")
        self._set_running(True)
        self.notebook.select(self.log_tab)
        self.worker_thread = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _stop(self):
        self._stop_event.set()
        self.status_var.set("正在停止（等当前文件结束）...")
        self._log("[停止] 已请求停止，当前文件处理完成后结束...")

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        self.stop_btn.config(state="normal" if running else "disabled")
        for btn in (self.fine_save_btn, self.fine_load_btn, self.fine_reclean_btn):
            btn.config(state=state)

    def _on_fine_wheel(self, event):
        self.fine_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_close(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno(
                    "正在批量处理", "任务还在进行，确定要退出吗？\n"
                    "已保存的文件都已备份，不受影响。", parent=self.root):
                return
            self._stop_event.set()
        self._save_config_file(self._collect_config_from_ui())
        self.root.destroy()

    # ---------- 工作线程 ----------
    def _validate_images(self, cfg, mode="batch"):
        """图片配置校验；返回 (标题, 消息, 级别) 或 None。精修只校验随机头像目录"""
        if mode == "fine":
            if cfg["fine_random_cover"] or cfg["fine_random_bg"]:
                if not list_avatar_images(cfg["avatar_dir"]):
                    return ("头像目录不可用",
                            "目录不存在或没有图片：\n%s" % cfg["avatar_dir"], "error")
            return None
        for key, rnd_key in (("batch_cover_path", "batch_random_cover"),
                             ("batch_bg_image_path", "batch_random_bg")):
            p = cfg[key]
            if p and not cfg[rnd_key] and not os.path.isfile(p):
                return ("提示", "图片文件不存在：%s" % p, "warning")
        if cfg["batch_random_cover"] or cfg["batch_random_bg"]:
            if not list_avatar_images(cfg["avatar_dir"]):
                return ("头像目录不可用",
                        "目录不存在或没有图片：\n%s" % cfg["avatar_dir"], "error")
        return None

    def _prepare_image_ops(self, cfg, mode="batch"):
        """图片操作：随机池只扫描一次；批量另有固定图片路径，精修仅随机"""
        if mode == "fine":
            cover_pool = list_avatar_images(cfg["avatar_dir"]) if cfg["fine_random_cover"] else []
            bg_pool = list_avatar_images(cfg["avatar_dir"]) if cfg["fine_random_bg"] else []
            return cover_pool, bg_pool, None, None
        cover_pool = list_avatar_images(cfg["avatar_dir"]) if cfg["batch_random_cover"] else []
        bg_pool = list_avatar_images(cfg["avatar_dir"]) if cfg["batch_random_bg"] else []
        cover_op = bg_op = None
        if cfg["batch_cover_path"] and not cfg["batch_random_cover"]:
            data = Path(cfg["batch_cover_path"]).read_bytes()
            cover_op = ("data", data, sniff_image_mime(data))
        if cfg["batch_bg_image_path"] and not cfg["batch_random_bg"]:
            data = Path(cfg["batch_bg_image_path"]).read_bytes()
            bg_op = ("data", data, sniff_image_mime(data))
        return cover_pool, bg_pool, cover_op, bg_op

    def _finish_fail_list(self, d, failed_list):
        """写出失败明细；本轮无失败则删除旧清单"""
        fail_log = d / FAIL_LIST_NAME
        if failed_list:
            with open(fail_log, "w", encoding="utf-8") as f:
                f.write("失败文件清单（%d 个）\n%s\n" % (len(failed_list), "=" * 40))
                for name, err in failed_list:
                    f.write("%s\n    原因: %s\n" % (name, err))
            self._thread_log("失败明细已写入: %s" % fail_log)
        elif fail_log.exists():
            try:
                fail_log.unlink()
                self._thread_log("已删除上一轮遗留的失败清单: %s" % fail_log.name)
            except Exception as e:
                logger.error("删除旧失败清单失败: %s", e)

    def _work(self, cfg):
        """批量主流程：扫描 -> 逐项写标签（备份+原子替换） -> 汇总失败清单"""
        try:
            d = Path(cfg["input_dir"])
            files = sorted(p for p in d.iterdir()
                           if p.is_file() and p.suffix.lower() == ".mp3")
            total = len(files)
            if total == 0:
                self.msg_queue.put(("empty", "目录下没有 MP3 文件:\n%s" % d))
                return

            # 起始序号解析（与音频合并工具一致：前导零决定补零宽度）
            raw = cfg["batch_start_num"] or "1"
            try:
                start = int(raw)
                if start < 0:
                    start = 1
                    raw = "1"
            except ValueError:
                start = 1
                raw = "1"
            width = max(1, len(raw))

            prefix = cfg["batch_title_prefix"]
            # 批量 meta：只包含非空字段（留空 = 不修改）
            base_meta = build_common_meta(cfg)
            cover_pool, bg_pool, cover_op, bg_op = self._prepare_image_ops(cfg)

            self._thread_log("=" * 60)
            self._thread_log("批量目录: %s（%d 个 MP3）" % (d, total))
            self._thread_log("标题前缀: %s | 起始序号: %s | 作者: %s | 专辑: %s | 日期: %s | 备注: %s" % (
                prefix or "（不改）", raw, cfg["batch_artist"] or "（不改）",
                cfg["batch_album"] or "（不改）", cfg["batch_date"] or "（不改）",
                cfg["batch_comment"] or "（不改）"))
            self._thread_log("封面: %s | 背景图: %s | 同步重命名: %s" % (
                ("随机（头像 %d 张）" % len(cover_pool)) if cover_pool else (cfg["batch_cover_path"] or "（不改）"),
                ("随机（头像 %d 张）" % len(bg_pool)) if bg_pool else (cfg["batch_bg_image_path"] or "（不改）"),
                "开" if cfg["sync_rename"] else "关"))
            self._thread_log("=" * 60)

            done = failed = 0
            failed_list = []
            start_ts = time.time()
            for idx, path in enumerate(files, start=1):
                if self._stop_event.is_set():
                    self.msg_queue.put(("stopped", "已在第 %d/%d 个文件后停止" % (idx - 1, total)))
                    return
                self.msg_queue.put(("progress", idx, total))
                meta = dict(base_meta)
                new_title = batch_title_for(prefix, start, width, idx)
                if new_title:
                    meta["title"] = new_title
                meta["track"] = "%d/%d" % (idx, total)
                try:
                    final, notes = apply_edits(
                        path, meta,
                        random_image_op(cover_pool, cover_op),
                        random_image_op(bg_pool, bg_op),
                        rename_title=new_title if cfg["sync_rename"] else None)
                    done += 1
                    self._thread_log("[%d/%d] 完成: %s%s" % (
                        idx, total, final.name,
                        ("  (%s)" % "；".join(notes)) if notes else ""))
                    logger.info("批量编辑完成: %s", final)
                except Exception as e:
                    failed += 1
                    brief = _short_err(e)
                    failed_list.append((path.name, brief))
                    self._thread_log("      [警告] 失败已跳过: %s\n             原因: %s" % (
                        path.name, brief))
                    logger.error("批量编辑失败 %s: %s", path.name, brief)

            elapsed = time.time() - start_ts
            self._finish_fail_list(d, failed_list)
            self.msg_queue.put(("done", done, failed, elapsed, str(d)))
        except Exception as e:
            self.msg_queue.put(("error", "任务异常：%s" % e))
            logger.exception("批量标签编辑异常")

    def _work_fine(self, cfg, items):
        """多文件精修主流程：逐行标题 + 通用字段 -> 写标签（备份+原子替换）"""
        try:
            d = Path(cfg["input_dir"])
            total = len(items)
            base_meta = build_common_meta(cfg, "fine")
            cover_pool, bg_pool, cover_op, bg_op = self._prepare_image_ops(cfg, "fine")

            self._thread_log("=" * 60)
            self._thread_log("多文件精修: %s（%d 个文件）" % (d, total))
            self._thread_log("作者: %s | 专辑: %s | 日期: %s | 备注: %s" % (
                cfg["fine_artist"] or "（不改）", cfg["fine_album"] or "（不改）",
                cfg["fine_date"] or "（不改）", cfg["fine_comment"] or "（不改）"))
            self._thread_log("封面: %s | 背景图: %s | 按标题重命名: %s" % (
                ("随机（头像 %d 张）" % len(cover_pool)) if cover_pool else "（不改）",
                ("随机（头像 %d 张）" % len(bg_pool)) if bg_pool else "（不改）",
                "开" if cfg["fine_rename"] else "关"))
            self._thread_log("=" * 60)

            done = failed = 0
            failed_list = []
            start_ts = time.time()
            for idx, (path, title) in enumerate(items, start=1):
                if self._stop_event.is_set():
                    self.msg_queue.put(("stopped", "已在第 %d/%d 个文件后停止" % (idx - 1, total)))
                    return
                self.msg_queue.put(("progress", idx, total))
                meta = dict(base_meta)
                meta["title"] = title
                meta["track"] = "%d/%d" % (idx, total)
                try:
                    final, notes = apply_edits(
                        path, meta,
                        random_image_op(cover_pool, cover_op),
                        random_image_op(bg_pool, bg_op),
                        rename_title=title if cfg["fine_rename"] else None)
                    done += 1
                    self._thread_log("[%d/%d] 完成: %s%s" % (
                        idx, total, final.name,
                        ("  (%s)" % "；".join(notes)) if notes else ""))
                    logger.info("精修编辑完成: %s", final)
                except Exception as e:
                    failed += 1
                    brief = _short_err(e)
                    failed_list.append((path.name, brief))
                    self._thread_log("      [警告] 失败已跳过: %s\n             原因: %s" % (
                        path.name, brief))
                    logger.error("精修编辑失败 %s: %s", path.name, brief)

            elapsed = time.time() - start_ts
            self._finish_fail_list(d, failed_list)
            self.msg_queue.put(("done", done, failed, elapsed, str(d)))
        except Exception as e:
            self.msg_queue.put(("error", "任务异常：%s" % e))
            logger.exception("多文件精修异常")

    # ---------- 消息轮询 ----------
    def _after_poll(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    idx, total = msg[1], msg[2]
                    self.progress_var.set(idx / total * 100)
                    self.status_var.set("正在处理 %d/%d" % (idx, total))
                elif kind == "empty":
                    self.status_var.set("没有可处理的文件")
                    self.progress_var.set(0)
                    self._set_running(False)
                    self._log("\n[提示] %s" % msg[1])
                    self._show_toast("没有文件", msg[1].splitlines()[0], "warning")
                elif kind == "done":
                    done, failed, elapsed, out_dir = msg[1:5]
                    self.progress_var.set(100)
                    self.status_var.set("完成：成功 %d，失败 %d" % (done, failed))
                    self._set_running(False)
                    self._log("\n" + "=" * 60)
                    self._log("任务结束：成功 %d，失败 %d，用时 %.1f 秒" % (done, failed, elapsed))
                    self._log("=" * 60)
                    self._refresh_file_list()
                    if self._last_mode == "fine":
                        self._load_fine_list()      # 重命名后刷新精修列表
                    if failed:
                        self._show_toast("完成（有失败）",
                                         "成功 %d，失败 %d\n明细见目录的『%s』" % (
                                             done, failed, FAIL_LIST_NAME), "warning", 7000)
                    else:
                        self._show_toast("精修完成" if self._last_mode == "fine" else "批量完成",
                                         "成功 %d 个，用时 %.1f 秒\n%s" % (done, elapsed, out_dir),
                                         "success", 5000)
                elif kind == "stopped":
                    self.status_var.set("已停止")
                    self._set_running(False)
                    self._log("\n[停止] %s\n已处理的文件均已保存并备份。" % msg[1])
                    self._refresh_file_list()
                    if self._last_mode == "fine":
                        self._load_fine_list()
                elif kind == "error":
                    self.status_var.set("出错")
                    self._set_running(False)
                    self._log("\n[错误] %s" % msg[1])
                    self._show_toast("出错", msg[1], "error", 7000)
        except queue.Empty:
            pass
        self.root.after(100, self._after_poll)


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
