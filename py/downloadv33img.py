import os
import re
import json
import pymysql
import requests
import threading
from queue import Queue
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PIL import Image
from io import BytesIO
import time
import signal

# -------------------
# 配置项
# -------------------
# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "test",
    "charset": "utf8mb4"
}

# 保存目录
SAVE_DIR = "A:\IMAGE\V33\已处理"

# 多线程配置，默认5线程
THREAD_COUNT = 5

# 下载重试次数
RETRY_COUNT = 3

# 小图映射JSON路径
SMALL_IMG_JSON = "D:\\www\\test\\py\\json\\imgSmallMapping.json"

# 安全停止标志
STOP_FLAG = False
STOP_LOCK = threading.Lock()

# -------------------
# 初始化
# -------------------
os.makedirs(SAVE_DIR, exist_ok=True)

# 确保小图JSON目录存在
os.makedirs(os.path.dirname(SMALL_IMG_JSON), exist_ok=True)
# 初始化小图JSON文件
if not os.path.exists(SMALL_IMG_JSON):
    with open(SMALL_IMG_JSON, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False)

# -------------------
# 数据库连接
# -------------------
def get_db_connection():
    """获取数据库连接"""
    return pymysql.connect(** DB_CONFIG)

# -------------------
# 获取待处理数据
# -------------------
def fetch_pending_data(conn):
    """从数据库获取待处理的数据"""
    sql = """
        SELECT id, data_key, data_content, data_type
        FROM general_data
        WHERE data_type LIKE 'V33-IMG-s%'
          AND is_deleted=0
    """
    # 执行 SQL 查询
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql)
        return cursor.fetchall()

# -------------------
# 检查图片是否在小图列表中
# -------------------
def is_in_small_mapping(img_url):
    """检查图片是否在小图映射列表中"""
    try:
        with open(SMALL_IMG_JSON, 'r', encoding='utf-8') as f:
            small_images = json.load(f)
            return img_url in small_images
    except Exception as e:
        print(f"❌ 读取小图JSON出错: {e}")
        return False

# -------------------
# 添加图片到小图列表
# -------------------
def add_to_small_mapping(img_url):
    """将小图URL添加到映射列表"""
    try:
        with open(SMALL_IMG_JSON, 'r+', encoding='utf-8') as f:
            small_images = json.load(f)
            if img_url not in small_images:
                small_images.append(img_url)
                f.seek(0)
                f.truncate()
                json.dump(small_images, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ 写入小图JSON出错: {e}")

# -------------------
# 图片裁剪逻辑（裁剪后删除原图）
# -------------------
def process_image(original_path, output_path):
    """裁剪图片并保存，完成后删除原图片"""
    try:
        with Image.open(original_path) as img:
            width, height = img.size

            # 判断图片方向自动设置底部裁剪比例
            if height > width:
                CROP_RATIO_BOTTOM = 0.12  # 竖图
            else:
                CROP_RATIO_BOTTOM = 0.09  # 横图

            crop_height = int(height * (1 - CROP_RATIO_BOTTOM))
            cropped_img = img.crop((0, 0, width, crop_height))

            # 创建输出目录
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cropped_img.save(output_path)

            print(f"─=≡Σ(((つ•̀ω•́)つ=== 裁剪完成: {os.path.basename(original_path)} (比例 {CROP_RATIO_BOTTOM})")

        # 裁剪成功后删除原图片
        if os.path.exists(original_path):
            os.remove(original_path)
            print(f"🗑️ 已删除原图片: {os.path.basename(original_path)}")

    except Exception as e:
        print(f"❌ 裁剪出错: {original_path} - {e}")

# -------------------
# 保存图片（带重试机制）
# -------------------
def save_image_with_retry(url, original_path, crop_path):
    """带重试机制的图片下载函数"""
    for attempt in range(RETRY_COUNT):
        try:
            # 检查是否需要安全停止
            with STOP_LOCK:
                if STOP_FLAG:
                    print(f"⚠️ 检测到停止信号，终止下载: {url}")
                    return False

            # 如果裁剪后的文件已经存在，直接跳过
            if os.path.exists(crop_path):
                print(f"⚠️ 裁剪后的图片已存在，跳过: {crop_path}")
                return True

            response = requests.get(url, stream=True, timeout=15)
            if response.status_code == 200:
                with open(original_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)

                # 下载完成后进行裁剪
                process_image(original_path, crop_path)
                print(f"✅ 成功下载并处理: {crop_path}")
                return True
            else:
                print(f"⚠️ 下载失败（状态码: {response.status_code}），尝试第 {attempt + 1} 次: {url}")
                time.sleep(1)  # 重试前等待1秒

        except Exception as e:
            print(f"⚠️ 下载出错，尝试第 {attempt + 1} 次: {url} - {e}")
            time.sleep(1)  # 重试前等待1秒

    print(f"❌ 达到最大重试次数，放弃下载: {url}")
    return False

# -------------------
# 从网页获取所有图片
# -------------------
def fetch_images_from_webpage(url):
    """从指定网页获取所有符合条件的图片URL"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        if resp.status_code != 200:
            print(f"⚠️ 获取页面失败: {url} -> 状态码: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # 查找页面中的所有 img 标签
        img_tags = soup.find_all("img")
        img_urls = []
        for img in img_tags:
            # 检查是否需要安全停止
            with STOP_LOCK:
                if STOP_FLAG:
                    print(f"⚠️ 检测到停止信号，终止图片获取")
                    return img_urls

            img_url = img.get("src") or img.get("data-src")  # 图片URL可能在data-src属性中
            if img_url:
                img_url = urljoin(url, img_url)  # 处理相对路径
                print(f"🔍 发现图片URL: {img_url}")

                # 检查是否已在小图列表中
                if is_in_small_mapping(img_url):
                    print(f"⚠️ 图片在小图列表中，跳过: {img_url}")
                    continue

                # 获取图片实际尺寸
                try:
                    image_resp = requests.get(img_url, stream=True, timeout=10)
                    if image_resp.status_code == 200:
                        img = Image.open(BytesIO(image_resp.content))
                        img_width, img_height = img.size
                        # 过滤小于100px x 100px的图片并添加到小图列表
                        if img_width < 100 or img_height < 100:
                            print(f"⚠️ 图片尺寸过小 ({img_width}x{img_height})，添加到小图列表: {img_url}")
                            add_to_small_mapping(img_url)
                        else:
                            img_urls.append(img_url)
                except Exception as e:
                    print(f"⚠️ 获取图片尺寸出错: {img_url} - {e}")

        return img_urls
    except Exception as e:
        print(f"⚠️ 获取图片列表出错: {url} - {e}")
        return []

# -------------------
# 生成唯一保存目录
# -------------------
def generate_save_directory(data_type, data_key):
    """生成图片保存目录，处理不合法字符"""
    subdir = os.path.join(SAVE_DIR, data_type)
    os.makedirs(subdir, exist_ok=True)

    # 替换不合法字符
    invalid_chars = r'[\\/:*?"<>|]'
    data_key = re.sub(invalid_chars, '_', data_key)

    # 直接返回最终保存目录（不区分原始和裁剪）
    save_dir = os.path.join(subdir, data_key)
    os.makedirs(save_dir, exist_ok=True)

    return save_dir

# -------------------
# 更新状态为已删除
# -------------------
def mark_as_deleted(conn, record_id):
    """将数据库记录标记为已删除"""
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE general_data SET is_deleted=1 WHERE id=%s", (record_id,))
        conn.commit()
        print(f"📝 已更新记录状态为已删除: {record_id}")
    except Exception as e:
        print(f"❌ 更新记录状态出错: {record_id} - {e}")
        conn.rollback()

# -------------------
# 工作线程函数
# -------------------
def worker(queue):
    """处理队列中的下载任务"""
    conn = get_db_connection()
    try:
        while True:
            # 检查是否需要停止
            with STOP_LOCK:
                if STOP_FLAG and queue.empty():
                    break

            try:
                # 非阻塞获取任务，超时1秒
                record = queue.get(timeout=1)
            except:
                continue

            try:
                data_type = record["data_type"]
                data_key = record["data_key"]
                data_content = record["data_content"]
                record_id = record["id"]

                print(f"\n➡️ 处理中: {data_key} (线程: {threading.current_thread().name})")
                img_urls = fetch_images_from_webpage(data_content)

                if not img_urls:
                    print("❌ 未找到有效图片，跳过")
                    mark_as_deleted(conn, record_id)
                    queue.task_done()
                    continue

                # 创建保存目录（直接使用最终目录）
                save_dir = generate_save_directory(data_type, data_key)

                # 下载图片并保存
                all_success = True
                for img_url in img_urls:
                    # 检查是否需要安全停止
                    with STOP_LOCK:
                        if STOP_FLAG:
                            all_success = False
                            break

                    img_name = os.path.basename(img_url)
                    # 原始图片临时路径（裁剪后会删除）
                    original_path = os.path.join(save_dir, f"temp_{img_name}")
                    # 裁剪后的最终路径
                    crop_path = os.path.join(save_dir, img_name)

                    # 下载图片（带重试）
                    if not save_image_with_retry(img_url, original_path, crop_path):
                        all_success = False

                # 无论是否全部成功，都标记为已处理
                mark_as_deleted(conn, record_id)

            except Exception as e:
                print(f"❌ 处理记录出错: {record['id']} - {e}")
            finally:
                queue.task_done()

    finally:
        conn.close()
        print(f"🔚 线程 {threading.current_thread().name} 已退出")

# -------------------
# 安全停止处理
# -------------------
def handle_stop(signal, frame):
    """处理停止信号"""
    global STOP_FLAG
    with STOP_LOCK:
        if not STOP_FLAG:
            STOP_FLAG = True
            print("\n⚠️ 收到停止信号，将在完成当前任务后停止...")

# -------------------
# 主函数
# -------------------
def main():
    # 注册信号处理函数，捕获Ctrl+C等停止信号
    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    conn = get_db_connection()
    try:
        records = fetch_pending_data(conn)
        print(f"发现 {len(records)} 条待处理记录。")

        # 创建任务队列
        task_queue = Queue()
        for record in records:
            task_queue.put(record)

        # 启动工作线程
        print(f"启动 {THREAD_COUNT} 个工作线程...")
        for i in range(THREAD_COUNT):
            t = threading.Thread(target=worker, args=(task_queue,), name=f"Worker-{i+1}")
            t.daemon = True
            t.start()

        # 等待所有任务完成
        task_queue.join()

    finally:
        conn.close()
        print("\n所有任务已完成 ✅")

# -------------------
# 程序入口
# -------------------
if __name__ == "__main__":
    main()