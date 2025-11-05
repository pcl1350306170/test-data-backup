import os
import json
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime
import base64
import fractions  # 用来处理 IFDRational 类型

# ================== 配置区 ==================
source_dir = r"D:\book\img"  # 图片所在目录
output_dir = r"C:\www\test\py\json"      # JSON 输出目录
output_file = os.path.join(output_dir, "exif_data.json")  # 输出文件路径
process_subdirs = True                    # 是否递归处理子目录
# ===========================================

def ensure_dir_exists(path):
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)

def convert_to_serializable(value):
    """确保值是可被 JSON 序列化的，并跳过无法解析的字段"""
    try:
        if isinstance(value, bytes):
            # 如果是 bytes 类型，转换为 base64 字符串
            return base64.b64encode(value).decode('utf-8')
        elif isinstance(value, datetime):
            # 如果是 datetime 类型，转换为字符串
            return value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, fractions.Fraction):
            # 如果是 IFDRational 类型（EXIF 中的分数），转换为 float
            return float(value)
        elif isinstance(value, dict):
            # 如果是 dict 类型，递归处理
            return {k: convert_to_serializable(v) for k, v in value.items()}
        elif isinstance(value, list):
            # 如果是 list 类型，递归处理
            return [convert_to_serializable(v) for v in value]
        elif isinstance(value, tuple):
            # 如果是 tuple，转换为 list
            return [convert_to_serializable(v) for v in value]
        elif isinstance(value, set):
            # 如果是 set，转换为 list
            return [convert_to_serializable(v) for v in value]
        elif value is None:
            # 如果是 None，直接返回
            return None
        else:
            # 其他类型，返回原值
            return value
    except Exception as e:
        # 遇到无法解析的字段时，跳过并打印警告
        print(f"⚠️ 跳过无法解析的字段: {e}")
        return None  # 返回 None 跳过这个字段

def get_exif_data(image_path):
    """提取图片的 EXIF 数据"""
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()
        if exif_data is not None:
            # 将 EXIF 数据中的数字标签转换为描述性标签
            exif_dict = {}
            for tag, value in exif_data.items():
                tag_name = TAGS.get(tag, tag)
                exif_dict[tag_name] = convert_to_serializable(value)
            return exif_dict
        else:
            return None
    except Exception as e:
        print(f"⚠️ 无法读取 EXIF 数据：{image_path} -> {e}")
        return None

def get_all_images(root_dir):
    """递归获取所有图片路径"""
    image_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                image_files.append(os.path.join(root, file))
        if not process_subdirs:
            break
    return image_files

def process_images():
    """处理图片，提取 EXIF 数据并保存到 JSON"""
    ensure_dir_exists(output_dir)

    image_paths = get_all_images(source_dir)
    exif_data_list = []

    for img_path in image_paths:
        exif_data = get_exif_data(img_path)
        if exif_data is not None:
            exif_data_list.append({
                "file_path": img_path,
                "exif_data": exif_data
            })

    # 将所有 EXIF 数据写入 JSON 文件
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(exif_data_list, f, ensure_ascii=False, indent=4)

    print(f"✅ EXIF 数据已保存到 {output_file}")

if __name__ == "__main__":
    process_images()
