# -*- coding: utf-8 -*-
"""配置管理：默认值、读写、首次启动从旧 GUI 配置导入。

配置键与旧脚本 MP3信息编辑.pyw 完全一致，便于无缝迁移；
新增 port 键用于服务端口。旧配置文件只读复制，绝不改动。
"""
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # audio_tag_editor/
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"

# 旧 GUI 脚本的真实配置（只读导入源）：py/other/json/config_mp3_tag_editor.json
OLD_CONFIG_PATH = BASE_DIR.parents[1] / "other" / "json" / "config_mp3_tag_editor.json"

# ---------- 日志（复用 py/log_utils.py，导入失败静默降级） ----------
_PY_DIR = str(BASE_DIR.parents[1])                      # 指向 py/ 目录
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger("audio_tag_editor")
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()

# ---------- 默认配置（每个键一行注释，与旧脚本对齐） ----------
DEFAULT_CONFIG = {
    "port": 8804,                       # 服务端口（避开 8800~8803 已占用）
    "input_dir": r"D:\AUDIO\mp3",       # 音频所在目录（批量/精修处理对象）
    "batch_title_prefix": "",           # 批量标题前缀，留空 = 不修改标题
    "batch_start_num": "1",             # 起始序号，前导零决定宽度（055 -> 三位）
    "batch_artist": "",                 # 批量作者，留空 = 不修改
    "batch_album": "",                  # 批量专辑，留空 = 不修改
    "batch_date": "",                   # 批量日期（年份），留空 = 不修改
    "batch_comment": "",                # 批量备注，留空 = 不修改
    "batch_cover_path": "",             # 批量封面图路径，留空 = 不修改
    "batch_bg_image_path": "",          # 批量播放背景图路径，留空 = 不修改
    "avatar_dir": r"D:\CODE\Miscellaneous\GPT-IMG\头像",  # 随机头像目录
    "batch_random_cover": False,        # 批量随机封面：每文件独立随机一张
    "batch_random_bg": False,           # 批量随机背景图：每文件独立随机一张
    "fine_t2s": True,                   # 多文件精修：标题清洗繁转简（需 zhconv）
    "fine_rename": True,                # 多文件精修：保存后按标题重命名文件
    "clean_filter_words": "",           # 标题清洗过滤词（逗号分隔），空 = 不启用
    "fine_artist": "",                  # 精修通用作者，留空 = 不修改
    "fine_album": "",                   # 精修通用专辑，留空 = 不修改
    "fine_date": "",                    # 精修通用日期（年份），留空 = 不修改
    "fine_comment": "",                 # 精修通用备注，留空 = 不修改
    "fine_random_cover": False,         # 精修随机封面（头像目录，每首不同）
    "fine_random_bg": False,            # 精修随机背景图（头像目录，每首不同）
    "sync_rename": False,               # 标题修改后同步重命名文件（仅批量模式）
    "manifest_rename": True,            # JSON 清单套用：按标题重命名文件
}


def _merge(saved):
    """缺失字段用默认值补齐（向后兼容旧配置文件）"""
    merged = DEFAULT_CONFIG.copy()
    if isinstance(saved, dict):
        merged.update(saved)
    return merged


def load_config():
    """读配置；首次启动（无 data/config.json）时从旧 GUI 配置只读导入。"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return _merge(json.load(f))
        except Exception as e:
            logger.error("加载配置失败，使用默认配置: %s", e)
            return DEFAULT_CONFIG.copy()

    # 首次启动：尝试从旧脚本配置导入真实数据（只读，不改旧文件）
    seed = {}
    try:
        if OLD_CONFIG_PATH.exists():
            with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, dict):
                seed = {k: v for k, v in old.items() if k in DEFAULT_CONFIG}
            logger.info("首次启动，从旧配置导入 %d 个键: %s", len(seed), OLD_CONFIG_PATH)
    except Exception as e:
        logger.warning("导入旧配置失败，使用默认值: %s", e)
    cfg = _merge(seed)
    save_config(cfg)
    return cfg


def save_config(cfg):
    """原子写入配置（仅保留已知键，避免脏键累积）"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        clean = {k: cfg[k] for k in DEFAULT_CONFIG if k in cfg}
        tmp = CONFIG_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        logger.info("配置已保存: %s", CONFIG_PATH)
    except Exception as e:
        logger.error("保存配置失败: %s", e)


# ---------- 「说明」页正文 ----------
TUTORIAL = """
【一、依赖安装】

  pip install mutagen zhconv fastapi uvicorn
  图片预览可选：pip install pillow

  国内镜像：
  pip install mutagen zhconv fastapi uvicorn -i https://pypi.tuna.tsinghua.edu.cn/simple

  · mutagen：纯 Python 读写标签，无需 ffmpeg，不重新编码音频。
  · zhconv：仅用于多文件精修的繁转简，未安装时降级为保留繁体。
  · 包名是 mutagen（变形虫），不要装成 mutate / mutation 等近似库。

【二、使用说明】

  1. “文件”页填写音频目录路径并“刷新列表”，列表显示每个文件的当前标题/作者。
     本服务运行在本机，直接编辑磁盘上的文件，路径手动填写即可。
  2. 单文件精修：点选列表中一个文件，下方编辑区载入现有标签与图片预览；
     改完点“保存当前文件”。封面/背景图可 更换（填图片路径）、删除、导出（下载）。
  3. 多文件精修：点“加载列表”，每行显示 原文件名 -> 清洗后标题，可逐行手改
     （红色=清洗为空已回退原文件名，橙色=标题重复）；清洗规则：去开头序号、
     只留中文+数字、繁转简（可关）、可配过滤词。页内可设通用作者/专辑/日期/备注
     （留空=不改），可选随机封面/背景图（头像目录，每首不同）；音轨自动 n/N；
     保存后默认按标题重命名文件。
  4. 批量处理：在“参数”页填好要统一套用的信息（留空 = 不修改该项），
     底部点“开始批量应用”。标题 = 前缀 + 序号（起始序号 055 表示三位补零），
     音轨自动写 序号/总数。
  5. JSON 歌曲清单：已查到每首歌的信息（歌名/歌手/专辑）时，在“参数”页
     “JSON 清单套用”粘贴或选择 JSON 文件，按文件名自动匹配到对应歌曲：
     标题/作者/专辑/日期/备注逐条写入，封面图保持原样，默认按标题重命名
     文件名（即文件名=歌名）。格式：
     [{"file": "原文件名.mp3", "title": "歌名", "artist": "歌手", "album": "专辑或空串"}]
     · file 可省略，改用 title+artist 也能匹配（兼容“歌名 - 歌手”与“歌手 - 歌名”）。
     · album 缺省 = 不修改专辑；空串 = 清空专辑。
     · 先点“预览匹配”看命中情况（弱匹配/未匹配文件/未命中条目）再启动。
  6. 随机头像：批量/精修勾选“随机封面/随机背景”后，每个文件从头像目录独立随机
     一张（完全随机可能重复），勾选时忽略固定图片路径。参数页提供“随机推荐一张”
     预览，可一键填入路径。
  7. 保存前自动把原文件备份到 源目录\\_backup_标签编辑\\（同名覆盖，只留最近一份），
     改错了可从备份恢复。确认无误后可用“文件”页的“清理备份”一键删除该备份文件夹。
  8. “标题修改后同步重命名文件”默认关闭（仅批量模式）；勾选后文件名随标题变化
     （非法字符自动过滤，目标重名则跳过重命名只改标签）。
  9. 只修改标签不重新编码音频，音质零损失；批量中单个文件失败只记警告不中断，
     结尾汇总并写『标签编辑失败清单.txt』，本轮无失败会自动删除旧清单。
  10. 所有设置都会记住（data/config.json），下次打开自动回填。

【三、格式支持】

  支持 MP3（ID3v2.3）、M4A（iTunes 原子）、APE（Monkey's Audio / APEv2）、
  FLAC（Vorbis Comment）、WMA（ASF 属性）。引擎按扩展名分派格式适配器，
  单文件精修 / 多文件精修 / 批量处理 / JSON 清单对各格式一致可用，目录内可混放。
  · M4A 标签映射：标题©nam / 作者©ART / 专辑©alb / 日期©day / 备注©cmt / 音轨trkn(n/N) / 封面covr。
  · APE 标签映射：Title / Artist / Album / Year / Comment / Track(n/N) / Cover Art (Front)。
  · FLAC 标签映射：title / artist / album / date / comment / tracknumber / Picture(type=3)。
  · WMA 标签映射：Title / Artist / Album / Year / Comment / Track / WM/Picture（主键与 WM/ 别名同写）。
  · M4A / APE / FLAC / WMA 标准只有封面、无背景图：随机背景/固定背景对其自动忽略，仅 MP3 有封面+背景两张。

【四、提醒】

  · 批量目录里放什么处理什么：目录下所有受支持音频都会被套用。
  · JSON 清单只改文本标签不动封面图；未匹配的文件/条目只在预览里列出，不会被修改。
  · 备份目录与音频同级，整个目录拷走/删除时注意一起处理。
  · MP3 写标签为 ID3v2.3，车载音响/老播放器兼容性更好。
  · M4A / APE / FLAC / WMA 仅封面：背景图选项对其不生效（只有 MP3 才有封面+背景两张）。
  · 图片会被内嵌进音频，单张建议控制在 1MB 以内，避免文件明显变大。
"""