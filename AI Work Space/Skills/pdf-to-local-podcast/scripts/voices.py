# -*- coding: utf-8 -*-
"""pdf-to-local-podcast 共享音色表。
AI 写脚本时使用的音色名 -> 本地参考音频 + prompt_text 的映射。
新增音色时在此追加一条，脚本中即可使用新音色名。
"""
import os

# 参考音频目录（Zero-Shot 音色复刻素材库）
TTS_DIR = r"D:\CODE\Python\test-data-backup\AI Work Space\TTS"

# 参考音频的原文（转写自各音频内容，与音频严格配对）
_DEFAULT_PROMPT_TEXT = "清晨的风轻轻吹过山头，世间万物慢慢苏醒过来。接下来我们就来看一看这里发生的有趣故事。"
_HUAHUA_PROMPT_TEXT = "清晨的风轻轻吹过山头，世间万物慢慢苏醒过来。接下来，我们就来看一看这里发生的有趣故事。"

# 音色表：音色名 -> {"audio": 参考音频绝对路径, "prompt_text": 音频原文, "desc": 声音类型}
VOICE_TABLE = {
    "郭靖": {
        "audio": os.path.join(TTS_DIR, "Jing郭靖-推荐短视频男声.mp3"),
        "prompt_text": _DEFAULT_PROMPT_TEXT,
        "desc": "男声",
    },
    "豆包桃子": {
        "audio": os.path.join(TTS_DIR, "豆包-桃子.mp3"),
        "prompt_text": _DEFAULT_PROMPT_TEXT,
        "desc": "女声",
    },
    "萌萌": {
        "audio": os.path.join(TTS_DIR, "Mmeng萌萌-儿童男孩声音 Child.mp3"),
        "prompt_text": _DEFAULT_PROMPT_TEXT,
        "desc": "男童",
    },
    "雪花": {
        "audio": os.path.join(TTS_DIR, "Huahua 雪花-儿童女孩声音 Child.mp3"),
        "prompt_text": _HUAHUA_PROMPT_TEXT,
        "desc": "女童",
    },
}


def resolve_voice(voice_name):
    """按音色名返回 (audio_path, prompt_text)；未知音色返回 None。"""
    item = VOICE_TABLE.get(voice_name)
    if item is None:
        return None
    return item["audio"], item["prompt_text"]
