# Flow Launcher 插件合集

本目录包含 4 个自研 Flow Launcher 插件，均为 Python 编写。

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

---

## 4. NPM Runner — 前端项目一键运行/打包

**触发关键字：** `npm`

### 功能

扫描配置目录下的前端项目（含 `package.json`），输入关键字快速匹配，按项目配置的 **node 版本自动切换**，选择 `run dev` / `run build` 等脚本后，启动一个**可见的 PowerShell 窗口**运行。无需手动 `nvm use`。支持 **npm / pnpm**（可配置，配置了 pnpm 则优先用 pnpm）。

### node 版本切换原理

不使用 `nvm use`（需管理员权限、改全局软链），而是把目标版本目录（如 `D:\dev\nvm\v14.19.1`）**前置到该 PowerShell 窗口的 `PATH`**，使窗口内的 `node/npm` 即为指定版本。**免提权、不影响全局**。

### 使用方法

| 操作 | 说明 |
|------|------|
| `npm` | 列出所有扫描到的前端项目（副标题显示 node 版本 + 包管理器） |
| `npm template` | 按关键字匹配项目（如 `template1.5.0`、`template1.5.2`） |
| 选中项目 **回车** | 进入该项目的**命令选择列表**（默认脚本置顶） |
| 命令列表再 **回车** | 用配置的 node 版本 + 包管理器执行命令（新开 PowerShell 窗口） |
| 命令列表选 `↩ 返回项目列表` | 返回上一级（退格删除路径也能回到搜索） |
| `npm template build` | 末尾直接指定脚本，回车**跳过列表直接执行**（支持 `dev`/`d`/`build`/`b`/`serve`/`s`/`start`） |
| 选中项目 **右键/上下文菜单键** | 同样可弹出脚本列表（备用入口） |

> 命令列表默认把 `dev`（或项目配置的脚本）置顶，**连续两次回车即可直接运行**；无 `dev` 时依次取 `serve`、`start`。

### 配置说明

编辑插件目录下的 `settings.json`：

```json
{
    "scan_dirs": [                          // 要扫描前端项目的目录
        {"path": "D:\\CODE\\Yarward\\门诊", "depth": 1}
    ],
    "default_node": "14.19.1",             // 未单独配置的项目使用的默认 node 版本
    "package_manager": "auto",             // 包管理器：auto / pnpm / npm
    "nvm_home": "",                        // nvm 安装目录，为空则自动读 NVM_HOME 环境变量
    "chrome_path": "C:\\Users\\...\\chrome.exe", // 自动打开的浏览器（尽力而为，可留空）
    "default_script": "dev",               // 兜底默认脚本
    "max_results": 30,
    "cache_minutes": 5,
    "projects": {                          // 每个项目单独指定 node 版本 / 包管理器
        "D:\\CODE\\Yarward\\门诊\\template1.5.0": {"node": "14.19.1"},
        "D:\\CODE\\Yarward\\门诊\\template1.5.2": {"node": "16.20.2", "pm": "pnpm"}
    }
}
```

- `projects` 按**项目绝对路径**为 key，`node` 指定版本、`pm` 指定包管理器（`pnpm`/`npm`）；不配置则用全局默认
- `package_manager` 包管理器：`auto`（有 `pnpm-lock.yaml` 就用 pnpm，否则 npm）/ `pnpm`（全局强制 pnpm）/ `npm`（全局强制 npm）
- 优先级：**项目级 `pm`** > 全局 `package_manager` > `auto` 自动判断；即“配置了 pnpm 就优先用 pnpm”
- pnpm 在当前 node 版本不可用时会**自动回退 npm** 并给出提示
- 想让某个项目自动打开指定 Chrome：填 `chrome_path`（通过 `BROWSER` 环境变量生效，部分脚手架支持）

### 注意事项

- 需要已安装 [nvm-windows](https://github.com/coreybutler/nvm-windows)，且目标版本已 `nvm install`
- 运行/打包会在**新的 PowerShell 窗口**中执行，dev 服务常驻、关闭窗口即停止

