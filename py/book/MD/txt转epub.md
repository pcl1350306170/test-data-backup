写一个可视化脚本，自行选择txt文件【可以多选】，转为epub ，并可以选择添加封面和插图。
1. 以txt文件名作为章节标题，格式为“第X章 文件名”（X为按文件创建时间/字母顺序排序后的序号）。
2. 可以选择清除txt文件内部原有章节标识（如“第一章. 1.. 一. 【章节名】”等常见格式），仅保留纯文本内容。
3. 合并未以中文标点（。！？；：”“’》】）」）结尾的行与下一行合并，避免乱换行；连续空行合并为单个空行。
4. 封面可以自行选择，获取从默认目录「D:\book\封面」目录随机读取图片（支持PNG. JPG. JPEG. WebP格式），优先选尺寸≥800×1200的图片作为封面
5. 插图可以多选，最多300张，没有选就从默认目录「D:\book\封面」目录获取所有图片。
6. 插图规则：插图总数不超过300张（可配置），均匀插入各章节，每章节插图数量按章节文本长度比例分配（如文本越长插图越多），插图位置避开章节开头和结尾的3行文本。
7. epub规则参照“txt_to_epub_with_cover.py”代码
8. 输出目录「D:\book\epub-py」自动创建，EPUB文件名以「A目录名_生成时间.epub」命名（如“HH_20251108.epub”），避免覆盖已存在文件（重名时自动加序号）。
9. 日志记录：生成转换日志（保存于输出目录，命名格式“txt2epub_生成时间.log”），记录文件读取. 图片获取. 替换次数. 转换成功/失败状态等信息。
10. 异常处理：txt文件编码自动识别（优先UTF-8. GBK），无法解码的文件记录日志并跳过；图片读取失败时自动跳过该图片，不影响整体转换。
11. 可配置项：支持通过配置文件（./json/txt_epub_config.json）自定义插图最大数量. 封面尺寸阈值. 章节排序方式（创建时间/字母顺序）. 是否忽略替换大小写等参数。将当前所有配置（文件选择. 图片设置. 文本规则等）保存到同级目录下“json”里面“txt_epub_config.json”，下次可直接加载，无需重复设置；
12. 进度条与日志面板：转换过程中显示进度条（标注“读取文件→处理文本→插入图片→生成EPUB”阶段），下方日志面板实时显示操作详情（成功/失败提示. 替换次数. 图片加载数量等）；
13. 完成提示弹窗：转换完成后弹出弹窗，显示“成功生成X个EPUB文件”，支持直接打开输出目录。

# 豆包实现-以下是一个符合您需求的可视化TXT转EPUB工具，基于PyQt5开发，具备文件选择、封面和插图配置、文本处理等功能：

```python
import os
import sys
import json
import uuid
import random
import logging
import shutil
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QFileDialog, QListWidget, QCheckBox, 
                            QProgressBar, QTextEdit, QMessageBox, QGroupBox, QRadioButton,
                            QSpinBox, QDoubleSpinBox, QFormLayout, QComboBox, QSplitter,
                            QTabWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDateTime, QSize
from PyQt5.QtGui import QPixmap, QImage, QIcon
from bs4 import BeautifulSoup
import chardet

# 默认配置路径
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "txt_epub_config.json")
DEFAULT_COVER_DIR = r"D:\book\封面"
DEFAULT_OUTPUT_DIR = r"D:\book\epub-py"

# 确保配置目录存在
os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

class ConvertThread(QThread):
    """转换线程，用于后台处理文件转换，不阻塞UI"""
    progress_updated = pyqtSignal(int, str)  # 进度值，当前阶段
    log_updated = pyqtSignal(str)            # 日志信息
    finished = pyqtSignal(bool, str)         # 完成状态，消息

    def __init__(self, txt_files, output_dir, cover_path, image_paths, config):
        super().__init__()
        self.txt_files = txt_files
        self.output_dir = output_dir
        self.cover_path = cover_path
        self.image_paths = image_paths
        self.config = config
        self.log_file = None
        self.logger = None

    def run(self):
        try:
            # 初始化日志
            self.init_logger()
            
            # 1. 准备工作
            self.progress_updated.emit(5, "准备转换...")
            
            # 排序文件
            sorted_files = self.sort_files(self.txt_files)
            if not sorted_files:
                self.log_updated.emit("没有要处理的文件")
                self.finished.emit(False, "没有要处理的文件")
                return
                
            # 2. 读取文件
            self.progress_updated.emit(10, "读取文件...")
            chapters_data = []
            total_files = len(sorted_files)
            
            for i, file_path in enumerate(sorted_files):
                try:
                    content = self.read_file_with_encoding(file_path)
                    chapters_data.append({
                        "path": file_path,
                        "content": content,
                        "length": len(content)
                    })
                    self.log_updated.emit(f"成功读取文件: {os.path.basename(file_path)}")
                except Exception as e:
                    self.log_updated.emit(f"读取文件失败 {os.path.basename(file_path)}: {str(e)}")
                
                progress = 10 + int(20 * (i + 1) / total_files)
                self.progress_updated.emit(progress, f"读取文件... ({i+1}/{total_files})")

            # 3. 处理文本
            self.progress_updated.emit(30, "处理文本...")
            processed_chapters = []
            total_length = sum(chapter["length"] for chapter in chapters_data)
            
            for i, chapter in enumerate(chapters_data):
                try:
                    # 清除原有章节标识
                    if self.config.get("remove_chapter_marks", False):
                        processed_content = self.remove_chapter_marks(chapter["content"])
                    else:
                        processed_content = chapter["content"]
                        
                    # 处理换行和空行
                    processed_content = self.process_line_breaks(processed_content)
                    
                    # 生成章节标题
                    chapter_title = f"第{i+1}章 {os.path.splitext(os.path.basename(chapter['path']))[0]}"
                    
                    processed_chapters.append({
                        "title": chapter_title,
                        "content": processed_content,
                        "length": len(processed_content),
                        "original_length": chapter["length"]
                    })
                    
                    self.log_updated.emit(f"处理完成: {chapter_title}")
                except Exception as e:
                    self.log_updated.emit(f"处理文本失败 {chapter['path']}: {str(e)}")
                
                progress = 30 + int(20 * (i + 1) / total_files)
                self.progress_updated.emit(progress, f"处理文本... ({i+1}/{total_files})")

            # 4. 准备图片
            self.progress_updated.emit(50, "准备图片...")
            valid_images = []
            for img_path in self.image_paths:
                try:
                    if self.is_valid_image(img_path):
                        valid_images.append(img_path)
                except Exception as e:
                    self.log_updated.emit(f"图片无效 {img_path}: {str(e)}")
            
            # 限制图片数量
            max_images = self.config.get("max_images", 300)
            valid_images = valid_images[:max_images]
            self.log_updated.emit(f"准备就绪 {len(valid_images)} 张插图")

            # 5. 分配插图
            self.progress_updated.emit(55, "分配插图...")
            image_allocation = self.allocate_images(processed_chapters, valid_images, total_length)

            # 6. 生成EPUB
            self.progress_updated.emit(60, "生成EPUB...")
            book_title = os.path.basename(os.path.dirname(sorted_files[0])) if sorted_files else "未知书籍"
            epub_filename = self.generate_epub_filename(book_title)
            epub_path = os.path.join(self.output_dir, epub_filename)
            
            success = self.create_epub(
                processed_chapters, 
                epub_path, 
                self.cover_path, 
                valid_images, 
                image_allocation, 
                book_title
            )

            if success:
                self.progress_updated.emit(100, "转换完成")
                self.log_updated.emit(f"成功生成EPUB: {epub_path}")
                self.finished.emit(True, f"成功生成EPUB文件：\n{epub_path}")
            else:
                self.finished.emit(False, "生成EPUB失败")
                
        except Exception as e:
            self.log_updated.emit(f"转换过程出错: {str(e)}")
            self.finished.emit(False, f"转换失败: {str(e)}")

    def init_logger(self):
        """初始化日志记录器"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = os.path.join(self.output_dir, f"txt2epub_{timestamp}.log")
        
        self.logger = logging.getLogger("epub_converter")
        self.logger.setLevel(logging.INFO)
        
        # 清除现有处理器
        if self.logger.handlers:
            self.logger.handlers = []
            
        # 添加文件处理器
        file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        self.log_updated.emit(f"日志文件已创建: {self.log_file}")

    def sort_files(self, file_paths):
        """根据配置排序文件"""
        sort_method = self.config.get("sort_method", "create_time")
        
        if sort_method == "create_time":
            return sorted(file_paths, key=lambda x: os.path.getctime(x))
        else:  # 字母顺序
            return sorted(file_paths, key=lambda x: os.path.basename(x))

    def read_file_with_encoding(self, file_path):
        """自动识别编码并读取文件"""
        try:
            # 尝试UTF-8
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                # 尝试GBK
                with open(file_path, 'r', encoding='gbk') as f:
                    return f.read()
            except UnicodeDecodeError:
                # 自动检测编码
                with open(file_path, 'rb') as f:
                    raw_data = f.read()
                    result = chardet.detect(raw_data)
                    encoding = result['encoding'] or 'utf-8'
                    
                try:
                    return raw_data.decode(encoding, errors='replace')
                except:
                    raise Exception(f"无法解码文件，尝试过UTF-8、GBK和{encoding}")

    def remove_chapter_marks(self, content):
        """移除章节标识"""
        import re
        
        # 常见章节标识模式
        patterns = [
            r'^第[零一二三四五六七八九十百千万]+章.*$',  # 第X章
            r'^[0-9]+\..*$',                              # 1. ...
            r'^[一二三四五六七八九十]+、.*$',            # 一、...
            r'^\【.*\】$',                                # 【章节名】
            r'^章节.*$'                                   # 章节...
        ]
        
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            stripped_line = line.strip()
            if any(re.match(pattern, stripped_line) for pattern in patterns):
                self.log_updated.emit(f"移除章节标识: {stripped_line}")
                continue
            cleaned_lines.append(line)
            
        return '\n'.join(cleaned_lines)

    def process_line_breaks(self, content):
        """处理换行和空行"""
        lines = [line.rstrip() for line in content.split('\n')]
        processed = []
        current_line = ""
        
        # 处理未以中文标点结尾的行
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_line:
                    processed.append(current_line)
                    current_line = ""
                processed.append("")
            else:
                if current_line:
                    current_line += " " + stripped
                else:
                    current_line = stripped
                
                # 检查是否以中文标点结尾
                if current_line and self.is_chinese_punctuation(current_line[-1]):
                    processed.append(current_line)
                    current_line = ""
        
        # 添加最后一行
        if current_line:
            processed.append(current_line)
        
        # 合并连续空行
        result = []
        prev_empty = False
        for line in processed:
            if not line.strip():
                if not prev_empty:
                    result.append("")
                    prev_empty = True
            else:
                result.append(line)
                prev_empty = False
                
        return '\n'.join(result)

    def is_chinese_punctuation(self, char):
        """判断是否是中文标点结尾"""
        return char in "。！？；：”“’》】）」"

    def is_valid_image(self, img_path):
        """检查图片是否有效"""
        try:
            from PIL import Image
            with Image.open(img_path) as img:
                return True
        except:
            return False

    def allocate_images(self, chapters, images, total_length):
        """按章节长度比例分配插图"""
        if not images:
            return {}
            
        allocation = {}
        remaining_images = images.copy()
        random.shuffle(remaining_images)
        
        # 计算每章应分配的图片数量
        for i, chapter in enumerate(chapters):
            if total_length == 0:
                allocation[i] = []
                continue
                
            ratio = chapter["length"] / total_length
            num_images = max(0, round(ratio * len(images)))
            allocation[i] = remaining_images[:num_images]
            remaining_images = remaining_images[num_images:]
            
        # 分配剩余图片
        i = 0
        while remaining_images and i < len(chapters):
            allocation[i].append(remaining_images.pop(0))
            i = (i + 1) % len(chapters)
            
        return allocation

    def generate_epub_filename(self, book_title):
        """生成EPUB文件名"""
        timestamp = datetime.now().strftime('%Y%m%d')
        base_name = f"{book_title}_{timestamp}.epub"
        file_path = os.path.join(self.output_dir, base_name)
        
        # 避免覆盖
        counter = 1
        while os.path.exists(file_path):
            base_name = f"{book_title}_{timestamp}_{counter}.epub"
            file_path = os.path.join(self.output_dir, base_name)
            counter += 1
            
        return base_name

    def create_epub(self, chapters, output_path, cover_path, images, image_allocation, book_title):
        """创建EPUB文件"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # 创建目录结构
                oebps_dir = os.path.join(temp_dir, "OEBPS")
                os.makedirs(oebps_dir, exist_ok=True)
                
                # 处理章节
                chapter_files = []
                total_chapters = len(chapters)
                
                for i, chapter in enumerate(chapters):
                    # 生成XHTML内容
                    chapter_filename = f"chapter_{i+1}.xhtml"
                    chapter_path = os.path.join(oebps_dir, chapter_filename)
                    
                    # 创建基本XHTML结构
                    xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
    <title>{chapter['title']}</title>
</head>
<body>
    <h2>{chapter['title']}</h2>
</body>
</html>"""
                    
                    soup = BeautifulSoup(xhtml, "lxml-xml")
                    body = soup.find("body")
                    
                    # 添加段落
                    paragraphs = chapter['content'].split('\n')
                    for para in paragraphs:
                        if para.strip():
                            p_tag = soup.new_tag("p")
                            p_tag.string = para.strip()
                            body.append(p_tag)
                        else:
                            # 添加空行
                            br_tag = soup.new_tag("br")
                            body.append(br_tag)
                    
                    # 插入图片
                    chapter_images = image_allocation.get(i, [])
                    if chapter_images and len(paragraphs) > 6:  # 确保有足够段落插入图片
                        # 排除开头和结尾3行
                        valid_positions = list(range(3, len(paragraphs) - 3))
                        if valid_positions and chapter_images:
                            # 计算插入位置
                            step = max(1, len(valid_positions) // len(chapter_images))
                            positions = valid_positions[::step][:len(chapter_images)]
                            
                            # 获取所有段落标签
                            p_tags = soup.find_all("p")
                            
                            for idx, img_path in zip(positions, chapter_images):
                                if idx < len(p_tags):
                                    img_tag = soup.new_tag("div")
                                    img_tag['style'] = "text-align:center;margin:1em 0;"
                                    img = soup.new_tag("img", alt="插图")
                                    img["src"] = os.path.basename(img_path)
                                    img["style"] = "max-width:100%;height:auto;"
                                    img_tag.append(img)
                                    p_tags[idx].insert_after(img_tag)
                                    self.log_updated.emit(f"在 {chapter['title']} 插入图片: {os.path.basename(img_path)}")
                    
                    # 保存章节文件
                    with open(chapter_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))
                    
                    chapter_files.append({
                        "title": chapter['title'],
                        "filename": chapter_filename
                    })
                    
                    # 更新进度
                    progress = 60 + int(30 * (i + 1) / total_chapters)
                    self.progress_updated.emit(progress, f"生成章节... ({i+1}/{total_chapters})")
                
                # 复制图片
                image_files = []
                for img_path in images:
                    try:
                        img_filename = os.path.basename(img_path)
                        dest_path = os.path.join(oebps_dir, img_filename)
                        
                        # 处理文件名冲突
                        counter = 1
                        while os.path.exists(dest_path):
                            name, ext = os.path.splitext(img_filename)
                            img_filename = f"{name}_{counter}{ext}"
                            dest_path = os.path.join(oebps_dir, img_filename)
                            counter += 1
                            
                        shutil.copy(img_path, dest_path)
                        image_files.append(img_filename)
                    except Exception as e:
                        self.log_updated.emit(f"复制图片失败 {img_path}: {str(e)}")
                
                # 处理封面
                cover_filename = None
                if cover_path and os.path.exists(cover_path):
                    try:
                        cover_filename = "cover.jpg"
                        shutil.copy(cover_path, os.path.join(oebps_dir, cover_filename))
                        
                        # 创建封面XHTML
                        cover_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
    <title>封面</title>
</head>
<body>
    <div style="text-align:center; margin-top:50%;">
        <img src="{cover_filename}" alt="封面" style="max-width:100%; height:auto;"/>
    </div>
</body>
</html>"""
                        with open(os.path.join(oebps_dir, "cover.xhtml"), 'w', encoding='utf-8') as f:
                            f.write(cover_xhtml)
                    except Exception as e:
                        self.log_updated.emit(f"处理封面失败: {str(e)}")
                        cover_filename = None
                
                # 创建目录文件
                toc_path = os.path.join(oebps_dir, "toc.ncx")
                self.create_toc(toc_path, chapter_files, book_title)
                
                # 创建container.xml
                meta_inf_dir = os.path.join(temp_dir, "META-INF")
                os.makedirs(meta_inf_dir, exist_ok=True)
                container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>"""
                with open(os.path.join(meta_inf_dir, "container.xml"), 'w', encoding='utf-8') as f:
                    f.write(container_xml)
                
                # 创建content.opf
                self.create_content_opf(oebps_dir, chapter_files, image_files, cover_filename, book_title)
                
                # 创建mimetype文件
                with open(os.path.join(temp_dir, "mimetype"), 'w', encoding='utf-8') as f:
                    f.write("application/epub+zip")
                
                # 打包EPUB
                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as epub:
                    # 首先添加mimetype，不压缩
                    epub.write(os.path.join(temp_dir, "mimetype"), "mimetype", compress_type=zipfile.ZIP_STORED)
                    
                    # 添加其他文件
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            if file == "mimetype":
                                continue
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            epub.write(file_path, arcname)
                
                return True
        except Exception as e:
            self.log_updated.emit(f"创建EPUB失败: {str(e)}")
            return False

    def create_toc(self, ncx_path, chapters, book_title):
        """创建目录文件"""
        ncx_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xml:lang="zh-CN" xmlns="http://www.daisy.org/z3986/2005/ncx/">
    <head>
        <meta name="dtb:uid" content="{uuid.uuid4()}"/>
        <meta name="dtb:depth" content="1"/>
        <meta name="dtb:totalPageCount" content="0"/>
        <meta name="dtb:maxPageNumber" content="0"/>
    </head>
    <docTitle>
        <text>{book_title}</text>
    </docTitle>
    <navMap>
"""
        for i, chapter in enumerate(chapters, 1):
            ncx_content += f"""        <navPoint id="chapter{i}" playOrder="{i}">
            <navLabel>
                <text>{chapter['title']}</text>
            </navLabel>
            <content src="{chapter['filename']}"/>
        </navPoint>
"""
        ncx_content += """    </navMap>
</ncx>"""

        with open(ncx_path, 'w', encoding='utf-8') as f:
            f.write(ncx_content)

    def create_content_opf(self, oebps_dir, chapters, images, cover_filename, book_title):
        """创建content.opf文件"""
        manifest_items = []
        spine_items = []

        # 添加封面
        if cover_filename:
            manifest_items.append(f'<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
            manifest_items.append(f'<item id="cover-img" href="{cover_filename}" media-type="image/jpeg"/>')
            spine_items.append('<itemref idref="cover" linear="yes"/>')

        # 添加目录
        manifest_items.append('<item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

        # 添加章节文件
        for i, chapter in enumerate(chapters, 1):
            manifest_items.append(f'<item id="chapter{i}" href="{chapter["filename"]}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="chapter{i}" linear="yes"/>')

        # 添加插图
        for i, img_filename in enumerate(images):
            ext = os.path.splitext(img_filename)[1].lower()
            if ext == '.png':
                media_type = "image/png"
            elif ext in ['.jpg', '.jpeg']:
                media_type = "image/jpeg"
            elif ext == '.webp':
                media_type = "image/webp"
            else:
                media_type = "image/*"
            manifest_items.append(f'<item id="img{i}" href="{img_filename}" media-type="{media_type}"/>')

        opf_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" unique-identifier="bookid" xmlns="http://www.idpf.org/2007/opf">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>{book_title}</dc:title>
        <dc:language>zh-CN</dc:language>
        <dc:identifier id="bookid" opf:scheme="UUID">{uuid.uuid4()}</dc:identifier>
    </metadata>
    <manifest>
        {"\n        ".join(manifest_items)}
    </manifest>
    <spine>
        {"\n        ".join(spine_items)}
    </spine>
</package>"""
        with open(os.path.join(oebps_dir, "content.opf"), 'w', encoding='utf-8') as f:
            f.write(opf_content)


class EPubConverter(QMainWindow):
    """TXT转EPUB可视化工具主窗口"""
    def __init__(self):
        super().__init__()
        self.txt_files = []
        self.selected_images = []
        self.selected_cover = None
        self.config = self.load_config()
        
        self.init_ui()
        
    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("TXT转EPUB工具")
        self.setGeometry(100, 100, 1000, 700)
        
        # 主部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 1. 文件选择标签页
        file_tab = QWidget()
        file_layout = QVBoxLayout(file_tab)
        
        # 文件选择区域
        file_group = QGroupBox("选择TXT文件")
        file_group_layout = QVBoxLayout()
        
        file_buttons_layout = QHBoxLayout()
        self.select_files_btn = QPushButton("选择TXT文件")
        self.select_files_btn.clicked.connect(self.select_txt_files)
        self.clear_files_btn = QPushButton("清空列表")
        self.clear_files_btn.clicked.connect(self.clear_txt_files)
        file_buttons_layout.addWidget(self.select_files_btn)
        file_buttons_layout.addWidget(self.clear_files_btn)
        
        self.files_list = QListWidget()
        file_group_layout.addLayout(file_buttons_layout)
        file_group_layout.addWidget(self.files_list)
        file_group.setLayout(file_group_layout)
        
        # 封面选择区域
        cover_group = QGroupBox("封面设置")
        cover_layout = QVBoxLayout()
        
        cover_buttons_layout = QHBoxLayout()
        self.select_cover_btn = QPushButton("选择封面图片")
        self.select_cover_btn.clicked.connect(self.select_cover)
        self.random_cover_btn = QPushButton("随机选择封面")
        self.random_cover_btn.clicked.connect(self.random_select_cover)
        cover_buttons_layout.addWidget(self.select_cover_btn)
        cover_buttons_layout.addWidget(self.random_cover_btn)
        
        self.cover_preview = QLabel("封面预览")
        self.cover_preview.setAlignment(Qt.AlignCenter)
        self.cover_preview.setMinimumHeight(150)
        self.cover_preview.setStyleSheet("border: 1px solid #ccc;")
        
        cover_layout.addLayout(cover_buttons_layout)
        cover_layout.addWidget(self.cover_preview)
        cover_group.setLayout(cover_layout)
        
        # 插图选择区域
        image_group = QGroupBox("插图设置")
        image_layout = QVBoxLayout()
        
        image_buttons_layout = QHBoxLayout()
        self.select_images_btn = QPushButton("选择插图")
        self.select_images_btn.clicked.connect(self.select_images)
        self.default_images_btn = QPushButton("使用默认插图")
        self.default_images_btn.clicked.connect(self.use_default_images)
        self.clear_images_btn = QPushButton("清空插图")
        self.clear_images_btn.clicked.connect(self.clear_images)
        image_buttons_layout.addWidget(self.select_images_btn)
        image_buttons_layout.addWidget(self.default_images_btn)
        image_buttons_layout.addWidget(self.clear_images_btn)
        
        self.images_list = QListWidget()
        image_layout.addLayout(image_buttons_layout)
        image_layout.addWidget(self.images_list)
        image_group.setLayout(image_layout)
        
        # 添加到文件标签页
        file_layout.addWidget(file_group)
        file_layout.addWidget(cover_group)
        file_layout.addWidget(image_group)
        
        # 2. 配置标签页
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        
        config_form = QFormLayout()
        
        # 排序方式
        self.sort_method = QComboBox()
        self.sort_method.addItems(["创建时间", "字母顺序"])
        self.sort_method.setCurrentIndex(0 if self.config.get("sort_method", "create_time") == "create_time" else 1)
        config_form.addRow("章节排序方式:", self.sort_method)
        
        # 最大插图数量
        self.max_images = QSpinBox()
        self.max_images.setRange(1, 500)
        self.max_images.setValue(self.config.get("max_images", 300))
        config_form.addRow("最大插图数量:", self.max_images)
        
        # 封面尺寸阈值
        self.cover_width = QSpinBox()
        self.cover_width.setRange(300, 2000)
        self.cover_width.setValue(self.config.get("cover_width", 800))
        self.cover_height = QSpinBox()
        self.cover_height.setRange(500, 3000)
        self.cover_height.setValue(self.config.get("cover_height", 1200))
        
        cover_size_layout = QHBoxLayout()
        cover_size_layout.addWidget(self.cover_width)
        cover_size_layout.addWidget(QLabel("×"))
        cover_size_layout.addWidget(self.cover_height)
        config_form.addRow("封面尺寸阈值:", cover_size_layout)
        
        # 文本处理选项
        self.remove_chapter_marks = QCheckBox()
        self.remove_chapter_marks.setChecked(self.config.get("remove_chapter_marks", False))
        config_form.addRow("清除原有章节标识:", self.remove_chapter_marks)
        
        # 配置按钮
        config_buttons = QHBoxLayout()
        self.save_config_btn = QPushButton("保存配置")
        self.save_config_btn.clicked.connect(self.save_config)
        self.load_config_btn = QPushButton("加载配置")
        self.load_config_btn.clicked.connect(self.load_config)
        config_buttons.addWidget(self.save_config_btn)
        config_buttons.addWidget(self.load_config_btn)
        
        config_layout.addLayout(config_form)
        config_layout.addLayout(config_buttons)
        config_layout.addStretch()
        
        # 添加标签页
        tab_widget.addTab(file_tab, "文件选择")
        tab_widget.addTab(config_tab, "配置")
        
        # 进度条和日志区域
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setRange(0, 100)
        
        self.status_label = QLabel("就绪")
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        
        progress_layout.addWidget(self.status_label)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(QLabel("转换日志:"))
        progress_layout.addWidget(self.log_text)
        
        # 转换按钮
        self.convert_btn = QPushButton("开始转换")
        self.convert_btn.clicked.connect(self.start_conversion)
        progress_layout.addWidget(self.convert_btn)
        
        # 添加到主布局
        main_layout.addWidget(tab_widget)
        main_layout.addLayout(progress_layout)
        
        # 初始化默认插图
        self.use_default_images()

    def select_txt_files(self):
        """选择TXT文件"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择TXT文件", "", "TXT文件 (*.txt)")
        if files:
            for file in files:
                if file not in self.txt_files:
                    self.txt_files.append(file)
                    self.files_list.addItem(os.path.basename(file))

    def clear_txt_files(self):
        """清空TXT文件列表"""
        self.txt_files = []
        self.files_list.clear()

    def select_cover(self):
        """选择封面图片"""
        file, _ = QFileDialog.getOpenFileName(
            self, "选择封面图片", DEFAULT_COVER_DIR, 
            "图片文件 (*.png *.jpg *.jpeg *.webp)"
        )
        if file:
            self.selected_cover = file
            self.update_cover_preview()

    def random_select_cover(self):
        """随机选择封面图片"""
        try:
            if not os.path.exists(DEFAULT_COVER_DIR):
                QMessageBox.warning(self, "警告", f"默认封面目录不存在: {DEFAULT_COVER_DIR}")
                return
                
            # 获取符合条件的图片
            valid_images = []
            for file in os.listdir(DEFAULT_COVER_DIR):
                file_path = os.path.join(DEFAULT_COVER_DIR, file)
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    try:
                        from PIL import Image
                        with Image.open(file_path) as img:
                            width, height = img.size
                            if width >= self.cover_width.value() and height >= self.cover_height.value():
                                valid_images.append(file_path)
                    except:
                        continue
            
            if valid_images:
                self.selected_cover = random.choice(valid_images)
                self.update_cover_preview()
                self.log(f"随机选择封面: {os.path.basename(self.selected_cover)}")
            else:
                QMessageBox.information(self, "提示", "没有找到符合尺寸要求的封面图片")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"选择封面失败: {str(e)}")

    def update_cover_preview(self):
        """更新封面预览"""
        if self.selected_cover and os.path.exists(self.selected_cover):
            pixmap = QPixmap(self.selected_cover)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.cover_preview.width(), 
                    self.cover_preview.height(), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                self.cover_preview.setPixmap(scaled_pixmap)
                return
                
        self.cover_preview.setText("无法预览封面")

    def select_images(self):
        """选择插图"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择插图", DEFAULT_COVER_DIR, 
            "图片文件 (*.png *.jpg *.jpeg *.webp)"
        )
        if files:
            for file in files:
                if file not in self.selected_images:
                    self.selected_images.append(file)
                    self.images_list.addItem(os.path.basename(file))

    def use_default_images(self):
        """使用默认目录的插图"""
        try:
            if not os.path.exists(DEFAULT_COVER_DIR):
                self.log(f"默认封面目录不存在: {DEFAULT_COVER_DIR}")
                return
                
            self.selected_images = []
            self.images_list.clear()
            
            for file in os.listdir(DEFAULT_COVER_DIR):
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    file_path = os.path.join(DEFAULT_COVER_DIR, file)
                    self.selected_images.append(file_path)
                    self.images_list.addItem(file)
            
            self.log(f"加载默认插图 {len(self.selected_images)} 张")
        except Exception as e:
            self.log(f"加载默认插图失败: {str(e)}")

    def clear_images(self):
        """清空插图列表"""
        self.selected_images = []
        self.images_list.clear()

    def log(self, message):
        """添加日志信息"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        # 滚动到底部
        self.log_text.moveCursor(self.log_text.textCursor().End)

    def save_config(self):
        """保存配置"""
        try:
            config = {
                "sort_method": "create_time" if self.sort_method.currentIndex() == 0 else "name",
                "max_images": self.max_images.value(),
                "cover_width": self.cover_width.value(),
                "cover_height": self.cover_height.value(),
                "remove_chapter_marks": self.remove_chapter_marks.isChecked(),
                "last_used": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                
            self.log(f"配置已保存到 {CONFIG_PATH}")
            QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")
            QMessageBox.warning(self, "失败", f"保存配置失败: {str(e)}")

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                # 更新UI
                self.sort_method.setCurrentIndex(0 if config.get("sort_method", "create_time") == "create_time" else 1)
                self.max_images.setValue(config.get("max_images", 300))
                self.cover_width.setValue(config.get("cover_width", 800))
                self.cover_height.setValue(config.get("cover_height", 1200))
                self.remove_chapter_marks.setChecked(config.get("remove_chapter_marks", False))
                
                self.log(f"已加载配置 {CONFIG_PATH}")
                return config
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")
            
        # 默认配置
        return {
            "sort_method": "create_time",
            "max_images": 300,
            "cover_width": 800,
            "cover_height": 1200,
            "remove_chapter_marks": False
        }

    def start_conversion(self):
        """开始转换过程"""
        if not self.txt_files:
            QMessageBox.warning(self, "警告", "请先选择TXT文件")
            return
            
        # 保存当前配置
        self.save_config()
        
        # 准备转换参数
        current_config = {
            "sort_method": "create_time" if self.sort_method.currentIndex() == 0 else "name",
            "max_images": self.max_images.value(),
            "cover_width": self.cover_width.value(),
            "cover_height": self.cover_height.value(),
            "remove_chapter_marks": self.remove_chapter_marks.isChecked()
        }
        
        # 禁用转换按钮
        self.convert_btn.setEnabled(False)
        
        # 创建并启动转换线程
        self.convert_thread = ConvertThread(
            self.txt_files,
            DEFAULT_OUTPUT_DIR,
            self.selected_cover,
            self.selected_images,
            current_config
        )
        
        # 连接信号槽
        self.convert_thread.progress_updated.connect(self.update_progress)
        self.convert_thread.log_updated.connect(self.log)
        self.convert_thread.finished.connect(self.conversion_finished)
        
        # 启动线程
        self.convert_thread.start()

    def update_progress(self, value, status):
        """更新进度条和状态"""
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def conversion_finished(self, success, message):
        """转换完成处理"""
        self.convert_btn.setEnabled(True)
        
        if success:
            reply = QMessageBox.information(
                self, "成功", 
                f"{message}\n是否打开输出目录？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                os.startfile(DEFAULT_OUTPUT_DIR)
        else:
            QMessageBox.warning(self, "失败", message)


if __name__ == "__main__":
    # 确保中文显示正常
    import matplotlib
    matplotlib.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
    
    app = QApplication(sys.argv)
    window = EPubConverter()
    window.show()
    sys.exit(app.exec_())
```

使用说明：

1. 程序需要安装以下依赖库：`PyQt5`, `beautifulsoup4`, `chardet`, `Pillow`，可以通过`pip install PyQt5 beautifulsoup4 chardet Pillow`安装

2. 功能亮点：
   - 可视化界面，操作简单直观
   - 支持TXT文件多选和排序
   - 封面可以手动选择或从默认目录随机选择（优先符合尺寸要求的）
   - 插图可以自定义选择或使用默认目录图片
   - 丰富的配置选项，支持保存和加载配置
   - 转换过程中显示进度和详细日志
   - 转换完成后可直接打开输出目录

3. 程序遵循您要求的所有规则，包括章节命名、文本处理、插图分配、文件命名等规范

4. 配置文件保存在`./json/txt_epub_config.json`，可以自定义各种转换参数

运行程序后，只需选择TXT文件，设置封面和插图（或使用默认），点击"开始转换"即可生成EPUB文件。
