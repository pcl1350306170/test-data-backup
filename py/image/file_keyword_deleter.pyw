# file_keyword_deleter.pyw

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import logging
from datetime import datetime

# 日志配置（保存在脚本同级目录）
SCRIPT_DIR = Path(__file__).parent
LOG_FILE = SCRIPT_DIR / "json/logs/file_keyword_deleter.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    encoding='utf-8'
)

class FileDeleterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文件关键词删除工具")
        self.root.geometry("800x600")
        self.root.minsize(700, 500)

        # 变量
        self.target_dir = tk.StringVar()
        self.keyword_input = tk.StringVar()
        self.files_to_delete = []

        self._create_widgets()

    def _select_directory(self):
        folder = filedialog.askdirectory(title="请选择要清理的文件夹")
        if folder:
            self.target_dir.set(folder)
            self._log(f"已选择目录: {folder}")

    def _scan_files(self):
        directory = self.target_dir.get()
        keywords_str = self.keyword_input.get().strip()

        if not directory or not Path(directory).is_dir():
            messagebox.showwarning("警告", "请先选择一个有效的目录！")
            return

        if not keywords_str:
            messagebox.showwarning("警告", "请输入关键词！")
            return

        # 支持多个关键词（逗号或空格分隔）
        keywords = [k.strip() for k in keywords_str.replace('，', ',').split(',') if k.strip()]
        if not keywords:
            messagebox.showwarning("警告", "关键词不能为空！")
            return

        self.files_to_delete = []
        try:
            for file_path in Path(directory).rglob("*"):
                if file_path.is_file():
                    filename = file_path.name
                    if any(kw in filename for kw in keywords):
                        self.files_to_delete.append(str(file_path))
        except Exception as e:
            messagebox.showerror("错误", f"扫描文件时出错:\n{e}")
            return

        # 显示结果
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete(1.0, tk.END)
        if self.files_to_delete:
            self.result_text.insert(tk.END, f"🔍 找到 {len(self.files_to_delete)} 个匹配文件:\n\n")
            for f in self.files_to_delete:
                self.result_text.insert(tk.END, f"{f}\n")
        else:
            self.result_text.insert(tk.END, "✅ 未找到包含关键词的文件。")
        self.result_text.config(state=tk.DISABLED)

        self._log(f"扫描完成，关键词: {keywords}，匹配文件数: {len(self.files_to_delete)}")

    def _delete_files(self):
        if not self.files_to_delete:
            messagebox.showinfo("提示", "没有文件需要删除。")
            return

        confirm = messagebox.askyesno(
            "确认删除",
            f"⚠️ 确定要删除这 {len(self.files_to_delete)} 个文件吗？\n此操作不可撤销！"
        )
        if not confirm:
            return

        success_count = 0
        fail_list = []

        for file_path in self.files_to_delete:
            try:
                Path(file_path).unlink()
                success_count += 1
            except Exception as e:
                fail_list.append((file_path, str(e)))

        # 更新日志和界面
        self._log(f"删除完成 - 成功: {success_count}, 失败: {len(fail_list)}")
        if fail_list:
            error_msg = "\n".join([f"{f}: {e}" for f, e in fail_list[:5]])  # 最多显示5条
            messagebox.showwarning("部分失败", f"有 {len(fail_list)} 个文件删除失败，例如:\n{error_msg}")
        else:
            messagebox.showinfo("完成", f"✅ 成功删除 {success_count} 个文件！")

        # 清空并重新扫描（可选）
        self._scan_files()

    def _log(self, message):
        logging.info(message)

    def _create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 目录选择
        dir_frame = ttk.Frame(main)
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Label(dir_frame, text="目标目录:").pack(side=tk.LEFT)
        ttk.Entry(dir_frame, textvariable=self.target_dir, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(dir_frame, text="浏览...", command=self._select_directory).pack(side=tk.RIGHT)

        # 关键词输入
        kw_frame = ttk.Frame(main)
        kw_frame.pack(fill=tk.X, pady=5)
        ttk.Label(kw_frame, text="关键词:").pack(side=tk.LEFT)
        ttk.Entry(kw_frame, textvariable=self.keyword_input, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(kw_frame, text="扫描文件", command=self._scan_files).pack(side=tk.RIGHT)

        # 说明标签
        help_label = ttk.Label(
            main,
            text="💡 提示：关键词支持多个，用英文逗号分隔（如：temp, backup, old）",
            foreground="gray"
        )
        help_label.pack(anchor=tk.W, pady=(0, 10))

        # 结果展示
        result_frame = ttk.LabelFrame(main, text="将被删除的文件（预览）", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.result_text = scrolledtext.ScrolledText(result_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # 操作按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="删除选中文件", command=self._delete_files, style="Accent.TButton").pack(side=tk.RIGHT)

if __name__ == "__main__":
    root = tk.Tk()
    app = FileDeleterApp(root)
    root.mainloop()
