# Python GUI 脚本开发标准规范

> **适用范围**：`py/` 下所有新增的桌面工具脚本（`.pyw` 为主）。
> **模板实现**：[py/other/语音转文字Whisper.pyw](../other/语音转文字Whisper.pyw)
> **配套文档**：[脚本配置与日志标准模板.md](./脚本配置与日志标准模板.md)（只讲配置+日志两件套，本文讲完整骨架）
>
> **⚠️ 强制要求：新建或改造脚本前，必须先读完本文档**，并按第六节的骨架顺序落地。
> 冲突时以本文档为准；本文档未覆盖的细节，参考模板实现和同目录下既有脚本。

---

## 一、文件与命名规则

| 项目 | 规则 | 说明 |
|------|------|------|
| 扩展名 | 面向日常使用 → `.pyw`；被调用/worker/需保留控制台 → `.py` | `.pyw` 双击不弹控制台窗口 |
| 文件名 | **中文功能名**，动宾或名词，如 `语音转文字Whisper.pyw`、`批量重命名.pyw` | 不用拼音、不用英文文件名 |
| 存放位置 | `py/<分类>/` 下按业务归类（`other`、`image`、`book`、`craw`、`yarward`…） | 单文件自成一体，不建子包 |
| `SCRIPT_NAME` | **英文小写下划线**，不含扩展名，如 `whisper_asr` | 用于配置文件名和日志名，与界面标题无关 |
| 配置文件 | `json/config_{SCRIPT_NAME}.json`，`ensure_ascii=False, indent=2` | 统一 `config_` 前缀；旧文档里 `{SCRIPT_NAME}_config.json` 的写法已废弃 |
| 数据/产物 | `json/`（配置、词库、进度）、`md/`（文档）、`logs/`（由 log_utils 管） | 不要在脚本目录里散落临时文件 |
| 启动器注册 | 在 `py/script_launcher.ini` 的 `[Descriptions]` 增加一行 | 格式见第四节 |

---

## 二、脚本骨架顺序（自上而下，固定不变）

模板里每一段的顺序是强制的，因为后面的段落依赖前面的常量与 logger：

```
1.  # -*- coding: utf-8 -*- + 模块 docstring（功能 5 条以内 / 运行方式 / 依赖命令）
2.  标准库 import（按字母序，不在顶部 import 第三方重库）
3.  # ================== 配置与常量 ==================
    SCRIPT_DIR / SCRIPT_NAME / CONFIG_DIR / CONFIG_PATH / CONFIG_DIR.mkdir(exist_ok=True)
4.  # ---------- 日志（可选依赖） ----------
    sys.path 注入 py/ → try: from log_utils import get_logger → except: _DummyLogger
5.  第三方依赖探测（try/except ImportError → HAVE_XXX 标志）
6.  DEFAULT_CONFIG 字典（每个键带一行中文注释）
7.  常量集合：扩展名白名单、下拉选项列表、MODEL_CHOICES 之类
8.  TUTORIAL 长文本（安装教程 + 使用说明 + 参数说明 + 资源提醒）
9.  纯函数区：环境检查 / 文件扫描 / 单任务处理 / 结果写出 / 文本压缩
10. class App: __init__ → _build_ui → _load_config_to_ui → 启动自检
11. def main(): ttk 主题 + App(root) + root.mainloop()
12. if __name__ == "__main__": main()
```

**分节注释统一用**：`# ================== 段落名 ==================`，
类内部用 `# ---------- 功能名 ----------`。这样 `Ctrl+F` 能直接跳段。

**纯函数不碰界面**：第 9 段的函数只接收参数、返回结果或抛异常，
不允许出现 `self`、控件、`messagebox`，方便单独测试和被 CLI 复用。

---

## 三、界面（tkinter/ttk）规范

- 只用标准库 `tkinter` + `ttk`，**不引入第三方 UI 框架**。
- 顶部 `ttk.Notebook` 分页，底部一条 `ttk.Frame` 操作栏：

```
 文件  | 参数  | 日志  | 说明          ← 页签顺序固定
 [开始执行]  [停止]  ▓▓▓▓░░░  60%  状态文字   ← 底部操作栏
```

| 页签 | 内容 |
|------|------|
| 文件 | 输入目录（Entry + 浏览）、输出目录（Entry + 浏览 + 打开）、关键选项、待处理文件列表（Listbox + 刷新 + 计数标签） |
| 参数 | 算法/输出参数，按 `ttk.LabelFrame` 分组；数值项一律"留空 = 用库默认值" |
| 日志 | `tk.Text(state="disabled")` + `Scrollbar`，Consolas 9；这是控制台输出的替代品 |
| 说明 | 只读 `tk.Text` 渲染 `TUTORIAL`，把安装/使用/参数/资源提醒内置进程序 |

- 窗口：`root.geometry("860x720")`、`root.minsize(760, 620)`、`try: root.state("zoomed")`。
- 每个控件配一个 `tk.StringVar` / `tk.BooleanVar`，命名 `xxx_var`，**变量名与配置键名对应**
  （`input_dir_var` ↔ `"input_dir"`），避免读写配置时靠猜。
- 主题：

```python
style = ttk.Style()
if "vista" in style.theme_names():
    style.theme_use("vista")
```

- 轻提示统一走 `_show_toast(title, message, level, duration_ms)`（右下角、4 级配色、可点叉），
  阻断性错误和确认才用 `messagebox`。**不要为每个小结果弹一个对话框**。

---

## 四、注册进脚本启动器

`py/script_launcher.ini` 的 `[Descriptions]` 追加一行，路径用反斜杠、分类写在方括号里：

```ini
other\语音转文字Whisper.pyw = 【音频：Whisper本地离线批量转文字】
```

约定：`【分类：一句话功能】`；废弃脚本用 `【【废弃】…】`，主力工具可标 `【主力使用】`。
`[UsageCount]` 由启动器自己维护，**不要手工改**。

---

## 五、线程、进度与健壮性

### 5.1 耗时任务必须开线程 + 队列

绝不能在 `mainloop` 里直接跑批处理，界面会假死。固定三件套：

```python
self.msg_queue = queue.Queue()          # __init__ 里
self._stop_event = threading.Event()

# 工作线程：只往队列丢消息，绝不直接操作控件
self.msg_queue.put(("log", text))
self.msg_queue.put(("progress", idx, total))
self.msg_queue.put(("done", done, skipped, failed, elapsed))
self.msg_queue.put(("error", msg))

# 主线程轮询，禁止子线程碰 tkinter 对象
def _after_poll(self):
    try:
        while True:
            msg = self.msg_queue.get_nowait()
            ...
    except queue.Empty:
        pass
    self.root.after(100, self._after_poll)
```

- 消息类型统一用 `log / progress / done / stopped / error`，新增类型要在注释里写明。
- 按钮态由 `_set_running(bool)` 统一切换，不要在各处零散 `config(state=...)`。
- **停止只能停在任务之间**：单个任务内部（如一次模型推理）无法中断，
  界面上要写清"等当前这条结束"，别让用户以为卡死。
- 昂贵资源（模型、引擎、数据库连接）**加载一次并缓存**，`_get_xxx()` 判断同名复用。

### 5.2 批量任务必须做到的 5 条

1. **目录自动创建**：输入、输出目录不存在都 `mkdir(parents=True, exist_ok=True)`；
   路径打错会建出空目录，所以要在日志里明确告知"目录不存在，已自动创建"。
2. **跳过已完成 = 断点续跑**：结果文件存在且不小于阈值就跳过；
   0 字节的半成品要重新处理（阈值放配置里，如 `skip_min_bytes`）。
3. **原子写出**：先写 `xxx.txt.tmp` 再 `replace()`，中断不会留半截文件。
4. **单任务失败不中断整批**：循环内 `try/except` 记警告继续下一个；
   结尾汇总"成功 X，跳过 Y，失败 Z"，失败明细写 `转写失败清单.txt`
   （文件名可换成业务名）；**本轮无失败时把上一轮遗留的清单删掉**，避免误导。
5. **长错误压行**：第三方库会把整段版本横幅塞进异常消息，
   用 `_short_err(err, limit=300)` 折叠空白 + 截断，再写日志和清单。

### 5.3 无控制台环境的坑

`.pyw` 下 `sys.stdout` 可能为 `None`，第三方库的进度条会往里写：

- `input()` 会抛 `EOFError`：交互要么去掉，要么捕获 `EOFError/KeyboardInterrupt` 兜底；
- `tqdm` 要显式关掉。例：whisper 的进度条条件是 `disable=(verbose is not False)`，
  所以 GUI 里 `verbose` 必须传 `None`，分段结果自己从 `result["segments"]` 渲染到日志页。

---

## 六、可直接复制的骨架

```python
# -*- coding: utf-8 -*-
"""
XXX 工具（GUI）
================
功能：
  1. …
  2. …

运行方式：
  双击运行（.pyw 不弹控制台），进度和结果显示在“日志”页

依赖：
  pip install XXX        （另需 ffmpeg，见“说明”页）
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "my_tool"                       # 英文小写下划线
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# ---------- 日志（可选依赖） ----------
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)
try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()

# ---------- 依赖探测 ----------
try:
    import some_lib
    HAVE_SOME_LIB = True
except Exception:
    some_lib = None
    HAVE_SOME_LIB = False

# ---------- 默认配置（每个键一行注释） ----------
DEFAULT_CONFIG = {
    "input_dir": r"D:\XXX\in",
    "output_dir": r"D:\XXX\out",
    "workers": 2,                    # 并发数，留空/非法值回退默认
    "keep_open": False,
}

# 「说明」页正文
TUTORIAL = """
【一、pip 安装命令】
【二、外部依赖安装教程（Windows）】
【三、使用说明】
【四、参数微调】
【五、内存 / 磁盘提醒】
"""


# ================== 环境检查 ==================
def check_env():
    """返回 (是否可用, 说明)；缺失时在界面提示，不要让脚本崩在第一个文件上"""
    return True, ""


# ================== 纯函数区（不碰界面） ==================
def collect_files(input_dir, output_dir, min_bytes):
    """扫描待处理项，返回 [(源文件, 目标文件, 是否已完成), ...]"""
    ...


def do_one(item, cfg):
    """处理单项，返回结果文本；异常向上抛，由批量循环捕获"""
    ...


def write_out(path, text):
    """先写 .tmp 再 replace，避免中断留半截文件"""
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _short_err(err, limit=300):
    text = " ".join(str(err).split())
    return text if len(text) <= limit else text[:limit] + "…（已截断）"


# ================== GUI 主程序 ==================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("XXX 工具")
        root.geometry("860x720")
        root.minsize(760, 620)
        try:
            root.state("zoomed")
        except Exception:
            pass

        self.msg_queue = queue.Queue()
        self.worker_thread = None
        self._stop_event = threading.Event()

        # 界面变量：变量名与 DEFAULT_CONFIG 的键一一对应
        self.input_dir_var = tk.StringVar(value=DEFAULT_CONFIG["input_dir"])
        self.output_dir_var = tk.StringVar(value=DEFAULT_CONFIG["output_dir"])
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)

        self._build_ui()
        self._load_config_to_ui()
        self._refresh_file_list()
        self._after_poll()

        if not HAVE_SOME_LIB:
            self.root.after(300, self._warn_no_dep)

    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=4)
        # 文件 / 参数 / 日志 / 说明 四个页签 + 底部操作栏
        ...

    # ---------- 配置读写 ----------
    def _load_config_to_ui(self):
        cfg = self._read_config_file()
        self.input_dir_var.set(cfg.get("input_dir", DEFAULT_CONFIG["input_dir"]))
        ...

    def _collect_config_from_ui(self):
        return {"input_dir": self.input_dir_var.get().strip(), ...}

    @staticmethod
    def _read_config_file():
        """缺字段用默认值补齐，保证旧配置文件向后兼容"""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(saved if isinstance(saved, dict) else {})
                return merged
        except Exception as e:
            logger.error("加载配置失败，使用默认配置: %s", e)
        return DEFAULT_CONFIG.copy()

    @staticmethod
    def _save_config_file(cfg):
        try:
            persist = {k: v for k, v in cfg.items() if not k.startswith("_")}
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(persist, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    @staticmethod
    def _str_to_num(text, default, caster):
        """输入框文本 → 数字；空串或非法值返回 default（None 表示用库默认值）"""
        s = (text or "").strip()
        if s == "":
            return default
        try:
            return caster(s)
        except Exception:
            return default

    # ---------- 日志 ----------
    def _log(self, s):
        self.log_text.config(state="normal")
        self.log_text.insert("end", s + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _thread_log(self, s):
        """工作线程里只能走队列，不能直接碰控件"""
        self.msg_queue.put(("log", s))

    # ---------- 控制 ----------
    def _start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        cfg = self._collect_config_from_ui()
        self._save_config_file(cfg)
        self._stop_event.clear()
        self._set_running(True)
        self.notebook.select(2)                    # 切到日志页
        self.worker_thread = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _stop(self):
        self._stop_event.set()
        self.status_var.set("正在停止（等当前一项结束）...")

    def _set_running(self, running):
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    def _work(self, cfg):
        """批量主流程：检查环境 → 扫描 → 加载资源(一次) → 逐项处理 → 汇总"""
        try:
            ...
        except Exception as e:
            self.msg_queue.put(("error", "任务异常：%s" % e))
            logger.exception("批量任务异常")

    def _after_poll(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                ...
        except queue.Empty:
            pass
        self.root.after(100, self._after_poll)


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
```

---

## 七、「说明」页必须覆盖的五段

需求文档里的"pip 安装命令、外部依赖安装教程、使用说明、显存/内存提醒"这类内容，
**一律内置成 TUTORIAL 并放进「说明」页**，不要只写在聊天回复或单独 md 里：

1. **pip 安装命令**：给出确切包名 + 国内加速方案 + "不要装错同名库"的告警 + 验证命令
2. **外部依赖安装教程（Windows）**：winget 一行式 + 手动下载配 PATH 步骤 + 常见失败原因
3. **使用说明**：怎么打开、目录/格式约定、跳过与断点续跑、失败清单在哪
4. **参数微调**：逐条对齐配置键名 + 默认值 + 什么场景该调
5. **内存/磁盘/耗时提醒**：官方数据 + 不同机器档位的选型建议 + 缓存目录位置（离线说明）

---

## 八、交付前自检清单

- [ ] `python -c "import py_compile; py_compile.compile('xx.pyw', doraise=True)"` 通过
- [ ] 真实渲染自检：构建 `App(root)` 后 `root.after(1500, root.destroy); root.mainloop()` 无异常
- [ ] **用真实数据完整跑一轮**（不要只用假对象自测——参数名写错这类问题只有真跑才会暴露）
- [ ] 配置往返一致：`_collect_config_from_ui()` → 存 → 读 → 再 collect 相等
- [ ] 第二轮全部命中"跳过"，说明断点续跑生效
- [ ] 造一个坏文件，确认：只警告不中断、失败清单生成、错误消息已压行
- [ ] 目录不存在时能自动创建并在日志里说明
- [ ] 输出无残留 `.tmp`
- [ ] `script_launcher.ini` 已注册；配置文件命名是 `config_{SCRIPT_NAME}.json`
- [ ] 清理临时测试脚本、临时音视频/图片、测试输出目录

---

## 九、模板实现对照（语音转文字Whisper.pyw）

| 规范条目 | 模板中的位置 |
|---|---|
| 配置与常量四件套 | `# ================== 配置与常量 ==================`（第 33 行起） |
| 日志可选依赖降级 | `# ---------- 日志（可选依赖） ----------` |
| DEFAULT_CONFIG + 逐行注释 | 第 72 行起 |
| TUTORIAL 五段式说明页 | 第 101 行起 |
| 环境检查纯函数 | `check_ffmpeg()` / `check_torch_cuda()` |
| 文件扫描 + 跳过判定 | `collect_audio_files()` |
| 单任务处理 + 参数分两层 | `transcribe_one()` |
| 长错误压行 | `_short_err()` |
| 原子写出 | `write_txt()` |
| 四页签 UI + 底部操作栏 | `class App` 的 `_build_ui()` |
| 配置往返 + 空值转默认 | `_load_config_to_ui()` / `_collect_config_from_ui()` / `_str_to_num()` |
| 线程 + 队列 + 轮询 | `_work()` / `_after_poll()` / `_thread_log()` |
| 昂贵资源缓存复用 | `_get_model()` |
| 失败清单生成与清理 | `_work()` 结尾的汇总段 |
| Toast / 退出确认 | `_show_toast()` / `_on_close()` |
