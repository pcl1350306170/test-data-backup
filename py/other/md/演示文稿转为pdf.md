2026/2/3
---

* 使用python写一个关于【多个pdf合并为一个】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 可以输入/选择【需要合并pdf文件】，写入配置
* 可以输入/选择【转换后的输出目录】，写入配置
* 增加按钮【开始、结束、暂停】
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
