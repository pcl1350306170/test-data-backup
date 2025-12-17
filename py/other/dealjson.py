import json
from pathlib import Path

# 配置路径
input_file = r"C:\www\test\py\other\json\words.json"
output_dir = Path(r"C:\www\test\py\other\json\wordJson")

# 创建输出目录（如果不存在）
output_dir.mkdir(parents=True, exist_ok=True)

# 读取原始 JSON 文件
with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# 确保是列表
if not isinstance(data, list):
    raise ValueError("JSON 根元素不是数组！")

total = len(data)
batch_size = 50
num_batches = (total + batch_size - 1) // batch_size  # 向上取整

print(f"共 {total} 个元素，将拆分为 {num_batches} 个文件（每组 {batch_size} 个）")

# 拆分并保存
for i in range(num_batches):
    start = i * batch_size
    end = min(start + batch_size, total)
    batch = data[start:end]

    # 生成带前导零的文件名：words-001.json, words-002.json, ...
    filename = f"绿山墙的安妮-{i+1:03d}.json"
    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=2)

    print(f"已保存：{filename} （{len(batch)} 项）")

print("✅ 拆分完成！")
