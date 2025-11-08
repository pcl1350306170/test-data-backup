import os
import zipfile
import tempfile
import shutil
import random
import logging
import json
import uuid
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

# ========== 配置区域 ==========
A_DIR = r"D:\book\HH"  # TXT文件目录
COVER_DIR = r"D:\book\封面"  # 封面图片目录
OUTPUT_DIR = r"D:\book\epub-py"  # EPUB输出目录
JSON_PATH = r"C:\www\test\py\json\novelMapping.json"  # 替换规则JSON文件

# 创建输出目录
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ========== 日志配置 ==========
log_file = os.path.join(OUTPUT_DIR, f"txt2epub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ========== 工具函数 (保留epub_image_in.py中的核心功能) ==========
def is_chinese_punctuation(char):
    """判断是否是中文标点结尾"""
    return char in "。！？；：”“’》】）」"

def merge_paragraphs(soup):
    """合并未以标点结束的段落（来自epub_image_in.py）"""
    paragraphs = soup.find_all("p")
    merged_count = 0
    i = 0
    while i < len(paragraphs) - 1:
        text = paragraphs[i].get_text().strip()
        if text and not is_chinese_punctuation(text[-1]):
            next_text = paragraphs[i + 1].get_text().strip()
            paragraphs[i].string = text + " " + next_text
            paragraphs[i + 1].decompose()
            paragraphs = soup.find_all("p")  # 重新获取段落列表
            merged_count += 1
            continue
        i += 1
    if merged_count > 0:
        log.info(f"合并了 {merged_count} 个段落")
    return soup

def insert_images_randomly(soup, image_paths):
    """在段落中随机插入图片（来自epub_image_in.py）"""
    paragraphs = soup.find_all("p")
    if not paragraphs:
        return 0, soup

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
        log.info(f"在第 {idx+1} 个段落后插入图片：{os.path.basename(img_path)}")

    return images_used, soup

def load_replacement_rules(json_path):
    """加载替换规则"""
    try:
        if not os.path.exists(json_path):
            log.error(f"替换规则文件不存在: {json_path}")
            return {}

        with open(json_path, 'r', encoding='utf-8-sig') as f:  # 使用utf-8-sig处理BOM
            rules = json.load(f)

        # 验证规则格式
        if not isinstance(rules, dict):
            log.error("替换规则必须是JSON对象（键值对）")
            return {}

        log.info(f"成功加载替换规则，共 {len(rules)} 条")
        return rules
    except json.JSONDecodeError as e:
        log.error(f"JSON格式错误: {str(e)}")
        return {}
    except Exception as e:
        log.error(f"加载替换规则失败: {str(e)}")
        return {}

def replace_text(content, rules):
    """根据规则替换文本，确保替换顺序和编码正确"""
    if not rules:
        return content

    # 先替换长字符串，避免短字符串替换影响长字符串
    sorted_rules = sorted(rules.items(), key=lambda x: len(x[0]), reverse=True)

    for old, new in sorted_rules:
        # 确保新旧字符串都是字符串类型
        old_str = str(old)
        new_str = str(new)
        if old_str in content:
            replaced_count = content.count(old_str)
            content = content.replace(old_str, new_str)
            log.debug(f"替换 '{old_str}' 为 '{new_str}'，共 {replaced_count} 处")

    return content

def get_cover_image(cover_dir):
    """获取封面图片，优先选择第一个图片"""
    cover_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    for file in os.listdir(cover_dir):
        if file.lower().endswith(cover_extensions):
            return os.path.join(cover_dir, file)
    return None

def process_txt_content(txt_path, chapter_title, replacement_rules):
    """处理TXT内容：读取、替换、移除原有章节、生成XHTML"""
    # 读取TXT内容
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except UnicodeDecodeError:
        try:
            with open(txt_path, 'r', encoding='gbk') as f:
                text = f.read()
        except UnicodeDecodeError as e:
            log.error(f"无法解码文件 {txt_path}: {str(e)}")
            text = ""

    # 应用文本替换规则
    original_length = len(text)
    text = replace_text(text, replacement_rules)
    if len(text) != original_length:
        log.info(f"文件 {os.path.basename(txt_path)} 替换完成，长度变化: {original_length} -> {len(text)}")

    # 分割段落（简单处理，可根据实际情况优化）
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

    # 创建基本XHTML结构
    xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
    <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=UTF-8"/>
    <title>{chapter_title}</title>
</head>
<body>
    <h2>{chapter_title}</h2>
</body>
</html>"""

    soup = BeautifulSoup(xhtml, "lxml-xml")
    body = soup.find("body")

    # 添加段落
    for para in paragraphs:
        p_tag = soup.new_tag("p")
        p_tag.string = para
        body.append(p_tag)

    # 合并段落（保留epub_image_in.py功能）
    soup = merge_paragraphs(soup)

    return str(soup)

def create_toc(ncx_path, chapters, book_title):
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

def txts_to_epub(txt_files, output_path, cover_dir, image_paths, replacement_rules, book_title):
    """将多个TXT文件合并转换为一个EPUB"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建EPUB目录结构
            oebps_dir = os.path.join(temp_dir, "OEBPS")
            os.makedirs(oebps_dir, exist_ok=True)

            # 处理每个TXT文件作为一个章节
            chapters = []
            for i, txt_path in enumerate(txt_files, 1):
                # 获取章节标题（文件名无扩展名）
                txt_basename = os.path.splitext(os.path.basename(txt_path))[0]
                chapter_title = f"第{i}章 {txt_basename}"
                log.info(f"处理章节：{chapter_title}")

                # 生成章节XHTML内容
                chapter_content = process_txt_content(txt_path, chapter_title, replacement_rules)
                chapter_filename = f"chapter_{i}.xhtml"
                chapter_path = os.path.join(oebps_dir, chapter_filename)

                with open(chapter_path, 'w', encoding='utf-8') as f:
                    f.write(chapter_content)

                # 插入图片（保留epub_image_in.py功能）
                with open(chapter_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), "lxml-xml")

                _, soup = insert_images_randomly(soup, image_paths)

                with open(chapter_path, 'w', encoding='utf-8') as f:
                    f.write(str(soup))

                chapters.append({
                    "title": chapter_title,
                    "filename": chapter_filename
                })

            # 复制图片到OEBPS目录
            for img in image_paths:
                img_filename = os.path.basename(img)
                dest_path = os.path.join(oebps_dir, img_filename)
                # 处理文件名冲突
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(img_filename)
                    img_filename = f"{base}_copy{ext}"
                    dest_path = os.path.join(oebps_dir, img_filename)
                shutil.copy(img, dest_path)

            # 创建封面
            cover_image = get_cover_image(cover_dir)
            cover_filename = None
            if cover_image:
                cover_filename = "cover.jpg"
                shutil.copy(cover_image, os.path.join(oebps_dir, cover_filename))
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

            # 创建目录文件
            toc_path = os.path.join(oebps_dir, "toc.ncx")
            create_toc(toc_path, chapters, book_title)

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
            manifest_items = []
            spine_items = []

            # 添加封面
            if cover_image:
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
            for i, img in enumerate(image_paths):
                img_filename = os.path.basename(img)
                ext = os.path.splitext(img_filename)[1].lower()
                media_type = f"image/{ext[1:]}" if ext[1:] in ['png', 'jpg', 'jpeg', 'gif'] else "image/*"
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

            log.info(f"成功生成EPUB: {output_path}")
            return True
    except Exception as e:
        log.error(f"转换失败: {str(e)}")
        return False

# ========== 主程序 ==========
def main():
    # 加载替换规则
    replacement_rules = load_replacement_rules(JSON_PATH)
    if not replacement_rules:
        log.warning("未加载到任何替换规则，将跳过文本替换步骤")

    # 获取所有图片（限制在100张以内）
    image_extensions = ('.png', '.jpg', '.jpeg', '.gif')
    image_files = [
                      os.path.join(COVER_DIR, f)
                      for f in os.listdir(COVER_DIR)
                      if f.lower().endswith(image_extensions)
                  ][:100]  # 限制最多100张图片
    random.shuffle(image_files)
    log.info(f"加载了 {len(image_files)} 张图片")

    # 获取所有TXT文件
    txt_files = [
        os.path.join(A_DIR, f)
        for f in os.listdir(A_DIR)
        if f.lower().endswith('.txt')
    ]

    if not txt_files:
        log.warning("没有找到TXT文件")
        return

    log.info(f"找到 {len(txt_files)} 个TXT文件，开始转换...")

    # 生成EPUB文件名（使用目录名作为书名）
    book_title = os.path.basename(A_DIR)  # 使用HH作为书名
    epub_name = f"{book_title}.epub"
    epub_path = os.path.join(OUTPUT_DIR, epub_name)

    # 避免覆盖已存在的文件
    counter = 1
    while os.path.exists(epub_path):
        epub_name = f"{book_title}_{counter}.epub"
        epub_path = os.path.join(OUTPUT_DIR, epub_name)
        counter += 1

    # 转换多个TXT为一个EPUB
    txts_to_epub(txt_files, epub_path, COVER_DIR, image_files, replacement_rules, book_title)

    log.info("所有文件处理完成")

if __name__ == "__main__":
    main()
