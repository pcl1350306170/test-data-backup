import os
import re
import chardet

# ======== 可自定义配置区域 ========
base_dir = r"C:\book\大于5M合并"  # 目标目录
process_subdirs = True       # 是否处理子目录，False 时只处理当前目录
replace_dict = {
    "欢迎光临翠微居": "",
    "…": "",
    "*": "",
    "&": "",
    "#": "",
    "=": "",
    "@": "",
    "欢迎光临翠微居小说阅读网www.cuiweiju.com": "",
    "www.cuiweiju.com": ""
}
# =================================

def detect_encoding(file_path):
    """自动检测文件编码"""
    with open(file_path, 'rb') as f:
        raw = f.read(4096)
    result = chardet.detect(raw)
    return result['encoding'] or 'utf-8'

def safe_read(file_path):
    """读取文件内容，自动识别编码"""
    encoding = detect_encoding(file_path)
    with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
        return f.read()

def replace_text(text):
    """执行替换逻辑"""
    # 先替换字典中的关键词
    for old, new in replace_dict.items():
        text = text.replace(old, new)

    # 再去掉 www 开头的网址
    text = re.sub(r'www\.[^\s]+', '', text)

    return text

def process_file(file_path):
    print(f"正在处理：{file_path}")
    try:
        text = safe_read(file_path)
        new_text = replace_text(text)

        # 新文件路径（加上 _clean 后缀）
        dir_name, file_name = os.path.split(file_path)
        name, ext = os.path.splitext(file_name)
        new_file = os.path.join(dir_name, f"{name}_clean{ext}")

        # 写入新文件（utf-8 编码）
        with open(new_file, 'w', encoding='utf-8') as f:
            f.write(new_text)

        print(f"✅ 已生成：{new_file}")
    except Exception as e:
        print(f"❌ 处理失败：{file_path}，错误：{e}")

def main():
    if process_subdirs:
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.lower().endswith('.txt'):
                    process_file(os.path.join(root, file))
    else:
        for file in os.listdir(base_dir):
            if file.lower().endswith('.txt'):
                process_file(os.path.join(base_dir, file))

if __name__ == "__main__":
    main()
