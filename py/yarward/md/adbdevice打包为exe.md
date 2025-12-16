2025/12/16
---
好的！现在我来详细说明如何**将 QtScrcpy 集成到你的 `adb_device_manager.pyw` 脚本中，并打包成一个独立的 EXE 文件**。

---

### ✅ 打包前的代码修改（必须）

为了让打包后的 EXE 能自动找到 QtScrcpy，需要修改脚本，使其能从 `_internal` 目录中查找 QtScrcpy。

---

### 🔧 修改 `adb_device_manager.pyw` 代码

在文件开头添加 `sys` 导入，并修改路径查找逻辑：

```python
# adb_device_manager.pyw

import os
import sys          # ← 新增：必须导入
import json
import logging
import subprocess
import threading
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))

# 🔧【关键修改】如果打包为exe，从 _internal 查找 QtScrcpy
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的路径
    BASE_DIR = Path(sys._MEIPASS)
    # 尝试从 _internal 查找
    INTERNAL_QTSCRCPY = BASE_DIR / "_internal" / "QtScrcpy"
    if INTERNAL_QTSCRCPY.exists():
        DEFAULT_ADB_DIR = str(INTERNAL_QTSCRCPY)
        DEFAULT_SCRCPY_EXE = str(INTERNAL_QTSCRCPY / "QtScrcpy.exe")
    else:
        # 如果 _internal 中没有，则使用默认路径
        DEFAULT_ADB_DIR = r"D:\tools\QtScrcpy-win-x86-v3.3.1"
        DEFAULT_SCRCPY_EXE = r"D:\tools\QtScrcpy-win-x86-v3.3.1\QtScrcpy.exe"
else:
    # 开发模式
    DEFAULT_ADB_DIR = r"D:\tools\QtScrcpy-win-x86-v3.3.1"
    DEFAULT_SCRCPY_EXE = r"D:\tools\QtScrcpy-win-x86-v3.3.1\QtScrcpy.exe"

SCRIPT_NAME = "adb_device_manager"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR = CONFIG_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "adb_dir": DEFAULT_ADB_DIR,
    "scrcpy_exe": DEFAULT_SCRCPY_EXE,
    "device_ip": "192.168.1.100"
}

# ... [其余代码保持不变，直到 launch_scrcpy 方法] ...

    def launch_scrcpy(self):
        scrcpy_exe = self.scrcpy_exe_var.get()
        if not Path(scrcpy_exe).exists():
            messagebox.showerror("文件不存在", f"未找到 QtScrcpy.exe:\n{scrcpy_exe}")
            return

        try:
            # 🔧【关键修改】确保在正确的目录下启动（以便 scrcpy-server 等文件能被找到）
            exe_path = Path(scrcpy_exe)
            subprocess.Popen([str(exe_path)], cwd=exe_path.parent)
            msg = "✅ 已启动 QtScrcpy 投屏"
            self.set_status(msg, "green")
            self.log_to_gui(msg)
            logging.info(msg)
        except Exception as e:
            msg = f"❌ 启动失败: {e}"
            self.set_status(msg, "red")
            self.log_to_gui(msg)
            logging.error(msg)
            messagebox.showerror("启动失败", str(e))

# ... [其余代码保持不变] ...
```

---

### 📦 打包步骤

#### 1. 安装 PyInstaller

```bash
pip install pyinstaller
```

#### 2. 准备目录结构

```
your_project/
├── adb_device_manager.pyw  （已修改的脚本）
└── QtScrcpy/               （完整的 QtScrcpy 目录）
    ├── adb.exe
    ├── QtScrcpy.exe
    ├── scrcpy-server
    ├── scrcpy-console.bat
    └── ...（其他 QtScrcpy 文件）
```

#### 3. 执行打包命令

```bash
pyinstaller --noconsole --onefile --add-data "QtScrcpy;_internal/QtScrcpy" adb_device_manager.pyw
```

> ⚠️ **Windows 上用分号 `;`**，Linux/macOS 用冒号 `:`

---

### ✅ 打包后说明

- 生成的 `dist/adb_device_manager.exe` 是独立文件，可直接分发；
- 首次运行时，程序会自动从 `_internal/QtScrcpy` 加载工具，无需用户配置；
- 用户依然可以在 GUI 中**修改路径**，修改后会保存到配置文件（`json/config_adb_device_manager.json`）；
- 如果用户配置了自定义路径，优先使用自定义路径；否则使用打包内置的 QtScrcpy。

---

### 🧪 验证步骤

1. 运行打包后的 `.exe` 文件；
2. 检查默认路径是否指向 `_internal/QtScrcpy`；
3. 尝试连接设备、启动投屏，确认功能正常。

---

### 📝 注意事项

- 如果 QtScrcpy 更新了版本，只需替换 `QtScrcpy/` 目录下的文件，重新打包即可；
- 打包后的 EXE 文件会比较大（因为包含了整个 QtScrcpy 目录，约 100MB+）；
- 如果希望减小体积，可以只打包 `adb.exe` 和 `scrcpy.exe`（约 10-20MB），但会失去 QtScrcpy 的图形化界面功能。

---

如需打包 SVN 脚本（`svn_quick_checkout.pyw`）或需要更详细的打包配置文件（`.spec`），也可以告诉我！
