import os
import re
import pymysql
import requests
from bs4 import BeautifulSoup

# -------------------
# Database Configuration
# -------------------
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "test",
    "charset": "utf8mb4"
}

# -------------------
# Save Directory
# -------------------
SAVE_DIR = "F:\\download\\txt"

# -------------------
# Filter Keywords
# -------------------
FILTER_KEYWORDS = ["请尊重原着,勿文章作任何修改", "本文章仅提供参考,剧中描写脱离现实"]

# -------------------
# Initialize
# -------------------
os.makedirs(SAVE_DIR, exist_ok=True)

# -------------------
# Database Connection
# -------------------
def get_db_connection():
    return pymysql.connect(**DB_CONFIG)

# -------------------
# Fetch Pending Data
# -------------------
def fetch_pending_data(conn, processed_ids):
    # 如果 processed_ids 为空，直接查询所有未处理的数据
    if not processed_ids:
        sql = """
            SELECT id, data_key, data_content, data_type
            FROM general_data
            WHERE data_type LIKE 'blog_nevel-%'
              AND is_deleted=0
        """
    else:
        # 如果 processed_ids 不为空，查询未处理的数据，并排除已处理的 ID
        sql = """
            SELECT id, data_key, data_content, data_type
            FROM general_data
            WHERE data_type LIKE 'blog_nevel-%'
              AND is_deleted=0
              AND id NOT IN (%s)
        """
        processed_ids_str = ",".join(map(str, processed_ids))
        sql = sql % processed_ids_str

    # 执行 SQL 查询
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql)
        return cursor.fetchall()

# -------------------
# Update Status
# -------------------
def mark_as_deleted(conn, record_id):
    with conn.cursor() as cursor:
        cursor.execute("UPDATE general_data SET is_deleted=1 WHERE id=%s", (record_id,))
    conn.commit()

# -------------------
# Fetch Blog Content
# -------------------
def fetch_blog_text(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.encoding = resp.apparent_encoding
    if resp.status_code != 200:
        raise Exception(f"Request failed: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    outer_div = soup.find("div", class_="date-outer")
    if not outer_div:
        raise Exception("Could not find the 'date-outer' class.")

    p_tags = outer_div.find_all("p")
    lines = []
    for p in p_tags:
        text = p.get_text(strip=True)
        if not text:
            continue
        # Filter keywords
        if any(kw in text for kw in FILTER_KEYWORDS):
            continue
        lines.append(text)
    return lines

# -------------------
# Generate Subdirectory Name
# -------------------
def generate_subdirectory_name(data_type):
    # Remove the "blog_nevel-" prefix
    return data_type.replace("blog_nevel-", "")

# -------------------
# Generate Unique Filename
# -------------------
def get_unique_filename(subdir, title):
    base_filename = re.sub(r'[\\/:*?"<>|]', '_', title)
    base_filepath = os.path.join(SAVE_DIR, subdir, f"{base_filename}.txt")

    # If file exists, add a counter suffix
    counter = 1
    while os.path.exists(base_filepath):
        base_filepath = os.path.join(SAVE_DIR, subdir, f"{base_filename}_{counter}.txt")
        counter += 1
    return base_filepath

# -------------------
# Save to TXT File
# -------------------
def save_to_txt(subdir, title, lines):
    os.makedirs(os.path.join(SAVE_DIR, subdir), exist_ok=True)
    file_path = get_unique_filename(subdir, title)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ File saved: {file_path}")

# -------------------
# Main Function
# -------------------
def main():
    processed_ids = []  # List of already processed IDs
    conn = get_db_connection()
    try:
        records = fetch_pending_data(conn, processed_ids)
        print(f"Found {len(records)} records to download.")

        for record in records:
            rid = record["id"]
            title = record["data_key"]
            url = record["data_content"]
            data_type = record["data_type"]

            subdir = generate_subdirectory_name(data_type)

            print(f"\n➡️ Processing: {title}")
            try:
                lines = fetch_blog_text(url)
                if not lines:
                    print("❌ No valid content on the page, skipping.")
                    continue
                save_to_txt(subdir, title, lines)
                mark_as_deleted(conn, rid)
                processed_ids.append(rid)
                print(f"✅ Download complete: {title}")
            except Exception as e:
                print(f"⚠️ Error: {title} -> {e}")
                continue

    finally:
        conn.close()
        print("\nAll tasks complete ✅")

# -------------------
# Entry Point
# -------------------
if __name__ == "__main__":
    main()
