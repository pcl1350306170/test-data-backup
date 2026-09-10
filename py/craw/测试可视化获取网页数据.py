import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests
from requests.exceptions import RequestException
import logging
from datetime import datetime
from pathlib import Path

# 配置与常量
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_NAME = "web_content_fetcher"

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
        def log(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

class WebContentFetcher:
    def __init__(self, root):
        self.root = root
        self.root.title("网页内容获取工具")
        self.root.geometry("900x600")
        self.root.minsize(800, 500)

        # 创建UI组件
        self._create_widgets()

    def _create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 网址输入区域
        url_frame = ttk.Frame(main_frame)
        url_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(url_frame, text="网址:").pack(side=tk.LEFT, padx=(0, 10))

        self.url_var = tk.StringVar(value="https://")
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, width=80)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        url_entry.focus_set()

        fetch_btn = ttk.Button(url_frame, text="获取内容", command=self._fetch_web_content)
        fetch_btn.pack(side=tk.LEFT)

        # 内容显示区域
        content_frame = ttk.LabelFrame(main_frame, text="网页内容")
        content_frame.pack(fill=tk.BOTH, expand=True)

        self.content_text = scrolledtext.ScrolledText(
            content_frame,
            wrap=tk.WORD,
            font=("Consolas", 10)
        )
        self.content_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.content_text.config(state=tk.DISABLED)

        # 状态条
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _log(self, message, level=logging.INFO):
        """记录日志"""
        logger.log(level, message)
        self.status_var.set(message)

    def _fetch_web_content(self):
        """获取网页内容"""
        url = self.url_var.get().strip()

        if not url:
            messagebox.showerror("错误", "请输入网址")
            return

        # 清空之前的内容
        self.content_text.config(state=tk.NORMAL)
        self.content_text.delete(1.0, tk.END)
        self.content_text.config(state=tk.DISABLED)

        # 显示加载状态
        self._log(f"正在获取: {url}")

        try:
            # 发送请求
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()  # 抛出HTTP错误

            # 尝试解析编码
            response.encoding = response.apparent_encoding

            # 显示内容
            self.content_text.config(state=tk.NORMAL)
            self.content_text.insert(tk.END, response.text)
            self.content_text.config(state=tk.DISABLED)

            self._log(f"成功获取内容，长度: {len(response.text)} 字符")

        except RequestException as e:
            error_msg = f"获取失败: {str(e)}"
            self._log(error_msg, logging.ERROR)
            self.content_text.config(state=tk.NORMAL)
            self.content_text.insert(tk.END, error_msg)
            self.content_text.config(state=tk.DISABLED)
            messagebox.showerror("获取失败", error_msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = WebContentFetcher(root)
    root.mainloop()
