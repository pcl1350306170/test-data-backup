# -*- coding: utf-8 -*-
"""音色管理：动态注册/删除音色，扫描 TTS 目录获取参考音频。

首次启动自动导入 6 个默认音色（啊乐/桃子/郭靖/球球/萌萌/雪花）。
"""
import json
import os
import re

from . import config

VOICE_PATH = os.path.join(config.DATA_DIR, "voices.json")

DEFAULT_PROMPT_TEXT = (
    "清晨的风轻轻吹过山头，世间万物慢慢苏醒过来。"
    "接下来，我们就来看一看这里发生的有趣故事。"
)

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}

# 文件名关键词 → 声音类型
_TYPE_HINTS = [
    (re.compile(r"童|儿童|Child|child|kid|Kid"), "童声"),
    (re.compile(r"男|Male|male|Jing|jing"), "男声"),
    (re.compile(r"女|Female|female|Taozi|taozi"), "女声"),
]


def _infer_type(filename):
    """从文件名推断声音类型。"""
    for pat, vtype in _TYPE_HINTS:
        if pat.search(filename):
            return vtype
    return "未知"


def _load():
    if os.path.isfile(VOICE_PATH):
        try:
            with open(VOICE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save(voices):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(VOICE_PATH, "w", encoding="utf-8") as f:
        json.dump(voices, f, ensure_ascii=False, indent=2)


def _init_defaults():
    """首次启动：导入 6 个默认音色。"""
    tts_dir = config.load().get("tts_dir", "")
    defaults = {
        "啊乐": {
            "audio": os.path.join(tts_dir, "Al啊乐-推荐阅读短视频播音男声.mp3"),
            "prompt_text": DEFAULT_PROMPT_TEXT,
            "type": "通用男声",
        },
        "桃子": {
            "audio": os.path.join(tts_dir, "豆包-桃子.mp3"),
            "prompt_text": DEFAULT_PROMPT_TEXT,
            "type": "通用女声",
        },
        "郭靖": {
            "audio": os.path.join(tts_dir, "Jing郭靖-推荐短视频男声.mp3"),
            "prompt_text": DEFAULT_PROMPT_TEXT,
            "type": "老年男声",
        },
        "球球": {
            "audio": os.path.join(tts_dir, "Qiu球球-通用播音故事演讲女声.mp3"),
            "prompt_text": DEFAULT_PROMPT_TEXT,
            "type": "老年女声",
        },
        "萌萌": {
            "audio": os.path.join(tts_dir, "Mmeng萌萌-儿童男孩声音 Child.mp3"),
            "prompt_text": DEFAULT_PROMPT_TEXT,
            "type": "儿童男声",
        },
        "雪花": {
            "audio": os.path.join(tts_dir, "Huahua 雪花-儿童女孩声音 Child.mp3"),
            "prompt_text": DEFAULT_PROMPT_TEXT,
            "type": "儿童女声",
        },
    }
    # 仅当文件存在时才导入
    valid = {}
    for name, info in defaults.items():
        if os.path.isfile(info["audio"]):
            valid[name] = info
    _save(valid)
    return valid


def get_all():
    """获取全部已注册音色。"""
    voices = _load()
    if voices is None:
        return _init_defaults()
    return voices


def get(name):
    """获取单个音色信息，不存在返回 None。"""
    return get_all().get(name)


def scan_tts_dir():
    """扫描 TTS 目录，返回尚未注册的音频文件列表。"""
    cfg = config.load()
    tts_dir = cfg.get("tts_dir", "")
    if not tts_dir or not os.path.isdir(tts_dir):
        return []
    registered = set()
    for info in get_all().values():
        registered.add(os.path.basename(info["audio"]))
    unregistered = []
    for f in sorted(os.listdir(tts_dir)):
        ext = os.path.splitext(f)[1].lower()
        if ext in AUDIO_EXTS and f not in registered:
            unregistered.append({
                "filename": f,
                "path": os.path.join(tts_dir, f),
                "inferred_type": _infer_type(f),
            })
    return unregistered


def add_voice(name, audio_file, prompt_text=None, voice_type="未知"):
    """注册新音色。audio_file 为文件名（在 TTS 目录下）或绝对路径。"""
    voices = get_all()
    if name in voices:
        raise ValueError("音色「%s」已存在" % name)
    cfg = config.load()
    tts_dir = cfg.get("tts_dir", "")
    if os.path.isabs(audio_file):
        full_path = audio_file
    else:
        full_path = os.path.join(tts_dir, audio_file)
    if not os.path.isfile(full_path):
        raise ValueError("参考音频文件不存在: %s" % full_path)
    voices[name] = {
        "audio": full_path,
        "prompt_text": prompt_text or DEFAULT_PROMPT_TEXT,
        "type": voice_type,
    }
    _save(voices)
    return voices[name]


def remove_voice(name):
    """删除音色。"""
    voices = get_all()
    if name not in voices:
        raise ValueError("音色「%s」不存在" % name)
    del voices[name]
    _save(voices)
