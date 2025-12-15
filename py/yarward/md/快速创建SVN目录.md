2025/12/15
---

* 使用python写一个关于【快速创建svn目录并检出】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 可以选择2个操作类型：病房、门诊，写入配置
* 可以输入svn使用的用户名密码，写入配置。
  * 病房类型默认：用户名：zhangsan 密码：888888
  * 门诊类型默认：用户名：lisi 密码：666666
* 可以输入在svn哪里地址下面新建目录，写入配置
  * 病房类型默认：https://192.168.30.124/svn/智慧病房特殊订单
  * 门诊类型默认：https://192.168.30.134/svn/门诊/YM-801S/7.特殊订单/2025年特殊订单
* 可以输入订单名称，写入配置。这个订单名称就是在svn新建的目录，如果已经存在这个目录，则直接走检出操作。
  * 例如：2025-2308江苏省中医院溧阳分院，必须是这种格式，前9个字符是订单编号，剩余字符是医院名称
  * 如果是病房类型，在svn地址后面拼接上医院名称再新建目录，例如“https://192.168.30.124/svn/智慧病房特殊订单/江苏省中医院溧阳分院”
* 选择本地的目录，将在svn新建的目录检出到这个目录下，写入配置
  * 病房类型默认：D:\CODE\Yarward\SVN
  * 门诊类型默认：D:\CODE\Yarward\SVN\0门诊
  * 检出后，自动打开检出的目录
  * 并新建一个目录“前端”
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
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
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
