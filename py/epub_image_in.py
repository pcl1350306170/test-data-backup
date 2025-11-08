import os
import zipfile
import tempfile
import shutil
import random
import logging
from bs4 import BeautifulSoup
from datetime import datetime

# ========== 配置区域 ==========
epub_path = r"D:\book\epub\妈烟媳全媚诱过球双让咪岸的略体侠世富吟后.epub"
images_dir = r"D:\book\封面"
output_dir = r"D:\book\已处理epub"

os.makedirs(output_dir, exist_ok=True)
output_epub_path = os.path.join(output_dir, os.path.basename(epub_path))

# ========== 日志配置 ==========
log_file = os.path.join(output_dir, f"epub_process_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

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
        log.info(f"合并了 {merged_count} 个段落。")

def insert_images_randomly(soup, image_paths):
    """在段落中随机插入图片（图片直接放在OEBPS目录下）"""
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
        # 图片直接放在OEBPS目录下，引用路径简化为文件名
        img["src"] = os.path.basename(img_path)
        img["style"] = "max-width:100%;height:auto;"
        img_tag.append(img)
        paragraphs[idx].insert_after(img_tag)
        images_used += 1
        log.info(f"在第 {idx+1} 个段落后插入图片：{os.path.basename(img_path)}")

    return images_used

def process_epub(epub_path, images_dir, output_epub_path):
    temp_dir = tempfile.mkdtemp()
    log.info(f"解压 EPUB 文件：{epub_path}")
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    # 收集所有图片
    image_files = [os.path.join(images_dir, f) for f in os.listdir(images_dir)
                   if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    random.shuffle(image_files)
    log.info(f"共加载 {len(image_files)} 张插图资源。")

    html_count = 0
    total_inserted = 0

    # 查找或创建 OEBPS 目录（所有文件都放在这里）
    oebps_dir = os.path.join(temp_dir, "OEBPS")
    os.makedirs(oebps_dir, exist_ok=True)
    log.info(f"使用 OEBPS 目录：{oebps_dir}")

    # 处理所有 HTML/XHTML 文件（仅处理 OEBPS 目录下的）
    for root, dirs, files in os.walk(oebps_dir):  # 直接遍历OEBPS目录
        for file in files:
            if file.lower().endswith((".xhtml", ".html")):
                html_path = os.path.join(root, file)
                html_count += 1
                log.info(f"\n处理文件：{html_path}")

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

                log.info(f"完成文件：{file}，插入 {inserted} 张图片。")

    # 直接将图片复制到 OEBPS 目录下（不创建Images子目录）
    for img in image_files:
        img_filename = os.path.basename(img)
        dest_path = os.path.join(oebps_dir, img_filename)
        # 避免文件名冲突
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(img_filename)
            img_filename = f"{base}_copy{ext}"
            dest_path = os.path.join(oebps_dir, img_filename)
        shutil.copy(img, dest_path)
    log.info(f"已复制 {len(image_files)} 张图片到 EPUB OEBPS 文件夹。")

    # 重新打包 EPUB
    log.info("开始重新打包 EPUB 文件...")
    with zipfile.ZipFile(output_epub_path, "w", zipfile.ZIP_DEFLATED) as new_zip:
        # mimetype 文件要放最前面且不压缩
        mimetype_path = os.path.join(temp_dir, "mimetype")
        if os.path.exists(mimetype_path):
            new_zip.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        # 打包所有文件（重点确保OEBPS目录内容正确）
        for foldername, subfolders, filenames in os.walk(temp_dir):
            for filename in filenames:
                filepath = os.path.join(foldername, filename)
                arcname = os.path.relpath(filepath, temp_dir)
                if arcname == "mimetype":
                    continue
                new_zip.write(filepath, arcname)

    shutil.rmtree(temp_dir)
    log.info(f"\n✅ EPUB 随机插图处理完成！输出文件：{output_epub_path}")
    log.info(f"📄 日志文件已保存：{log_file}")

# ========== 主程序 ==========
if __name__ == "__main__":
    process_epub(epub_path, images_dir, output_epub_path)
