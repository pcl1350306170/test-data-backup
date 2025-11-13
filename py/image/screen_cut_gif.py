import os
import json
import time
import threading
import pyautogui
import cv2
import numpy as np
from PIL import Image, ImageTk, ImageGrab
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import io
import keyboard
import ctypes
from ctypes import wintypes

# 引入Windows剪贴板API
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD)
    ]

class ScreenRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("屏幕录制转GIF工具")
        self.root.iconbitmap(default="")
        self.root.geometry("400x300")
        self.root.resizable(False, False)

        # 配置相关
        self.script_name = os.path.splitext(os.path.basename(__file__))[0]
        self.config_dir = "json"
        self.config_file = os.path.join(self.config_dir, f"{self.script_name}_config.json")
        self.default_config = {
            "save_dir": os.getcwd(),
            "hotkey": "ctrl+shift+alt+j",
            "gif_loop": 0,  # 0表示无限循环
            "quality": 0.8,  # 0-1之间的压缩比例
            "auto_open_dir": True
        }
        self.config = self.load_config()

        # 录制相关变量
        self.recording = False
        self.paused = False
        self.region = None
        self.frames = []
        self.start_time = 0
        self.preview_window = None
        self.preview_window_exists = False  # 跟踪预览窗口状态

        # 创建界面
        self.create_widgets()

        # 注册热键
        self.register_hotkey()

    def create_widgets(self):
        # 选择区域按钮
        self.select_region_btn = tk.Button(self.root, text="选择录制区域", command=self.select_region,
                                           font=("微软雅黑", 12), height=2)
        self.select_region_btn.pack(pady=10, fill=tk.X, padx=20)

        # 区域信息显示
        self.region_info = tk.Label(self.root, text="未选择区域", font=("微软雅黑", 10))
        self.region_info.pack(pady=5)

        # 录制控制按钮
        self.control_frame = tk.Frame(self.root)
        self.control_frame.pack(pady=15)

        self.start_btn = tk.Button(self.control_frame, text="开始录制", command=self.toggle_recording,
                                   font=("微软雅黑", 12), width=10, bg="#4CAF50", fg="white")
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = tk.Button(self.control_frame, text="暂停", command=self.toggle_pause,
                                   font=("微软雅黑", 12), width=10, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        # 录制状态显示
        self.status_var = tk.StringVar(value="就绪")
        self.status_label = tk.Label(self.root, textvariable=self.status_var, font=("微软雅黑", 10),
                                     fg="#666666")
        self.status_label.pack(pady=5)

        # 热键提示
        self.hotkey_label = tk.Label(self.root, text=f"热键: {self.config['hotkey']}",
                                     font=("微软雅黑", 9), fg="#999999")
        self.hotkey_label.pack(pady=5)

        # 配置按钮
        self.settings_btn = tk.Button(self.root, text="设置", command=self.open_settings,
                                      font=("微软雅黑", 10))
        self.settings_btn.pack(side=tk.BOTTOM, pady=10)

    def select_region(self):
        """让用户通过鼠标拖拽选择录制区域"""
        # 创建一个全屏半透明窗口用于选择区域
        selection_window = tk.Toplevel(self.root)
        selection_window.attributes("-fullscreen", True)
        selection_window.attributes("-alpha", 0.3)
        selection_window.attributes("-topmost", True)
        selection_window.configure(bg="gray")

        # 绘制选择框的画布
        canvas = tk.Canvas(selection_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)

        # 选择区域变量
        start_x = start_y = end_x = end_y = 0
        rect = None

        def on_press(event):
            nonlocal start_x, start_y, rect
            start_x, start_y = event.x, event.y
            rect = canvas.create_rectangle(0, 0, 0, 0, outline="red", width=2)

        def on_drag(event):
            nonlocal end_x, end_y
            end_x, end_y = event.x, event.y
            canvas.coords(rect, start_x, start_y, end_x, end_y)

        def on_release(event):
            nonlocal end_x, end_y
            end_x, end_y = event.x, event.y
            selection_window.destroy()

            # 确保坐标正确（左上角到右下角）
            self.region = (
                min(start_x, end_x),
                min(start_y, end_y),
                abs(end_x - start_x),
                abs(end_y - start_y)
            )

            # 更新区域信息显示
            self.region_info.config(text=f"区域: {self.region[0]},{self.region[1]} "
                                         f"大小: {self.region[2]}x{self.region[3]}")

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        # 显示提示信息
        instruction = tk.Label(selection_window, text="拖动鼠标选择录制区域，松开确认",
                               bg="yellow", font=("微软雅黑", 12))
        instruction.place(relx=0.5, rely=0.5, anchor="center")

        self.root.wait_window(selection_window)

    def toggle_recording(self):
        """开始或停止录制"""
        if not self.region:
            messagebox.showwarning("警告", "请先选择录制区域")
            return

        if not self.recording:
            # 开始录制
            self.recording = True
            self.paused = False
            self.frames = []
            self.start_time = time.time()
            self.status_var.set("正在录制...")
            self.start_btn.config(text="停止录制", bg="#f44336")
            self.pause_btn.config(state=tk.NORMAL)

            # 创建悬浮窗
            self.create_floating_window()

            # 启动录制线程
            self.recording_thread = threading.Thread(target=self.record_screen)
            self.recording_thread.daemon = True
            self.recording_thread.start()
        else:
            # 停止录制
            self.recording = False
            self.status_var.set("正在处理GIF...")
            self.start_btn.config(text="开始录制", bg="#4CAF50")
            self.pause_btn.config(state=tk.DISABLED, text="暂停")

            # 关闭悬浮窗（安全方式）
            if self.preview_window_exists and self.preview_window:
                try:
                    self.preview_window.destroy()
                except:
                    pass
                self.preview_window = None
                self.preview_window_exists = False

            # 处理并保存GIF（确保在主线程中处理对话框）
            self.root.after(100, self.process_and_save_gif)

    def toggle_pause(self):
        """暂停或继续录制"""
        if self.recording:
            self.paused = not self.paused
            if self.paused:
                self.status_var.set("已暂停")
                self.pause_btn.config(text="继续")
            else:
                self.status_var.set("正在录制...")
                self.pause_btn.config(text="暂停")

    def record_screen(self):
        """录制屏幕的线程函数"""
        try:
            while self.recording:
                if not self.paused:
                    # 捕获选定区域的屏幕
                    x, y, width, height = self.region
                    img = ImageGrab.grab(bbox=(x, y, x + width, y + height))

                    # 转换为OpenCV格式用于预览
                    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

                    # 添加到帧列表
                    self.frames.append(img.copy())

                    # 更新预览窗口（添加安全检查）
                    if self.preview_window_exists and self.preview_window:
                        try:
                            # 检查窗口是否仍存在
                            self.preview_window.winfo_exists()

                            # 调整预览大小
                            preview_size = (min(320, width), min(240, height))
                            preview_img = cv2.resize(frame, preview_size)
                            preview_img = cv2.cvtColor(preview_img, cv2.COLOR_BGR2RGB)
                            preview_img = Image.fromarray(preview_img)
                            preview_photo = ImageTk.PhotoImage(image=preview_img)

                            self.preview_window.preview_label.config(image=preview_photo)
                            self.preview_window.preview_label.image = preview_photo
                        except:
                            # 窗口已关闭，更新状态
                            self.preview_window_exists = False

                # 控制录制帧率（约15fps）
                time.sleep(0.067)
        except Exception as e:
            print(f"录制错误: {e}")
            self.status_var.set(f"录制错误: {str(e)}")
            self.recording = False

    def create_floating_window(self):
        """创建悬浮预览窗口"""
        # 先销毁可能存在的旧窗口
        if self.preview_window_exists and self.preview_window:
            try:
                self.preview_window.destroy()
            except:
                pass

        self.preview_window = tk.Toplevel(self.root)
        self.preview_window.title("预览")
        self.preview_window.overrideredirect(True)  # 无边框
        self.preview_window.attributes("-topmost", True)
        self.preview_window.geometry("340x280+10+10")
        self.preview_window_exists = True  # 标记窗口存在

        # 预览标签
        self.preview_window.preview_label = tk.Label(self.preview_window)
        self.preview_window.preview_label.pack(pady=10)

        # 控制按钮
        btn_frame = tk.Frame(self.preview_window)
        btn_frame.pack(pady=5)

        # 暂停/继续按钮
        pause_btn = tk.Button(btn_frame, text="暂停", command=self.toggle_pause,
                              width=8)
        pause_btn.pack(side=tk.LEFT, padx=5)

        # 停止按钮
        stop_btn = tk.Button(btn_frame, text="停止", command=self.toggle_recording,
                             width=8, bg="#f44336", fg="white")
        stop_btn.pack(side=tk.LEFT, padx=5)

        # 拖动窗口功能
        def start_drag(event):
            self.preview_window.x = event.x
            self.preview_window.y = event.y

        def on_drag(event):
            x = self.preview_window.winfo_x() + event.x - self.preview_window.x
            y = self.preview_window.winfo_y() + event.y - self.preview_window.y
            self.preview_window.geometry(f"+{x}+{y}")

        self.preview_window.bind("<ButtonPress-1>", start_drag)
        self.preview_window.bind("<B1-Motion>", on_drag)

        # 窗口关闭事件处理
        def on_close():
            self.preview_window_exists = False
            self.preview_window.destroy()

        self.preview_window.protocol("WM_DELETE_WINDOW", on_close)

    def process_and_save_gif(self):
        """处理录制的帧并保存为GIF（确保在主线程中执行）"""
        try:
            if not self.frames:
                self.status_var.set("未录制到任何内容")
                return

            # 询问文件名（使用主线程处理）
            default_filename = f"recording_{time.strftime('%Y%m%d_%H%M%S')}.gif"

            # 使用对话框前检查主窗口是否存在
            if not self.root.winfo_exists():
                return

            filename = simpledialog.askstring("保存GIF", "请输入文件名:",
                                              initialvalue=default_filename,
                                              parent=self.root)

            if filename is None:  # 用户取消
                self.status_var.set("已取消保存")
                return

            if not filename.endswith(".gif"):
                filename += ".gif"

            save_path = os.path.join(self.config["save_dir"], filename)

            # 应用压缩比例
            quality = self.config["quality"]
            if quality < 1.0:
                resized_frames = []
                for frame in self.frames:
                    new_size = (int(frame.width * quality), int(frame.height * quality))
                    resized_frame = frame.resize(new_size, Image.Resampling.LANCZOS)
                    resized_frames.append(resized_frame)
                self.frames = resized_frames

            # 保存为GIF
            self.frames[0].save(
                save_path,
                format="GIF",
                append_images=self.frames[1:],
                save_all=True,
                duration=67,  # 约15fps
                loop=self.config["gif_loop"]
            )

            # 复制到剪贴板（使用新的系统API方式）
            success = self.copy_image_to_clipboard(save_path)

            # 自动打开目录
            if self.config["auto_open_dir"]:
                os.startfile(os.path.dirname(save_path))

            self.status_var.set(f"已保存: {filename}")
            msg = f"GIF已保存到:\n{save_path}"
            if success:
                msg += "\n并已复制到剪贴板"
            else:
                msg += "\n复制到剪贴板失败"
            messagebox.showinfo("成功", msg, parent=self.root)

        except Exception as e:
            print(f"保存错误: {e}")
            self.status_var.set(f"保存错误: {str(e)}")
            if self.root.winfo_exists():  # 检查窗口是否存在
                messagebox.showerror("错误", f"保存GIF失败:\n{str(e)}", parent=self.root)

    def copy_image_to_clipboard(self, image_path):
        """使用Windows API将图像复制到剪贴板（支持直接粘贴）"""
        try:
            # 打开图像并转换为BMP格式
            image = Image.open(image_path)
            bmp_image = image.convert("RGB")  # 确保是RGB格式

            # 获取图像数据
            width, height = bmp_image.size
            pixels = bmp_image.tobytes()

            # 打开剪贴板
            if not user32.OpenClipboard(None):
                return False

            try:
                # 清空剪贴板
                user32.EmptyClipboard()

                # 计算每行字节数（必须是4的倍数）
                row_size = (width * 24 + 31) // 32 * 4
                total_size = row_size * height

                # 创建BITMAPINFOHEADER结构
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = width
                bmi.biHeight = -height  # 负号表示从上到下
                bmi.biPlanes = 1
                bmi.biBitCount = 24
                bmi.biCompression = 0  # BI_RGB
                bmi.biSizeImage = total_size

                # 分配全局内存
                h_global = kernel32.GlobalAlloc(0x0042, total_size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
                if not h_global:
                    return False

                try:
                    # 锁定内存并复制像素数据
                    p_global = kernel32.GlobalLock(h_global)
                    if p_global:
                        ctypes.memmove(p_global, pixels, len(pixels))
                        kernel32.GlobalUnlock(h_global)

                        # 将位图放入剪贴板
                        if gdi32.SetDIBitsToDevice(
                                gdi32.CreateCompatibleDC(None),
                                0, 0, width, height,
                                0, 0, 0, height,
                                p_global,
                                ctypes.byref(bmi),
                                0
                        ):
                            # 设置剪贴板数据
                            if user32.SetClipboardData(2, h_global):  # CF_DIB
                                return True
                finally:
                    if not user32.IsClipboardFormatAvailable(2):
                        kernel32.GlobalFree(h_global)

            finally:
                user32.CloseClipboard()

            return False

        except Exception as e:
            print(f"复制到剪贴板失败: {e}")
            return False

    def register_hotkey(self):
        """注册热键用于控制录制"""
        try:
            keyboard.add_hotkey(self.config["hotkey"], self.toggle_recording)
        except Exception as e:
            print(f"注册热键失败: {e}")
            messagebox.showerror("错误", f"注册热键失败:\n{str(e)}")

    def load_config(self):
        """加载配置文件"""
        try:
            if not os.path.exists(self.config_dir):
                os.makedirs(self.config_dir)

            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 确保所有配置项都存在
                    for key, value in self.default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            else:
                return self.default_config.copy()
        except Exception as e:
            print(f"加载配置失败: {e}")
            return self.default_config.copy()

    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            messagebox.showerror("错误", f"保存配置失败:\n{str(e)}")
            return False

    def open_settings(self):
        """打开设置窗口"""
        # 检查主窗口是否存在
        if not self.root.winfo_exists():
            return

        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("350x300")
        settings_window.resizable(False, False)
        settings_window.transient(self.root)
        settings_window.grab_set()

        # 保存目录设置
        tk.Label(settings_window, text="保存目录:", font=("微软雅黑", 10)).grid(
            row=0, column=0, sticky="w", padx=10, pady=10)

        dir_frame = tk.Frame(settings_window)
        dir_frame.grid(row=0, column=1, padx=10, pady=10)

        dir_var = tk.StringVar(value=self.config["save_dir"])
        dir_entry = tk.Entry(dir_frame, textvariable=dir_var, width=20)
        dir_entry.pack(side=tk.LEFT)

        def browse_dir():
            directory = filedialog.askdirectory(title="选择保存目录",
                                                initialdir=dir_var.get())
            if directory:
                dir_var.set(directory)

        browse_btn = tk.Button(dir_frame, text="浏览", command=browse_dir)
        browse_btn.pack(side=tk.LEFT, padx=5)

        # 热键设置
        tk.Label(settings_window, text="录制热键:", font=("微软雅黑", 10)).grid(
            row=1, column=0, sticky="w", padx=10, pady=10)

        hotkey_var = tk.StringVar(value=self.config["hotkey"])
        hotkey_entry = tk.Entry(settings_window, textvariable=hotkey_var, width=20)
        hotkey_entry.grid(row=1, column=1, padx=10, pady=10)

        # GIF循环次数
        tk.Label(settings_window, text="GIF循环次数:", font=("微软雅黑", 10)).grid(
            row=2, column=0, sticky="w", padx=10, pady=10)

        loop_var = tk.StringVar(value=str(self.config["gif_loop"]))
        loop_entry = tk.Entry(settings_window, textvariable=loop_var, width=10)
        loop_entry.grid(row=2, column=1, sticky="w", padx=10, pady=10)
        tk.Label(settings_window, text="(0表示无限循环)", font=("微软雅黑", 8)).grid(
            row=2, column=1, sticky="e", padx=10, pady=10)

        # 压缩质量
        tk.Label(settings_window, text="压缩比例:", font=("微软雅黑", 10)).grid(
            row=3, column=0, sticky="w", padx=10, pady=10)

        quality_var = tk.StringVar(value=str(self.config["quality"]))
        quality_entry = tk.Entry(settings_window, textvariable=quality_var, width=10)
        quality_entry.grid(row=3, column=1, sticky="w", padx=10, pady=10)
        tk.Label(settings_window, text="(0-1之间，1表示不压缩)", font=("微软雅黑", 8)).grid(
            row=3, column=1, sticky="e", padx=10, pady=10)

        # 自动打开目录
        auto_open_var = tk.BooleanVar(value=self.config["auto_open_dir"])
        auto_open_check = tk.Checkbutton(settings_window, text="录制完成后自动打开保存目录",
                                         variable=auto_open_var)
        auto_open_check.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=5)

        # 保存按钮
        def save_settings():
            try:
                self.config["save_dir"] = dir_var.get()
                self.config["hotkey"] = hotkey_var.get()
                self.config["gif_loop"] = int(loop_var.get())
                self.config["quality"] = float(quality_var.get())
                self.config["auto_open_dir"] = auto_open_var.get()

                # 验证质量值
                if not (0 < self.config["quality"] <= 1):
                    messagebox.showwarning("警告", "压缩比例必须在0-1之间")
                    return

                # 重新注册热键
                keyboard.unhook_all_hotkeys()
                self.register_hotkey()

                # 更新界面显示
                self.hotkey_label.config(text=f"热键: {self.config['hotkey']}")

                if self.save_config():
                    messagebox.showinfo("成功", "设置已保存")
                    settings_window.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数值")

        save_btn = tk.Button(settings_window, text="保存设置", command=save_settings,
                             font=("微软雅黑", 10))
        save_btn.grid(row=5, column=0, columnspan=2, pady=20)

        self.root.wait_window(settings_window)

if __name__ == "__main__":
    # 禁用PyAutoGUI的安全功能，允许捕获整个屏幕
    pyautogui.FAILSAFE = False

    root = tk.Tk()
    app = ScreenRecorder(root)
    root.mainloop()
