import os
import time
import threading
import requests
import mysql.connector
from flask import Flask, request, jsonify
from urllib.parse import urlparse
from PIL import Image
from io import BytesIO
import uuid

# Flask 应用
app = Flask(__name__)

# 全局任务存储
tasks = {}

# 数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'test'
}

# 下载函数
def download_images(task_id, data_type, save_dir, batch_size):
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)

    # 查询待处理的数据
    cursor.execute("SELECT uid, title, content FROM web_crawl_data WHERE is_deleted = 0")
    rows = cursor.fetchall()

    total_count = len(rows)
    tasks[task_id]['progress']['totalCount'] = total_count

    processed = 0
    success = 0
    failed = 0

    for row in rows:
        if tasks[task_id]['status'] == 'STOPPED':
            break

        title = row['title'] or "default"
        content = row['content'] or ""
        img_urls = [u.strip() for u in content.split(",") if u.strip()]

        folder = os.path.join(save_dir, title)
        os.makedirs(folder, exist_ok=True)

        for url in img_urls:
            if tasks[task_id]['status'] == 'STOPPED':
                break

            file_name = os.path.basename(urlparse(url).path)  # 保留原始文件名
            save_path = os.path.join(folder, file_name)

            # 下载 + 重试机制
            retry = 3
            success_flag = False
            for attempt in range(retry):
                try:
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200:
                        # 检查分辨率
                        img = Image.open(BytesIO(resp.content))
                        w, h = img.size
                        if w >= 100 and h >= 100:
                            with open(save_path, "wb") as f:
                                f.write(resp.content)
                            success += 1
                            success_flag = True
                        else:
                            failed += 1
                        break
                except Exception as e:
                    time.sleep(2)  # 等待后重试
            if not success_flag:
                failed += 1

        # 更新数据库状态
        cursor.execute("UPDATE web_crawl_data SET is_deleted = 1 WHERE uid = %s", (row['uid'],))
        conn.commit()

        processed += 1
        tasks[task_id]['progress'] = {
            "totalCount": total_count,
            "processedCount": processed,
            "successCount": success,
            "failedCount": failed,
            "progressPercentage": int((processed / total_count) * 100),
            "status": tasks[task_id]['status']
        }

    cursor.close()
    conn.close()

    if tasks[task_id]['status'] != 'STOPPED':
        tasks[task_id]['status'] = "COMPLETED"


# 启动任务接口
@app.route("/crawl-api/v1/generalData/process/start", methods=["POST"])
def start_task():
    data_type = request.args.get("dataType")
    save_dir = request.args.get("saveDir", "D:\\download\\MTMT")
    batch_size = int(request.args.get("batchSize", 100))

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "status": "PROCESSING",
        "progress": {
            "totalCount": 0,
            "processedCount": 0,
            "successCount": 0,
            "failedCount": 0,
            "progressPercentage": 0
        }
    }

    thread = threading.Thread(target=download_images, args=(task_id, data_type, save_dir, batch_size))
    thread.start()

    return jsonify({"resultCode": 200, "data": {"taskId": task_id}})


# 查询进度接口
@app.route("/crawl-api/v1/generalData/process/progress", methods=["GET"])
def get_progress():
    task_id = request.args.get("taskId")
    if task_id not in tasks:
        return jsonify({"resultCode": 404, "message": "任务不存在"})
    return jsonify({"resultCode": 200, "data": {**tasks[task_id]['progress'], "status": tasks[task_id]['status']}})


# 停止任务接口
@app.route("/crawl-api/v1/generalData/process/stop", methods=["POST"])
def stop_task():
    task_id = request.args.get("taskId")
    if task_id in tasks:
        tasks[task_id]['status'] = "STOPPED"
        return jsonify({"resultCode": 200, "message": "任务已停止"})
    return jsonify({"resultCode": 404, "message": "任务不存在"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
