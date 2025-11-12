import os
import json
from tkinter import *
from tkinter import filedialog, colorchooser, messagebox
from PIL import Image, ImageTk, ImageEnhance

# 确保json目录存在
JSON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json")
os.makedirs(JSON_DIR, exist_ok=True)

# 配置文件和历史记录文件路径
CONFIG_FILE = os.path.join(JSON_DIR, "image_composer_config.json")


class ImageOverlayApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片叠加与预览工具")

        # 默认参数
        self.bg_mode = StringVar(value="color")
        self.bg_color = "#FFFFFF"
        self.bg_image = None
        self.image_a = None
        self.image_a_path = None
        self.scale_percent = DoubleVar(value=100)
        self.alpha = DoubleVar(value=100)
        self.pos_x = IntVar(value=0)
        self.pos_y = IntVar(value=0)
        self.last_params_file = CONFIG_FILE

        # 拖拽相关变量
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.preview_scale = 1.0  # 预览图缩放比例

        self.load_last_params()

        # ======= 控件区域 =======
        frame = Frame(root)
        frame.pack(side=LEFT, fill=Y, padx=10, pady=10)

        Button(frame, text="选择图片A", command=self.load_image_a).pack(fill=X)
        Radiobutton(frame, text="使用背景图", variable=self.bg_mode, value="image", command=self.select_bg_image).pack(anchor=W)
        Radiobutton(frame, text="使用纯色背景", variable=self.bg_mode, value="color", command=self.select_bg_color).pack(anchor=W)

        Label(frame, text="缩放比例（%）").pack(anchor=W)
        Scale(frame, from_=10, to=200, orient=HORIZONTAL, variable=self.scale_percent, command=lambda v:self.update_preview()).pack(fill=X)

        Label(frame, text="透明度（%）").pack(anchor=W)
        Scale(frame, from_=0, to=100, orient=HORIZONTAL, variable=self.alpha, command=lambda v:self.update_preview()).pack(fill=X)

        Label(frame, text="X坐标").pack(anchor=W)
        Entry(frame, textvariable=self.pos_x).pack(fill=X)
        Label(frame, text="Y坐标").pack(anchor=W)
        Entry(frame, textvariable=self.pos_y).pack(fill=X)
        Button(frame, text="刷新预览", command=self.update_preview).pack(fill=X, pady=5)

        Button(frame, text="居中", command=self.center_image).pack(fill=X)
        Button(frame, text="导出图片", command=self.export_result).pack(fill=X, pady=5)

        # 预览区域 - 添加鼠标事件绑定
        self.preview_label = Label(root, bg="#ddd")
        self.preview_label.pack(side=RIGHT, expand=True, fill=BOTH)
        self.preview_label.bind("<Button-1>", self.on_drag_start)
        self.preview_label.bind("<B1-Motion>", self.on_drag_motion)
        self.preview_label.bind("<ButtonRelease-1>", self.on_drag_end)

        self.update_preview()

    def load_image_a(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.gif;*.webp")])
        if path:
            self.image_a_path = path
            self.image_a = Image.open(path).convert("RGBA")
            self.update_preview()

    def select_bg_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.gif;*.webp")])
        if path:
            self.bg_image = Image.open(path).convert("RGBA")
            self.update_preview()

    def select_bg_color(self):
        color = colorchooser.askcolor(title="选择背景颜色")[1]
        if color:
            self.bg_color = color
            self.bg_image = None
            self.update_preview()

    def center_image(self):
        if not self.image_a:
            return
        bg_w, bg_h = self.get_bg_size()
        scaled_w, scaled_h = self.get_scaled_size()
        self.pos_x.set((bg_w - scaled_w) // 2)
        self.pos_y.set((bg_h - scaled_h) // 2)
        self.update_preview()

    def get_bg_size(self):
        if self.bg_image:
            return self.bg_image.size
        else:
            return (800, 600)

    def get_scaled_size(self):
        if not self.image_a:
            return (0, 0)
        scale = self.scale_percent.get() / 100.0
        w = int(self.image_a.width * scale)
        h = int(self.image_a.height * scale)
        return (w, h)

    def update_preview(self):
        bg_w, bg_h = self.get_bg_size()

        # 背景
        if self.bg_image:
            bg = self.bg_image.copy()
        else:
            bg = Image.new("RGBA", (bg_w, bg_h), self.bg_color)

        # 图片A叠加
        if self.image_a:
            scaled_w, scaled_h = self.get_scaled_size()
            img = self.image_a.resize((scaled_w, scaled_h), Image.LANCZOS)
            alpha_val = self.alpha.get() / 100.0
            if alpha_val < 1:
                # 创建透明度掩码
                alpha_mask = img.split()[3].point(lambda p: p * alpha_val)
                img = img.copy()
                img.putalpha(alpha_mask)
            bg.paste(img, (self.pos_x.get(), self.pos_y.get()), img)

        # 计算预览缩放比例
        orig_width, orig_height = bg.size
        max_preview_size = (800, 600)
        self.preview_scale = min(max_preview_size[0]/orig_width, max_preview_size[1]/orig_height, 1.0)

        # 生成预览图
        preview = bg.copy()
        preview_width = int(orig_width * self.preview_scale)
        preview_height = int(orig_height * self.preview_scale)
        preview = preview.resize((preview_width, preview_height), Image.LANCZOS)

        tk_img = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=tk_img)
        self.preview_label.image = tk_img
        # 存储原始尺寸用于拖拽计算
        self.preview_original_size = (orig_width, orig_height)

    def on_drag_start(self, event):
        """开始拖拽"""
        if not self.image_a:
            return

        # 检查点击位置是否在图片A上
        bg_w, bg_h = self.get_bg_size()
        scaled_w, scaled_h = self.get_scaled_size()
        x, y = self.pos_x.get(), self.pos_y.get()

        # 将预览窗口坐标转换为原始图像坐标
        orig_x = event.x / self.preview_scale
        orig_y = event.y / self.preview_scale

        # 判断是否点击在图片A区域内
        if (x <= orig_x <= x + scaled_w) and (y <= orig_y <= y + scaled_h):
            self.dragging = True
            self.drag_start_x = orig_x - x
            self.drag_start_y = orig_y - y

    def on_drag_motion(self, event):
        """拖拽过程中更新位置"""
        if self.dragging and self.image_a:
            # 将预览窗口坐标转换为原始图像坐标
            orig_x = event.x / self.preview_scale
            orig_y = event.y / self.preview_scale

            # 计算新位置
            new_x = int(orig_x - self.drag_start_x)
            new_y = int(orig_y - self.drag_start_y)

            # 更新坐标
            self.pos_x.set(new_x)
            self.pos_y.set(new_y)
            self.update_preview()

    def on_drag_end(self, event):
        """结束拖拽"""
        self.dragging = False

    def export_result(self):
        if not self.image_a:
            messagebox.showerror("错误", "请先选择图片A")
            return

        save_path = filedialog.asksaveasfilename(defaultextension=".png",
                                                 filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg;*.jpeg"), ("WebP", "*.webp")])
        if not save_path:
            return

        bg_w, bg_h = self.get_bg_size()
        if self.bg_image:
            bg = self.bg_image.copy()
        else:
            bg = Image.new("RGBA", (bg_w, bg_h), self.bg_color)

        scaled_w, scaled_h = self.get_scaled_size()
        img = self.image_a.resize((scaled_w, scaled_h), Image.LANCZOS)
        # 处理透明度
        alpha_val = self.alpha.get() / 100.0
        if alpha_val < 1:
            alpha_mask = img.split()[3].point(lambda p: p * alpha_val)
            img = img.copy()
            img.putalpha(alpha_mask)
        bg.paste(img, (self.pos_x.get(), self.pos_y.get()), img)

        ext = os.path.splitext(save_path)[1].lower()
        if ext in [".jpg", ".jpeg"]:
            bg = bg.convert("RGB")
        bg.save(save_path)
        messagebox.showinfo("完成", f"图片已导出至：\n{save_path}")

        self.save_last_params()

    def save_last_params(self):
        data = {
            "scale_percent": self.scale_percent.get(),
            "alpha": self.alpha.get(),
            "pos_x": self.pos_x.get(),
            "pos_y": self.pos_y.get(),
            "bg_mode": self.bg_mode.get(),
            "bg_color": self.bg_color
        }
        with open(self.last_params_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_last_params(self):
        if os.path.exists(self.last_params_file):
            with open(self.last_params_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.scale_percent.set(data.get("scale_percent", 100))
                self.alpha.set(data.get("alpha", 100))
                self.pos_x.set(data.get("pos_x", 0))
                self.pos_y.set(data.get("pos_y", 0))
                self.bg_mode.set(data.get("bg_mode", "color"))
                self.bg_color = data.get("bg_color", "#FFFFFF")

if __name__ == "__main__":
    root = Tk()
    app = ImageOverlayApp(root)
    root.mainloop()
