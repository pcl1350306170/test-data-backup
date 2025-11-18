import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pymysql
import re
from pathlib import Path

# 配置路径设置（与epub_replace_txt_cover.py保持一致）
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "txt_replace"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
NOVEL_MAPPING_PATH = CONFIG_DIR / "novelMapping.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 确保配置目录存在
CONFIG_DIR.mkdir(exist_ok=True)

class TxtReplacerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TXT文本替换工具")
        self.root.geometry("800x800")

        # 初始化配置
        self.config = {
            "last_input_dir": "",
            "last_output_dir": "",
            "use_json": True,
            "use_db": True
        }

        # 数据存储
        self.selected_files = []
        self.json_replacements = {}  # 从novelMapping.json加载
        self.db_replacements = {}    # 从数据库加载

        # 创建界面
        self.create_widgets()

        # 加载配置和替换规则
        self.load_config()
        self.load_json_mappings()

    def create_widgets(self):
        # 主布局
        main_notebook = ttk.Notebook(self.root)
        main_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. 文件选择标签页
        file_frame = ttk.Frame(main_notebook)
        main_notebook.add(file_frame, text="文件选择")

        # 选择文件区域
        ttk.Label(file_frame, text="选择TXT文件:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=10)
        self.file_listbox = tk.Listbox(file_frame, width=60, height=10)
        self.file_listbox.grid(row=1, column=0, columnspan=2, padx=5, pady=5)

        # 滚动条
        scrollbar = ttk.Scrollbar(file_frame, orient="vertical", command=self.file_listbox.yview)
        scrollbar.grid(row=1, column=2, sticky=tk.NS)
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        # 按钮区域
        btn_frame = ttk.Frame(file_frame)
        btn_frame.grid(row=2, column=0, columnspan=3, pady=10)

        ttk.Button(btn_frame, text="添加文件...", command=self.add_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="移除选中", command=self.remove_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空列表", command=self.clear_file_list).pack(side=tk.LEFT, padx=5)

        # 输出目录选择
        ttk.Label(file_frame, text="输出目录:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=10)
        self.output_dir_var = tk.StringVar(value=self.config["last_output_dir"])
        ttk.Entry(file_frame, textvariable=self.output_dir_var, width=50).grid(row=3, column=1, padx=5, pady=10)
        ttk.Button(file_frame, text="浏览...", command=self.select_output_dir).grid(row=3, column=2, padx=5, pady=10)

        # 2. 替换设置标签页
        settings_frame = ttk.Frame(main_notebook)
        main_notebook.add(settings_frame, text="替换设置")

        # 替换选项
        self.use_json = tk.BooleanVar(value=self.config["use_json"])
        ttk.Checkbutton(settings_frame, text="使用novelMapping.json替换规则", variable=self.use_json).grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=5)

        self.use_db = tk.BooleanVar(value=self.config["use_db"])
        ttk.Checkbutton(settings_frame, text="使用数据库替换规则", variable=self.use_db).grid(
            row=1, column=0, sticky=tk.W, padx=5, pady=5)

        # 数据库连接测试
        ttk.Button(settings_frame, text="测试数据库连接", command=self.test_db_connection).grid(
            row=2, column=0, padx=5, pady=10, sticky=tk.W)

        # JSON替换规则预览
        ttk.Label(settings_frame, text="JSON替换规则预览:").grid(
            row=3, column=0, sticky=tk.NW, padx=5, pady=5)
        self.json_preview = tk.Text(settings_frame, height=10, width=60)
        self.json_preview.grid(row=4, column=0, padx=5, pady=5)
        self.json_preview.config(state=tk.DISABLED)

        # 数据库替换规则预览
        ttk.Label(settings_frame, text="数据库替换规则预览:").grid(
            row=5, column=0, sticky=tk.NW, padx=5, pady=5)
        self.db_preview = tk.Text(settings_frame, height=10, width=60)
        self.db_preview.grid(row=6, column=0, padx=5, pady=5)
        self.db_preview.config(state=tk.DISABLED)

        # 3. 日志标签页
        log_frame = ttk.Frame(main_notebook)
        main_notebook.add(log_frame, text="操作日志")

        ttk.Label(log_frame, text="执行日志:").pack(anchor=tk.W, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, height=20, width=80)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)

        # 底部按钮
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="加载替换规则", command=self.load_all_replacements).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="执行替换", command=self.execute_replacement).pack(side=tk.RIGHT, padx=10)

    def log(self, message):
        """添加日志信息"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def add_files(self):
        """添加TXT文件"""
        initial_dir = self.config["last_input_dir"] if self.config["last_input_dir"] else str(SCRIPT_DIR)

        files = filedialog.askopenfilenames(
            title="选择TXT文件",
            filetypes=[("TXT文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=initial_dir
        )

        if files:
            # 更新最后访问目录
            self.config["last_input_dir"] = os.path.dirname(files[0])

            # 添加文件到列表
            for file in files:
                if file not in self.selected_files:
                    self.selected_files.append(file)
                    self.file_listbox.insert(tk.END, os.path.basename(file))

            self.log(f"已添加 {len(files)} 个文件")

    def remove_selected(self):
        """移除选中的文件"""
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            return

        # 从后往前删除，避免索引偏移
        for i in sorted(selected_indices, reverse=True):
            del self.selected_files[i]
            self.file_listbox.delete(i)

        self.log(f"已移除 {len(selected_indices)} 个文件")

    def clear_file_list(self):
        """清空文件列表"""
        if self.selected_files:
            self.selected_files.clear()
            self.file_listbox.delete(0, tk.END)
            self.log("已清空文件列表")

    def select_output_dir(self):
        """选择输出目录"""
        initial_dir = self.config["last_output_dir"] if self.config["last_output_dir"] else str(SCRIPT_DIR)

        dir_path = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=initial_dir
        )

        if dir_path:
            self.output_dir_var.set(dir_path)
            self.config["last_output_dir"] = dir_path
            self.log(f"已选择输出目录: {dir_path}")

    def load_json_mappings(self):
        """加载novelMapping.json替换规则（与EPUB工具路径一致）"""
        try:
            if os.path.exists(NOVEL_MAPPING_PATH):
                with open(NOVEL_MAPPING_PATH, "r", encoding="utf-8") as f:
                    self.json_replacements = json.load(f)

                self.log(f"已加载JSON替换规则，共 {len(self.json_replacements)} 条")
                self.update_json_preview()
            else:
                self.log(f"未找到JSON配置文件: {NOVEL_MAPPING_PATH}")
                self.json_replacements = {}
        except Exception as e:
            self.log(f"加载JSON配置失败: {str(e)}")
            self.json_replacements = {}

    def update_json_preview(self):
        """更新JSON替换规则预览"""
        self.json_preview.config(state=tk.NORMAL)
        self.json_preview.delete(1.0, tk.END)
        if self.json_replacements:
            for i, (old, new) in enumerate(self.json_replacements.items()):
                if i < 20:  # 只显示前20条
                    self.json_preview.insert(tk.END, f"{old} → {new}\n")
            if len(self.json_replacements) > 20:
                self.json_preview.insert(tk.END, f"... 共 {len(self.json_replacements)} 条规则\n")
        else:
            self.json_preview.insert(tk.END, "未加载任何JSON替换规则")
        self.json_preview.config(state=tk.DISABLED)

    def load_db_config(self):
        """加载数据库配置（与EPUB工具路径一致）"""
        try:
            if os.path.exists(DB_CONFIG_PATH):
                with open(DB_CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                self.log(f"未找到数据库配置文件: {DB_CONFIG_PATH}")
                return None
        except Exception as e:
            self.log(f"加载数据库配置失败: {str(e)}")
            return None

    def test_db_connection(self):
        """测试数据库连接"""
        db_config = self.load_db_config()
        if not db_config:
            messagebox.showerror("错误", "数据库配置加载失败")
            return

        try:
            conn = pymysql.connect(
                host=db_config["host"],
                port=db_config["port"],
                user=db_config["user"],
                password=db_config["password"],
                database=db_config["database"],
                charset=db_config["charset"]
            )
            conn.close()
            messagebox.showinfo("成功", "数据库连接测试成功")
            self.log("数据库连接测试成功")
        except Exception as e:
            messagebox.showerror("错误", f"数据库连接失败: {str(e)}")
            self.log(f"数据库连接测试失败: {str(e)}")

    def load_db_replacements(self):
        """从数据库加载替换规则（与EPUB工具逻辑一致）"""
        self.db_replacements = {}
        db_config = self.load_db_config()
        if not db_config:
            return False

        try:
            conn = pymysql.connect(
                host=db_config["host"],
                port=db_config["port"],
                user=db_config["user"],
                password=db_config["password"],
                database=db_config["database"],
                charset=db_config["charset"]
            )
            cursor = conn.cursor()
            cursor.execute("SELECT `old`, `new` FROM v_pornographic_novel_replacement_string")
            results = cursor.fetchall()

            for old, new in results:
                self.db_replacements[str(old)] = str(new)

            cursor.close()
            conn.close()

            self.log(f"已加载数据库替换规则，共 {len(self.db_replacements)} 条")
            self.update_db_preview()
            return True
        except Exception as e:
            self.log(f"加载数据库替换规则失败: {str(e)}")
            return False

    def update_db_preview(self):
        """更新数据库替换规则预览"""
        self.db_preview.config(state=tk.NORMAL)
        self.db_preview.delete(1.0, tk.END)
        if self.db_replacements:
            for i, (old, new) in enumerate(self.db_replacements.items()):
                if i < 20:  # 只显示前20条
                    self.db_preview.insert(tk.END, f"{old} → {new}\n")
            if len(self.db_replacements) > 20:
                self.db_preview.insert(tk.END, f"... 共 {len(self.db_replacements)} 条规则\n")
        else:
            self.db_preview.insert(tk.END, "未加载任何数据库替换规则")
        self.db_preview.config(state=tk.DISABLED)

    def load_all_replacements(self):
        """加载所有替换规则"""
        self.log("开始加载替换规则...")
        self.load_json_mappings()
        if self.use_db.get():
            self.load_db_replacements()
        self.log("替换规则加载完成")

    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
                self.log(f"已加载配置文件: {CONFIG_PATH}")
        except Exception as e:
            self.log(f"加载配置文件失败: {str(e)}")

    def save_config(self):
        """保存配置文件"""
        try:
            self.config = {
                "last_input_dir": self.config["last_input_dir"],
                "last_output_dir": self.output_dir_var.get(),
                "use_json": self.use_json.get(),
                "use_db": self.use_db.get()
            }

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.log(f"配置已保存到: {CONFIG_PATH}")
            messagebox.showinfo("成功", "配置保存成功")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def replace_text_content(self, content):
        """替换文本内容（合并JSON和数据库规则）"""
        replacements = {}

        # 合并替换规则（数据库规则优先级高于JSON）
        if self.use_json.get():
            replacements.update(self.json_replacements)
        if self.use_db.get():
            replacements.update(self.db_replacements)

        if not replacements:
            return content, 0

        # 构建替换正则表达式（按长度排序，避免部分匹配）
        pattern = re.compile('|'.join(re.escape(k) for k in sorted(replacements.keys(), key=len, reverse=True)))
        count = 0

        # 自定义替换函数，用于计数
        def replace_match(match):
            nonlocal count
            count += 1
            return replacements[match.group(0)]

        new_content = pattern.sub(replace_match, content)
        return new_content, count

    def process_single_file(self, input_path, output_path):
        """处理单个TXT文件"""
        try:
            # 读取文件内容
            with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            # 替换内容
            new_content, count = self.replace_text_content(content)

            # 写入新文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            return count
        except Exception as e:
            self.log(f"处理文件 {os.path.basename(input_path)} 失败: {str(e)}")
            return -1

    def execute_replacement(self):
        """执行替换操作"""
        # 检查是否选择了文件
        if not self.selected_files:
            messagebox.showerror("错误", "请先添加TXT文件")
            return

        # 确保替换规则已加载
        if self.use_json.get() and not self.json_replacements:
            self.load_json_mappings()
        if self.use_db.get() and not self.db_replacements:
            self.load_db_replacements()

        # 检查是否有替换规则
        active_rules = {}
        if self.use_json.get():
            active_rules.update(self.json_replacements)
        if self.use_db.get():
            active_rules.update(self.db_replacements)

        if not active_rules:
            if messagebox.askyesno("确认", "没有启用任何替换规则，是否继续?"):
                self.log("没有启用替换规则，直接复制文件")
            else:
                return

        # 检查输出目录
        output_dir = self.output_dir_var.get()
        if not output_dir:
            messagebox.showerror("错误", "请选择输出目录")
            return

        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                self.log(f"创建输出目录: {output_dir}")
            except Exception as e:
                messagebox.showerror("错误", f"无法创建输出目录: {str(e)}")
                return

        # 执行替换
        self.log("===== 开始执行替换操作 =====")
        total_replacements = 0
        success_count = 0

        for input_path in self.selected_files:
            file_name = os.path.basename(input_path)
            output_path = os.path.join(output_dir, file_name)

            # 避免覆盖原文件
            if os.path.abspath(input_path) == os.path.abspath(output_path):
                name, ext = os.path.splitext(file_name)
                output_path = os.path.join(output_dir, f"{name}_modified{ext}")
                self.log(f"原文件路径与输出路径相同，自动重命名为: {os.path.basename(output_path)}")

            # 处理文件
            count = self.process_single_file(input_path, output_path)

            if count >= 0:
                success_count += 1
                total_replacements += count
                self.log(f"处理完成: {file_name}，替换 {count} 处")

        # 保存配置
        self.save_config()

        # 显示结果
        self.log(f"===== 处理完成 =====")
        self.log(f"成功处理 {success_count}/{len(self.selected_files)} 个文件")
        self.log(f"总计替换 {total_replacements} 处内容")
        self.log(f"文件已保存至: {output_dir}")

        messagebox.showinfo("完成",
                            f"成功处理 {success_count}/{len(self.selected_files)} 个文件\n"
                            f"总计替换 {total_replacements} 处内容\n"
                            f"文件已保存至: {output_dir}")

if __name__ == "__main__":
    # 检查依赖
    try:
        import pymysql
    except ImportError:
        print("请先安装pymysql: pip install pymysql")
        exit(1)

    root = tk.Tk()
    app = TxtReplacerApp(root)
    root.mainloop()
