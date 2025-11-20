# chinese_translator.py

import os
import json
import logging
import re
import threading
from pathlib import Path
from tkinter import *
from tkinter import messagebox, scrolledtext
import requests
import pyttsx3

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "chinese_translator"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"{SCRIPT_NAME}_config.json"
CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR = CONFIG_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PROCESS_LOG_FILE = LOGS_DIR / f"log_{SCRIPT_NAME}.log"

# 设置日志
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# ================== 工具函数 ==================

def load_config():
    """加载百度翻译API配置"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logging.info("成功加载 CONFIG.json")
        return config.get("baidu_appid"), config.get("baidu_secret")
    except Exception as e:
        logging.error(f"加载配置失败: {e}")
        messagebox.showerror("配置错误", f"无法加载配置文件:\n{CONFIG_PATH}\n错误: {e}")
        raise

def baidu_translate(query, app_id, secret_key):
    """调用百度翻译API"""
    import hashlib
    import random
    import time

    url = "https://fanyi-api.baidu.com/api/trans/vip/translate"
    salt = random.randint(32768, 65536)
    sign_str = app_id + query + str(salt) + secret_key
    sign = hashlib.md5(sign_str.encode()).hexdigest()

    params = {
        'q': query,
        'from': 'en',
        'to': 'zh',
        'appid': app_id,
        'salt': salt,
        'sign': sign
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        result = response.json()
        if 'trans_result' in result:
            return result['trans_result'][0]['dst']
        else:
            error_msg = result.get('error_msg', '未知错误')
            logging.error(f"百度翻译API错误: {error_msg}")
            return f"[翻译错误] {error_msg}"
    except Exception as e:
        logging.error(f"请求百度翻译失败: {e}")
        return f"[网络错误] {e}"

def split_words(text):
    """提取英文单词（去重、排序）"""
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    return sorted(set(words))

def speak_text(text):
    """朗读文本（异步）"""
    def _speak():
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)
        engine.say(text)
        engine.runAndWait()
    threading.Thread(target=_speak, daemon=True).start()

def speak_word(word):
    """朗读单个单词"""
    def _speak():
        engine = pyttsx3.init()
        engine.setProperty('rate', 120)
        engine.say(word)
        engine.runAndWait()
    threading.Thread(target=_speak, daemon=True).start()

# ================== GUI 主程序 ==================

class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📚 英文学习翻译器")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        # 加载配置
        try:
            self.app_id, self.secret_key = load_config()
        except:
            self.root.destroy()
            return

        # 输入区域
        Label(root, text="请输入英文（单词或句子）:", font=("Arial", 12)).pack(pady=(10, 5))
        self.input_text = Text(root, height=4, width=80, font=("Consolas", 11))
        self.input_text.pack(padx=20, pady=5)

        # 按钮区域
        btn_frame = Frame(root)
        btn_frame.pack(pady=10)
        Button(btn_frame, text="🔄 翻译", command=self.translate, bg="#4CAF50", fg="white", width=10).pack(side=LEFT, padx=5)
        Button(btn_frame, text="📋 复制结果", command=self.copy_result, width=10).pack(side=LEFT, padx=5)
        Button(btn_frame, text="💾 导出文本", command=self.export_text, width=10).pack(side=LEFT, padx=5)

        # 翻译结果显示
        Label(root, text="中文翻译:", font=("Arial", 12)).pack(pady=(10, 5))
        self.translated_text = scrolledtext.ScrolledText(root, height=3, width=80, font=("SimSun", 12), wrap=WORD)
        self.translated_text.pack(padx=20, pady=5)

        # 朗读按钮（仅句子）
        self.speak_btn = Button(root, text="🔊 朗读句子", command=self.speak_translation, state=DISABLED, bg="#2196F3", fg="white")
        self.speak_btn.pack(pady=5)

        # 单词列表区域
        Label(root, text="包含的单词（点击喇叭听发音）:", font=("Arial", 12)).pack(pady=(15, 5))
        self.words_frame = Frame(root)
        self.words_frame.pack(fill=BOTH, expand=True, padx=20, pady=5)

        self.word_buttons = []

    def translate(self):
        # 清理旧内容
        self.translated_text.delete(1.0, END)
        for btn in self.word_buttons:
            btn.destroy()
        self.word_buttons.clear()
        self.speak_btn.config(state=DISABLED)

        query = self.input_text.get(1.0, END).strip()
        if not query:
            messagebox.showwarning("输入为空", "请输入要翻译的内容！")
            return

        logging.info(f"用户输入: {query[:50]}...")

        # 执行翻译
        translation = baidu_translate(query, self.app_id, self.secret_key)
        self.translated_text.insert(END, translation)

        # 判断是否为长句（含空格且长度>1个单词）
        words = split_words(query)
        is_sentence = len(words) > 1

        if is_sentence:
            self.speak_btn.config(state=NORMAL)
            self.display_word_list(words)
        else:
            self.speak_btn.config(state=DISABLED)
            if words:
                self.display_word_list(words)  # 单个单词也显示

        logging.info(f"翻译结果: {translation[:50]}...")

    def display_word_list(self, words):
        """显示单词列表，每个单词带发音按钮"""
        for word in words:
            frame = Frame(self.words_frame)
            frame.pack(anchor=W, pady=2)
            Label(frame, text=word, font=("Consolas", 11), width=15, anchor=W).pack(side=LEFT)

            # 获取单词翻译（简单处理：再调一次API，实际可用离线词典优化）
            word_trans = baidu_translate(word, self.app_id, self.secret_key)
            Label(frame, text=f" → {word_trans}", font=("SimSun", 11), fg="gray").pack(side=LEFT, padx=(10, 10))

            btn = Button(frame, text="🔈", command=lambda w=word: speak_word(w), width=3)
            btn.pack(side=LEFT)
            self.word_buttons.append(frame)

    def speak_translation(self):
        text = self.translated_text.get(1.0, END).strip()
        if text:
            speak_text(text)

    def copy_result(self):
        text = self.translated_text.get(1.0, END).strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("已复制", "翻译结果已复制到剪贴板！")
            logging.info("用户复制了翻译结果")

    def export_text(self):
        original = self.input_text.get(1.0, END).strip()
        translation = self.translated_text.get(1.0, END).strip()
        if not translation:
            messagebox.showwarning("无内容", "没有可导出的翻译结果！")
            return

        export_path = SCRIPT_DIR / "exported_translation.txt"
        try:
            with open(export_path, 'a', encoding='utf-8') as f:
                f.write("="*50 + "\n")
                f.write(f"原文: {original}\n")
                f.write(f"译文: {translation}\n")
                f.write("\n")
            messagebox.showinfo("导出成功", f"已追加保存到:\n{export_path}")
            logging.info(f"导出翻译到 {export_path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"错误: {e}")
            logging.error(f"导出失败: {e}")

# ================== 启动程序 ==================

if __name__ == "__main__":
    root = Tk()
    app = TranslatorApp(root)
    root.mainloop()
