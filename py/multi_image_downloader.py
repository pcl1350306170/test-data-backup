import os
import requests
import pymysql
import threading
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
# 下载重试次数
RETRY_COUNT = 2
# 停止下载标志
stop_flag = threading.Event()
print_lock = threading.Lock()

# 需要直接跳过的图片文件名
SKIP_IMAGES = {
    "rss.png",
    "post.png",
    "reply.png",
    "none.gif",
    "home-old.gif",
    "7.gif"  # 匹配level/7.gif
}


def get_filename_from_url(url):
    """从URL中提取文件名"""
    filename = url.split("/")[-1].split("?")[0]
    return filename if filename else "unknown.jpg"


def check_skip_image(url):
    """检查是否是需要跳过的特定图片"""
    filename = get_filename_from_url(url)
    return filename in SKIP_IMAGES


def check_image_exists(url, save_dir):
    """检查图片是否已存在"""
    filename = get_filename_from_url(url)
    filepath = os.path.join(save_dir, filename)
    return os.path.exists(filepath)


def download_image(url, save_dir, retry=0):
    """下载单张图片，支持重试机制"""
    try:
        # 先检查是否是需要直接跳过的图片
        if check_skip_image(url):
            with print_lock:
                print(f"[跳过指定小图] {url}")
            return True

        # 检查图片是否已存在
        if check_image_exists(url, save_dir):
            filename = get_filename_from_url(url)
            with print_lock:
                print(f"[已存在] {os.path.join(save_dir, filename)}")
            return True

        resp = requests.get(url.strip(), timeout=10)
        if resp.status_code != 200:
            with print_lock:
                print(f"[失败] 状态码：{resp.status_code} => {url}")
            # 只有特定状态码才重试
            if retry < RETRY_COUNT and resp.status_code in [500, 502, 503, 504, 429]:
                with print_lock:
                    print(f"[重试] {url} (剩余次数: {RETRY_COUNT - retry - 1})")
                return download_image(url, save_dir, retry + 1)
            return False

        img = Image.open(BytesIO(resp.content))
        if img.width < 100 or img.height < 100:
            with print_lock:
                print(f"[跳过小图] {url} ({img.width}x{img.height})")
            return True  # 小图视为处理成功，避免重复检查

        filename = get_filename_from_url(url)
        filepath = os.path.join(save_dir, filename)
        img.save(filepath)
        with print_lock:
            print(f"[完成] {filepath}")
        return True

    except requests.exceptions.Timeout:
        with print_lock:
            print(f"[超时] {url}")
        # 超时错误重试
        if retry < RETRY_COUNT:
            with print_lock:
                print(f"[重试] {url} (剩余次数: {RETRY_COUNT - retry - 1})")
            return download_image(url, save_dir, retry + 1)
        return False
    except Exception as e:
        with print_lock:
            print(f"[错误] {url} => {str(e)[:100]}")  # 限制错误信息长度
        return False


def worker_task(uid, title, urls):
    """线程任务：下载一个数据记录中的所有图片"""
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "untitled"
    save_dir = os.path.join(BASE_DIR, safe_title)
    os.makedirs(save_dir, exist_ok=True)

    total = len(urls)
    success_count = 0
    failed_urls = []

    for url in urls:
        if stop_flag.is_set():
            with print_lock:
                print("⚠️ 检测到停止信号，等待当前任务结束...")
            return (False, failed_urls)  # 中断任务

        # 下载图片
        if download_image(url, save_dir):
            success_count += 1
        else:
            failed_urls.append(url)

    # 即使有部分失败，也视为任务完成，避免永远卡在同一批数据
    completion_rate = success_count / total if total > 0 else 1
    task_completed = completion_rate > 0  # 只要有一个成功就视为完成处理

    with print_lock:
        print(f"[任务总结] UID:{uid} 完成{success_count}/{total} 图片")

    return (task_completed, failed_urls)


def fetch_data():
    """从数据库读取数据"""
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT uid, title, content FROM web_crawl_data WHERE is_deleted=0")
        rows = cursor.fetchall()
        cursor.close()
        return rows
    except Exception as e:
        with print_lock:
            print(f"[数据库读取错误] {e}")
        return []
    finally:
        if conn:
            conn.close()


def mark_as_deleted(uid):
    """标记数据库中的记录为已处理，增加详细日志和错误处理"""
    conn = None
    try:
        conn = pymysql.connect(** DB_CONFIG)
        cursor = conn.cursor()
        # 先查询当前状态，用于调试
        cursor.execute("SELECT is_deleted FROM web_crawl_data WHERE uid=%s", (uid,))
        current_status = cursor.fetchone()

        if not current_status:
            with print_lock:
                print(f"[更新失败] UID: {uid} 不存在")
            return False

        # 如果已经是1，不需要重复更新
        if current_status[0] == 1:
            with print_lock:
                print(f"[已更新状态] UID: {uid} (状态已为1)")
            return True

        # 执行更新
        affected_rows = cursor.execute(
            "UPDATE web_crawl_data SET is_deleted=1 WHERE uid=%s",
            (uid,)
        )
        conn.commit()

        with print_lock:
            if affected_rows > 0:
                print(f"[已更新状态] UID: {uid} (之前状态: {current_status[0]})")
            else:
                print(f"[更新失败] UID: {uid} 未找到或已更新")

        return affected_rows > 0
    except Exception as e:
        if conn:
            conn.rollback()
        with print_lock:
            print(f"[更新状态错误] UID: {uid} => {e}")
        return False
    finally:
        if conn:
            conn.close()


def process_data():
    """主流程"""
    rows = fetch_data()
    print(f"共读取 {len(rows)} 条数据\n")

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {}
        for row in rows:
            uid = row["uid"]
            title = row["title"] or "untitled"
            content = row["content"]
            if not content:
                print(f"{uid} 没有图片，跳过并标记为已处理")
                mark_as_deleted(uid)  # 没有图片也标记为已处理
                continue

            urls = [u.strip() for u in content.split(",") if u.strip()]
            futures[executor.submit(worker_task, uid, title, urls)] = uid

        completed_count = 0
        for f in as_completed(futures):
            uid = futures[f]
            completed_count += 1

            if stop_flag.is_set():
                break

            try:
                result, failed_urls = f.result()
                # 无论是否完全成功，都尝试更新状态
                update_success = mark_as_deleted(uid)

                if not update_success:
                    with print_lock:
                        print(f"[警告] UID: {uid} 状态更新失败")
                elif not result:
                    with print_lock:
                        print(f"[部分失败] UID: {uid} 已标记为处理，但有 {len(failed_urls)} 张图片下载失败")
            except Exception as e:
                with print_lock:
                    print(f"[任务异常] UID: {uid} => {e}")
                    # 即使任务抛出异常，也尝试标记为已处理，避免死循环
                    mark_as_deleted(uid)

            with print_lock:
                print(f"进度：{completed_count}/{len(futures)} 条记录已完成")

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
