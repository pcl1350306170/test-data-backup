# word_splitter.pyw

import os
import json
import re
import logging
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "word_splitter"  # 脚本名称
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
PROCESS_LOG_FILE = SCRIPT_DIR / "json" / "logs" / f"log_{SCRIPT_NAME}.log"

# 确保日志目录存在
PROCESS_LOG_FILE.parent.mkdir(exist_ok=True)

# 设置日志
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

class WordSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("英语句子拆分工具")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        # 变量
        self.word_file_path = tk.StringVar()
        self.sentence_input = tk.StringVar()

        # 加载配置
        self.config = self.load_config()

        # 创建界面
        self.create_widgets()

        # 应用配置
        self.apply_config()

    def load_config(self):
        """加载配置文件"""
        default_config = {
            "word_file_path": "",
            "exclude_words": ["the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "its", "our", "their", "mine", "yours", "hers", "ours", "theirs"]
        }

        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    # 合并默认配置和现有配置
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    return config
            except Exception as e:
                logging.error(f"加载配置失败: {e}")
                messagebox.showerror("错误", f"配置文件加载失败: {e}")
        return default_config

    def save_config(self):
        """保存配置文件"""
        # 获取过滤词文本框中的内容
        exclude_text = self.exclude_text.get("1.0", tk.END).strip()
        # 按换行符和逗号分割，去重并过滤空字符串
        exclude_list = []
        for part in exclude_text.split(','):
            part = part.strip()
            if part:
                exclude_list.extend([word.strip() for word in part.split('\n') if word.strip()])
        exclude_list = list(set(word.lower() for word in exclude_list if word))  # 去重并转小写

        config = {
            "word_file_path": self.word_file_path.get(),
            "exclude_words": exclude_list
        }

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logging.info("配置已保存")
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            logging.error(f"保存配置失败: {e}")
            messagebox.showerror("错误", f"配置保存失败: {e}")

    def apply_config(self):
        """应用配置到界面"""
        self.word_file_path.set(self.config.get("word_file_path", ""))
        # 将过滤词列表转为字符串，每行一个词
        exclude_str = "\n".join(self.config.get("exclude_words", []))
        self.exclude_text.delete("1.0", tk.END)
        self.exclude_text.insert("1.0", exclude_str)

    def create_widgets(self):
        """创建界面组件"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 词库文件选择
        file_frame = ttk.LabelFrame(main_frame, text="词库文件", padding="5")
        file_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(file_frame, textvariable=self.word_file_path, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        ttk.Button(file_frame, text="浏览...", command=self.select_word_file).pack(side=tk.RIGHT)

        # 2. 过滤词输入（增高并支持换行）
        exclude_frame = ttk.LabelFrame(main_frame, text="过滤词（每行一个词，或用逗号分隔）", padding="5")
        exclude_frame.pack(fill=tk.X, pady=5)
        self.exclude_text = tk.Text(exclude_frame, height=6, wrap=tk.WORD)  # 增高
        self.exclude_text.pack(fill=tk.X, pady=5)

        # 3. 句子输入
        sentence_frame = ttk.LabelFrame(main_frame, text="输入英语句子", padding="5")
        sentence_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.sentence_text = tk.Text(sentence_frame, height=6, wrap=tk.WORD)
        self.sentence_text.pack(fill=tk.BOTH, expand=True)

        # 4. 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="拆分并写入", command=self.split_and_write).pack(side=tk.LEFT, padx=(0,5))
        ttk.Button(button_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=(0,5))
        ttk.Button(button_frame, text="清空日志", command=self.clear_log).pack(side=tk.RIGHT)

        # 5. 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def select_word_file(self):
        """选择词库文件"""
        file_path = filedialog.askopenfilename(
            title="选择词库 JSON 文件",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=CONFIG_DIR
        )
        if file_path:
            self.word_file_path.set(file_path)
            self.log(f"选择词库文件: {file_path}")

            # 读取文件中的所有单词并添加到过滤词中
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    word_list = json.load(f)

                existing_words = set(word.lower() for word in self.config.get("exclude_words", []))
                new_words = set()

                for item in word_list:
                    word = item.get("Word", "").strip().lower()
                    if word:
                        new_words.add(word)

                # 合并现有和新单词
                all_words = existing_words.union(new_words)

                # 更新配置
                self.config["exclude_words"] = list(all_words)

                # 更新界面显示
                exclude_str = "\n".join(sorted(all_words))
                self.exclude_text.delete("1.0", tk.END)
                self.exclude_text.insert("1.0", exclude_str)

                self.log(f"从文件中读取到 {len(new_words)} 个单词，已添加到过滤词中")

            except Exception as e:
                error_msg = f"读取文件中的单词失败: {e}"
                logging.error(error_msg)
                self.log(error_msg)
                messagebox.showerror("错误", error_msg)

    def split_and_write(self):
        """拆分句子并写入 JSON"""
        sentence = self.sentence_text.get("1.0", tk.END).strip()
        if not sentence:
            messagebox.showwarning("警告", "请输入要拆分的句子")
            return

        word_file_path_str = self.word_file_path.get()
        if not word_file_path_str:
            messagebox.showerror("错误", "请先选择词库文件")
            return

        word_file_path = Path(word_file_path_str)
        if not word_file_path.exists():
            messagebox.showerror("错误", f"词库文件不存在: {word_file_path}")
            return

        try:
            # 读取现有词库
            with open(word_file_path, "r", encoding="utf-8") as f:
                word_list = json.load(f)

            # 拆分句子为单词
            words = self.split_sentence(sentence)

            # 获取过滤词（从文本框中读取）
            exclude_text = self.exclude_text.get("1.0", tk.END).strip()
            exclude_set = set()
            for part in exclude_text.split(','):
                part = part.strip()
                if part:
                    exclude_set.update(word.strip().lower() for word in part.split('\n') if word.strip())

            # 转换为小写集合，用于快速查找重复
            existing_words = set(item.get("Word", "").lower() for item in word_list)

            # 统计
            added_count = 0
            skipped_count = 0

            for word in words:
                lower_word = word.lower()
                if len(lower_word) < 3:
                    skipped_count += 1
                    self.log(f"跳过短单词: {word} (长度<{3})")
                    continue

                if lower_word in exclude_set:
                    skipped_count += 1
                    self.log(f"跳过过滤词: {word}")
                    continue

                if lower_word in existing_words:
                    skipped_count += 1
                    self.log(f"跳过已存在单词: {word}")
                    continue

                # 添加新单词
                new_entry = {
                    "Word": word,
                    "Phonetic": "",
                    "Meaning": "",
                    "Example": "",
                    "ExampleTranslator": "",
                    "Audio": "",
                    "ExampleAudio": ""
                }
                word_list.append(new_entry)
                existing_words.add(lower_word)
                added_count += 1
                self.log(f"添加新单词: {word}")

            # 写回文件
            with open(word_file_path, "w", encoding="utf-8") as f:
                json.dump(word_list, f, ensure_ascii=False, indent=2)

            self.log(f"拆分完成！新增: {added_count}, 跳过: {skipped_count}")
            messagebox.showinfo("成功", f"拆分完成！\n新增单词: {added_count}\n跳过单词: {skipped_count}")

        except Exception as e:
            error_msg = f"拆分写入失败: {e}"
            logging.error(error_msg)
            self.log(error_msg)
            messagebox.showerror("错误", error_msg)

    def split_sentence(self, sentence):
        """拆分句子为单词"""
        # 使用正则表达式拆分，保留字母数字组成的单词
        words = re.findall(r'\b[a-zA-Z]+\b', sentence)
        # 去重，保持顺序
        seen = set()
        result = []
        for word in words:
            lower_word = word.lower()
            if lower_word not in seen:
                seen.add(lower_word)
                result.append(word)
        return result

    def clear_log(self):
        """清空日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log("日志已清空")

    def log(self, message):
        """记录日志到界面和文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        logging.info(message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = WordSplitterApp(root)
    root.mainloop()
