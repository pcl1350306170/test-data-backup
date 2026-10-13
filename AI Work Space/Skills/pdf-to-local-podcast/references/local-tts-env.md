# 本地 CosyVoice 环境与生成/合并细节

## 1. 环境参数（已验证，写死在脚本默认值中）

| 项 | 值 |
|---|---|
| conda python | `D:\TOOLS\miniconda3\envs\cosyvoice\python.exe` |
| 模型目录 | `D:\dev\sherpa-models\CosyVoice2-0.5B` |
| 仓库目录 | `D:\dev\sherpa-models\CosyVoice` |
| worker 脚本 | `D:\CODE\Python\test-data-backup\py\other\cosyvoice_tts_worker.py` |
| 参考音频目录 | `D:\CODE\Python\test-data-backup\AI Work Space\TTS\` |
| ffmpeg | 需在 PATH（`D:\TOOLS\ffmpeg\bin` 已确认可用） |

> PYTHONPATH 需含仓库根目录与 `third_party/Matcha-TTS`（`generate_audio.py` 会自动构造）。

## 2. worker 调用方式（zero-shot 音色复刻）

```powershell
D:\TOOLS\miniconda3\envs\cosyvoice\python.exe cosyvoice_tts_worker.py `
  --model_dir "D:\dev\sherpa-models\CosyVoice2-0.5B" `
  --text "台词文本" `
  --output "out\001.wav" `
  --spk "中文女" `
  --prompt_audio "D:\CODE\Python\test-data-backup\AI Work Space\TTS\Jing郭靖-推荐短视频男声.mp3" `
  --prompt_text "清晨的风轻轻吹过山头，世间万物慢慢苏醒过来。接下来我们就来看一看这里发生的有趣故事。"
```

- `--prompt_audio` + `--prompt_text` 同时传 → zero-shot（优先级最高）；此时 `--spk` 实际不生效，但仍需传（默认"中文女"即可）。
- 参考音频是 mp3 时 worker 内部用 ffmpeg 转 16k 单声道 wav 再加载，无需预处理。
- 成功时 stdout 打印 `COSYVOICE_OK <output> mode=zero_shot`；失败时 stderr 打印 `COSYVOICE_ERR ...`。
- 单次生成可能耗时 1–5 分钟（GPU）；`generate_audio.py` 超时上限 900 秒。
- 主要风险：显存不足（报 `out of memory` 类错误）——此时减少块字数重试。

## 3. 生成脚本用法（generate_audio.py）

```powershell
python generate_audio.py 任务清单.json --out-dir D:\xxx\audio
```

- 逐块调用 worker，输出 `001.wav`、`002.wav`…（与 blocks 顺序一致）。
- 已存在且非空的同名 wav 默认跳过（断点续转）；`--force` 可强制重生成。
- 单块失败自动重试 2 次（间隔 10s/30s），仍失败则记录到 `failed.txt` 并继续后续块，不中断整批。
- 结尾块自动加 900ms 静音尾（避免戛然而止）——通过 `--tail-ms` 控制。

## 4. 合并与响度（merge_audio.py）

```powershell
python merge_audio.py D:\xxx\audio --output D:\xxx\成品.mp3 [--bgm bgm.mp3] [--bgm-volume 30] [--lufs -16]
```

- 按文件名顺序（001…NNN）无缝拼接 → 可选 BGM 叠加（默认 30 音量，约 -19.5dB）→ 整体 loudnorm 到目标响度（默认 -16 LUFS）→ 输出 mp3。
- 不传 `--bgm` 则不叠加 BGM。
- 输出后用 ffprobe 校验时长与响度（见下）。

### 响度统一原理（防止段间音量跳变）

- 各块由同一模型生成，响度天然接近；但不同音色（如童声 vs 男声）可能差几个 LU。
- `merge_audio.py` 内部：先对每块做一遍 `loudnorm`（目标 -16 LUFS）再拼接，拼接后整体再 `loudnorm` 一遍收尾（两遍式，与 pdf-to-podcast 的 normalize_loudness.py 逻辑一致）。
- 若不想逐块归一（耗时），`--skip-per-block` 可只做整体一遍；对同一模型生成的播客通常差异 ≤3 LU，可接受。

### 校验命令

```powershell
D:\TOOLS\ffmpeg\bin\ffprobe.exe -v error -show_entries format=duration -of csv=p=0 成品.mp3
D:\TOOLS\ffmpeg\bin\ffmpeg.exe -i 成品.mp3 -af volumedetect -f null -   # 看 mean/max volume
```

## 5. 与已有工具的关系（参考脚本）

- `CosyVoice语音合成.py`：GUI 封装，`call_worker()` 逻辑与本技能 generate_audio.py 等价（参数构造一致），可用作单条试听。
- `音频合并工具.pyw`：GUI/CLI 合并工具，**按目标时长动态分组输出多文件**（CLI `--input/--output/--duration/--format/--bgm/--bgm-volume`）。如需整部单文件成品，`--duration` 必须 ≥ 总时长（否则会被拆成多个文件）；本技能的 merge_audio.py 已内置单文件合并 + 响度统一，推荐优先使用。
- 在线通道（text_to_audio_plus + mediakit）由 `pdf-to-podcast` 技能覆盖，本技能只走本地 CosyVoice。

## 5.5 语速与时长校准（实测数据）

| 项目 | 实测值（2026-10-12《清平乐·村居》） |
|---|---|
| 脚本 | 6650 字 / 112 块 |
| 成品 | 1455.2 秒（24.3 分钟），mp3 128k |
| 块间静音 | 400ms × 111 ≈ 44.4 秒（merge 默认 `--gap-ms 400`） |
| 纯语音速率 | ≈ 4.7 字/秒 |
| 含静音整体 | ≈ 100 字 / 22 秒（0.219 秒/字） |

**规划口径（写脚本时用，勿沿用在线通道"每段110秒/16段"）**：目标 30 分钟 ≈ **8100–8300 字**；20 分钟 ≈ 5500 字；10 分钟 ≈ 2700 字。
**估算公式**：成品秒数 ≈ 字数 × 0.212 + 块数 × 0.4。
若未来模型或语速变化，以最近一部成品的（字数、块数、成品秒数）重算本表，并把新数据写回此处。

## 6. 故障排查速查

| 现象 | 原因/处理 |
|---|---|
| `COSYVOICE_ERR import_failed` | 未在 cosyvoice conda 环境跑 / PYTHONPATH 不对（脚本会自动设置，确认 conda_python 路径正确） |
| `COSYVOICE_ERR model_load_failed` | 模型目录不存在或不完整，检查 `D:\dev\sherpa-models\CosyVoice2-0.5B` |
| `COSYVOICE_ERR prompt_audio_not_found` | 参考音频路径写错，检查 VOICE_TABLE 与 TTS 目录文件名 |
| `out of memory` | 显存不足：减少块字数（≤100字）、关其他占显存程序、或降低 batch |
| 生成成功但时长极短/静音 | 文本过短或含大量无法发音字符；检查汉字谐音化是否漏做 |
| wav 拼接后总时长对不上 | 用 ffprobe 逐块核时长，确认无 0 字节文件（failed.txt 里查） |
