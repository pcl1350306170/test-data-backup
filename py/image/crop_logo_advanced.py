# -*- coding: utf-8 -*-
import os
import threading
import time
import json
from PIL import Image
from queue import Queue

# ==============================
# 🧩 配置区域
# ==============================
INPUT_DIR = r"D:\download\V33图片"        # 输入文件夹
OUTPUT_DIR = r"D:\download\IMAGE3"  # 输出文件夹（与原结构一致）
THREAD_COUNT = 5                         # 线程数量
REPLACE_ORIGINAL = True                 # True = 覆盖原文件，False = 另存为
PROGRESS_FILE = "./json/crop_progress.json"     # 进度记录文件
SUPPORTED_EXTS = [".jpg", ".jpeg", ".png", ".bmp", ".webp"]

# ==============================
# ⚙️ 控制变量
# ==============================
task_queue = Queue()
pause_event = threading.Event()
stop_event = threading.Event()
lock = threading.Lock()
progress_data = {}

# ==============================
# 📂 加载或保存进度
# ==============================
def load_progress():
    global progress_data
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
        except:
            progress_data = {}
    else:
        progress_data = {}

def save_progress():
    with lock:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)

# ==============================
# 🖼️ 图片裁剪逻辑
# ==============================
def process_image(image_path, output_path):
    try:
        with Image.open(image_path) as img:
            width, height = img.size

            # ✅ 判断图片方向自动设置底部裁剪比例
            if height > width:
                CROP_RATIO_BOTTOM = 0.12  # 竖图
            else:
                CROP_RATIO_BOTTOM = 0.09  # 横图

            crop_height = int(height * (1 - CROP_RATIO_BOTTOM))
            cropped_img = img.crop((0, 0, width, crop_height))

            # 创建输出目录
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cropped_img.save(output_path)

            print(f"─=≡Σ(((つ•̀ω•́)つ=== 裁--剪---完-----成----: {os.path.basename(image_path)} (比例 {CROP_RATIO_BOTTOM})")

    except Exception as e:
        print(f"❌ 裁剪出错: {image_path} - {e}")

# ==============================
# 🧵 工作线程函数
# ==============================
def worker():
    while not stop_event.is_set():
        try:
            image_path = task_queue.get(timeout=1)
        except:
            break  # 队列空了

        if stop_event.is_set():
            break

        while pause_event.is_set():
            time.sleep(0.5)

        rel_path = os.path.relpath(image_path, INPUT_DIR)
        output_path = image_path if REPLACE_ORIGINAL else os.path.join(OUTPUT_DIR, rel_path)

        if progress_data.get(image_path):
            task_queue.task_done()
            continue

        process_image(image_path, output_path)
        progress_data[image_path] = True
        save_progress()
        task_queue.task_done()

# ==============================
# 📋 扫描目录
# ==============================
def scan_images():
    for root, dirs, files in os.walk(INPUT_DIR):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in SUPPORTED_EXTS:
                full_path = os.path.join(root, file)
                if not progress_data.get(full_path):
                    task_queue.put(full_path)

# ==============================
# 🚀 主逻辑
# ==============================
def main():
    load_progress()
    scan_images()

    total = task_queue.qsize()
    print(f"📂 共找到 {total} 张待处理图片")

    threads = []
    for _ in range(THREAD_COUNT):
        t = threading.Thread(target=worker)
        t.start()
        threads.append(t)

    try:
        while any(t.is_alive() for t in threads):
            done = len(progress_data)
            percent = (done / (total or 1)) * 100
            print(f"￣へ￣  (｀⌒´メ)  (￣ェ￣;)进度: {done}/{total} ({percent:.2f}%)")
            time.sleep(60)
    except KeyboardInterrupt:
        stop_event.set()
        print("\n🟥 用户中止，正在安全退出...")
    finally:
        for t in threads:
            t.join()
        save_progress()
        print("\n✅ 所有任务完成！")

# ==============================
# ▶️ 运行入口
# ==============================
if __name__ == "__main__":
    main()
