import os
import shutil
from nsfw_detector import predict
from PIL import Image

# ================== 配置区 ==================
SOURCE_DIR = r"G:\图片\竖屏壁纸绝美"     # 原始图片目录
TARGET_DIR = r"G:\图片\竖屏壁纸绝美2"     # 检测到违规图片的存放目录
PROCESS_SUBDIRS = True                    # 是否处理子目录
NSFW_THRESHOLD = 0.6                      # 色情概率阈值，越高越严格（0~1）
# ===========================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def get_all_images(root_dir):
    """递归获取所有图片路径"""
    image_files = []
    for root, _, files in os.walk(root_dir):
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                image_files.append(os.path.join(root, f))
        if not PROCESS_SUBDIRS:
            break
    return image_files

def detect_nsfw_images(model, image_paths):
    """检测并移动违规图片"""
    total = len(image_paths)
    moved = 0

    print(f"🚀 开始检测，共 {total} 张图片...\n")

    for idx, img_path in enumerate(image_paths, 1):
        try:
            # 检测图片
            preds = model.predict(img_path)
            probs = list(preds.values())[0]
            nsfw_score = probs.get("porn", 0) + probs.get("sexy", 0)

            if nsfw_score >= NSFW_THRESHOLD:
                rel_path = os.path.relpath(os.path.dirname(img_path), SOURCE_DIR)
                dest_dir = os.path.join(TARGET_DIR, rel_path)
                ensure_dir(dest_dir)

                dest_path = os.path.join(dest_dir, os.path.basename(img_path))
                shutil.move(img_path, dest_path)
                moved += 1
                print(f"🚫 [{idx}/{total}] 违规图片已剪切：{dest_path}")
            else:
                print(f"✅ [{idx}/{total}] 正常：{img_path}")

        except Exception as e:
            print(f"⚠️ 检测失败：{img_path} -> {e}")

    print(f"\n🎯 检测完成：共检测 {total} 张图片，发现并剪切 {moved} 张违规图片。")

def main():
    print("🧠 正在加载离线 NSFW 模型，请稍等...")
    model = predict.load_model()  # 会自动下载一次模型文件
    print("✅ 模型加载完成\n")

    image_paths = get_all_images(SOURCE_DIR)
    detect_nsfw_images(model, image_paths)

if __name__ == "__main__":
    main()
