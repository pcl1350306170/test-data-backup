2025/12/3
---

* 使用python写一个关于【提取电脑播放的声音导出mp3】的脚本
* 具体需求如下
* 可视化操作。
* 点击开始录制，自动获取当前电脑播放的声音
* 点击结束录制，录制结束，导出录制出来的声音，并转为mp3
* 可以选择mp3导出目录-保存为配置文件
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
---

“Cable Output”（通常显示为 VB-CABLE Output、CABLE Output (VB-Audio Virtual Cable) 等）是来自 VB-Audio Virtual Cable 软件的虚拟音频设备。

✅ 它是什么？

VB-Audio Virtual Cable 是一个 Windows 上常用的免费虚拟音频线缆工具，作用是：
将一个程序的音频输出，当作另一个程序的音频输入。
它会创建一对设备：
CABLE Input（录音设备）← 用于接收音频
CABLE Output（播放设备）← 用于发送音频

但注意：
在 录音/输入设备列表 中看到的 “CABLE Output” 实际上是 虚拟线缆的输出端被系统识别为可录制的源 —— 这其实是 可以用来录系统声音的！

🔍 为什么你会在“录音设备”里看到 “Cable Output”？

当你安装了 VB-Cable 或 VoiceMeeter 等工具后：
系统会把 CABLE Output 暴露为一个可录制的输入源（类似“立体声混音”）
实际上它是虚拟线缆的回环输出，如果你把系统声音路由到它，就能录到

✅ 所以：如果你正确配置了音频路由，Cable Output 是完全可以用来录制系统声音的！

🎯 能用它来替代“立体声混音”吗？

可以，而且很多时候更稳定！

对比项 立体声混音（Stereo Mix） CABLE Output（VB-Cable）
------- ------------------------ ------------------------
是否内置 是（但很多电脑厂商禁用了） 否（需手动安装）
兼容性 部分 Realtek 声卡不支持 所有 Windows 电脑可用
延迟 低 极低（<10ms）
配置难度 简单（启用即可） 需要设置默认播放设备
可靠性 经常消失或灰色不可用 安装后始终可用

⚙️ 如何正确使用 “Cable Output” 录制系统声音？
步骤 1：确认已安装 VB-Cable
下载地址：https://vb-audio.com/Cable/
安装后重启电脑
步骤 2：将系统声音输出切换到 CABLE Input
注意：这里容易混淆！
打开 声音设置 → 输出设备
选择 CABLE Input (VB-Audio Virtual Cable) 作为默认播放设备

这样，所有系统声音（音乐、视频等）都会被发送到虚拟线缆。
步骤 3：在你的录音脚本中选择 CABLE Output 作为输入设备

因为：
CABLE Input = 播放端（你把声音“送进去”）
CABLE Output = 录音端（你可以从这里“读出来”）

所以你的 Python 脚本应该捕获 “CABLE Output” 设备。

✅ 在你的 record_system_audio.py 中是否能自动识别？

当前代码匹配关键词：
python
if any(kw in name_lower for kw in ['stereo mix', 'what you hear', '立体声混音', 'loopback']):

但 “CABLE Output” 不包含这些词，所以会被跳过，回退到麦克风！

🔧 修复方法：增加对 VB-Cable 的支持

修改设备匹配逻辑：

python
新增对 VB-Cable 和 VoiceMeeter 的支持
VIRTUAL_CABLE_KEYWORDS = [
'stereo mix', 'what you hear', '立体声混音', 'loopback',
'cable output', 'vb-audio', 'voicemeeter', 'virtual audio'
]

for i in range(self.p.get_device_count()):
dev_info = self.p.get_device_info_by_index(i)
if dev_info['maxInputChannels'] > 0:
name_lower = dev_info['name'].lower()
if any(kw in name_lower for kw in VIRTUAL_CABLE_KEYWORDS):
device_index = i
self._log(f"选中录音设备: {dev_info['name']} (索引 {i})")
break

这样，只要设备名含 cable output，就会被自动选中。

🧪 验证是否成功

1. 播放一段音乐
2. 将系统默认播放设备设为 CABLE Input
3. 运行你的脚本，开始录制
4. 停止后检查 MP3 —— 应该有声音！
   💡 如果还是无声，请检查：是否真的把播放设备切到了 CABLE Input？很多人误以为选“CABLE Output”播放，其实应该选 CABLE Input 播放！

✅ 总结

问题 回答
------ ------
“Cable Output” 是什么？ VB-Audio 虚拟音频线缆的录音端
能用来录系统声音吗？ ✅ 可以，且推荐使用
为什么我的脚本没选它？ 当前代码没匹配 cable 关键词
怎么用？ 1. 播放设备设为 CABLE Input<br>2. 录音设备选 CABLE Output
✅ 结论：只要你正确配置音频路由，“Cable Output” 是录制系统声音的绝佳选择！

![配置图](https://raw.githubusercontent.com/pcl1350306170/test-data-backup/refs/heads/main/img/md/Snipaste_2025-12-17_10-57-29.png)
