import os
import random
import json
import shutil
from PIL import Image

# ---------------- 配置区 ----------------
SOURCE_DIR = r"A:\IMAGE\V33\AI-去二维"      # 源目录（含子目录）
TARGET_DIR = r"F:\book\封面"        # 目标目录
HISTORY_FILE =r"./json/copy_history.json"   # 历史记录文件路径
COPY_COUNT = 50                    # 每次复制多少张
RANDOM_SKIP_RATE = 0.5             # 跳过比例（越大扫描越少，建议 0.7~0.95）
# ---------------------------------------


def load_history():
    """加载历史记录"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_history(history):
    """保存历史记录"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history), f, ensure_ascii=False, indent=2)


def clear_target_dir(target_dir):
    """清空目标目录"""
    if os.path.exists(target_dir):
        for item in os.listdir(target_dir):
            path = os.path.join(target_dir, item)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    else:
        os.makedirs(target_dir, exist_ok=True)


def find_vertical_images_fast(source_dir, needed, history):
    """
    高速查找：仅随机扫描部分文件，一旦找到 enough 张就立即返回
    """
    selected = []
    image_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

    for root, _, files in os.walk(source_dir):
        random.shuffle(files)  # 打乱，避免每次都一样
        for file in files:
            # 随机跳过大量文件
            if random.random() < RANDOM_SKIP_RATE:
                continue

            if not file.lower().endswith(image_ext):
                continue

            full_path = os.path.join(root, file)
            if full_path in history:
                continue

            try:
                with Image.open(full_path) as img:
                    w, h = img.size
                    if h > w:
                        selected.append(full_path)
                        if len(selected) >= needed:
                            return selected
            except Exception:
                continue

    return selected


def copy_images(selected, target_dir, history):
    """复制图片并更新历史"""
    clear_target_dir(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    for img_path in selected:
        dest_path = os.path.join(target_dir, os.path.basename(img_path))
        shutil.copy2(img_path, dest_path)
        history.add(img_path)

    save_history(history)


def main():
    history = load_history()
    selected = find_vertical_images_fast(SOURCE_DIR, COPY_COUNT, history)

    if not selected:
        print("⚠️ 没找到符合条件的新图片（可能都复制过了）。")
        return

    copy_images(selected, TARGET_DIR, history)
    print(f"✅ 本次复制完成：{len(selected)} 张图片。")
    print(f"📁 目标目录：{TARGET_DIR}")


if __name__ == "__main__":
    main()
