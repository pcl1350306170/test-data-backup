# txt2epub_gui.py
import os
import sys
import json
import shutil
import random
import tempfile
import traceback
from datetime import datetime
from functools import partial
from pathlib import Path
import threading

import chardet
from PIL import Image
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning
import warnings

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# ebooklib
from ebooklib import epub

# -------------------------
# 默认配置文件位置
# -------------------------
DEFAULT_CONFIG = {
    "txt_dir": r"D:\book\HH",
    "recursive": True,
    "cover_dir": r"D:\book\封面",
    "fallback_dir": r"H:\IMAGE\V33\AI-去二维",
    "output_dir": r"D:\book\epub-py",
    "max_images": 50,
    "cover_min_size": [800, 1200],
    "image_min_size": [500, 500],
    "sort_by": "ctime",  # or 'name'
    "ignore_case_replace": False,
    "images_source_shuffle": True,
    "insert_mode": "proportional",  # or 'even'
    "replace_json": r"C:\www\test\py\json\novelMapping.json"
}
CONFIG_PATH = "txt2epub_config.json"


# -------------------------
# 工具函数
# -------------------------
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                DEFAULT_CONFIG.update(cfg)
        except Exception:
            print("加载配置失败，使用默认配置。")


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("保存配置失败：", e)


def detect_encoding(file_path, sample=8192):
    try:
        with open(file_path, "rb") as f:
            raw = f.read(sample)
        res = chardet.detect(raw)
        enc = res.get("encoding") or "utf-8"
        return enc
    except Exception:
        return "utf-8"


# 清除章节标识的简单正则 / 处理
import re
CHAPTER_PATTERNS = [
    r'^\s*第[一二三四五六七八九十零百千]+\s*章[\s\S]*',  # "第一章 ..." 前缀
    r'^\s*第\s*\d+\s*章[\s\S]*',
    r'^\s*\d+\.\s*',  # 1. ...
    r'^\s*【.+】',  # 【章节名】
    r'^\s*第[0-9一二三四五六七八九十]+\s*节',  # 节
]


def strip_chapter_headers(text):
    # 逐行判断，若行匹配章标题模式则删除该行
    lines = text.splitlines()
    new_lines = []
    for ln in lines:
        s = ln.strip()
        remove = False
        for pat in CHAPTER_PATTERNS:
            if re.match(pat, s):
                remove = True
                break
        if not remove:
            new_lines.append(ln)
    return "\n".join(new_lines)


# 合并乱换行
def merge_lines(text):
    lines = text.splitlines()
    out = []
    zh_punct = set(list("。！？；：”“’》】）】」、"))  # treat punctuation
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line == "":
            # collapse consecutive blank lines to single blank line
            out.append("")
            while i + 1 < len(lines) and lines[i + 1].strip() == "":
                i += 1
            i += 1
            continue
        # if current line does not end with punctuation and next line is normal, merge
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if line and (line[-1] not in zh_punct) and nxt:
                # merge with a space
                merged = line + " " + nxt
                lines[i + 1] = merged
                i += 1
                continue
        out.append(line)
        i += 1
    # remove trailing blanks
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def read_txt_file(path, log_func=None):
    try:
        enc = detect_encoding(path)
        with open(path, "r", encoding=enc, errors="replace") as f:
            content = f.read()
        return content, enc
    except Exception as e:
        if log_func:
            log_func(f"读取失败: {path} -> {e}")
        return None, None


def load_replace_rules(json_path, ignore_case=False):
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # ensure list of (old, new) pairs sorted by length desc
        pairs = []
        for k, v in data.items():
            pairs.append((k, v))
        pairs.sort(key=lambda x: -len(x[0]))
        if ignore_case:
            # return lambda or tuple that performs case-insensitive replacing
            return pairs, True
        return pairs, False
    except Exception as e:
        print("加载替换规则失败：", e)
        return [], False


def apply_replacements(text, pairs, ignore_case=False):
    if not pairs:
        return text, 0
    count = 0
    if ignore_case:
        # replace case-insensitive: using re with flags
        for old, new in pairs:
            pattern = re.compile(re.escape(old), flags=re.IGNORECASE)
            text, n = pattern.subn(new, text)
            count += n
    else:
        for old, new in pairs:
            if old in text:
                text = text.replace(old, new)
                # approximate count: number of replacements
                count += text.count(new)  # not accurate but okay
    return text, count


def find_images_from_dir(primary_dir, fallback_dir, cfg, log_func=None):
    # scan primary dir for images, filter by size thresholds
    def scan_dir(d, min_w, min_h):
        imgs = []
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    p = os.path.join(root, fn)
                    try:
                        with Image.open(p) as im:
                            w, h = im.size
                        if w >= min_w and h >= min_h:
                            imgs.append(p)
                    except Exception:
                        continue
        return imgs

    cover_imgs = []
    insert_imgs = []
    # primary cover dir
    if os.path.isdir(primary_dir):
        cover_imgs = scan_dir(primary_dir, cfg["cover_min_size"][0], cfg["cover_min_size"][1])
        insert_imgs = scan_dir(primary_dir, cfg["image_min_size"][0], cfg["image_min_size"][1])
    # fallback if not found
    if (not cover_imgs) and os.path.isdir(fallback_dir):
        # scan fallback entire tree quickly
        imgs = scan_dir(fallback_dir, cfg["image_min_size"][0], cfg["image_min_size"][1])
        # deduplicate
        imgs = list(dict.fromkeys(imgs))
        random.shuffle(imgs)
        # use first as cover candidate
        if imgs:
            cover_imgs.append(imgs[0])
        insert_imgs.extend(imgs[1:cfg["max_images"]+1])
    else:
        # we might fill insert_imgs from fallback if not enough
        if len(insert_imgs) < cfg["max_images"] and os.path.isdir(fallback_dir):
            more = scan_dir(fallback_dir, cfg["image_min_size"][0], cfg["image_min_size"][1])
            for m in more:
                if m not in insert_imgs:
                    insert_imgs.append(m)
                    if len(insert_imgs) >= cfg["max_images"]:
                        break
    # ensure uniqueness and limit
    insert_imgs = list(dict.fromkeys(insert_imgs))[:cfg["max_images"]]
    if cfg.get("images_source_shuffle", True):
        random.shuffle(insert_imgs)
    return cover_imgs, insert_imgs


# -------------------------
# EPUB 构造函数
# -------------------------
def build_epub_book(title_str, author, chapters, cover_path, images_paths, cfg, log_func=None, progress_callback=None):
    """
    chapters: list of tuples (chapter_title, chapter_html_content)
    images_paths: list of image absolute paths to embed in book (<=100)
    """
    book = epub.EpubBook()
    book.set_identifier(f"book-{random.randint(100000,999999)}")
    book.set_title(title_str)
    book.set_language("zh-CN")
    book.add_author(author or "unknown")

    # add cover
    if cover_path and os.path.exists(cover_path):
        try:
            with open(cover_path, "rb") as f:
                cover_bytes = f.read()
            book.set_cover(os.path.basename(cover_path), cover_bytes)
            if log_func:
                log_func(f"封面已添加: {cover_path}")
        except Exception as e:
            if log_func: log_func(f"添加封面失败: {e}")

    # add images into book and remember name mapping
    image_items = {}
    for idx, imgp in enumerate(images_paths):
        try:
            with open(imgp, "rb") as f:
                data = f.read()
            imgname = f"img_{idx+1:03d}{Path(imgp).suffix.lower()}"
            item = epub.EpubItem(uid=imgname, file_name=imgname, media_type=f"image/{Path(imgp).suffix.lower().lstrip('.')}", content=data)
            book.add_item(item)
            image_items[imgp] = imgname
            if log_func: log_func(f"嵌入图片：{imgp} -> {imgname}")
        except Exception as e:
            if log_func: log_func(f"嵌入图片失败：{imgp} -> {e}")
        if progress_callback:
            progress_callback(idx+1, len(images_paths))

    # create chapters
    epub_chapters = []
    for i, (title, html_content) in enumerate(chapters, start=1):
        c = epub.EpubHtml(title=title, file_name=f"chap_{i:03d}.xhtml", lang='zh-CN')
        # Ensure the inserted images reference the new filenames (image_items mapping)
        # We assume html_content uses src="./Images/...." or "./..." absolute path; we replace by imgname mapping
        soup = BeautifulSoup(html_content, "lxml")
        for img_tag in soup.find_all("img"):
            src = img_tag.get("src", "")
            # try to map by basename to image_items key
            bn = os.path.basename(src)
            # find image_items value with same basename
            mapped = None
            for p, nm in image_items.items():
                if os.path.basename(p) == bn:
                    mapped = nm
                    break
            if mapped:
                img_tag['src'] = mapped
            else:
                # leave as-is; reader may still try to load but likely missing
                pass
        c.content = str(soup)
        book.add_item(c)
        epub_chapters.append(c)

    # Define Table Of Contents and spine
    book.toc = tuple(epub_chapters)
    book.spine = ['nav'] + epub_chapters
    # add default NCX and Nav files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # add CSS minimal
    style = 'body { font-family: serif; line-height: 1.6; } img { max-width: 100%; height: auto; display:block; margin:0.6em auto; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/style.css", media_type="text/css", content=style)
    book.add_item(nav_css)

    # write to temp file handled by caller
    return book


# -------------------------
# 文本 -> HTML 处理函数
# -------------------------
def txt_to_html_chapters(file_paths, cfg, rules_pairs, ignore_case, log_func=None):
    """
    Reads files, cleans, applies replacements, returns list of (title, html_content)
    file_paths: list of absolute txt paths in the order of chapters
    """
    chapters = []
    total_replace_count = 0
    for idx, fp in enumerate(file_paths, start=1):
        basename = os.path.splitext(os.path.basename(fp))[0]
        title = f"第{idx}章 {basename}"

        text, enc = read_txt_file(fp, log_func=log_func)
        if text is None:
            if log_func:
                log_func(f"跳过无法读取文件：{fp}")
            continue
        # strip chapter headers
        text = strip_chapter_headers(text)
        # merge lines
        text = merge_lines(text)
        # collapse multiple blank lines
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        # apply replacements
        replaced_text, cnt = apply_replacements(text, rules_pairs, ignore_case)
        total_replace_count += cnt

        # wrap into simple xhtml body paragraphs
        # Escape & maybe handled by BeautifulSoup below
        paragraphs = []
        for p in replaced_text.split("\n\n"):
            p = p.strip()
            if not p:
                continue
            paragraphs.append(f"<p>{p}</p>")

        body_html = "<body>\n" + "\n".join(paragraphs) + "\n</body>"
        # compose full xhtml with header minimal
        xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
<meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8" />
<title>{title}</title>
<link rel="stylesheet" href="style/style.css" type="text/css"/>
</head>
{body_html}
</html>
'''
        chapters.append((title, xhtml))
        if log_func:
            log_func(f"章节生成：{title} (文件：{fp}) 编码：{enc} 段落：{len(paragraphs)}")
    return chapters, total_replace_count


# -------------------------
# GUI Implementation
# -------------------------
class Txt2EpubGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TXT -> EPUB 转换器 (GUI)")
        self.cfg = DEFAULT_CONFIG.copy()
        load_config()
        self.cfg.update(DEFAULT_CONFIG)
        # load config file if exists
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.cfg.update(json.load(f))
            except:
                pass

        self.txt_files = []  # list of (path, checked)
        self.images_cover = []
        self.images_insert = []

        # GUI layout
        self.create_widgets()
        self.log("程序启动")
        self.update_file_list()

    def create_widgets(self):
        # Left: file selection and list
        left = ttk.Frame(self.root, padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(left, text="TXT 源目录:").pack(anchor=tk.W)
        frame_dir = ttk.Frame(left)
        frame_dir.pack(fill=tk.X)
        self.entry_txt_dir = ttk.Entry(frame_dir)
        self.entry_txt_dir.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry_txt_dir.insert(0, self.cfg.get("txt_dir", ""))
        ttk.Button(frame_dir, text="选择", command=self.choose_txt_dir).pack(side=tk.LEFT)

        self.recursive_var = tk.BooleanVar(value=self.cfg.get("recursive", True))
        ttk.Checkbutton(left, text="递归子目录", variable=self.recursive_var, command=self.update_file_list).pack(anchor=tk.W)

        # file listbox with checkboxes - simulate with treeview
        ttk.Label(left, text="TXT 文件 (可选/调整顺序):").pack(anchor=tk.W, pady=(8,0))
        self.tree_files = ttk.Treeview(left, columns=("path", "ctime"), show="headings", selectmode="browse", height=18)
        self.tree_files.heading("path", text="文件路径")
        self.tree_files.heading("ctime", text="创建时间")
        self.tree_files.pack(fill=tk.BOTH, expand=True)
        btnf = ttk.Frame(left)
        btnf.pack(fill=tk.X)
        ttk.Button(btnf, text="上移", command=self.move_file_up).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(btnf, text="下移", command=self.move_file_down).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(btnf, text="刷新列表", command=self.update_file_list).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Middle: image & cover config
        mid = ttk.Frame(self.root, padding=8)
        mid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(mid, text="封面目录 (优先):").grid(row=0, column=0, sticky=tk.W)
        self.entry_cover_dir = ttk.Entry(mid)
        self.entry_cover_dir.grid(row=0, column=1, sticky=tk.EW)
        self.entry_cover_dir.insert(0, self.cfg.get("cover_dir", ""))
        ttk.Button(mid, text="选择", command=self.choose_cover_dir).grid(row=0, column=2)

        ttk.Label(mid, text="备用图片目录:").grid(row=1, column=0, sticky=tk.W)
        self.entry_fallback = ttk.Entry(mid)
        self.entry_fallback.grid(row=1, column=1, sticky=tk.EW)
        self.entry_fallback.insert(0, self.cfg.get("fallback_dir", ""))
        ttk.Button(mid, text="选择", command=self.choose_fallback_dir).grid(row=1, column=2)

        mid.columnconfigure(1, weight=1)

        # image options
        img_opt_frame = ttk.LabelFrame(mid, text="插图配置", padding=6)
        img_opt_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=6)
        ttk.Label(img_opt_frame, text="插图最大数量:").grid(row=0, column=0, sticky=tk.W)
        self.max_images_var = tk.IntVar(value=self.cfg.get("max_images", 50))
        ttk.Entry(img_opt_frame, textvariable=self.max_images_var, width=6).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(img_opt_frame, text="封面最小尺寸 (W x H)").grid(row=1, column=0, sticky=tk.W)
        self.cover_w_var = tk.IntVar(value=self.cfg.get("cover_min_size", [800,1200])[0])
        self.cover_h_var = tk.IntVar(value=self.cfg.get("cover_min_size", [800,1200])[1])
        ttk.Entry(img_opt_frame, textvariable=self.cover_w_var, width=6).grid(row=1, column=1, sticky=tk.W)
        ttk.Entry(img_opt_frame, textvariable=self.cover_h_var, width=6).grid(row=1, column=2, sticky=tk.W)

        ttk.Label(img_opt_frame, text="插图最小尺寸 (W x H)").grid(row=2, column=0, sticky=tk.W)
        self.img_w_var = tk.IntVar(value=self.cfg.get("image_min_size", [500,500])[0])
        self.img_h_var = tk.IntVar(value=self.cfg.get("image_min_size", [500,500])[1])
        ttk.Entry(img_opt_frame, textvariable=self.img_w_var, width=6).grid(row=2, column=1, sticky=tk.W)
        ttk.Entry(img_opt_frame, textvariable=self.img_h_var, width=6).grid(row=2, column=2, sticky=tk.W)

        ttk.Label(img_opt_frame, text="插图分配方式:").grid(row=3, column=0, sticky=tk.W)
        self.insert_mode_var = tk.StringVar(value=self.cfg.get("insert_mode", "proportional"))
        ttk.Radiobutton(img_opt_frame, text="按章节长度分配", variable=self.insert_mode_var, value="proportional").grid(row=3, column=1, sticky=tk.W)
        ttk.Radiobutton(img_opt_frame, text="均匀分布", variable=self.insert_mode_var, value="even").grid(row=3, column=2, sticky=tk.W)

        # Text processing config
        text_opt_frame = ttk.LabelFrame(mid, text="文本处理与替换", padding=6)
        text_opt_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=6)
        ttk.Button(text_opt_frame, text="加载替换规则 (novelMapping.json)", command=self.select_replace_json).grid(row=0, column=0, sticky=tk.W)
        self.replace_path_var = tk.StringVar(value=self.cfg.get("replace_json", ""))
        ttk.Entry(text_opt_frame, textvariable=self.replace_path_var).grid(row=0, column=1, sticky=tk.EW)
        self.ignore_case_var = tk.BooleanVar(value=self.cfg.get("ignore_case_replace", False))
        ttk.Checkbutton(text_opt_frame, text="忽略替换大小写", variable=self.ignore_case_var).grid(row=1, column=0, sticky=tk.W)
        self.sort_by_var = tk.StringVar(value=self.cfg.get("sort_by", "ctime"))
        ttk.Radiobutton(text_opt_frame, text="按创建时间排序", variable=self.sort_by_var, value="ctime").grid(row=1, column=1, sticky=tk.W)
        ttk.Radiobutton(text_opt_frame, text="按字母顺序排序", variable=self.sort_by_var, value="name").grid(row=1, column=2, sticky=tk.W)
        text_opt_frame.columnconfigure(1, weight=1)

        # Output config
        out_frame = ttk.LabelFrame(mid, text="输出配置", padding=6)
        out_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=6)
        ttk.Label(out_frame, text="输出目录:").grid(row=0, column=0, sticky=tk.W)
        self.out_entry = ttk.Entry(out_frame)
        self.out_entry.grid(row=0, column=1, sticky=tk.EW)
        self.out_entry.insert(0, self.cfg.get("output_dir", ""))
        ttk.Button(out_frame, text="选择", command=self.choose_output_dir).grid(row=0, column=2)
        self.overwrite_var = tk.StringVar(value="auto")
        ttk.Radiobutton(out_frame, text="自动加序号", variable=self.overwrite_var, value="auto").grid(row=1, column=0, sticky=tk.W)
        ttk.Radiobutton(out_frame, text="覆盖已存在", variable=self.overwrite_var, value="overwrite").grid(row=1, column=1, sticky=tk.W)

        # Controls bottom: preview, start
        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(bottom, text="预览选中TXT（处理后）", command=self.preview_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="开始转换", command=self.start_conversion).pack(side=tk.LEFT, padx=4)

        # progress and log panel on right
        right = ttk.Frame(self.root, padding=8)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        ttk.Label(right, text="进度与日志").pack(anchor=tk.W)
        self.progress = ttk.Progressbar(right, mode="determinate")
        self.progress.pack(fill=tk.X, pady=6)
        self.log_text = tk.Text(right, height=30)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # -------------------------
    # GUI actions
    # -------------------------
    def log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.root.update()

    def choose_txt_dir(self):
        d = filedialog.askdirectory(title="选择TXT源目录", initialdir=self.entry_txt_dir.get() or ".")
        if d:
            self.entry_txt_dir.delete(0, tk.END)
            self.entry_txt_dir.insert(0, d)
            self.update_file_list()

    def choose_cover_dir(self):
        d = filedialog.askdirectory(title="选择封面目录", initialdir=self.entry_cover_dir.get() or ".")
        if d:
            self.entry_cover_dir.delete(0, tk.END)
            self.entry_cover_dir.insert(0, d)

    def choose_fallback_dir(self):
        d = filedialog.askdirectory(title="选择备用图片目录", initialdir=self.entry_fallback.get() or ".")
        if d:
            self.entry_fallback.delete(0, tk.END)
            self.entry_fallback.insert(0, d)

    def choose_output_dir(self):
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.out_entry.get() or ".")
        if d:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, d)

    def select_replace_json(self):
        p = filedialog.askopenfilename(title="选择novelMapping.json", filetypes=[("JSON", "*.json")])
        if p:
            self.replace_path_var.set(p)

    def update_file_list(self):
        txt_dir = self.entry_txt_dir.get().strip()
        recursive = self.recursive_var.get()
        self.tree_files.delete(*self.tree_files.get_children())
        self.txt_files.clear()
        if not txt_dir or not os.path.isdir(txt_dir):
            self.log("TXT目录无效")
            return
        files = []
        for root, _, fnames in os.walk(txt_dir):
            for fn in fnames:
                if fn.startswith("."):
                    continue
                if fn.lower().endswith(".txt"):
                    p = os.path.join(root, fn)
                    st = os.stat(p)
                    files.append((p, st.st_ctime))
            if not recursive:
                break
        sort_by = self.sort_by_var.get()
        if sort_by == "ctime":
            files.sort(key=lambda x: x[1])
        else:
            files.sort(key=lambda x: os.path.basename(x[0]).lower())
        for p, ctime in files:
            short = os.path.relpath(p, txt_dir)
            self.tree_files.insert("", tk.END, values=(short, datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")))
            self.txt_files.append(p)
        self.log(f"已扫描到 {len(self.txt_files)} 个TXT文件")

    def move_file_up(self):
        sel = self.tree_files.selection()
        if not sel:
            return
        idx = self.tree_files.index(sel[0])
        if idx <= 0:
            return
        vals = self.tree_files.item(sel[0], "values")
        prev = self.tree_files.get_children()[idx-1]
        prev_vals = self.tree_files.item(prev, "values")
        # swap treeview
        self.tree_files.item(prev, values=vals)
        self.tree_files.item(sel[0], values=prev_vals)
        # swap underlying list
        self.txt_files[idx], self.txt_files[idx-1] = self.txt_files[idx-1], self.txt_files[idx]
        self.log("已上移文件")

    def move_file_down(self):
        sel = self.tree_files.selection()
        if not sel:
            return
        idx = self.tree_files.index(sel[0])
        count = len(self.tree_files.get_children())
        if idx >= count-1:
            return
        vals = self.tree_files.item(sel[0], "values")
        next_item = self.tree_files.get_children()[idx+1]
        next_vals = self.tree_files.item(next_item, "values")
        self.tree_files.item(next_item, values=vals)
        self.tree_files.item(sel[0], values=next_vals)
        self.txt_files[idx], self.txt_files[idx+1] = self.txt_files[idx+1], self.txt_files[idx]
        self.log("已下移文件")

    def preview_selected(self):
        sel = self.tree_files.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个 TXT 文件以预览")
            return
        idx = self.tree_files.index(sel[0])
        path = self.txt_files[idx]
        content, enc = read_txt_file(path)
        if content is None:
            messagebox.showerror("错误", "读取失败")
            return
        text = strip_chapter_headers(content)
        text = merge_lines(text)
        pairs, ignore_case = load_replace_rules(self.replace_path_var.get() or "", self.ignore_case_var.get())
        text, cnt = apply_replacements(text, pairs, ignore_case)
        # show in a simple toplevel window
        win = tk.Toplevel(self.root)
        win.title("预览 - " + os.path.basename(path))
        txt = tk.Text(win, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert(tk.END, text[:20000])  # show first 20k chars
        self.log(f"预览已生成 (替换 {cnt} 次)")

    def start_conversion(self):
        # collect parameters and run in a thread
        self.cfg.update({
            "txt_dir": self.entry_txt_dir.get().strip(),
            "recursive": self.recursive_var.get(),
            "cover_dir": self.entry_cover_dir.get().strip(),
            "fallback_dir": self.entry_fallback.get().strip(),
            "output_dir": self.out_entry.get().strip(),
            "max_images": int(self.max_images_var.get()),
            "cover_min_size": [int(self.cover_w_var.get()), int(self.cover_h_var.get())],
            "image_min_size": [int(self.img_w_var.get()), int(self.img_h_var.get())],
            "insert_mode": self.insert_mode_var.get(),
            "replace_json": self.replace_path_var.get(),
            "ignore_case_replace": self.ignore_case_var.get(),
            "sort_by": self.sort_by_var.get(),
            "images_source_shuffle": True
        })
        save_config(self.cfg)
        t = threading.Thread(target=self.run_conversion, daemon=True)
        t.start()

    def run_conversion(self):
        try:
            # prepare
            txt_list = list(self.txt_files)
            if not txt_list:
                self.log("没有TXT文件，停止")
                return
            self.progress['value'] = 0
            self.progress['maximum'] = len(txt_list) + 10

            # load replace rules
            pairs, ignore_case = load_replace_rules(self.cfg.get("replace_json", ""), self.cfg.get("ignore_case_replace", False))
            if pairs:
                self.log(f"已加载 {len(pairs)} 条替换规则")
            else:
                self.log("未加载替换规则或规则为空")

            # find images
            cover_candidates, insert_candidates = find_images_from_dir(self.cfg.get("cover_dir", ""), self.cfg.get("fallback_dir", ""), self.cfg, log_func=self.log)
            if not cover_candidates and not insert_candidates:
                self.log("没有找到可用图片，继续生成EPUB但没有封面与插图")
            # pick cover
            cover_path = None
            if cover_candidates:
                cover_path = cover_candidates[0]
                self.log(f"选用封面: {cover_path}")
            elif insert_candidates:
                cover_path = insert_candidates[0]
                self.log(f"备用图片选用封面: {cover_path}")

            images_to_use = insert_candidates[:self.cfg.get("max_images", 50)]

            # convert texts to html
            self.log("开始处理TXT文本为章节...")
            chapters, total_replacements = txt_to_html_chapters(txt_list, self.cfg, pairs, ignore_case, log_func=self.log)
            self.log(f"文本处理完成，生成 {len(chapters)} 章节, 替换总计 {total_replacements} 次")
            self.progress['value'] += len(txt_list)

            # distribute images among chapters
            if images_to_use:
                # compute per-chapter counts
                ch_count = len(chapters)
                if ch_count == 0:
                    self.log("没有章节，停止")
                    return
                if self.cfg.get("insert_mode") == "even":
                    per_ch = max(1, len(images_to_use) // ch_count)
                    alloc = [per_ch] * ch_count
                else:
                    # proportional by text length (# chars)
                    lengths = [len(BeautifulSoup(html, "lxml", features="xml").get_text()) for (_, html) in chapters]
                    total_len = sum(lengths) or 1
                    alloc = [max(1, int(len(images_to_use) * (l / total_len))) for l in lengths]
                # adjust to not exceed available images
                s = sum(alloc)
                if s > len(images_to_use):
                    # trim by reducing from largest allocations
                    while s > len(images_to_use):
                        idx_max = alloc.index(max(alloc))
                        alloc[idx_max] -= 1
                        s -= 1
                # assign images slices
                idx_img = 0
                new_chapters = []
                for i, (title, html) in enumerate(chapters):
                    cnt = alloc[i]
                    imgs = images_to_use[idx_img: idx_img + cnt]
                    idx_img += cnt
                    # insert imgs randomly into html avoiding first/last 3 paragraphs
                    soup = BeautifulSoup(html, "lxml", features="xml")
                    paragraphs = soup.find_all("p")
                    if paragraphs:
                        safe_positions = list(range(3, max(3, len(paragraphs)-3)))
                        if not safe_positions:
                            safe_positions = list(range(len(paragraphs)))
                        # pick positions evenly
                        positions = []
                        if cnt >= len(safe_positions):
                            positions = safe_positions
                        else:
                            step = max(1, len(safe_positions) // cnt)
                            for k in range(cnt):
                                pos = safe_positions[min(k*step, len(safe_positions)-1)]
                                positions.append(pos)
                        for j, imgp in enumerate(imgs):
                            pos = positions[j % len(positions)]
                            div = soup.new_tag("div")
                            div['style'] = "text-align:center;margin:1em 0;"
                            tag = soup.new_tag("img", src=f"./{os.path.basename(imgp)}", alt="插图", style="max-width:100%;height:auto;")
                            div.append(tag)
                            paragraphs[pos].insert_after(div)
                            self.log(f"章节[{title}] 插入图片 {os.path.basename(imgp)} at para {pos}")
                    new_chapters.append((title, str(soup)))
                chapters = new_chapters

            # create epub
            book_title = os.path.basename(self.cfg.get("txt_dir", "book_dir"))
            dt = datetime.now().strftime("%Y%m%d")
            fname_base = f"{book_title}_{dt}"
            outdir = self.out_entry.get().strip() or self.cfg.get("output_dir", "")
            os.makedirs(outdir, exist_ok=True)
            outpath = os.path.join(outdir, fname_base + ".epub")
            # handle name collision
            if os.path.exists(outpath) and self.overwrite_var.get() == "auto":
                i = 1
                while os.path.exists(os.path.join(outdir, f"{fname_base}_{i}.epub")):
                    i += 1
                outpath = os.path.join(outdir, f"{fname_base}_{i}.epub")
            if os.path.exists(outpath) and self.overwrite_var.get() == "overwrite":
                pass

            # build book
            self.log("开始构建 EPUB ...")
            # progress callback for images embedding (dummy)
            def prog_cb(cur, total):
                self.progress['value'] = min(self.progress['maximum'], self.progress['value'] + 1)
                self.root.update()

            book = build_epub_book(book_title, "unknown", chapters, cover_path, images_to_use, self.cfg, log_func=self.log, progress_callback=prog_cb)
            # write file
            epub.write_epub(outpath, book)
            self.log(f"EPUB 已保存：{outpath}")

            # write log file
            logpath = os.path.join(outdir, f"txt2epub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            with open(logpath, "w", encoding="utf-8") as lf:
                lf.write(self.log_text.get("1.0", tk.END))
            self.log(f"日志已保存：{logpath}")

            self.progress['value'] = self.progress['maximum']
            messagebox.showinfo("完成", f"EPUB 生成完成：\n{outpath}\n日志：{logpath}")
        except Exception as e:
            traceback_str = traceback.format_exc()
            self.log("错误: " + str(e))
            self.log(traceback_str)
            messagebox.showerror("错误", str(e))


# -------------------------
# 运行主程序
# -------------------------
def main():
    load_config()
    root = tk.Tk()
    root.geometry("1200x800")
    app = Txt2EpubGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
