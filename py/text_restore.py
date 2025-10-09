import os
import json
import re

# ========== 配置区域 ==========
# 输入文件夹
INPUT_DIR = r"F:\data\txt_in"
# 输出文件夹
OUTPUT_DIR = r"F:\data\txt_out"
# 关键词映射表文件
MAPPING_FILE = r"F:\data\mapping.json"
# =============================

def load_mapping():
    """读取关键词映射表"""
    if not os.path.exists(MAPPING_FILE):
        raise FileNotFoundError(f"未找到映射文件：{MAPPING_FILE}")
    with open(MAPPING_FILE, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    print(f"✅ 已加载 {len(mapping)} 条关键词映射规则")
    return mapping

def restore_text(text, mapping):
    """根据映射表替换模糊词"""
    for k, v in mapping.items():
        # 使用正则忽略大小写替换
        pattern = re.compile(re.escape(k), re.IGNORECASE)
        text = pattern.sub(v, text)
    return text

def process_file(src_path, dst_path, mapping):
    """处理单个文件"""
    try:
        with open(src_path, "r", encoding="utf-8", errors="ignore") as fin:
            content = fin.read()
        new_content = restore_text(content, mapping)

        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(dst_path, "w", encoding="utf-8") as fout:
            fout.write(new_content)
        print(f"✅ 已处理：{src_path} → {dst_path}")
    except Exception as e:
        print(f"❌ 文件处理失败：{src_path}，错误：{e}")

def process_all():
    """递归处理整个输入目录"""
    mapping = load_mapping()
    total_files = 0

    for root, _, files in os.walk(INPUT_DIR):
        for f in files:
            if f.lower().endswith(".txt"):
                total_files += 1
                src = os.path.join(root, f)
                relative_path = os.path.relpath(src, INPUT_DIR)
                dst = os.path.join(OUTPUT_DIR, relative_path)
                process_file(src, dst, mapping)

    if total_files == 0:
        print("⚠️ 未找到任何 .txt 文件！")
    else:
        print(f"\n🎉 所有文件处理完成，共处理 {total_files} 个 .txt 文件。")

if __name__ == "__main__":
    process_all()
