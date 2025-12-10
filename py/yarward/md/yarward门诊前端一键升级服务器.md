2025/12/10
---

* 使用python写一个关于【yarward门诊前端一键升级服务器】的脚本
* 具体需求如下
* 可视化操作，保存为“pyw”
* 输入或者选择要升级的服务器，写入配置
* 从配置里面读取服务器密码，没有保存这个服务器密码，则使用其他的服务器密码尝试（都是自己的测试服务器，密码都一样！），都不行就提示手输，用户名都是root，登录这个服务器进行升级
* 可以选择2种升级方式：目录升级、压缩包升级
* 目录升级：选择项目目录，目录下必须要有2个目录【dist】【lib-render-dist】，没有不能升级，提示先打包
  * 清空服务器“/home/ym_clinic/ym801s/webapps/tpleditor/design”目录下的所有文件， dist 目录下的所有文件覆盖到 “/home/ym_clinic/ym801s/webapps/tpleditor/design”目录下
  * 清空服务器“/home/ym_clinic/ym801s/webapps/tpleditor/resource/js/render-design”目录下的所有文件， lib-render-dist 目录下的所有文件覆盖到 “/home/ym_clinic/ym801s/webapps/tpleditor/resource/js/render-design”目录下
* 压缩包升级
  * 选择压缩包，解压获取里面的文件，比如解压后的文件夹名称是【YM-801S-TLSS-V1.5.1.252241.01001-DZSSLYY-FE】
  * 【YM-801S-TLSS-V1.5.1.252241.01001-DZSSLYY-FE】里面必须包含【design】【resource】2个目录
    * 清空服务器“/home/ym_clinic/ym801s/webapps/tpleditor/design”目录下的所有文件， 【YM-801S-TLSS-V1.5.1.252241.01001-DZSSLYY-FE\design】 目录下的所有文件覆盖到 “/home/ym_clinic/ym801s/webapps/tpleditor/design”目录下
    * 清空服务器“/home/ym_clinic/ym801s/webapps/tpleditor/resource/js/render-design”目录下的所有文件，【YM-801S-TLSS-V1.5.1.252241.01001-DZSSLYY-FE\resource\js\render-design】目录下的所有文件覆盖到 “/home/ym_clinic/ym801s/webapps/tpleditor/resource/js/render-design”目录下 
* 点击一键升级按钮，开始升级，给我展示进度和提示
* 配置文件引入方式如下：
    * 绝对路径引入配置文件的代码，确保无论脚本在何处执行，都能准确定位到配置文件
    *  配置在“CONFIG_PATH”的json里面
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
