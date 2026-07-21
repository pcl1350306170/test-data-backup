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

import matplotlib
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFileDialog, QListWidget, QCheckBox, QLineEdit,
                             QProgressBar, QTextEdit, QMessageBox, QGroupBox, QSpinBox,
                             QFormLayout, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from bs4 import BeautifulSoup
import chardet

SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "batch_txt_to_epub"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"{SCRIPT_NAME}_config.json"
CONFIG_DIR.mkdir(exist_ok=True)




# ──────────── 公共日志模块（可选依赖）────────────
import sys
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────
# ========================== 工具函数 ==========================

def read_file_with_encoding(file_path):
    """自动识别编码并读取文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='gbk') as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                encoding = result['encoding'] or 'utf-8'
            try:
                return raw_data.decode(encoding, errors='replace')
            except:
                raise Exception(f"无法解码文件，尝试过UTF-8、GBK和{encoding}")


def remove_chapter_marks(content):
    """移除章节标识"""
    import re
    patterns = [
        r'^第[零一二三四五六七八九十百千万]+章.*$',
        r'^[0-9]+\..*$',
        r'^[一二三四五六七八九十]+、.*$',
        r'^\【.*\】$',
        r'^章节.*$'
    ]
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped_line = line.strip()
        if any(re.match(pattern, stripped_line) for pattern in patterns):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


def process_line_breaks(content):
    """处理换行和空行"""
    lines = [line.rstrip() for line in content.split('\n')]
    processed = []
    current_line = ""
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
            if current_line and current_line[-1] in '。！？；：\u201c\u201d\u2018\u300b\u3011\uff09\u300d':
                processed.append(current_line)
                current_line = ""
    if current_line:
        processed.append(current_line)
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


def split_chapter_by_size(content, base_title, max_size_bytes, log_fn):
    """根据最大文件大小切割章节"""
    estimated_xhtml_size = len(content.encode('utf-8')) * 1.4
    if estimated_xhtml_size <= max_size_bytes:
        return [{"title": base_title, "content": content, "length": len(content)}]

    paragraphs = content.split('\n')
    sub_chapters = []
    current_paragraphs = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para.encode('utf-8')) * 1.4
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

    if current_paragraphs:
        sub_content = '\n'.join(current_paragraphs)
        sub_chapters.append({
            "title": f"{base_title}（{len(sub_chapters) + 1}）",
            "content": sub_content,
            "length": len(sub_content)
        })

    log_fn(f"章节 '{base_title}' 已切割为 {len(sub_chapters)} 个子章节")
    return sub_chapters


def allocate_images(chapters, images, total_length):
    """按章节长度比例分配插图"""
    if not images:
        return {}
    allocation = {}
    remaining_images = images.copy()
    random.shuffle(remaining_images)
    for i, chapter in enumerate(chapters):
        if total_length == 0:
            allocation[i] = []
            continue
        ratio = chapter["length"] / total_length
        num_images = max(0, round(ratio * len(images)))
        allocation[i] = remaining_images[:num_images]
        remaining_images = remaining_images[num_images:]
    i = 0
    while remaining_images and i < len(chapters):
        allocation[i].append(remaining_images.pop(0))
        i = (i + 1) % len(chapters)
    return allocation


def is_valid_image(img_path):
    """检查图片是否有效"""
    try:
        from PIL import Image
        with Image.open(img_path) as img:
            return True
    except:
        return False


# ========================== EPUB 创建 ==========================

def create_epub(chapters, output_path, cover_path, images, image_allocation, book_title, log_fn):
    """创建EPUB文件"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            oebps_dir = os.path.join(temp_dir, "OEBPS")
            os.makedirs(oebps_dir, exist_ok=True)

            # 处理图片
            image_uuid_map = {}
            image_files = []
            for img_path in images:
                try:
                    ext = os.path.splitext(img_path)[1].lower()
                    uuid_filename = f"{uuid.uuid4()}{ext}"
                    dest_path = os.path.join(oebps_dir, uuid_filename)
                    shutil.copy(img_path, dest_path)
                    image_uuid_map[img_path] = uuid_filename
                    image_files.append(uuid_filename)
                except Exception as e:
                    log_fn(f"复制图片失败 {img_path}: {str(e)}")

            # 处理章节
            chapter_files = []
            total_chapters = len(chapters)
            for i, chapter in enumerate(chapters):
                chapter_filename = f"chapter_{i + 1}.xhtml"
                chapter_path = os.path.join(oebps_dir, chapter_filename)

                xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
    <title>{chapter['title']}</title>
</head>
<body>
    <h2 id="title" class="titlel2std">{chapter['title']}</h2>
</body>
</html>"""
                soup = BeautifulSoup(xhtml, "lxml-xml")
                body = soup.find("body")

                paragraphs = chapter['content'].split('\n')
                for para in paragraphs:
                    if para.strip():
                        p_tag = soup.new_tag("p")
                        p_tag.string = para.strip()
                        body.append(p_tag)

                # 插入图片
                chapter_images = image_allocation.get(i, [])
                if chapter_images and len(paragraphs) > 6:
                    valid_positions = list(range(3, len(paragraphs) - 3))
                    if valid_positions and chapter_images:
                        step = max(1, len(valid_positions) // len(chapter_images))
                        positions = valid_positions[::step][:len(chapter_images)]
                        p_tags = soup.find_all("p")
                        for idx, img_path in zip(positions, chapter_images):
                            if idx < len(p_tags) and img_path in image_uuid_map:
                                img_tag = soup.new_tag("div")
                                img_tag['style'] = "text-align:center;margin:1em 0;"
                                img = soup.new_tag("img", alt="插图")
                                img["src"] = image_uuid_map[img_path]
                                img["style"] = "max-width:100%;height:auto;"
                                img_tag.append(img)
                                p_tags[idx].insert_after(img_tag)

                with open(chapter_path, 'w', encoding='utf-8') as f:
                    f.write(str(soup))

                file_size = os.path.getsize(chapter_path)
                log_fn(f"生成章节: {chapter['title']} ({file_size / 1024:.1f}KB)")
                chapter_files.append({"title": chapter['title'], "filename": chapter_filename})

            # 生成目录
            create_book_toc(oebps_dir, chapter_files, log_fn)

            # 处理封面
            cover_filename = None
            if cover_path and os.path.exists(cover_path):
                try:
                    ext = os.path.splitext(cover_path)[1].lower()
                    cover_filename = f"cover{ext}"
                    shutil.copy(cover_path, os.path.join(oebps_dir, cover_filename))
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
                    log_fn(f"处理封面失败: {str(e)}")
                    cover_filename = None

            # toc.ncx
            toc_path = os.path.join(oebps_dir, "toc.ncx")
            create_toc(toc_path, chapter_files, book_title)

            # container.xml
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

            # content.opf
            create_content_opf(oebps_dir, chapter_files, image_files, cover_filename, book_title)

            # mimetype
            with open(os.path.join(temp_dir, "mimetype"), 'w', encoding='utf-8') as f:
                f.write("application/epub+zip")

            # 打包
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as epub:
                epub.write(os.path.join(temp_dir, "mimetype"), "mimetype", compress_type=zipfile.ZIP_STORED)
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        if file == "mimetype":
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        epub.write(file_path, arcname)
            return True
    except Exception as e:
        log_fn(f"创建EPUB失败: {str(e)}")
        return False


def create_book_toc(oebps_dir, chapters, log_fn):
    """创建book-toc.xhtml目录文件"""
    toc_content = """<?xml version="1.0" encoding="utf-8" ?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
<meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8" />
<title>Table Of Contents</title>
</head>
<body>
<h2 class="titletoc">目录</h2>
<div class="toc">
<dl>
"""
    for chapter in chapters:
        toc_content += f'<dt class="tocl2"><a href="{chapter["filename"]}">{chapter["title"]}</a></dt>\n'
    toc_content += """</dl>
</div>
</body>
</html>"""
    toc_path = os.path.join(oebps_dir, "book-toc.xhtml")
    with open(toc_path, 'w', encoding='utf-8') as f:
        f.write(toc_content)
    log_fn("生成目录文件: book-toc.xhtml")


def create_toc(ncx_path, chapters, book_title):
    """创建toc.ncx"""
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
    <docTitle><text>{book_title}</text></docTitle>
    <docAuthor><text>评重楼</text></docAuthor>
    <navMap>
      <navPoint id="cover" playOrder="0">
            <navLabel><text>封面</text></navLabel>
            <content src="cover.html" />
        </navPoint>
        <navPoint id="htmltoc" playOrder="1">
            <navLabel><text>目录</text></navLabel>
            <content src="book-toc.xhtml" />
        </navPoint>
"""
    for i, chapter in enumerate(chapters, 2):
        ncx_content += f"""        <navPoint id="chapter{i}" playOrder="{i}">
            <navLabel><text>{chapter['title']}</text></navLabel>
            <content src="{chapter['filename']}"/>
        </navPoint>
"""
    ncx_content += """    </navMap>
</ncx>"""
    with open(ncx_path, 'w', encoding='utf-8') as f:
        f.write(ncx_content)


def create_content_opf(oebps_dir, chapters, images, cover_filename, book_title):
    """创建content.opf"""
    manifest_items = []
    spine_items = []

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

    manifest_items.append('<item id="book-toc" href="book-toc.xhtml" media-type="application/xhtml+xml"/>')
    spine_items.append('<itemref idref="book-toc" linear="no"/>')
    manifest_items.append('<item id="ncxtoc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')

    for i, chapter in enumerate(chapters, 1):
        manifest_items.append(
            f'<item id="chapter{i}" href="{chapter["filename"]}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="chapter{i}" linear="yes"/>')

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
    <spine toc="ncxtoc">
        {"\n        ".join(spine_items)}
    </spine>
</package>"""
    with open(os.path.join(oebps_dir, "content.opf"), 'w', encoding='utf-8') as f:
        f.write(opf_content)


# ========================== 批量转换线程 ==========================

class BatchConvertThread(QThread):
    """批量转换线程"""
    progress_updated = pyqtSignal(int, str)
    log_updated = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, txt_dir, output_dir, cover_dir, image_dir, config):
        super().__init__()
        self.txt_dir = txt_dir
        self.output_dir = output_dir
        self.cover_dir = cover_dir
        self.image_dir = image_dir
        self.config = config

    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)

            # 扫描txt文件
            txt_files = []
            for f in sorted(os.listdir(self.txt_dir), key=lambda x: os.path.getctime(os.path.join(self.txt_dir, x))):
                if f.lower().endswith('.txt'):
                    txt_files.append(os.path.join(self.txt_dir, f))

            if not txt_files:
                self.finished.emit(False, "目录下没有txt文件")
                return

            self.log_updated.emit(f"扫描到 {len(txt_files)} 个txt文件")

            # 扫描封面和插图
            cover_images = self._scan_images(self.cover_dir, vertical_only=True)
            illustration_images = self._scan_images(self.image_dir)
            self.log_updated.emit(f"可用封面(竖屏): {len(cover_images)} 张, 可用插图: {len(illustration_images)} 张")

            # 分组
            merge_count = self.config.get("merge_count", 3)
            groups = []
            for i in range(0, len(txt_files), merge_count):
                groups.append(txt_files[i:i + merge_count])

            total_groups = len(groups)
            self.log_updated.emit(f"共 {total_groups} 个EPUB待生成（每 {merge_count} 个txt合并）")

            success_count = 0
            fail_count = 0

            for gi, group in enumerate(groups):
                self.progress_updated.emit(int(5 + 90 * gi / total_groups),
                                           f"生成第 {gi + 1}/{total_groups} 个EPUB...")

                # 生成文件名
                group_names = [os.path.splitext(os.path.basename(f))[0] for f in group]
                if self.config.get("use_custom_filename") and self.config.get("custom_filename"):
                    template = self.config["custom_filename"]
                    timestamp = datetime.now().strftime('%Y%m%d')
                    book_title = template.replace("{index}", str(gi + 1)).replace("{timestamp}", timestamp)
                else:
                    book_title = "·".join(group_names)

                epub_filename = f"{book_title}.epub"
                # 避免重名
                epub_path = os.path.join(self.output_dir, epub_filename)
                counter = 1
                while os.path.exists(epub_path):
                    epub_filename = f"{book_title}_{counter}.epub"
                    epub_path = os.path.join(self.output_dir, epub_filename)
                    counter += 1

                self.log_updated.emit(f"--- 开始生成: {epub_filename} ---")

                # 读取文件
                chapters_data = []
                for file_path in group:
                    try:
                        content = read_file_with_encoding(file_path)
                        chapters_data.append({
                            "path": file_path,
                            "content": content,
                            "length": len(content)
                        })
                        self.log_updated.emit(f"  读取: {os.path.basename(file_path)} ({len(content)} 字符)")
                    except Exception as e:
                        self.log_updated.emit(f"  读取失败 {os.path.basename(file_path)}: {str(e)}")

                if not chapters_data:
                    self.log_updated.emit(f"  跳过（无可用内容）")
                    fail_count += 1
                    continue

                # 处理文本
                processed_chapters = []
                for i, chapter in enumerate(chapters_data):
                    content = chapter["content"]
                    if self.config.get("remove_chapter_marks", False):
                        content = remove_chapter_marks(content)
                    content = process_line_breaks(content)
                    base_title = f"第{i + 1}章 {os.path.splitext(os.path.basename(chapter['path']))[0]}"
                    processed_chapters.append({
                        "base_title": base_title,
                        "content": content,
                        "length": len(content)
                    })

                # 切割章节
                max_size_kb = self.config.get("max_chapter_size", 200)
                max_size_bytes = max_size_kb * 1024
                flat_chapters = []
                for chapter in processed_chapters:
                    subs = split_chapter_by_size(chapter["content"], chapter["base_title"],
                                                 max_size_bytes, self.log_updated.emit)
                    flat_chapters.extend(subs)

                total_length = sum(c["length"] for c in flat_chapters)

                # 分配封面
                cover_path = None
                if cover_images:
                    cover_path = cover_images.pop(0)
                    self.log_updated.emit(f"  封面: {os.path.basename(cover_path)}")

                # 分配插图（每个EPUB最多max_images张）
                max_images = self.config.get("max_images", 800)
                batch_images = []
                if illustration_images:
                    # 按比例取图
                    take_count = min(max_images, len(illustration_images))
                    batch_images = illustration_images[:take_count]
                    illustration_images = illustration_images[take_count:]

                valid_images = [img for img in batch_images if is_valid_image(img)]
                self.log_updated.emit(f"  插图: {len(valid_images)} 张")

                image_allocation = allocate_images(flat_chapters, valid_images, total_length)

                # 生成EPUB
                success = create_epub(
                    flat_chapters, epub_path, cover_path,
                    valid_images, image_allocation, book_title,
                    self.log_updated.emit
                )

                if success:
                    success_count += 1
                    self.log_updated.emit(f"  ✅ 成功: {epub_filename}")
                    # 删除已使用的封面和插图
                    if cover_path and os.path.exists(cover_path):
                        try:
                            os.remove(cover_path)
                            self.log_updated.emit(f"  已删除封面: {os.path.basename(cover_path)}")
                        except Exception as e:
                            self.log_updated.emit(f"  删除封面失败: {e}")
                    for img_path in valid_images:
                        if os.path.exists(img_path):
                            try:
                                os.remove(img_path)
                            except:
                                pass
                    self.log_updated.emit(f"  已删除 {len(valid_images)} 张插图")
                else:
                    fail_count += 1
                    self.log_updated.emit(f"  ❌ 失败: {epub_filename}")

            self.progress_updated.emit(100, "全部完成")
            msg = f"批量转换完成\n成功: {success_count} 个\n失败: {fail_count} 个\n输出目录: {self.output_dir}"
            self.log_updated.emit(msg)
            self.finished.emit(True, msg)

        except Exception as e:
            self.log_updated.emit(f"批量转换出错: {str(e)}")
            self.finished.emit(False, f"转换失败: {str(e)}")

    def _scan_images(self, directory, vertical_only=False):
        """扫描目录下的所有图片文件
        vertical_only: 为True时只返回竖屏图片（高度>宽度），用于封面筛选
        """
        if not directory or not os.path.exists(directory):
            return []
        images = []
        for f in sorted(os.listdir(directory)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                full_path = os.path.join(directory, f)
                if vertical_only:
                    try:
                        from PIL import Image
                        with Image.open(full_path) as img:
                            w, h = img.size
                            if h <= w:
                                continue  # 跳过横屏和正方形图片
                    except:
                        continue  # 无法读取的图片也跳过
                images.append(full_path)
        return images


# ========================== 主窗口 ==========================

class BatchEPubConverter(QMainWindow):
    """批量TXT转EPUB工具"""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.config = self.load_config()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("批量TXT转EPUB工具")
        self.setGeometry(100, 100, 900, 700)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        tab_widget = QTabWidget()

        # ========== 标签页1: 路径配置 ==========
        path_tab = QWidget()
        path_layout = QVBoxLayout(path_tab)

        # txt目录
        txt_group = QGroupBox("TXT文件目录")
        txt_layout = QHBoxLayout()
        self.txt_dir_edit = QLineEdit()
        self.txt_dir_edit.setPlaceholderText("选择包含txt文件的目录")
        self.txt_dir_browse = QPushButton("浏览...")
        self.txt_dir_browse.clicked.connect(self.browse_txt_dir)
        txt_layout.addWidget(self.txt_dir_edit)
        txt_layout.addWidget(self.txt_dir_browse)
        txt_group.setLayout(txt_layout)
        path_layout.addWidget(txt_group)

        # 封面目录
        cover_group = QGroupBox("封面图片目录（使用过的封面自动删除）")
        cover_layout = QHBoxLayout()
        self.cover_dir_edit = QLineEdit()
        self.cover_dir_edit.setPlaceholderText("选择封面图片所在目录")
        self.cover_dir_browse = QPushButton("浏览...")
        self.cover_dir_browse.clicked.connect(self.browse_cover_dir)
        cover_layout.addWidget(self.cover_dir_edit)
        cover_layout.addWidget(self.cover_dir_browse)
        cover_group.setLayout(cover_layout)
        path_layout.addWidget(cover_group)

        # 插图目录
        img_group = QGroupBox("插图图片目录（使用过的插图自动删除）")
        img_layout = QHBoxLayout()
        self.img_dir_edit = QLineEdit()
        self.img_dir_edit.setPlaceholderText("选择插图图片所在目录")
        self.img_dir_browse = QPushButton("浏览...")
        self.img_dir_browse.clicked.connect(self.browse_img_dir)
        img_layout.addWidget(self.img_dir_edit)
        img_layout.addWidget(self.img_dir_browse)
        img_group.setLayout(img_layout)
        path_layout.addWidget(img_group)

        # 输出目录
        out_group = QGroupBox("输出目录")
        out_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("选择EPUB输出目录")
        self.output_dir_browse = QPushButton("浏览...")
        self.output_dir_browse.clicked.connect(self.browse_output_dir)
        out_layout.addWidget(self.output_dir_edit)
        out_layout.addWidget(self.output_dir_browse)
        out_group.setLayout(out_layout)
        path_layout.addWidget(out_group)

        path_layout.addStretch()

        # ========== 标签页2: 转换配置 ==========
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)

        config_form = QFormLayout()

        # 合并数量
        self.merge_count = QSpinBox()
        self.merge_count.setRange(1, 99999)
        self.merge_count.setValue(3)
        config_form.addRow("每N个txt合并为一个EPUB:", self.merge_count)

        # 最大插图数量
        self.max_images = QSpinBox()
        self.max_images.setRange(0, 5000)
        self.max_images.setValue(800)
        config_form.addRow("每个EPUB最大插图数量:", self.max_images)

        # 章节大小
        self.max_chapter_size = QSpinBox()
        self.max_chapter_size.setRange(50, 1000)
        self.max_chapter_size.setValue(200)
        self.max_chapter_size.setSuffix(" KB")
        config_form.addRow("章节最大大小:", self.max_chapter_size)

        # 清除章节标识
        self.remove_chapter_marks = QCheckBox()
        config_form.addRow("清除原有章节标识:", self.remove_chapter_marks)

        # 自定义文件名
        self.use_custom_filename = QCheckBox()
        config_form.addRow("使用自定义文件名:", self.use_custom_filename)

        self.custom_filename = QLineEdit()
        self.custom_filename.setPlaceholderText("支持 {index} 和 {timestamp} 占位符，如：合集_{index}")
        config_form.addRow("文件名模板:", self.custom_filename)

        config_layout.addLayout(config_form)

        # 提示
        tip_label = QLabel("提示：不勾选自定义文件名时，自动用合并的txt文件名以\"·\"拼接作为epub文件名")
        tip_label.setStyleSheet("color: #666; font-size: 12px;")
        tip_label.setWordWrap(True)
        config_layout.addWidget(tip_label)

        config_layout.addStretch()

        # 添加标签页
        tab_widget.addTab(path_tab, "路径配置")
        tab_widget.addTab(config_tab, "转换配置")

        main_layout.addWidget(tab_widget)

        # 文件预览
        preview_group = QGroupBox("TXT文件预览")
        preview_layout = QVBoxLayout()
        self.file_preview = QTextEdit()
        self.file_preview.setReadOnly(True)
        self.file_preview.setMaximumHeight(120)
        preview_layout.addWidget(self.file_preview)

        self.file_count_label = QLabel("共 0 个txt文件，将生成 0 个EPUB")
        preview_layout.addWidget(self.file_count_label)
        preview_group.setLayout(preview_layout)
        main_layout.addWidget(preview_group)

        # 进度和日志
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.status_label = QLabel("就绪")
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(QLabel("转换日志:"))
        main_layout.addWidget(self.log_text)

        # 按钮
        btn_layout = QHBoxLayout()
        self.save_config_btn = QPushButton("保存配置")
        self.save_config_btn.clicked.connect(self.save_config)
        self.convert_btn = QPushButton("开始批量转换")
        self.convert_btn.clicked.connect(self.start_conversion)
        self.convert_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        btn_layout.addWidget(self.save_config_btn)
        btn_layout.addWidget(self.convert_btn)
        main_layout.addLayout(btn_layout)

    # ========== 浏览目录 ==========

    def browse_txt_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择TXT文件目录")
        if d:
            self.txt_dir_edit.setText(d)
            self._update_preview()

    def browse_cover_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择封面图片目录")
        if d:
            self.cover_dir_edit.setText(d)

    def browse_img_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择插图图片目录")
        if d:
            self.img_dir_edit.setText(d)

    def browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.output_dir_edit.setText(d)

    def _update_preview(self):
        """更新文件预览"""
        txt_dir = self.txt_dir_edit.text().strip()
        if not txt_dir or not os.path.isdir(txt_dir):
            self.file_preview.clear()
            self.file_count_label.setText("共 0 个txt文件")
            return

        txt_files = sorted(
            [f for f in os.listdir(txt_dir) if f.lower().endswith('.txt')],
            key=lambda x: os.path.getctime(os.path.join(txt_dir, x))
        )
        merge_count = self.merge_count.value()
        epub_count = (len(txt_files) + merge_count - 1) // merge_count if txt_files else 0

        preview_text = "\n".join(f"  {i + 1}. {f}" for i, f in enumerate(txt_files[:30]))
        if len(txt_files) > 30:
            preview_text += f"\n  ... 还有 {len(txt_files) - 30} 个文件"
        self.file_preview.setPlainText(preview_text)
        self.file_count_label.setText(f"共 {len(txt_files)} 个txt文件，将生成 {epub_count} 个EPUB")

    # ========== 配置 ==========

    def save_config(self):
        """保存配置"""
        try:
            config = {
                "txt_dir": self.txt_dir_edit.text().strip(),
                "cover_dir": self.cover_dir_edit.text().strip(),
                "img_dir": self.img_dir_edit.text().strip(),
                "output_dir": self.output_dir_edit.text().strip(),
                "merge_count": self.merge_count.value(),
                "max_images": self.max_images.value(),
                "max_chapter_size": self.max_chapter_size.value(),
                "remove_chapter_marks": self.remove_chapter_marks.isChecked(),
                "use_custom_filename": self.use_custom_filename.isChecked(),
                "custom_filename": self.custom_filename.text(),
                "last_used": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.log(f"配置已保存到 {CONFIG_PATH}")
            QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"保存配置失败: {str(e)}")

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.txt_dir_edit.setText(config.get("txt_dir", ""))
                self.cover_dir_edit.setText(config.get("cover_dir", ""))
                self.img_dir_edit.setText(config.get("img_dir", ""))
                self.output_dir_edit.setText(config.get("output_dir", ""))
                self.merge_count.setValue(config.get("merge_count", 3))
                self.max_images.setValue(config.get("max_images", 800))
                self.max_chapter_size.setValue(config.get("max_chapter_size", 200))
                self.remove_chapter_marks.setChecked(config.get("remove_chapter_marks", False))
                self.use_custom_filename.setChecked(config.get("use_custom_filename", False))
                self.custom_filename.setText(config.get("custom_filename", ""))
                self.merge_count.valueChanged.connect(lambda: self._update_preview())
                self._update_preview()
                self.log(f"已加载配置 {CONFIG_PATH}")
                return config
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")

        self.merge_count.valueChanged.connect(lambda: self._update_preview())
        return {}

    def log(self, message):
        """日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        self.log_text.moveCursor(self.log_text.textCursor().End)
        logger.info(message)

    # ========== 转换 ==========

    def start_conversion(self):
        """开始批量转换"""
        txt_dir = self.txt_dir_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()
        cover_dir = self.cover_dir_edit.text().strip()
        img_dir = self.img_dir_edit.text().strip()

        if not txt_dir or not os.path.isdir(txt_dir):
            QMessageBox.warning(self, "警告", "请选择有效的TXT文件目录")
            return
        if not output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return

        # 确认
        txt_count = len([f for f in os.listdir(txt_dir) if f.lower().endswith('.txt')])
        if txt_count == 0:
            QMessageBox.warning(self, "警告", "目录下没有txt文件")
            return

        merge_count = self.merge_count.value()
        epub_count = (txt_count + merge_count - 1) // merge_count
        reply = QMessageBox.question(
            self, "确认",
            f"共 {txt_count} 个txt文件，每 {merge_count} 个合并，将生成 {epub_count} 个EPUB。\n"
            f"使用过的封面和插图将被自动删除。\n\n确认开始？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 保存配置
        self.save_config()

        current_config = {
            "merge_count": merge_count,
            "max_images": self.max_images.value(),
            "max_chapter_size": self.max_chapter_size.value(),
            "remove_chapter_marks": self.remove_chapter_marks.isChecked(),
            "use_custom_filename": self.use_custom_filename.isChecked(),
            "custom_filename": self.custom_filename.text()
        }

        self.convert_btn.setEnabled(False)

        self.convert_thread = BatchConvertThread(txt_dir, output_dir, cover_dir, img_dir, current_config)
        self.convert_thread.progress_updated.connect(self.update_progress)
        self.convert_thread.log_updated.connect(self.log)
        self.convert_thread.finished.connect(self.conversion_finished)
        self.convert_thread.start()

    def update_progress(self, value, status):
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def conversion_finished(self, success, message):
        self.convert_btn.setEnabled(True)
        if success:
            output_dir = self.output_dir_edit.text().strip()
            reply = QMessageBox.information(
                self, "完成", f"{message}\n\n是否打开输出目录？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes and output_dir:
                os.startfile(output_dir)
        else:
            QMessageBox.warning(self, "失败", message)


if __name__ == "__main__":
    matplotlib.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
    app = QApplication(sys.argv)
    window = BatchEPubConverter()
    window.show()
    sys.exit(app.exec_())
