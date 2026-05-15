# 📥 VLC 播放器安装指南

## ⚠️ 重要提示

**交互式时间轴编辑器需要 VLC 播放器软件才能工作！**

`python-vlc` 只是一个 Python 绑定库，它需要调用系统安装的 VLC 播放器来播放音频。

---

## 🚀 安装步骤

### **第1步：下载 VLC**

访问官方网站：
```
https://www.videolan.org/vlc/
```

或直接下载 Windows 版本：
```
https://www.videolan.org/vlc/download-windows.html
```

---

### **第2步：安装 VLC**

1. 运行下载的安装程序（如 `vlc-3.0.xx-win64.exe`）
2. 选择语言（建议中文或英文）
3. 点击"下一步"
4. 选择安装路径（默认即可）
5. 选择组件（保持默认）
6. 点击"安装"
7. 等待安装完成
8. 点击"完成"

---

### **第3步：验证安装**

#### **方法1：启动 VLC**

1. 在开始菜单搜索 "VLC"
2. 打开 VLC media player
3. 如果能正常启动，说明安装成功 ✅

#### **方法2：命令行检查**

打开 PowerShell 或 CMD，运行：
```bash
vlc --version
```

预期输出：
```
VLC media player 3.0.xx Vetinari (revision 3.0.xx-0-gxxxxxxxx)
```

---

## 🔧 常见问题

### **Q1: 安装后 python-vlc 仍然报错？**

**A:** 尝试以下步骤：

1. **重启电脑**
   - VLC 安装后可能需要重启才能被系统识别

2. **检查环境变量**
   - 确保 VLC 安装目录已添加到 PATH
   - 默认路径：`C:\Program Files\VideoLAN\VLC\`

3. **重新安装 python-vlc**
   ```bash
   pip uninstall python-vlc
   pip install python-vlc
   ```

---

### **Q2: 提示 "找不到 libvlc.dll"？**

**A:** 这是 DLL 路径问题，解决方法：

#### **方法1：复制 DLL 文件**

1. 找到 VLC 安装目录：
   ```
   C:\Program Files\VideoLAN\VLC\
   ```

2. 复制以下文件到 Python 安装目录：
   - `libvlc.dll`
   - `libvlccore.dll`
   - `plugins` 文件夹（整个文件夹）

3. 粘贴到 Python 的 site-packages 目录：
   ```
   D:\dev\python\Lib\site-packages\
   ```

#### **方法2：设置环境变量**

1. 右键"此电脑" → "属性"
2. 点击"高级系统设置"
3. 点击"环境变量"
4. 在"系统变量"中找到 `Path`
5. 点击"编辑"
6. 添加新路径：
   ```
   C:\Program Files\VideoLAN\VLC\
   ```
7. 点击"确定"保存
8. **重启命令行窗口**

---

### **Q3: 64位 vs 32位？**

**A:** 必须匹配！

- 如果你的 Python 是 **64位**，必须安装 **64位 VLC**
- 如果你的 Python 是 **32位**，必须安装 **32位 VLC**

**检查 Python 位数：**
```bash
python -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
```

预期输出：
```
64 bit    ← 64位Python
```
或
```
32 bit    ← 32位Python
```

---

### **Q4: 安装后还是不能用？**

**A:** 运行以下诊断脚本：

创建文件 `test_vlc.py`：
```python
import vlc

print("测试 VLC...")

try:
    instance = vlc.Instance()
    print("✅ VLC 实例创建成功")
    
    player = instance.media_player_new()
    print("✅ 播放器创建成功")
    
    print("\nVLC 版本:", vlc.libvlc_get_version().decode())
    print("\n🎉 VLC 工作正常！")
    
except Exception as e:
    print(f"❌ 错误: {e}")
    print("\n请检查:")
    print("1. VLC 播放器是否已安装")
    print("2. 是否重启了电脑")
    print("3. Python 和 VLC 位数是否匹配")
```

运行：
```bash
python test_vlc.py
```

---

## 📊 版本要求

| 组件 | 最低版本 | 推荐版本 |
|------|---------|---------|
| VLC 播放器 | 3.0.x | 3.0.20+ |
| python-vlc | 3.0.x | 3.0.21203+ |
| Python | 3.6+ | 3.8+ |

---

## 🎯 快速验证

安装完成后，运行以下命令验证：

```bash
python -c "
import vlc
print('✅ python-vlc 导入成功')
instance = vlc.Instance()
print('✅ VLC 实例创建成功')
print('🎉 一切正常！')
"
```

预期输出：
```
✅ python-vlc 导入成功
✅ VLC 实例创建成功
🎉 一切正常！
```

---

## 💡 使用建议

### **1. 保持 VLC 更新**

定期检查 VLC 更新，获取最新功能和修复：
- 打开 VLC
- 菜单 → 帮助 → 检查更新

### **2. 不要卸载 VLC**

`python-vlc` 依赖 VLC 播放器，卸载 VLC 会导致交互式编辑器无法工作。

### **3. 自定义安装选项**

安装 VLC 时，可以取消勾选不需要的组件以节省空间：
- ❌ Mozilla plugin（浏览器插件）
- ❌ ActiveX plugin
- ❌ 桌面快捷方式（可选）

但必须保留：
- ✅ 核心播放器
- ✅ 编解码器

---

## 🔗 相关资源

- **VLC 官网：** https://www.videolan.org/
- **VLC 下载：** https://www.videolan.org/vlc/
- **VLC 文档：** https://wiki.videolan.org/
- **python-vlc GitHub：** https://github.com/oaubert/python-vlc

---

## ✅ 安装检查清单

安装完成后，确认以下项目：

- [ ] VLC 播放器已下载安装
- [ ] VLC 可以正常启动播放视频/音频
- [ ] python-vlc 已通过 pip 安装
- [ ] 运行诊断脚本无错误
- [ ] 重启过电脑（如果需要）

全部打勾后，就可以使用交互式时间轴编辑器了！🎉

---

**祝你使用愉快！**
