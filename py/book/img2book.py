#!/usr/bin/env python3
"""
图片目录转EPUB/PDF工具

使用方式:
  python img2book.py

  1. 点击"浏览..."选择一个包含多个子目录的文件夹
     (每个子目录即为一章, 子目录名 = 章节名, 子目录内图片按文件名排序)
  2. 选择输出格式: EPUB 或 PDF
  3. 选择输出目录(默认在源目录同级自动生成)
  4. 点击"开始转换"
  5. 如果所有图片总大小 > 300MB, 自动按章节拆分为多个文件
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import re
import shutil
import zipfile
import uuid
import threading
import queue
import json
import logging
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    print("=" * 50)
    print("缺少依赖: Pillow")
    print("请运行: pip install Pillow")
    print("=" * 50)
    raise SystemExit(1)

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "img2book"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
MAX_FILE_BYTES = 300 * 1024 * 1024  # 300 MB

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "last_input_dir": "",
    "last_output_dir": "",
    "output_format": "epub"
}


def load_config():
    """加载配置文件"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        logging.error(f"加载配置文件失败: {str(e)}")
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"保存配置文件失败: {str(e)}")
        return False


def human_size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def _natural_key(s):
    """自然排序键: '第2章' 排在 '第10章' 前面"""
    return [
        int(p) if p.isdigit() else p.lower()
        for p in re.split(r"(\d+)", str(s))
    ]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("图片目录 → EPUB / PDF 转换工具")
        root.geometry("780x700")
        root.minsize(640, 540)
        self.chapters: list[dict] = []
        self.busy = False
        self.res_queue: queue.Queue = queue.Queue()
        self._build()
        self._load_config()
        self._poll()

    # ────────────── GUI ──────────────
    def _build(self):
        pad = dict(padx=10, pady=4)

        # --- 输入目录 ---
        f_in = ttk.LabelFrame(self.root, text="输入目录")
        f_in.pack(fill="x", **pad)

        self.var_in = tk.StringVar()
        ttk.Entry(f_in, textvariable=self.var_in, width=68).pack(
            side="left", padx=6, pady=6
        )
        ttk.Button(f_in, text="浏览…", command=self._pick_src).pack(
            side="left", padx=4, pady=6
        )

        # --- 章节预览 ---
        f_tree = ttk.LabelFrame(self.root, text="章节预览")
        f_tree.pack(fill="both", expand=True, **pad)

        cols = ("no", "name", "count", "size")
        self.tree = ttk.Treeview(f_tree, columns=cols, show="headings", height=12)
        for col, hdr, w, anc in [
            ("no", "序号", 45, "center"),
            ("name", "章节名称", 360, "w"),
            ("count", "图片数", 70, "center"),
            ("size", "大小", 85, "e"),
        ]:
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=w, anchor=anc, minwidth=40)

        sb = ttk.Scrollbar(f_tree, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=4)

        # --- 设置 ---
        f_set = ttk.LabelFrame(self.root, text="设置")
        f_set.pack(fill="x", **pad)

        ttk.Label(f_set, text="输出格式:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.var_fmt = tk.StringVar(value="epub")
        for v, t in [("epub", "EPUB"), ("pdf", "PDF")]:
            ttk.Radiobutton(f_set, text=t, variable=self.var_fmt, value=v).grid(
                row=0, column={"epub": 1, "pdf": 2}[v], sticky="w", padx=12
            )

        ttk.Label(f_set, text="输出目录:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.var_out = tk.StringVar()
        ttk.Entry(f_set, textvariable=self.var_out, width=52).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=4
        )
        ttk.Button(f_set, text="浏览…", command=self._pick_out).grid(
            row=1, column=3, padx=4, pady=4
        )
        f_set.columnconfigure(2, weight=1)

        # --- 进度 ---
        f_prog = ttk.LabelFrame(self.root, text="进度")
        f_prog.pack(fill="x", **pad)

        self.prog = ttk.Progressbar(f_prog, length=100, mode="determinate")
        self.prog.pack(fill="x", padx=8, pady=(8, 2))

        self.var_stat = tk.StringVar(value="就绪")
        ttk.Label(f_prog, textvariable=self.var_stat, foreground="gray").pack(
            anchor="w", padx=8, pady=(0, 4)
        )

        # --- 按钮 ---
        f_btn = ttk.Frame(self.root)
        f_btn.pack(fill="x", padx=10, pady=8)

        self.btn_go = ttk.Button(f_btn, text="开始转换", command=self._start)
        self.btn_go.pack(side="right", padx=6)

        self.log = tk.Text(f_btn, height=3, state="disabled", font=("Consolas", 9))
        self.log.pack(side="left", fill="both", expand=True)

    # ────────────── helpers ──────────────
    def _append_log(self, msg: str):
        self.log.config(state="normal")
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _log(self, message: str, level=logging.INFO):
        """同时写入日志文件和界面"""
        logging.log(level, message)
        self._append_log(message)

    def _load_config(self):
        """加载配置并填充UI"""
        self.config = load_config()
        if self.config.get("last_input_dir") and Path(self.config["last_input_dir"]).exists():
            self.var_in.set(self.config["last_input_dir"])
            self._scan(self.config["last_input_dir"])
        if self.config.get("last_output_dir"):
            self.var_out.set(self.config["last_output_dir"])
        if self.config.get("output_format") in ("epub", "pdf"):
            self.var_fmt.set(self.config["output_format"])
        self._append_log("配置已加载")

    def _save_current_config(self):
        """保存当前配置"""
        config = {
            "last_input_dir": self.var_in.get(),
            "last_output_dir": self.var_out.get(),
            "output_format": self.var_fmt.get()
        }
        if save_config(config):
            logging.info("配置已保存")

    def _poll(self):
        """从工作线程取结果, 在主线程更新GUI"""
        while True:
            try:
                kind, data = self.res_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "prog":
                val, stat = data
                self.prog["value"] = val
                self.var_stat.set(stat)
            elif kind == "log":
                self._append_log(data)
            elif kind == "done":
                self.busy = False
                self.btn_go.config(state="normal")
                self.prog["value"] = 100
                self.var_stat.set("完成!")
                self._log(data)
                messagebox.showinfo("完成", data)
            elif kind == "err":
                self.busy = False
                self.btn_go.config(state="normal")
                self.var_stat.set("出错")
                self._log(f"错误: {data}", logging.ERROR)
                messagebox.showerror("错误", data)
        self.root.after(80, self._poll)

    # ────────────── 目录操作 ──────────────
    def _pick_src(self):
        d = filedialog.askdirectory(title="选择图片根目录")
        if not d:
            return
        self.var_in.set(d)
        self.var_out.set(str(Path(d).parent / f"{Path(d).name}_输出"))
        self._scan(d)

    def _pick_out(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.var_out.set(d)

    def _scan(self, root_dir: str):
        self.tree.delete(*self.tree.get_children())
        self.chapters.clear()

        p = Path(root_dir)
        if not p.exists():
            self._log(f"输入目录不存在: {root_dir}", logging.WARNING)
            return

        dirs = sorted(
            [d for d in p.iterdir() if d.is_dir()],
            key=lambda x: _natural_key(x.name),
        )

        idx = 0
        for d in dirs:
            imgs = sorted(
                [f for f in d.iterdir() if f.suffix.lower() in IMG_EXTS],
                key=lambda x: _natural_key(x.name),
            )
            if not imgs:
                continue
            idx += 1
            sz = sum(f.stat().st_size for f in imgs)
            self.chapters.append({"name": d.name, "images": imgs, "size": sz})
            self.tree.insert(
                "", "end", values=(idx, d.name, len(imgs), human_size(sz))
            )

        n_img = sum(len(c["images"]) for c in self.chapters)
        t_sz = sum(c["size"] for c in self.chapters)
        self.var_stat.set(f"共 {len(self.chapters)} 章, {n_img} 张图片, {human_size(t_sz)}")
        self._log(f"扫描完成: {len(self.chapters)} 章, {n_img} 张图片, {human_size(t_sz)}")

    # ────────────── 转换入口 ──────────────
    def _start(self):
        if self.busy:
            return
        if not self.chapters:
            messagebox.showwarning("提示", "请先选择输入目录")
            return
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning("提示", "请指定输出目录")
            return

        # 保存配置
        self._save_current_config()

        Path(out).mkdir(parents=True, exist_ok=True)
        self.busy = True
        self.btn_go.config(state="disabled")
        self.prog["value"] = 0
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

        fmt = self.var_fmt.get()
        self._log(f"开始转换: 格式={fmt.upper()}, 输出={out}")

        threading.Thread(
            target=self._worker,
            args=(list(self.chapters), fmt, out),
            daemon=True,
        ).start()

    # ────────────── 工作线程 ──────────────
    def _worker(self, chapters, fmt, out_dir):
        try:
            total = sum(c["size"] for c in chapters)
            groups = self._split(chapters)

            self.res_queue.put(("log", f"总大小 {human_size(total)}, 分为 {len(groups)} 个文件"))

            for i, group in enumerate(groups):
                tag = f"[{i+1}/{len(groups)}]"
                if fmt == "epub":
                    self._make_epub(group, out_dir, i + 1, len(groups), tag)
                else:
                    self._make_pdf(group, out_dir, i + 1, len(groups), tag)

            self.res_queue.put(("done", f"转换完成!\n共 {len(groups)} 个文件\n输出: {out_dir}"))
        except Exception as e:
            self.res_queue.put(("err", str(e)))

    # ────────────── 拆分策略 ──────────────
    def _split(self, chapters: list[dict]) -> list[list[dict]]:
        """贪心拆分：每组不超过 MAX_FILE_BYTES，不限制组数"""
        total = sum(c["size"] for c in chapters)
        if total <= MAX_FILE_BYTES:
            return [chapters]

        groups, cur_grp, cur_sz = [], [], 0
        for c in chapters:
            # 如果当前章节本身就超过限制，单独成组
            if c["size"] > MAX_FILE_BYTES:
                if cur_grp:
                    groups.append(cur_grp)
                    cur_grp, cur_sz = [], 0
                groups.append([c])
                continue

            if cur_sz + c["size"] > MAX_FILE_BYTES and cur_grp:
                groups.append(cur_grp)
                cur_grp, cur_sz = [], 0
            cur_grp.append(c)
            cur_sz += c["size"]

        if cur_grp:
            groups.append(cur_grp)
        return groups

    # ────────────── EPUB 生成 ──────────────
    def _make_epub(self, chapters, out_dir, pnum, ptotal, tag):
        tmp = Path(out_dir) / f".tmp_epub_{pnum}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()

        # 复制公共文件
        (tmp / "mimetype").write_text("application/epub+zip", encoding="ascii")
        (tmp / "META-INF").mkdir()
        (tmp / "META-INF" / "container.xml").write_text(
            '<?xml version="1.0"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles>\n'
            '    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>\n'
            '  </rootfiles>\n'
            '</container>',
            encoding="utf-8",
        )
        (tmp / "images").mkdir()
        (tmp / "text").mkdir()

        # 封面
        cover = chapters[0]["images"][0]
        ext = cover.suffix.lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(
            ext.lstrip("."), "image/jpeg"
        )
        shutil.copy2(cover, tmp / f"cover{ext}")

        # 逐章处理
        manifest, spine, nav, img_items = [], [], [], set()
        manifest.append('    <item href="cover.xhtml" id="cover_page" media-type="application/xhtml+xml"/>')
        manifest.append(f'    <item href="cover{ext}" id="cover_img" media-type="{mime}"/>')
        spine.append('    <itemref idref="cover_page"/>')

        n_ch = len(chapters)
        for ci, ch in enumerate(chapters):
            self.res_queue.put(
                ("prog", ((ci / n_ch) * 90, f"{tag} EPUB: {ch['name']}"))
            )
            safe = re.sub(r'[^\w\u4e00-\u9fff]', '_', ch["name"])
            html = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" lang="zh">\n'
                "<head>\n"
                f"  <title>{ch['name']}</title>\n"
                '  <style>body{margin:0;padding:0;text-align:center;}'
                "img{max-width:100%;height:auto;}</style>\n"
                "</head>\n<body>\n"
                f'<h2 style="text-align:center;padding:1em;">{ch["name"]}</h2>\n'
            )

            for img_path in ch["images"]:
                img_name = f"ch{ci:03d}_{img_path.name}"
                dest = tmp / "images" / img_name
                if not dest.exists():
                    shutil.copy2(img_path, dest)
                    img_items.add(img_name)

                html += f'<p><img src="../images/{img_name}" alt=""/></p>\n'

            html += "</body>\n</html>"
            xhtml = f"ch{ci:03d}.xhtml"
            (tmp / "text" / xhtml).write_text(html, encoding="utf-8")

            mid = f"ch{ci}"
            manifest.append(f'    <item href="text/{xhtml}" id="{mid}" media-type="application/xhtml+xml"/>')
            spine.append(f'    <itemref idref="{mid}"/>')
            nav.append(
                f'    <navPoint id="nav{ci}" playOrder="{ci+2}">\n'
                f"      <navLabel><text>{ch['name']}</text></navLabel>\n"
                f'      <content src="text/{xhtml}"/>\n'
                f"    </navPoint>"
            )

        # 图片 manifest
        for idx, name in enumerate(sorted(img_items)):
            e = Path(name).suffix.lower().lstrip(".")
            m = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(e, "image/jpeg")
            manifest.append(f'    <item href="images/{name}" id="img{idx}" media-type="{m}"/>')

        manifest.append('    <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>')

        uid = str(uuid.uuid4())
        ch_names = " ~ ".join(c["name"] for c in chapters)
        title = f"图片合集 第{pnum}部分" if ptotal > 1 else "图片合集"

        # content.opf
        (tmp / "content.opf").write_text(
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="2.0">\n'
            f'  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">\n'
            f'    <dc:identifier id="uid" opf:scheme="uuid">{uid}</dc:identifier>\n'
            f"    <dc:title>{title}</dc:title>\n"
            f'    <dc:language>zh</dc:language>\n'
            f'    <meta name="cover" content="cover_img"/>\n'
            f"  </metadata>\n"
            f"  <manifest>\n" + "\n".join(manifest) + "\n  </manifest>\n"
            f'  <spine toc="ncx">\n' + "\n".join(spine) + "\n  </spine>\n"
            f"</package>\n",
            encoding="utf-8",
        )

        # toc.ncx
        (tmp / "toc.ncx").write_text(
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh">\n'
            f"  <head>\n"
            f'    <meta content="{uid}" name="dtb:uid"/>\n'
            f'    <meta content="1" name="dtb:depth"/>\n'
            f"  </head>\n"
            f"  <docTitle><text>{title}</text></docTitle>\n"
            f"  <navMap>\n"
            f'    <navPoint id="nav_cover" playOrder="1">\n'
            f'      <navLabel><text>封面</text></navLabel>\n'
            f'      <content src="cover.xhtml"/>\n'
            f"    </navPoint>\n"
            + "\n".join(nav)
            + "\n  </navMap>\n</ncx>\n",
            encoding="utf-8",
        )

        # 封面页
        (tmp / "cover.xhtml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" lang="zh">\n'
            "<head><title>封面</title></head>\n"
            '<body style="margin:0;text-align:center;">\n'
            f'<img src="cover{ext}" style="max-width:100%;height:auto;"/>\n'
            "</body>\n</html>",
            encoding="utf-8",
        )

        # 打包
        self.res_queue.put(("prog", (92, f"{tag} 打包EPUB…")))
        epub_name = f"output_part{pnum}.epub" if ptotal > 1 else "output.epub"
        epub_path = Path(out_dir) / epub_name

        with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, dirs, files in os.walk(tmp):
                for fn in sorted(files):
                    fp = Path(root) / fn
                    if fp.name == "mimetype":
                        continue
                    zf.write(fp, fp.relative_to(tmp))

        shutil.rmtree(tmp)
        self.res_queue.put(("log", f"{tag} {epub_name} → {human_size(epub_path.stat().st_size)}"))

    # ────────────── PDF 生成 ──────────────
    def _make_pdf(self, chapters, out_dir, pnum, ptotal, tag):
        pdf_name = f"output_part{pnum}.pdf" if ptotal > 1 else "output.pdf"
        pdf_path = Path(out_dir) / pdf_name
        tmp_dir = Path(out_dir) / f".tmp_pdf_{pnum}"
        tmp_dir.mkdir(exist_ok=True)

        first_img = None
        buffer: list[Image.Image] = []
        total_ch = sum(len(c["images"]) for c in chapters)
        done = 0

        for ci, ch in enumerate(chapters):
            self.res_queue.put(
                ("prog", ((done / max(total_ch, 1)) * 90, f"{tag} PDF: {ch['name']}"))
            )
            for img_path in ch["images"]:
                try:
                    im = Image.open(img_path)
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")
                    elif im.mode == "L":
                        im = im.convert("RGB")
                    tmp_jpg = tmp_dir / f"p{done:05d}.jpg"
                    im.save(tmp_jpg, "JPEG", quality=85)
                    im.close()

                    page = Image.open(tmp_jpg)
                    if first_img is None:
                        first_img = page
                    else:
                        buffer.append(page)
                    done += 1
                except Exception as e:
                    self.res_queue.put(("log", f"跳过 {img_path.name}: {e}"))
                    done += 1

        if first_img:
            self.res_queue.put(("prog", (92, f"{tag} 写入PDF…")))
            first_img.save(
                pdf_path,
                "PDF",
                save_all=True,
                append_images=buffer,
                resolution=100.0,
            )
            for p in [first_img] + buffer:
                p.close()

        shutil.rmtree(tmp_dir, ignore_errors=True)
        if pdf_path.exists():
            self.res_queue.put(("log", f"{tag} {pdf_name} → {human_size(pdf_path.stat().st_size)}"))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
