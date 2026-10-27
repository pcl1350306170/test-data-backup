# -*- coding: utf-8 -*-
"""配置持久化（JSON），管理 CosyVoice 环境路径、输出目录等。"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    # CosyVoice 环境
    "conda_python": r"D:\TOOLS\miniconda3\envs\cosyvoice\python.exe",
    "model_dir": r"D:\dev\sherpa-models\CosyVoice2-0.5B",
    "repo_dir": r"D:\dev\sherpa-models\CosyVoice",
    "worker_script": r"D:\CODE\Python\test-data-backup\py\other\cosyvoice_tts_worker.py",
    # 目录
    "output_dir": os.path.join(BASE_DIR, "output"),
    "tts_dir": r"D:\CODE\Python\test-data-backup\AI Work Space\TTS",
    # 默认合成参数
    "spk": "中文女",
    "style": "",
    "speed": 1.0,
    "format": "wav",
    "seg_len": 500,
    "fade": True,
    "fade_ms": 0,
    "tail_ms": 900,
    "prompt_audio": "",
    "prompt_text": "",
    "default_prompt_text": "清晨的风轻轻吹过山头，世间万物慢慢苏醒过来。接下来，我们就来看一看这里发生的有趣故事。",
    # 合并功能：媒体目录（供前端下拉选择）
    "bgm_dir": r"D:\CODE\Python\test-data-backup\AI Work Space\TTS",
    "image_dir": r"D:\CODE\Python\test-data-backup\img",
    # 合并参数（选择一次后记住，下次自动加载）
    "merge_target_duration": 20,
    "merge_format": "mp3",
    "merge_bgm_path": "",
    "merge_bgm_volume": 30,
    "merge_cover_path": "",
    "merge_bg_image_path": "",
    "meta_title": "",
    "meta_artist": "",
    "meta_album": "",
    "meta_date": "",
    "meta_comment": "",
    "merge_start_num": "1",
    "merge_output_dir": r"D:\FILES\music\AI音频\MP3",
}

# 预置选项（不可配置，固定列表）
SPK_OPTIONS = ["中文女", "中文男", "英文女", "英文男", "日语男", "粤语女", "韩语女"]
STYLE_OPTIONS = ["", "开心", "温柔", "严肃", "活泼", "深情"]
SPEED_OPTIONS = ["0.8", "1.0", "1.2", "1.5"]


def load() -> dict:
    """加载配置，不存在则用默认值。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}
        except Exception:
            return dict(DEFAULTS)
    return dict(DEFAULTS)


def save(cfg: dict):
    """保存配置到 JSON 文件。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
