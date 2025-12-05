2025/12/2
---

* 使用python写一个关于【拆分英语句子为单个单词】的脚本
* 具体需求如下
* 可视化操作
* 选取某一个json文件，里面是一个单词数组，写入配置，拆出来的单词写入这个json的word，如果已经存在，则不写入，格式如下：
  ```json
  [
    {
    "Word":"ephemeral",
    "Phonetic":"",
    "Meaning":"",
    "Example":"",
    "ExampleTranslator":"",
    "Audio":"",
    "ExampleAudio":""
    }
  ]
  ```

* 可以输入不需要写入json文件的单词，比如the、or、and等，少于3个字母的单词默认不写入-保存为配置文件
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
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
```
---
完善words.json的里面的单词和例子，要求：
1. 完善这个json内容，如果json里面有些字段已经存在了【Example、ExampleTranslator】不用替换。
2. 如果不存在，就给我生成一个例子和翻译，要贴近技术。
3. 如果json里面的单词是xx的复数、现在或过去分词，给我替换为xx，并说明xx的复数是什么或者现在或过去分词是什么。
4. 需要的数据格式是：
```json
{"Word": "Serialization","Phonetic": "英 [ˌsɪəriəlaɪˈzeɪʃn]，美 [ˌsɪriəlaɪˈzeɪʃn]","Meaning": "序列化（Java 中将对象转换为字节流的过程，用于对象的持久化或网络传输）","Example": "A Java class must implement the Serializable interface to support object serialization.","ExampleTranslator": "Java 类必须实现 Serializable 接口才能支持对象序列化。","Audio": "","ExampleAudio": ""}
```

---

