# 高清图片转JPG保存GIT仓库和图片库.pyw
"""
高清图片转JPG保存GIT仓库和图片库
================================
功能：
1. 扫描源目录（AI自定义）下所有 PNG，检查目标 GIT 目录（GPT-IMG）中是否已存在同名 JPG；
   缺失的 PNG 转换为 JPG 保存到对应子目录（自动新建目录）。
2. 可选：转换完成后自动 git add / commit / push 到仓库。
3. 可选：保存到在线图片库——把图片拼接为 CDN raw 地址，压缩为 base64，
   调用 general-data 接口（含 check-keys 去重 + save 保存），逻辑复刻 imageGallery.html。

约定：
- 配置持久化到 json/config_<name>.json（pathlib + JSON）。
- 日志走公共 log_utils（导入失败静默兜底）。
- 所有耗时操作在后台线程执行，界面不卡顿；可随时停止。
"""

import os
import sys
import base64
import threading
import subprocess
import urllib.parse
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ================== 路径与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "hd_png_to_jpg_git_gallery"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# 默认配置
DEFAULT_SOURCE_DIR = r"D:\FILES\IMG\AI自定义"
DEFAULT_TARGET_DIR = r"D:\CODE\Miscellaneous\GPT-IMG"
DEFAULT_URL_PREFIX = "https://cdn.jsdelivr.net/gh/pcl1350306170/Miscellaneous@refs/heads/main/"
DEFAULT_API_BASE = "http://localhost:28019"

# 图片库压缩参数（复刻 imageGallery.html）
SIZE_LIMIT_KB = 300        # 单张 base64 上限
MAX_WIDTH = 1920           # 最大宽度
QUALITY_STEPS = (85, 60, 40, 20)   # 质量递减档位
SAVE_JPEG_QUALITY = 95             # 转换保存到仓库的 JPG 起始质量（高清）
SAVE_JPEG_MIN_QUALITY = 40         # 转换质量下限（分辨率不变，最低降到此质量）
MAX_JPG_SIZE_KB = 2048             # 转换后 JPG 体积上限 2MB（分辨率保持不变）

# subprocess 静默标志（Windows）
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# ---------- 可选依赖：日志 ----------
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

# ---------- 可选依赖：Pillow ----------
try:
    from PIL import Image
    _PIL_OK = True
except Exception:
    Image = None
    _PIL_OK = False

# ---------- 可选依赖：requests ----------
try:
    import requests
    _REQUESTS_OK = True
except Exception:
    requests = None
    _REQUESTS_OK = False


# ================== 工具函数 ==================
def derive_data_type(url: str) -> str:
    """
    从图片 URL 推导 dataType（复刻前端 deriveDataType）。
    规则：域名各段 + 路径前两段，用 - 连接。
    例：https://cdn.jsdelivr.net/gh/pcl1350306170/Miscellaneous@.../xxx.jpg
        → cdn-jsdelivr-net-gh-pcl1350306170
    """
    try:
        parsed = urllib.parse.urlparse(url)
        host_parts = (parsed.hostname or "").split(".")
        path_parts = [p for p in parsed.path.split("/") if p]
        path_prefix = path_parts[:2]
        return "-".join(host_parts + path_prefix)
    except Exception:
        return "image_gallery"


def find_repo_root(start: str):
    """从 start 目录向上查找 .git，返回仓库根 Path；找不到返回 None。"""
    try:
        p = Path(start).resolve()
    except Exception:
        return None
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def to_rgb(im):
    """把任意模式图片转为 RGB（透明区域铺白底）。"""
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def jpeg_bytes(im, quality: int, progressive: bool = False) -> bytes:
    b = BytesIO()
    im.save(b, "JPEG", quality=quality, optimize=True, progressive=progressive)
    return b.getvalue()


def compress_to_base64(img_path: str) -> str:
    """
    读取本地图片并压缩为 data URL（base64），保证不超过 SIZE_LIMIT_KB。
    先按 MAX_WIDTH 等比缩放，再逐步降低质量，仍超限则逐步缩小分辨率。
    """
    with Image.open(img_path) as src:
        im = to_rgb(src)
        w, h = im.size
        if w > MAX_WIDTH:
            h = round(h * MAX_WIDTH / w)
            w = MAX_WIDTH
            im = im.resize((w, h), Image.LANCZOS)

        base_im = im
        data = jpeg_bytes(base_im, QUALITY_STEPS[0])
        for q in QUALITY_STEPS[1:]:
            if len(data) / 1024 <= SIZE_LIMIT_KB:
                break
            data = jpeg_bytes(base_im, q)

        # 质量到下限仍超限 → 逐步缩小分辨率（每次 75%）
        while len(data) / 1024 > SIZE_LIMIT_KB and w > 80 and h > 80:
            w = round(w * 0.75)
            h = round(h * 0.75)
            data = jpeg_bytes(base_im.resize((w, h), Image.LANCZOS), 20)

    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


# ================== 主程序 ==================
class HdPngToJpgApp:
    def __init__(self, root):
        self.root = root
        self.root.title("高清图片转JPG保存GIT仓库和图片库")
        self.root.geometry("1040x720")
        self.root.minsize(860, 600)

        # 配置变量
        self.source_dir = tk.StringVar(value=DEFAULT_SOURCE_DIR)
        self.target_dir = tk.StringVar(value=DEFAULT_TARGET_DIR)
        self.url_prefix = tk.StringVar(value=DEFAULT_URL_PREFIX)
        self.api_base = tk.StringVar(value=DEFAULT_API_BASE)
        self.auto_push = tk.BooleanVar(value=True)
        self.recompress_var = tk.BooleanVar(value=False)

        self.is_running = False
        self._stop_flag = False
        self._row_map = {}   # rel(显示) -> tree iid
        self.repo_root = None

        self._load_config()
        self._build_ui()

    # ---------------- 配置读写 ----------------
    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                import json
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.source_dir.set(cfg.get("source_dir", DEFAULT_SOURCE_DIR))
                self.target_dir.set(cfg.get("target_dir", DEFAULT_TARGET_DIR))
                self.url_prefix.set(cfg.get("url_prefix", DEFAULT_URL_PREFIX))
                self.api_base.set(cfg.get("api_base", DEFAULT_API_BASE))
                self.auto_push.set(cfg.get("auto_push", True))
                self.recompress_var.set(cfg.get("recompress", False))
            except Exception:
                pass

    def _save_config(self):
        try:
            import json
            cfg = {
                "source_dir": self.source_dir.get().strip(),
                "target_dir": self.target_dir.get().strip(),
                "url_prefix": self.url_prefix.get().strip(),
                "api_base": self.api_base.get().strip(),
                "auto_push": bool(self.auto_push.get()),
                "recompress": bool(self.recompress_var.get()),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- UI ----------------
    def _build_ui(self):
        # 配置区
        cfg = ttk.LabelFrame(self.root, text="配置", padding=10)
        cfg.pack(fill=tk.X, padx=10, pady=(10, 5))
        cfg.columnconfigure(1, weight=1)

        ttk.Label(cfg, text="源目录(PNG):").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(cfg, textvariable=self.source_dir).grid(row=0, column=1, padx=5, sticky=tk.EW)
        ttk.Button(cfg, text="选择", width=6,
                   command=lambda: self._pick_dir(self.source_dir)).grid(row=0, column=2)

        ttk.Label(cfg, text="目标目录(JPG):").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.target_dir).grid(row=1, column=1, padx=5, sticky=tk.EW, pady=(6, 0))
        ttk.Button(cfg, text="选择", width=6,
                   command=lambda: self._pick_dir(self.target_dir)).grid(row=1, column=2, pady=(6, 0))

        ttk.Label(cfg, text="CDN地址前缀:").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.url_prefix).grid(row=2, column=1, padx=5, sticky=tk.EW, pady=(6, 0))

        ttk.Label(cfg, text="接口地址:").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.api_base).grid(row=3, column=1, padx=5, sticky=tk.EW, pady=(6, 0))
        ttk.Label(cfg, text="(general-data 服务, 端口28019)",
                  foreground="#888").grid(row=3, column=2, sticky=tk.W, padx=5, pady=(6, 0))

        # 选项 + 操作区
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=10, pady=5)

        ttk.Checkbutton(bar, text="转换后自动 git push",
                        variable=self.auto_push).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(bar, text="重压超限的已存在JPG(>2MB)",
                        variable=self.recompress_var).pack(side=tk.LEFT, padx=(0, 12))

        self.btn_start = ttk.Button(bar, text="开始扫描并转换", command=self._start)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        self.btn_gallery = ttk.Button(bar, text="保存到图片库", command=self._start_gallery)
        self.btn_gallery.pack(side=tk.LEFT, padx=5)
        self.btn_stop = ttk.Button(bar, text="停止", command=self._stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(bar, text="就绪")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # 进度条
        self.progress = ttk.Progressbar(self.root, maximum=100)
        self.progress.pack(fill=tk.X, padx=10, pady=(0, 5))

        # 结果表格
        res = ttk.LabelFrame(self.root, text="处理结果", padding=5)
        res.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        cols = ("rel", "conv", "gallery")
        self.tree = ttk.Treeview(res, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("rel", text="相对路径")
        self.tree.heading("conv", text="转换状态")
        self.tree.heading("gallery", text="图片库状态")
        self.tree.column("rel", width=520, minwidth=200, anchor=tk.W)
        self.tree.column("conv", width=120, minwidth=80, anchor=tk.CENTER)
        self.tree.column("gallery", width=140, minwidth=80, anchor=tk.CENTER)
        sb = ttk.Scrollbar(res, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # 日志区
        logf = ttk.LabelFrame(self.root, text="日志", padding=5)
        logf.pack(fill=tk.BOTH, padx=10, pady=(0, 10), expand=False)
        self.log_text = scrolledtext.ScrolledText(logf, height=8, state="disabled",
                                                  font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _pick_dir(self, var):
        d = filedialog.askdirectory(title="选择目录", initialdir=var.get() or None)
        if d:
            var.set(os.path.normpath(d))

    # ---------------- 线程安全的 UI 更新 ----------------
    def _log(self, msg):
        logger.info(msg)
        def _do():
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        self.root.after(0, _do)

    def _set_progress(self, frac, text=None):
        def _do():
            self.progress["value"] = max(0.0, min(100.0, frac * 100))
            if text:
                self.status_label.config(text=text)
        self.root.after(0, _do)

    def _insert_row(self, rel, conv, gallery=""):
        def _do():
            iid = self.tree.insert("", tk.END, values=(rel, conv, gallery))
            self._row_map[rel] = iid
        self.root.after(0, _do)

    def _set_gallery_status(self, rel, status):
        def _do():
            iid = self._row_map.get(rel)
            if iid:
                vals = list(self.tree.item(iid, "values"))
                vals[2] = status
                self.tree.item(iid, values=vals)
        self.root.after(0, _do)

    def _set_buttons_running(self, running):
        def _do():
            st = tk.DISABLED if running else tk.NORMAL
            self.btn_start.config(state=st)
            self.btn_gallery.config(state=st)
            self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)
        self.root.after(0, _do)

    # ---------------- 控制 ----------------
    def _stop(self):
        self._stop_flag = True
        self._log("⚠ 已请求停止，正在等待当前步骤结束…")

    def _start(self):
        if self.is_running:
            return
        src = self.source_dir.get().strip()
        tgt = self.target_dir.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("提示", "源目录无效，请重新选择")
            return
        if not tgt:
            messagebox.showwarning("提示", "请填写目标目录")
            return
        if not _PIL_OK:
            messagebox.showerror("缺少依赖", "未安装 Pillow，无法转换/压缩图片。\n请执行：pip install Pillow")
            return
        if self.save_gallery.get() and not _REQUESTS_OK:
            messagebox.showerror("缺少依赖", "未安装 requests，无法调用图片库接口。\n请执行：pip install requests")
            return

        self._save_config()
        # 清空表格
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_map.clear()

        self.is_running = True
        self._stop_flag = False
        self._set_buttons_running(True)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------------- 后台主流程 ----------------
    def _worker(self):
        try:
            self._run_pipeline()
        except Exception as e:
            logger.error(f"流程异常: {e}", exc_info=True)
            self._log(f"❌ 发生异常: {e}")
        finally:
            self.is_running = False
            self._set_buttons_running(False)

    def _run_pipeline(self):
        src = Path(self.source_dir.get().strip())
        tgt = Path(self.target_dir.get().strip())
        tgt.mkdir(parents=True, exist_ok=True)

        # 仓库根（用于 git push 与 URL 相对路径）
        self.repo_root = find_repo_root(str(tgt))
        if self.repo_root:
            self._log(f"仓库根: {self.repo_root}")
        else:
            self._log("⚠ 未在目标目录上层找到 .git，git push 与 CDN 相对路径可能不准确")

        # ---------- 阶段1：扫描 + 转换 ----------
        pngs = sorted(src.rglob("*.png"))
        total = len(pngs)
        self._log(f"扫描到 {total} 张 PNG，开始比对/转换…")

        matched = []      # [(jpg_path, rel_display), ...]
        converted = existed = failed = 0
        for i, png in enumerate(pngs):
            if self._stop_flag:
                self._log("已停止（转换阶段）")
                break
            rel = png.relative_to(src)
            rel_display = str(rel)
            jpg_rel = rel.with_suffix(".jpg")
            jpg_path = tgt / jpg_rel

            if jpg_path.exists():
                existed += 1
                matched.append((jpg_path, rel_display))
                self._insert_row(rel_display, "已存在")
            else:
                ok, err = self._convert(png, jpg_path)
                if ok:
                    converted += 1
                    matched.append((jpg_path, rel_display))
                    self._insert_row(rel_display, "已转换")
                    if err:   # 成功但仍有体积警告
                        self._log(f"  {rel_display}: {err}")
                else:
                    failed += 1
                    self._insert_row(rel_display, "转换失败")
                    self._log(f"  转换失败 {rel_display}: {err}")
            self._set_progress((i + 1) / total * 0.4 if total else 0.4,
                               f"转换 {i + 1}/{total}")

        self._log(f"转换完成：已存在 {existed}，新转换 {converted}，失败 {failed}")

        # ---------- 阶段1b：重新压缩超限的已存在JPG ----------
        recompressed = 0
        if self.recompress_var.get() and not self._stop_flag:
            recompressed = self._recompress_oversized()

        # ---------- 阶段2：git push ----------
        changed = converted + recompressed
        if self.auto_push.get() and changed > 0 and not self._stop_flag:
            self._do_git_push(converted, recompressed)
        elif self.auto_push.get() and changed == 0:
            self._log("无文件变更，跳过 git push")

        # ---------- 汇总 ----------
        summary = (f"全部完成：已存在 {existed}，新转换 {converted}，"
                   f"重压 {recompressed}，失败 {failed}")
        self._set_progress(1.0, summary)
        self._log("✅ " + summary)
        self.root.after(0, lambda: messagebox.showinfo("完成", summary))

    # ---------------- 转换 ----------------
    def _encode_under_limit(self, rgb):
        """保持分辨率不变，从高质量逐档降低，直到 JPEG 字节 ≤ MAX_JPG_SIZE_KB。"""
        data = b""
        for q in range(SAVE_JPEG_QUALITY, SAVE_JPEG_MIN_QUALITY - 1, -5):
            data = jpeg_bytes(rgb, q, progressive=True)
            if len(data) / 1024 <= MAX_JPG_SIZE_KB:
                break
        return data

    def _convert(self, png_path: Path, jpg_path: Path):
        """
        PNG → JPG：保持原始分辨率不变，从高质量逐步降低，直到文件 ≤ MAX_JPG_SIZE_KB。
        返回 (是否成功, 提示信息)；成功但超限时提示信息为警告文案。
        """
        try:
            jpg_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(str(png_path)) as im:
                rgb = to_rgb(im)   # 分辨率保持不变，仅处理透明通道
                data = self._encode_under_limit(rgb)
            with open(str(jpg_path), "wb") as f:
                f.write(data)
            if len(data) / 1024 > MAX_JPG_SIZE_KB:
                warn = (f"⚠ 已降至最低质量({SAVE_JPEG_MIN_QUALITY})仍超 "
                        f"{MAX_JPG_SIZE_KB // 1024}MB（分辨率不变）: {len(data) / 1024 / 1024:.2f}MB")
                logger.warning(f"{png_path.name}: {warn}")
                return True, warn
            return True, ""
        except Exception as e:
            logger.error(f"转换失败 {png_path}: {e}")
            return False, str(e)

    def _recompress_jpg(self, jpg_path: Path):
        """就地重压一张已存在的 JPG（无源 PNG 时），分辨率不变。返回 (成功, 警告文案)。"""
        try:
            with Image.open(str(jpg_path)) as im:
                rgb = to_rgb(im)
                data = self._encode_under_limit(rgb)
            with open(str(jpg_path), "wb") as f:
                f.write(data)
            if len(data) / 1024 > MAX_JPG_SIZE_KB:
                warn = (f"⚠ 降至最低质量({SAVE_JPEG_MIN_QUALITY})仍超 "
                        f"{MAX_JPG_SIZE_KB // 1024}MB: {len(data) / 1024 / 1024:.2f}MB")
                logger.warning(f"{jpg_path.name}: {warn}")
                return True, warn
            return True, ""
        except Exception as e:
            logger.error(f"重新压缩失败 {jpg_path}: {e}")
            return False, str(e)

    def _recompress_oversized(self):
        """扫描目标目录中所有超过 MAX_JPG_SIZE_KB 的 JPG，重新压缩至上限以内（分辨率不变）。"""
        tgt = Path(self.target_dir.get().strip())
        src = Path(self.source_dir.get().strip())
        if not tgt.is_dir():
            self._log("⚠ 目标目录无效，跳过重新压缩")
            return 0
        oversized = [j for j in sorted(tgt.rglob("*.jpg"))
                     if j.stat().st_size / 1024 > MAX_JPG_SIZE_KB]
        if not oversized:
            self._log(f"无超过 {MAX_JPG_SIZE_KB // 1024}MB 的 JPG，无需重压")
            return 0

        self._log(f"发现 {len(oversized)} 张超过 {MAX_JPG_SIZE_KB // 1024}MB 的 JPG，"
                  f"开始重新压缩（分辨率不变）…")
        done = still = failed = 0
        n = len(oversized)
        for i, jpg in enumerate(oversized):
            if self._stop_flag:
                self._log("已停止（重新压缩阶段）")
                break
            self._set_progress(0.4 + (i / n) * 0.1, f"重新压缩 {i + 1}/{n}")
            rel = jpg.relative_to(tgt)
            png = src / rel.with_suffix(".png")
            before = jpg.stat().st_size / 1024 / 1024
            if png.exists():
                ok, warn = self._convert(png, jpg)      # 从 PNG 源重生，画质更佳
                origin = "PNG源"
            else:
                ok, warn = self._recompress_jpg(jpg)    # 无源 PNG，从 JPG 自身重压
                origin = "JPG自压"
            if ok:
                done += 1
                after = jpg.stat().st_size / 1024 / 1024
                tag = "⚠仍超限" if warn else "✓"
                if warn:
                    still += 1
                self._log(f"  {tag} [{origin}] {rel.as_posix()}: {before:.2f}MB → {after:.2f}MB")
            else:
                failed += 1
                self._log(f"  ✗ 压缩失败 [{origin}] {rel.as_posix()}: {warn}")
        self._log(f"重新压缩完成：成功 {done}（仍超限 {still}），失败 {failed}")
        return done

    # ---------------- git push ----------------
    def _git(self, args, cwd):
        return subprocess.run(
            ["git", *args], cwd=str(cwd),
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )

    def _do_git_push(self, converted, recompressed=0):
        repo = self.repo_root
        if not repo:
            self._log("⚠ 未找到仓库根，跳过 git push")
            return
        try:
            target_rel = os.path.relpath(self.target_dir.get().strip(), str(repo)).replace("\\", "/")
        except Exception:
            target_rel = "."

        # 当前分支
        br = self._git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        branch = (br.stdout or "").strip() or "main"

        self._log(f"→ git add {target_rel}")
        self._git(["add", "--", target_rel], repo)

        parts = []
        if converted:
            parts.append(f"convert {converted} PNG to JPG")
        if recompressed:
            parts.append(f"recompress {recompressed} oversized JPG")
        msg = "chore: auto " + ", ".join(parts)
        self._log(f"→ git commit -m \"{msg}\"")
        cm = self._git(["commit", "-m", msg], repo)
        if cm.returncode != 0:
            out = ((cm.stdout or "") + (cm.stderr or "")).strip()
            self._log(f"  提交无变化或失败: {out}")
            return

        self._log(f"→ git push origin {branch}")
        ps = self._git(["push", "origin", branch], repo)
        out = ((ps.stdout or "") + (ps.stderr or "")).strip()
        if ps.returncode == 0:
            self._log("  ✓ push 成功")
        else:
            self._log(f"  ✗ push 失败: {out}")
        if out:
            for line in out.splitlines()[-6:]:
                self._log("    " + line)

    # ---------------- 图片库 ----------------
    def _build_url(self, jpg_path: Path):
        prefix = self.url_prefix.get().strip()
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        if self.repo_root:
            try:
                rel = jpg_path.relative_to(self.repo_root)
            except Exception:
                rel = Path(self.target_dir.get().strip().rstrip("/\\").split(os.sep)[-1]) / jpg_path.name
        else:
            rel = Path("GPT-IMG") / jpg_path.name
        rel_posix = rel.as_posix()
        # 保留正常汉字（不做 percent 编码），以便与图片库已有记录的 dataKey 去重匹配
        return prefix + rel_posix

    def _api_check_keys(self, api_base, data_type, keys):
        url = api_base.rstrip("/") + "/api/v1/general-data/check-keys"
        r = requests.post(url, json={"dataType": data_type, "dataKeys": keys},
                          headers={"Content-Type": "application/json"}, timeout=120)
        d = r.json()
        if d.get("resultCode") == 200:
            return d.get("data") or []
        raise Exception(d.get("message") or d.get("desc") or "check-keys 失败")

    def _api_save(self, api_base, item):
        url = api_base.rstrip("/") + "/api/v1/general-data/save"
        r = requests.post(url, json=item,
                          headers={"Content-Type": "application/json"}, timeout=120)
        d = r.json()
        if d.get("resultCode") == 200:
            return True
        raise Exception(d.get("message") or d.get("desc") or "save 失败")

    def _save_with_retry(self, api_base, item, retries=2):
        last = ""
        for attempt in range(1, retries + 1):
            try:
                self._api_save(api_base, item)
                return True, ""
            except Exception as e:
                last = str(e)
                logger.warning(f"保存失败(第{attempt}次) {item.get('dataKey')}: {e}")
        return False, last

    def _start_gallery(self):
        """独立按钮：仅执行「保存到图片库」，不涉及转换/push。"""
        if self.is_running:
            messagebox.showinfo("提示", "已有任务正在运行，请等待结束或先停止")
            return
        if not _PIL_OK:
            messagebox.showerror("缺少依赖", "未安装 Pillow，无法压缩图片。\n请执行：pip install Pillow")
            return
        if not _REQUESTS_OK:
            messagebox.showerror("缺少依赖", "未安装 requests，无法调用图片库接口。\n请执行：pip install requests")
            return
        if not self.api_base.get().strip():
            messagebox.showwarning("提示", "请先填写接口地址")
            return
        if not os.path.isdir(self.target_dir.get().strip()):
            messagebox.showwarning("提示", "目标目录无效")
            return

        self._save_config()
        self.is_running = True
        self._stop_flag = False
        self._set_buttons_running(True)
        threading.Thread(target=self._gallery_worker, daemon=True).start()

    def _gallery_worker(self):
        try:
            src = Path(self.source_dir.get().strip())
            tgt = Path(self.target_dir.get().strip())
            self.repo_root = find_repo_root(str(tgt))
            if self.repo_root:
                self._log(f"仓库根: {self.repo_root}")

            # 构建待保存集合：源PNG → 目标已存在的同名JPG
            matched = []
            if src.is_dir():
                for png in sorted(src.rglob("*.png")):
                    rel = png.relative_to(src)
                    jpg = tgt / rel.with_suffix(".jpg")
                    if jpg.exists():
                        matched.append((jpg, str(rel)))
            else:
                self._log("⚠ 源目录无效")

            # 清空并填充表格
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self._row_map.clear()
            for _jpg, rel_display in matched:
                self._insert_row(rel_display, "—")

            self._log(f"待保存到图片库：{len(matched)} 张")
            if not matched:
                self._set_progress(1.0, "无可保存图片")
                self.root.after(0, lambda: messagebox.showinfo("完成", "没有可保存的 JPG"))
                return
            self._do_gallery(matched, progress_base=0.0, progress_span=1.0)
            self._set_progress(1.0, "图片库保存结束")
        except Exception as e:
            logger.error(f"图片库保存异常: {e}", exc_info=True)
            self._log(f"❌ 图片库保存异常: {e}")
        finally:
            self.is_running = False
            self._set_buttons_running(False)

    def _do_gallery(self, matched, progress_base=0.5, progress_span=0.5):
        api_base = self.api_base.get().strip()
        if not api_base:
            self._log("⚠ 未填写接口地址，跳过图片库保存")
            return

        # 构建 URL 列表
        pairs = []   # (rel_display, jpg_path, url)
        for jpg_path, rel_display in matched:
            pairs.append((rel_display, jpg_path, self._build_url(jpg_path)))

        data_type = derive_data_type(pairs[0][2])
        self._log(f"图片库 dataType: {data_type}，待校验 {len(pairs)} 条")

        # check-keys 去重
        urls = [p[2] for p in pairs]
        try:
            not_exist = set(self._api_check_keys(api_base, data_type, urls))
        except Exception as e:
            self._log(f"✗ check-keys 调用失败，跳过图片库保存: {e}")
            return

        todo = [p for p in pairs if p[2] in not_exist]
        skipped = len(pairs) - len(todo)
        # 已存在的标记
        exist_set = {p[0] for p in pairs if p[2] not in not_exist}
        for rel_display in exist_set:
            self._set_gallery_status(rel_display, "图库已存在")
        self._log(f"去重：已存在 {skipped} 条，待保存 {len(todo)} 条")

        if not todo:
            return

        saved = fail = 0
        n = len(todo)
        for i, (rel_display, jpg_path, url) in enumerate(todo):
            if self._stop_flag:
                self._log("已停止（图片库阶段）")
                break
            self._set_progress(progress_base + (i / n) * progress_span, f"图片库 {i + 1}/{n}")
            try:
                b64 = compress_to_base64(str(jpg_path))
            except Exception as e:
                fail += 1
                self._set_gallery_status(rel_display, "压缩失败")
                self._log(f"  压缩失败 {rel_display}: {e}")
                continue
            item = {"dataType": data_type, "dataKey": url, "dataContent": b64}
            ok, err = self._save_with_retry(api_base, item)
            if ok:
                saved += 1
                self._set_gallery_status(rel_display, "已保存")
            else:
                fail += 1
                self._set_gallery_status(rel_display, "保存失败")
                self._log(f"  保存失败 {rel_display}: {err}")

        self._log(f"图片库保存完成：成功 {saved}，失败 {fail}，已存在跳过 {skipped}")


if __name__ == "__main__":
    root = tk.Tk()
    app = HdPngToJpgApp(root)
    root.mainloop()
