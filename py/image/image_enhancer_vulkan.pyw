# -*- coding: utf-8 -*-
"""
图片放大增强工具（Vulkan 加速版）
==================================
基于 realesrgan-ncnn-vulkan（Intel Arc GPU / Vulkan 加速）+ 可选 GFPGAN 人脸增强。

相比原版 image_enhancer.pyw 的改进：
    1. 放大引擎改用 ncnn-vulkan（GPU/Vulkan 加速），不再依赖 PyTorch 跑 CPU
    2. 固定放大倍数 2x / 3x / 4x（下拉框选择）
    3. 输出统一转为无损 PNG
    4. 可选 GFPGAN 人脸增强（针对人物照片）
    5. 沿用项目通用规范：json/ 配置保存 + log_utils 日志

依赖说明（离线可运行）：
    - 放大：realesrgan-ncnn-vulkan.exe + models/（默认 D:\\dev\\image_enhancer\\realesrgan-tool）
    - 人脸增强（可选）：Python 库 gfpgan + 模型 GFPGANv1.4.pth（默认 D:\\dev\\image_enhancer）
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import sys
import json
import uuid
import shutil
import tempfile
import threading
import subprocess
import queue
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ──────────── 公共日志模块（可选依赖）────────────
_PY_DIR = str(Path(__file__).resolve().parent.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger()
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

# GFPGAN 库状态（None=加载中，True=已加载，False=不可用）
HAS_GFPGAN = None
_GFPGANer = None

# ──────────── 路径与配置 ────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config_image_enhancer_vulkan.json"

# 默认目录（可在界面/配置中修改）
DEFAULT_WEIGHTS_DIR = r"D:\dev\image_enhancer"
DEFAULT_TOOL_DIR = r"D:\dev\image_enhancer\realesrgan-tool"

MODEL_URLS = {
    'GFPGANv1.4.pth': 'https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth',
}


# ──────────── 核心引擎（与 GUI 解耦，便于复用/测试）────────────

def upscale_with_vulkan(input_path, temp_png, tool_dir, factor):
    """调用 realesrgan-ncnn-vulkan.exe 做 GPU(Vulkan) 放大，输出无损 PNG 到 temp_png。

    factor: 2 / 3 / 4
    注意：realesrgan-x4plus 模型的原生倍数是 4x；ncnn 工具的 2x/3x 内部
    降采样在部分显卡（如 Intel Arc）上会把图片切成方块错位乱码。
    因此 2x/3x 一律走「4x 放大 → Pillow LANCZOS 缩回」的方式，保证正确性。
    """
    exe = os.path.join(tool_dir, 'realesrgan-ncnn-vulkan.exe')
    if not os.path.isfile(exe):
        raise FileNotFoundError(f"未找到 Vulkan 引擎: {exe}")

    factor = int(factor)
    if factor not in (2, 3, 4):
        factor = 4

    if factor == 4:
        # 原生倍数，直接出图
        cmd = [exe, '-i', input_path, '-o', temp_png,
               '-n', 'realesrgan-x4plus', '-s', '4', '-f', 'png']
        proc = subprocess.run(cmd, cwd=tool_dir, capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        if not os.path.isfile(temp_png) or os.path.getsize(temp_png) == 0:
            err = (proc.stderr or b'').decode('utf-8', 'ignore').strip()
            raise RuntimeError(f"Vulkan 放大失败: {err[:300] or '未知错误'}")
        return

    # 2x / 3x：先 4x 再 Pillow 无损缩回（规避 ncnn 非原生倍数乱码）
    tmp4 = temp_png + '.tmp4.png'
    if os.path.exists(tmp4):
        try:
            os.remove(tmp4)
        except OSError:
            pass
    cmd = [exe, '-i', input_path, '-o', tmp4,
           '-n', 'realesrgan-x4plus', '-s', '4', '-f', 'png']
    proc = subprocess.run(cmd, cwd=tool_dir, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    if not os.path.isfile(tmp4) or os.path.getsize(tmp4) == 0:
        err = (proc.stderr or b'').decode('utf-8', 'ignore').strip()
        raise RuntimeError(f"Vulkan 放大失败: {err[:300] or '未知错误'}")
    try:
        from PIL import Image
        with Image.open(input_path) as src_im:
            iw, ih = src_im.size
        with Image.open(tmp4) as im:
            im = im.convert('RGB')
            target = (max(1, int(round(iw * factor))), max(1, int(round(ih * factor))))
            if im.size != target:
                im = im.resize(target, Image.LANCZOS)
            im.save(temp_png, format='PNG')
    finally:
        if os.path.exists(tmp4):
            try:
                os.remove(tmp4)
            except OSError:
                pass


def create_face_enhancer(model_path, weights_base):
    """创建 GFPGAN 人脸增强器（只做人脸恢复，不再放大，upscale=1）。

    facexlib 会按相对路径 'gfpgan/weights' 查找人脸检测/解析模型，
    因此这里临时切换到 weights_base 目录，使离线模型可被稳定找到。
    """
    import os
    from gfpgan import GFPGANer

    base = str(weights_base)
    facex_weights = os.path.join(base, 'gfpgan', 'weights')
    os.makedirs(facex_weights, exist_ok=True)

    # 离线检测：人脸检测/解析模型缺失时给出明确提示
    need = ['detection_Resnet50_Final.pth', 'parsing_parsenet.pth']
    missing = [n for n in need if not os.path.isfile(os.path.join(facex_weights, n))]
    if missing:
        raise FileNotFoundError(
            f"缺少 GFPGAN 人脸模型: {', '.join(missing)}\n"
            f"请放到: {facex_weights}\n"
            f"（联网时可首次自动下载；离线需提前手动放置）")

    cwd = os.getcwd()
    try:
        os.chdir(base)
        return GFPGANer(
            model_path=model_path,
            upscale=1,
            arch='clean',
            channel_multiplier=2,
            bg_upsampler=None,
        )
    finally:
        os.chdir(cwd)


def enhance_face_image(face_enhancer, input_png, output_png):
    """对已放大的 PNG 做人脸增强，输出无损 PNG（支持中文路径）。"""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.fromfile(input_png, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法读取图片: {input_png}")

    _, _, output = face_enhancer.enhance(
        img, has_aligned=False, only_center_face=False,
        paste_back=True, weight=0.5,
    )

    os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)
    success, buf = cv2.imencode('.png', output)
    if not success:
        raise RuntimeError(f"编码 PNG 失败: {output_png}")
    buf.tofile(output_png)


# ──────────── 图形界面 ────────────

class ImageEnhancerVulkanApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🔍 图片放大增强工具 - Vulkan 加速版")
        self.root.geometry("980x780")
        self.root.resizable(True, True)

        # 中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))
        self.style.configure("TCheckbutton", font=("SimHei", 9))

        # 变量
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.weights_dir = tk.StringVar(value=str(WEIGHTS_DIR))
        self.tool_dir = tk.StringVar(value=str(TOOL_DIR))
        self.upscale_factor = tk.IntVar(value=2)
        self.face_enhance = tk.BooleanVar(value=True)
        self.thread_count = tk.IntVar(value=1)
        self._stop_event = threading.Event()
        self.is_processing = False
        self.log_queue = queue.Queue()

        self.face_enhancer = None
        self._face_lock = threading.Lock()

        self.create_widgets()
        self.load_config()

        self._poll_log_queue()
        threading.Thread(target=self._load_enhance_libs, daemon=True).start()

        logger.info("图片放大增强工具（Vulkan 版）启动")

    # ── UI ──
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="图片放大增强工具 - Vulkan 加速版",
                  font=("SimHei", 16, "bold")).pack(pady=(0, 15))

        # 输入设置
        input_frame = ttk.LabelFrame(main_frame, text="输入设置", padding="10")
        input_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(input_frame, text="图片目录:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Entry(input_frame, textvariable=self.input_dir, width=62).grid(row=0, column=1, padx=5)
        ttk.Button(input_frame, text="选择目录", command=self.select_input_dir).grid(row=0, column=2, padx=5)

        ttk.Label(input_frame, text="导出目录:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        ttk.Entry(input_frame, textvariable=self.output_dir, width=62).grid(row=1, column=1, padx=5, pady=(10, 0))
        ttk.Button(input_frame, text="选择目录", command=self.select_output_dir).grid(row=1, column=2, padx=5, pady=(10, 0))

        # 引擎与模型目录
        eng_frame = ttk.LabelFrame(main_frame, text="引擎与模型", padding="10")
        eng_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(eng_frame, text="Vulkan引擎:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        ttk.Entry(eng_frame, textvariable=self.tool_dir, width=62).grid(row=0, column=1, padx=5)
        ttk.Button(eng_frame, text="选择目录", command=self.select_tool_dir).grid(row=0, column=2, padx=5)

        ttk.Label(eng_frame, text="模型目录:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))
        ttk.Entry(eng_frame, textvariable=self.weights_dir, width=62).grid(row=1, column=1, padx=5, pady=(10, 0))
        ttk.Button(eng_frame, text="选择目录", command=self.select_weights_dir).grid(row=1, column=2, padx=5, pady=(10, 0))

        # 增强参数
        param_frame = ttk.LabelFrame(main_frame, text="增强参数", padding="10")
        param_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(param_frame, text="放大倍数:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        factor_combo = ttk.Combobox(param_frame, textvariable=self.upscale_factor,
                                    values=[2, 3, 4], state="readonly", width=8)
        factor_combo.grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(param_frame, text="线程数:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5))
        thread_spin = ttk.Spinbox(param_frame, from_=1, to=4,
                                  textvariable=self.thread_count, width=5)
        thread_spin.grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Checkbutton(param_frame,
                        text="启用人脸增强（GFPGAN，针对人物照片，CPU 较慢）",
                        variable=self.face_enhance).grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(10, 0))

        self.lib_status_label = ttk.Label(param_frame, text="⏳ 正在检测引擎...",
                                          foreground="gray", font=("SimHei", 8))
        self.lib_status_label.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(5, 0))

        ttk.Label(param_frame, text="技术方案: Real-ESRGAN (ncnn-Vulkan GPU) + 可选 GFPGAN 人脸增强",
                  foreground="gray", font=("SimHei", 8)).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))

        # 控制按钮
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="开始增强", command=self.start_processing)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_processing, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空日志", command=self.clear_log).pack(side=tk.LEFT, padx=5)

        # 进度
        progress_frame = ttk.Frame(main_frame, padding="5")
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        self.progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress.pack(fill=tk.X, expand=True)
        self.progress_label = ttk.Label(progress_frame, text="就绪")
        self.progress_label.pack(fill=tk.X, pady=(5, 0))

        # 日志
        log_frame = ttk.LabelFrame(main_frame, text="处理日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, height=15, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

    # ── 目录选择 ──
    def select_input_dir(self):
        d = filedialog.askdirectory(title="选择图片所在目录")
        if d:
            self.input_dir.set(d)
            logger.info(f"选择输入目录: {d}")

    def select_output_dir(self):
        d = filedialog.askdirectory(title="选择导出目录")
        if d:
            self.output_dir.set(d)
            logger.info(f"选择导出目录: {d}")

    def select_weights_dir(self):
        d = filedialog.askdirectory(title="选择模型文件存放目录")
        if d:
            self.weights_dir.set(d)
            logger.info(f"选择模型目录: {d}")

    def select_tool_dir(self):
        d = filedialog.askdirectory(title="选择 realesrgan-ncnn-vulkan 引擎目录")
        if d:
            self.tool_dir.set(d)
            logger.info(f"选择引擎目录: {d}")

    # ── 配置保存/加载（沿用项目规范）──
    def load_config(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.input_dir.set(config.get('input_dir', ''))
                self.output_dir.set(config.get('output_dir', ''))
                wdir = config.get('weights_dir', '')
                if wdir and os.path.isdir(wdir):
                    self.weights_dir.set(wdir)
                tdir = config.get('tool_dir', '')
                if tdir and os.path.isdir(tdir):
                    self.tool_dir.set(tdir)
                self.upscale_factor.set(config.get('upscale_factor', 2))
                self.face_enhance.set(config.get('face_enhance', True))
                self.thread_count.set(config.get('thread_count', 1))
                logger.info("配置加载成功")
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")

    def save_config(self):
        try:
            config = {
                'input_dir': self.input_dir.get(),
                'output_dir': self.output_dir.get(),
                'weights_dir': self.weights_dir.get(),
                'tool_dir': self.tool_dir.get(),
                'upscale_factor': self.upscale_factor.get(),
                'face_enhance': self.face_enhance.get(),
                'thread_count': self.thread_count.get(),
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    # ── 日志与提示 ──
    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg + '\n')
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def log(self, message):
        self.log_queue.put(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def _show_toast(self, title, message, level="info", duration_ms=3500):
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)
            colors = {
                "success": ("#2e7d32", "#e8f5e9", "✅"),
                "error":   ("#c62828", "#ffebee", "❌"),
                "info":    ("#1565c0", "#e3f2fd", "ℹ️"),
                "warning": ("#e65100", "#fff3e0", "⚠️"),
            }
            fg, bg, icon = colors.get(level, colors["info"])
            toast.configure(bg=bg)
            header = tk.Frame(toast, bg=bg)
            header.pack(fill=tk.X, padx=10, pady=8)
            tk.Label(header, text=f"{icon} {title}", font=("Microsoft YaHei UI", 11, "bold"),
                     fg=fg, bg=bg).pack(side=tk.LEFT)
            close_btn = tk.Label(header, text="✕", font=("Consolas", 10), fg="#999", bg=bg, cursor="hand2")
            close_btn.pack(side=tk.RIGHT)
            close_btn.bind("<Button-1>", lambda e: toast.destroy())
            tk.Label(toast, text=message, font=("Microsoft YaHei UI", 10),
                     fg="#333", bg=bg, wraplength=320, justify=tk.LEFT).pack(padx=12, pady=(4, 10), anchor=tk.W)
            toast.update_idletasks()
            w, h = toast.winfo_width(), toast.winfo_height()
            sx, sy = toast.winfo_screenwidth(), toast.winfo_screenheight()
            toast.geometry(f"+{sx - w - 20}+{sy - h - 60}")
            toast.deiconify()
            toast.after(duration_ms, toast.destroy)
        except Exception:
            pass

    # ── 库/引擎状态检测 ──
    def _load_enhance_libs(self):
        global HAS_GFPGAN, _GFPGANer

        try:
            from gfpgan import GFPGANer
            _GFPGANer = GFPGANer
            HAS_GFPGAN = True
            logger.info("GFPGAN 库加载完成")
        except ImportError:
            HAS_GFPGAN = False
            logger.warning("GFPGAN 库未安装")
        except Exception as e:
            HAS_GFPGAN = False
            logger.error(f"GFPGAN 加载失败: {type(e).__name__}: {e}")
        finally:
            self.root.after(0, self._update_lib_status)

    def _update_lib_status(self):
        parts = []
        # Vulkan 引擎检测
        exe = os.path.join(self.tool_dir.get(), 'realesrgan-ncnn-vulkan.exe')
        if os.path.isfile(exe):
            parts.append("✅ Vulkan 引擎")
        else:
            parts.append("❌ 未找到 Vulkan 引擎")

        if HAS_GFPGAN:
            parts.append("✅ GFPGAN")
        elif HAS_GFPGAN is False:
            parts.append("⚠️ GFPGAN 未安装")
        else:
            parts.append("⏳ GFPGAN 加载中...")

        if '❌' in parts[0]:
            self.lib_status_label.config(text=" | ".join(parts), foreground="red")
        else:
            self.lib_status_label.config(text=" | ".join(parts), foreground="green")

    # ── 模型下载（缺失时才联网）──
    def _download_model(self, filename, url):
        """若模型已存在则直接使用（离线可跑）；缺失时才下载。"""
        weights_dir = Path(self.weights_dir.get())
        weights_dir.mkdir(parents=True, exist_ok=True)
        dest = weights_dir / filename
        if dest.exists():
            return str(dest)

        self.log(f"正在下载模型 {filename}（首次使用需联网）...")
        logger.info(f"下载模型: {url}")
        try:
            import urllib.request
            urllib.request.urlretrieve(url, str(dest))
            self.log(f"✅ 模型 {filename} 下载完成")
            return str(dest)
        except Exception as e:
            if dest.exists():
                dest.unlink()
            raise RuntimeError(f"模型下载失败: {e}\n请手动下载: {url}\n保存到: {dest}")

    def init_face_enhancer(self):
        """加载 GFPGAN 模型（仅当勾选人脸增强时调用）"""
        if not HAS_GFPGAN:
            raise RuntimeError("未安装 GFPGAN，请执行: pip install gfpgan")
        self.log("正在加载 GFPGAN 人脸增强模型...")
        logger.info("初始化 GFPGAN 模型")
        gfpgan_weight = self._download_model('GFPGANv1.4.pth', MODEL_URLS['GFPGANv1.4.pth'])
        self.face_enhancer = create_face_enhancer(gfpgan_weight, self.weights_dir.get())
        self.log("✅ GFPGAN 人脸增强模型加载完成")

    # ── 开始/停止 ──
    def start_processing(self):
        input_dir = self.input_dir.get()
        output_dir = self.output_dir.get()
        tool_dir = self.tool_dir.get()

        if not input_dir or not os.path.isdir(input_dir):
            messagebox.showerror("错误", "请选择有效的图片目录")
            return
        if not output_dir:
            messagebox.showerror("错误", "请选择导出目录")
            return

        exe = os.path.join(tool_dir, 'realesrgan-ncnn-vulkan.exe')
        if not os.path.isfile(exe):
            messagebox.showerror("错误", f"未找到 Vulkan 引擎:\n{exe}\n请在界面选择 realesrgan-tool 目录")
            return

        if HAS_GFPGAN is None:
            messagebox.showinfo("提示", "库检测中，请稍后再试...")
            return
        if self.face_enhance.get() and not HAS_GFPGAN:
            if not messagebox.askyesno("警告", "未安装 GFPGAN，人脸增强功能将禁用\n是否继续？\n安装命令: pip install gfpgan"):
                return

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建输出目录: {e}")
            return

        # 扫描图片（递归，保留子目录结构）
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        image_files = []
        for file_path in Path(input_dir).rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                image_files.append(str(file_path))

        if not image_files:
            messagebox.showwarning("警告", "未找到图片文件")
            return

        self.log(f"找到 {len(image_files)} 张图片")
        self.log(f"放大倍数: {self.upscale_factor.get()}x (Vulkan GPU)")
        self.log(f"人脸增强: {'启用' if self.face_enhance.get() else '禁用'}")
        self.log(f"线程数: {self.thread_count.get()}")

        # 保存配置 & 初始化人脸增强器
        self.save_config()
        if self.face_enhance.get():
            try:
                self.init_face_enhancer()
            except Exception as e:
                messagebox.showerror("错误", f"GFPGAN 初始化失败: {e}")
                return

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.is_processing = True
        self._stop_event.clear()

        self.progress['value'] = 0
        self.progress['maximum'] = len(image_files)

        thread = threading.Thread(
            target=self._process_images,
            args=(image_files, output_dir),
            daemon=True
        )
        thread.start()

    def stop_processing(self):
        self._stop_event.set()
        self.is_processing = False
        self.log("⚠️ 正在停止，等待当前任务完成...")

    # ── 批处理 ──
    def _process_images(self, image_files, output_dir):
        executor = None
        temp_root = None
        try:
            temp_root = Path(tempfile.gettempdir()) / f"vulkan_enhancer_{uuid.uuid4().hex[:8]}"
            temp_root.mkdir(parents=True, exist_ok=True)

            success_count = 0
            fail_count = 0
            total = len(image_files)
            factor = self.upscale_factor.get()
            tool_dir = self.tool_dir.get()

            executor = ThreadPoolExecutor(max_workers=max(1, self.thread_count.get()))
            futures = {}
            for image_path in image_files:
                if self._stop_event.is_set():
                    break
                future = executor.submit(
                    self._process_single_image, image_path, output_dir, temp_root, factor, tool_dir
                )
                futures[future] = image_path

            pending = set(futures.keys())
            while pending:
                if self._stop_event.is_set():
                    for f in list(pending):
                        if f.cancel():
                            pending.discard(f)
                    if not pending:
                        break

                done = {f for f in pending if f.done()}
                if not done:
                    self._stop_event.wait(timeout=0.2)
                    continue

                for future in done:
                    pending.discard(future)
                    image_path = futures[future]
                    try:
                        if future.result():
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        fail_count += 1
                        self.log(f"❌ {os.path.basename(image_path)}: {e}")

                    current = success_count + fail_count
                    self.root.after(0, lambda v=current: self.progress.config(value=v))
                    self.root.after(
                        0, lambda s=success_count, f=fail_count, t=total:
                        self.progress_label.config(text=f"进度: {s + f}/{t} (成功: {s}, 失败: {f})"))

            if self._stop_event.is_set():
                self.log(f"⚠️ 处理已停止。已处理: {success_count + fail_count}/{total} (成功: {success_count}, 失败: {fail_count})")
            else:
                self.log(f"✅ 处理完成！成功: {success_count}, 失败: {fail_count}")
                self.root.after(0, lambda: self._show_toast(
                    "图片增强完成", f"成功: {success_count}，失败: {fail_count}", "success"))

        except Exception as e:
            logger.error(f"批量处理出错: {e}")
            self.log(f"❌ 处理出错: {e}")

        finally:
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    executor.shutdown(wait=False)
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)
            self.is_processing = False
            self._stop_event.clear()
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))

    def _process_single_image(self, image_path, output_dir, temp_root, factor, tool_dir):
        """处理单张图片：Vulkan 放大 →（可选）GFPGAN 人脸增强 → 无损 PNG。"""
        temp_png = None
        try:
            rel_path = os.path.relpath(image_path, self.input_dir.get())
            stem = os.path.splitext(os.path.basename(rel_path))[0]
            rel_dir = os.path.dirname(rel_path)
            output_path = os.path.join(output_dir, rel_dir, stem + '.png')
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            self.log(f"⏳ 正在处理 {os.path.basename(image_path)}（Vulkan {factor}x）...")

            temp_png = str(temp_root / f"{uuid.uuid4().hex}.png")
            upscale_with_vulkan(image_path, temp_png, tool_dir, factor)

            if self.face_enhance.get() and self.face_enhancer:
                self.log(f"   ↳ 人脸增强: {os.path.basename(image_path)} ...")
                with self._face_lock:
                    enhance_face_image(self.face_enhancer, temp_png, output_path)
                os.remove(temp_png)
                temp_png = None
            else:
                shutil.move(temp_png, output_path)
                temp_png = None

            logger.info(f"增强成功: {image_path} → {output_path}")
            self.log(f"✅ {os.path.basename(image_path)} → {output_path}")
            return True

        except Exception as e:
            logger.error(f"处理失败: {image_path} | {e}")
            self.log(f"❌ {os.path.basename(image_path)}: {e}")
            return False
        finally:
            if temp_png and os.path.exists(temp_png):
                try:
                    os.remove(temp_png)
                except Exception:
                    pass


# 解析默认目录（避免在 import 时即抛错）
def _resolve_defaults():
    global WEIGHTS_DIR, TOOL_DIR
    cfg = CONFIG_FILE
    wdir = DEFAULT_WEIGHTS_DIR
    tdir = DEFAULT_TOOL_DIR
    if cfg.exists():
        try:
            with open(cfg, 'r', encoding='utf-8') as f:
                c = json.load(f)
            if c.get('weights_dir') and os.path.isdir(c['weights_dir']):
                wdir = c['weights_dir']
            if c.get('tool_dir') and os.path.isdir(c['tool_dir']):
                tdir = c['tool_dir']
        except Exception:
            pass
    WEIGHTS_DIR = wdir
    TOOL_DIR = tdir


_resolve_defaults()


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageEnhancerVulkanApp(root)
    root.mainloop()
