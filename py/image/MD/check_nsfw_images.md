非常好 👍
你要的是一个 **离线版（本地检测）** 的脚本，用来从图片目录中筛选出包含**色情/暴露内容**的图片，剪切到另一个目录中去。
下面我会完整告诉你：

---

## ✅ 一、功能说明

这个脚本会：

1. 遍历 `G:\图片\竖屏壁纸绝美` 目录（可包含子目录）；
2. 使用 **本地 AI 模型** 检测每张图片是否含色情或暴露内容；
3. 如果检测为违规，则剪切到
   `G:\图片\竖屏壁纸绝美2`
   并保留原目录结构；
4. 不需要联网，完全离线运行。

---

## ✅ 二、安装依赖

打开命令行（CMD 或 PowerShell），执行以下命令：

```bash
pip install pillow
pip install nsfw-detector
```

> 🔸 `nsfw-detector` 是一个轻量级的 TensorFlow 模型封装包，可以直接使用离线的 NSFW 模型。

安装完后第一次运行脚本时会自动下载一个本地的模型（几十 MB 左右），只需一次即可。

---

## ✅ 三、完整 Python 脚本

将以下内容保存为：

> `check_nsfw_images.py`

```python
import os
import shutil
from nsfw_detector import predict
from PIL import Image

# ================== 配置区 ==================
SOURCE_DIR = r"G:\图片\竖屏壁纸绝美"     # 原始图片目录
TARGET_DIR = r"G:\图片\竖屏壁纸绝美2"     # 检测到违规图片的存放目录
PROCESS_SUBDIRS = True                    # 是否处理子目录
NSFW_THRESHOLD = 0.6                      # 色情概率阈值，越高越严格（0~1）
# ===========================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def get_all_images(root_dir):
    """递归获取所有图片路径"""
    image_files = []
    for root, _, files in os.walk(root_dir):
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                image_files.append(os.path.join(root, f))
        if not PROCESS_SUBDIRS:
            break
    return image_files

def detect_nsfw_images(model, image_paths):
    """检测并移动违规图片"""
    total = len(image_paths)
    moved = 0

    print(f"🚀 开始检测，共 {total} 张图片...\n")

    for idx, img_path in enumerate(image_paths, 1):
        try:
            # 检测图片
            preds = model.predict(img_path)
            probs = list(preds.values())[0]
            nsfw_score = probs.get("porn", 0) + probs.get("sexy", 0)

            if nsfw_score >= NSFW_THRESHOLD:
                rel_path = os.path.relpath(os.path.dirname(img_path), SOURCE_DIR)
                dest_dir = os.path.join(TARGET_DIR, rel_path)
                ensure_dir(dest_dir)

                dest_path = os.path.join(dest_dir, os.path.basename(img_path))
                shutil.move(img_path, dest_path)
                moved += 1
                print(f"🚫 [{idx}/{total}] 违规图片已剪切：{dest_path}")
            else:
                print(f"✅ [{idx}/{total}] 正常：{img_path}")

        except Exception as e:
            print(f"⚠️ 检测失败：{img_path} -> {e}")

    print(f"\n🎯 检测完成：共检测 {total} 张图片，发现并剪切 {moved} 张违规图片。")

def main():
    print("🧠 正在加载离线 NSFW 模型，请稍等...")
    model = predict.load_model()  # 会自动下载一次模型文件
    print("✅ 模型加载完成\n")

    image_paths = get_all_images(SOURCE_DIR)
    detect_nsfw_images(model, image_paths)

if __name__ == "__main__":
    main()
```

---

## ✅ 四、运行方法

1. 把脚本放到任意位置，比如 `E:\scripts\check_nsfw_images.py`
2. 运行命令：

   ```bash
   python E:\scripts\check_nsfw_images.py
   ```
3. 脚本会自动加载模型并开始检测。

---

## ✅ 五、模型原理

`nsfw-detector` 使用的是 Yahoo 开源的 **NSFW Model**（基于 MobileNet 结构），能识别以下五类内容：

| 标签         | 含义    |
| ---------- | ----- |
| `drawings` | 动漫、插画 |
| `hentai`   | 色情动漫  |
| `neutral`  | 正常图片  |
| `porn`     | 色情内容  |
| `sexy`     | 轻微暴露  |

我们用 `porn + sexy` 的总概率来判断是否违规。

---

## ✅ 六、进阶优化（可选）

你可以在顶部修改参数：

```python
NSFW_THRESHOLD = 0.7  # 调高这个值可以减少误判
PROCESS_SUBDIRS = False  # 只检测一级目录
```

---

是否希望我帮你加上一个 **进度条 + 日志文件记录（保存检测结果）** 的版本？
可以方便你人工复查每次被剪切的图片路径。
