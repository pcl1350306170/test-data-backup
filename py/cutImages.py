import os
from PIL import Image, ImageOps
import cv2
import numpy as np

# ========== 配置区域 ==========
source_dir = r"D:\book\tom"    # 原始图片目录
target_dir = r"D:\book\卡贴"       # 输出目录
process_subdirs = True              # 是否递归处理子目录
# =============================

# 目标比例（横图与竖图）
RATIO_LANDSCAPE = 85.5 / 54
RATIO_PORTRAIT = 54 / 85.5

os.makedirs(target_dir, exist_ok=True)

def detect_main_area(image):
    """检测图片主要内容区域，返回中心位置坐标（用于尽量保留主体）"""
    try:
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            areas = [cv2.boundingRect(c) for c in contours]
            # 找面积最大的区域
            largest = max(areas, key=lambda r: r[2]*r[3])
            x, y, w, h = largest
            cx, cy = x + w//2, y + h//2
            return cx, cy
        else:
            # 默认中心
            w, h = image.size
            return w // 2, h // 2
    except Exception:
        w, h = image.size
        return w // 2, h // 2

def crop_to_ratio(image):
    """根据宽高比例裁剪图片"""
    w, h = image.size
    cx, cy = detect_main_area(image)

    if w > h:  # 横图
        target_ratio = RATIO_LANDSCAPE
    else:      # 竖图
        target_ratio = RATIO_PORTRAIT

    current_ratio = w / h

    # 如果当前比例大于目标比例 -> 说明太宽，需要裁掉两边
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        new_h = h
    else:  # 太高，需要裁掉上下
        new_w = w
        new_h = int(w / target_ratio)

    # 保证裁剪框在图片范围内
    left = max(0, min(cx - new_w // 2, w - new_w))
    top = max(0, min(cy - new_h // 2, h - new_h))
    right = left + new_w
    bottom = top + new_h

    return image.crop((left, top, right, bottom))

def process_image(src_path, dst_path):
    try:
        img = Image.open(src_path).convert("RGB")
        cropped = crop_to_ratio(img)
        cropped.save(dst_path, "JPEG", quality=95)
        print(f"✅ 已裁剪：{dst_path}")
    except Exception as e:
        print(f"❌ 处理失败：{src_path} 错误：{e}")

def main():
    print("🚀 开始批量裁剪图片...")
    count = 0
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                src_path = os.path.join(root, file)
                dst_path = os.path.join(target_dir, os.path.splitext(file)[0] + "_crop.jpg")
                process_image(src_path, dst_path)
                count += 1
        if not process_subdirs:
            break

    print(f"\n🎯 处理完成，总计 {count} 张图片已保存到：{target_dir}")

if __name__ == "__main__":
    main()
