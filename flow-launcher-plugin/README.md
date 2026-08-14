# Flow Launcher 插件合集

本目录包含 3 个自研 Flow Launcher 插件，均为 Python 编写。

---

## 前置要求

- 已安装 [Flow Launcher](https://www.flowlauncher.com/)（≥ 1.8.0）
- Python 环境（插件通过 `flowlauncher` Python SDK 运行）
- 安装 SDK：`pip install flowlauncher`

安装插件：将对应插件文件夹复制到 Flow Launcher 插件目录即可（`%APPDATA%\FlowLauncher\Plugins\`），重启 Flow Launcher 自动加载。

---

## 1. NVM Switcher — Node.js 版本切换

**触发关键字：** `nv`

### 功能

基于 nvm-windows，在 Flow Launcher 中快速查看和切换已安装的 Node.js 版本。

### 使用方法

| 操作 | 说明 |
|------|------|
| `nv` | 列出所有已安装的 Node.js 版本，当前版本以 ★ 标记 |
| `nv 18` | 过滤版本号包含 `18` 的版本 |
| 选中某版本回车 | 自动以管理员权限执行 `nvm use <version>`，完成后弹出通知 |

### 注意事项

- 需要预先安装 [nvm-windows](https://github.com/coreybutler/nvm-windows) 并加入 PATH
- 切换版本需要管理员权限，执行时会弹出 UAC 提权窗口
- 切换成功后 Flow Launcher 会弹出 Toast 通知

---

## 2. Quick Folder Open — 文件夹快速打开

**触发关键字：** `kl`

### 功能

扫描指定根目录下的所有子文件夹，支持模糊搜索，选中后在资源管理器中打开。

### 使用方法

| 操作 | 说明 |
|------|------|
| `kl` | 显示已索引的目录数量和根目录名称 |
| `kl xxx` | 按关键字搜索子文件夹（支持子串匹配和模糊匹配） |
| 选中某目录回车 | 在资源管理器中打开该文件夹 |

### 配置说明

编辑插件目录下的 `config.json`：

```json
{
    "root_dirs": [          // 要扫描的根目录列表
        "D:\\CODE",
        "D:\\FILES\\IMG"
    ],
    "exclude_dirs": [       // 排除的目录名（不区分大小写）
        "node_modules",
        ".git",
        "__pycache__"
    ],
    "max_depth": 4,         // 最大扫描深度（相对于根目录）
    "max_results": 30,      // 最多显示结果数
    "cache_minutes": 10     // 目录索引缓存时间（分钟），过期自动重新扫描
}
```

### 匹配规则

- **子串匹配优先**：输入内容是目录名的子串时排在前面
- **模糊匹配其次**：输入的字符按顺序出现在目录名中即可匹配
- 不区分大小写

---

## 3. Script Runner — 脚本快捷启动器

**触发关键字：** `pj`

### 功能

通过配置将本地 Python 脚本注册为快捷命令，在 Flow Launcher 中搜索并一键运行。

### 使用方法

| 操作 | 说明 |
|------|------|
| `pj` | 显示所有已配置的命令 |
| `pj 门诊` | 按名称搜索命令 |
| `pj mcsj` | 按关键词搜索命令 |
| 选中某命令回车 | 后台运行对应的 Python 脚本 |

### 配置说明

编辑插件目录下的 `commands.json`：

```json
{
    "python_exe": "D:\\dev\\python\\pythonw.exe",   // Python 解释器路径
    "script_dir": "D:\\CODE\\Python\\...\\py",       // 脚本根目录
    "commands": [
        {
            "name": "门诊升级",              // 命令显示名称
            "keywords": ["mcsj"],            // 搜索关键词
            "script": "yarward\\menz_upgrade.pyw",  // 脚本路径（相对或绝对）
            "description": "门诊-升级"        // 描述（可选）
        }
    ]
}
```

- `script` 字段支持相对路径（自动拼接 `script_dir`）或绝对路径
- `keywords` 用于快速搜索，支持多个关键词
- 脚本以无窗口模式后台运行（`CREATE_NO_WINDOW`）

### 当前已配置的命令一览

| 分类 | 命令名称 | 关键词 | 说明 |
|------|---------|--------|------|
| **开发** | 指定分辨率浏览器 | res, browser | 开启指定分辨率的浏览器 |
| | 门诊打包（关键字匹配） | mzdb | 门诊订单打包 |
| | 门诊升级 | mcsj | 门诊前端升级 |
| | 门诊批量挂号 | mcpgh, gh | 门诊批量挂号测试 |
| | 病房打包（关键字匹配） | bfdb | 病房打包并提 SVN |
| | 病房升级 | bfsj | 病房前端升级 |
| | 病房床头卡SQL | bfcdk | 生成床头卡 SQL |
| | ADB设备管理【QTscrcpy版】 | adb, qt, scrcpy | ADB 连接（QT 版） |
| | ADB设备管理【scrcpy版】 | adb, scrcpy | ADB 连接（scrcpy 版） |
| | 快速创建Git分支 | git, branch | 快速创建 Git 分支 |
| | 创建svn目录并检出 | svn | SVN 快速检出 |
| | 部署Baseio-Web工具 | web | 部署 Web 工具 |
| **图片** | 图片裁剪（生成新文件） | tp1 | 裁剪图片生成新文件 |
| | 图片裁剪并替换原图 | tp2 | 裁剪并替换原图 |
| | 可视化图片裁剪任务 | tp3 | 可视化裁剪界面 |
| | 随机复制图片 | tp8 | 从 A 目录随机复制到 B |
| | 可视化裁剪工具 | tp11 | 可视化裁剪工具 |
| | 图片格式转换 | tp13 | 图片格式互转 |
| | 图片横竖重命名 | tp20 | 按横竖屏方向重命名 |
| | 图片提取并压缩 | tp21 | 提取目录下图片并压缩 |
| | 批量AI裁剪 | tp22 | AI 识图批量裁剪 |
| | AI图片放大增强 | tp23 | Real-ESRGAN + GFPGAN |
| | PDF转图片 | tp25 | PDF 转为图片 |
| | 按关键词删除文件 | tp26 | 根据关键词删除文件 |
| **文件** | 文件按个数分组 | wj1 | 按数量分组文件 |
| | 批量重命名【过滤章节回标点等】 | wj2 | 批量重命名 |
| | 移动文件 | wj3 | 移动文件 |
| | 批量打包ZIP加密 | wj4 | 批量打包可加密 ZIP |
| | 清理空目录 | wj5 | 删除空文件夹 |
| | 压缩包密码破解 | wj6 | 尝试破解 ZIP 密码 |
| | 文件重命名【增加前缀、后缀】 | wj7 | 批量加前后缀 |
| | 按后缀名移动文件 | wj8 | 按后缀分类移动 |
| | PPT转图片和PDF | wj9 | PPT 导出图片和 PDF |
| | 图片转PDF | wj10 | 图片合成 PDF |
| | PDF合并 | wj11 | 合并多个 PDF |
| | 文件重命名为数字 | wj12 | 按修改时间重命名 |
| | 按子目录同名清理 | wj13 | 按子目录名清理文件 |
| | Git图片Raw地址拼接 | wj14 | Git 图片 Raw URL 拼接 |
| **音视频** | MP4转MP3 | qt1 | 视频转音频 |
| | PC录音 | qt2 | 手动录音（需配置声音源） |
| | PC自动录音 | qt3 | VAD 自动录音 |
| | 音频转视频 | qt4 | 音频生成视频 |
| **电子书** | TXT文本替换 | dz1 | TXT 内容替换 |
| | 可视化TXT转EPUB | dz2 | TXT 转 EPUB |
| | EPUB替换封面和关键字 | dz3 | 替换 EPUB 元数据 |
| | 快速创建TXT | dz4 | 快速新建 TXT |
| | 快速粘贴创建TXT | dz5 | 剪贴板内容创建 TXT |
| | 批量合并TXT为EPUB | dz6 | 多个 TXT 合并 EPUB |
| | 图片整合为EPUB | dz7 | 图片生成 EPUB |
| | TXT文件合并 | dz8 | TXT 文件合并 |
