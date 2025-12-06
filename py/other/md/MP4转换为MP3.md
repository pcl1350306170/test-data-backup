2025/12/6
---

* 使用python写一个关于【MP4转换为MP3】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 选择一个或多个Mp4文件
* 可以使用ffmpeg，path获取不到就手动选，写入配置
* 输入开启几个线程转换，写入配置
* 可以选择导出目录，写入配置
* 可以看到转换进度
* 配置文件引入方式如下：
    * 绝对路径引入配置文件的代码，确保无论脚本在何处执行，都能准确定位到配置文件
    * 配置在“CONFIG_PATH”的json里面
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
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}"
```

