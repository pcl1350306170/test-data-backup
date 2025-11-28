import os
import json
import zipfile
import tempfile
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import sqlite3
import pymysql
from PIL import Image, ImageTk
import re
from pathlib import Path

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "epub_replace_txt_cover"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"{SCRIPT_NAME}_config.json"
NOVEL_MAPPING_PATH = CONFIG_DIR / "novelMapping.json"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 确保目录存在
CONFIG_DIR.mkdir(exist_ok=True)

class EpubReplacerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB内容替换工具")
        self.root.geometry("800x800")

        # 初始化配置
        self.config = {
            "last_epub_path": "",
            "last_cover_path": "",
            "replace_json": True,
            "replace_db": True
        }

        # 数据存储
        self.epub_path = ""
        self.cover_path = ""
        self.json_replacements = {}
        self.db_replacements = {}

        # 创建界面
        self.create_widgets()

        # 加载JSON替换规则
        self.load_config()
        self.load_json_mappings()

    def create_widgets(self):
        # 主布局
        main_notebook = ttk.Notebook(self.root)
        main_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 1. 文件选择标签页
        file_frame = ttk.Frame(main_notebook)
        main_notebook.add(file_frame, text="文件选择")

        # EPUB文件选择
        ttk.Label(file_frame, text="EPUB文件:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=10)
        self.epub_var = tk.StringVar(value=self.config["last_epub_path"])
        ttk.Entry(file_frame, textvariable=self.epub_var, width=60).grid(row=0, column=1, padx=5, pady=10)
        ttk.Button(file_frame, text="浏览...", command=self.select_epub).grid(row=0, column=2, padx=5, pady=10)

        # 封面图片选择
        ttk.Label(file_frame, text="新封面图片:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=10)
        self.cover_var = tk.StringVar(value=self.config["last_cover_path"])
        ttk.Entry(file_frame, textvariable=self.cover_var, width=60).grid(row=1, column=1, padx=5, pady=10)
        ttk.Button(file_frame, text="浏览...", command=self.select_cover).grid(row=1, column=2, padx=5, pady=10)

        # 封面预览
        ttk.Label(file_frame, text="封面预览:").grid(row=2, column=0, sticky=tk.NW, padx=5, pady=10)
        self.cover_preview = ttk.Label(file_frame)
        self.cover_preview.grid(row=2, column=1, padx=5, pady=10)
        self.update_cover_preview()

        # 2. 替换设置标签页
        settings_frame = ttk.Frame(main_notebook)
        main_notebook.add(settings_frame, text="替换设置")

        # 替换选项
        self.use_json = tk.BooleanVar(value=self.config["replace_json"])
        ttk.Checkbutton(settings_frame, text="使用JSON配置替换", variable=self.use_json).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)

        self.use_db = tk.BooleanVar(value=self.config["replace_db"])
        ttk.Checkbutton(settings_frame, text="使用数据库替换", variable=self.use_db).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)

        # 数据库连接测试
        ttk.Button(settings_frame, text="测试数据库连接", command=self.test_db_connection).grid(row=2, column=0, padx=5, pady=10, sticky=tk.W)

        # JSON替换规则预览
        ttk.Label(settings_frame, text="JSON替换规则:").grid(row=3, column=0, sticky=tk.NW, padx=5, pady=5)
        self.json_preview = tk.Text(settings_frame, height=10, width=60)
        self.json_preview.grid(row=4, column=0, padx=5, pady=5)
        self.json_preview.config(state=tk.DISABLED)

        # 数据库替换规则预览
        ttk.Label(settings_frame, text="数据库替换规则:").grid(row=5, column=0, sticky=tk.NW, padx=5, pady=5)
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

    def select_epub(self):
        """选择EPUB文件"""
        path = filedialog.askopenfilename(
            title="选择EPUB文件",
            filetypes=[("EPUB文件", "*.epub")],
            initialdir=os.path.dirname(self.config["last_epub_path"]) if self.config["last_epub_path"] else SCRIPT_DIR
        )
        if path:
            self.epub_var.set(path)
            self.epub_path = path
            self.log(f"已选择EPUB文件: {os.path.basename(path)}")

    def select_cover(self):
        """选择封面图片"""
        path = filedialog.askopenfilename(
            title="选择封面图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.webp")],
            initialdir=os.path.dirname(self.config["last_cover_path"]) if self.config["last_cover_path"] else SCRIPT_DIR
        )
        if path:
            self.cover_var.set(path)
            self.cover_path = path
            self.update_cover_preview()
            self.log(f"已选择封面图片: {os.path.basename(path)}")

    def update_cover_preview(self):
        """更新封面预览"""
        path = self.cover_var.get()
        if path and os.path.exists(path):
            try:
                img = Image.open(path)
                img.thumbnail((300, 450))  # 缩放预览图
                photo = ImageTk.PhotoImage(img)
                self.cover_preview.config(image=photo)
                self.cover_preview.image = photo  # 保持引用
            except Exception as e:
                self.cover_preview.config(text=f"无法预览图片: {str(e)}")
                self.log(f"封面预览错误: {str(e)}")
        else:
            self.cover_preview.config(text="未选择封面图片")

    def load_json_mappings(self):
        """加载JSON替换规则"""
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
        """加载数据库配置"""
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
        """从数据库加载替换规则"""
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
                "last_epub_path": self.epub_var.get(),
                "last_cover_path": self.cover_var.get(),
                "replace_json": self.use_json.get(),
                "replace_db": self.use_db.get()
            }

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.log(f"配置已保存到: {CONFIG_PATH}")
            messagebox.showinfo("成功", "配置保存成功")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def replace_text_content(self, content):
        """替换文本内容"""
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

    def replace_cover(self, temp_dir):
        """替换封面图片"""
        if not self.cover_var.get() or not os.path.exists(self.cover_var.get()):
            self.log("未选择有效的封面图片，跳过封面替换")
            return False

        try:
            # 查找原封面文件
            cover_files = []
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    if "cover" in file.lower() and file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        cover_files.append(os.path.join(root, file))

            if not cover_files:
                self.log("未找到原封面文件，将添加新封面")
                # 在OEBPS目录添加新封面
                oebps_dir = os.path.join(temp_dir, "OEBPS")
                if not os.path.exists(oebps_dir):
                    os.makedirs(oebps_dir)
                cover_dest = os.path.join(oebps_dir, "cover.jpg")
            else:
                cover_dest = cover_files[0]
                self.log(f"找到原封面文件: {os.path.basename(cover_dest)}")

            # 复制新封面
            shutil.copy2(self.cover_var.get(), cover_dest)
            self.log(f"已替换封面图片为: {os.path.basename(self.cover_var.get())}")
            return True
        except Exception as e:
            self.log(f"替换封面失败: {str(e)}")
            return False

    def process_epub(self, epub_path, output_path):
        """处理EPUB文件"""
        total_replacements = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            # 解压EPUB
            self.log("开始解压EPUB文件...")
            with zipfile.ZipFile(epub_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            # 替换封面
            self.replace_cover(temp_dir)

            # 处理文本文件
            self.log("开始替换文本内容...")
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    if file.lower().endswith(('.xhtml', '.html', '.xml', '.opf', '.ncx')):
                        file_path = os.path.join(root, file)
                        try:
                            # 读取文件内容
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()

                            # 替换内容
                            new_content, count = self.replace_text_content(content)
                            if count > 0:
                                total_replacements += count
                                # 写回文件
                                with open(file_path, 'w', encoding='utf-8') as f:
                                    f.write(new_content)
                                self.log(f"处理文件: {file}，替换 {count} 处")
                        except Exception as e:
                            self.log(f"处理文件 {file} 失败: {str(e)}")

            # 重新打包EPUB
            self.log("开始重新打包EPUB文件...")
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
                # 特殊处理mimetype文件（不压缩）
                mimetype_path = os.path.join(temp_dir, "mimetype")
                if os.path.exists(mimetype_path):
                    zip_ref.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)

                # 添加其他文件
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        if file == "mimetype":
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zip_ref.write(file_path, arcname)

        return total_replacements

    def execute_replacement(self):
        """执行替换操作"""
        epub_path = self.epub_var.get()
        if not epub_path or not os.path.exists(epub_path):
            messagebox.showerror("错误", "请选择有效的EPUB文件")
            return

        # 确保替换规则已加载
        if self.use_json.get() and not self.json_replacements:
            self.load_json_mappings()
        if self.use_db.get() and not self.db_replacements:
            self.load_db_replacements()

        # 确认输出路径
        epub_dir = os.path.dirname(epub_path)
        epub_name = os.path.basename(epub_path)
        name, ext = os.path.splitext(epub_name)
        output_path = os.path.join(epub_dir, f"{name}_modified{ext}")

        # 执行处理
        self.log("===== 开始执行替换操作 =====")
        try:
            total = self.process_epub(epub_path, output_path)
            self.log(f"===== 替换完成，共替换 {total} 处内容 =====")
            self.log(f"修改后的文件已保存至: {output_path}")

            # 更新配置
            self.config["last_epub_path"] = epub_path
            self.config["last_cover_path"] = self.cover_var.get()
            self.save_config()

            messagebox.showinfo("成功", f"替换完成，共替换 {total} 处内容\n文件已保存至: {output_path}")
        except Exception as e:
            self.log(f"执行替换失败: {str(e)}")
            messagebox.showerror("错误", f"执行替换失败: {str(e)}")

if __name__ == "__main__":
    # 检查依赖
    try:
        import pymysql
    except ImportError:
        print("请先安装pymysql: pip install pymysql")
        exit(1)

    try:
        from PIL import Image
    except ImportError:
        print("请先安装Pillow: pip install pillow")
        exit(1)

    root = tk.Tk()
    app = EpubReplacerApp(root)
    root.mainloop()
