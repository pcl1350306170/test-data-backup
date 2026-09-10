import os
import zipfile
import tempfile
import shutil
import logging
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime

# 配置与常量
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "epub_splitter"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)


# ──────────── 公共日志模块（可选依赖）────────────
import sys
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger, get_log_file
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
    def get_log_file(name=None):
        return Path()
# ────────────────────────────────────────────────
# 默认配置
DEFAULT_CONFIG = {
    "last_input_dir": "",
    "last_output_dir": "",
    "split_count": 3,
    "split_by_size": True,  # ✅ 新增：按文件大小拆分（而非HTML数量）
    "target_size_mb": 50  # ✅ 新增：每个部分的目标大小（MB）
}

# 加载配置文件
def load_config():
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")
        return DEFAULT_CONFIG

# 保存配置文件
def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")
        return False

# 初始化配置
config = load_config()

# ========== 工具函数 ==========
def extract_epub_structure(epub_path, temp_dir):
    """解压EPUB并分析结构"""
    # 验证文件路径
    if not os.path.exists(epub_path):
        raise FileNotFoundError(f"EPUB文件不存在: {epub_path}")
    
    if os.path.isdir(epub_path):
        raise IsADirectoryError(f"请选择EPUB文件，而不是目录: {epub_path}")
    
    if not epub_path.lower().endswith('.epub'):
        logger.warning(f"警告：文件可能不是EPUB格式: {epub_path}")
    
    logger.info(f"解压 EPUB 文件：{epub_path}")
    try:
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
    except zipfile.BadZipFile:
        raise ValueError(f"文件不是有效的ZIP/EPUB格式: {epub_path}")
    except PermissionError:
        raise PermissionError(f"无法访问文件，请检查文件是否被占用或权限不足: {epub_path}")
    
    # 查找 OEBPS 目录
    oebps_dir = None
    for root, dirs, files in os.walk(temp_dir):
        if "OEBPS" in dirs or any(f.lower().endswith(('.xhtml', '.html')) for f in files):
            oebps_dir = root
            break
    
    if not oebps_dir:
        oebps_dir = temp_dir
    
    logger.info(f"找到内容目录：{oebps_dir}")
    return oebps_dir

def get_html_files_with_size(oebps_dir):
    """获取所有HTML/XHTML文件及其关联的图片大小"""
    html_files = []
    
    for root, dirs, files in os.walk(oebps_dir):
        for file in sorted(files):  # 排序确保顺序一致
            if file.lower().endswith(('.xhtml', '.html')):
                html_path = os.path.join(root, file)
                
                # 读取HTML文件，查找引用的图片
                try:
                    with open(html_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    soup = BeautifulSoup(content, 'lxml')
                    img_tags = soup.find_all('img')
                    
                    # 计算该HTML引用的图片总大小
                    total_img_size = 0
                    for img in img_tags:
                        src = img.get('src', '')
                        if src:
                            # 解析图片路径
                            img_path = os.path.join(os.path.dirname(html_path), src)
                            img_path = os.path.normpath(img_path)
                            if os.path.exists(img_path):
                                total_img_size += os.path.getsize(img_path)
                    
                    html_size = os.path.getsize(html_path) + total_img_size
                    html_files.append({
                        'path': html_path,
                        'size': html_size,
                        'img_count': len(img_tags)
                    })
                    
                except Exception as e:
                    logger.warning(f"处理HTML文件失败 {file}: {e}")
                    # 如果解析失败，只计算HTML文件大小
                    html_files.append({
                        'path': html_path,
                        'size': os.path.getsize(html_path),
                        'img_count': 0
                    })
    
    logger.info(f"找到 {len(html_files)} 个 HTML 文件")
    return html_files

def split_html_files_by_count(html_files, split_count):
    """将HTML文件列表平均分成指定数量的组（按文件数量）"""
    total = len(html_files)
    if total <= split_count:
        # 如果文件数少于拆分数，每个文件一组
        return [[f] for f in html_files] + [[] for _ in range(split_count - total)]
    
    # 计算每组应该有多少文件
    base_size = total // split_count
    remainder = total % split_count
    
    groups = []
    start = 0
    for i in range(split_count):
        # 前 remainder 组多一个文件
        size = base_size + (1 if i < remainder else 0)
        end = start + size
        groups.append(html_files[start:end])
        start = end
    
    return groups

def split_html_files_by_size(html_files, target_size_bytes):
    """按目标大小拆分HTML文件（适合漫画EPUB）"""
    if not html_files:
        return []
    
    groups = []
    current_group = []
    current_size = 0
    
    for html_info in html_files:
        file_size = html_info['size']
        
        # 如果当前组已有文件且添加此文件会超过目标大小，则开始新组
        if current_group and current_size + file_size > target_size_bytes:
            groups.append(current_group)
            current_group = [html_info]
            current_size = file_size
        else:
            current_group.append(html_info)
            current_size += file_size
    
    # 添加最后一组
    if current_group:
        groups.append(current_group)
    
    logger.info(f"按大小拆分：目标 {target_size_bytes/1024/1024:.1f}MB/组，共 {len(groups)} 组")
    return groups

def create_split_epub(original_epub_path, temp_dir, oebps_dir, html_group, output_path, index, total_groups):
    """创建拆分后的EPUB文件"""
    logger.info(f"\n创建第 {index + 1} 部分...")
    
    # 生成输出文件名：原文件名_序号.epub
    original_name = os.path.splitext(os.path.basename(original_epub_path))[0]
    output_filename = f"{original_name}_{index + 1}.epub"
    output_path = os.path.join(output_path, output_filename)
    
    logger.info(f"输出文件：{output_filename}")
    
    # 创建临时目录用于构建新的EPUB
    new_epub_temp = tempfile.mkdtemp()
    
    try:
        # 复制 mimetype 文件
        mimetype_src = os.path.join(temp_dir, "mimetype")
        mimetype_dst = os.path.join(new_epub_temp, "mimetype")
        if os.path.exists(mimetype_src):
            shutil.copy2(mimetype_src, mimetype_dst)
            logger.info("已复制 mimetype 文件")
        
        # 复制 META-INF 目录（包含 container.xml）
        meta_inf_src = os.path.join(temp_dir, "META-INF")
        meta_inf_dst = os.path.join(new_epub_temp, "META-INF")
        if os.path.exists(meta_inf_src):
            shutil.copytree(meta_inf_src, meta_inf_dst)
            logger.info("已复制 META-INF 目录")
        
        # 创建 OEBPS 目录
        new_oebps = os.path.join(new_epub_temp, "OEBPS")
        os.makedirs(new_oebps, exist_ok=True)
        
        # 收集本组HTML引用的所有图片
        referenced_images = set()
        for html_info in html_group:
            html_file = html_info['path']
            try:
                with open(html_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                soup = BeautifulSoup(content, 'lxml')
                img_tags = soup.find_all('img')
                for img in img_tags:
                    src = img.get('src', '')
                    if src:
                        # 解析图片路径
                        img_path = os.path.join(os.path.dirname(html_file), src)
                        img_path = os.path.normpath(img_path)
                        if os.path.exists(img_path):
                            referenced_images.add(img_path)
            except Exception as e:
                logger.warning(f"解析HTML图片引用失败: {e}")
        
        logger.info(f"本组HTML共引用 {len(referenced_images)} 张图片")
        
        # 复制选中的HTML文件
        total_imgs_in_group = 0
        for html_info in html_group:
            html_file = html_info['path']
            rel_path = os.path.relpath(html_file, oebps_dir)
            dest_path = os.path.join(new_oebps, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(html_file, dest_path)
            total_imgs_in_group += html_info['img_count']
            logger.info(f"  复制HTML: {rel_path} ({html_info['img_count']}张图片)")
        
        # 只复制本组HTML引用的图片、CSS等资源文件
        resource_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.css', '.svg', '.ttf', '.otf')
        resource_count = 0
        for img_path in referenced_images:
            rel_path = os.path.relpath(img_path, oebps_dir)
            dest_path = os.path.join(new_oebps, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            if not os.path.exists(dest_path):  # 避免重复复制
                shutil.copy2(img_path, dest_path)
                resource_count += 1
        
        # 也复制CSS等非图片资源（遍历查找）
        for root, dirs, files in os.walk(oebps_dir):
            for file in files:
                if file.lower().endswith(('.css', '.svg', '.ttf', '.otf')):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, oebps_dir)
                    dest_path = os.path.join(new_oebps, rel_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    if not os.path.exists(dest_path):
                        shutil.copy2(full_path, dest_path)
                        resource_count += 1
        
        logger.info(f"已复制 {resource_count} 个资源文件，本部分共 {total_imgs_in_group} 张图片")
        
        # 重新打包EPUB
        logger.info("开始打包EPUB...")
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as new_zip:
            # mimetype 文件要放最前面且不压缩
            if os.path.exists(mimetype_dst):
                new_zip.write(mimetype_dst, "mimetype", compress_type=zipfile.ZIP_STORED)
            
            # 打包所有文件
            for foldername, subfolders, filenames in os.walk(new_epub_temp):
                for filename in filenames:
                    filepath = os.path.join(foldername, filename)
                    arcname = os.path.relpath(filepath, new_epub_temp)
                    if arcname == "mimetype":
                        continue
                    new_zip.write(filepath, arcname)
        
        logger.info(f"✅ 第 {index + 1} 部分创建完成：{output_filename}")
        return True
        
    except Exception as e:
        logger.error(f"创建第 {index + 1} 部分失败: {str(e)}", exc_info=True)
        return False
    finally:
        shutil.rmtree(new_epub_temp, ignore_errors=True)

def split_epub(epub_path, split_count, output_dir, progress_callback=None, split_by_size=True, target_size_mb=50):
    """主拆分函数"""
    temp_dir = tempfile.mkdtemp()
    logger.info(f"="*60)
    logger.info(f"开始拆分 EPUB: {os.path.basename(epub_path)}")
    logger.info(f"拆分模式: {'按文件大小' if split_by_size else '按HTML数量'}")
    if split_by_size:
        logger.info(f"目标大小: {target_size_mb}MB/部分")
    else:
        logger.info(f"拆分为 {split_count} 部分")
    logger.info(f"输出目录: {output_dir}")
    
    try:
        # 步骤1：解压并分析结构
        oebps_dir = extract_epub_structure(epub_path, temp_dir)
        
        # 步骤2：获取HTML文件列表（带大小信息）
        html_files_info = get_html_files_with_size(oebps_dir)
        
        if not html_files_info:
            logger.error("未找到任何HTML文件，无法拆分")
            return False
        
        # 计算总大小
        total_size = sum(h['size'] for h in html_files_info)
        total_imgs = sum(h['img_count'] for h in html_files_info)
        logger.info(f"总大小: {total_size/1024/1024:.1f}MB, 总图片数: {total_imgs}")
        
        # 步骤3：分组
        if split_by_size:
            # 按目标大小拆分
            target_size_bytes = target_size_mb * 1024 * 1024
            groups = split_html_files_by_size(html_files_info, target_size_bytes)
        else:
            # 按文件数量拆分
            html_paths = [h['path'] for h in html_files_info]
            path_groups = split_html_files_by_count(html_paths, split_count)
            # 转换回带信息的格式
            groups = []
            for path_group in path_groups:
                info_group = [h for h in html_files_info if h['path'] in path_group]
                groups.append(info_group)
        
        non_empty_groups = [g for g in groups if g]
        logger.info(f"将 {len(html_files_info)} 个HTML文件分为 {len(non_empty_groups)} 组")
        
        # 步骤4：创建拆分后的EPUB
        success_count = 0
        total_groups = len(non_empty_groups)
        
        for i, group in enumerate(groups):
            if not group:  # 跳过空组
                continue
            
            # 计算本组大小
            group_size = sum(h['size'] for h in group)
            group_imgs = sum(h['img_count'] for h in group)
            logger.info(f"\n处理进度: {i + 1}/{total_groups} (大小: {group_size/1024/1024:.1f}MB, 图片: {group_imgs}张)")
            
            # 更新进度回调
            if progress_callback:
                progress_callback(i + 1, total_groups)
            
            success = create_split_epub(
                epub_path, temp_dir, oebps_dir, group, 
                output_dir, i, total_groups
            )
            if success:
                success_count += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"✅ 拆分完成！成功创建 {success_count} 个文件")
        logger.info(f"📁 输出目录: {output_dir}")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"拆分过程出错: {str(e)}", exc_info=True)
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ========== 界面相关函数 ==========
class EpubSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB文件拆分工具")
        self.root.geometry("700x550")
        self.root.resizable(True, True)

        self.epub_path = tk.StringVar(value=config.get("last_input_dir", ""))
        self.output_dir = tk.StringVar(value=config.get("last_output_dir", ""))
        self.split_count = tk.StringVar(value=str(config.get("split_count", 3)))
        self.split_by_size = tk.BooleanVar(value=config.get("split_by_size", True))
        self.target_size_mb = tk.StringVar(value=str(config.get("target_size_mb", 50)))
        
        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="就绪")

        self.setup_ui()
        self.setup_logging()

    def setup_logging(self):
        """配置日志系统"""
        # 清除之前的handlers
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        

    def setup_ui(self):
        """设置用户界面"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # EPUB文件选择
        file_frame = ttk.LabelFrame(main_frame, text="📄 文件选择", padding="10")
        file_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(file_frame, text="EPUB文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(file_frame, textvariable=self.epub_path, width=50).grid(row=0, column=1, pady=5, padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.select_epub).grid(row=0, column=2, padx=5, pady=5)

        # 输出目录选择
        ttk.Label(file_frame, text="输出目录:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(file_frame, textvariable=self.output_dir, width=50).grid(row=1, column=1, pady=5, padx=5)
        ttk.Button(file_frame, text="浏览...", command=self.select_output_dir).grid(row=1, column=2, padx=5, pady=5)

        # 拆分设置
        settings_frame = ttk.LabelFrame(main_frame, text="⚙️ 拆分设置", padding="10")
        settings_frame.pack(fill=tk.X, pady=5)
        
        # 拆分模式选择
        mode_frame = ttk.Frame(settings_frame)
        mode_frame.grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        ttk.Label(mode_frame, text="拆分模式:").pack(side=tk.LEFT)
        ttk.Radiobutton(mode_frame, text="按文件大小（推荐漫画）", variable=self.split_by_size, 
                       value=True).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="按HTML数量", variable=self.split_by_size, 
                       value=False).pack(side=tk.LEFT, padx=10)
        
        # 动态显示参数
        param_frame = ttk.Frame(settings_frame)
        param_frame.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        ttk.Label(param_frame, text="目标大小(MB):").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.target_size_entry = ttk.Entry(param_frame, textvariable=self.target_size_mb, width=10)
        self.target_size_entry.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Label(param_frame, text="拆分数:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        self.split_count_entry = ttk.Entry(param_frame, textvariable=self.split_count, width=10)
        self.split_count_entry.grid(row=0, column=3, sticky=tk.W, padx=5)
        
        # 根据模式显示/隐藏控件
        def update_visibility(*args):
            if self.split_by_size.get():
                self.target_size_entry.config(state=tk.NORMAL)
                self.split_count_entry.config(state=tk.DISABLED)
            else:
                self.target_size_entry.config(state=tk.DISABLED)
                self.split_count_entry.config(state=tk.NORMAL)
        
        self.split_by_size.trace_add("write", update_visibility)
        update_visibility()  # 初始化
        
        # 文件名说明
        ttk.Label(settings_frame, text="📝 命名规则: 原文件名_序号.epub (如: book_1.epub, book_2.epub)", 
                 foreground="gray").grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=5)

        # 进度条
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(progress_frame, text="进度:").pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ttk.Label(progress_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=5)

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="💾 保存配置", command=self.save_current_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="🚀 开始拆分", command=self.start_splitting).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="📝 查看日志", command=self.view_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="❌ 退出", command=self.root.quit).pack(side=tk.RIGHT, padx=5)

        # 日志显示区域
        log_frame = ttk.LabelFrame(main_frame, text="📋 处理日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text = tk.Text(log_frame, height=12, yscrollcommand=scrollbar.set, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)

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
        initial_dir = config.get("last_input_dir", "")
        file_path = filedialog.askopenfilename(
            title="选择EPUB文件",
            filetypes=[("EPUB文件", "*.epub"), ("所有文件", "*.*")],
            initialdir=initial_dir if initial_dir else ""
        )
        if file_path:
            self.epub_path.set(file_path)
            # 自动设置输出目录为输入文件所在目录
            if not self.output_dir.get():
                self.output_dir.set(os.path.dirname(file_path))

    def select_output_dir(self):
        """选择输出目录"""
        initial_dir = config.get("last_output_dir", "")
        dir_path = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=initial_dir if initial_dir else ""
        )
        if dir_path:
            self.output_dir.set(dir_path)

    def save_current_config(self):
        """保存当前配置"""
        try:
            new_config = {
                "last_input_dir": os.path.dirname(self.epub_path.get()) if self.epub_path.get() else "",
                "last_output_dir": self.output_dir.get(),
                "split_count": int(self.split_count.get()),
                "split_by_size": self.split_by_size.get(),
                "target_size_mb": int(self.target_size_mb.get())
            }
            if save_config(new_config):
                global config
                config = new_config
                messagebox.showinfo("成功", "配置已保存")
            else:
                messagebox.showerror("错误", "配置保存失败")
        except ValueError:
            messagebox.showerror("错误", "数值必须是整数")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置时出错: {str(e)}")

    def view_log(self):
        """查看日志文件"""
        try:
            log_path = get_log_file(SCRIPT_NAME)
            if os.path.exists(log_path):
                os.startfile(log_path)
            else:
                messagebox.showinfo("提示", "日志文件不存在")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开日志文件: {str(e)}")

    def update_progress(self, current, total):
        """更新进度条"""
        if total > 0:
            percentage = (current / total) * 100
            self.progress_var.set(percentage)
            self.status_var.set(f"{current}/{total}")
            self.root.update_idletasks()

    def start_splitting(self):
        """开始拆分EPUB文件"""
        epub_path = self.epub_path.get()
        output_dir = self.output_dir.get()
        
        # 验证输入
        if not epub_path:
            messagebox.showerror("错误", "请选择EPUB文件")
            return
        
        if not os.path.exists(epub_path):
            messagebox.showerror("错误", f"文件不存在: {epub_path}")
            return
        
        if os.path.isdir(epub_path):
            messagebox.showerror("错误", f"请选择EPUB文件，而不是目录:\n{epub_path}")
            return
        
        if not epub_path.lower().endswith('.epub'):
            if not messagebox.askyesno("警告", 
                f"文件可能不是EPUB格式:\n{epub_path}\n\n是否继续？"):
                return

        if not output_dir or not os.path.exists(output_dir):
            messagebox.showerror("错误", "请选择有效的输出目录")
            return

        try:
            split_count = int(self.split_count.get())
            if split_count < 2:
                raise ValueError("拆分数量必须大于等于2")
        except ValueError as e:
            messagebox.showerror("错误", f"拆分数量无效: {str(e)}")
            return

        split_by_size = self.split_by_size.get()
        target_size_mb = 50  # 默认值
        
        if split_by_size:
            try:
                target_size_mb = int(self.target_size_mb.get())
                if target_size_mb < 10:
                    raise ValueError("目标大小必须大于等于10MB")
            except ValueError as e:
                messagebox.showerror("错误", f"目标大小无效: {str(e)}")
                return
        else:
            try:
                split_count = int(self.split_count.get())
                if split_count < 2:
                    raise ValueError("拆分数量必须大于等于2")
            except ValueError as e:
                messagebox.showerror("错误", f"拆分数量无效: {str(e)}")
                return

        # 确认对话框
        confirm_msg = f"即将拆分EPUB文件\n\n"
        confirm_msg += f"源文件: {os.path.basename(epub_path)}\n"
        if split_by_size:
            confirm_msg += f"拆分模式: 按文件大小 ({target_size_mb}MB/部分)\n"
        else:
            confirm_msg += f"拆分模式: 按HTML数量 ({split_count}个部分)\n"
        confirm_msg += f"输出目录: {output_dir}\n\n"
        confirm_msg += "是否继续？"
        
        if not messagebox.askyesno("确认拆分", confirm_msg):
            logger.info("用户取消了拆分操作")
            return

        # 重置进度
        self.progress_var.set(0)
        self.status_var.set("准备中...")
        self.root.update_idletasks()

        # 清空日志
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)

        logger.info("="*60)
        logger.info(f"开始拆分任务")
        
        # 执行拆分
        def progress_callback(current, total):
            self.update_progress(current, total)
        
        success = split_epub(
            epub_path, split_count, output_dir, 
            progress_callback=progress_callback,
            split_by_size=split_by_size,
            target_size_mb=target_size_mb
        )

        if success:
            self.progress_var.set(100)
            self.status_var.set("完成")
            messagebox.showinfo("成功", f"拆分完成！\n文件已保存至: {output_dir}")
        else:
            self.status_var.set("失败")
            messagebox.showerror("失败", "拆分过程中出现错误，请查看日志获取详细信息")

# ========== 主程序 ==========
if __name__ == "__main__":
    root = tk.Tk()
    app = EpubSplitterApp(root)
    root.mainloop()
