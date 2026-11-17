# asset_api.py 外部使用说明

> 脚本位置：`py/other/asset_api.py`
> 用途：把文本/md 内容保存到远程资产库（geeker/public/assets），供其他脚本或外部 AI 助手调用。
> 接口约定：`GET ?keyword=标题` 查重（`data.total>0` 视为已存在）+ `POST JSON` 保存，均以响应 `code==200` 判定成功。

---

## 一、前置条件

| 条件 | 说明 |
|---|---|
| Python + requests | 系统 Python（`D:\dev\python`）已装 requests 可直接用；项目 `.venv` 未装，用前需 `pip install requests` |
| 资产库服务在线 | 默认接口 `http://localhost/api/geeker/public/assets`，服务未启动时调用会报「查重请求失败」 |
| 内容编码 | md 文件必须 UTF-8，且**第一行一级标题 `# 标题` 决定资产标题**（CLI 模式） |

## 二、CLI 参数速查

```powershell
python d:\CODE\Python\test-data-backup\py\other\asset_api.py <md文件路径> [选项]
```

| 选项 | 默认值 | 说明 |
|---|---|---|
| `--api` | `http://localhost/api/geeker/public/assets` | 接口地址 |
| `--type` | `SOLUTION` | 资产类型 |
| `--prefix` | 空 | 标题前缀，最终标题 = 前缀 + md 一级标题 |
| `--tags` | 空 | 标签，逗号分隔，如 `--tags "标签1,标签2"` |
| `--check-only` | - | 只查重不保存 |
| `--no-check` | - | 跳过查重强制保存（会产生重复记录，慎用） |

**结果判定**（外部程序/AI 按此分支处理）：

- 退出码 `0` + 输出 `✅ 保存成功` → 新增入库
- 退出码 `0` + 输出 `↪ 已存在，跳过` → 查重命中，未写入
- 退出码 `1` + 输出 `❌ 失败: ...` → 服务离线 / 无一级标题 / 接口业务异常

## 三、AI 协作场景：用户定标题、AI 提取标签、AI 写内容

**完全可行**，标准流程如下（AI 侧执行）：

1. **AI 撰写内容**：按用户要求写好 markdown 正文（如「XXX功能总结」）。
2. **落临时文件**：把内容写入 UTF-8 编码的临时 md，**第一行必须是 `# {用户指定的标题}`**——这是 CLI 提取标题的唯一来源，用户指定的标题就放在这里。
3. **AI 提取标签**：从正文提炼 2~4 个关键词标签。
4. **调用脚本**：

```powershell
python d:\CODE\Python\test-data-backup\py\other\asset_api.py "$env:TEMP\xxx功能总结.md" --type SOLUTION --tags "标签1,标签2,标签3"
```

5. **按退出码与输出向用户汇报**：保存成功 / 已存在跳过 / 失败原因。
6. 临时 md 可保留作为本地底稿，也可删除（资产库已存全文）。

### 可直接发给 AI 的指令模板

```text
请写一份《{标题}》的功能总结，要求：{内容要求}。
完成后保存到资产库，步骤：
1. 把总结写成 markdown，第一行必须是「# {标题}」，以 UTF-8 保存到临时文件；
2. 从内容中提取 2~4 个标签；
3. 执行：python d:\CODE\Python\test-data-backup\py\other\asset_api.py "<临时文件路径>" --tags "<标签1,标签2,...>"
4. 退出码 0 且输出「✅ 保存成功」即入库成功；输出「↪ 已存在，跳过」说明资产库已有同标题资产，
   此时先告诉我，由我决定是否换标题或强制保存（--no-check），不要自行强制保存。
```

### 注意事项

- **查重按标题关键词**：用户定的标题若与库内已有资产重名（keyword 模糊匹配 total>0），会被跳过。换个更具体的标题即可，`--prefix` 不影响查重关键词。
- **PowerShell 中文输出**：管道/重定向可能显示乱码，判定结果以**退出码**为准；需要看原文时用 `$env:PYTHONIOENCODING='utf-8'` 并落 UTF-8 文件再读。
- **不要自行加 `--no-check`**：会产生重复资产，须用户确认。

## 四、import 方式（Python 脚本内复用）

不想落临时文件时，直接调 `save_asset`——**标题可显式传参，不依赖 md 一级标题**：

```python
import sys
sys.path.insert(0, r"d:\CODE\Python\test-data-backup\py\other")
from asset_api import save_asset, check_exists, save_md_file, AssetApiError

# 场景：标题用户定、内容程序/AI 生成、标签自定义
title = "XXX功能总结"          # 用户指定
content = "# XXX功能总结\n\n..."  # AI 生成的 markdown 全文
tags = ["功能总结", "XXX"]      # AI 提取

try:
    if check_exists("http://localhost/api/geeker/public/assets", title):
        print("已存在，跳过")
    else:
        save_asset(
            "http://localhost/api/geeker/public/assets",
            title, content,
            asset_type="SOLUTION",   # 自定义类型
            title_prefix="",         # 自定义前缀
            tags=tags,               # 自定义标签
        )
        print("保存成功")
except AssetApiError as e:
    print("失败:", e)
```

三个函数签名要点：

- `check_exists(api_base, keyword) -> bool`：查重，异常抛 `AssetApiError`
- `save_asset(api_base, title, content, *, asset_type, title_prefix, tags, description, language) -> dict`：保存，`description` 默认取原始 title
- `save_md_file(md_path, api_base, *, asset_type, title_prefix, tags, skip_if_exists) -> {"status": "saved"|"skipped", ...}`：读文件一站式入口（标题仍取自 md 一级标题）

## 五、已知限制

1. CLI 无 `--title` 参数，标题只能来自 md 一级标题（import `save_asset` 可显式传标题）。
2. CLI 无 stdin/`--content` 输入，内容必须先落 md 文件。
3. 未封装删除/更新接口，写错的资产需走服务端处理。