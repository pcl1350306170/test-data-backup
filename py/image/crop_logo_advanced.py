# -*- coding: utf-8 -*-
import os
import threading
import time
import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image
from queue import Queue

# ==============================
# 🧩 配置与常量
# ==============================
CONFIG_FILE = "./json/config_crop_logo_advanced.json"
PROGRESS_FILE = "./json/progress_crop_logo_advanced.json"
SUPPORTED_EXTS = [".jpg", ".jpeg", ".png", ".bmp", ".webp"]

# 确保json目录存在
os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

# ==============================
# ⚙️ 控制变量
# ==============================
task_queue = Queue()
pause_event = threading.Event()
stop_event = threading.Event()
lock = threading.Lock()
progress_data = {}
config_data = {
    "input_dir": "",
    "traverse_subdirs": True,
    "replace_original": False,
    "output_dir": r"G:\图片\v33\裁剪处理",
    "thread_count": 5,
    "vertical_ratio": 0.12,  # 竖图裁剪比例
    "horizontal_ratio": 0.09  # 横图裁剪比例
}

# ==============================
# 📂 配置与进度管理
# ==============================
def load_config():
    """加载配置文件"""
    global config_data
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                config_data.update(loaded)
        except Exception as e:
            print(f"加载配置失败: {e}")

def save_config():
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

def load_progress():
    """加载进度数据"""
    global progress_data
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
        except Exception as e:
            print(f"加载进度失败: {e}")
            progress_data = {}
    else:
        progress_data = {}

def save_progress():
    """保存进度数据"""
    with lock:
        try:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                # 先创建字典副本，避免迭代原始字典时被修改
                progress_copy = progress_data.copy()
                json.dump(progress_copy, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存进度失败: {e}")

# ==============================
# 🖼️ 图片裁剪逻辑
# ==============================
def process_image(image_path, output_path):
    """处理单张图片裁剪"""
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # 根据配置选择裁剪比例
            if height > width:
                crop_ratio = config_data["vertical_ratio"]  # 竖图
            else:
                crop_ratio = config_data["horizontal_ratio"]  # 横图

            crop_height = int(height * (1 - crop_ratio))
            cropped_img = img.crop((0, 0, width, crop_height))

            # 创建输出目录
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cropped_img.save(output_path)

            return True, f"裁剪完成: {os.path.basename(image_path)}"

    except Exception as e:
        return False, f"裁剪出错: {image_path} - {str(e)}"

# ==============================
# 🧵 工作线程函数
# ==============================
def worker():
    """工作线程处理队列任务"""
    while not stop_event.is_set():
        try:
            image_path = task_queue.get(timeout=1)
        except:
            break  # 队列空了

        if stop_event.is_set():
            break

        while pause_event.is_set():
            time.sleep(0.5)

        # 计算输出路径 - 保留完整父级目录结构
        if config_data["replace_original"]:
            output_path = image_path
        else:
            # 获取相对于输入目录的相对路径，确保完整保留目录结构
            rel_path = os.path.relpath(image_path, config_data["input_dir"])
            output_path = os.path.join(config_data["output_dir"], rel_path)

        # 检查是否已处理
        if progress_data.get(image_path):
            task_queue.task_done()
            continue

        # 处理图片
        success, msg = process_image(image_path, output_path)
        update_status(msg)

        if success:
            with lock:  # 确保修改字典时加锁
                progress_data[image_path] = True
            save_progress()

        task_queue.task_done()

# ==============================
# 📋 扫描目录
# ==============================
def scan_images():
    """扫描图片文件并添加到任务队列"""
    input_dir = config_data["input_dir"]
    if not input_dir or not os.path.exists(input_dir):
        return 0

    count = 0
    # 决定是否遍历子目录
    walk_func = os.walk if config_data["traverse_subdirs"] else lambda d: [(d, [], os.listdir(d))]

    for root, dirs, files in walk_func(input_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in SUPPORTED_EXTS:
                full_path = os.path.join(root, file)
                if not progress_data.get(full_path):
                    task_queue.put(full_path)
                    count += 1
    return count

# ==============================
# 🖥️ GUI 相关函数
# ==============================
def select_input_dir():
    """选择输入目录"""
    dir_path = filedialog.askdirectory(title="选择图片目录")
    if dir_path:
        input_dir_var.set(dir_path)
        config_data["input_dir"] = dir_path

def select_output_dir():
    """选择输出目录"""
    dir_path = filedialog.askdirectory(title="选择导出目录")
    if dir_path:
        output_dir_var.set(dir_path)
        config_data["output_dir"] = dir_path

def toggle_output_dir_state(*args):
    """根据是否覆盖原文件切换输出目录控件状态"""
    replace = replace_var.get()
    output_dir_entry.config(state="disabled" if replace else "normal")
    select_output_btn.config(state="disabled" if replace else "normal")

def update_status(message):
    """更新状态显示"""
    status_text.config(state="normal")
    status_text.insert(tk.END, message + "\n")
    status_text.see(tk.END)
    status_text.config(state="disabled")

def validate_ratio(input_str):
    """验证裁剪比例是否为有效的小数"""
    if not input_str:  # 允许空值，之后会使用默认值
        return True
    try:
        value = float(input_str)
        return 0 <= value < 1  # 比例必须在0到1之间
    except ValueError:
        return False

def start_processing():
    """开始处理任务"""
    global threads, total_tasks

    # 验证配置
    if not config_data["input_dir"] or not os.path.exists(config_data["input_dir"]):
        messagebox.showerror("错误", "请选择有效的图片目录")
        return

    if not config_data["replace_original"]:
        if not config_data["output_dir"]:
            messagebox.showerror("错误", "请选择有效的导出目录")
            return
        # 确保输出目录存在
        os.makedirs(config_data["output_dir"], exist_ok=True)

    # 验证线程数
    try:
        thread_count = int(thread_count_var.get())
        if thread_count < 1 or thread_count > 32:
            raise ValueError
        config_data["thread_count"] = thread_count
    except ValueError:
        messagebox.showerror("错误", "线程数必须是1-32之间的整数")
        return

    # 验证裁剪比例
    try:
        vertical_ratio = float(vertical_ratio_var.get())
        if not (0 <= vertical_ratio < 1):
            raise ValueError
        config_data["vertical_ratio"] = vertical_ratio
    except ValueError:
        messagebox.showerror("错误", "竖图比例必须是0-1之间的数字")
        return

    try:
        horizontal_ratio = float(horizontal_ratio_var.get())
        if not (0 <= horizontal_ratio < 1):
            raise ValueError
        config_data["horizontal_ratio"] = horizontal_ratio
    except ValueError:
        messagebox.showerror("错误", "横图比例必须是0-1之间的数字")
        return

    # 保存配置
    save_config()

    # 重置状态
    stop_event.clear()
    pause_event.clear()
    load_progress()

    # 扫描图片
    total_tasks = scan_images()
    if total_tasks == 0:
        messagebox.showinfo("提示", "没有找到需要处理的图片")
        return

    update_status(f"共找到 {total_tasks} 张待处理图片，开始处理...")

    # 启动工作线程
    threads = []
    for _ in range(thread_count):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)

    # 更新控制按钮状态
    start_btn.config(state="disabled")
    pause_btn.config(state="normal")
    stop_btn.config(state="normal")

    # 启动进度更新线程
    root.after(1000, update_progress)

def update_progress():
    """更新进度显示"""
    if stop_event.is_set():
        return

    done = len(progress_data)
    percent = (done / total_tasks) * 100 if total_tasks > 0 else 0
    progress_var.set(percent)
    progress_label.config(text=f"进度: {done}/{total_tasks} ({percent:.2f}%)")

    # 检查是否所有任务都已完成
    if done >= total_tasks and task_queue.empty() and all(not t.is_alive() for t in threads):
        update_status("所有任务处理完成！")
        reset_controls()
        return

    # 继续定时更新
    root.after(1000, update_progress)

def pause_processing():
    """暂停处理"""
    if pause_event.is_set():
        pause_event.clear()
        pause_btn.config(text="暂停")
        update_status("继续处理...")
    else:
        pause_event.set()
        pause_btn.config(text="继续")
        update_status("已暂停处理")

def stop_processing():
    """停止处理"""
    stop_event.set()
    update_status("正在停止处理...")
    root.after(1000, check_stop_complete)

def check_stop_complete():
    """检查是否已完全停止"""
    if all(not t.is_alive() for t in threads):
        update_status("已停止处理")
        reset_controls()
    else:
        root.after(500, check_stop_complete)

def reset_controls():
    """重置控制按钮状态"""
    start_btn.config(state="normal")
    pause_btn.config(state="disabled", text="暂停")
    stop_btn.config(state="disabled")
    progress_var.set(0)

# ==============================
# 🎨 创建GUI界面
# ==============================
def create_gui():
    """创建图形用户界面"""
    global root, input_dir_var, output_dir_var, replace_var, traverse_var, thread_count_var
    global vertical_ratio_var, horizontal_ratio_var
    global status_text, progress_var, progress_label, start_btn, pause_btn, stop_btn, output_dir_entry, select_output_btn

    root = tk.Tk()
    root.title("图片裁剪工具")
    root.geometry("750x600")
    root.resizable(True, True)

    # 配置样式
    style = ttk.Style()
    style.configure("TLabel", font=("微软雅黑", 10))
    style.configure("TButton", font=("微软雅黑", 10))
    style.configure("TCheckbutton", font=("微软雅黑", 10))
    style.configure("TEntry", font=("微软雅黑", 10))

    # 创建比例验证器
    ratio_validator = root.register(validate_ratio)

    # 主框架
    main_frame = ttk.Frame(root, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # 1. 输入目录选择
    ttk.Label(main_frame, text="图片目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
    input_dir_var = tk.StringVar(value=config_data["input_dir"])
    ttk.Entry(main_frame, textvariable=input_dir_var, width=50).grid(row=0, column=1, sticky=tk.EW, pady=5)
    ttk.Button(main_frame, text="浏览...", command=select_input_dir).grid(row=0, column=2, padx=5, pady=5)

    # 2. 遍历子目录选项
    traverse_var = tk.BooleanVar(value=config_data["traverse_subdirs"])
    ttk.Checkbutton(
        main_frame,
        text="遍历子目录",
        variable=traverse_var,
        command=lambda: config_data.update({"traverse_subdirs": traverse_var.get()})
    ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)

    # 3. 覆盖原文件选项
    replace_var = tk.BooleanVar(value=config_data["replace_original"])
    replace_var.trace_add("write", lambda *args: config_data.update({"replace_original": replace_var.get()}))
    replace_var.trace_add("write", toggle_output_dir_state)
    ttk.Checkbutton(main_frame, text="覆盖原文件", variable=replace_var).grid(
        row=2, column=0, columnspan=3, sticky=tk.W, pady=5)

    # 4. 输出目录选择
    ttk.Label(main_frame, text="导出目录:").grid(row=3, column=0, sticky=tk.W, pady=5)
    output_dir_var = tk.StringVar(value=config_data["output_dir"])
    output_dir_entry = ttk.Entry(main_frame, textvariable=output_dir_var, width=50)
    output_dir_entry.grid(row=3, column=1, sticky=tk.EW, pady=5)
    select_output_btn = ttk.Button(main_frame, text="浏览...", command=select_output_dir)
    select_output_btn.grid(row=3, column=2, padx=5, pady=5)
    output_dir_var.trace_add("write", lambda *args: config_data.update({"output_dir": output_dir_var.get()}))

    # 5. 线程数设置
    ttk.Label(main_frame, text="线程数量:").grid(row=4, column=0, sticky=tk.W, pady=5)
    thread_count_var = tk.StringVar(value=str(config_data["thread_count"]))
    ttk.Entry(main_frame, textvariable=thread_count_var, width=10).grid(row=4, column=1, sticky=tk.W, pady=5)
    ttk.Label(main_frame, text="(1-32之间的整数)").grid(row=4, column=2, sticky=tk.W, pady=5)

    # 6. 裁剪比例设置
    ttk.Label(main_frame, text="竖图裁剪比例:").grid(row=5, column=0, sticky=tk.W, pady=5)
    vertical_ratio_var = tk.StringVar(value=str(config_data["vertical_ratio"]))
    ttk.Entry(
        main_frame,
        textvariable=vertical_ratio_var,
        width=10,
        validate="key",
        validatecommand=(ratio_validator, "%P")
    ).grid(row=5, column=1, sticky=tk.W, pady=5)
    ttk.Label(main_frame, text="(0-1之间，例如0.12表示保留88%)").grid(row=5, column=2, sticky=tk.W, pady=5)

    ttk.Label(main_frame, text="横图裁剪比例:").grid(row=6, column=0, sticky=tk.W, pady=5)
    horizontal_ratio_var = tk.StringVar(value=str(config_data["horizontal_ratio"]))
    ttk.Entry(
        main_frame,
        textvariable=horizontal_ratio_var,
        width=10,
        validate="key",
        validatecommand=(ratio_validator, "%P")
    ).grid(row=6, column=1, sticky=tk.W, pady=5)
    ttk.Label(main_frame, text="(0-1之间，例如0.09表示保留91%)").grid(row=6, column=2, sticky=tk.W, pady=5)

    # 进度条
    progress_frame = ttk.Frame(main_frame)
    progress_frame.grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=10)
    progress_var = tk.DoubleVar()
    ttk.Progressbar(progress_frame, variable=progress_var, maximum=100).pack(fill=tk.X, side=tk.LEFT, expand=True, padx=5)
    progress_label = ttk.Label(progress_frame, text="进度: 0/0 (0.00%)")
    progress_label.pack(side=tk.RIGHT, padx=5)

    # 状态文本框
    ttk.Label(main_frame, text="处理状态:").grid(row=8, column=0, sticky=tk.NW, pady=5)
    status_frame = ttk.Frame(main_frame)
    status_frame.grid(row=8, column=1, columnspan=2, sticky=tk.NSEW, pady=5)

    scrollbar = ttk.Scrollbar(status_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    status_text = tk.Text(status_frame, height=10, width=50, state="disabled", wrap=tk.WORD, yscrollcommand=scrollbar.set)
    status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=status_text.yview)

    # 按钮区域
    btn_frame = ttk.Frame(main_frame)
    btn_frame.grid(row=9, column=0, columnspan=3, pady=10)

    start_btn = ttk.Button(btn_frame, text="开始处理", command=start_processing)
    start_btn.pack(side=tk.LEFT, padx=10)

    pause_btn = ttk.Button(btn_frame, text="暂停", command=pause_processing, state="disabled")
    pause_btn.pack(side=tk.LEFT, padx=10)

    stop_btn = ttk.Button(btn_frame, text="停止", command=stop_processing, state="disabled")
    stop_btn.pack(side=tk.LEFT, padx=10)

    # 网格权重设置
    main_frame.columnconfigure(1, weight=1)
    main_frame.rowconfigure(8, weight=1)

    # 初始化输出目录状态
    toggle_output_dir_state()

    return root

# ==============================
# ▶️ 程序入口
# ==============================
if __name__ == "__main__":
    # 加载配置和进度
    load_config()
    load_progress()

    # 创建并运行GUI
    root = create_gui()

    # 窗口关闭事件处理
    def on_closing():
        save_config()  # 关闭时保存配置
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
