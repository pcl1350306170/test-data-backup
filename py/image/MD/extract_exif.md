非常明确 ✅，你需要获取目录 `G:\图片\小学语文课本插图` 中所有图片的 **EXIF 数据**，并将这些数据保存到一个 **JSON 文件** 中。每条记录包含 **图片文件的路径** 和其对应的 **EXIF 数据**。

EXIF 数据是由相机或智能手机在拍摄照片时自动附加到图片中的元数据，包括时间、相机型号、光圈、曝光等。

### 🧠 步骤总结

1. 遍历 `G:\图片\小学语文课本插图` 中的所有图片。
2. 提取每张图片的 **EXIF 数据**（如果有）。
3. 将 **文件路径** 和对应的 **EXIF 数据** 保存到 `C:\www\test\py\json` 目录下的 JSON 文件。

### 📁 输出

* JSON 文件保存为 `exif_data.json`，每条记录包括：

    * 图片的文件路径。
    * 图片的 EXIF 数据。

### 🐍 完整代码

```python
import os
import json
from PIL import Image
from PIL.ExifTags import TAGS

# ================== 配置区 ==================
source_dir = r"G:\图片\小学语文课本插图"  # 图片所在目录
output_dir = r"/image/json"  # JSON 输出目录
output_file = os.path.join(output_dir, "exif_data.json")  # 输出文件路径
process_subdirs = True  # 是否递归处理子目录


# ===========================================

def ensure_dir_exists(path):
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)


def get_exif_data(image_path):
    """提取图片的 EXIF 数据"""
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()
        if exif_data is not None:
            # 将 EXIF 数据中的数字标签转换为描述性标签
            exif_dict = {}
            for tag, value in exif_data.items():
                tag_name = TAGS.get(tag, tag)
                exif_dict[tag_name] = value
            return exif_dict
        else:
            return None
    except Exception as e:
        print(f"⚠️ 无法读取 EXIF 数据：{image_path} -> {e}")
        return None


def get_all_images(root_dir):
    """递归获取所有图片路径"""
    image_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                image_files.append(os.path.join(root, file))
        if not process_subdirs:
            break
    return image_files


def process_images():
    """处理图片，提取 EXIF 数据并保存到 JSON"""
    ensure_dir_exists(output_dir)

    image_paths = get_all_images(source_dir)
    exif_data_list = []

    for img_path in image_paths:
        exif_data = get_exif_data(img_path)
        if exif_data is not None:
            exif_data_list.append({
                "file_path": img_path,
                "exif_data": exif_data
            })

    # 将所有 EXIF 数据写入 JSON 文件
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(exif_data_list, f, ensure_ascii=False, indent=4)

    print(f"✅ EXIF 数据已保存到 {output_file}")


if __name__ == "__main__":
    process_images()
```

---

### ✅ 脚本说明

1. **遍历图片：**
   `get_all_images()` 函数递归扫描指定目录下所有图片文件，支持 `.jpg`、`.jpeg`、`.png`、`.bmp` 和 `.webp` 格式。

2. **提取 EXIF 数据：**
   `get_exif_data()` 函数使用 `PIL.Image` 获取图片的 EXIF 数据，并将每个标签的 **数字 ID** 转换为 **描述性标签**（比如 `Make`、`Model`、`DateTime`）。

3. **保存为 JSON：**
   所有图片的 EXIF 数据会被保存在 `C:\www\test\py\json\exif_data.json` 文件中，每个图片记录包含：

    * `file_path`：图片的路径。
    * `exif_data`：EXIF 数据（字典格式）。

4. **JSON 格式：**

    * 文件会采用 **UTF-8 编码** 写入，保证字符的兼容性。
    * 使用 `json.dump()` 将数据保存为格式化的 JSON 文件，便于查看和后续使用。

### ✅ 运行方法

1. 确保安装了 **Pillow** 库：

   ```bash
   pip install pillow
   ```

2. 将脚本保存为文件（比如 `extract_exif.py`），然后在命令行运行：

   ```bash
   python extract_exif.py
   ```

3. 执行后，所有图片的 EXIF 数据将被保存到 `C:\www\test\py\json\exif_data.json` 文件中。

---

### ✅ 注意事项

1. **EXIF 数据缺失：**
   有些图片可能没有 EXIF 数据，脚本会跳过这些图片，记录到 JSON 文件中时不会包含这些图片的 EXIF 信息。

2. **处理子目录：**
   你可以通过设置 `process_subdirs = True` 来递归处理子目录，或者设置为 `False` 只处理当前目录下的图片。

3. **输出 JSON 文件：**
   输出的 JSON 文件将包含每个图片的路径和其 EXIF 数据，格式类似如下：

   ```json
   [
       {
           "file_path": "G:/图片/小学语文课本插图/图片1.jpg",
           "exif_data": {
               "Make": "Canon",
               "Model": "Canon EOS 5D Mark III",
               "DateTime": "2022:01:01 12:00:00",
               "ExposureTime": "1/200",
               "FNumber": "2.8"
               // 更多 EXIF 数据...
           }
       },
       {
           "file_path": "G:/图片/小学语文课本插图/图片2.jpg",
           "exif_data": {
               // 如果没有 EXIF 数据，这个记录会被跳过
           }
       }
   ]
   ```

---

如果你有任何问题或需要进一步的帮助，请随时告诉我！
这个错误提示说明你的 EXIF 数据中包含了 `IFDRational` 类型的对象，而这个类型是无法直接序列化为 JSON 的。

### 问题分析：

* **`IFDRational`** 类型是一个来自 `PIL` 库的特殊对象，它表示的是 EXIF 中的分数或比率（例如，图像分辨率等字段）。JSON 不知道如何处理这种类型，因此会抛出 `TypeError`。
* 你需要手动将这种类型转换为可序列化的格式（例如，将其转换为 `float` 或 `string`）。

### 解决方案：

在 `convert_to_serializable` 函数中处理 `IFDRational` 类型。我们可以将它转换为浮动数字 `float`，这是大多数情况中 `IFDRational` 类型的实际意义。

### 修改后的 `convert_to_serializable` 函数：

```python
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime
import base64
import fractions  # 用来处理 IFDRational 类型

# ================== 配置区 ==================
source_dir = r"G:\图片\小学语文课本插图"  # 图片所在目录
output_dir = r"/image/json"  # JSON 输出目录
output_file = os.path.join(output_dir, "exif_data.json")  # 输出文件路径
process_subdirs = True  # 是否递归处理子目录


# ===========================================

def ensure_dir_exists(path):
    """确保目录存在，不存在则创建"""
    os.makedirs(path, exist_ok=True)


def convert_to_serializable(value):
    """确保值是可被 JSON 序列化的，并跳过无法解析的字段"""
    try:
        if isinstance(value, bytes):
            # 如果是 bytes 类型，转换为 base64 字符串
            return base64.b64encode(value).decode('utf-8')
        elif isinstance(value, datetime):
            # 如果是 datetime 类型，转换为字符串
            return value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, fractions.Fraction):
            # 如果是 IFDRational 类型（EXIF 中的分数），转换为 float
            return float(value)
        elif isinstance(value, dict):
            # 如果是 dict 类型，递归处理
            return {k: convert_to_serializable(v) for k, v in value.items()}
        elif isinstance(value, list):
            # 如果是 list 类型，递归处理
            return [convert_to_serializable(v) for v in value]
        elif isinstance(value, tuple):
            # 如果是 tuple，转换为 list
            return [convert_to_serializable(v) for v in value]
        elif isinstance(value, set):
            # 如果是 set，转换为 list
            return [convert_to_serializable(v) for v in value]
        elif value is None:
            # 如果是 None，直接返回
            return None
        else:
            # 其他类型，返回原值
            return value
    except Exception as e:
        # 遇到无法解析的字段时，跳过并打印警告
        print(f"⚠️ 跳过无法解析的字段: {e}")
        return None  # 返回 None 跳过这个字段


def get_exif_data(image_path):
    """提取图片的 EXIF 数据"""
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()
        if exif_data is not None:
            # 将 EXIF 数据中的数字标签转换为描述性标签
            exif_dict = {}
            for tag, value in exif_data.items():
                tag_name = TAGS.get(tag, tag)
                exif_dict[tag_name] = convert_to_serializable(value)
            return exif_dict
        else:
            return None
    except Exception as e:
        print(f"⚠️ 无法读取 EXIF 数据：{image_path} -> {e}")
        return None


def get_all_images(root_dir):
    """递归获取所有图片路径"""
    image_files = []
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                image_files.append(os.path.join(root, file))
        if not process_subdirs:
            break
    return image_files


def process_images():
    """处理图片，提取 EXIF 数据并保存到 JSON"""
    ensure_dir_exists(output_dir)

    image_paths = get_all_images(source_dir)
    exif_data_list = []

    for img_path in image_paths:
        exif_data = get_exif_data(img_path)
        if exif_data is not None:
            exif_data_list.append({
                "file_path": img_path,
                "exif_data": exif_data
            })

    # 将所有 EXIF 数据写入 JSON 文件
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(exif_data_list, f, ensure_ascii=False, indent=4)

    print(f"✅ EXIF 数据已保存到 {output_file}")


if __name__ == "__main__":
    process_images()
```

### 说明：

1. **处理 `IFDRational` 类型：**

   * 我们使用 `fractions.Fraction` 来检测 `IFDRational` 类型，然后将其转换为 `float` 类型。这样它就可以正确地序列化为 JSON 格式。

   * `fractions.Fraction` 是用来表示分数的类。EXIF 中的一些值（如分辨率）会以 `IFDRational` 类型存储，这个类型实际上是一个分数表示，`Fraction` 可以轻松地将其转换为浮动数字（即 `float`）。

2. **异常处理：**

   * 如果在转换过程中发生异常（如无法解析某个字段），它会跳过该字段并打印警告。

3. **其他字段处理：**

   * 对于 `datetime` 类型、`bytes` 类型以及其他可序列化的数据，我们已在 `convert_to_serializable` 函数中做了处理。

### 运行步骤：

1. **安装依赖：**
   如果没有安装 `Pillow` 和 `fractions`，请先安装：

   ```bash
   pip install pillow
   ```

2. **运行脚本：**
   运行该脚本：

   ```bash
   python extract_exif.py
   ```

3. **查看输出：**
   EXIF 数据将保存到 `C:\www\test\py\json\exif_data.json` 中。

### 结果：

通过上述处理，`IFDRational` 类型的字段应该能够被成功转换为 `float` 类型，并且不会再出现 `TypeError` 错误。

如果问题依然存在，或者有新的特殊字段需要处理，请随时告知！
