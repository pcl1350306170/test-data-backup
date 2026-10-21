---
name: create-local-web-service
description: 快速搭建本地 Web 服务（FastAPI 后端 + 静态前端），自动集成到本地服务大厅 Hub。当用户需要创建新的本地 web 服务、Python 后台联动项目、或提到"新建服务"时使用此技能。
---

# 创建本地 Web 服务

## 适用场景

- 新建 FastAPI + 静态前端的本地 web 服务
- 需要与 Hub（本地服务大厅）集成
- Python 后端 + HTML/JS/CSS 前端联动项目

## 标准项目结构

```
new_service/
├── server.py              # FastAPI 后端主文件
├── start.bat              # 启动脚本（pause 结尾）
├── static/                # 前端静态文件
│   ├── index.html         # 主页面
│   ├── js/
│   │   └── app.js         # 前端逻辑
│   └── css/
│       └── style.css      # 样式
├── data/                  # 数据和配置存储
│   └── config.json        # 持久化配置（可选）
├── core/                  # 业务逻辑模块（可选）
│   ├── __init__.py
│   └── engine.py
└── requirements.txt       # Python 依赖（可选）
```

## 开发步骤

### 1. 创建项目目录

在 `py/local_services/` 下创建新目录（如果是通用服务）或 `py/` 下（如果是独立项目）：

```bash
mkdir py\local_services\new_service
cd py\local_services\new_service
```

### 2. 创建 server.py 模板

```python
# -*- coding: utf-8 -*-
"""服务名称 - 简短描述"""
import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── 路径与常量 ────────────────────────────────────────

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"

# ── 配置管理 ─────────────────────────────────────────

DEFAULT_CONFIG = {
    # 在这里定义默认配置项
    "port": 8800,  # 避免与现有服务冲突：8000(novel_agent), 8010(voice_notes), 8020(voice_tts), 8642(podcast_web), 8700(hub)
}

def load_config():
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)

# ── FastAPI 应用 ─────────────────────────────────────

app = FastAPI(title="服务名称")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/config")
async def get_config():
    return load_config()

@app.post("/api/config")
async def update_config(cfg: dict):
    current = load_config()
    current.update(cfg)
    save_config(current)
    return {"ok": True}

# ── 启动入口 ─────────────────────────────────────────

if __name__ == "__main__":
    cfg = load_config()
    port = cfg.get("port", 8800)
    
    print("=" * 50)
    print(f"  服务名称 Web 服务已启动")
    print(f"  本机访问:   http://127.0.0.1:{port}")
    print(f"  按 Ctrl+C 停止服务")
    print("=" * 50)
    
    uvicorn.run(app, host="0.0.0.0", port=port)
```

### 3. 创建 start.bat

```batch
@echo off
cd /d "%~dp0"
python server.py
pause
```

### 4. 创建前端文件

**static/index.html**:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>服务名称</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <h1>服务名称</h1>
        <div id="app"></div>
    </div>
    <script src="/static/js/app.js"></script>
</body>
</html>
```

**static/js/app.js**:
```javascript
// 前端逻辑
async function loadConfig() {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    // 处理配置
}

loadConfig();
```

**static/css/style.css**:
```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5;
    padding: 20px;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    background: white;
    border-radius: 8px;
    padding: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
```

### 5. 注册到 Hub

编辑 `py/local_services/hub/services.json`，在 `services` 数组中添加：

```json
{
  "id": "new_service",
  "name": "服务显示名称",
  "icon": "🔧",
  "desc": "服务简短描述",
  "path": "D:\\CODE\\Python\\test-data-backup\\py\\local_services\\new_service",
  "cmd": ["python", "server.py"],
  "port": 8800,
  "health_path": "/",
  "checks": [
    {"type": "exe", "target": "ffmpeg", "label": "ffmpeg 在 PATH（如需要）"}
  ]
}
```

**字段说明**：
- `id`: 唯一标识（小写，下划线分隔）
- `name`: Hub 页面显示名称
- `icon`: emoji 图标
- `desc`: 一句话描述
- `path`: 项目绝对路径
- `cmd`: 启动命令（Hub 会自动将 python 替换为 pythonw）
- `port`: 服务端口（避免冲突：8000/8010/8020/8642/8700 已占用）
- `health_path`: 健康检查路径
- `checks`: 依赖预检（可选）

### 6. 添加 QuickFolderOpen 快捷方式（可选）

编辑 `flow-launcher-plugin/FlowLauncher.QuickFolderOpen/config.json`，在 `file_shortcuts` 数组中添加：

```json
{
    "name": "快速启动web页面-服务名称",
    "keywords": ["关键词1", "关键词2"],
    "path": "D:\\CODE\\Python\\test-data-backup\\py\\local_services\\new_service\\start.bat"
}
```

## 最佳实践

### 子进程调用

如果需要调用外部命令（如 ffmpeg），使用 `CREATE_NO_WINDOW` 避免黑窗：

```python
import subprocess
import sys

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

result = subprocess.run(
    ["ffmpeg", "-i", "input.mp3", "output.wav"],
    capture_output=True,
    text=True,
    creationflags=_NO_WINDOW
)
```

### 配置持久化

使用 JSON + pathlib，避免 configparser + INI：

```python
from pathlib import Path
import json

CONFIG_PATH = BASE_DIR / "data" / "config.json"

def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)  # 原子写入
```

### 日志输出

FastAPI/uvicorn 会自动输出访问日志。如需自定义日志：

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)
```

### SSE 实时进度推送（可选）

如果需要推送任务进度：

```python
from asyncio import Queue
from collections import defaultdict

subscribers = defaultdict(set)

@app.get("/api/task/progress")
async def progress_stream():
    queue = Queue()
    subscribers["task_id"].add(queue)
    try:
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        subscribers["task_id"].discard(queue)

# 在业务逻辑中发送事件
def emit_event(task_id, event):
    for queue in subscribers.get(task_id, []):
        asyncio.get_event_loop().call_soon_threadsafe(queue.put_nowait, event)
```

## 端口分配

现有服务端口表（避免冲突）：

| 服务 | 端口 | 说明 |
|------|------|------|
| novel_agent | 8000 | AI 小说生成 |
| voice_notes | 8010 | 语音速记本 |
| voice_tts | 8020 | CosyVoice 语音合成 |
| podcast_web | 8642 | 本地播客制作 |
| hub | 8700 | 本地服务大厅 |
| **新服务** | **8800+** | 从 8800 开始递增 |

## 测试清单

- [ ] server.py 能正常启动（`python server.py`）
- [ ] 前端页面能正常访问（http://127.0.0.1:端口）
- [ ] Hub 能正确识别服务状态（stopped/running）
- [ ] Hub 启动服务时不弹出黑窗（使用 pythonw）
- [ ] Hub 停止服务时能正确杀进程
- [ ] 日志输出到 hub/logs/{service_id}.log
- [ ] 配置持久化正常工作（如有）

## 参考项目

- **简单架构**: [voice_notes](file:///d:/CODE/Python/test-data-backup/py/voice_notes) - 单文件后端
- **分层架构**: [voice_tts](file:///d:/CODE/Python/test-data-backup/py/voice_tts) - core/ + static/ + data/
- **SSE 推送**: [podcast_web](file:///d:/CODE/Python/test-data-backup/AI%20Work%20Space/Skills/pdf-to-local-podcast/web) - 任务进度实时推送
