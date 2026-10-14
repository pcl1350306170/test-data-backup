# -*- coding: utf-8 -*-
"""配置持久化（JSON），管理脚本目录、输出目录、CosyVoice 环境路径等。"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULTS = {
    "script_dirs": [r"D:\FILES\糖蛋蛋(＾Ｕ＾)ノ~ＹＯ\播客脚本"],
    "output_dir": r"D:\FILES\糖蛋蛋(＾Ｕ＾)ノ~ＹＯ\本地播客",
    "audio_dir": r"D:\FILES\糖蛋蛋(＾Ｕ＾)ノ~ＹＯ\audio",
    "tts_dir": r"D:\CODE\Python\test-data-backup\AI Work Space\TTS",
    "bgm_dir": os.path.join(BASE_DIR, "uploads"),
    "default_lufs": -16,
    "default_gap_ms": 400,
    "conda_python": r"D:\TOOLS\miniconda3\envs\cosyvoice\python.exe",
    "model_dir": r"D:\dev\sherpa-models\CosyVoice2-0.5B",
    "repo_dir": r"D:\dev\sherpa-models\CosyVoice",
    "worker_script": r"D:\CODE\Python\test-data-backup\py\other\cosyvoice_tts_worker.py",
}


def load():
    """加载配置，不存在则用默认值。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = {**DEFAULTS, **saved}
            return merged
        except Exception:
            return dict(DEFAULTS)
    return dict(DEFAULTS)


def save(cfg):
    """保存配置到 JSON 文件。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
