import os
from PIL import Image

# === 配置部分 ===
# 需要处理的文件夹路径（会递归遍历所有子文件夹）
input_dir = r"A:\IMAGE\V33\AI-2"

# 右下角裁剪比例（例如去掉图片宽度的10%、高度的8%）
CROP_RATIO_RIGHT = 0
CROP_RATIO_BOTTOM = 0.09

# 支持的图片格式
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')

# === 核心裁剪函数 ===
def crop_logo(image_path):
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            # 计算裁剪区域：左、上、右、下
            left = 0
            top = 0
            right = width - int(width * CROP_RATIO_RIGHT)
            bottom = height - int(height * CROP_RATIO_BOTTOM)

            cropped = img.crop((left, top, right, bottom))
            cropped.save(image_path)  # 直接覆盖原图
            print(f"✅ 已裁剪: {image_path}")

    except Exception as e:
        print(f"❌ 处理失败 {image_path}: {e}")

# === 递归处理文件夹 ===
def process_folder(folder_path):
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(IMAGE_EXTENSIONS):
                image_path = os.path.join(root, file)
                crop_logo(image_path)

# === 程序入口 ===
if __name__ == "__main__":
    print(f"🚀 开始处理文件夹：{input_dir}")
    process_folder(input_dir)
    print("\n🎉 所有图片已裁剪完成并覆盖原文件！")
