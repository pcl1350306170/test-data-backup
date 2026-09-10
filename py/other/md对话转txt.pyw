# -*- coding: utf-8 -*-
"""md对话记录转纯文本txt（支持 Grok 导出的 md 聊天记录）
- 勾选"仅获取Assistant内容"：只输出 Assistant 消息；不勾选：User+Assistant 都输出
- 选择 md 文件、输入或选择输出目录、可自定义输出文件名
- markdown 标记只留文字：去掉代码块/链接/图片、粗体斜体标题列表引用等符号
- 配置保存到 json（UI 状态记忆）
"""
import os
import re
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, "json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config_md_to_txt.json")

ROLE_USER = "**User:**"
ROLE_ASSISTANT = "**Assistant:**"
ROLE_RE = re.compile(r"^\*\*([^*]+):\*\*\s*$")


def strip_markdown_to_text(text):
    """markdown -> 纯文本（只留文字）"""
    # 1. 删除代码块（含围栏）
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    # 2. 删除图片、链接（整个去掉）
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", "", text)
    out = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        # 水平线整行删除
        if re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", line):
            continue
        # 标题 / 引用 去符号
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s{0,3}>\s?", "", line)
        # 无序列表 / 有序列表 去符号
        line = re.sub(r"^\s{0,3}[-*+]\s+", "", line)
        line = re.sub(r"^\s{0,3}\d+[.)]\s+", "", line)
        # 行内代码 / 粗体 / 斜体 去符号
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\*([^*]+)\*", r"\1", line)
        # 表格：去掉 | 用空格连接
        line = re.sub(r"\|", " ", line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        out.append(line)
    # 3. 压缩连续空行：最多保留 1 个空行
    cleaned = []
    blank = 0
    for line in out:
        if not line:
            blank += 1
            if blank <= 1:
                cleaned.append("")
        else:
            blank = 0
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def parse_md_messages(content):
    """按 **User:** / **Assistant:** 标签切分消息，返回 [(role, body), ...]
    其他角色标签（如 **System:**、**Tool:**）忽略，不产生消息。"""
    messages = []
    cur_role = None
    buf = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped in (ROLE_USER, ROLE_ASSISTANT):
            if cur_role is not None:
                messages.append((cur_role, "\n".join(buf)))
            cur_role = "User" if stripped == ROLE_USER else "Assistant"
            buf = []
            continue
        # 其他整行粗体角色标签 -> 忽略该角色消息（含其内容）
        if cur_role is not None and ROLE_RE.match(stripped):
            messages.append((cur_role, "\n".join(buf)))
            cur_role = None
            buf = []
            continue
        if cur_role is not None:
            buf.append(line)
    if cur_role is not None:
        messages.append((cur_role, "\n".join(buf)))
    return messages


def md_to_txt(md_path, only_assistant):
    """读取 md 文件并转换为纯文本内容"""
    with open(md_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    messages = parse_md_messages(content)
    parts = []
    for role, body in messages:
        if only_assistant and role != "Assistant":
            continue
        text = strip_markdown_to_text(body)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


# ---------------- GUI ----------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("md对话记录转txt")
        root.geometry("680x300")
        root.resizable(False, False)

        self.only_assistant = tk.BooleanVar(value=True)
        self.md_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self.out_name = tk.StringVar()
        self.status = tk.StringVar(value="请选择 md 文件")

        self._custom_name = False
        self._load_config()

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Checkbutton(frm, text="仅获取 “Assistant” 内容（不勾选则 User + Assistant 都获取）",
                        variable=self.only_assistant).grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        ttk.Label(frm, text="md 文件：").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.md_path, state="readonly").grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(frm, text="选择…", command=self.choose_md).grid(row=1, column=2, **pad)

        ttk.Label(frm, text="输出目录：").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.out_dir).grid(row=2, column=1, sticky="we", **pad)
        ttk.Button(frm, text="浏览…", command=self.choose_dir).grid(row=2, column=2, **pad)

        ttk.Label(frm, text="输出文件名：").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.out_name).grid(row=3, column=1, sticky="we", **pad)
        ttk.Label(frm, text=".txt").grid(row=3, column=2, sticky="w", **pad)

        frm.rowconfigure(4, minsize=12)
        ttk.Button(frm, text="开始转换", command=self.convert).grid(row=5, column=0, columnspan=3, **pad)
        ttk.Label(frm, textvariable=self.status, foreground="#666").grid(row=6, column=0, columnspan=3, sticky="w", **pad)

        frm.columnconfigure(1, weight=1)

    # ---- 配置 ----
    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                self.only_assistant.set(bool(cfg.get("only_assistant", True)))
                self.md_path.set(cfg.get("last_md", ""))
                self.out_dir.set(cfg.get("output_dir", ""))
                self.out_name.set(cfg.get("output_name", ""))
                if self.out_name.get():
                    self._custom_name = True
        except Exception:
            pass

    def _save_config(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            cfg = {
                "only_assistant": bool(self.only_assistant.get()),
                "last_md": self.md_path.get(),
                "output_dir": self.out_dir.get(),
                "output_name": self.out_name.get(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")

    # ---- 事件 ----
    def choose_md(self):
        path = filedialog.askopenfilename(
            title="选择 md 文件", filetypes=[("Markdown 文件", "*.md"), ("所有文件", "*.*")])
        if not path:
            return
        self.md_path.set(path)
        if not self._custom_name:
            name = os.path.splitext(os.path.basename(path))[0] + ".txt"
            self.out_name.set(name)
        if not self.out_dir.get():
            self.out_dir.set(os.path.dirname(path))
        self.status.set(f"已选择：{path}")

    def choose_dir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.out_dir.set(d)

    def convert(self):
        md = self.md_path.get().strip()
        out_dir = self.out_dir.get().strip()
        out_name = self.out_name.get().strip()
        if not md:
            messagebox.showwarning("提示", "请先选择 md 文件")
            return
        if not os.path.isfile(md):
            messagebox.showerror("错误", f"md 文件不存在：\n{md}")
            return
        if not out_dir:
            messagebox.showwarning("提示", "请填写或选择输出目录")
            return
        if not out_name:
            out_name = os.path.splitext(os.path.basename(md))[0] + ".txt"
            self.out_name.set(out_name)
        if not out_name.lower().endswith(".txt"):
            out_name += ".txt"
            self.out_name.set(out_name)
        try:
            os.makedirs(out_dir, exist_ok=True)
            only = bool(self.only_assistant.get())
            content = md_to_txt(md, only)
            out_path = os.path.join(out_dir, out_name)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._save_config()
            self.status.set(f"转换完成：{out_path}")
            messagebox.showinfo("完成", f"转换完成：\n{out_path}")
        except Exception as e:
            self.status.set(f"转换失败：{e}")
            messagebox.showerror("错误", f"转换失败：\n{e}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
