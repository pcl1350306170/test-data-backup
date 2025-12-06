2025/12/6
---

* 使用python写一个关于【爬取YouTube视频】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 可以输入一个或多个视频地址，写入配置
* 增加进度显示、暂停继续功能
* 输入开启线程，写入配置
* 可以选择直接下载视频可以选择清晰度
* 可以转为音频，选择格式
* 可以选择保存目录，写入配置
* 可以配置下载重试次数-保存为配置文件D:\book\封面
* 配置文件引入方式如下：
    * 绝对路径引入配置文件的代码，确保无论脚本在何处执行，都能准确定位到配置文件
    *  配置在“CONFIG_PATH”的json里面
* 可视化操作给我加上合适的操作按钮
* 记录操作日志“PROCESS_LOG_FILE”


```python
# 配置与常量
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "XXXX_XXXX" #脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
```
---
* 提示：正在处理: https://www.youtube.com/watch?v=DL_wfKddoLs&list=PLd9hCvj34W5hZxGsu5etKF6bZ9w4Ap2hl
  ⚠️ 第 1 次尝试失败: HTTP Error 400: Bad Request
* 使用 FFmpeg 转码为 mp3 / wav / flac【可选择，写入配置】

---

GPT版本
* 修改这个脚本
* 所有按钮、提示等改为中文
* SCRIPT_NAME 使用“youtube_downloader_gpt”
* 如果没有获取到“ffmpeg”，可以手动选择

