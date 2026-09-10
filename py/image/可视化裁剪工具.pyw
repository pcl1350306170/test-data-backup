import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import os
import subprocess
import sys
import queue
from pathlib import Path

# ──────────── 公共日志模块（可选依赖）────────────
# 将 py/ 目录加入搜索路径，以导入 log_utils
_PY_DIR = str(Path(__file__).resolve().parent.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger()   # 自动以本脚本名命名
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

# 尝试导入拖拽支持
try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND2 = True
except ImportError:
    HAS_DND2 = False

class ImageCropperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🖼️ 图片裁剪工具")
        self.root.geometry("1000x650")
        self.root.resizable(True, True)

        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))
        self.style.configure("TCheckbutton", font=("SimHei", 9))

        # 初始化变量
        self.original_image = None  # 原始图片
        self.displayed_image = None  # 显示用的图片
        self.cropped_image = None  # 裁剪后的图片
        self.image_path = None  # 图片路径
        self.scale = 1.0  # 缩放比例
        self.rect_id = None  # 裁剪框ID
        self.selection = None  # 裁剪区域 画布坐标 (x1, y1, x2, y2)
        self.last_save_dir = None  # 上次保存目录
        self.auto_open_dir = tk.BooleanVar(value=False)  # 是否自动打开目录
        self.overwrite_original = tk.BooleanVar(value=False)  # 是否覆盖原文件
        self.reuse_last_crop = tk.BooleanVar(value=False)  # 是否复用上次裁剪区域
        self.auto_execute = tk.BooleanVar(value=False)  # 一键执行：裁剪后自动保存并清空
        self.last_crop_ratios = None  # 上次裁剪区域相对坐标 (x1%, y1%, x2%, y2%)
        self.dnd_queue = queue.Queue()  # 拖拽文件队列（线程安全）

        # 选框交互状态
        self.resize_mode = None  # 当前拖拽模式: None/'nw'/'ne'/'sw'/'se'/'n'/'s'/'e'/'w'/'move'/'new'
        self.drag_start = None  # 拖拽起始点 (x, y)
        self.sel_origin = None  # 拖拽前原始选区 (x1, y1, x2, y2)
        self.HANDLE_MARGIN = 8  # 边缘检测容差（像素）
        self.overlay_ids = []  # 半透明遮罩 id 列表
        self._init_done = False  # 初始化完成标志

        # 创建UI组件
        self.create_widgets()

        # 注册拖拽支持
        self._setup_dnd()

        # 启动拖拽队列轮询
        self._poll_dnd_queue()

        # 标记初始化完成，并延迟执行首次显示
        self.root.after_idle(self._on_init_done)

        logger.info("应用启动完成")

    def _on_init_done(self):
        """初始化完成后执行"""
        self._init_done = True
        # 如果已有图片但还没显示选区，现在显示
        if self.original_image and not self.selection:
            self.root.update_idletasks()
            self.display_original_image()
            self._select_full_image()

    def _setup_dnd(self):
        """设置文件拖拽支持"""
        if HAS_WINDND:
            # 使用 windnd 库（Windows）—— 通过队列解决线程安全问题
            windnd.hook_dropfiles(self.root, func=self._on_windnd_drop)
        elif HAS_DND2:
            # 使用 tkinterdnd2
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_dnd2_drop)
        else:
            # 无拖拽库，使用命令行参数支持
            if len(sys.argv) > 1:
                file_path = sys.argv[1]
                if os.path.isfile(file_path):
                    self.root.after(100, lambda: self._load_image(file_path))

    def _on_windnd_drop(self, files):
        """windnd 拖拽回调（在外部线程中调用，通过队列传递到主线程）"""
        if files:
            try:
                file_path = files[0].decode('gbk', errors='ignore')
                if os.path.isfile(file_path):
                    self.dnd_queue.put(file_path)
            except Exception:
                pass

    def _poll_dnd_queue(self):
        """轮询拖拽队列，在主线程中处理文件"""
        try:
            while True:
                file_path = self.dnd_queue.get_nowait()
                self._load_image(file_path)
        except queue.Empty:
            pass
        # 每100ms轮询一次
        self.root.after(100, self._poll_dnd_queue)

    def _on_dnd2_drop(self, event):
        """tkinterdnd2 拖拽回调"""
        file_path = event.data.strip()
        # 处理可能的花括号包裹路径
        if file_path.startswith('{') and file_path.endswith('}'):
            file_path = file_path[1:-1]
        if os.path.isfile(file_path):
            self._load_image(file_path)

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 按钮区域
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X)

        self.select_btn = ttk.Button(btn_frame, text="选择图片", command=self.select_image)
        self.select_btn.pack(side=tk.LEFT, padx=5)

        self.crop_btn = ttk.Button(btn_frame, text="确认裁剪", command=self.confirm_crop, state=tk.DISABLED)
        self.crop_btn.pack(side=tk.LEFT, padx=5)

        self.save_btn = ttk.Button(btn_frame, text="保存图片", command=self.save_image, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=5)

        self.reset_btn = ttk.Button(btn_frame, text="重置选择", command=self.reset_selection, state=tk.DISABLED)
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        self.clear_btn = ttk.Button(btn_frame, text="🗑️ 清空", command=self.clear_image, state=tk.DISABLED)
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(btn_frame, text="请选择或拖拽一张图片")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # 裁剪尺寸预设
        preset_frame = ttk.Frame(main_frame, padding="5")
        preset_frame.pack(fill=tk.X)

        ttk.Label(preset_frame, text="裁剪尺寸:").pack(side=tk.LEFT, padx=(5, 2))
        self.crop_preset = tk.StringVar(value="自由裁剪")
        self.preset_combo = ttk.Combobox(
            preset_frame,
            textvariable=self.crop_preset,
            values=["自由裁剪", "1:1", "16:9", "9:16", "1920×1080", "1080×1920", "2160×3840", "3840×1920"],
            state="readonly", width=14
        )
        self.preset_combo.pack(side=tk.LEFT, padx=(0, 5))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        ttk.Label(preset_frame, text="选中后自动框选对应比例区域", foreground="gray").pack(side=tk.LEFT, padx=5)

        # 选项区域
        opt_frame = ttk.Frame(main_frame, padding="5")
        opt_frame.pack(fill=tk.X)

        ttk.Checkbutton(
            opt_frame,
            text="保存后自动打开文件所在目录",
            variable=self.auto_open_dir
        ).pack(side=tk.LEFT, padx=5)

        ttk.Checkbutton(
            opt_frame,
            text="保存时直接覆盖原文件",
            variable=self.overwrite_original
        ).pack(side=tk.LEFT, padx=5)

        ttk.Checkbutton(
            opt_frame,
            text="加载新图时复用上次裁剪区域",
            variable=self.reuse_last_crop
        ).pack(side=tk.LEFT, padx=5)

        ttk.Checkbutton(
            opt_frame,
            text="⚡ 一键执行(裁剪后自动保存并清空)",
            variable=self.auto_execute
        ).pack(side=tk.LEFT, padx=5)

        if not HAS_WINDND and not HAS_DND2:
            ttk.Label(opt_frame, text="💡 安装 windnd 或 tkinterdnd2 可启用拖拽功能", foreground="gray").pack(side=tk.RIGHT, padx=5)

        # 图片显示区域
        display_frame = ttk.Frame(main_frame, padding="5")
        display_frame.pack(fill=tk.BOTH, expand=True)

        # 原始图片区域
        ttk.Label(display_frame, text="原始图片 (拖动选框边缘调整 / 空白区域新建选区):").pack(anchor=tk.W)
        self.original_frame = ttk.Frame(display_frame, borderwidth=1, relief=tk.SUNKEN)
        self.original_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.original_canvas = tk.Canvas(self.original_frame, bg="lightgray")
        self.original_canvas.pack(fill=tk.BOTH, expand=True)

        # 绑定鼠标事件
        self.original_canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.original_canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.original_canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.original_canvas.bind("<Motion>", self.on_mouse_move)

        # 裁剪预览区域
        ttk.Label(display_frame, text="裁剪预览:").pack(anchor=tk.W)
        self.preview_frame = ttk.Frame(display_frame, borderwidth=1, relief=tk.SUNKEN)
        self.preview_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.preview_canvas = tk.Canvas(self.preview_frame, bg="lightgray")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        # 绑定窗口大小变化事件
        self.root.bind("<Configure>", self.on_window_resize)

    def select_image(self):
        """选择图片文件"""
        file_path = filedialog.askopenfilename(
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp *.gif")]
        )
        if file_path:
            self._load_image(file_path)

    def _load_image(self, file_path):
        """加载图片文件"""
        self.image_path = file_path
        logger.info(f"加载图片: {file_path}")
        try:
            # 打开图片并转换为RGB模式（处理透明图片）
            self.original_image = Image.open(file_path).convert("RGB")
            img_size = self.original_image.size
            self.status_label.config(text=f"已加载: {os.path.basename(file_path)}")
            logger.info(f"图片加载成功: {os.path.basename(file_path)} 尺寸={img_size}")

            # 重置状态
            self.selection = None
            self.cropped_image = None
            self.resize_mode = None
            self.crop_preset.set("自由裁剪")
            if self.rect_id:
                self.original_canvas.delete(self.rect_id)
                self.rect_id = None
            self._clear_overlay()
            self.preview_canvas.delete("all")
            self.crop_btn.config(state=tk.DISABLED)
            self.save_btn.config(state=tk.DISABLED)

            # 显示图片
            self.display_original_image()

            # 如果勾选了复用上次裁剪区域，且有历史记录，则应用
            if self.reuse_last_crop.get() and self.last_crop_ratios:
                self._apply_crop_ratios(self.last_crop_ratios)
            else:
                # 延迟到画布实际渲染后再框选全图
                self._init_done = False  # 临时禁止resize处理
                self.root.after_idle(self._deferred_select_full)

            # 启用按钮
            self.reset_btn.config(state=tk.NORMAL)
            self.clear_btn.config(state=tk.NORMAL)

        except Exception as e:
            logger.error(f"打开图片失败: {file_path} | {e}")
            messagebox.showerror("错误", f"无法打开图片: {str(e)}")
            self.status_label.config(text="打开图片失败")

    def _deferred_select_full(self):
        """延迟执行的全选操作，确保画布已完成布局"""
        if self.original_image:
            # 强制更新以确保画布尺寸正确
            self.root.update_idletasks()
            self.display_original_image()
            self._select_full_image()
            self._init_done = True  # 标记已完成初始化

    def display_original_image(self):
        """在画布上显示原始图片，自动适应窗口大小"""
        self.original_canvas.delete("all")
        self.overlay_ids = []

        if not self.original_image:
            return

        # 获取画布尺寸
        canvas_width = self.original_canvas.winfo_width()
        canvas_height = self.original_canvas.winfo_height()

        # 如果画布还没渲染，使用默认尺寸
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = 400
            canvas_height = 400

        # 计算缩放比例
        img_width, img_height = self.original_image.size
        self.scale = min(canvas_width / img_width, canvas_height / img_height)

        # 缩放图片
        new_width = int(img_width * self.scale)
        new_height = int(img_height * self.scale)
        self.displayed_image = self.original_image.resize((new_width, new_height), Image.LANCZOS)

        # 计算居中偏移
        self.img_offset_x = (canvas_width - new_width) // 2
        self.img_offset_y = (canvas_height - new_height) // 2

        # 显示图片
        self.tk_image = ImageTk.PhotoImage(self.displayed_image)
        self.original_canvas.create_image(
            self.img_offset_x, self.img_offset_y,
            anchor=tk.NW, image=self.tk_image
        )
        self.original_canvas.image = self.tk_image  # 保持引用

        # 记录图片在画布上的边界
        self.img_x1 = self.img_offset_x
        self.img_y1 = self.img_offset_y
        self.img_x2 = self.img_offset_x + new_width
        self.img_y2 = self.img_offset_y + new_height

    def _select_full_image(self):
        """默认框选完整图片区域"""
        if not self.displayed_image:
            return
        self.selection = (self.img_x1, self.img_y1, self.img_x2, self.img_y2)
        self._draw_selection()
        self._update_crop_state()

    def _draw_selection(self):
        """绘制选框和半透明遮罩"""
        # 清除旧的
        self.original_canvas.delete("rect")
        self._clear_overlay()

        if not self.selection:
            return

        x1, y1, x2, y2 = self.selection

        # 绘制半透明遮罩（选区外区域）
        cw = self.original_canvas.winfo_width()
        ch = self.original_canvas.winfo_height()

        # 上方
        if y1 > 0:
            self.overlay_ids.append(
                self.original_canvas.create_rectangle(
                    0, 0, cw, y1, fill='black', stipple='gray50', tags='rect'))
        # 下方
        if y2 < ch:
            self.overlay_ids.append(
                self.original_canvas.create_rectangle(
                    0, y2, cw, ch, fill='black', stipple='gray50', tags='rect'))
        # 左方
        if x1 > 0:
            self.overlay_ids.append(
                self.original_canvas.create_rectangle(
                    0, y1, x1, y2, fill='black', stipple='gray50', tags='rect'))
        # 右方
        if x2 < cw:
            self.overlay_ids.append(
                self.original_canvas.create_rectangle(
                    x2, y1, cw, y2, fill='black', stipple='gray50', tags='rect'))

        # 绘制选框
        self.rect_id = self.original_canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="red", width=2, dash=(5, 2), tags='rect'
        )

    def _clear_overlay(self):
        """清除遮罩"""
        for oid in self.overlay_ids:
            self.original_canvas.delete(oid)
        self.overlay_ids = []

    # ===================== 鼠标交互 =====================

    def _hit_test(self, mx, my):
        """检测鼠标位置在选框的哪个部位，返回模式字符串"""
        if not self.selection:
            return 'new'

        x1, y1, x2, y2 = self.selection
        m = self.HANDLE_MARGIN

        # 检测四个角
        if abs(mx - x1) <= m and abs(my - y1) <= m:
            return 'nw'
        if abs(mx - x2) <= m and abs(my - y1) <= m:
            return 'ne'
        if abs(mx - x1) <= m and abs(my - y2) <= m:
            return 'sw'
        if abs(mx - x2) <= m and abs(my - y2) <= m:
            return 'se'

        # 检测四条边
        if x1 + m < mx < x2 - m:
            if abs(my - y1) <= m:
                return 'n'
            if abs(my - y2) <= m:
                return 's'
        if y1 + m < my < y2 - m:
            if abs(mx - x1) <= m:
                return 'w'
            if abs(mx - x2) <= m:
                return 'e'

        # 检测是否在选框内部（移动）
        if x1 < mx < x2 and y1 < my < y2:
            return 'move'

        return 'new'

    def _get_cursor(self, mode):
        """根据模式返回鼠标样式"""
        cursors = {
            'nw': 'top_left_corner',
            'ne': 'top_right_corner',
            'sw': 'bottom_left_corner',
            'se': 'bottom_right_corner',
            'n': 'top_side',
            's': 'bottom_side',
            'e': 'right_side',
            'w': 'left_side',
            'move': 'fleur',
            'new': 'crosshair',
        }
        return cursors.get(mode, 'crosshair')

    def on_mouse_move(self, event):
        """鼠标移动事件：更新鼠标样式"""
        if self.resize_mode:
            return  # 拖拽中不更新
        mode = self._hit_test(event.x, event.y)
        self.original_canvas.config(cursor=self._get_cursor(mode))

    def on_mouse_down(self, event):
        """鼠标按下事件"""
        if not self.displayed_image:
            return

        mode = self._hit_test(event.x, event.y)
        self.resize_mode = mode
        self.drag_start = (event.x, event.y)

        if mode == 'new':
            # 新建选区
            self.selection = None
            self._draw_selection()
            self.crop_btn.config(state=tk.DISABLED)
        elif mode == 'move':
            # 移动选区
            self.sel_origin = self.selection
        else:
            # 调整选区大小
            self.sel_origin = self.selection

    def on_mouse_drag(self, event):
        """鼠标拖动事件"""
        if not self.resize_mode or not self.drag_start:
            return

        mx, my = event.x, event.y
        # 限制在图片范围内
        mx = max(self.img_x1, min(self.img_x2, mx))
        my = max(self.img_y1, min(self.img_y2, my))

        mode = self.resize_mode
        dx = mx - self.drag_start[0]
        dy = my - self.drag_start[1]

        if mode == 'new':
            # 新建选区：从起点到当前点
            sx, sy = self.drag_start
            sx = max(self.img_x1, min(self.img_x2, sx))
            sy = max(self.img_y1, min(self.img_y2, sy))
            self.selection = (
                min(sx, mx), min(sy, my),
                max(sx, mx), max(sy, my)
            )
        elif mode == 'move':
            ox1, oy1, ox2, oy2 = self.sel_origin
            w, h = ox2 - ox1, oy2 - oy1
            nx1 = ox1 + dx
            ny1 = oy1 + dy
            # 限制不超出图片边界
            nx1 = max(self.img_x1, min(self.img_x2 - w, nx1))
            ny1 = max(self.img_y1, min(self.img_y2 - h, ny1))
            self.selection = (nx1, ny1, nx1 + w, ny1 + h)
        else:
            # 调整大小
            ox1, oy1, ox2, oy2 = self.sel_origin
            nx1, ny1, nx2, ny2 = ox1, oy1, ox2, oy2

            if 'w' in mode:
                nx1 = min(mx, ox2 - 10)
            if 'e' in mode:
                nx2 = max(mx, ox1 + 10)
            if 'n' in mode:
                ny1 = min(my, oy2 - 10)
            if 's' in mode:
                ny2 = max(my, oy1 + 10)

            self.selection = (nx1, ny1, nx2, ny2)

        self._draw_selection()
        self._update_crop_state()

    def on_mouse_up(self, event):
        """鼠标释放事件"""
        if not self.resize_mode:
            return

        self.resize_mode = None
        self.drag_start = None
        self.sel_origin = None

        # 检查选区是否有效
        if self.selection:
            x1, y1, x2, y2 = self.selection
            if (x2 - x1) < 10 or (y2 - y1) < 10:
                self.selection = None
                self._draw_selection()
                self.crop_btn.config(state=tk.DISABLED)
                self.status_label.config(text="裁剪区域太小，请重新选择")
                return

        self._update_crop_state()

    def _update_crop_state(self):
        """更新裁剪状态和预览（画布坐标 → 原图坐标）"""
        if not self.selection or not self.original_image:
            self.crop_btn.config(state=tk.DISABLED)
            return

        # 转换为原图坐标
        x1, y1, x2, y2 = self.selection
        orig_x1 = int((x1 - self.img_x1) / self.scale)
        orig_y1 = int((y1 - self.img_y1) / self.scale)
        orig_x2 = int((x2 - self.img_x1) / self.scale)
        orig_y2 = int((y2 - self.img_y1) / self.scale)

        # 限制在图片范围内
        img_w, img_h = self.original_image.size
        orig_x1 = max(0, min(img_w, orig_x1))
        orig_y1 = max(0, min(img_h, orig_y1))
        orig_x2 = max(0, min(img_w, orig_x2))
        orig_y2 = max(0, min(img_h, orig_y2))

        if (orig_x2 - orig_x1) >= 10 and (orig_y2 - orig_y1) >= 10:
            # 用原图坐标裁剪
            self.cropped_image = self.original_image.crop((orig_x1, orig_y1, orig_x2, orig_y2))
            # 预览（不再重新裁剪，直接显示已有的 cropped_image）
            self._show_preview()
            self.crop_btn.config(state=tk.NORMAL)
            self.status_label.config(text=f"裁剪区域: {orig_x2-orig_x1}x{orig_y2-orig_y1} 像素")

            # 保存当前裁剪区域为相对坐标（用于复用）
            self.last_crop_ratios = (
                orig_x1 / img_w, orig_y1 / img_h,
                orig_x2 / img_w, orig_y2 / img_h
            )
        else:
            self.crop_btn.config(state=tk.DISABLED)

    def _apply_crop_ratios(self, ratios):
        """根据相对坐标比例应用裁剪区域"""
        if not self.original_image or not ratios:
            self._init_done = False
            self.root.after_idle(self._deferred_select_full)
            return

        rx1, ry1, rx2, ry2 = ratios
        img_w, img_h = self.original_image.size

        # 转换为原图坐标
        orig_x1 = int(rx1 * img_w)
        orig_y1 = int(ry1 * img_h)
        orig_x2 = int(rx2 * img_w)
        orig_y2 = int(ry2 * img_h)

        # 确保有效
        if (orig_x2 - orig_x1) < 10 or (orig_y2 - orig_y1) < 10:
            self._init_done = False
            self.root.after_idle(self._deferred_select_full)
            return

        # 转换为画布坐标
        canvas_x1 = int(orig_x1 * self.scale) + self.img_x1
        canvas_y1 = int(orig_y1 * self.scale) + self.img_y1
        canvas_x2 = int(orig_x2 * self.scale) + self.img_x1
        canvas_y2 = int(orig_y2 * self.scale) + self.img_y1

        # 限制在图片边界内
        canvas_x1 = max(self.img_x1, min(self.img_x2, canvas_x1))
        canvas_y1 = max(self.img_y1, min(self.img_y2, canvas_y1))
        canvas_x2 = max(self.img_x1, min(self.img_x2, canvas_x2))
        canvas_y2 = max(self.img_y1, min(self.img_y2, canvas_y2))

        self.selection = (canvas_x1, canvas_y1, canvas_x2, canvas_y2)
        self._draw_selection()
        self._update_crop_state()
        self._init_done = True
        logger.info(f"复用上次裁剪区域: {orig_x2-orig_x1}x{orig_y2-orig_y1} 像素")

    def _show_preview(self):
        """在预览画布上显示已裁剪的图片（不重新裁剪）"""
        if not self.cropped_image:
            return

        self.preview_canvas.delete("all")

        # 获取预览画布尺寸
        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = 400
            canvas_height = 400

        # 计算缩放比例
        img_width, img_height = self.cropped_image.size
        scale = min(canvas_width / img_width, canvas_height / img_height)

        # 缩放图片
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        preview_img = self.cropped_image.resize((new_width, new_height), Image.LANCZOS)

        # 显示预览图片
        self.preview_tk_img = ImageTk.PhotoImage(preview_img)
        self.preview_canvas.create_image(
            canvas_width//2 - new_width//2,
            canvas_height//2 - new_height//2,
            anchor=tk.NW,
            image=self.preview_tk_img
        )
        self.preview_canvas.image = self.preview_tk_img  # 保持引用

    def confirm_crop(self):
        """确认裁剪，更新原始图片为裁剪后的图片"""
        if not self.cropped_image:
            return

        crop_size = self.cropped_image.size
        # 更新原始图片为裁剪后的图片
        self.original_image = self.cropped_image.copy()
        self.display_original_image()

        # 重置选择状态
        self.reset_selection()

        # 更新状态
        self.status_label.config(text="裁剪完成，可以保存或继续裁剪")
        self.save_btn.config(state=tk.NORMAL)
        logger.info(f"裁剪完成，新尺寸={crop_size}")

        # 一键执行：自动保存并清空
        if self.auto_execute.get():
            saved = self.save_image()
            if saved:
                self.clear_image()

    def save_image(self):
        """保存裁剪后的图片，返回是否保存成功"""
        if not self.original_image:
            return False

        # 如果勾选了覆盖原文件，直接保存
        if self.overwrite_original.get() and self.image_path:
            return self._do_save(self.image_path)

        # 否则弹出保存对话框
        # 生成默认文件名
        if self.image_path:
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            default_filename = f"{base_name}_cropped.png"
        else:
            default_filename = "cropped_image.png"

        # 确定初始目录
        initial_dir = None
        if self.last_save_dir and os.path.isdir(self.last_save_dir):
            initial_dir = self.last_save_dir
        elif self.image_path:
            initial_dir = os.path.dirname(self.image_path)

        # 询问保存路径
        save_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[
                ("PNG图片", "*.png"),
                ("JPEG图片", "*.jpg"),
                ("BMP图片", "*.bmp")
            ],
            initialfile=default_filename,
            initialdir=initial_dir
        )

        if save_path:
            return self._do_save(save_path)
        return False

    def _do_save(self, save_path):
        """执行保存操作，返回是否成功"""
        try:
            # 根据文件扩展名选择保存格式
            if save_path.lower().endswith('.png'):
                self.original_image.save(save_path, 'PNG')
            elif save_path.lower().endswith('.jpg') or save_path.lower().endswith('.jpeg'):
                self.original_image.save(save_path, 'JPEG', quality=95)
            else:
                self.original_image.save(save_path, 'BMP')

            save_dir = os.path.dirname(save_path)
            self.last_save_dir = save_dir
            self.status_label.config(text=f"已保存至: {save_path}")
            logger.info(f"图片已保存: {save_path}")

            # 显示 Toast 通知
            self._show_toast("✅ 保存成功", os.path.basename(save_path))

            # 如果勾选了自动打开目录
            if self.auto_open_dir.get():
                self._open_directory(save_dir)
            return True

        except Exception as e:
            logger.error(f"保存图片失败: {save_path} | {e}")
            messagebox.showerror("错误", f"保存图片失败: {str(e)}")
            self.status_label.config(text="保存图片失败")
            return False

    def _show_toast(self, title, message, duration_ms=3000):
        """右下角弹窗通知"""
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)
            toast.configure(bg='#2e7d32', padx=2, pady=2)

            # 关闭按钮
            close_btn = tk.Label(toast, text="✕", bg='#2e7d32', fg='white',
                                 font=('Arial', 10, 'bold'), cursor='hand2')
            close_btn.place(relx=1.0, x=-20, y=5)
            close_btn.bind('<Button-1>', lambda e: toast.destroy())

            # 标题
            tk.Label(toast, text=title, bg='#2e7d32', fg='white',
                     font=('Microsoft YaHei UI', 11, 'bold'), anchor='w').pack(
                fill=tk.X, padx=(15, 30), pady=(10, 3))

            # 内容
            tk.Label(toast, text=message, bg='#2e7d32', fg='#e8f5e9',
                     font=('Microsoft YaHei UI', 9), anchor='w',
                     wraplength=280).pack(fill=tk.X, padx=(15, 15), pady=(0, 10))

            # 点击任意处关闭
            for w in [toast]:
                w.bind('<Button-1>', lambda e: toast.destroy())

            # 计算位置：右下角
            toast.update_idletasks()
            sw = toast.winfo_screenwidth()
            sh = toast.winfo_screenheight()
            x = sw - 320 - 20
            y = sh - 90 - 60
            toast.geometry(f"300x80+{x}+{y}")
            toast.deiconify()

            # 自动关闭
            toast.after(duration_ms, lambda: toast.destroy() if toast.winfo_exists() else None)
        except Exception:
            pass

    def _open_directory(self, directory):
        """打开文件目录"""
        try:
            if sys.platform == 'win32':
                os.startfile(directory)
            elif sys.platform == 'darwin':
                subprocess.run(['open', directory])
            else:
                subprocess.run(['xdg-open', directory])
        except Exception as e:
            messagebox.showwarning("提示", f"无法打开目录: {e}")

    def clear_image(self):
        """清空当前图片，恢复初始状态"""
        logger.info("清空图片，恢复初始状态")
        self.original_image = None
        self.displayed_image = None
        self.cropped_image = None
        self.image_path = None
        self.selection = None
        self.resize_mode = None
        self.drag_start = None
        self.sel_origin = None
        self.crop_preset.set("自由裁剪")

        # 清除画布
        self.original_canvas.delete("all")
        self._clear_overlay()
        self.preview_canvas.delete("all")

        # 重置按钮
        self.crop_btn.config(state=tk.DISABLED)
        self.save_btn.config(state=tk.DISABLED)
        self.reset_btn.config(state=tk.DISABLED)
        self.clear_btn.config(state=tk.DISABLED)
        self.status_label.config(text="请选择或拖拽一张图片")

    def _on_preset_selected(self, event=None):
        """裁剪尺寸预设被选中"""
        if not self.original_image:
            return

        preset = self.crop_preset.get()
        if preset == "自由裁剪":
            return

        # 解析预设尺寸/比例
        try:
            if ":" in preset:
                # 比例格式，如 "16:9"
                w_str, h_str = preset.split(":")
            else:
                # 尺寸格式，如 "1920×1080"
                w_str, h_str = preset.replace("×", "x").split("x")
            target_w = int(w_str)
            target_h = int(h_str)
        except (ValueError, IndexError):
            return

        # 计算目标宽高比
        target_ratio = target_w / target_h

        # 获取原图尺寸
        img_w, img_h = self.original_image.size
        img_ratio = img_w / img_h

        # 计算在原图范围内最大化的裁剪区域（保持目标比例）
        if img_ratio > target_ratio:
            # 原图更宽，以高度为基准
            crop_h = img_h
            crop_w = int(img_h * target_ratio)
        else:
            # 原图更高，以宽度为基准
            crop_w = img_w
            crop_h = int(img_w / target_ratio)

        # 居中裁剪
        orig_x1 = (img_w - crop_w) // 2
        orig_y1 = (img_h - crop_h) // 2
        orig_x2 = orig_x1 + crop_w
        orig_y2 = orig_y1 + crop_h

        # 转换为画布坐标
        canvas_x1 = int(orig_x1 * self.scale) + self.img_x1
        canvas_y1 = int(orig_y1 * self.scale) + self.img_y1
        canvas_x2 = int(orig_x2 * self.scale) + self.img_x1
        canvas_y2 = int(orig_y2 * self.scale) + self.img_y1

        # 限制在图片边界内
        canvas_x1 = max(self.img_x1, min(self.img_x2, canvas_x1))
        canvas_y1 = max(self.img_y1, min(self.img_y2, canvas_y1))
        canvas_x2 = max(self.img_x1, min(self.img_x2, canvas_x2))
        canvas_y2 = max(self.img_y1, min(self.img_y2, canvas_y2))

        self.selection = (canvas_x1, canvas_y1, canvas_x2, canvas_y2)
        self._draw_selection()
        self._update_crop_state()

        logger.info(f"应用裁剪预设: {preset} ({crop_w}×{crop_h})")
        self.status_label.config(
            text=f"预设: {preset} | 裁剪区域: {crop_w}×{crop_h} 像素")

    def reset_selection(self):
        """重置裁剪选择"""
        # 清除裁剪框和遮罩
        if self.rect_id:
            self.original_canvas.delete(self.rect_id)
            self.rect_id = None
        self._clear_overlay()

        # 清除预览
        self.preview_canvas.delete("all")

        # 重置变量
        self.selection = None
        self.cropped_image = None
        self.resize_mode = None
        self.drag_start = None
        self.sel_origin = None

        # 重置预设
        self.crop_preset.set("自由裁剪")

        # 更新按钮状态
        self.crop_btn.config(state=tk.DISABLED)

        # 如果有图片，重新显示并全选
        if self.original_image:
            self.display_original_image()
            self._select_full_image()

    def on_window_resize(self, event):
        """窗口大小变化时重新调整图片显示"""
        if not self._init_done:
            return  # 初始化阶段不处理
        if event.widget == self.root and self.original_image:
            # 保存旧的缩放和偏移信息
            old_scale = getattr(self, 'scale', 1.0)
            old_img_x1 = getattr(self, 'img_x1', 0)
            old_img_y1 = getattr(self, 'img_y1', 0)
            old_selection = self.selection

            # 强制更新后再获取真实画布尺寸
            self.root.update_idletasks()
            self.display_original_image()

            # 如果有选区，按比例重新映射选区坐标
            if old_selection and old_scale > 0:
                ox1, oy1, ox2, oy2 = old_selection
                # 从旧画布坐标 → 原图坐标 → 新画布坐标
                rx1 = int((ox1 - old_img_x1) / old_scale * self.scale) + self.img_x1
                ry1 = int((oy1 - old_img_y1) / old_scale * self.scale) + self.img_y1
                rx2 = int((ox2 - old_img_x1) / old_scale * self.scale) + self.img_x1
                ry2 = int((oy2 - old_img_y1) / old_scale * self.scale) + self.img_y1
                # 限制在图片边界内
                rx1 = max(self.img_x1, min(self.img_x2, rx1))
                ry1 = max(self.img_y1, min(self.img_y2, ry1))
                rx2 = max(self.img_x1, min(self.img_x2, rx2))
                ry2 = max(self.img_y1, min(self.img_y2, ry2))
                self.selection = (rx1, ry1, rx2, ry2)
                self._draw_selection()
                self._update_crop_state()

if __name__ == "__main__":
    # 根据可用的拖拽库选择根窗口类型
    if HAS_DND2:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = ImageCropperApp(root)
    root.mainloop()
