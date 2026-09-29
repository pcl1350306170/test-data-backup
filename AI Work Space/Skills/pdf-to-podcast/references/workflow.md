# PDF 转 AI 播客 — 详细工作流

## 0. 输出目录

- **默认输出目录：`D:\FILES\糖蛋蛋(＾Ｕ＾)ノ~ＹＯ`**（用户未特别指定时）。
- 成品（mp3 + 脚本 md）直接放输出目录；中间产物（段落音频、标准化产物）放输出目录下的 `audio\` 子目录。
- 用户指定了其他目录时以其指定为准。

## 1. 读取 PDF

- 用 `Read` 工具读取用户提供的 PDF 绝对路径。
- 超过 10 页时用 `pages` 参数分页读取（每次最多 20 页），直到读完。
- 绘本/图文类 PDF 会返回图文混排内容；以正文文字为准，图片描述仅作场景参考。
- 读不到或路径含特殊字符时，先解决读取问题，不要凭印象写脚本。

## 2. 内容与角色分析

读完 PDF 后产出三样分析（写入交付说明或脚本开头）：

### 主线
`起因 → 出发 → 冒险（分阶段）→ 高潮 → 结局 → 主题收尾`，一句话概括每段。

### 知识点清单
列出台词中必须保留的教学点（如口诀、公式、方法技巧），这些**零删减**。

### 角色音色映射表
| 角色 | 身份/性格 | 建议音色 |
| --- | --- | --- |
| 主角 | 儿童→童声、成人→对应年龄感 | 清亮/活泼等 |
| 向导/长辈 | 温柔/沉稳 | 柔和女声、老年男声等 |
| 搞笑担当 | 爱吹牛/跳脱 | 夸张男声、语速快 |
| 配角 | 机灵/憨厚/幼小 | 轻快、低沉、软糯童声 |
| 旁白/主播 | 串场 | 成熟男/女主播声 |

音色靠 prompt 文字描述实现（性别+年龄感+音色+语气+语速）。

## 3. 时长与分段规划

- 每段目标 **110 秒左右**（受单次 120 秒上限约束，留余量）。
- 每段字数 **450–520 字**（中文广播语速实测约 440 字/110 秒）。
- 段数 = 目标秒数 ÷ 110，向上取整。示例：
  - 30 分钟 → 16 段（约 7700 字）
  - 20 分钟 → 11 段
  - 10 分钟 → 6 段
- 按内容结构分配段落（开场/各章节/高潮/结尾），每段一个主题。

## 4. 撰写广播脚本

按 `assets/播客脚本模板.md` 的结构写完整脚本，保存为工作目录下的 md 文件。

**每段结构四步法**（针对故事/教程类内容）：
1. 开场钩子（引入本段主题/场景）
2. 内容主体（双人对话演绎，知识讲解）
3. 互动小结（提问听众/总结要点）
4. 转场（衔接下一段）

**删减规则**（对比原文压缩时）：
- 教学知识点、主线情节零删减；
- 删除重复桥段（口头禅复读、同质互动模式、过渡性描述）；
- 为"听"重构：新增开场白、听众互动、结尾收尾（原文没有，是广播形式所需）；
- 时长约束决定压缩幅度。

## 5. 逐段生成音频

对每段调用 `text_to_audio_plus`，一次一段，prompt 格式：

```
{播客类型}《{标题}》第{N}段：男声为{音色描述}（{称呼}），女声为{音色描述}（{称呼}），双人对话演绎，语气{风格}，适合{受众}收听。内容：{完整台词，按 男：...女：... 标注}
```

要点：
- prompt 必须包含声音要求 + 完整台词，不能只给待朗读文本；
- 台词里的对话内容直接写出来，角色提示词（如"汤姆说"）可保留以辅助语气；
- 不传 `duration` 参数（由内容长度自然决定）；
- 每段返回一个音频 URL，立即记录 URL 与段号对应关系（第1段→seg01…）。

## 6. 下载与时长校验

```powershell
New-Item -ItemType Directory -Force "<输出目录>\audio" | Out-Null
Invoke-WebRequest -Uri "<音频URL>" -OutFile "<输出目录>\audio\seg01.wav"
& "D:\TOOLS\ffmpeg\bin\ffprobe.exe" -v error -show_entries format=duration -of csv=p=0 "<文件路径>"
```

- 逐段下载全部段落（段数多时用循环，URL 存在哈希表里按序取）。
- 用 ffprobe 统计每段时长和总时长，与目标对比：
  - 单段超 120 秒 → 该段脚本字数过多，重生成；
  - 总时长偏差超过目标 ±10% → 增删段或调整结尾段。
- 注意：生成服务偶发失败，报错时重试一次，仍失败则报告。

## 7. 响度标准化（拼接前必做）

多段拼接音量不一致的根源是各段感知响度（LUFS）不同；目标是让所有段落归一化到统一 LUFS，保证段间无跳变。

### 目标值
| 场景 | 目标响度 | 峰值上限 |
| --- | --- | --- |
| 中文播客/有声内容 | -16 LUFS | -1.5 dBTP |
| 广播标准 (EBU R128) | -23 LUFS | -1.0 dBTP |

### 逐段标准化（自动）
运行技能自带脚本，两遍式 loudnorm 线性归一（最稳，段间无跳变）：

```powershell
python "<技能目录>\pdf-to-podcast\scripts\normalize_loudness.py" "<工作目录>\audio\seg*.wav" --lufs -16
```

- 输出：每段生成 `norm_segNN.wav`（44.1kHz 立体声），并打印"处理前→处理后"响度报告；
- 脚本依赖 ffmpeg（默认 `D:\TOOLS\ffmpeg\bin\ffmpeg.exe`，可用 `--ffmpeg` 覆盖）；
- 处理前先用 `--lufs` 确认目标值，播客默认 -16，广播标准用 -23；
- 脚本失败（无法解析测量/归一失败）时，检查 ffmpeg 路径与文件格式，或对单段手动重跑。

### 拼接前快速检测（可选，用于判断是否需要处理）
```powershell
ffmpeg -i seg01.wav -af ebur128 -f null - 2>&1 | Select-String "I:"
```
- 各段 Integrated 响度差 ≤ 1~2 LU：直接拼接，拼接后整体收尾即可；
- 任意两段差 > 3 LU：必须逐段标准化后再拼接（直接跑上面的脚本即可覆盖此情形）。

## 8. 拼接（使用标准化后的段落）

```powershell
$dir = "<输出目录>\audio\norm"
$files = (1..16 | ForEach-Object { Join-Path $dir ("norm_seg{0:d2}.wav" -f $_) }) -join ","
mediakit-cli editing concat-audio --audio-urls "$files" --format mp3
```

- 异步任务：记录返回的 `task_id`，轮询 `mediakit-cli shared query-task --task-id <task_id> --poll-complete`。
- 结果含 `audio_url` 与 `duration`，确认时长后下载。
- 若未运行脚本而直接拼接，则跳过第 7 步的逐段归一，但第 9 步的整体 loudnorm 仍然必做。

## 9. 整体响度收尾与淡入淡出

### 整体 loudnorm（拼接后必做）
对拼接产物整体再做一遍响度标准化，消除残余差异并保证整条达标：

```powershell
ffmpeg -i "<拼接产物.mp3>" -af loudnorm=I=-16:TP=-1.5:LRA=11 -ar 44100 "<工作目录>\podcast_norm.mp3"
```

- 单遍 loudnorm 对整体已足够（逐段差异已在前一步处理）；
- 想更精确可用两遍式：先 `-af loudnorm=print_format=json` 测量，再带 measured 值线性归一（命令同第 7 步脚本逻辑，单文件场景）。

### 淡入淡出
```powershell
mediakit-cli editing fade-audio --audio-url "<整体归一产物路径>" --fade-in-duration 3 --fade-out-duration 5 --format mp3
```

- 同样异步，轮询后下载最终成品到默认输出目录（`D:\FILES\糖蛋蛋(＾Ｕ＾)ノ~ＹＯ`，用户未指定时），命名为中文名（如 `《书名》-双人播客.mp3`）。

## 10. 最终验证与交付

1. ffprobe 验证成品时长/格式：
   ```powershell
   ffprobe -v error -show_entries format=duration,format_name -of default=noprint_wrappers=1 "<成品路径>"
   ```
2. 响度/非静音检查：`ffmpeg -i "<成品>" -af volumedetect -f null -`，mean_volume 正常约 -16 ~ -22 dB，max_volume 接近但不超过 0 dB（无削波）。
3. 用 `present_files` 一次交付：成品 mp3 + 配套脚本 md。
4. 交付说明里写明：时长、播音员配置（男/女声风格）、目标响度、内容结构、可调整项。

## 关键工具与限制速查

| 能力 | 工具/命令 | 限制 |
| --- | --- | --- |
| 读 PDF | `Read` | 每次 ≤20 页，长文档分页 |
| 生成人声 | `text_to_audio_plus` | 单次 ≤120 秒；不传 duration |
| 参考音色 | `audio_to_audio_plus` | 1–3 条参考音频 |
| 逐段响度标准化 | `scripts/normalize_loudness.py` | 需 ffmpeg；输出 norm_*.wav |
| 响度检测 | ffmpeg `ebur128` / `volumedetect` | — |
| 整体响度归一 | ffmpeg `loudnorm` | 拼接后必做 |
| 拼接 | `mediakit-cli editing concat-audio` | 异步，≤100 个输入 |
| 淡入淡出 | `mediakit-cli editing fade-audio` | 异步 |
| 时长校验 | ffprobe（`D:\TOOLS\ffmpeg\bin\ffprobe.exe`） | — |
