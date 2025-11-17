import os
import json
import logging
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import time

# 配置与常量
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "batch_renamer"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
PROCESS_LOG_FILE.parent.mkdir(exist_ok=True, parents=True)

# 默认配置
DEFAULT_CONFIG = {
    "target_dir": r"H:\NOVEL\合集\old\HH",
    "replace_rules": ["《", "》", "章节", "已完结", "_", "-"],
    "remove_parentheses": True,  # 删除各类括号及内容
    "remove_numbers": True       # 删除数字
}

# 加载配置
def load_config():
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 兼容旧配置
                if "remove_parentheses" not in config:
                    config["remove_parentheses"] = DEFAULT_CONFIG["remove_parentheses"]
                if "remove_numbers" not in config:
                    config["remove_numbers"] = DEFAULT_CONFIG["remove_numbers"]
                return config
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        logging.error(f"加载配置失败: {str(e)}")
        return DEFAULT_CONFIG.copy()

# 保存配置
def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"保存配置失败: {str(e)}")
        return False

class BatchRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("批量文件重命名工具")
        self.root.geometry("750x600")
        self.root.resizable(True, True)

        # 加载配置
        self.config = load_config()
        self.target_dir = tk.StringVar(value=self.config["target_dir"])
        self.replace_rules = self.config["replace_rules"].copy()
        self.remove_parentheses = tk.BooleanVar(value=self.config["remove_parentheses"])
        self.remove_numbers = tk.BooleanVar(value=self.config["remove_numbers"])

        # 初始化日志
        self.setup_logging()

        # 创建界面
        self.create_widgets()

    def setup_logging(self):
        """配置日志系统"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(PROCESS_LOG_FILE, encoding="utf-8"),
                logging.StreamHandler()
            ]
        )

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 目标文件夹选择
        ttk.Label(main_frame, text="目标文件夹:").pack(anchor=tk.W, pady=(0, 5))
        dir_frame = ttk.Frame(main_frame)
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(dir_frame, textvariable=self.target_dir, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(dir_frame, text="浏览...", command=self.browse_dir).pack(side=tk.RIGHT, padx=5)

        # 替换规则设置
        ttk.Label(main_frame, text="替换规则（将以下字符替换为空）:").pack(anchor=tk.W, pady=(0, 5))

        # 规则列表
        rule_frame = ttk.Frame(main_frame)
        rule_frame.pack(fill=tk.X, pady=(0, 10))

        self.rule_listbox = tk.Listbox(rule_frame, height=6, selectmode=tk.SINGLE)
        self.rule_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        for rule in self.replace_rules:
            self.rule_listbox.insert(tk.END, rule)

        # 规则操作按钮
        btn_frame = ttk.Frame(rule_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y)

        self.new_rule_var = tk.StringVar()
        ttk.Entry(btn_frame, textvariable=self.new_rule_var, width=10).pack(pady=(0, 5))
        ttk.Button(btn_frame, text="添加", command=self.add_rule).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(btn_frame, text="删除选中", command=self.delete_rule).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(btn_frame, text="恢复默认", command=self.reset_rules).pack(fill=tk.X)

        # 括号处理选项
        parentheses_frame = ttk.Frame(main_frame)
        parentheses_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(
            parentheses_frame,
            text="删除所有括号及其中的内容（包括()、[]、【】、{}）",
            variable=self.remove_parentheses
        ).pack(anchor=tk.W)

        # 数字处理选项
        numbers_frame = ttk.Frame(main_frame)
        numbers_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Checkbutton(
            numbers_frame,
            text="删除文件名中的所有数字（0-9）",
            variable=self.remove_numbers
        ).pack(anchor=tk.W)

        # 操作按钮
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Button(action_frame, text="保存配置", command=self.save_current_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="预览效果", command=self.preview_rename).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="执行重命名", command=self.execute_rename).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="查看日志", command=self.view_log).pack(side=tk.LEFT, padx=5)

        # 日志/预览区域
        ttk.Label(main_frame, text="操作日志/预览:").pack(anchor=tk.W, pady=(0, 5))
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        # 绑定日志到文本框
        class TextHandler(logging.StreamHandler):
            def __init__(self, text_widget):
                logging.StreamHandler.__init__(self)
                self.text_widget = text_widget

            def emit(self, record):
                msg = self.format(record) + "\n"
                self.text_widget.configure(state=tk.NORMAL)
                self.text_widget.insert(tk.END, msg)
                self.text_widget.see(tk.END)
                self.text_widget.configure(state=tk.DISABLED)

        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(text_handler)

    def browse_dir(self):
        """选择目标文件夹"""
        dir_path = filedialog.askdirectory(title="选择目标文件夹")
        if dir_path:
            self.target_dir.set(dir_path)

    def add_rule(self):
        """添加新的替换规则"""
        new_rule = self.new_rule_var.get().strip()
        if new_rule and new_rule not in self.replace_rules:
            self.replace_rules.append(new_rule)
            self.rule_listbox.insert(tk.END, new_rule)
            self.new_rule_var.set("")
            logging.info(f"已添加替换规则: '{new_rule}'")

    def delete_rule(self):
        """删除选中的替换规则"""
        try:
            selected_idx = self.rule_listbox.curselection()[0]
            deleted_rule = self.replace_rules.pop(selected_idx)
            self.rule_listbox.delete(selected_idx)
            logging.info(f"已删除替换规则: '{deleted_rule}'")
        except (IndexError, ValueError):
            messagebox.showwarning("提示", "请先选中要删除的规则")

    def reset_rules(self):
        """恢复默认替换规则"""
        self.replace_rules = DEFAULT_CONFIG["replace_rules"].copy()
        self.rule_listbox.delete(0, tk.END)
        for rule in self.replace_rules:
            self.rule_listbox.insert(tk.END, rule)
        logging.info("已恢复默认替换规则")

    def save_current_config(self):
        """保存当前配置"""
        new_config = {
            "target_dir": self.target_dir.get(),
            "replace_rules": self.replace_rules.copy(),
            "remove_parentheses": self.remove_parentheses.get(),
            "remove_numbers": self.remove_numbers.get()
        }
        if save_config(new_config):
            self.config = new_config.copy()
            messagebox.showinfo("成功", "配置已保存")
            logging.info("配置已保存到文件")
        else:
            messagebox.showerror("错误", "配置保存失败")

    def view_log(self):
        """查看日志文件"""
        try:
            if os.path.exists(PROCESS_LOG_FILE):
                os.startfile(PROCESS_LOG_FILE)
            else:
                messagebox.showinfo("提示", "日志文件不存在")
        except Exception as e:
            logging.error(f"打开日志文件失败: {str(e)}")
            messagebox.showerror("错误", f"无法打开日志文件: {str(e)}")

    def get_renamed_filename(self, original_name):
        """应用所有规则获取新文件名"""
        new_name = original_name

        # 1. 删除所有括号及内容（包括中文括号）
        if self.remove_parentheses.get():
            # 匹配规则：()、[]、【】、{} 及其中的内容
            new_name = re.sub(
                r'\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】|\{[^\{\}]*\}',
                '',
                new_name
            )

        # 2. 删除所有数字
        if self.remove_numbers.get():
            new_name = re.sub(r'[0-9]', '', new_name)

        # 3. 替换指定字符为空
        for char in self.replace_rules:
            new_name = new_name.replace(char, "")

        # 4. 处理可能产生的连续空格（可选优化）
        new_name = re.sub(r'\s+', ' ', new_name).strip()

        return new_name

    def preview_rename(self):
        """预览重命名效果"""
        target_dir = self.target_dir.get()
        if not os.path.exists(target_dir):
            messagebox.showerror("错误", f"目标文件夹不存在: {target_dir}")
            return

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, "\n====== 预览重命名效果 ======\n")

        try:
            files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
            if not files:
                self.log_text.insert(tk.END, "目标文件夹中没有文件\n")
                self.log_text.config(state=tk.DISABLED)
                return

            for file in files:
                new_name = self.get_renamed_filename(file)
                if new_name != file:
                    self.log_text.insert(tk.END, f"原文件名: {file} → 新文件名: {new_name}\n")
                else:
                    self.log_text.insert(tk.END, f"原文件名: {file} (无需修改)\n")

        except Exception as e:
            self.log_text.insert(tk.END, f"预览出错: {str(e)}\n")
        finally:
            self.log_text.insert(tk.END, "====== 预览结束 ======\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

    def execute_rename(self):
        """执行批量重命名"""
        target_dir = self.target_dir.get()
        if not os.path.exists(target_dir):
            messagebox.showerror("错误", f"目标文件夹不存在: {target_dir}")
            return

        if not messagebox.askyesno("确认", "确定要执行批量重命名吗？此操作不可撤销！"):
            return

        logging.info("====== 开始执行批量重命名 ======")
        logging.info(f"目标文件夹: {target_dir}")
        logging.info(f"替换规则: {self.replace_rules}")
        logging.info(f"是否删除括号及内容: {self.remove_parentheses.get()}")
        logging.info(f"是否删除数字: {self.remove_numbers.get()}")

        renamed_count = 0
        skipped_count = 0

        try:
            files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]

            for file in files:
                original_path = os.path.join(target_dir, file)
                new_name = self.get_renamed_filename(file)

                if new_name == file:
                    logging.info(f"跳过: {file} (无需修改)")
                    skipped_count += 1
                    continue

                new_path = os.path.join(target_dir, new_name)

                # 处理重名
                if os.path.exists(new_path):
                    name, ext = os.path.splitext(new_name)
                    counter = 1
                    while os.path.exists(os.path.join(target_dir, f"{name}_{counter}{ext}")):
                        counter += 1
                    new_name = f"{name}_{counter}{ext}"
                    new_path = os.path.join(target_dir, new_name)
                    logging.warning(f"文件已存在，自动重命名为: {new_name}")

                # 执行重命名
                os.rename(original_path, new_path)
                logging.info(f"重命名成功: {file} → {new_name}")
                renamed_count += 1

            logging.info("====== 批量重命名完成 ======")
            logging.info(f"总计: {len(files)} 个文件，成功重命名: {renamed_count} 个，跳过: {skipped_count} 个")
            messagebox.showinfo("完成", f"重命名完成\n成功: {renamed_count} 个\n跳过: {skipped_count} 个")

        except Exception as e:
            logging.error(f"重命名过程出错: {str(e)}", exc_info=True)
            messagebox.showerror("错误", f"操作失败: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = BatchRenamerApp(root)
    root.mainloop()
