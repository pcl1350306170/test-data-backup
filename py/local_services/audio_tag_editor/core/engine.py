# -*- coding: utf-8 -*-
"""引擎层：与界面无关的纯函数 + 文件级安全写入（备份/原子替换/重命名）。

标签读写按扩展名分派到 formats 适配器；本层只负责通用逻辑与文件安全。
"""
import os
import random
import re
import shutil
from pathlib import Path

from .formats import get_adapter, SUPPORTED_EXTS, UnsupportedFormat  # noqa: F401

# ---------- 可选依赖：zhconv（繁转简，标题清洗用） ----------
try:
    import zhconv
    HAVE_ZHCONV = True
except Exception:
    zhconv = None
    HAVE_ZHCONV = False

# 备份子目录名 / 失败清单文件名
BACKUP_SUBDIR = "_backup_标签编辑"
FAIL_LIST_NAME = "标签编辑失败清单.txt"

# 头像目录扫描的图片扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


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
    """按文件头魔数判断图片 MIME；兼容性最好的是 JPEG，兜底按 JPEG 处理"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def list_audio_files(directory):
    """目录顶层受支持的音频文件（按名排序）；目录无效返回空列表"""
    try:
        d = Path(directory)
        if not d.is_dir():
            return []
        return sorted(p for p in d.iterdir()
                      if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)
    except Exception:
        return []


def read_info(path):
    """读取音频标签与内嵌图片（按格式分派）"""
    return get_adapter(path).read_info(path)


def apply_edits(src_path, meta, cover_op=None, bg_op=None,
                rename_title=None, backup=True):
    """
    编辑单个音频：备份 → 副本写标签 → 原子替换 → 可选重命名。
    :param meta: 只包含“要修改”的键（title/artist/album/date/comment/track）
    :return: (最终路径 Path, 提示语列表)
    """
    src = Path(src_path)
    adapter = get_adapter(src)          # 不支持的格式在此抛出
    notes = []

    if backup:
        bak_dir = src.parent / BACKUP_SUBDIR
        bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, bak_dir / src.name)
        notes.append("已备份 %s" % (bak_dir.name + "\\" + src.name))

    tmp = src.parent / (src.name + ".tmp")
    try:
        shutil.copy2(src, tmp)
        adapter.write_tags(tmp, meta, cover_op, bg_op)
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
            dst = src.parent / (safe + src.suffix)   # 保留原扩展名（格式无关）
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
    """随机取一张头像图路径；无候选返回 None"""
    pool = list_avatar_images(avatar_dir)
    return random.choice(pool) if pool else None


def random_image_op(pool, fallback=None):
    """随机图片操作：从池随机读一张 -> ("data", bytes, mime)；池空或读失败回退 fallback"""
    if not pool:
        return fallback
    try:
        data = random.choice(pool).read_bytes()
        return ("data", data, sniff_image_mime(data))
    except Exception:
        return fallback


def cleanup_backups(input_dir):
    """删除音频目录下的 _backup_标签编辑 备份子目录（仅限该固定名称，不越界删除）
    :return: (删除文件数, 备份目录路径字符串)
    :raises FileNotFoundError: 备份目录不存在时抛出
    """
    bak_dir = Path(input_dir) / BACKUP_SUBDIR
    if not bak_dir.is_dir():
        raise FileNotFoundError("备份目录不存在: %s" % bak_dir)
    count = sum(1 for p in bak_dir.rglob("*") if p.is_file())
    shutil.rmtree(str(bak_dir))
    return count, str(bak_dir)


def validate_images(cfg, mode="batch"):
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


def prepare_image_ops(cfg, mode="batch"):
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


def write_fail_list(directory, failed_list):
    """写出失败明细；本轮无失败则删除旧清单。返回日志提示列表"""
    d = Path(directory)
    fail_log = d / FAIL_LIST_NAME
    notes = []
    if failed_list:
        with open(fail_log, "w", encoding="utf-8") as f:
            f.write("失败文件清单（%d 个）\n%s\n" % (len(failed_list), "=" * 40))
            for name, err in failed_list:
                f.write("%s\n    原因: %s\n" % (name, err))
        notes.append("失败明细已写入: %s" % fail_log)
    elif fail_log.exists():
        try:
            fail_log.unlink()
            notes.append("已删除上一轮遗留的失败清单: %s" % fail_log.name)
        except Exception:
            pass
    return notes