import os
from PIL import Image

# =================== 配置区 ===================
image_dir = r"G:\图片\竖屏壁纸绝美"  # 图片所在目录
process_subdirs = True              # 是否递归处理子目录
min_width = 800
min_height = 800
# ============================================

def is_image_file(filename):
    return filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif'))

def check_and_delete_image(image_path):
    try:
        with Image.open(image_path) as img:
            width, height = img.size

        if width < min_width or height < min_height:
            os.remove(image_path)
            print(f"🗑️ 已删除：{image_path} ({width}x{height})")
        else:
            print(f"✅ 保留：{image_path} ({width}x{height})")

    except Exception as e:
        print(f"⚠️ 无法读取图片：{image_path}，错误：{e}")

def main():
    print("🚀 开始检查图片分辨率...\n")

    total = 0
    deleted = 0

    for root, _, files in os.walk(image_dir):
        for file in files:
            if is_image_file(file):
                total += 1
                path = os.path.join(root, file)
                try:
                    with Image.open(path) as img:
                        w, h = img.size
                    if w < min_width or h < min_height:
                        os.remove(path)
                        deleted += 1
                        print(f"🗑️ 删除 {path} ({w}x{h})")
                    else:
                        print(f"✅ 保留 {path} ({w}x{h})")
                except Exception as e:
                    print(f"⚠️ 读取失败：{path} -> {e}")
        if not process_subdirs:
            break

    print(f"\n🎯 完成，总共检查 {total} 张图片，删除 {deleted} 张。")

if __name__ == "__main__":
    main()
