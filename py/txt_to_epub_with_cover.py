import os
import re
import glob
from ebooklib import epub
from PIL import Image

# ========== 配置区 ==========
TXT_DIR = r"F:\book\HH"        # TXT 目录
COVER_DIR = r"F:\book\封面"      # 封面图片目录
EPUB_DIR = r"F:\book\epub"       # EPUB 输出目录
# ============================


def get_txt_files(directory):
    """获取所有txt文件（含子目录）"""
    return [f for f in glob.glob(os.path.join(directory, "**", "*.txt"), recursive=True)]


def get_cover_images(directory):
    """获取所有封面图片路径"""
    valid_exts = (".jpg", ".jpeg", ".png", ".webp")
    return [os.path.join(directory, f) for f in os.listdir(directory)
            if f.lower().endswith(valid_exts)]


def split_chapters(text):
    """
    按“第x章”分割章节
    返回 [(章节标题, 内容), ...]
    """
    pattern = re.compile(r"(第\d+章[^\n]*)")  # 捕获标题
    parts = pattern.split(text)
    chapters = []

    if len(parts) <= 1:
        # 没有章节标识，整个文件当一章
        return [("正文", text)]

    current_title = "序章"
    buffer = []

    for part in parts:
        if pattern.match(part):
            # 遇到新章节，保存旧章节
            if buffer:
                chapters.append((current_title, "\n".join(buffer)))
                buffer = []
            current_title = part.strip()
        else:
            buffer.append(part.strip())

    if buffer:
        chapters.append((current_title, "\n".join(buffer)))

    return chapters


def txt_to_epub(txt_path, cover_path, output_dir):
    """将TXT转换为EPUB，并添加封面和目录"""
    title = os.path.splitext(os.path.basename(txt_path))[0]
    epub_path = os.path.join(output_dir, f"{title}.epub")

    # 读取文本内容
    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    # 创建EPUB书
    book = epub.EpubBook()
    book.set_identifier(title)
    book.set_title(title)
    book.set_language('zh')
    book.add_author('狂魔')

    # 添加封面
    with open(cover_path, "rb") as img_file:
        cover_data = img_file.read()
    book.set_cover(os.path.basename(cover_path), cover_data)

    # 拆分章节
    chapters = split_chapters(text)
    epub_chapters = []

    for i, (chapter_title, chapter_text) in enumerate(chapters, start=1):
        chapter = epub.EpubHtml(
            title=chapter_title,
            file_name=f"chapter_{i}.xhtml",
            lang="zh"
        )
        content_html = f"<h2>{chapter_title}</h2><p>{chapter_text.replace('\n', '<br/>')}</p>"
        chapter.content = f"<html><body>{content_html}</body></html>"
        book.add_item(chapter)
        epub_chapters.append(chapter)

    # 设置目录（TOC）和阅读顺序（spine）
    book.toc = [(epub.Link(ch.file_name, ch.title, f"chap_{i}")) for i, ch in enumerate(epub_chapters)]
    book.spine = ['nav'] + epub_chapters

    # 添加导航文件
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # 写入文件
    epub.write_epub(epub_path, book)
    print(f"✅ 已生成：{epub_path}")
    return epub_path


def main():
    os.makedirs(EPUB_DIR, exist_ok=True)

    txt_files = get_txt_files(TXT_DIR)
    cover_images = get_cover_images(COVER_DIR)

    if not txt_files:
        print("⚠️ 没有发现TXT文件。")
        return
    if not cover_images:
        print("⚠️ 没有可用的封面图片。")
        return
    if len(cover_images) < len(txt_files):
        print(f"⚠️ 封面数量不足！（TXT数量: {len(txt_files)}，封面: {len(cover_images)}）")
        print("❌ 程序终止，请补充封面图片。")
        return

    for i, txt_path in enumerate(txt_files):
        if i >= len(cover_images):
            print("❌ 封面已用完，程序结束。")
            break

        cover_path = cover_images[i]

        try:
            txt_to_epub(txt_path, cover_path, EPUB_DIR)

            # 删除TXT文件和封面
            os.remove(txt_path)
            os.remove(cover_path)

        except Exception as e:
            print(f"❌ 转换失败：{txt_path} => {e}")

    print("\n🎉 所有任务完成！")


if __name__ == "__main__":
    main()
