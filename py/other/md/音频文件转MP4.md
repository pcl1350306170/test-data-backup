2026/1/28
---

* 使用python写一个关于【把音频文件转为mp4】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 可以输入/选择【ffmpeg路径】，默认“D:\TOOLS\ffmpeg”，写入配置
* 可以输入/选择【音频文件】，写入配置，音频支持常见格式：.wav, .mp3, .flac, .aac 等
* 可以输入【转换mp4文件名】，默认和音频文件一样
* 可以输入/选择【转换视频显示的静态图片】，写入配置，图片支持：.jpg, .png, .bmp
* 可以输入/选择【mp4输出路径，默认“D:\FILES\视音频”】，写入配置
* 转换参数细节（关键！）
  使用 FFmpeg 命令：
*  ffmpeg -loop 1 -i image.jpg -i audio.wav -c:v libx264 -tune stillimage -c:a aac -b:a 192k -shortest -pix_fmt yuv420p output.mp4
*  必须包含 -pix_fmt yuv420p（否则手机/微信无法播放）
*  必须包含 -shortest（视频长度 = 音频长度）

---

使用 Python 写一个将音频文件转为 MP4 视频的图形化脚本，保存为 .pyw 文件（无控制台窗口）。具体需求如下：

1. **界面要求**：
  - 使用 tkinter 构建简洁 GUI
  - 包含三个输入区域（带“浏览”按钮）：
    * FFmpeg 路径（默认 "D:\TOOLS\ffmpeg\ffmpeg.exe"）
    * 音频文件（支持 .wav/.mp3/.flac/.aac）
    * 静态图片（支持 .jpg/.png/.bmp）
    * 可以输入/选择【mp4输出路径，默认“D:\FILES\视音频”】，写入配置
    * 可以输入转换mp4文件名，默认和音频文件一样
  - 一个“开始转换”按钮
  - 底部状态栏显示操作日志

2. **功能逻辑**：
  - 启动时从 config.json 加载上次配置（若存在）
  - 点击“浏览”时，文件对话框应过滤对应文件类型
  - 转换命令必须包含：
    - `-loop 1`（循环图片）
    - `-shortest`（视频长度=音频长度）
    - `-pix_fmt yuv420p`（确保全平台兼容）
    - 音频编码为 AAC（-c:a aac -b:a 192k）
  - 输出 MP4 与音频文件同目录，同文件名（仅扩展名不同）

3. **健壮性**：
  - 验证 FFmpeg 路径是否存在，若不存在则报错
  - 转换前检查输入文件是否存在
  - 捕获 subprocess 执行异常并显示错误信息
  - 转换成功后弹出提示，并提供“打开文件夹”选项

4. **配置持久化**：
  - 关闭程序时保存配置
  - 下次启动自动填充输入框
---
* 配置文件引入方式如下：
  * 绝对路径引入配置文件的代码，确保无论脚本在何处执行，都能准确定位到配置文件
  * 配置在“CONFIG_PATH”的json里面
  * 通用数据库配置：DB_CONFIG_PATH，都是在运行脚本的父级目录的json文件夹，里面的DB_CONFIG.json【脚本用不到本地数据库就不用引入了】
* 可视化操作给我加上合适的操作按钮
* 记录操作日志“PROCESS_LOG_FILE”

```python
# 配置与常量
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "XXXX_XXXX" #脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
```

DB_CONFIG_PATH数据如下：

```
{
  "host": "localhost",
  "port": 3306,
  "user": "root",
  "password": "123456",
  "database": "test",
  "charset": "utf8mb4"
}

```
