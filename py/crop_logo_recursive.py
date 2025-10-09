import os
import sys
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import threading

# ============ 可配置参数 ============
INPUT_DIR = r"A:\IMAGE\V33\AI-4"
OUTPUT_DIR = r"F:\download\output"

# 裁剪方式：按比例 或 固定像素
CROP_MODE = "ratio"  # 可选: "ratio" 或 "pixel"
CROP_RATIO = 0.91     # 当 CROP_MODE="ratio" 时，保留高度比例（0.85 表示裁掉底部 15%）
CROP_BOTTOM_PIXEL = 100  # 当 CROP_MODE="pixel" 时，裁掉底部固定像素高度

# 最大线程数
MAX_WORKERS = 5
# ==================================

stop_flag = threading.Event()


def crop_image(src_path, dest_path):
    """裁剪单张图片"""
    try:
        img = Image.open(src_path)
        width, height = img.size

        if CROP_MODE == "ratio":
            bottom = int(height * CROP_RATIO)
        else:
            bottom = max(0, height - CROP_BOTTOM_PIXEL)

        cropped = img.crop((0, 0, width, bottom))

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        cropped.save(dest_path)
        return True
    except Exception as e:
        print(f"❌ 裁剪失败：{src_path}，错误：{e}")
        return False


def get_all_images(base_dir):
    """递归获取所有图片文件路径"""
    image_files = []
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".gif")):
                image_files.append(os.path.join(root, f))
    return image_files


def process_images():
    """批量处理所有图片"""
    if not os.path.exists(INPUT_DIR):
        print(f"❌ 输入目录不存在：{INPUT_DIR}")
        sys.exit(1)

    files = get_all_images(INPUT_DIR)
    if not files:
        print("⚠️ 未找到图片文件")
        return

    print(f"开始裁剪，共 {len(files)} 张图片...（可按 Ctrl+C 停止）")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for src in files:
            if stop_flag.is_set():
                break

            # 保留目录结构
            rel_path = os.path.relpath(src, INPUT_DIR)
            dest = os.path.join(OUTPUT_DIR, rel_path)
            futures.append(executor.submit(crop_image, src, dest))

        # 显示进度条
        for _ in tqdm(as_completed(futures), total=len(futures), desc="裁剪进度", ncols=80):
            if stop_flag.is_set():
                break

    print("✅ 所有图片处理完成！")


def main():
    try:
        process_images()
    except KeyboardInterrupt:
        stop_flag.set()
        print("\n🛑 用户中断，已停止任务。")
        sys.exit(0)


if __name__ == "__main__":
    main()
