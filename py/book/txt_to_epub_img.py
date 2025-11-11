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
                             QLabel, QPushButton, QFileDialog, QListWidget, QCheckBox, QLineEdit,
                             QProgressBar, QTextEdit, QMessageBox, QGroupBox, QRadioButton,
                             QSpinBox, QDoubleSpinBox, QFormLayout, QComboBox, QSplitter,
                             QTabWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDateTime, QSize
from PyQt5.QtGui import QPixmap, QImage, QIcon
from bs4 import BeautifulSoup
import chardet
import re

# 默认配置路径
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "txt_epub_config.json")

# 确保配置目录存在
os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)


class ConvertThread(QThread):
    """转换线程，用于后台处理文件转换，不阻塞UI"""
    progress_updated = pyqtSignal(int, str)  # 进度值，当前阶段
    log_updated = pyqtSignal(str)  # 日志信息
    finished = pyqtSignal(bool, str)  # 完成状态，消息

    def __init__(self, txt_files, output_dir, cover_dir, cover_path, image_paths, config):
        super().__init__()
        self.txt_files = txt_files
        self.output_dir = output_dir
        self.cover_dir = cover_dir
        self.cover_path = cover_path
        self.image_paths = image_paths
        self.config = config
        self.log_file = None
        self.logger = None
        # 保存原始文件名用于生成目录
        self.original_filenames = [os.path.splitext(os.path.basename(f))[0] for f in txt_files]

    def run(self):
        try:
            # 初始化日志
            self.init_logger()
            # 确保输出目录存在
            os.makedirs(self.output_dir, exist_ok=True)

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
                self.progress_updated.emit(progress, f"读取文件... ({i + 1}/{total_files})")

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
                    base_title = f"第{i + 1}章 {os.path.splitext(os.path.basename(chapter['path']))[0]}"

                    processed_chapters.append({
                        "base_title": base_title,  # 基础标题，用于切割后的子章节
                        "content": processed_content,
                        "length": len(processed_content),
                        "original_length": chapter["length"]
                    })

                    self.log_updated.emit(f"处理完成: {base_title}")
                except Exception as e:
                    self.log_updated.emit(f"处理文本失败 {chapter['path']}: {str(e)}")

                progress = 30 + int(20 * (i + 1) / total_files)
                self.progress_updated.emit(progress, f"处理文本... ({i + 1}/{total_files})")

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
            # 先展平所有章节（包括切割后的）再分配图片
            flat_chapters = []
            for chapter in processed_chapters:
                # 根据配置切割章节
                max_size_kb = self.config.get("max_chapter_size", 200)
                max_size_bytes = max_size_kb * 1024  # 转换为字节
                sub_chapters = self.split_chapter_by_size(chapter, max_size_bytes)
                flat_chapters.extend(sub_chapters)

            image_allocation = self.allocate_images(flat_chapters, valid_images, total_length)

            # 6. 生成EPUB
            self.progress_updated.emit(60, "生成EPUB...")
            book_title = os.path.basename(os.path.dirname(sorted_files[0])) if sorted_files else "未知书籍"
            epub_filename = self.generate_epub_filename(book_title)
            epub_path = os.path.join(self.output_dir, epub_filename)

            success = self.create_epub(
                flat_chapters,  # 使用切割后的章节列表
                epub_path,
                self.cover_path,
                valid_images,
                image_allocation,
                epub_filename.replace(".epub","")
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

    def split_chapter_by_size(self, chapter, max_size_bytes):
        """根据最大文件大小切割章节"""
        content = chapter["content"]
        base_title = chapter["base_title"]

        # 估算当前内容转换为XHTML后的大小
        # 经验系数：纯文本转换为XHTML后大约会增加30-50%的大小
        estimated_xhtml_size = len(content.encode('utf-8')) * 1.4

        # 如果小于最大限制，不需要切割
        if estimated_xhtml_size <= max_size_bytes:
            return [{
                "title": base_title,
                "content": content,
                "length": len(content)
            }]

        # 需要切割，按段落分割内容
        paragraphs = content.split('\n')
        sub_chapters = []
        current_paragraphs = []
        current_size = 0

        for para in paragraphs:
            # 估算段落的XHTML大小
            para_size = len(para.encode('utf-8')) * 1.4  # 应用同样的经验系数

            # 如果添加当前段落后超过限制，则创建新的子章节
            if current_size + para_size > max_size_bytes and current_paragraphs:
                sub_content = '\n'.join(current_paragraphs)
                sub_chapters.append({
                    "title": f"{base_title}（{len(sub_chapters) + 1}）",
                    "content": sub_content,
                    "length": len(sub_content)
                })
                current_paragraphs = [para]
                current_size = para_size
            else:
                current_paragraphs.append(para)
                current_size += para_size

        # 添加最后一个子章节
        if current_paragraphs:
            sub_content = '\n'.join(current_paragraphs)
            sub_chapters.append({
                "title": f"{base_title}（{len(sub_chapters) + 1}）",
                "content": sub_content,
                "length": len(sub_content)
            })

        self.log_updated.emit(f"章节 '{base_title}' 已切割为 {len(sub_chapters)} 个子章节")
        return sub_chapters

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
            r'^[0-9]+\..*$',  # 1. ...
            r'^[一二三四五六七八九十]+、.*$',  # 一、...
            r'^\【.*\】$',  # 【章节名】
            r'^章节.*$'  # 章节...
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
        """处理换行和空行，不添加<br>标签"""
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
        # 检查是否使用自定义文件名
        if self.config.get("use_custom_filename", False) and self.config.get("custom_filename"):
            template = self.config["custom_filename"]
            # 替换占位符
            timestamp = datetime.now().strftime('%Y%m%d')
            filename = template.replace("{title}", book_title).replace("{timestamp}", timestamp)
            # 确保扩展名正确
            if not filename.endswith(".epub"):
                filename += ".epub"
        else:
            # 原文件名生成逻辑
            timestamp = datetime.now().strftime('%Y%m%d')
            filename = f"{book_title}_{timestamp}.epub"

        # 避免文件名重复的逻辑保持不变
        file_path = os.path.join(self.output_dir, filename)
        counter = 1
        while os.path.exists(file_path):
            base, ext = os.path.splitext(filename)
            filename = f"{base}_{counter}{ext}"
            file_path = os.path.join(self.output_dir, filename)
            counter += 1

        return filename

    def create_epub(self, chapters, output_path, cover_path, images, image_allocation, book_title):
        """创建EPUB文件"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # 创建目录结构
                oebps_dir = os.path.join(temp_dir, "OEBPS")
                os.makedirs(oebps_dir, exist_ok=True)

                # 处理图片 - 使用UUID重命名
                image_uuid_map = {}  # 原路径 -> UUID文件名
                image_files = []

                for img_path in images:
                    try:
                        # 获取文件扩展名
                        ext = os.path.splitext(img_path)[1].lower()
                        # 生成UUID作为文件名
                        uuid_filename = f"{uuid.uuid4()}{ext}"
                        dest_path = os.path.join(oebps_dir, uuid_filename)

                        # 复制图片
                        shutil.copy(img_path, dest_path)
                        image_uuid_map[img_path] = uuid_filename
                        image_files.append(uuid_filename)

                        self.log_updated.emit(f"处理图片: {os.path.basename(img_path)} -> {uuid_filename}")
                    except Exception as e:
                        self.log_updated.emit(f"复制图片失败 {img_path}: {str(e)}")

                # 处理章节
                chapter_files = []
                total_chapters = len(chapters)

                for i, chapter in enumerate(chapters):
                    # 生成XHTML内容
                    chapter_filename = f"chapter_{i + 1}.xhtml"
                    chapter_path = os.path.join(oebps_dir, chapter_filename)

                    # 创建基本XHTML结构
                    xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
    <title>{chapter['title']}</title>
</head>
<body>
    <h2  id="title" class="titlel2std">{chapter['title']}</h2>
</body>
</html>"""

                    soup = BeautifulSoup(xhtml, "lxml-xml")
                    body = soup.find("body")

                    # 添加段落 - 不使用<br>标签
                    paragraphs = chapter['content'].split('\n')
                    for para in paragraphs:
                        if para.strip():
                            p_tag = soup.new_tag("p")
                            p_tag.string = para.strip()
                            body.append(p_tag)

                    # 插入图片 - 使用UUID文件名
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
                                if idx < len(p_tags) and img_path in image_uuid_map:
                                    img_tag = soup.new_tag("div")
                                    img_tag['style'] = "text-align:center;margin:1em 0;"
                                    img = soup.new_tag("img", alt="插图")
                                    # 使用UUID文件名
                                    img["src"] = image_uuid_map[img_path]
                                    img["style"] = "max-width:100%;height:auto;"
                                    img_tag.append(img)
                                    p_tags[idx].insert_after(img_tag)
                                    self.log_updated.emit(
                                        f"在 {chapter['title']} 插入图片: {os.path.basename(img_path)}")

                    # 保存章节文件
                    with open(chapter_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))

                    # 记录实际文件大小
                    file_size = os.path.getsize(chapter_path)
                    self.log_updated.emit(f"生成章节: {chapter['title']} ({file_size / 1024:.1f}KB)")

                    chapter_files.append({
                        "title": chapter['title'],
                        "filename": chapter_filename
                    })

                    # 更新进度
                    progress = 60 + int(30 * (i + 1) / total_chapters)
                    self.progress_updated.emit(progress, f"生成章节... ({i + 1}/{total_chapters})")

                # 生成目录文件 book-toc.xhtml
                self.create_book_toc(oebps_dir, chapter_files)

                # 处理封面 - 使用UUID重命名
                cover_filename = None
                if cover_path and os.path.exists(cover_path):
                    try:
                        # 获取文件扩展名
                        ext = os.path.splitext(cover_path)[1].lower()
                        #
                        cover_filename = f"cover{ext}"
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

                        self.log_updated.emit(f"处理封面: {os.path.basename(cover_path)} -> {cover_filename}")
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

                # 创建content.opf - 使用UUID文件名
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

    def create_book_toc(self, oebps_dir, chapters):
        """创建book-toc.xhtml目录文件"""
        toc_content = """<?xml version="1.0" encoding="utf-8" ?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
<meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8" />
<meta name="generator" content="EasyPub v1.50" />
<title>
Table Of Contents
</title>
<link rel="stylesheet" href="style.css" type="text/css"/>
</head>
<body>
<h2 class="titletoc">
目录
</h2>
<div class="toc">
<dl>
"""
        # 添加目录项
        for i, chapter in enumerate(chapters):
            toc_content += f'<dt class="tocl2"><a href="{chapter["filename"]}">{chapter["title"]}</a></dt>\n'

        toc_content += """</dl>
</div>
</body>
</html>"""

        # 保存目录文件
        toc_path = os.path.join(oebps_dir, "book-toc.xhtml")
        with open(toc_path, 'w', encoding='utf-8') as f:
            f.write(toc_content)

        self.log_updated.emit("生成目录文件: book-toc.xhtml")

    def create_toc(self, ncx_path, chapters, book_title):
        """创建目录文件"""
        ncx_content = f"""<?xml version="1.0" encoding="utf-8" standalone="no" ?>
        <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx version="2005-1" xml:lang="zh-CN" xmlns="http://www.daisy.org/z3986/2005/ncx/">
    <head>
        <meta name="cover" content="cover" />
        <meta name="dtb:uid" content="{uuid.uuid4()}"/>
        <meta name="dtb:depth" content="1"/>
        <meta name="dtb:totalPageCount" content="0"/>
        <meta name="dtb:maxPageNumber" content="0"/>
    </head>
    <docTitle>
        <text>{book_title}</text>
    </docTitle>
    <docAuthor>
        <text>评重楼</text>
    </docAuthor>
    <navMap>
      <navPoint id="cover" playOrder="0">
            <navLabel>
                <text>封面</text>
            </navLabel>
            <content src="cover.html" />
        </navPoint>
        <navPoint id="htmltoc" playOrder="1">
            <navLabel>
                <text>目录</text>
            </navLabel>
            <content src="book-toc.xhtml" />
        </navPoint>
"""
        for i, chapter in enumerate(chapters, 2):
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
            ext = os.path.splitext(cover_filename)[1].lower()
            if ext == '.png':
                cover_media_type = "image/png"
            elif ext in ['.jpg', '.jpeg']:
                cover_media_type = "image/jpeg"
            elif ext == '.webp':
                cover_media_type = "image/webp"
            else:
                cover_media_type = "image/*"

            manifest_items.append(f'<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
            manifest_items.append(f'<item id="cover-img" href="{cover_filename}" media-type="{cover_media_type}"/>')

            spine_items.append('<itemref idref="cover" linear="no"/>')

        # 添加自定义目录文件
        manifest_items.append('<item id="book-toc" href="book-toc.xhtml" media-type="application/xhtml+xml"/>')
        spine_items.append('<itemref idref="book-toc" linear="no"/>')

        # 添加目录
        manifest_items.append('<item id="ncxtoc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

        # 添加章节文件
        for i, chapter in enumerate(chapters, 1):
            manifest_items.append(
                f'<item id="chapter{i}" href="{chapter["filename"]}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="chapter{i}" linear="yes"/>')

        # 添加插图 - 使用UUID文件名
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
    <spine  toc="ncxtoc">
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

        # 先初始化UI，再加载配置（解决属性不存在问题）
        self.init_ui()
        self.config = self.load_config()

        # 从配置获取目录路径
        self.default_cover_dir = self.config.get("default_cover_dir", r"D:\book\封面")
        self.default_output_dir = self.config.get("default_output_dir", r"D:\book\epub-py")

        # 更新UI显示
        self.cover_dir_edit.setText(self.default_cover_dir)
        self.output_dir_edit.setText(self.default_output_dir)
        self.max_chapter_size.setValue(self.config.get("max_chapter_size", 200))

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
        config_form.addRow("章节排序方式:", self.sort_method)

        # 最大插图数量
        self.max_images = QSpinBox()
        self.max_images.setRange(1, 500)
        self.max_images.setValue(300)
        config_form.addRow("最大插图数量:", self.max_images)

        # 章节大小限制
        self.max_chapter_size = QSpinBox()
        self.max_chapter_size.setRange(50, 1000)  # 50KB到1000KB
        self.max_chapter_size.setValue(200)  # 默认200KB
        self.max_chapter_size.setSuffix(" KB")
        config_form.addRow("章节最大大小:", self.max_chapter_size)

        # 封面尺寸阈值
        self.cover_width = QSpinBox()
        self.cover_width.setRange(300, 2000)
        self.cover_width.setValue(800)
        self.cover_height = QSpinBox()
        self.cover_height.setRange(500, 3000)
        self.cover_height.setValue(1200)

        cover_size_layout = QHBoxLayout()
        cover_size_layout.addWidget(self.cover_width)
        cover_size_layout.addWidget(QLabel("×"))
        cover_size_layout.addWidget(self.cover_height)
        config_form.addRow("封面尺寸阈值:", cover_size_layout)

        # 文本处理选项
        self.remove_chapter_marks = QCheckBox()
        config_form.addRow("清除原有章节标识:", self.remove_chapter_marks)

        # 目录设置
        self.cover_dir_edit = QTextEdit()
        self.cover_dir_edit.setMaximumHeight(50)
        config_form.addRow("默认封面目录:", self.cover_dir_edit)

        self.output_dir_edit = QTextEdit()
        self.output_dir_edit.setMaximumHeight(50)
        config_form.addRow("默认输出目录:", self.output_dir_edit)

        # 在init_ui方法的config_form部分添加
        self.use_custom_filename = QCheckBox()
        config_form.addRow("使用自定义文件名:", self.use_custom_filename)

        self.custom_filename = QLineEdit()
        self.custom_filename.setPlaceholderText("支持{title}和{timestamp}占位符")
        config_form.addRow("自定义文件名模板:", self.custom_filename)

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
            self, "选择封面图片", self.default_cover_dir,
            "图片文件 (*.png *.jpg *.jpeg *.webp)"
        )
        if file:
            self.selected_cover = file
            self.update_cover_preview()

    def random_select_cover(self):
        """随机选择封面图片"""
        try:
            if not os.path.exists(self.default_cover_dir):
                QMessageBox.warning(self, "警告", f"默认封面目录不存在: {self.default_cover_dir}")
                return

            # 获取符合条件的图片
            valid_images = []
            for file in os.listdir(self.default_cover_dir):
                file_path = os.path.join(self.default_cover_dir, file)
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
            self, "选择插图", self.default_cover_dir,
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
            if not os.path.exists(self.default_cover_dir):
                self.log(f"默认封面目录不存在: {self.default_cover_dir}")
                return

            self.selected_images = []
            self.images_list.clear()

            for file in os.listdir(self.default_cover_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    file_path = os.path.join(self.default_cover_dir, file)
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
            # 获取目录路径
            self.default_cover_dir = self.cover_dir_edit.toPlainText().strip()
            self.default_output_dir = self.output_dir_edit.toPlainText().strip()

            # 确保目录存在
            if self.default_cover_dir:
                os.makedirs(self.default_cover_dir, exist_ok=True)
            if self.default_output_dir:
                os.makedirs(self.default_output_dir, exist_ok=True)

            config = {
                "sort_method": "create_time" if self.sort_method.currentIndex() == 0 else "name",
                "max_images": self.max_images.value(),
                "max_chapter_size": self.max_chapter_size.value(),  # 新增配置项
                "cover_width": self.cover_width.value(),
                "cover_height": self.cover_height.value(),
                "remove_chapter_marks": self.remove_chapter_marks.isChecked(),
                "default_cover_dir": self.default_cover_dir,
                "default_output_dir": self.default_output_dir,
                "custom_filename": self.custom_filename.text(),
                "use_custom_filename": self.use_custom_filename.isChecked(),
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
                self.max_chapter_size.setValue(config.get("max_chapter_size", 200))  # 加载章节大小配置
                self.cover_width.setValue(config.get("cover_width", 800))
                self.cover_height.setValue(config.get("cover_height", 1200))
                self.remove_chapter_marks.setChecked(config.get("remove_chapter_marks", False))
                self.use_custom_filename.setChecked(config.get("use_custom_filename", False))
                self.custom_filename.setText(config.get("custom_filename", r"新文件"))

                # 更新目录路径
                self.default_cover_dir = config.get("default_cover_dir", r"D:\book\封面")
                self.default_output_dir = config.get("default_output_dir", r"D:\book\epub-py")
                self.cover_dir_edit.setText(self.default_cover_dir)
                self.output_dir_edit.setText(self.default_output_dir)

                self.log(f"已加载配置 {CONFIG_PATH}")
                return config
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")

        # 默认配置
        return {
            "sort_method": "create_time",
            "max_images": 300,
            "max_chapter_size": 200,  # 默认章节大小200KB
            "cover_width": 800,
            "cover_height": 1200,
            "remove_chapter_marks": False,
            "default_cover_dir": r"D:\book\封面",
            "default_output_dir": r"D:\book\epub-py",
            "custom_filename": "",  # 新增：自定义文件名模板
            "use_custom_filename": False  # 新增：是否使用自定义文件名
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
            "max_chapter_size": self.max_chapter_size.value(),  # 传递章节大小配置
            "cover_width": self.cover_width.value(),
            "cover_height": self.cover_height.value(),
            "remove_chapter_marks": self.remove_chapter_marks.isChecked(),
            "use_custom_filename": self.use_custom_filename.isChecked(),
            "custom_filename": self.custom_filename.text()
        }

        # 禁用转换按钮
        self.convert_btn.setEnabled(False)

        # 创建并启动转换线程
        self.convert_thread = ConvertThread(
            self.txt_files,
            self.default_output_dir,
            self.default_cover_dir,
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
                os.startfile(self.default_output_dir)
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
