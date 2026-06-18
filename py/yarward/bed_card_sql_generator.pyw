# bed_card_sql_generator.pyw
"""
床头卡SQL脚本生成工具

功能：
1. 可视化界面，保存配置，记录日志
2. 输出"床头卡脚本.sql"文件，可选择输出目录
3. 图片上传/粘贴，自动压缩到30k以内并转base64
"""

import os
import json
import uuid
import base64
import io
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image, ImageGrab
except ImportError:
    print("=" * 50)
    print("缺少依赖: Pillow")
    print("请运行: pip install Pillow")
    print("=" * 50)
    raise SystemExit(1)

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "bed_card_sql_generator"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

MAX_IMAGE_BYTES = 30 * 1024  # 30 KB

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 默认配置
DEFAULT_CONFIG = {
    "label": "",
    "path": "",
    "type_value": "床头分机-1024*600",
    "output_dir": "",
    "include_alter": True
}

TYPE_OPTIONS = [
    "床头分机-1024*600",
    "床旁分机-1920*1080",
    "手动输入"
]


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


class BedCardSqlApp:
    def __init__(self, root):
        self.root = root
        root.title("床头卡SQL脚本生成工具")
        root.geometry("800x700")
        root.minsize(700, 600)

        self.image_data = None  # 存储压缩后的图片base64
        self.image_preview = None  # 存储PIL图片用于预览

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        pad = dict(padx=10, pady=4)

        # --- 模板名称 ---
        f_label = ttk.LabelFrame(self.root, text="模板名称 (label)", padding="5")
        f_label.pack(fill="x", **pad)
        self.var_label = tk.StringVar()
        ttk.Entry(f_label, textvariable=self.var_label, width=60).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )

        # --- 文件路径 ---
        f_path = ttk.LabelFrame(self.root, text="文件路径 (path)", padding="5")
        f_path.pack(fill="x", **pad)
        self.var_path = tk.StringVar()
        ttk.Entry(f_path, textvariable=self.var_path, width=60).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )

        # --- 类型选择 ---
        f_type = ttk.LabelFrame(self.root, text="类型 (type)", padding="5")
        f_type.pack(fill="x", **pad)

        self.var_type = tk.StringVar(value=TYPE_OPTIONS[0])
        self.combo_type = ttk.Combobox(
            f_type, textvariable=self.var_type,
            values=TYPE_OPTIONS, width=30, state="readonly"
        )
        self.combo_type.pack(side="left", padx=6, pady=6)
        self.combo_type.bind("<<ComboboxSelected>>", self._on_type_selected)

        self.var_type_custom = tk.StringVar()
        self.entry_type_custom = ttk.Entry(
            f_type, textvariable=self.var_type_custom, width=30
        )
        self.entry_type_custom.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        self.entry_type_custom.pack_forget()  # 默认隐藏

        # --- 图片上传 ---
        f_img = ttk.LabelFrame(self.root, text="图片 (image) - 自动压缩到30KB以内并转Base64", padding="5")
        f_img.pack(fill="x", **pad)

        btn_frame = ttk.Frame(f_img)
        btn_frame.pack(fill="x", padx=6, pady=4)

        ttk.Button(btn_frame, text="选择图片...", command=self._select_image).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="从剪贴板粘贴", command=self._paste_image).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="清空图片", command=self._clear_image).pack(
            side="left", padx=4
        )

        self.lbl_img_info = ttk.Label(f_img, text="未选择图片", foreground="gray")
        self.lbl_img_info.pack(anchor="w", padx=6, pady=2)

        # 图片预览区域
        self.canvas_preview = tk.Canvas(f_img, width=200, height=120, bg="#f0f0f0")
        self.canvas_preview.pack(padx=6, pady=4)

        # --- 输出设置 ---
        f_out = ttk.LabelFrame(self.root, text="输出设置", padding="5")
        f_out.pack(fill="x", **pad)

        self.var_include_alter = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f_out, text="包含 ALTER TABLE 语句（修改image字段类型为LONGTEXT）",
            variable=self.var_include_alter
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Label(f_out, text="输出目录:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.var_output_dir = tk.StringVar()
        ttk.Entry(f_out, textvariable=self.var_output_dir, width=50).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Button(f_out, text="浏览...", command=self._select_output_dir).grid(
            row=1, column=2, padx=4, pady=4
        )
        f_out.columnconfigure(1, weight=1)

        # --- 日志 ---
        f_log = ttk.LabelFrame(self.root, text="日志", padding="5")
        f_log.pack(fill="both", expand=True, **pad)

        self.log_text = scrolledtext.ScrolledText(
            f_log, state="disabled", wrap=tk.WORD, height=8, font=("Consolas", 9)
        )
        self.log_text.pack(fill="both", expand=True, padx=6, pady=4)

        # --- 按钮 ---
        f_btn = ttk.Frame(self.root)
        f_btn.pack(fill="x", padx=10, pady=8)

        ttk.Button(f_btn, text="保存配置", command=self._save_current_config).pack(
            side="left", padx=6
        )
        ttk.Button(
            f_btn, text="生成SQL脚本", command=self._generate_sql, style="Accent.TButton"
        ).pack(side="right", padx=6)

    # ────────────── 日志 ──────────────
    def _log(self, message: str, level=logging.INFO):
        """同时写入日志文件和界面"""
        logging.log(level, message)
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{datetime.now():%H:%M:%S}] {message}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ────────────── 配置 ──────────────
    def _load_config(self):
        """加载配置并填充UI"""
        config = load_config()
        self.var_label.set(config.get("label", ""))
        self.var_path.set(config.get("path", ""))
        self.var_output_dir.set(config.get("output_dir", ""))
        self.var_include_alter.set(config.get("include_alter", True))

        type_val = config.get("type_value", TYPE_OPTIONS[0])
        if type_val in TYPE_OPTIONS:
            self.var_type.set(type_val)
            self.entry_type_custom.pack_forget()
        else:
            self.var_type.set("手动输入")
            self.var_type_custom.set(type_val)
            self.entry_type_custom.pack(side="left", fill="x", expand=True, padx=6, pady=6)

        self._log("配置已加载")

    def _save_current_config(self):
        """保存当前配置"""
        type_val = self.var_type.get()
        if type_val == "手动输入":
            type_val = self.var_type_custom.get()

        config = {
            "label": self.var_label.get(),
            "path": self.var_path.get(),
            "type_value": type_val,
            "output_dir": self.var_output_dir.get(),
            "include_alter": self.var_include_alter.get()
        }
        if save_config(config):
            self._log("配置已保存")

    # ────────────── 类型选择 ──────────────
    def _on_type_selected(self, event=None):
        if self.var_type.get() == "手动输入":
            self.entry_type_custom.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        else:
            self.entry_type_custom.pack_forget()

    # ────────────── 图片处理 ──────────────
    def _select_image(self):
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"), ("所有文件", "*.*")]
        )
        if file_path:
            self._process_image_file(file_path)

    def _paste_image(self):
        """从剪贴板获取图片"""
        try:
            img = ImageGrab.grabclipboard()
            if img is None:
                messagebox.showwarning("提示", "剪贴板中没有图片")
                return
            if isinstance(img, list):
                # 可能是文件路径列表
                for item in img:
                    if isinstance(item, str) and Path(item).exists():
                        self._process_image_file(item)
                        return
                messagebox.showwarning("提示", "剪贴板中没有有效的图片")
                return
            self._compress_and_set_image(img)
        except Exception as e:
            messagebox.showerror("错误", f"从剪贴板获取图片失败: {e}")

    def _process_image_file(self, file_path):
        """处理图片文件"""
        try:
            img = Image.open(file_path)
            self._compress_and_set_image(img)
        except Exception as e:
            messagebox.showerror("错误", f"打开图片失败: {e}")

    def _compress_and_set_image(self, img: Image.Image):
        """压缩图片到30KB以内并设置"""
        # 转换为RGB模式（去掉alpha通道）
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 二分法压缩
        quality_low, quality_high = 10, 95
        best_data = None
        best_quality = quality_high

        while quality_low <= quality_high:
            mid = (quality_low + quality_high) // 2
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=mid, optimize=True)
            size = buf.tell()

            if size <= MAX_IMAGE_BYTES:
                best_data = buf.getvalue()
                best_quality = mid
                quality_low = mid + 1  # 尝试更高质量
            else:
                quality_high = mid - 1

        # 如果最低质量还是太大，缩小图片尺寸
        if best_data is None:
            scale = 0.9
            while scale > 0.1:
                new_size = (int(img.width * scale), int(img.height * scale))
                resized = img.resize(new_size, Image.LANCZOS)
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=50, optimize=True)
                size = buf.tell()
                if size <= MAX_IMAGE_BYTES:
                    best_data = buf.getvalue()
                    best_quality = 50
                    self._log(f"图片尺寸过大，缩放至 {new_size[0]}x{new_size[1]}")
                    break
                scale -= 0.1

        if best_data is None:
            messagebox.showerror("错误", "无法将图片压缩到30KB以内")
            return

        # 转base64，拼接 Data URI 前缀
        b64_str = base64.b64encode(best_data).decode('ascii')
        self.image_data = f"data:image/jpeg;base64,{b64_str}"
        self.image_preview = img.copy()

        size_kb = len(best_data) / 1024
        self.lbl_img_info.config(
            text=f"已加载: {len(self.image_data)} 字符 (压缩后 {size_kb:.1f} KB, quality={best_quality})",
            foreground="green"
        )
        self._log(f"图片已压缩: {size_kb:.1f} KB, quality={best_quality}, base64长度={len(self.image_data)}")

        # 显示预览
        self._show_preview(img)

    def _show_preview(self, img: Image.Image):
        """在Canvas上显示图片预览"""
        self.canvas_preview.delete("all")
        # 缩放图片适应canvas
        canvas_w, canvas_h = 200, 120
        ratio = min(canvas_w / img.width, canvas_h / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        preview_img = img.resize(new_size, Image.LANCZOS)

        # 转换为PhotoImage
        from PIL import ImageTk
        self._preview_photo = ImageTk.PhotoImage(preview_img)
        x = (canvas_w - new_size[0]) // 2
        y = (canvas_h - new_size[1]) // 2
        self.canvas_preview.create_image(x, y, anchor="nw", image=self._preview_photo)

    def _clear_image(self):
        """清空图片"""
        self.image_data = None
        self.image_preview = None
        self.lbl_img_info.config(text="未选择图片", foreground="gray")
        self.canvas_preview.delete("all")
        self._log("图片已清空")

    # ────────────── 输出目录 ──────────────
    def _select_output_dir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.var_output_dir.set(d)

    # ────────────── 生成SQL ──────────────
    def _generate_sql(self):
        """验证输入并生成SQL脚本"""
        # 验证
        label = self.var_label.get().strip()
        if not label:
            messagebox.showerror("错误", "请输入模板名称")
            return

        path = self.var_path.get().strip()
        if not path:
            messagebox.showerror("错误", "请输入文件路径")
            return

        type_val = self.var_type.get()
        if type_val == "手动输入":
            type_val = self.var_type_custom.get().strip()
            if not type_val:
                messagebox.showerror("错误", "请输入类型")
                return

        if not self.image_data:
            messagebox.showerror("错误", "请选择或粘贴图片")
            return

        output_dir = self.var_output_dir.get().strip()
        if not output_dir:
            messagebox.showerror("错误", "请选择输出目录")
            return

        if not Path(output_dir).exists():
            messagebox.showerror("错误", f"输出目录不存在: {output_dir}")
            return

        # 生成SQL
        record_id = uuid.uuid4().hex[:16]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        include_alter = self.var_include_alter.get()

        sql_lines = []

        if include_alter:
            sql_lines.append("-- 修改字段的类型")
            sql_lines.append("ALTER TABLE `wn_bedHeadConfig`")
            sql_lines.append("MODIFY COLUMN `image` LONGTEXT;")
            sql_lines.append("")

        sql_lines.append(f"-- 模板: {label}")
        sql_lines.append(f"-- 生成时间: {now_str}")
        sql_lines.append("")
        sql_lines.append(
            f"INSERT INTO `YHDB`.`wn_bedHeadConfig` "
            f"(`id`, `label`, `path`, `image`, `type`, `createUser`, `createTime`, "
            f"`updateUser`, `updateTime`, `isDelete`, `isEnable`) VALUES "
            f"('{record_id}', '{label}', '{path}', '{self.image_data}', '{type_val}', "
            f"'', '{now_str}', '', '{now_str}', '0', '1');"
        )

        sql_content = "\n".join(sql_lines)

        # 写入文件
        output_path = Path(output_dir) / "床头卡脚本.sql"
        try:
            output_path.write_text(sql_content, encoding='utf-8')
            self._log(f"SQL脚本已生成: {output_path}")
            self._log(f"  ID: {record_id}")
            self._log(f"  模板: {label}")
            self._log(f"  路径: {path}")
            self._log(f"  类型: {type_val}")

            # 保存配置
            self._save_current_config()

            messagebox.showinfo(
                "成功",
                f"SQL脚本已生成！\n\n"
                f"文件: {output_path}\n"
                f"ID: {record_id}"
            )

            # 打开目录
            os.startfile(output_dir)

        except Exception as e:
            self._log(f"生成SQL失败: {e}", logging.ERROR)
            messagebox.showerror("错误", f"生成SQL脚本失败: {e}")


def main():
    root = tk.Tk()
    BedCardSqlApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
