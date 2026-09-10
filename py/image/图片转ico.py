# image_to_ico.py
import os
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
from PIL import Image

# 支持的输入格式（Pillow 能打开的常见格式）
SUPPORTED_FORMATS = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"]

class ImageToIcoConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("🖼️ 图片转 ICO 工具")
        self.root.geometry("500x300")
        self.root.resizable(False, False)
        self.input_path = None

        self.create_widgets()

    def create_widgets(self):
        # 标题
        title_label = Label(
            self.root,
            text="选择一张图片，一键转为 .ico 图标",
            font=("Microsoft YaHei", 14, "bold"),
            fg="#2c3e50"
        )
        title_label.pack(pady=15)

        # 文件选择区域
        file_frame = Frame(self.root)
        file_frame.pack(pady=10)

        self.file_label = Label(
            file_frame,
            text="未选择文件",
            width=40,
            relief="sunken",
            anchor="w",
            padx=5,
            bg="#f9f9f9"
        )
        self.file_label.pack(side=LEFT, padx=(0, 10))

        Button(file_frame, text="📂 选择图片", command=self.select_image, width=12).pack(side=RIGHT)

        # 转换按钮
        self.convert_btn = Button(
            self.root,
            text="🔄 转换为 ICO",
            command=self.convert_to_ico,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 10, "bold"),
            width=20,
            height=2,
            state="disabled"  # 初始禁用
        )
        self.convert_btn.pack(pady=20)

        # 状态标签
        self.status_label = Label(self.root, text="", fg="blue", font=("Arial", 9))
        self.status_label.pack()

        # 底部说明
        info_label = Label(
            self.root,
            text="支持格式：PNG, JPG, BMP, GIF 等\n生成的 .ico 文件将保存在原图同目录下",
            font=("Arial", 8),
            fg="#7f8c8d"
        )
        info_label.pack(side=BOTTOM, pady=10)

    def select_image(self):
        file_path = filedialog.askopenfilename(
            title="选择图片文件",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            path = Path(file_path)
            if path.suffix.lower() not in SUPPORTED_FORMATS:
                messagebox.showerror("格式不支持", f"不支持的文件格式：{path.suffix}\n请使用 PNG/JPG/BMP 等常见图片。")
                return

            self.input_path = path
            self.file_label.config(text=str(path.name))
            self.convert_btn.config(state="normal")
            self.status_label.config(text="")

    def convert_to_ico(self):
        if not self.input_path or not self.input_path.exists():
            messagebox.showerror("错误", "请选择有效的图片文件！")
            return

        try:
            # 打开图像并转换为 RGBA（ICO 需要透明通道支持）
            with Image.open(self.input_path) as img:
                img = img.convert("RGBA")

                # ICO 通常包含多个尺寸，这里生成常用尺寸
                icon_sizes = [(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)]

                # 过滤掉比原图还大的尺寸
                original_size = max(img.size)
                valid_sizes = [size for size in icon_sizes if min(size) <= original_size]

                # 输出路径：同目录，.ico 后缀
                output_path = self.input_path.with_suffix(".ico")

                # 保存为 ICO
                img.save(
                    output_path,
                    format="ICO",
                    sizes=valid_sizes
                )

                self.status_label.config(text=f"✅ 转换成功！\n已保存至：{output_path.name}", fg="green")
                messagebox.showinfo("成功", f"图标已生成！\n\n{output_path}")

        except Exception as e:
            error_msg = f"转换失败：{str(e)}"
            self.status_label.config(text=error_msg, fg="red")
            messagebox.showerror("错误", error_msg)
            return

# 启动程序
if __name__ == "__main__":
    try:
        from PIL import Image
    except ImportError:
        root = Tk()
        root.withdraw()
        messagebox.showerror("依赖缺失", "请安装 Pillow 库：\n\npip install Pillow")
        root.destroy()
        exit(1)

    root = Tk()
    app = ImageToIcoConverter(root)
    root.mainloop()
