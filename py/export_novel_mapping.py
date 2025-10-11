import os
import json
import pymysql

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "test",
    "charset": "utf8mb4"
}

# 输出文件路径
OUTPUT_PATH = r"./json/novelMapping.json"

def export_novel_mapping():
    try:
        # 连接数据库
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 查询数据
        cursor.execute("SELECT `old`, `new` FROM v_pornographic_novel_replacement_string")
        rows = cursor.fetchall()

        if not rows:
            print("❌ 没有查询到数据，表可能为空。")
            return

        # 构建字典
        mapping = {}
        for row in rows:
            old_val = row.get("old")
            new_val = row.get("new")
            if old_val and new_val:
                mapping[old_val.strip()] = new_val.strip()

        # 创建目录
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

        # 写入 JSON 文件
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

        print(f"✅ 导出成功，共 {len(mapping)} 条映射，保存路径：{OUTPUT_PATH}")

    except Exception as e:
        print(f"❌ 导出失败：{e}")

    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

if __name__ == "__main__":
    export_novel_mapping()
