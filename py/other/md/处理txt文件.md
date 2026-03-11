2026/3/11
---

* 使用python写一个关于【处理txt文件】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 可以输入/选择【需要处理的txt文件】，写入配置
* 可以输入/选择【是否覆盖原文件】，默认否，写入配置
* 可以输入【每行字数】，写入配置
* 点击开始处理，把txt文件里面，每行字数超过“每行字数”的那一行删除
* 文件保存为utf-8编码保存
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
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
```

