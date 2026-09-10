# deduplicate_words.py

import json
from pathlib import Path

# 文件路径
file_path = Path(r"C:\www\test\py\other\json\words.json")

def main():
    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}")
        return

    try:
        # 读取 JSON 文件
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            print("❌ 文件内容不是列表格式")
            return

        seen_words = set()
        unique_data = []

        for item in data:
            if not isinstance(item, dict) or "Word" not in item:
                # 如果不是有效对象，保留原样（可选）
                unique_data.append(item)
                continue

            word = item["Word"]
            if word not in seen_words:
                seen_words.add(word)
                unique_data.append(item)
            # else: 跳过重复项

        # 如果有去重发生，写回原文件
        if len(unique_data) != len(data):
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(unique_data, f, ensure_ascii=False, indent=2)
            print(f"✅ 去重完成！原 {len(data)} 项 → 现 {len(unique_data)} 项")
        else:
            print("ℹ️ 无重复项，文件未改动")

    except json.JSONDecodeError as e:
        print(f"❌ JSON 格式错误: {e}")
    except Exception as e:
        print(f"❌ 发生错误: {e}")

if __name__ == "__main__":
    main()
