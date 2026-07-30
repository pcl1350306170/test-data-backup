"""
Git项目图片Raw地址拼接工具
- 选择Git项目目录
- 配置Raw地址前缀
- 扫描所有图片文件，拼接为在线Raw地址
- 导出为JSON格式的TXT文件
"""

import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 支持的图片扩展名
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico', '.tiff', '.tif'}


class ImageRawUrlBuilder:
    def __init__(self, root):
        self.root = root
        self.root.title("Git项目图片Raw地址拼接工具")
        self.root.geometry("800x560")
        self.root.minsize(700, 480)

        self.git_dir = tk.StringVar()
        self.url_prefix = tk.StringVar(value="https://raw.githubusercontent.com/pcl1350306170/test-data-backup/refs/heads/main/")

        self._build_ui()

    def _build_ui(self):
        # --- 顶部配置区 ---
        config_frame = ttk.LabelFrame(self.root, text="配置", padding=10)
        config_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        # Git目录
        ttk.Label(config_frame, text="Git项目目录:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(config_frame, textvariable=self.git_dir, width=60).grid(row=0, column=1, padx=5, sticky=tk.EW)
        ttk.Button(config_frame, text="选择目录", command=self._select_dir).grid(row=0, column=2, padx=5)

        # URL前缀
        ttk.Label(config_frame, text="Raw地址前缀:").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(config_frame, textvariable=self.url_prefix, width=60).grid(row=1, column=1, padx=5, sticky=tk.EW, pady=(8, 0))

        config_frame.columnconfigure(1, weight=1)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(btn_frame, text="开始扫描", command=self._scan).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="保存为TXT", command=self._save).pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(btn_frame, text="就绪")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # --- 结果列表 ---
        result_frame = ttk.LabelFrame(self.root, text="扫描结果", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))

        columns = ("source", "address")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("source", text="相对目录 (source)")
        self.tree.heading("address", text="Raw地址 (address)")
        self.tree.column("source", width=220, minwidth=120)
        self.tree.column("address", width=540, minwidth=200)

        scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.results = []  # [{"source": ..., "address": ...}, ...]

    def _select_dir(self):
        d = filedialog.askdirectory(title="选择Git项目根目录")
        if d:
            self.git_dir.set(d)

    def _scan(self):
        git_dir = self.git_dir.get().strip()
        prefix = self.url_prefix.get().strip()

        if not git_dir or not os.path.isdir(git_dir):
            messagebox.showwarning("提示", "请先选择有效的Git项目目录")
            return
        if not os.path.isdir(os.path.join(git_dir, '.git')):
            messagebox.showwarning("提示", "所选目录不是Git仓库（未找到.git目录）")
            return
        if not prefix:
            messagebox.showwarning("提示", "请填写Raw地址前缀")
            return

        # 确保前缀以 / 结尾
        if not prefix.endswith('/'):
            prefix += '/'

        self.results.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        count = 0
        for root_path, dirs, files in os.walk(git_dir):
            # 跳过隐藏目录（如 .git, .idea 等）
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTENSIONS:
                    full_path = os.path.join(root_path, f)
                    rel_path = os.path.relpath(full_path, git_dir)
                    # 使用 / 拼接URL
                    url_path = rel_path.replace('\\', '/')
                    source_dir = os.path.relpath(root_path, git_dir)
                    if source_dir == '.':
                        source_dir = ''
                    source_display = source_dir if not source_dir else source_dir

                    address = prefix + url_path
                    self.results.append({
                        "source": source_display,
                        "address": address
                    })
                    self.tree.insert("", tk.END, values=(source_display, address))
                    count += 1

        self.status_label.config(text=f"共扫描到 {count} 张图片")

    def _save(self):
        if not self.results:
            messagebox.showwarning("提示", "没有数据可保存，请先扫描")
            return

        filepath = filedialog.asksaveasfilename(
            title="保存结果",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("JSON文件", "*.json"), ("所有文件", "*.*")]
        )
        if not filepath:
            return

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(json.dumps(self.results, ensure_ascii=False, indent=4))
            messagebox.showinfo("成功", f"已保存 {len(self.results)} 条记录到:\n{filepath}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageRawUrlBuilder(root)
    root.mainloop()
