import os
import re
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

# 配置路径设置
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "txt_split_to_json"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"

# 确保配置目录存在
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
    "last_txt_path": "",
    "last_search_dir": "",
    "last_output_dir": "",
    "split_length": 500,
}


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


def save_config(cfg):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


def read_txt_file(file_path):
    """读取 TXT 文件，自动检测编码"""
    import chardet
    raw = Path(file_path).read_bytes()
    detected = chardet.detect(raw)
    encoding = detected.get('encoding', 'utf-8') or 'utf-8'
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return raw.decode('utf-8', errors='replace')


def split_text(text, target_length):
    """
    按目标字符数拆分文本，在句号等标点后截断，不截断句子。
    返回拆分后的文本片段列表。
    """
    text = text.strip()
    if not text:
        return []

    sentence_endings = set('。！？')
    segments = []
    pos = 0

    while pos < len(text):
        remaining = text[pos:]

        # 剩余内容不足目标长度，全部作为最后一段
        if len(remaining) <= target_length:
            segments.append(remaining.strip())
            break

        target_pos = pos + target_length
        char_at_target = text[target_pos] if target_pos < len(text) else ''

        # 目标位置已经是句末标点，直接切分
        if char_at_target in sentence_endings:
            segments.append(text[pos:target_pos + 1].strip())
            pos = target_pos + 1
            continue

        # 从目标位置向后查找最近的句末标点（最多 200 字符）
        forward_found = -1
        for i in range(target_pos + 1, min(target_pos + 201, len(text))):
            if text[i] in sentence_endings:
                forward_found = i
                break

        if forward_found != -1:
            segments.append(text[pos:forward_found + 1].strip())
            pos = forward_found + 1
        else:
            # 向后找不到标点，回退到目标位置之前找最近的句末标点
            backward_found = -1
            for i in range(target_pos - 1, max(pos + target_length // 2 - 1, pos) - 1, -1):
                if text[i] in sentence_endings:
                    backward_found = i
                    break

            if backward_found != -1:
                segments.append(text[pos:backward_found + 1].strip())
                pos = backward_found + 1
            else:
                # 前后都找不到标点，在目标位置强制截断
                segments.append(text[pos:target_pos].strip())
                pos = target_pos

    # 过滤空片段
    return [s for s in segments if s]


class TxtSplitApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TXT 文件拆分转 JSON 工具")
        self.root.geometry("800x650")

        self.config = load_config()
        self.matched_files = []

        self.create_widgets()
        self.load_config_to_ui()

    def create_widgets(self):
        # ── 文件来源 ──
        source_frame = ttk.LabelFrame(self.root, text="文件来源", padding=10)
        source_frame.pack(fill=tk.X, padx=10, pady=5)

        # 模式选择
        mode_frame = ttk.Frame(source_frame)
        mode_frame.pack(fill=tk.X)

        self.mode_var = tk.StringVar(value="file")
        ttk.Radiobutton(mode_frame, text="选择 TXT 文件", variable=self.mode_var,
                        value="file", command=self.on_mode_change).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_frame, text="按目录 + 关键字匹配", variable=self.mode_var,
                        value="dir", command=self.on_mode_change).pack(side=tk.LEFT, padx=(20, 0))

        # 直接选文件
        self.file_frame = ttk.Frame(source_frame)
        self.file_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(self.file_frame, text="TXT 文件:").pack(side=tk.LEFT)
        self.txt_path_var = tk.StringVar()
        ttk.Entry(self.file_frame, textvariable=self.txt_path_var, width=55).pack(
            side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(self.file_frame, text="浏览...", command=self.browse_file).pack(side=tk.LEFT)

        # 目录 + 关键字
        self.dir_frame = ttk.Frame(source_frame)
        # 先不 pack，由 on_mode_change 控制

        dir_row1 = ttk.Frame(self.dir_frame)
        dir_row1.pack(fill=tk.X)
        ttk.Label(dir_row1, text="目录:").pack(side=tk.LEFT)
        self.search_dir_var = tk.StringVar()
        ttk.Entry(dir_row1, textvariable=self.search_dir_var, width=55).pack(
            side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(dir_row1, text="浏览...", command=self.browse_dir).pack(side=tk.LEFT)

        dir_row2 = ttk.Frame(self.dir_frame)
        dir_row2.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(dir_row2, text="关键字:").pack(side=tk.LEFT)
        self.keyword_var = tk.StringVar()
        ttk.Entry(dir_row2, textvariable=self.keyword_var, width=30).pack(side=tk.LEFT, padx=5)
        ttk.Button(dir_row2, text="搜索匹配", command=self.search_files).pack(side=tk.LEFT, padx=5)

        # 匹配结果列表
        self.match_listbox = tk.Listbox(self.dir_frame, height=4, selectmode=tk.EXTENDED)
        self.match_listbox.pack(fill=tk.X, pady=(5, 0))
        self.match_count_label = ttk.Label(self.dir_frame, text="")
        self.match_count_label.pack(anchor=tk.W)

        # ── 输出设置 ──
        output_frame = ttk.LabelFrame(self.root, text="输出设置", padding=10)
        output_frame.pack(fill=tk.X, padx=10, pady=5)

        row1 = ttk.Frame(output_frame)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="JSON 保存目录:").pack(side=tk.LEFT)
        self.output_dir_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.output_dir_var, width=50).pack(
            side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(row1, text="浏览...", command=self.browse_output_dir).pack(side=tk.LEFT)

        row2 = ttk.Frame(output_frame)
        row2.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(row2, text="拆分字数:").pack(side=tk.LEFT)
        self.split_length_var = tk.StringVar(value=str(self.config.get("split_length", 500)))
        ttk.Entry(row2, textvariable=self.split_length_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Label(row2, text="（每段约多少字符，会在句末标点处截断）",
                  foreground="gray").pack(side=tk.LEFT)

        # ── 操作按钮 ──
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="执行拆分", command=self.run_split).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="保存配置", command=self.save_current_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="打开输出目录", command=self.open_output_dir).pack(side=tk.LEFT, padx=5)

        # ── 日志区域 ──
        log_frame = ttk.LabelFrame(self.root, text="处理日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = tk.Text(log_frame, height=10, state=tk.DISABLED,
                                font=("Consolas", 9), wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 右键菜单
        self.log_menu = tk.Menu(self.log_text, tearoff=0)
        self.log_menu.add_command(label="复制", command=self._copy_log)
        self.log_menu.add_command(label="清空日志", command=self.clear_log)
        self.log_text.bind("<Button-3>", self._show_log_menu)

        # ── 状态栏 ──
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W, foreground="blue").pack(side=tk.BOTTOM, fill=tk.X)

        # 初始化模式显示
        self.on_mode_change()

    # ── 界面交互 ──

    def on_mode_change(self):
        if self.mode_var.get() == "file":
            self.dir_frame.pack_forget()
            self.file_frame.pack(fill=tk.X, pady=(8, 0))
        else:
            self.file_frame.pack_forget()
            self.dir_frame.pack(fill=tk.X, pady=(8, 0))

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="选择 TXT 文件",
            initialdir=self.txt_path_var.get() or self.config.get("last_txt_dir", ""),
            filetypes=[("TXT 文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.txt_path_var.set(path)

    def browse_dir(self):
        path = filedialog.askdirectory(
            title="选择搜索目录",
            initialdir=self.search_dir_var.get() or self.config.get("last_search_dir", ""))
        if path:
            self.search_dir_var.set(path)

    def search_files(self):
        search_dir = self.search_dir_var.get().strip()
        keyword = self.keyword_var.get().strip()

        if not search_dir:
            messagebox.showwarning("提示", "请先选择目录")
            return

        dir_path = Path(search_dir)
        if not dir_path.exists():
            messagebox.showerror("错误", f"目录不存在:\n{search_dir}")
            return

        self.matched_files = []
        self.match_listbox.delete(0, tk.END)

        for f in sorted(dir_path.iterdir()):
            if f.is_file() and f.suffix.lower() == '.txt':
                if not keyword or keyword in f.stem:
                    self.matched_files.append(str(f))
                    self.match_listbox.insert(tk.END, f.name)

        self.match_count_label.config(text=f"匹配到 {len(self.matched_files)} 个 TXT 文件")
        if self.matched_files:
            self.match_listbox.select_set(0, tk.END)

    def browse_output_dir(self):
        path = filedialog.askdirectory(
            title="选择 JSON 保存目录",
            initialdir=self.output_dir_var.get() or self.config.get("last_output_dir", ""))
        if path:
            self.output_dir_var.set(path)

    def open_output_dir(self):
        out_dir = self.output_dir_var.get().strip()
        if out_dir and Path(out_dir).exists():
            os.startfile(out_dir)
        else:
            messagebox.showwarning("提示", "输出目录不存在")

    def _show_log_menu(self, event):
        self.log_menu.tk_popup(event.x_root, event.y_root)

    def _copy_log(self):
        try:
            sel = self.log_text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)
        except tk.TclError:
            pass

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ── 日志输出 ──

    def log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    # ── 配置读写 ──

    def load_config_to_ui(self):
        self.txt_path_var.set(self.config.get("last_txt_path", ""))
        self.search_dir_var.set(self.config.get("last_search_dir", ""))
        self.output_dir_var.set(self.config.get("last_output_dir", ""))
        self.split_length_var.set(str(self.config.get("split_length", 500)))

    def collect_config(self):
        return {
            "last_txt_path": self.txt_path_var.get().strip(),
            "last_search_dir": self.search_dir_var.get().strip(),
            "last_output_dir": self.output_dir_var.get().strip(),
            "split_length": int(self.split_length_var.get() or 500),
        }

    def save_current_config(self):
        cfg = self.collect_config()
        save_config(cfg)
        self.status_var.set("配置已保存")
        self.log("配置已保存")

    # ── 核心拆分逻辑 ──

    def run_split(self):
        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("提示", "请选择 JSON 保存目录")
            return

        try:
            split_length = int(self.split_length_var.get())
            if split_length <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "拆分字数必须为正整数")
            return

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 收集待处理文件
        txt_files = []
        if self.mode_var.get() == "file":
            txt_path = self.txt_path_var.get().strip()
            if not txt_path or not Path(txt_path).exists():
                messagebox.showerror("错误", "请选择有效的 TXT 文件")
                return
            txt_files.append(txt_path)
        else:
            selected = self.match_listbox.curselection()
            if not selected:
                messagebox.showwarning("提示", "请先搜索并选中要处理的 TXT 文件")
                return
            txt_files = [self.matched_files[i] for i in selected]

        # 保存配置
        save_config(self.collect_config())

        self.clear_log()
        self.log(f"拆分字数: {split_length}")
        self.log(f"待处理文件: {len(txt_files)} 个")
        self.log("-" * 50)

        total_segments = 0
        for txt_file in txt_files:
            total_segments += self._process_file(txt_file, output_dir, split_length)

        self.log("-" * 50)
        self.log(f"全部完成！共生成 {total_segments} 个片段")
        self.status_var.set(f"完成！共 {total_segments} 个片段")
        messagebox.showinfo("完成", f"拆分完成！\n共生成 {total_segments} 个片段")

    def _process_file(self, txt_file, output_dir, split_length):
        """处理单个 TXT 文件，返回生成的片段数"""
        file_name = Path(txt_file).stem
        self.log(f"\n处理: {Path(txt_file).name}")

        text = read_txt_file(txt_file)
        self.log(f"  读取 {len(text)} 个字符")

        # 过滤所有空格、换行等空白字符
        text = re.sub(r'\s+', '', text)
        self.log(f"  过滤空白后 {len(text)} 个字符")

        segments = split_text(text, split_length)
        self.log(f"  拆分为 {len(segments)} 个片段")

        # 构建 JSON 数据
        json_data = []
        for i, seg in enumerate(segments, 1):
            json_data.append({
                "num": str(i),
                "plotContent": seg
            })
            self.log(f"  [{i}] {len(seg)} 字符")

        # 保存 JSON（存在则直接替换）
        output_path = Path(output_dir) / f"{file_name}.json"
        if output_path.exists():
            self.log(f"  已存在同名文件，直接替换")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        self.log(f"  已保存: {output_path}")
        return len(segments)


# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    root = tk.Tk()
    app = TxtSplitApp(root)
    root.mainloop()
