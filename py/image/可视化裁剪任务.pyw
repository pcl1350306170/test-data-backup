# -*- coding: utf-8 -*-
import os
import threading
import time
import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image
from queue import Queue
from pathlib import Path

# ==============================
# 🧩 配置与常量
# ==============================
# 获取当前脚本所在目录的绝对路径
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))

# 绝对路径配置
CONFIG_FILE = SCRIPT_DIR / "json" / "config_crop_logo_advanced.json"
PROGRESS_FILE = SCRIPT_DIR / "json" / "logs" / "progress_crop_logo_advanced.log"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / "process_log_crop_logo_advanced.log"
SUPPORTED_EXTS = [".jpg", ".jpeg", ".png", ".bmp", ".webp"]

# 确保目录存在（基于绝对路径创建）
os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
os.makedirs(os.path.dirname(PROCESS_LOG_FILE), exist_ok=True)

# ==============================
# ⚙️ 控制变量（使用线程安全的计数器）
# ==============================
task_queue = Queue()
pause_event = threading.Event()
stop_event = threading.Event()
# 分离计数锁和进度锁，减少竞争
count_lock = threading.Lock()  # 仅用于process_count计数
progress_lock = threading.Lock()  # 仅用于progress_data操作
log_lock = threading.Lock()  # 单独的日志写入锁
progress_data = {}
process_count = 0  # 已处理文件计数
config_data = {
    "input_dir": "",
    "traverse_subdirs": True,
    "replace_original": False,
    "output_dir": r"G:\图片\v33\裁剪处理",
    "thread_count": 5,
    "vertical_ratio": 0.12,
    "horizontal_ratio": 0.09,
    "logo_position": "下"
}

# ==============================
# 📂 配置与进度管理
# ==============================
def load_config():
    global config_data
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                config_data.update(loaded)
                if "logo_position" not in config_data:
                    config_data["logo_position"] = "下"
        except Exception as e:
            print(f"加载配置失败: {e}")

def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

def load_progress():
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
    """非阻塞式保存进度（使用副本避免锁竞争）"""
    with progress_lock:
        progress_copy = progress_data.copy()  # 复制副本，减少锁持有时间
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress_copy, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存进度失败: {e}")

def log_process_status():
    """非阻塞式写入日志（单独锁+异步思想）"""
    global process_count
    with count_lock:
        current_count = process_count  # 读取当前计数后立即释放锁
    with log_lock:
        try:
            with open(PROCESS_LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] 已处理 {current_count} 张图片\n")
        except Exception as e:
            print(f"记录进度日志失败: {e}")

# ==============================
# 🖼️ 图片裁剪逻辑
# ==============================
def process_image(image_path, output_path):
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # 选择裁剪比例
            if height > width:
                crop_ratio = config_data["vertical_ratio"]
            else:
                crop_ratio = config_data["horizontal_ratio"]

            # 根据logo位置裁剪
            position = config_data["logo_position"]
            if position in ["上", "下"]:
                crop_height = int(height * (1 - crop_ratio))
                if position == "上":
                    cropped_img = img.crop((0, height - crop_height, width, height))
                else:
                    cropped_img = img.crop((0, 0, width, crop_height))
            else:
                crop_width = int(width * (1 - crop_ratio))
                if position == "左":
                    cropped_img = img.crop((width - crop_width, 0, width, height))
                else:
                    cropped_img = img.crop((0, 0, crop_width, height))

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cropped_img.save(output_path)
            return True, f"裁剪完成: {os.path.basename(image_path)}"
    except Exception as e:
        return False, f"裁剪出错: {image_path} - {str(e)}"

# ==============================
# 🧵 工作线程函数（核心修复）
# ==============================
def worker():
    global process_count
    while not stop_event.is_set():
        try:
            # 超时时间1秒，避免线程永久阻塞在空队列
            image_path = task_queue.get(timeout=1)
        except:
            break  # 队列空，退出线程

        if stop_event.is_set():
            task_queue.task_done()  # 确保队列计数正确
            break

        # 处理暂停
        while pause_event.is_set():
            time.sleep(0.5)
            if stop_event.is_set():  # 暂停时检查是否需要停止
                task_queue.task_done()
                break
        if stop_event.is_set():
            break

        # 计算输出路径
        if config_data["replace_original"]:
            output_path = image_path
        else:
            rel_path = os.path.relpath(image_path, config_data["input_dir"])
            output_path = os.path.join(config_data["output_dir"], rel_path)

        # 跳过已处理文件
        with progress_lock:
            if progress_data.get(image_path):
                task_queue.task_done()
                continue

        # 处理图片
        success, msg = process_image(image_path, output_path)
        update_status(msg)

        if success:
            # 分离计数和进度更新，减少锁竞争
            with progress_lock:
                progress_data[image_path] = True
            with count_lock:
                process_count += 1
                # 每100张记录日志（使用局部变量判断，避免锁内计算）
                current = process_count
                if current % 100 == 0:
                    # 异步思想：启动临时线程写入日志，不阻塞工作线程
                    threading.Thread(target=log_process_status, daemon=True).start()
                    threading.Thread(target=save_progress, daemon=True).start()

        task_queue.task_done()

# ==============================
# 📋 扫描目录
# ==============================
def scan_images():
    input_dir = config_data["input_dir"]
    if not input_dir or not os.path.exists(input_dir):
        return 0

    count = 0
    walk_func = os.walk if config_data["traverse_subdirs"] else lambda d: [(d, [], os.listdir(d))]
    for root, dirs, files in walk_func(input_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in SUPPORTED_EXTS:
                full_path = os.path.join(root, file)
                with progress_lock:
                    if not progress_data.get(full_path):
                        task_queue.put(full_path)
                        count += 1
    return count

# ==============================
# 🖥️ GUI 相关函数
# ==============================
def select_input_dir():
    dir_path = filedialog.askdirectory(title="选择图片目录")
    if dir_path:
        input_dir_var.set(dir_path)
        config_data["input_dir"] = dir_path

def select_output_dir():
    dir_path = filedialog.askdirectory(title="选择导出目录")
    if dir_path:
        output_dir_var.set(dir_path)
        config_data["output_dir"] = dir_path

def toggle_output_dir_state(*args):
    replace = replace_var.get()
    output_dir_entry.config(state="disabled" if replace else "normal")
    select_output_btn.config(state="disabled" if replace else "normal")

def update_status(message):
    """线程安全的状态更新（通过GUI主线程）"""
    def _update():
        status_text.config(state="normal")
        status_text.insert(tk.END, message + "\n")
        status_text.see(tk.END)
        status_text.config(state="disabled")
    root.after(0, _update)  # 确保在主线程执行

def validate_ratio(input_str):
    if not input_str:
        return True
    try:
        return 0 <= float(input_str) < 1
    except ValueError:
        return False

def start_processing():
    global threads, total_tasks
    if not config_data["input_dir"] or not os.path.exists(config_data["input_dir"]):
        messagebox.showerror("错误", "请选择有效的图片目录")
        return

    if not config_data["replace_original"] and not config_data["output_dir"]:
        messagebox.showerror("错误", "请选择有效的导出目录")
        return
    os.makedirs(config_data["output_dir"], exist_ok=True)

    # 验证线程数
    try:
        thread_count = int(thread_count_var.get())
        if not 1 <= thread_count <= 32:
            raise ValueError
        config_data["thread_count"] = thread_count
    except ValueError:
        messagebox.showerror("错误", "线程数必须是1-32之间的整数")
        return

    # 验证比例
    try:
        vertical_ratio = float(vertical_ratio_var.get())
        if not 0 <= vertical_ratio < 1:
            raise ValueError
        config_data["vertical_ratio"] = vertical_ratio
    except ValueError:
        messagebox.showerror("错误", "竖图比例必须是0-1之间的数字")
        return

    try:
        horizontal_ratio = float(horizontal_ratio_var.get())
        if not 0 <= horizontal_ratio < 1:
            raise ValueError
        config_data["horizontal_ratio"] = horizontal_ratio
    except ValueError:
        messagebox.showerror("错误", "横图比例必须是0-1之间的数字")
        return

    save_config()
    stop_event.clear()
    pause_event.clear()
    load_progress()

    # 初始化计数（使用锁确保线程安全）
    with count_lock:
        global process_count
        process_count = len(progress_data)

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

    # 更新控件状态
    start_btn.config(state="disabled")
    pause_btn.config(state="normal")
    stop_btn.config(state="normal")
    root.after(1000, update_progress)

def update_progress():
    """更可靠的进度判断（考虑线程存活状态）"""
    if stop_event.is_set():
        return

    with progress_lock:
        done = len(progress_data)
    total = total_tasks
    percent = (done / total) * 100 if total > 0 else 0
    progress_var.set(percent)
    progress_label.config(text=f"进度: {done}/{total} ({percent:.2f}%)")

    # 判断任务是否完成：队列空 + 所有线程都已处理完当前任务
    all_idle = all(not t.is_alive() for t in threads) if threads else True
    if done >= total and task_queue.empty() and all_idle:
        save_progress()
        log_process_status()
        update_status("所有任务处理完成！")
        reset_controls()
        return

    root.after(1000, update_progress)

def pause_processing():
    if pause_event.is_set():
        pause_event.clear()
        pause_btn.config(text="暂停")
        update_status("继续处理...")
    else:
        pause_event.set()
        pause_btn.config(text="继续")
        update_status("已暂停处理")

def stop_processing():
    stop_event.set()
    update_status("正在停止处理...")
    root.after(1000, check_stop_complete)

def check_stop_complete():
    if all(not t.is_alive() for t in threads) if threads else True:
        save_progress()
        log_process_status()
        update_status("已停止处理")
        reset_controls()
    else:
        root.after(500, check_stop_complete)

def reset_controls():
    start_btn.config(state="normal")
    pause_btn.config(state="disabled", text="暂停")
    stop_btn.config(state="disabled")
    progress_var.set(0)

# ==============================
# 🎨 创建GUI界面
# ==============================
def create_gui():
    global root, input_dir_var, output_dir_var, replace_var, thread_count_var
    global vertical_ratio_var, horizontal_ratio_var, logo_position_var
    global status_text, progress_var, progress_label, start_btn, pause_btn, stop_btn
    global output_dir_entry, select_output_btn

    root = tk.Tk()
    root.title("图片裁剪工具")
    root.geometry("750x650")
    root.resizable(True, True)

    style = ttk.Style()
    style.configure("TLabel", font=("微软雅黑", 10))
    style.configure("TButton", font=("微软雅黑", 10))
    style.configure("TCheckbutton", font=("微软雅黑", 10))
    style.configure("TEntry", font=("微软雅黑", 10))
    style.configure("TCombobox", font=("微软雅黑", 10))

    ratio_validator = root.register(validate_ratio)
    main_frame = ttk.Frame(root, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # 输入目录
    ttk.Label(main_frame, text="图片目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
    input_dir_var = tk.StringVar(value=config_data["input_dir"])
    ttk.Entry(main_frame, textvariable=input_dir_var, width=50).grid(row=0, column=1, sticky=tk.EW, pady=5)
    ttk.Button(main_frame, text="浏览...", command=select_input_dir).grid(row=0, column=2, padx=5, pady=5)

    # 遍历子目录
    traverse_var = tk.BooleanVar(value=config_data["traverse_subdirs"])
    ttk.Checkbutton(
        main_frame, text="遍历子目录", variable=traverse_var,
        command=lambda: config_data.update({"traverse_subdirs": traverse_var.get()})
    ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)

    # 覆盖原文件
    replace_var = tk.BooleanVar(value=config_data["replace_original"])
    replace_var.trace_add("write", lambda *args: config_data.update({"replace_original": replace_var.get()}))
    replace_var.trace_add("write", toggle_output_dir_state)
    ttk.Checkbutton(main_frame, text="覆盖原文件", variable=replace_var).grid(
        row=2, column=0, columnspan=3, sticky=tk.W, pady=5)

    # 输出目录
    ttk.Label(main_frame, text="导出目录:").grid(row=3, column=0, sticky=tk.W, pady=5)
    output_dir_var = tk.StringVar(value=config_data["output_dir"])
    output_dir_entry = ttk.Entry(main_frame, textvariable=output_dir_var, width=50)
    output_dir_entry.grid(row=3, column=1, sticky=tk.EW, pady=5)
    select_output_btn = ttk.Button(main_frame, text="浏览...", command=select_output_dir)
    select_output_btn.grid(row=3, column=2, padx=5, pady=5)
    output_dir_var.trace_add("write", lambda *args: config_data.update({"output_dir": output_dir_var.get()}))

    # 线程数
    ttk.Label(main_frame, text="线程数量:").grid(row=4, column=0, sticky=tk.W, pady=5)
    thread_count_var = tk.StringVar(value=str(config_data["thread_count"]))
    ttk.Entry(main_frame, textvariable=thread_count_var, width=10).grid(row=4, column=1, sticky=tk.W, pady=5)
    ttk.Label(main_frame, text="(1-32之间的整数)").grid(row=4, column=2, sticky=tk.W, pady=5)

    # Logo位置
    ttk.Label(main_frame, text="Logo位置:").grid(row=5, column=0, sticky=tk.W, pady=5)
    logo_position_var = tk.StringVar(value=config_data["logo_position"])
    position_combobox = ttk.Combobox(
        main_frame, textvariable=logo_position_var, values=["上", "下", "左", "右"],
        state="readonly", width=8
    )
    position_combobox.grid(row=5, column=1, sticky=tk.W, pady=5)
    position_combobox.bind("<<ComboboxSelected>>",
                           lambda e: config_data.update({"logo_position": logo_position_var.get()}))
    ttk.Label(main_frame, text="(选择需要裁剪掉的logo位置)").grid(row=5, column=2, sticky=tk.W, pady=5)

    # 裁剪比例
    ttk.Label(main_frame, text="竖图裁剪比例:").grid(row=6, column=0, sticky=tk.W, pady=5)
    vertical_ratio_var = tk.StringVar(value=str(config_data["vertical_ratio"]))
    ttk.Entry(
        main_frame, textvariable=vertical_ratio_var, width=10,
        validate="key", validatecommand=(ratio_validator, "%P")
    ).grid(row=6, column=1, sticky=tk.W, pady=5)
    ttk.Label(main_frame, text="(0-1之间，例如0.12表示保留88%)").grid(row=6, column=2, sticky=tk.W, pady=5)

    ttk.Label(main_frame, text="横图裁剪比例:").grid(row=7, column=0, sticky=tk.W, pady=5)
    horizontal_ratio_var = tk.StringVar(value=str(config_data["horizontal_ratio"]))
    ttk.Entry(
        main_frame, textvariable=horizontal_ratio_var, width=10,
        validate="key", validatecommand=(ratio_validator, "%P")
    ).grid(row=7, column=1, sticky=tk.W, pady=5)
    ttk.Label(main_frame, text="(0-1之间，例如0.09表示保留91%)").grid(row=7, column=2, sticky=tk.W, pady=5)

    # 进度条
    progress_frame = ttk.Frame(main_frame)
    progress_frame.grid(row=8, column=0, columnspan=3, sticky=tk.EW, pady=10)
    progress_var = tk.DoubleVar()
    ttk.Progressbar(progress_frame, variable=progress_var, maximum=100).pack(
        fill=tk.X, side=tk.LEFT, expand=True, padx=5)
    progress_label = ttk.Label(progress_frame, text="进度: 0/0 (0.00%)")
    progress_label.pack(side=tk.RIGHT, padx=5)

    # 状态文本框
    ttk.Label(main_frame, text="处理状态:").grid(row=9, column=0, sticky=tk.NW, pady=5)
    status_frame = ttk.Frame(main_frame)
    status_frame.grid(row=9, column=1, columnspan=2, sticky=tk.NSEW, pady=5)
    scrollbar = ttk.Scrollbar(status_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    status_text = tk.Text(
        status_frame, height=10, width=50, state="disabled",
        wrap=tk.WORD, yscrollcommand=scrollbar.set
    )
    status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=status_text.yview)

    # 按钮
    btn_frame = ttk.Frame(main_frame)
    btn_frame.grid(row=10, column=0, columnspan=3, pady=10)
    start_btn = ttk.Button(btn_frame, text="开始处理", command=start_processing)
    start_btn.pack(side=tk.LEFT, padx=10)
    pause_btn = ttk.Button(btn_frame, text="暂停", command=pause_processing, state="disabled")
    pause_btn.pack(side=tk.LEFT, padx=10)
    stop_btn = ttk.Button(btn_frame, text="停止", command=stop_processing, state="disabled")
    stop_btn.pack(side=tk.LEFT, padx=10)

    # 网格权重
    main_frame.columnconfigure(1, weight=1)
    main_frame.rowconfigure(9, weight=1)
    toggle_output_dir_state()

    return root

# ==============================
# ▶️ 程序入口
# ==============================
if __name__ == "__main__":
    load_config()
    load_progress()
    root = create_gui()

    def on_closing():
        save_config()
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
