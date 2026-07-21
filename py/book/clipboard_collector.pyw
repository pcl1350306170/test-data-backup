# clipboard_collector.pyw

import os
import json
import logging
import pyperclip
import threading
import time
from pathlib import Path
from datetime import datetime
from tkinter import *
from tkinter import messagebox, filedialog, scrolledtext

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "clipboard_collector"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
TEMP_FILE = CONFIG_DIR / "temp_clipboard.txt"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)



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
    "save_directory": str(Path.home() / "Documents"),
    "auto_monitor": True,  # 是否自动监控剪贴板
    "monitor_interval": 1.0,  # 监控间隔（秒）
}

# ==============================
# 工具函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(save_dir, auto_monitor, interval):
    config = {
        "save_directory": save_dir.strip(),
        "auto_monitor": auto_monitor,
        "monitor_interval": interval,
    }
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False

def load_temp_content():
    """加载临时文件中的历史内容"""
    if TEMP_FILE.exists():
        try:
            with open(TEMP_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"加载临时文件失败: {e}")
    return ""

def save_temp_content(content):
    """保存内容到临时文件"""
    try:
        with open(TEMP_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"保存临时文件失败: {e}")
        return False

def clear_temp_file():
    """清空临时文件"""
    try:
        if TEMP_FILE.exists():
            TEMP_FILE.unlink()
        return True
    except Exception as e:
        logger.error(f"清空临时文件失败: {e}")
        return False

# ==============================
# GUI 主类
# ==============================
class ClipboardCollectorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📋 剪贴板内容收集器")
        self.root.geometry("700x600")
        self.root.resizable(True, True)

        self.config = load_config()
        self.clipboard_history = load_temp_content()  # 显示用（带时间戳）
        self.clean_content_list = []  # 纯净内容列表（用于保存）
        self.last_clipboard = ""
        self.is_monitoring = False
        self.monitor_thread = None
        
        self.setup_ui()
        
        # 启动时加载历史内容
        if self.clipboard_history:
            self.content_text.insert(END, self.clipboard_history)
            self.update_status(f"已加载历史内容")
        
        # 加载纯净内容列表（从临时文件）
        clean_temp = load_temp_content()
        if clean_temp and clean_temp.strip():
            # 用两个换行符分割，恢复为列表
            self.clean_content_list = [item.strip() for item in clean_temp.split("\n\n") if item.strip()]
        
        # 如果配置了自动监控，则启动
        if self.config.get("auto_monitor", True):
            self.start_monitoring()

    def setup_ui(self):
        # 保存目录
        dir_frame = LabelFrame(self.root, text="📂 保存目录", padx=10, pady=8)
        dir_frame.pack(fill=X, padx=10, pady=5)
        self.dir_var = StringVar(value=self.config["save_directory"])
        Entry(dir_frame, textvariable=self.dir_var, font=("Consolas", 9)).pack(side=LEFT, fill=X, expand=True)
        Button(dir_frame, text="📁 选择目录", command=self.select_dir).pack(side=RIGHT, padx=(5, 0))

        # 监控设置
        monitor_frame = LabelFrame(self.root, text="⚙️ 监控设置", padx=10, pady=8)
        monitor_frame.pack(fill=X, padx=10, pady=5)
        
        self.auto_monitor_var = BooleanVar(value=self.config.get("auto_monitor", True))
        Checkbutton(monitor_frame, text="自动监控剪贴板变化", variable=self.auto_monitor_var).pack(side=LEFT, padx=5)
        
        Label(monitor_frame, text="间隔(秒):").pack(side=LEFT, padx=(10, 5))
        self.interval_var = DoubleVar(value=self.config.get("monitor_interval", 1.0))
        Spinbox(monitor_frame, from_=0.5, to=5.0, increment=0.5, textvariable=self.interval_var, width=8).pack(side=LEFT, padx=5)
        
        self.monitor_btn = Button(monitor_frame, text="▶️ 启动监控", command=self.toggle_monitoring, 
                                  bg="#4CAF50", fg="white", width=12)
        self.monitor_btn.pack(side=RIGHT, padx=5)

        # 剪贴板内容显示
        content_frame = LabelFrame(self.root, text="📝 已收集的内容", padx=10, pady=8)
        content_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # 文本框和滚动条
        text_scroll = Scrollbar(content_frame)
        text_scroll.pack(side=RIGHT, fill=Y)
        
        self.content_text = scrolledtext.ScrolledText(content_frame, wrap=WORD, font=("Consolas", 10), 
                                                       height=15, yscrollcommand=text_scroll.set)
        self.content_text.pack(fill=BOTH, expand=True)
        text_scroll.config(command=self.content_text.yview)

        # 按钮区域
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=10)
        
        Button(btn_frame, text="📋 一键粘贴", command=self.paste_from_clipboard, 
               bg="#2196F3", fg="white", width=15, height=1).pack(side=LEFT, padx=5)
        
        Button(btn_frame, text="💾 保存配置", command=self.save_config_action, 
               bg="#FF9800", fg="white", width=12).pack(side=LEFT, padx=5)
        
        Button(btn_frame, text="🗑️ 清空内容", command=self.clear_content, 
               bg="#f44336", fg="white", width=12).pack(side=LEFT, padx=5)
        
        Button(btn_frame, text="💿 保存为TXT", command=self.save_to_file, 
               bg="#9C27B0", fg="white", width=15).pack(side=LEFT, padx=5)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        Label(self.root, textvariable=self.status_var, bd=1, relief=SUNKEN, anchor=W, fg="blue").pack(side=BOTTOM, fill=X)

    def select_dir(self):
        folder = filedialog.askdirectory(title="选择保存目录", initialdir=self.dir_var.get())
        if folder:
            self.dir_var.set(folder)

    def toggle_monitoring(self):
        """切换监控状态"""
        if self.is_monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        """启动剪贴板监控"""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.monitor_btn.config(text="⏹️ 停止监控", bg="#f44336")
        self.update_status("✅ 剪贴板监控已启动")
        
        # 启动监控线程
        self.monitor_thread = threading.Thread(target=self._monitor_clipboard, daemon=True)
        self.monitor_thread.start()
        logger.info("剪贴板监控已启动")

    def stop_monitoring(self):
        """停止剪贴板监控"""
        self.is_monitoring = False
        self.monitor_btn.config(text="▶️ 启动监控", bg="#4CAF50")
        self.update_status("⏸️ 剪贴板监控已停止")
        logger.info("剪贴板监控已停止")

    def _monitor_clipboard(self):
        """监控剪贴板变化的后台线程"""
        interval = self.interval_var.get()
        
        while self.is_monitoring:
            try:
                # 获取当前剪贴板内容
                current_content = pyperclip.paste()
                
                # 如果内容发生变化且不为空
                if current_content and current_content != self.last_clipboard:
                    self.last_clipboard = current_content
                    
                    # 在主线程中更新UI
                    self.root.after(0, self._append_clipboard_content, current_content)
                
                time.sleep(interval)
            except Exception as e:
                logger.error(f"监控剪贴板出错: {e}")
                time.sleep(interval)

    def _append_clipboard_content(self, content):
        """追加剪贴板内容到文本框"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "\n" + "="*60 + "\n"
        new_content = f"[{timestamp}]\n{content}\n"
        
        # 添加到文本框（显示时带时间戳）
        self.content_text.insert(END, separator + new_content)
        self.content_text.see(END)  # 滚动到底部
        
        # 更新历史记录（显示用，带时间戳）
        self.clipboard_history += separator + new_content
        
        # 保存到临时文件（只保存纯内容，用两个换行分隔）
        self._save_clean_temp_content(content)
        
        self.update_status(f"✅ 已粘贴新内容 ({len(content)} 字符)")
        logger.info(f"检测到剪贴板变化，已追加内容")

    def _save_clean_temp_content(self, new_content):
        """保存纯净内容到临时文件（无时间戳和分隔符，只用两个换行分隔）"""
        # 将新内容添加到列表
        self.clean_content_list.append(new_content.strip())
        
        # 用两个换行符连接所有内容
        clean_text = "\n\n".join(self.clean_content_list)
        
        # 保存到临时文件
        save_temp_content(clean_text)

    def paste_from_clipboard(self):
        """手动从剪贴板粘贴内容"""
        try:
            content = pyperclip.paste()
            
            if not content or not content.strip():
                messagebox.showwarning("警告", "剪贴板为空！")
                return
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            separator = "\n" + "="*60 + "\n"
            new_content = f"[{timestamp}]\n{content}\n"
            
            # 添加到文本框（显示时带时间戳）
            self.content_text.insert(END, separator + new_content)
            self.content_text.see(END)
            
            # 更新历史记录（显示用，带时间戳）
            self.clipboard_history += separator + new_content
            
            # 保存到临时文件（只保存纯内容，用两个换行分隔）
            self._save_clean_temp_content(content)
            
            self.update_status(f"✅ 已粘贴 ({len(content)} 字符)")
            logger.info(f"手动粘贴内容: {len(content)} 字符")
            
        except Exception as e:
            logger.error(f"粘贴失败: {e}")
            messagebox.showerror("错误", f"粘贴失败: {e}")

    def clear_content(self):
        """清空所有内容"""
        if messagebox.askyesno("确认", "确定要清空所有已收集的内容吗？\n此操作不可恢复！"):
            self.content_text.delete(1.0, END)
            self.clipboard_history = ""
            self.last_clipboard = ""
            self.clean_content_list = []  # 清空纯内容列表
            clear_temp_file()
            self.update_status("🗑️ 内容已清空")
            logger.info("用户清空了所有内容")

    def save_to_file(self):
        """保存内容为TXT文件（纯净版，无时间戳和分隔符）"""
        # 从临时文件读取纯净内容
        clean_content = load_temp_content()
        
        if not clean_content or not clean_content.strip():
            messagebox.showwarning("警告", "没有内容可保存！")
            return
        
        # 弹出文件名输入对话框
        filename = simpledialog_askstring("保存文件", "请输入文件名（不含扩展名）：")
        
        if not filename:
            return
        
        # 确保文件名合法
        safe_filename = "".join(c for c in filename if c not in r'<>:"/\|?*')
        if not safe_filename:
            safe_filename = "clipboard_content"
        
        # 构建完整路径
        save_dir = Path(self.dir_var.get().strip())
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / f"{safe_filename}.txt"
        
        try:
            # 以 UTF-8 编码保存纯净内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(clean_content)
            
            self.update_status(f"✅ 文件已保存: {file_path.name}")
            logger.info(f"文件已保存: {file_path}")
            messagebox.showinfo("成功", f"文件已保存：\n{file_path}")
            
            # 询问是否打开文件所在目录
            if messagebox.askyesno("提示", "是否打开文件所在目录？"):
                os.startfile(str(save_dir))
                
        except Exception as e:
            logger.error(f"保存文件失败: {e}")
            messagebox.showerror("错误", f"保存文件失败：\n{e}")

    def save_config_action(self):
        save_dir = self.dir_var.get().strip()
        auto_monitor = self.auto_monitor_var.get()
        interval = self.interval_var.get()
        
        if not save_dir:
            messagebox.showwarning("输入错误", "保存目录不能为空！")
            return
        
        if save_config(save_dir, auto_monitor, interval):
            self.config = load_config()
            self.update_status("✅ 配置已保存")
            logger.info("配置已保存")
        else:
            messagebox.showerror("错误", "保存配置失败，请查看日志。")

    def update_status(self, message):
        self.status_var.set(message)
        self.root.update_idletasks()

# ==============================
# 辅助函数：简单的字符串输入对话框
# ==============================
def simpledialog_askstring(title, prompt):
    """简单的字符串输入对话框"""
    dialog = Toplevel()
    dialog.title(title)
    dialog.geometry("400x120")
    dialog.transient(root)
    dialog.grab_set()
    
    result = [None]
    
    Label(dialog, text=prompt, pady=10).pack()
    
    entry = Entry(dialog, width=40, font=("Consolas", 10))
    entry.pack(padx=10, pady=5)
    entry.focus_set()
    
    def on_ok():
        result[0] = entry.get().strip()
        dialog.destroy()
    
    def on_cancel():
        result[0] = None
        dialog.destroy()
    
    btn_frame = Frame(dialog)
    btn_frame.pack(pady=10)
    Button(btn_frame, text="确定", command=on_ok, width=10).pack(side=LEFT, padx=5)
    Button(btn_frame, text="取消", command=on_cancel, width=10).pack(side=LEFT, padx=5)
    
    # 绑定回车键
    dialog.bind('<Return>', lambda e: on_ok())
    dialog.bind('<Escape>', lambda e: on_cancel())
    
    # 居中显示
    dialog.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() - dialog.winfo_width()) // 2
    y = root.winfo_y() + (root.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")
    
    root.wait_window(dialog)
    return result[0]

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = ClipboardCollectorGUI(root)
    
    # 窗口关闭时清理
    def on_closing():
        app.stop_monitoring()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
