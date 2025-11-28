import os
import zipfile
import tempfile
import shutil
import random
import logging
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime

# 配置与常量
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "epub_image_in"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"
PROCESS_LOG_FILE.parent.mkdir(exist_ok=True, parents=True)

# 默认配置
DEFAULT_CONFIG = {
    "save_dir": r"D:\book\已处理epub",
    "cover_dir": r"D:\book\封面",
    "retry_count": 3
}

# 加载配置文件
def load_config():
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return DEFAULT_CONFIG
    except Exception as e:
        logging.error(f"加载配置文件失败: {str(e)}")
        return DEFAULT_CONFIG

# 保存配置文件
def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"保存配置文件失败: {str(e)}")
        return False

# 初始化配置
config = load_config()

# ========== 工具函数 ==========
def is_chinese_punctuation(char):
    """判断是否是中文标点结尾"""
    return char in "。！？；：”“’》】）」"

def merge_paragraphs(soup):
    """合并未以标点结束的段落"""
    paragraphs = soup.find_all("p")
    merged_count = 0
    i = 0
    while i < len(paragraphs) - 1:
        text = paragraphs[i].get_text().strip()
        if text and not is_chinese_punctuation(text[-1]):
            next_text = paragraphs[i + 1].get_text().strip()
            paragraphs[i].string = text + " " + next_text
            paragraphs[i + 1].decompose()
            paragraphs = soup.find_all("p")
            merged_count += 1
            continue
        i += 1
    if merged_count > 0:
        logging.info(f"合并了 {merged_count} 个段落。")
    return merged_count

def insert_images_randomly(soup, image_paths):
    """在段落中随机插入图片"""
    paragraphs = soup.find_all("p")
    if not paragraphs:
        return 0

    total_images = len(image_paths)
    paragraph_count = len(paragraphs)
    images_to_insert = max(1, total_images // 15)  # 每个章节大约插入 N 张图片
    images_used = 0

    # 随机选取段落索引
    insert_indices = sorted(random.sample(range(len(paragraphs)), min(images_to_insert, len(paragraphs))))
    for idx in insert_indices:
        img_path = random.choice(image_paths)
        img_tag = soup.new_tag("div")
        img_tag['style'] = "text-align:center;margin:1em 0;"
        img = soup.new_tag("img", alt="插图")
        img["src"] = os.path.basename(img_path)
        img["style"] = "max-width:100%;height:auto;"
        img_tag.append(img)
        paragraphs[idx].insert_after(img_tag)
        images_used += 1
        logging.info(f"在第 {idx+1} 个段落后插入图片：{os.path.basename(img_path)}")

    return images_used

def process_epub(epub_path, images_dir, output_epub_path):
    temp_dir = tempfile.mkdtemp()
    logging.info(f"解压 EPUB 文件：{epub_path}")
    try:
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # 收集所有图片
        image_files = [os.path.join(images_dir, f) for f in os.listdir(images_dir)
                       if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
        random.shuffle(image_files)
        logging.info(f"共加载 {len(image_files)} 张插图资源。")

        if not image_files:
            logging.warning("未找到任何图片文件，请检查图片目录")
            return False

        html_count = 0
        total_inserted = 0

        # 查找或创建 OEBPS 目录
        oebps_dir = os.path.join(temp_dir, "OEBPS")
        os.makedirs(oebps_dir, exist_ok=True)
        logging.info(f"使用 OEBPS 目录：{oebps_dir}")

        # 处理所有 HTML/XHTML 文件
        for root, dirs, files in os.walk(oebps_dir):
            for file in files:
                if file.lower().endswith((".xhtml", ".html")):
                    html_path = os.path.join(root, file)
                    html_count += 1
                    logging.info(f"\n处理文件：{html_path}")

                    try:
                        with open(html_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except UnicodeDecodeError:
                        with open(html_path, "r", encoding="utf-8-sig") as f:
                            content = f.read()

                    soup = BeautifulSoup(content, "lxml")

                    # 段落合并
                    merge_paragraphs(soup)

                    # 随机插入图片
                    inserted = insert_images_randomly(soup, image_files)
                    total_inserted += inserted

                    # 写回文件
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(str(soup))

                    logging.info(f"完成文件：{file}，插入 {inserted} 张图片。")

        # 复制图片到 OEBPS 目录
        for img in image_files:
            img_filename = os.path.basename(img)
            dest_path = os.path.join(oebps_dir, img_filename)
            # 避免文件名冲突
            counter = 1
            while os.path.exists(dest_path):
                base, ext = os.path.splitext(img_filename)
                img_filename = f"{base}_copy{counter}{ext}"
                dest_path = os.path.join(oebps_dir, img_filename)
                counter += 1
            shutil.copy(img, dest_path)
        logging.info(f"已复制 {len(image_files)} 张图片到 EPUB OEBPS 文件夹。")

        # 重新打包 EPUB
        logging.info("开始重新打包 EPUB 文件...")
        with zipfile.ZipFile(output_epub_path, "w", zipfile.ZIP_DEFLATED) as new_zip:
            # mimetype 文件要放最前面且不压缩
            mimetype_path = os.path.join(temp_dir, "mimetype")
            if os.path.exists(mimetype_path):
                new_zip.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            # 打包所有文件
            for foldername, subfolders, filenames in os.walk(temp_dir):
                for filename in filenames:
                    filepath = os.path.join(foldername, filename)
                    arcname = os.path.relpath(filepath, temp_dir)
                    if arcname == "mimetype":
                        continue
                    new_zip.write(filepath, arcname)

        logging.info(f"\n✅ EPUB 随机插图处理完成！输出文件：{output_epub_path}")
        logging.info(f"📄 日志文件已保存：{PROCESS_LOG_FILE}")
        return True

    except Exception as e:
        logging.error(f"处理过程出错: {str(e)}", exc_info=True)
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ========== 界面相关函数 ==========
class EpubImageApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB插图添加工具")
        self.root.geometry("600x400")
        self.root.resizable(True, True)

        self.epub_path = tk.StringVar()
        self.save_dir = tk.StringVar(value=config["save_dir"])
        self.cover_dir = tk.StringVar(value=config["cover_dir"])
        self.retry_count = tk.StringVar(value=str(config["retry_count"]))

        self.setup_ui()
        self.setup_logging()

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

    def setup_ui(self):
        """设置用户界面"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # EPUB文件选择
        ttk.Label(main_frame, text="EPUB文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.epub_path, width=50).grid(row=0, column=1, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self.select_epub).grid(row=0, column=2, padx=5, pady=5)

        # 保存目录选择
        ttk.Label(main_frame, text="保存目录:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.save_dir, width=50).grid(row=1, column=1, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self.select_save_dir).grid(row=1, column=2, padx=5, pady=5)

        # 封面目录选择
        ttk.Label(main_frame, text="封面目录:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.cover_dir, width=50).grid(row=2, column=1, pady=5)
        ttk.Button(main_frame, text="浏览...", command=self.select_cover_dir).grid(row=2, column=2, padx=5, pady=5)

        # 重试次数设置
        ttk.Label(main_frame, text="下载重试次数:").grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.retry_count, width=10).grid(row=3, column=1, sticky=tk.W, pady=5)

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=3, pady=20)

        ttk.Button(button_frame, text="保存配置", command=self.save_current_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="开始处理", command=self.start_processing).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="查看日志", command=self.view_log).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="退出", command=self.root.quit).pack(side=tk.LEFT, padx=10)

        # 日志显示区域
        ttk.Label(main_frame, text="处理日志:").grid(row=5, column=0, sticky=tk.W, pady=5)
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=6, column=0, columnspan=3, sticky=tk.NSEW, pady=5)

        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(log_frame, height=10, width=70, yscrollcommand=scrollbar.set, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)

        # 配置网格权重，使控件可拉伸
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(6, weight=1)

        # 重定向日志到文本框
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

    def select_epub(self):
        """选择EPUB文件"""
        file_path = filedialog.askopenfilename(
            title="选择EPUB文件",
            filetypes=[("EPUB文件", "*.epub"), ("所有文件", "*.*")]
        )
        if file_path:
            self.epub_path.set(file_path)

    def select_save_dir(self):
        """选择保存目录"""
        dir_path = filedialog.askdirectory(title="选择保存目录")
        if dir_path:
            self.save_dir.set(dir_path)

    def select_cover_dir(self):
        """选择封面目录"""
        dir_path = filedialog.askdirectory(title="选择封面目录")
        if dir_path:
            self.cover_dir.set(dir_path)

    def save_current_config(self):
        """保存当前配置"""
        try:
            new_config = {
                "save_dir": self.save_dir.get(),
                "cover_dir": self.cover_dir.get(),
                "retry_count": int(self.retry_count.get())
            }
            if save_config(new_config):
                messagebox.showinfo("成功", "配置已保存")
                global config
                config = new_config
            else:
                messagebox.showerror("错误", "配置保存失败")
        except ValueError:
            messagebox.showerror("错误", "重试次数必须是数字")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置时出错: {str(e)}")

    def view_log(self):
        """查看日志文件"""
        try:
            if os.path.exists(PROCESS_LOG_FILE):
                os.startfile(PROCESS_LOG_FILE)
            else:
                messagebox.showinfo("提示", "日志文件不存在")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开日志文件: {str(e)}")

    def start_processing(self):
        """开始处理EPUB文件"""
        epub_path = self.epub_path.get()
        save_dir = self.save_dir.get()
        cover_dir = self.cover_dir.get()

        # 验证输入
        if not epub_path or not os.path.exists(epub_path):
            messagebox.showerror("错误", "请选择有效的EPUB文件")
            return

        if not save_dir or not os.path.exists(save_dir):
            messagebox.showerror("错误", "请选择有效的保存目录")
            return

        if not cover_dir or not os.path.exists(cover_dir):
            messagebox.showerror("错误", "请选择有效的封面目录")
            return

        try:
            retry_count = int(self.retry_count.get())
            if retry_count < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "重试次数必须是非负整数")
            return

        # 准备输出路径
        output_filename = os.path.basename(epub_path)
        output_path = os.path.join(save_dir, output_filename)

        # 检查输出文件是否已存在
        if os.path.exists(output_path):
            if not messagebox.askyesno("确认", "输出文件已存在，是否覆盖？"):
                return

        # 开始处理
        logging.info("="*50)
        logging.info(f"开始处理EPUB: {epub_path}")
        self.root.update()  # 更新UI显示

        success = process_epub(epub_path, cover_dir, output_path)

        if success:
            messagebox.showinfo("成功", f"处理完成！\n文件已保存至: {output_path}")
        else:
            messagebox.showerror("失败", "处理过程中出现错误，请查看日志获取详细信息")

# ========== 主程序 ==========
if __name__ == "__main__":
    root = tk.Tk()
    app = EpubImageApp(root)
    root.mainloop()
