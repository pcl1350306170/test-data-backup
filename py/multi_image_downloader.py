import os
import requests
import pymysql
import threading
import queue
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "test",
    "charset": "utf8mb4"
}

# 图片保存根目录
BASE_DIR = r"F:\download\MTMT"
os.makedirs(BASE_DIR, exist_ok=True)

# 最大线程数
MAX_THREADS = 5

# 停止下载标志
stop_flag = threading.Event()

# 打印锁（防止输出混乱）
print_lock = threading.Lock()

def get_filename_from_url(url):
    """从URL中提取文件名"""
    filename = url.split("/")[-1].split("?")[0]
    if not filename:
        filename = "unknown.jpg"
    return filename

def download_image(url, save_dir):
    """下载单张图片"""
    try:
        resp = requests.get(url.strip(), timeout=10)
        if resp.status_code != 200:
            with print_lock:
                print(f"[失败] 状态码：{resp.status_code} => {url}")
            return False

        img = Image.open(BytesIO(resp.content))
        if img.width < 100 or img.height < 100:
            with print_lock:
                print(f"[跳过小图] {url} ({img.width}x{img.height})")
            return False

        filename = get_filename_from_url(url)
        filepath = os.path.join(save_dir, filename)
        img.save(filepath)
        with print_lock:
            print(f"[完成] {filepath}")
        return True

    except Exception as e:
        with print_lock:
            print(f"[错误] {url} => {e}")
        return False


def worker_task(uid, title, urls):
    """线程任务：下载一个数据记录中的所有图片"""
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "untitled"
    save_dir = os.path.join(BASE_DIR, safe_title)
    os.makedirs(save_dir, exist_ok=True)

    for url in urls:
        if stop_flag.is_set():  # 停止下载
            with print_lock:
                print("⚠️ 检测到停止信号，等待当前任务结束...")
            return
        download_image(url, save_dir)


def fetch_data():
    """从数据库读取数据"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute("SELECT uid, title, content FROM web_crawl_data WHERE is_deleted=0")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def mark_as_deleted(uid):
    """标记数据库中的记录为已处理"""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("UPDATE web_crawl_data SET is_deleted=1 WHERE uid=%s", (uid,))
    conn.commit()
    cursor.close()
    conn.close()


def process_data():
    """主流程"""
    rows = fetch_data()
    print(f"共读取 {len(rows)} 条数据\n")

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = []
        for row in rows:
            uid = row["uid"]
            title = row["title"] or "untitled"
            content = row["content"]
            if not content:
                print(f"{uid} 没有图片，跳过")
                continue

            urls = [u.strip() for u in content.split(",") if u.strip()]
            futures.append(executor.submit(worker_task, uid, title, urls))

        for i, f in enumerate(as_completed(futures), start=1):
            if stop_flag.is_set():
                break
            try:
                f.result()
            except Exception as e:
                print(f"[任务异常] {e}")
            print(f"进度：{i}/{len(futures)} 条记录已完成")

    print("\n✅ 所有下载任务完成")


def stop_listener():
    """监听用户输入，用于停止下载"""
    while True:
        cmd = input()
        if cmd.lower() == "q":
            stop_flag.set()
            print("\n🛑 已请求停止下载，执行完当前任务后结束。\n")
            break


if __name__ == "__main__":
    # 开启监听线程
    listener_thread = threading.Thread(target=stop_listener, daemon=True)
    listener_thread.start()

    process_data()
