import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import os

class ImageCropperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片裁剪工具")
        self.root.geometry("1000x600")
        self.root.resizable(True, True)

        # 设置中文字体
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))

        # 初始化变量
        self.original_image = None  # 原始图片
        self.displayed_image = None  # 显示用的图片
        self.cropped_image = None  # 裁剪后的图片
        self.image_path = None  # 图片路径
        self.scale = 1.0  # 缩放比例
        self.start_x = None  # 裁剪起点x
        self.start_y = None  # 裁剪起点y
        self.rect_id = None  # 裁剪框ID
        self.selection = None  # 裁剪区域 (x1, y1, x2, y2)

        # 创建UI组件
        self.create_widgets()

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

        self.status_label = ttk.Label(btn_frame, text="请选择一张图片")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # 图片显示区域
        display_frame = ttk.Frame(main_frame, padding="5")
        display_frame.pack(fill=tk.BOTH, expand=True)

        # 原始图片区域
        ttk.Label(display_frame, text="原始图片 (拖动鼠标选择裁剪区域):").pack(anchor=tk.W)
        self.original_frame = ttk.Frame(display_frame, borderwidth=1, relief=tk.SUNKEN)
        self.original_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.original_canvas = tk.Canvas(self.original_frame, bg="lightgray")
        self.original_canvas.pack(fill=tk.BOTH, expand=True)

        # 绑定鼠标事件
        self.original_canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.original_canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.original_canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

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
            self.image_path = file_path
            try:
                # 打开图片并转换为RGB模式（处理透明图片）
                self.original_image = Image.open(file_path).convert("RGB")
                self.status_label.config(text=f"已加载: {os.path.basename(file_path)}")

                # 重置状态
                self.reset_selection()

                # 显示图片
                self.display_original_image()

                # 启用按钮
                self.reset_btn.config(state=tk.NORMAL)

            except Exception as e:
                messagebox.showerror("错误", f"无法打开图片: {str(e)}")
                self.status_label.config(text="打开图片失败")

    def display_original_image(self):
        """在画布上显示原始图片，自动适应窗口大小"""
        self.original_canvas.delete("all")

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

        # 显示图片
        self.tk_image = ImageTk.PhotoImage(self.displayed_image)
        self.original_canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self.original_canvas.image = self.tk_image  # 保持引用

    def on_mouse_down(self, event):
        """鼠标按下事件，记录裁剪起点"""
        if not self.displayed_image:
            return

        # 记录起点坐标
        self.start_x = event.x
        self.start_y = event.y

        # 清除已有的裁剪框
        if self.rect_id:
            self.original_canvas.delete(self.rect_id)

        # 创建新的裁剪框
        self.rect_id = self.original_canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", dash=(5, 2)
        )

    def on_mouse_drag(self, event):
        """鼠标拖动事件，更新裁剪框"""
        if not self.start_x or not self.start_y or not self.rect_id:
            return

        # 更新裁剪框
        self.original_canvas.coords(
            self.rect_id,
            self.start_x, self.start_y,
            event.x, event.y
        )

    def on_mouse_up(self, event):
        """鼠标释放事件，确定裁剪区域"""
        if not self.start_x or not self.start_y:
            return

        # 计算裁剪区域（确保坐标正确，左上角到右下角）
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        # 检查裁剪区域是否有效（至少10x10像素）
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            self.original_canvas.delete(self.rect_id)
            self.rect_id = None
            self.selection = None
            self.crop_btn.config(state=tk.DISABLED)
            self.save_btn.config(state=tk.DISABLED)
            self.status_label.config(text="裁剪区域太小，请重新选择")
            return

        # 保存裁剪区域（转换为原始图片的坐标）
        orig_x1 = int(x1 / self.scale)
        orig_y1 = int(y1 / self.scale)
        orig_x2 = int(x2 / self.scale)
        orig_y2 = int(y2 / self.scale)
        self.selection = (orig_x1, orig_y1, orig_x2, orig_y2)

        # 预览裁剪效果
        self.preview_crop()

        # 更新状态和按钮
        self.status_label.config(text=f"裁剪区域: {orig_x2-orig_x1}x{orig_y2-orig_y1} 像素")
        self.crop_btn.config(state=tk.NORMAL)

    def preview_crop(self):
        """预览裁剪效果"""
        if not self.selection or not self.original_image:
            return

        # 裁剪图片
        self.cropped_image = self.original_image.crop(self.selection)

        # 在预览画布上显示
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

        # 更新原始图片为裁剪后的图片
        self.original_image = self.cropped_image.copy()
        self.display_original_image()

        # 重置选择状态
        self.reset_selection()

        # 更新状态
        self.status_label.config(text="裁剪完成，可以保存或继续裁剪")
        self.save_btn.config(state=tk.NORMAL)

    def save_image(self):
        """保存裁剪后的图片"""
        if not self.original_image:
            return

        # 生成默认文件名
        if self.image_path:
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            default_filename = f"{base_name}_cropped.png"
        else:
            default_filename = "cropped_image.png"

        # 询问保存路径
        save_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[
                ("PNG图片", "*.png"),
                ("JPEG图片", "*.jpg"),
                ("BMP图片", "*.bmp")
            ],
            initialfile=default_filename
        )

        if save_path:
            try:
                # 根据文件扩展名选择保存格式
                if save_path.lower().endswith('.png'):
                    self.original_image.save(save_path, 'PNG')
                elif save_path.lower().endswith('.jpg') or save_path.lower().endswith('.jpeg'):
                    self.original_image.save(save_path, 'JPEG', quality=95)
                else:
                    self.original_image.save(save_path, 'BMP')

                self.status_label.config(text=f"已保存至: {save_path}")
                messagebox.showinfo("成功", f"图片已成功保存至:\n{save_path}")
            except Exception as e:
                messagebox.showerror("错误", f"保存图片失败: {str(e)}")
                self.status_label.config(text="保存图片失败")

    def reset_selection(self):
        """重置裁剪选择"""
        # 清除裁剪框
        if self.rect_id:
            self.original_canvas.delete(self.rect_id)
            self.rect_id = None

        # 清除预览
        self.preview_canvas.delete("all")

        # 重置变量
        self.start_x = None
        self.start_y = None
        self.selection = None
        self.cropped_image = None

        # 更新按钮状态
        self.crop_btn.config(state=tk.DISABLED)

        # 如果有图片，重新显示
        if self.original_image:
            self.display_original_image()

    def on_window_resize(self, event):
        """窗口大小变化时重新调整图片显示"""
        # 避免窗口初始化时的不必要调用
        if event.widget == self.root and self.original_image:
            self.display_original_image()
            if self.selection:
                self.preview_crop()

if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCropperApp(root)
    root.mainloop()
