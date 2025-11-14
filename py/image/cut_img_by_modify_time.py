import os
import shutil
from datetime import datetime
import sys

# 配置参数
SOURCE_DIR = r"H:\IMAGE\V33\AI-3"  # 源目录
TARGET_DIR = r"H:\IMAGE\V33\AI"    # 目标目录
TARGET_DATE = datetime(2025, 11, 13)  # 目标修改日期（2025年11月12日）
SUPPORTED_IMG_EXTS = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp']  # 支持的图片格式

# 统计变量
total_files = 0
processed_files = 0
moved_files = 0
overwritten_files = 0
deleted_dirs = 0

def get_file_modify_date(file_path):
    """获取文件的修改日期（仅日期部分）"""
    try:
        # 获取文件修改时间戳（Windows系统）
        modify_timestamp = os.path.getmtime(file_path)
        # 转换为datetime对象，仅保留日期部分
        modify_date = datetime.fromtimestamp(modify_timestamp).date()
        return modify_date
    except Exception as e:
        print(f"⚠️ 获取文件 {file_path} 修改时间失败: {str(e)}")
        return None

def move_file_with_structure(source_file, source_root, target_root):
    """保留目录结构移动文件，重名则覆盖"""
    global moved_files, overwritten_files

    # 计算相对路径（相对于源根目录）
    rel_path = os.path.relpath(os.path.dirname(source_file), source_root)
    # 构建目标目录路径
    target_dir = os.path.join(target_root, rel_path)
    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)

    # 构建目标文件路径
    target_file = os.path.join(target_dir, os.path.basename(source_file))

    # 检查是否需要覆盖
    if os.path.exists(target_file):
        os.remove(target_file)  # 删除原有文件
        overwritten_files += 1
        log_msg = f"🔄 覆盖文件: {source_file} -> {target_file}"
    else:
        moved_files += 1
        log_msg = f"✅ 移动文件: {source_file} -> {target_file}"

    # 移动文件
    shutil.move(source_file, target_file)
    print(log_msg)
    return True

def scan_and_move_files():
    """扫描源目录，移动符合条件的图片"""
    global total_files, processed_files

    # 先统计所有图片文件总数（用于进度计算）
    print("📊 正在统计文件总数...")
    for root, dirs, files in os.walk(SOURCE_DIR):
        for file in files:
            if os.path.splitext(file.lower())[1] in SUPPORTED_IMG_EXTS:
                total_files += 1
    print(f"📋 共发现 {total_files} 个图片文件\n")

    # 扫描并移动符合条件的文件
    print("🚀 开始扫描并移动文件...")
    for root, dirs, files in os.walk(SOURCE_DIR):
        for file in files:
            # 过滤支持的图片格式
            file_ext = os.path.splitext(file.lower())[1]
            if file_ext not in SUPPORTED_IMG_EXTS:
                continue

            file_path = os.path.join(root, file)
            processed_files += 1

            # 获取文件修改日期
            modify_date = get_file_modify_date(file_path)
            if not modify_date:
                continue

            # 检查是否符合目标日期
            if modify_date == TARGET_DATE.date():
                move_file_with_structure(file_path, SOURCE_DIR, TARGET_DIR)

            # 显示进度
            progress = (processed_files / total_files) * 100 if total_files > 0 else 100
            sys.stdout.write(f"\r⚡ 处理进度: {processed_files}/{total_files} ({progress:.1f}%)")
            sys.stdout.flush()

    print("\n\n📥 文件处理完成！")
    print(f"📈 统计结果:")
    print(f"   - 总处理文件数: {processed_files}")
    print(f"   - 成功移动文件数: {moved_files}")
    print(f"   - 覆盖文件数: {overwritten_files}")

def delete_empty_dirs():
    """删除源目录下所有空目录"""
    global deleted_dirs

    print("\n🗑️ 开始删除空目录...")
    # 反向遍历目录（先删子目录，再删父目录）
    for root, dirs, files in os.walk(SOURCE_DIR, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            # 检查目录是否为空
            if not os.listdir(dir_path):
                try:
                    os.rmdir(dir_path)
                    deleted_dirs += 1
                    print(f"🗑️ 删除空目录: {dir_path}")
                except Exception as e:
                    print(f"⚠️ 删除目录 {dir_path} 失败: {str(e)}")

    print(f"\n🗑️ 空目录删除完成，共删除 {deleted_dirs} 个空目录")

def main():
    """主函数"""
    print("======================================")
    print("📁 图片批量移动工具")
    print(f"📌 源目录: {SOURCE_DIR}")
    print(f"📌 目标目录: {TARGET_DIR}")
    print(f"📌 目标修改日期: {TARGET_DATE.strftime('%Y年%m月%d日')}")
    print("======================================\n")

    # 检查源目录是否存在
    if not os.path.exists(SOURCE_DIR):
        print(f"❌ 错误: 源目录 {SOURCE_DIR} 不存在！")
        return

    # 确保目标目录存在
    os.makedirs(TARGET_DIR, exist_ok=True)

    try:
        # 扫描并移动文件
        scan_and_move_files()

        # 删除空目录
        delete_empty_dirs()

        print("\n🎉 所有操作完成！")
        print(f"📊 最终统计:")
        print(f"   - 移动文件: {moved_files} 个")
        print(f"   - 覆盖文件: {overwritten_files} 个")
        print(f"   - 删除空目录: {deleted_dirs} 个")
    except KeyboardInterrupt:
        print("\n\n⚠️ 操作被用户中断！")
    except Exception as e:
        print(f"\n\n❌ 操作出错: {str(e)}")

if __name__ == "__main__":
    main()
