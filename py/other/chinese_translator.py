import os
import json
import hashlib
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests
from pathlib import Path

# 配置与常量
SCRIPT_NAME = "chinese_translator"
CONFIG_DIR = Path("json")
CONFIG_PATH = CONFIG_DIR / f"{SCRIPT_NAME}_config.json"
SUPPORTED_FORMATS = {
    "驼峰格式": "camelCase",
    "直译格式": "literal",
    "全部大写": "uppercase",
    "全部小写": "lowercase",
    "下划线间隔": "snake_case"
}

# 确保配置目录存在
CONFIG_DIR.mkdir(exist_ok=True)

class ChineseTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("中文翻译格式转换工具")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        # 加载配置
        self.config = self.load_config()

        # 创建界面
        self.create_widgets()

        # 绑定快捷键（修复部分）
        self.bind_shortcuts()

    def load_config(self):
        """加载百度API配置"""
        default_config = {
            "baidu_appid": "",
            "baidu_secret": ""
        }

        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return {**default_config,** config}
            except Exception as e:
                messagebox.showerror("配置加载失败", f"使用默认配置: {str(e)}")

        return default_config

    def save_config(self):
        """保存百度API配置"""
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            messagebox.showerror("保存失败", f"配置保存出错: {str(e)}")

    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 配置区域
        config_frame = ttk.LabelFrame(main_frame, text="百度翻译API配置", padding="10")
        config_frame.pack(fill=tk.X, pady=5)

        # 百度APP ID
        ttk.Label(config_frame, text="百度APP ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.appid_var = tk.StringVar(value=self.config["baidu_appid"])
        ttk.Entry(config_frame, textvariable=self.appid_var, width=50).grid(row=0, column=1, sticky=tk.EW, pady=5)

        # 百度密钥
        ttk.Label(config_frame, text="百度密钥:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.secret_var = tk.StringVar(value=self.config["baidu_secret"])
        ttk.Entry(config_frame, textvariable=self.secret_var, width=50).grid(row=1, column=1, sticky=tk.EW, pady=5)

        # 保存配置按钮
        ttk.Button(config_frame, text="保存配置", command=self.save_current_config).grid(row=1, column=2, padx=10, pady=5)
        config_frame.columnconfigure(1, weight=1)

        # 2. 输入区域
        input_frame = ttk.LabelFrame(main_frame, text="中文输入", padding="10")
        input_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.input_text = tk.Text(input_frame, height=6, wrap=tk.WORD)
        self.input_text.pack(fill=tk.BOTH, expand=True)
        ttk.Button(input_frame, text="翻译", command=self.translate_text).pack(pady=10)

        # 3. 结果区域
        result_frame = ttk.LabelFrame(main_frame, text="翻译结果", padding="10")
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # 创建结果表格
        columns = ("format", "result", "action")
        self.result_tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=5)

        # 设置列标题
        self.result_tree.heading("format", text="格式类型")
        self.result_tree.heading("result", text="结果")
        self.result_tree.heading("action", text="操作")

        # 设置列宽
        self.result_tree.column("format", width=150, anchor=tk.CENTER)
        self.result_tree.column("result", width=400, anchor=tk.W)
        self.result_tree.column("action", width=100, anchor=tk.CENTER)

        self.result_tree.pack(fill=tk.BOTH, expand=True)

    def bind_shortcuts(self):
        """绑定快捷键（修复关键处）"""
        # 修复：将 Control+Return 改为 Control-Return
        self.root.bind("<Control-Return>", lambda e: self.translate_text())  # Ctrl+Enter翻译
        self.root.bind("<Control-s>", lambda e: self.save_current_config())  # Ctrl+S保存配置

    def save_current_config(self):
        """保存当前配置到文件"""
        self.config["baidu_appid"] = self.appid_var.get().strip()
        self.config["baidu_secret"] = self.secret_var.get().strip()
        self.save_config()

    def baidu_translate(self, text):
        """调用百度翻译API"""
        appid = self.config["baidu_appid"]
        secret = self.config["baidu_secret"]

        if not appid or not secret:
            raise ValueError("请先配置并保存百度API的APP ID和密钥")

        url = "http://api.fanyi.baidu.com/api/trans/vip/translate"
        salt = str(int(time.time() * 1000))
        sign_str = f"{appid}{text}{salt}{secret}"
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        params = {
            "q": text,
            "from": "zh",
            "to": "en",
            "appid": appid,
            "salt": salt,
            "sign": sign
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            result = response.json()

            if "error_code" in result:
                error_msg = f"API错误: {result.get('error_msg', '未知错误')} (代码: {result['error_code']})"
                raise Exception(error_msg)

            if "trans_result" in result and result["trans_result"]:
                return result["trans_result"][0]["dst"]
            else:
                raise Exception("翻译结果为空")

        except Exception as e:
            raise Exception(f"翻译失败: {str(e)}")

    def format_text(self, original):
        """将翻译结果转换为多种格式"""
        words = original.strip().lower().replace(',', '').replace('.', '').split()
        if not words:
            return {}

        formatted = {}

        # 1. 直译格式（首字母大写）
        formatted["literal"] = ' '.join(word.capitalize() for word in words)

        # 2. 全部大写
        formatted["uppercase"] = ' '.join(words).upper()

        # 3. 全部小写
        formatted["lowercase"] = ' '.join(words).lower()

        # 4. 下划线间隔
        formatted["snake_case"] = '_'.join(words)

        # 5. 驼峰格式
        if len(words) == 1:
            formatted["camelCase"] = words[0].lower()
        else:
            camel_case = words[0].lower() + ''.join(word.capitalize() for word in words[1:])
            formatted["camelCase"] = camel_case

        return formatted

    def copy_to_clipboard(self, text):
        """复制文本到剪贴板"""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def translate_text(self):
        """翻译并显示结果"""
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)

        chinese_text = self.input_text.get("1.0", tk.END).strip()
        if not chinese_text:
            messagebox.showwarning("提示", "请输入要翻译的中文")
            return

        try:
            english_text = self.baidu_translate(chinese_text)
            formatted_results = self.format_text(english_text)

            for format_name, format_key in SUPPORTED_FORMATS.items():
                if format_key in formatted_results:
                    result_text = formatted_results[format_key]
                    item = self.result_tree.insert("", tk.END, values=(format_name, result_text, "复制"))

            def copy_action(event):
                item = self.result_tree.selection()[0]
                result_text = self.result_tree.item(item, "values")[1]
                self.copy_to_clipboard(result_text)
                self.result_tree.set(item, "action", "已复制")
                self.root.after(1000, lambda: self.result_tree.set(item, "action", "复制"))

            self.result_tree.bind("<ButtonRelease-1>", lambda e:
            copy_action(e) if self.result_tree.identify_column(e.x) == "#3" else None)
            self.result_tree.bind("<Double-1>", lambda e:
            copy_action(e) if self.result_tree.identify_column(e.x) != "#3" else None)

        except Exception as e:
            messagebox.showerror("翻译错误", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = ChineseTranslatorApp(root)
    root.mainloop()
