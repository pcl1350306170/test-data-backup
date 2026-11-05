# -*- coding: utf-8 -*-
"""
Whisper 本地批量语音转文字（ASR，纯离线）—— GUI 版
====================================================
功能：
  1. 批量读取【输入文件夹】下的音频（mp3 / wav / flac / m4a）
  2. 使用 openai-whisper 在本地转写为中文文本（不上传云端）
  3. 每条音频单独输出一个同名 txt 到【输出文件夹】
  4. 已转写过（txt 存在且非空）的音频自动跳过，支持断点续跑
  5. 单个音频损坏/解码失败只记录警告并跳过，不中断整个批量任务

运行方式：
  双击运行（.pyw 不弹控制台窗口，进度和结果都显示在“日志”页）

依赖：
  pip install -U openai-whisper      （另需 ffmpeg，见“说明”页）
"""

import json
import os
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "whisper_asr"
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

# ---------- whisper 依赖探测（放在函数里导入会更慢，这里启动即探测） ----------
try:
    import whisper as _whisper_probe
    HAVE_WHISPER = True
except Exception:
    _whisper_probe = None
    HAVE_WHISPER = False

# ---------- 默认配置 ----------
#   model        tiny / base / small / medium（越大越准、越慢、越吃内存）
#   language     zh = 强制中文；留空 = 自动检测
#   task         transcribe = 原文转写；translate = 翻译成英文
#   温度：whisper 的库 API 没有 temperature_inc 参数（那只是命令行的写法），
#         它接受温度梯度序列，本脚本用下面两项在运行时拼出来，
#         见 build_temperature_ladder()
#   其余字段为 whisper.transcribe() 的原生参数，含义见“说明”页
DEFAULT_CONFIG = {
    "input_dir": r"D:\AUDIO\whisper_in",
    "output_dir": r"D:\AUDIO\whisper_out",
    "model": "base",
    "language": "zh",
    "task": "transcribe",
    "temperature": 0.0,
    "temperature_increment_on_fallback": 0.2,
    "beam_size": None,
    "best_of": 1,
    "patience": None,
    "compression_ratio_threshold": 2.4,
    "logprob_threshold": -1.0,
    "condition_on_previous_text": True,
    "no_speech_threshold": 0.6,
    "initial_prompt": "以下是普通话的内容。",
    "word_timestamps": False,
    "show_segments": True,       # 转写完成后在日志页逐段显示结果（带时间戳）
    "skip_min_bytes": 10,        # txt 小于该字节数视为"未完成"，重新转写
    "open_dir_after_done": True,
}

# 支持的音频扩展名（whisper 内部用 ffmpeg 解码，四种格式原生支持）
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a"}

# 模型推荐列表（也可以手动输入 large-v3 / distil-large-v3 等其它名字）
MODEL_CHOICES = ["tiny", "base", "small", "medium"]

# 「说明」页正文
TUTORIAL = """
【一、pip 安装命令】

  pip install -U openai-whisper

  国内网络下载 torch 太慢时，可先单独装 CPU 版 torch：
  pip install torch --index-url https://download.pytorch.org/whl/cpu
  pip install -U openai-whisper

  注意：请安装 openai-whisper，不要装 faster-whisper / whisper.cpp，
        它们是不同实现，API 不一样，本程序用不了。

【二、ffmpeg 安装教程（Windows）】

  Whisper 解码音频靠调用 ffmpeg 命令行，必须先装好并加入 PATH。

  方式 A（推荐，最简单）——用 winget：
      winget install Gyan.FFmpeg
      装完关闭并重开终端，执行 ffmpeg -version 验证。

  方式 B——手动下载：
      1. 打开 https://www.gyan.dev/ffmpeg/builds/ ，下载 ffmpeg-release-essentials.zip
      2. 解压到一个不带中文和空格的目录，例如 C:\\ffmpeg
      3. 把 C:\\ffmpeg\\bin 加入系统环境变量 PATH：
         设置 → 系统 → 关于 → 高级系统设置 → 环境变量 → 在 Path 中新建一条
         C:\\ffmpeg\\bin → 确定
      4. 重开终端，执行 ffmpeg -version 能打印版本号即成功

  若日志提示“未找到 ffmpeg”，通常是改完 PATH 没有重开程序。

【三、使用说明】

  1. 双击本程序运行，在“文件”页选择输入文件夹（放音频）和输出文件夹（存 txt）。
  2. mp3/wav/flac/m4a 直接放进去即可，不需要改后缀；目录不存在会自动创建。
  3. “刷新列表”可先看看会处理哪些文件、哪些已转过；点“开始转写”即开始。
  4. 输出 txt 与音频同名（a.mp3 → a.txt），纯文本、每段一行、UTF-8 编码。
  5. 同名冲突：目录里同时有 x.mp3 和 x.wav 时，输出为 x_mp3.txt 和 x_wav.txt。
  6. 已转写过（txt 存在且不短）的音频会自动跳过，所以中途停止或关掉程序后，
     重新点“开始转写”就是接着没做的部分继续。
  7. 某个音频损坏/解码失败只会记一条警告并跳过，任务结束时汇总，并把失败明细
     写到输出目录的『转写失败清单.txt』；全部成功时该清单会被自动删除。
  8. 所有设置都会记住（json/config_whisper_asr.json），下次打开自动回填；
     想精细调参也可以直接编辑这个 json 文件。

【四、参数微调（“参数”页）】

    model                              tiny/base/small/medium，越大越准越慢
    language                           zh 强制中文；留空则自动检测
    task                               transcribe 原文转写；translate 翻成英文
    temperature                        起始温度，0.0 最稳定可复现；越大越有创造性
    temperature_increment_on_fallback  解码不理想时的温度递增步长，0.2 为官方默认；
                                       留空则关闭重试，只用单一温度
    beam_size / best_of                都设为 5 走 beam search，准确率更高但更慢
    patience                           beam search 的 patience 值，如 1.0
    compression_ratio_threshold        压缩率上限，用于抑制复读/幻觉，默认 2.4
    logprob_threshold                  平均对数概率下限，低于它则重试，默认 -1.0
    condition_on_previous_text         勾选更连贯；长录音出现复读/跑偏时取消勾选
    no_speech_threshold                静音/无人声判定，调低更少输出空内容
    initial_prompt                     引导用词与标点，如行业术语提示词
    word_timestamps                    词级时间戳（慢，一般不用）
    show_segments                      转写完成后在日志页逐段显示识别结果
    skip_min_bytes                     txt 小于此字节数视为没做完、重新转写

  注：temperature 与 temperature_increment_on_fallback 组合后相当于 whisper
      命令行的 --temperature 与 --temperature_increment_on_fallback；
      库 API 里没有 temperature_inc 这个参数名，直接传会报 unexpected keyword。

  whisper.transcribe 的完整参数说明见官方 README：
  https://github.com/openai/whisper#available-models-and-languages

【五、显存 / 内存提醒】

  模型大小与资源占用（官方数据）：
      tiny    参数 39M，显存/内存约 1GB，速度约 x10
      base    参数 74M，显存/内存约 1GB，速度约 x7
      small   参数 244M，显存/内存约 2GB，速度约 x4
      medium  参数 769M，显存/内存约 5GB，速度约 x2

  · 有 NVIDIA 独立显卡（显存 ≥4GB）：medium 可用，速度和质量都好。
  · 只有集成显卡 / 纯 CPU：建议 tiny 或 base；small 能跑但慢；
    medium 在 CPU 上会非常慢（1 小时音频可能要好几个小时），不建议。
  · 内存不足通常表现为进程被系统杀掉或报 CUDA out of memory，换更小的 model 即可。
  · 批量任务期间 CPU/GPU 会长时间满载，笔记本请接电源并注意散热。
  · 首次使用某个模型会自动下载到  %USERPROFILE%\\.cache\\whisper ，
    下载完成后即可完全离线，音频数据不会上传到任何云端。
"""


# ================== 环境检查 ==================

def check_ffmpeg():
    """
    检查 ffmpeg 是否可用（返回路径或 None）。
    openai-whisper 解码音频靠调用 ffmpeg 命令行，缺失时所有文件都会"假损坏"，
    因此必须在批量开始前先检查。
    """
    return shutil.which("ffmpeg")


def check_torch_cuda():
    """
    返回 (是否使用GPU, 描述信息)。
    无 GPU 时 fp16=True 会让 whisper 刷屏警告，所以这里自动判断，
    由调用方把 fp16 设为 False。
    """
    try:
        import torch
        if torch.cuda.is_available():
            return True, "GPU: %s (fp16 已启用)" % torch.cuda.get_device_name(0)
        return False, "CPU 模式 (torch %s)" % torch.__version__
    except Exception as e:
        return False, "CPU 模式 (torch 检测失败: %s)" % e


# ================== 文件扫描 ==================

def collect_audio_files(input_dir, output_dir, min_bytes):
    """
    扫描输入目录，返回 [(音频路径, 输出txt路径, 是否已完成), ...]。

    命名规则：a.mp3 -> a.txt（去扩展名）。
    冲突处理：若目录下同时存在 x.mp3 和 x.wav（去扩展名后同名），
              则输出名带上来源扩展名区分：x_mp3.txt / x_wav.txt。
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        return []
    files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    # 统计"去扩展名后"的重名情况
    stem_count = Counter(p.stem.lower() for p in files)

    pairs = []
    for p in files:
        if stem_count[p.stem.lower()] > 1:
            txt_name = "%s_%s.txt" % (p.stem, p.suffix.lstrip(".").lower())
        else:
            txt_name = "%s.txt" % p.stem
        txt_path = output_dir / txt_name
        done = txt_path.exists() and txt_path.stat().st_size >= min_bytes
        pairs.append((p, txt_path, done))
    return pairs


# ================== 单文件转写 ==================

def get_audio_duration(audio_path):
    """
    用 ffprobe 获取音频时长（秒），仅用于日志展示。
    失败返回 None，绝不影响主流程。
    """
    try:
        if not shutil.which("ffprobe"):
            return None
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def _fmt_ts(seconds):
    """秒 -> 分:秒，用于日志里的分段展示"""
    try:
        m, s = divmod(int(seconds), 60)
        return "%02d:%02d" % (m, s)
    except Exception:
        return "00:00"


def build_temperature_ladder(start, increment):
    """
    把「起始温度 + 递增步长」拼成 whisper 需要的温度梯度序列。
    等价于官方 CLI 的 --temperature / --temperature_increment_on_fallback，
    但 whisper 的库 API 只接受温度序列，不认 temperature_inc 这个名字。

    例：start=0.0, increment=0.2 -> (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    increment 为 None 时不退让，只用单一温度（重试机制关闭）。
    """
    if increment is None:
        return (start,)
    ladder = []
    t = float(start)
    while t <= 1.0 + 1e-6:
        ladder.append(round(t, 4))
        t += float(increment)
    return tuple(ladder) if ladder else (float(start),)


def transcribe_one(model, audio_path, cfg, use_fp16):
    """
    转写单个音频，返回 (纯文本, 分段列表)。
    任何异常（文件损坏、解码失败等）都向上抛出，由批量循环捕获后跳过。

    注意 whisper 的参数分两层（已比对已安装版本的实际签名）：
      transcribe() 本身：verbose, temperature, compression_ratio_threshold,
                         logprob_threshold, no_speech_threshold,
                         condition_on_previous_text, initial_prompt, word_timestamps
      **decode_options（转给 DecodingOptions）：task, language, beam_size, best_of,
                         patience, length_penalty, fp16, suppress_blank 等
    """
    kwargs = {
        # ---- transcribe 层 ----
        # verbose 必须传 None：源码里进度条是 disable=(verbose is not False)，
        # 传 None 时既打印不了文字、也不会启动 tqdm 进度条，.pyw 无控制台时最干净；
        # 分段结果由本函数返回、在 GUI 日志页显示。
        "verbose": None,
        "temperature": build_temperature_ladder(
            cfg["temperature"], cfg.get("temperature_increment_on_fallback")
        ),
        "condition_on_previous_text": cfg["condition_on_previous_text"],
        "no_speech_threshold": cfg["no_speech_threshold"],
        "word_timestamps": cfg["word_timestamps"],
        "fp16": use_fp16,
        # ---- decode_options 层 ----
        "task": cfg.get("task") or "transcribe",
    }
    # language 留空 = 不传，让 whisper 自动检测
    if cfg.get("language"):
        kwargs["language"] = cfg["language"]
    # 以下 None 表示用 whisper 自身默认值，不主动传入
    for key in ("compression_ratio_threshold", "logprob_threshold",
                "beam_size", "best_of", "patience", "initial_prompt"):
        if cfg.get(key) is not None and cfg.get(key) != "":
            kwargs[key] = cfg[key]

    result = model.transcribe(str(audio_path), **kwargs)

    segments = result.get("segments") or []
    # 拼接所有段的文本：每段一行，方便后续阅读与再加工
    lines = [seg["text"].strip() for seg in segments if seg["text"].strip()]
    text = "\n".join(lines) + "\n" if lines else ""
    return text, segments


def _short_err(err, limit=300):
    """
    把异常信息压成一行简短描述。
    whisper 解码失败时会把 ffmpeg 的整段版本信息一起抛出来，
    不截断会把日志页和失败清单刷屏。
    """
    text = " ".join(str(err).split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…（已截断，共 %d 字）" % len(text)


def write_txt(txt_path, text):
    """写输出文件；先写临时文件再原子改名，避免中断产生半截 txt"""
    tmp_path = txt_path.parent / (txt_path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    tmp_path.replace(txt_path)


# ================== GUI 主程序 ==================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Whisper 本地批量语音转文字")
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

        # 模型缓存：同一次运行里换目录不用重新加载模型
        self._model = None
        self._model_name = None

        # 界面变量
        self.input_dir_var = tk.StringVar(value=DEFAULT_CONFIG["input_dir"])
        self.output_dir_var = tk.StringVar(value=DEFAULT_CONFIG["output_dir"])
        self.model_var = tk.StringVar(value=DEFAULT_CONFIG["model"])
        self.language_var = tk.StringVar(value=DEFAULT_CONFIG["language"])
        self.task_var = tk.StringVar(value=DEFAULT_CONFIG["task"])
        self.temperature_var = tk.StringVar(value=str(DEFAULT_CONFIG["temperature"]))
        self.temp_inc_var = tk.StringVar(value=str(DEFAULT_CONFIG["temperature_increment_on_fallback"]))
        self.beam_size_var = tk.StringVar(value="")
        self.best_of_var = tk.StringVar(value=str(DEFAULT_CONFIG["best_of"]))
        self.patience_var = tk.StringVar(value="")
        self.compression_var = tk.StringVar(value=str(DEFAULT_CONFIG["compression_ratio_threshold"]))
        self.logprob_var = tk.StringVar(value=str(DEFAULT_CONFIG["logprob_threshold"]))
        self.no_speech_var = tk.StringVar(value=str(DEFAULT_CONFIG["no_speech_threshold"]))
        self.initial_prompt_var = tk.StringVar(value=DEFAULT_CONFIG["initial_prompt"])
        self.skip_min_var = tk.StringVar(value=str(DEFAULT_CONFIG["skip_min_bytes"]))
        self.condition_prev_var = tk.BooleanVar(value=DEFAULT_CONFIG["condition_on_previous_text"])
        self.word_ts_var = tk.BooleanVar(value=DEFAULT_CONFIG["word_timestamps"])
        self.show_seg_var = tk.BooleanVar(value=DEFAULT_CONFIG["show_segments"])
        self.open_dir_var = tk.BooleanVar(value=DEFAULT_CONFIG["open_dir_after_done"])
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.list_count_var = tk.StringVar(value="尚未刷新")

        self._build_ui()
        self._load_config_to_ui()
        self._refresh_file_list()
        self._after_poll()

        if not HAVE_WHISPER:
            self.root.after(300, self._warn_no_whisper)
        if not check_ffmpeg():
            self.root.after(600, self._warn_no_ffmpeg)

    # ---------- 依赖缺失提示 ----------
    def _warn_no_whisper(self):
        messagebox.showwarning(
            "缺少依赖",
            "未检测到 openai-whisper 库，无法转写。\n\n"
            "请在命令行执行：\n  pip install -U openai-whisper\n\n"
            "安装后重启本程序。", parent=self.root)

    def _warn_no_ffmpeg(self):
        self._log("[警告] 未在 PATH 中找到 ffmpeg，Whisper 无法解码音频。\n"
                  "       请先安装（winget install Gyan.FFmpeg），详见“说明”页，"
                  "装完需要重启本程序。")
        logger.warning("ffmpeg 不可用")

    # ---------- UI 构建 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, **pad)

        # ===== 文件页 =====
        file_tab = ttk.Frame(self.notebook)
        self.notebook.add(file_tab, text=" 文件 ")

        frm_in = ttk.LabelFrame(file_tab, text="1. 输入文件夹（放音频：mp3 / wav / flac / m4a）")
        frm_in.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_in)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Entry(row, textvariable=self.input_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_input_dir).pack(side="right", padx=4)

        frm_out = ttk.LabelFrame(file_tab, text="2. 输出文件夹（每条音频生成一个同名 txt）")
        frm_out.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_out)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Entry(row, textvariable=self.output_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览…", command=self._pick_output_dir).pack(side="right", padx=4)
        ttk.Button(row, text="打开", command=self._open_output_dir).pack(side="right", padx=4)

        # 模型选择
        frm_model = ttk.LabelFrame(file_tab, text="3. 模型（越大越准越慢，纯 CPU 建议 base）")
        frm_model.pack(fill="x", padx=10, pady=4)
        row = ttk.Frame(frm_model)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="模型:").pack(side="left")
        self.model_combo = ttk.Combobox(row, textvariable=self.model_var,
                                       width=16, values=MODEL_CHOICES)
        self.model_combo.pack(side="left", padx=6)
        ttk.Label(row, text="（也可手动输入 large-v3 等其它模型名）", foreground="#888").pack(side="left")

        # 文件列表预览
        frm_list = ttk.LabelFrame(file_tab, text="4. 待处理文件")
        frm_list.pack(fill="both", expand=True, padx=10, pady=4)
        row = ttk.Frame(frm_list)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Button(row, text="刷新列表", command=self._refresh_file_list).pack(side="left")
        ttk.Label(row, textvariable=self.list_count_var, foreground="#555").pack(side="left", padx=10)
        ttk.Checkbutton(row, text="完成后打开输出目录", variable=self.open_dir_var).pack(side="right")

        list_frame = ttk.Frame(frm_list)
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)
        self.file_list = tk.Listbox(list_frame, font=("Consolas", 9))
        self.file_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, command=self.file_list.yview)
        sb.pack(side="right", fill="y")
        self.file_list.config(yscrollcommand=sb.set)

        # ===== 参数页 =====
        param_tab = ttk.Frame(self.notebook)
        self.notebook.add(param_tab, text=" 参数 ")
        outer = ttk.Frame(param_tab)
        outer.pack(fill="both", expand=True, padx=10, pady=6)

        frm_lang = ttk.LabelFrame(outer, text="语言与任务")
        frm_lang.pack(fill="x", pady=4)
        row = ttk.Frame(frm_lang)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="识别语言:").pack(side="left")
        ttk.Combobox(row, textvariable=self.language_var, width=8,
                     values=["zh", "en", "ja", "ko", "auto"]).pack(side="left", padx=4)
        ttk.Label(row, text="auto/留空 = 自动检测", foreground="#888").pack(side="left", padx=4)
        ttk.Label(row, text="任务:").pack(side="left", padx=(20, 0))
        ttk.Combobox(row, textvariable=self.task_var, width=12, state="readonly",
                     values=["transcribe", "translate"]).pack(side="left", padx=4)

        frm_temp = ttk.LabelFrame(outer, text="解码参数（留空表示用 whisper 默认值）")
        frm_temp.pack(fill="x", pady=4)
        grid = [
            ("起始温度", self.temperature_var, "0.0 最稳定可复现"),
            ("温度递增步长", self.temp_inc_var, "重试时 +多少，0.2 为默认"),
            ("beam_size", self.beam_size_var, "留空=贪心；填 5 更准更慢"),
            ("best_of", self.best_of_var, "配合温度>0 使用"),
            ("patience", self.patience_var, "beam 长度惩罚，如 1.0"),
            ("压缩率阈值", self.compression_var, "抑制复读幻觉，默认 2.4"),
            ("对数概率阈值", self.logprob_var, "低于它则重试，默认 -1.0"),
            ("无人声阈值", self.no_speech_var, "静音判定，默认 0.6"),
            ("跳过字节数", self.skip_min_var, "txt 小于此值视为没做完"),
        ]
        for i, (label, var, hint) in enumerate(grid):
            r, c = divmod(i, 3)
            cell = ttk.Frame(frm_temp)
            cell.grid(row=r, column=c, sticky="w", padx=6, pady=4)
            ttk.Label(cell, text=label + ":").pack(side="left")
            ttk.Entry(cell, textvariable=var, width=8).pack(side="left", padx=4)
            ttk.Label(cell, text=hint, foreground="#888").pack(side="left")
        frm_temp.columnconfigure(3, weight=1)

        frm_prompt = ttk.LabelFrame(outer, text="提示词与选项")
        frm_prompt.pack(fill="both", expand=True, pady=4)
        row = ttk.Frame(frm_prompt)
        row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="initial_prompt:").pack(side="left")
        ttk.Entry(row, textvariable=self.initial_prompt_var).pack(side="left", fill="x", expand=True, padx=6)
        row2 = ttk.Frame(frm_prompt)
        row2.pack(fill="x", padx=6, pady=4)
        ttk.Checkbutton(row2, text="上下文连贯（condition_on_previous_text）",
                        variable=self.condition_prev_var).pack(side="left")
        ttk.Checkbutton(row2, text="词级时间戳（更慢）",
                        variable=self.word_ts_var).pack(side="left", padx=16)
        ttk.Checkbutton(row2, text="日志中逐段显示识别结果",
                        variable=self.show_seg_var).pack(side="left")
        ttk.Label(row2, text="提示：长录音出现复读/跑偏时，取消“上下文连贯”",
                  foreground="#888").pack(side="right")

        # ===== 日志页 =====
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text=" 日志 ")
        frm_log = ttk.Frame(log_tab)
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
        self.start_btn = ttk.Button(btn_bar, text="开始转写", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(btn_bar, text="停止", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.progress_bar = ttk.Progressbar(btn_bar, variable=self.progress_var,
                                            maximum=100, length=240)
        self.progress_bar.pack(side="left", padx=16)
        self.lbl_status = ttk.Label(btn_bar, textvariable=self.status_var, foreground="#333")
        self.lbl_status.pack(side="left", padx=8)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- 浏览按钮 ----------
    def _pick_input_dir(self):
        p = filedialog.askdirectory(title="选择输入文件夹（音频所在目录）")
        if p:
            self.input_dir_var.set(p)
            self._refresh_file_list()

    def _pick_output_dir(self):
        p = filedialog.askdirectory(title="选择输出文件夹（txt 保存目录）")
        if p:
            self.output_dir_var.set(p)
            self._refresh_file_list()

    def _open_output_dir(self):
        out = self.output_dir_var.get().strip()
        if out and Path(out).is_dir():
            try:
                os.startfile(out)
            except Exception as e:
                messagebox.showerror("打开失败", str(e), parent=self.root)
        else:
            messagebox.showinfo("提示", "输出目录还不存在，开始转写后会自动创建。", parent=self.root)

    # ---------- 配置读写 ----------
    def _load_config_to_ui(self):
        cfg = self._read_config_file()
        self.input_dir_var.set(cfg.get("input_dir", DEFAULT_CONFIG["input_dir"]))
        self.output_dir_var.set(cfg.get("output_dir", DEFAULT_CONFIG["output_dir"]))
        self.model_var.set(cfg.get("model", DEFAULT_CONFIG["model"]))
        self.language_var.set(cfg.get("language") or "auto")
        self.task_var.set(cfg.get("task", DEFAULT_CONFIG["task"]))
        self.temperature_var.set(self._num_to_str(cfg.get("temperature", 0.0)))
        inc = cfg.get("temperature_increment_on_fallback")
        self.temp_inc_var.set("" if inc is None else self._num_to_str(inc))
        self.beam_size_var.set(self._num_to_str(cfg.get("beam_size")))
        self.best_of_var.set(self._num_to_str(cfg.get("best_of")))
        self.patience_var.set(self._num_to_str(cfg.get("patience")))
        self.compression_var.set(self._num_to_str(cfg.get("compression_ratio_threshold")))
        self.logprob_var.set(self._num_to_str(cfg.get("logprob_threshold")))
        self.no_speech_var.set(self._num_to_str(cfg.get("no_speech_threshold")))
        self.skip_min_var.set(self._num_to_str(cfg.get("skip_min_bytes", 10)))
        self.initial_prompt_var.set(cfg.get("initial_prompt", "") or "")
        self.condition_prev_var.set(bool(cfg.get("condition_on_previous_text", True)))
        self.word_ts_var.set(bool(cfg.get("word_timestamps", False)))
        self.show_seg_var.set(bool(cfg.get("show_segments", True)))
        self.open_dir_var.set(bool(cfg.get("open_dir_after_done", True)))

    def _collect_config_from_ui(self):
        """把界面控件的值收集成配置字典（数值项留空 -> None，用 whisper 默认值）"""
        lang = self.language_var.get().strip().lower()
        if lang in ("", "auto"):
            lang = None                      # None 表示交给 whisper 自动检测
        cfg = {
            "input_dir": self.input_dir_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "model": self.model_var.get().strip() or DEFAULT_CONFIG["model"],
            "language": lang,
            "task": self.task_var.get().strip() or "transcribe",
            "temperature": self._str_to_num(self.temperature_var.get(), 0.0, float),
            "temperature_increment_on_fallback": self._str_to_num(self.temp_inc_var.get(), None, float),
            "beam_size": self._str_to_num(self.beam_size_var.get(), None, int),
            "best_of": self._str_to_num(self.best_of_var.get(), None, int),
            "patience": self._str_to_num(self.patience_var.get(), None, float),
            "compression_ratio_threshold": self._str_to_num(self.compression_var.get(), None, float),
            "logprob_threshold": self._str_to_num(self.logprob_var.get(), None, float),
            "no_speech_threshold": self._str_to_num(self.no_speech_var.get(), 0.6, float),
            "initial_prompt": self.initial_prompt_var.get().strip(),
            "word_timestamps": bool(self.word_ts_var.get()),
            "condition_on_previous_text": bool(self.condition_prev_var.get()),
            "show_segments": bool(self.show_seg_var.get()),
            "skip_min_bytes": int(self._str_to_num(self.skip_min_var.get(), 10, int) or 0),
            "open_dir_after_done": bool(self.open_dir_var.get()),
        }
        return cfg

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
        """保存配置到 json，供下次打开自动回填"""
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    @staticmethod
    def _num_to_str(v):
        """None -> 空串；数字 -> 去掉多余的 .0"""
        if v is None:
            return ""
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)

    @staticmethod
    def _str_to_num(text, default, caster):
        """输入框文本 -> 数字；空串或非法值返回 default"""
        s = (text or "").strip()
        if s == "":
            return default
        try:
            return caster(s)
        except Exception:
            return default

    # ---------- 文件列表预览 ----------
    def _refresh_file_list(self):
        cfg = self._collect_config_from_ui()
        self.file_list.delete(0, tk.END)
        pairs = collect_audio_files(cfg["input_dir"], cfg["output_dir"], cfg["skip_min_bytes"])
        if not pairs:
            self.list_count_var.set("未发现音频文件")
            return
        todo = 0
        for audio_path, txt_path, done in pairs:
            if done:
                mark = "[已完成] -> %s" % txt_path.name
            else:
                todo += 1
                mark = "[待转写] -> %s" % txt_path.name
            self.file_list.insert(tk.END, "%s    %s" % (audio_path.name, mark))
        self.list_count_var.set("共 %d 个音频，待转写 %d 个，已跳过 %d 个"
                                % (len(pairs), todo, len(pairs) - todo))

    # ---------- 日志 ----------
    def _log(self, s):
        self.log_text.config(state="normal")
        self.log_text.insert("end", s + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _thread_log(self, s):
        """工作线程里只能走队列，不能直接碰 tkinter 控件"""
        self.msg_queue.put(("log", s))

    def _switch_to_log_tab(self):
        self.notebook.select(2)

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
        if not HAVE_WHISPER:
            self._show_toast("缺少依赖", "请先安装 openai-whisper：\npip install -U openai-whisper", "error")
            return
        if not check_ffmpeg():
            self._show_toast("缺少 ffmpeg", "未在 PATH 中找到 ffmpeg，详见“说明”页；\n装完需重启本程序。", "error")
            return

        cfg = self._collect_config_from_ui()
        if not cfg["input_dir"] or not cfg["output_dir"]:
            self._show_toast("提示", "输入文件夹和输出文件夹都不能为空。", "warning")
            return
        # 需求：目录不存在则自动创建（路径写错时会建一个空目录，日志里明确告知）
        for d in (cfg["input_dir"], cfg["output_dir"]):
            p = Path(d)
            if not p.is_dir():
                p.mkdir(parents=True, exist_ok=True)
                logger.warning("目录不存在，已自动创建: %s" % p)
        self._save_config_file(cfg)

        self._stop_event.clear()
        self.progress_var.set(0)
        self.status_var.set("准备中...")
        self._set_running(True)
        self._switch_to_log_tab()
        self.worker_thread = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _stop(self):
        self._stop_event.set()
        self.status_var.set("正在停止（等当前这条音频结束）...")
        self._log("[停止] 已请求停止，当前音频转写完成后结束...")

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        self.stop_btn.config(state="normal" if running else "disabled")

    def _on_close(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno(
                    "正在转写", "任务还在进行，确定要退出吗？\n"
                    "已完成的 txt 都已保存，下次打开可继续（自动跳过）。", parent=self.root):
                return
            self._stop_event.set()
        self.root.destroy()

    # ---------- 工作线程 ----------
    def _get_model(self, model_name):
        """加载模型；同名模型只加载一次（load_model 很慢，绝不能每个文件都调）"""
        if self._model is not None and self._model_name == model_name:
            self._thread_log("模型 '%s' 已在内存中，直接复用。" % model_name)
            return self._model
        import whisper
        cache_dir = Path.home() / ".cache" / "whisper"
        self._thread_log("正在加载模型 '%s'（首次使用会自动下载到 %s，"
                         "下载完成后即可完全离线）..." % (model_name, cache_dir))
        logger.info("开始加载模型: %s", model_name)
        model = whisper.load_model(model_name)
        self._model = model
        self._model_name = model_name
        self._thread_log("模型加载完成: %s" % model_name)
        return model

    def _work(self, cfg):
        """批量转写主流程：检查环境 -> 扫描文件 -> 加载模型(一次) -> 逐个转写"""
        try:
            input_dir = Path(cfg["input_dir"])
            output_dir = Path(cfg["output_dir"])
            # 目录不存在则自动创建
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            use_gpu, device_info = check_torch_cuda()
            # CPU 下必须 fp16=False，否则 whisper 每步都会打印警告
            self.msg_queue.put(("device", device_info))
            self._thread_log("=" * 60)
            self._thread_log("输入目录: %s" % input_dir)
            self._thread_log("输出目录: %s" % output_dir)
            self._thread_log("模型: %s | 语言: %s | 任务: %s | 温度: %s(+%s)" % (
                cfg["model"], cfg["language"] or "自动检测", cfg["task"],
                cfg["temperature"], cfg["temperature_increment_on_fallback"]))
            self._thread_log("=" * 60)

            # 扫描音频（支持 mp3/wav/flac/m4a）
            pairs = collect_audio_files(input_dir, output_dir, cfg["skip_min_bytes"])
            total = len(pairs)
            if total == 0:
                self.msg_queue.put(("empty", "输入目录下没有找到音频文件\n%s\n支持格式: %s" % (
                    input_dir, ", ".join(sorted(AUDIO_EXTS)))))
                return

            model = self._get_model(cfg["model"])

            # 固定随机种子：温度为 0 时结果完全可复现，便于对比参数
            random.seed(0)
            try:
                import torch
                torch.manual_seed(0)
            except Exception:
                pass

            done = skipped = failed = 0
            failed_list = []                 # 记录失败文件，结尾统一汇总
            start_ts = time.time()

            for idx, (audio_path, txt_path, is_done) in enumerate(pairs, start=1):
                if self._stop_event.is_set():
                    self.msg_queue.put(("stopped", "已在第 %d/%d 个文件后停止" % (idx - 1, total)))
                    return

                prefix = "[%d/%d]" % (idx, total)
                self.msg_queue.put(("progress", idx, total))

                # 跳过已生成（且非空）的 txt，避免重复转写
                if is_done:
                    skipped += 1
                    self._thread_log("%s 跳过（已存在 %s）: %s" % (prefix, txt_path.name, audio_path.name))
                    continue

                duration = get_audio_duration(audio_path)
                dur_str = "，时长约 %.0f 秒" % duration if duration else ""
                self._thread_log("%s 转写: %s%s" % (prefix, audio_path.name, dur_str))
                logger.info("%s 开始转写 %s%s", prefix, audio_path.name, dur_str)

                # 单文件异常只记录跳过，不中断整个批量任务
                file_start = time.time()
                try:
                    text, segments = transcribe_one(model, audio_path, cfg, use_gpu)
                    write_txt(txt_path, text)
                    done += 1
                    cost = time.time() - file_start
                    self._thread_log("      -> 已保存 %s（%d 字，耗时 %.1f 秒）" % (
                        txt_path.name, len(text), cost))
                    if cfg["show_segments"]:
                        for seg in segments:
                            t = seg["text"].strip()
                            if t:
                                self._thread_log("      [%s --> %s] %s" % (
                                    _fmt_ts(seg.get("start", 0)), _fmt_ts(seg.get("end", 0)), t))
                    logger.info("完成 %s -> %s", audio_path.name, txt_path.name)
                except Exception as e:
                    failed += 1
                    brief = _short_err(e)
                    failed_list.append((audio_path.name, brief))
                    self._thread_log("      [警告] 转写失败，已跳过: %s\n             原因: %s" % (
                        audio_path.name, brief))
                    logger.error("转写失败 %s: %s", audio_path.name, brief)
                self._thread_log("")

            # ---------- 结果汇总 ----------
            elapsed = time.time() - start_ts
            fail_log = output_dir / "转写失败清单.txt"
            if failed_list:
                with open(fail_log, "w", encoding="utf-8") as f:
                    f.write("失败文件清单（%d 个）\n%s\n" % (len(failed_list), "=" * 40))
                    for name, err in failed_list:
                        f.write("%s\n    原因: %s\n" % (name, err))
                self._thread_log("失败明细已写入: %s" % fail_log)
                logger.warning("失败清单: %s", [(n, e) for n, e in failed_list])
            elif fail_log.exists():
                # 本次没有失败：清掉上一轮遗留的失败清单，避免误导
                try:
                    fail_log.unlink()
                    self._thread_log("已删除上一轮遗留的失败清单: %s" % fail_log.name)
                except Exception as e:
                    logger.error("删除旧失败清单失败: %s", e)

            self.msg_queue.put(("done", done, skipped, failed, elapsed,
                                str(output_dir), bool(cfg["open_dir_after_done"])))
        except ImportError as e:
            self.msg_queue.put(("error", "openai-whisper 导入失败：%s\n请执行 pip install -U openai-whisper" % e))
        except Exception as e:
            self.msg_queue.put(("error", "任务异常：%s" % e))
            logger.exception("批量转写异常")

    # ---------- 消息轮询 ----------
    def _after_poll(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "device":
                    self.status_var.set("运行中（%s）" % msg[1])
                    self._log("运行设备: %s" % msg[1])
                elif kind == "progress":
                    idx, total = msg[1], msg[2]
                    self.progress_var.set(idx / total * 100)
                    self.status_var.set("正在转写 %d/%d" % (idx, total))
                elif kind == "empty":
                    self.status_var.set("没有需要处理的音频")
                    self.progress_var.set(0)
                    self._set_running(False)
                    self._log("\n[提示] %s" % msg[1])
                    self._show_toast("没有音频文件", msg[1].splitlines()[0], "warning")
                elif kind == "done":
                    done, skipped, failed, elapsed, out_dir, open_dir = msg[1:7]
                    self.progress_var.set(100)
                    self.status_var.set("完成：成功 %d，跳过 %d，失败 %d" % (done, skipped, failed))
                    self._set_running(False)
                    self._log("\n" + "=" * 60)
                    self._log("任务结束：成功 %d，跳过(已转写) %d，失败 %d，用时 %.1f 秒" % (
                        done, skipped, failed, elapsed))
                    self._log("=" * 60)
                    logger.info("GUI 批量转写完成：成功 %d，跳过 %d，失败 %d", done, skipped, failed)
                    self._refresh_file_list()
                    if failed:
                        self._show_toast("完成（有失败）",
                                         "成功 %d，跳过 %d，失败 %d\n明细见输出目录的『转写失败清单.txt』" % (
                                             done, skipped, failed), "warning", 7000)
                    else:
                        self._show_toast("转写完成",
                                         "成功 %d，跳过 %d，用时 %.1f 秒\n%s" % (done, skipped, elapsed, out_dir),
                                         "success", 5000)
                    if open_dir and Path(out_dir).is_dir():
                        try:
                            os.startfile(out_dir)
                        except Exception:
                            pass
                elif kind == "stopped":
                    self.status_var.set("已停止")
                    self._set_running(False)
                    self._log("\n[停止] %s\n已完成的 txt 均已保存，重新开始会自动跳过它们。" % msg[1])
                    self._refresh_file_list()
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
