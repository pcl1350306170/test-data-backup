import tkinter as tk
from tkinter import ttk, messagebox
import re
import pyperclip
import platform

def extract_books():
    raw_text = input_text.get("1.0", tk.END).strip()

    if not raw_text:
        messagebox.showwarning("提示", "请输入包含书名的字符串！")
        return

    books = []

    # 核心正则逻辑优化：
    # 1. ["\']?          -> 匹配开头可选的引号（不捕获）
    # 2. (.*?)           -> 【捕获组1】非贪婪匹配书名内容
    # 3. 作者            -> 匹配关键字 "作者"
    # 4. .*?             -> 忽略作者名及中间内容
    # 5. (?:\.txt)?      -> 匹配可选的后缀（如 .txt），但不捕获到书名里
    # 6. ["\']?          -> 匹配结尾可选的引号
    # 7. \s*             -> 忽略末尾空格

    # 这个正则会直接提取出干净的书名，不包含引号和后缀
    pattern = r'["\']?\s*(.*?)\s*作者：.*?(?:\.txt|\.epub|\.mobi|\.pdf)?\s*["\']?'

    matches = re.findall(pattern, raw_text, re.IGNORECASE)

    for match in matches:
        # 二次清洗：防止文件名内部有多余空格或意外字符
        clean_name = match.strip()

        # 额外防御：如果书名里还残留 .txt (比如格式非常奇怪的情况)，再次移除
        if clean_name.lower().endswith('.txt'):
            clean_name = clean_name[:-4]

        if clean_name:
            books.append(clean_name)

    if not books:
        # 尝试更宽松的匹配，以防用户输入的格式完全不包含"作者："
        # 备用方案：匹配 "文件名" 格式，手动切除作者部分
        fallback_pattern = r'["\']([^"\']+?)\.txt["\']'
        fallback_matches = re.findall(fallback_pattern, raw_text)
        for m in fallback_matches:
            if "作者" in m:
                name = m.split("作者")[0].strip()
                if name:
                    books.append(name)

        if not books:
            messagebox.showerror("错误", "未找到符合格式的书名。\n请确保格式包含：...作者：...")
            return

    # 用 "·" 连接
    result_string = "·".join(books)

    # 显示结果
    output_text.delete("1.0", tk.END)
    output_text.insert(tk.END, result_string)

    # 复制到剪贴板
    try:
        pyperclip.copy(result_string)
        status_label.config(text="✅ 已提取纯净书名并复制到剪贴板！", fg="green")
    except Exception as e:
        # 针对 Linux 无 xclip 的常见错误提示
        msg = f"提取成功：{result_string}\n\n(自动复制失败，请手动复制上方结果)\n错误信息: {str(e)}"
        if "xclip" in str(e) or "xsel" in str(e):
            msg += "\n\n提示: Linux用户请安装 'xclip' 或 'xsel' (sudo apt install xclip)"

        status_label.config(text="⚠️ 提取成功，但复制失败", fg="orange")
        messagebox.showinfo("提取成功但复制失败", msg)

def clear_text():
    input_text.delete("1.0", tk.END)
    output_text.delete("1.0", tk.END)
    status_label.config(text="", fg="black")

# --- GUI 设置 ---
root = tk.Tk()
root.title("纯净书名提取器 (无引号/无后缀)")
root.geometry("600x520")

# 输入区域
lbl_info = tk.Label(root, text="粘贴原始字符串 (支持混合格式):", font=("Microsoft YaHei", 11))
lbl_info.pack(pady=(15, 5))

input_text = tk.Text(root, height=8, font=("Consolas", 10), wrap=tk.WORD)
input_text.pack(padx=15, pady=5, fill=tk.BOTH, expand=True)
# 默认填入测试数据
default_data = '"汉祚高门作者：衣冠正伦.txt" "拜见教主大人作者：封七月.txt" \'穿梭时空的侠客作者：牵牛喂大将军.txt\''
input_text.insert(tk.END, default_data)

# 按钮区域
btn_frame = tk.Frame(root)
btn_frame.pack(pady=10)

btn_extract = tk.Button(btn_frame, text="🚀 提取并复制", command=extract_books,
                        bg="#2E7D32", fg="white", font=("Microsoft YaHei", 12, "bold"),
                        padx=25, pady=8, relief=tk.FLAT, cursor="hand2")
btn_extract.pack(side=tk.LEFT, padx=15)

btn_clear = tk.Button(btn_frame, text="🗑️ 清空", command=clear_text,
                      bg="#C62828", fg="white", font=("Microsoft YaHei", 12),
                      padx=25, pady=8, relief=tk.FLAT, cursor="hand2")
btn_clear.pack(side=tk.LEFT, padx=15)

# 状态栏
status_label = tk.Label(root, text="", font=("Microsoft YaHei", 10, "italic"))
status_label.pack(pady=5)

# 输出区域
lbl_out = tk.Label(root, text="最终结果 (已自动复制，无引号/无.txt):", font=("Microsoft YaHei", 11))
lbl_out.pack(pady=(5, 0))

output_text = tk.Text(root, height=4, font=("Consolas", 12, "bold"), wrap=tk.WORD, bg="#E8F5E9", fg="#1B5E20")
output_text.pack(padx=15, pady=10, fill=tk.X)

# 启动
root.mainloop()
