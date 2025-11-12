import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageDraw
import numpy as np
import torch
from torchvision import transforms
from torchvision.models.segmentation import deeplabv3_resnet101
import os
import threading

class PersonExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("人物提取工具")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        # 设置中文字体支持
        self.style = ttk.Style()
        self.style.configure("TButton", font=("SimHei", 10))
        self.style.configure("TLabel", font=("SimHei", 10))

        # 初始化变量
        self.input_image = None
        self.output_image = None
        self.image_path = None
        self.model = None

        # 创建UI组件
        self.create_widgets()

        # 加载模型（在后台线程中加载，避免UI卡顿）
        self.load_model_in_background()

    def create_widgets(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 按钮区域
        button_frame = ttk.Frame(main_frame, padding="5")
        button_frame.pack(fill=tk.X)

        self.select_btn = ttk.Button(button_frame, text="选择图片", command=self.select_image)
        self.select_btn.pack(side=tk.LEFT, padx=5)

        self.extract_btn = ttk.Button(button_frame, text="提取人物", command=self.extract_person, state=tk.DISABLED)
        self.extract_btn.pack(side=tk.LEFT, padx=5)

        self.save_btn = ttk.Button(button_frame, text="保存结果", command=self.save_image, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(button_frame, text="准备就绪")
        self.status_label.pack(side=tk.RIGHT, padx=5)

        # 图片显示区域
        image_frame = ttk.Frame(main_frame, padding="5")
        image_frame.pack(fill=tk.BOTH, expand=True)

        # 原始图片
        ttk.Label(image_frame, text="原始图片:").pack(anchor=tk.W)
        self.original_canvas = tk.Canvas(image_frame, bg="lightgray")
        self.original_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 处理后图片
        ttk.Label(image_frame, text="提取结果:").pack(anchor=tk.W)
        self.result_canvas = tk.Canvas(image_frame, bg="lightgray")
        self.result_canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

    def load_model_in_background(self):
        """在后台线程中加载模型，避免UI卡顿"""
        self.status_label.config(text="正在加载模型，请稍候...")
        self.select_btn.config(state=tk.DISABLED)

        def load_model():
            try:
                # 检查是否有可用的GPU
                self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

                # 加载预训练的DeepLabV3模型
                self.model = deeplabv3_resnet101(pretrained=True)
                self.model.to(self.device)
                self.model.eval()

                # 模型加载成功后更新UI
                self.root.after(0, self.on_model_loaded)
            except Exception as e:
                self.root.after(0, lambda: self.on_model_error(str(e)))

        # 启动后台线程加载模型
        thread = threading.Thread(target=load_model)
        thread.daemon = True
        thread.start()

    def on_model_loaded(self):
        """模型加载成功后的回调"""
        self.status_label.config(text=f"模型加载完成，使用设备: {self.device}")
        self.select_btn.config(state=tk.NORMAL)

    def on_model_error(self, error_msg):
        """模型加载失败后的回调"""
        self.status_label.config(text="模型加载失败")
        messagebox.showerror("错误", f"无法加载模型: {error_msg}\n请确保已安装所有依赖库")

    def select_image(self):
        """选择图片文件"""
        file_path = filedialog.askopenfilename(
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp *.gif")]
        )

        if file_path:
            self.image_path = file_path
            try:
                self.input_image = Image.open(file_path).convert("RGB")
                self.display_image(self.original_canvas, self.input_image)
                self.status_label.config(text=f"已加载图片: {os.path.basename(file_path)}")
                self.extract_btn.config(state=tk.NORMAL)
                self.save_btn.config(state=tk.DISABLED)
                self.result_canvas.delete("all")  # 清除之前的结果
            except Exception as e:
                messagebox.showerror("错误", f"无法打开图片: {str(e)}")
                self.status_label.config(text="打开图片失败")

    def display_image(self, canvas, image):
        """在画布上显示图片，保持比例缩放"""
        canvas.delete("all")

        # 获取画布尺寸
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()

        # 如果画布还没渲染，使用默认尺寸
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = 350
            canvas_height = 450

        # 计算缩放比例
        img_width, img_height = image.size
        ratio = min(canvas_width / img_width, canvas_height / img_height)
        new_width = int(img_width * ratio)
        new_height = int(img_height * ratio)

        # 缩放图片
        resized_img = image.resize((new_width, new_height), Image.LANCZOS)
        photo_img = ImageTk.PhotoImage(resized_img)

        # 保存引用，防止被垃圾回收
        canvas.image = photo_img

        # 居中显示
        x = (canvas_width - new_width) // 2
        y = (canvas_height - new_height) // 2
        canvas.create_image(x, y, anchor=tk.NW, image=photo_img)

    def extract_person(self):
        """提取图片中的人物"""
        if not self.input_image or not self.model:
            return

        self.status_label.config(text="正在提取人物，请稍候...")
        self.extract_btn.config(state=tk.DISABLED)
        self.select_btn.config(state=tk.DISABLED)

        # 在后台线程中处理图片，避免UI卡顿
        def process_image():
            try:
                # 准备图片
                preprocess = transforms.Compose([
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
                ])

                input_tensor = preprocess(self.input_image)
                input_batch = input_tensor.unsqueeze(0).to(self.device)  # 添加批次维度并移动到设备

                # 进行推理
                with torch.no_grad():
                    output = self.model(input_batch)['out'][0]

                output_predictions = output.argmax(0)

                # 创建掩码：15是DeepLabV3中人类的类别ID
                mask = output_predictions.cpu().numpy() == 15
                mask = mask.astype(np.uint8) * 255

                # 将掩码转换为PIL图像
                mask_image = Image.fromarray(mask).resize(self.input_image.size, Image.LANCZOS)

                # 创建透明背景的结果图片
                result = Image.new("RGBA", self.input_image.size, (0, 0, 0, 0))
                result.paste(self.input_image, mask=mask_image)

                # 更新UI
                self.root.after(0, lambda: self.on_extraction_complete(result))

            except Exception as e:
                self.root.after(0, lambda: self.on_extraction_error(str(e)))

        # 启动后台线程处理图片
        thread = threading.Thread(target=process_image)
        thread.daemon = True
        thread.start()

    def on_extraction_complete(self, result_image):
        """提取完成后的回调"""
        self.output_image = result_image
        self.display_image(self.result_canvas, result_image)
        self.status_label.config(text="人物提取完成")
        self.extract_btn.config(state=tk.NORMAL)
        self.select_btn.config(state=tk.NORMAL)
        self.save_btn.config(state=tk.NORMAL)

    def on_extraction_error(self, error_msg):
        """提取失败后的回调"""
        self.status_label.config(text="人物提取失败")
        messagebox.showerror("错误", f"提取人物时出错: {error_msg}")
        self.extract_btn.config(state=tk.NORMAL)
        self.select_btn.config(state=tk.NORMAL)

    def save_image(self):
        """保存提取结果"""
        if not self.output_image:
            return

        # 生成默认文件名
        if self.image_path:
            base_name = os.path.splitext(os.path.basename(self.image_path))[0]
            default_filename = f"{base_name}_person.png"
        else:
            default_filename = "extracted_person.png"

        # 询问保存路径
        save_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG图片", "*.png")],
            initialfile=default_filename
        )

        if save_path:
            try:
                self.output_image.save(save_path)
                self.status_label.config(text=f"已保存至: {save_path}")
                messagebox.showinfo("成功", f"图片已成功保存至:\n{save_path}")
            except Exception as e:
                messagebox.showerror("错误", f"保存图片失败: {str(e)}")
                self.status_label.config(text="保存图片失败")

if __name__ == "__main__":
    # 确保中文显示正常
    root = tk.Tk()
    app = PersonExtractorApp(root)

    # 绑定窗口大小变化事件，重新调整图片大小
    def on_resize(event):
        if app.input_image:
            app.display_image(app.original_canvas, app.input_image)
        if app.output_image:
            app.display_image(app.result_canvas, app.output_image)

    root.bind("<Configure>", on_resize)
    root.mainloop()
