# chinese_to_pinyin_with_spaces.py

import os
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime
import threading

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "chinese_to_pinyin"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# ──────────── 公共日志模块（可选依赖）────────────
import sys
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
# ────────────────────────────────────────────────

# 默认配置
DEFAULT_CONFIG = {
    "input_file": "",
    "output_dir": str(Path.home() / "Desktop")  # 默认桌面
}

class ChineseToPinyinApp:
    def __init__(self, root):
        self.root = root
        self.root.title("汉字转拼音工具（带声调）")
        self.root.geometry("800x600")
        self.root.minsize(700, 500)

        # 初始化变量
        self.input_file = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.is_processing = False

        # 创建UI
        self._create_widgets()

        # 加载配置
        self._load_config()

    def _select_input_file(self):
        """选择输入txt文件"""
        file_path = filedialog.askopenfilename(
            title="选择txt文件",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=Path(self.input_file.get()).parent if self.input_file.get() else "."
        )
        if file_path:
            self.input_file.set(file_path)
            self._log(f"选择输入文件: {file_path}")

    def _select_output_dir(self):
        """选择输出目录"""
        dir_path = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=self.output_dir.get()
        )
        if dir_path:
            self.output_dir.set(dir_path)
            self._log(f"选择输出目录: {dir_path}")

    def _convert_chinese_to_pinyin(self):
        """转换汉字为带声调的拼音（每个汉字拼音后加空格）"""
        try:
            from pypinyin import lazy_pinyin, Style
        except ImportError:
            messagebox.showerror(
                "错误",
                "缺少依赖库 'pypinyin'，请先安装：\n"
                "pip install pypinyin"
            )
            return

        input_path = Path(self.input_file.get())
        output_dir = Path(self.output_dir.get())

        if not input_path.exists():
            messagebox.showerror("错误", "输入文件不存在")
            return
        if not output_dir.exists():
            messagebox.showerror("错误", "输出目录不存在")
            return

        try:
            # 读取原文件
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self._log("开始转换汉字为拼音...")

            # 转换汉字为带声调的拼音（每个汉字后加空格）
            converted_content = ""
            for char in content:
                if '\u4e00' <= char <= '\u9fff':  # 判断是否为汉字
                    # 获取单个汉字的带声调拼音
                    pinyin_list = lazy_pinyin(char, style=Style.TONE)
                    if pinyin_list:
                        converted_content += pinyin_list[0] + " "  # 拼音后加空格
                    else:
                        converted_content += char  # 如果无法转换，保留原字符
                else:
                    converted_content += char  # 非汉字字符保留

            # 生成输出文件名
            output_filename = input_path.stem + "_拼音.txt"
            output_path = output_dir / output_filename

            # 写入转换后的内容
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(converted_content)

            self._log(f"✅ 转换完成，输出文件: {output_path}")
            messagebox.showinfo("完成", f"转换完成！\n输出文件: {output_path}")

        except Exception as e:
            self._log(f"转换过程中出错: {str(e)}", logging.ERROR)
            messagebox.showerror("错误", f"转换失败: {str(e)}")

    def _start_conversion(self):
        """开始转换（在新线程中执行）"""
        if not self.input_file.get():
            messagebox.showerror("错误", "请选择输入文件")
            return
        if not self.output_dir.get():
            messagebox.showerror("错误", "请选择输出目录")
            return

        self.is_processing = True
        self._update_button_states()
        threading.Thread(target=self._convert_chinese_to_pinyin, daemon=True).start()

    def _save_config(self):
        """保存配置"""
        config = {
            "input_file": self.input_file.get(),
            "output_dir": self.output_dir.get()
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log("配置已保存")
        except Exception as e:
            self._log(f"保存配置失败: {str(e)}", logging.ERROR)

    def _load_config(self):
        """加载配置"""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self.input_file.set(config.get("input_file", DEFAULT_CONFIG["input_file"]))
                self.output_dir.set(config.get("output_dir", DEFAULT_CONFIG["output_dir"]))
                self._log("配置已加载")
            else:
                # 使用默认值
                self.output_dir.set(DEFAULT_CONFIG["output_dir"])
                self._log("使用默认配置")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

    def _log(self, message, level=logging.INFO):
        """记录日志并更新UI"""
        logger.log(level, message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def _update_button_states(self):
        """更新按钮状态"""
        state = tk.DISABLED if self.is_processing else tk.NORMAL
        for btn in [
            self.select_file_btn, self.select_dir_btn,
            self.start_btn, self.save_btn
        ]:
            btn.config(state=state)

    def _create_widgets(self):
        """创建UI组件"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 输入文件选择
        input_frame = ttk.LabelFrame(main_frame, text="📄 输入文件", padding="5")
        input_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(input_frame, textvariable=self.input_file, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_file_btn = ttk.Button(input_frame, text="浏览...", command=self._select_input_file)
        self.select_file_btn.pack(side=tk.RIGHT)

        # 输出目录选择
        output_frame = ttk.LabelFrame(main_frame, text="📁 输出目录", padding="5")
        output_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(output_frame, textvariable=self.output_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_dir_btn = ttk.Button(output_frame, text="浏览...", command=self._select_output_dir)
        self.select_dir_btn.pack(side=tk.RIGHT)

        # 操作按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="🔄 开始转换", command=self._start_conversion, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0,10))
        self.save_btn = ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config)
        self.save_btn.pack(side=tk.LEFT)

        # 说明标签
        info_label = ttk.Label(
            btn_frame,
            text="💡 说明：转换后的文件名将在原文件名后添加'_拼音.txt'",
            foreground="gray"
        )
        info_label.pack(side=tk.RIGHT)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="📝 转换日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChineseToPinyinApp(root)
    root.mainloop()
