# qwen_vocab_enhancer.py
import os
import json
import logging
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
import threading
import re

# ==============================
# 第三方库导入
# ==============================
try:
    from httpx import Client as HTTPXClient
except ImportError:
    HTTPXClient = None

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "qwen_vocab_enhancer"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 创建目录
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROCESS_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger()

# ==============================
# 工具函数
# ==============================
def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}
    return {}

def save_config(data):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Config saved.")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

def is_verb_form(word):
    """简单判断是否为动词分词或复数，并尝试还原原形（仅基础规则）"""
    irregulars = {
        "went": "go", "seen": "see", "done": "do", "taken": "take", "given": "give", "made": "make",
        "said": "say", "thought": "think", "brought": "bring", "built": "build", "bought": "buy",
        "taught": "teach", "caught": "catch", "found": "find", "held": "hold", "kept": "keep",
        "left": "leave", "lost": "lose", "meant": "mean", "met": "meet", "paid": "pay", "put": "put",
        "read": "read", "run": "run", "sat": "sit", "sold": "sell", "sent": "send", "shut": "shut",
        "spent": "spend", "stood": "stand", "told": "tell", "understood": "understand", "woke": "wake",
        "won": "win", "written": "write",
    }
    if word.lower() in irregulars:
        return irregulars[word.lower()], "过去分词/过去式"
    # 规则动词过去式/过去分词
    if re.search(r'ed$', word) and len(word) > 3:
        base = re.sub(r'ed$', '', word)
        return base, "过去分词/过去式"
    # 复数名词
    if word.endswith('ies') and len(word) > 4:
        base = word[:-3] + 'y'
        return base, "复数"
    elif word.endswith('es') and len(word) > 3:
        base = word[:-2]
        return base, "复数"
    elif word.endswith('s') and len(word) > 2 and not word.endswith(('ss', 'us', 'is')):
        base = word[:-1]
        return base, "复数"
    return None, None

def build_ai_help_html(api_key, word):
    prompt = f"""你是专业的英语词典编纂者。帮助一个初学者记住单词 "{word}" 。要求：
    - 如果单词"{word}"可以拆解，你就把这个单词"{word}"拆解一下，是由那几个词根组成，还有哪些类似的单词
    - 如果"{word}"可以使用谐音 + 场景记忆，你具体列出来记忆方式。
    - 给我列出来"{word}"还有哪些含义、词根组成类似的单词
    。"""
    response = call_qwen_api(api_key, prompt)
    lines = response.split('\n')
    help_text = lines[0].strip() if len(lines) > 0 else f"关于 '{word}' ，自己去死记硬背吧，AI都帮不了你！"
    return help_text

# ==============================
# Qwen API 调用
# ==============================
def call_qwen_api(api_key, prompt, timeout=30):
    if not HTTPXClient:
        raise RuntimeError("httpx 未安装，请运行: pip install httpx")
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen-max",
        "input": {
            "messages": [{"role": "user", "content": prompt}]
        },
        "parameters": {"result_format": "message"}
    }
    try:
        with HTTPXClient(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=data)
            resp.raise_for_status()
            result = resp.json()
            content = result['output']['choices'][0]['message']['content']
            return content.strip()
    except Exception as e:
        logger.error(f"Qwen API error: {e}")
        raise

def generate_example_and_translation(api_key, word, meaning=""):
    prompt = f"""你是一名资深程序员和技术英语专家。请为单词 "{word}" 生成一个贴近程序员工作场景的英文例句（简洁、真实、技术相关），并提供对应的中文翻译。要求：
- 例句必须包含 "{word}"，例句长度3到6个短句子，且自然流畅
- 场景可包括：编程、系统运维、网络安全、云计算、AI开发、吐槽不合理的系统交互等
- 中文翻译要准确、口语化
只返回两行：
第一行：英文例句
第二行：中文翻译
不要任何其他文字、标号或解释。"""
    response = call_qwen_api(api_key, prompt)
    lines = response.split('\n')
    en = lines[0].strip() if len(lines) > 0 else f"The term '{word}' is commonly used in technical documentation."
    zh = lines[1].strip() if len(lines) > 1 else en
    return en, zh

# --- 新增函数：获取 Meaning 和 Phonetic ---
def generate_meaning_and_phonetic(api_key, word):
    """
    调用 AI 获取单词的详细含义和音标。
    返回: (meaning_str, phonetic_str)
    """
    prompt = f"""你是一位专业的英语词典编纂者。请为单词 "{word}" 提供以下信息：
1. **Meaning**: 详细的词性和释义，格式如 "adj. 不变的；恒定的；n. 常数；常量"。
2. **Phonetic**: 标准英式和美式发音的音标，格式如 "英 [ˈkɒnstənt]，美 [ˈkɑːnstənt]"。

请严格按照以下 JSON 格式返回，不要包含任何其他文字：
{{
    "Meaning": "此处填写含义",
    "Phonetic": "此处填写音标"
}}"""
    try:
        response = call_qwen_api(api_key, prompt)
        # 尝试解析 JSON
        import json
        data = json.loads(response)
        meaning = data.get("Meaning", "").strip()
        phonetic = data.get("Phonetic", "").strip()
        return meaning, phonetic
    except Exception as e:
        logger.error(f"Failed to parse Meaning/Phonetic for '{word}': {e}")
        # 如果解析失败，提供一个安全的回退方案
        fallback_meaning = f"（AI 未能成功解析含义，请手动补充）"
        fallback_phonetic = f"（AI 未能成功解析音标，请手动补充）"
        return fallback_meaning, fallback_phonetic
# --- 新增函数结束 ---

# ==============================
# 主处理逻辑
# ==============================
def process_json_file(input_path, output_path, api_key, progress_callback):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    total = len(data)
    for idx, item in enumerate(data):
        word = item.get("Word", "").strip()
        if not word:
            continue

        # --- 新增逻辑：检查并补充 Meaning 和 Phonetic ---
        need_meaning = not item.get("Meaning", "").strip()
        need_phonetic = not item.get("Phonetic", "").strip()

        if need_meaning or need_phonetic:
            try:
                ai_meaning, ai_phonetic = generate_meaning_and_phonetic(api_key, word)
                if need_meaning:
                    item["Meaning"] = ai_meaning
                if need_phonetic:
                    item["Phonetic"] = ai_phonetic
                logger.info(f"Generated Meaning/Phonetic for '{word}': {ai_meaning} | {ai_phonetic}")
            except Exception as e:
                fallback_meaning = f"（获取含义失败: {str(e)}）"
                fallback_phonetic = f"（获取音标失败: {str(e)}）"
                if need_meaning:
                    item["Meaning"] = fallback_meaning
                if need_phonetic:
                    item["Phonetic"] = fallback_phonetic
                logger.warning(f"Failed to generate Meaning/Phonetic for '{word}', using fallback. Error: {e}")
        # --- 新增逻辑结束 ---

        # 检查是否需要补全 Example / ExampleTranslator
        need_example = not item.get("Example", "").strip()
        need_translator = not item.get("ExampleTranslator", "").strip()

        # 还原词形
        base_word, form_type = is_verb_form(word)
        actual_word = base_word if base_word else word

        # 补全 Example 和翻译
        if need_example or need_translator:
            try:
                en_ex, zh_ex = generate_example_and_translation(api_key, actual_word)
                if need_example:
                    item["Example"] = en_ex
                if need_translator:
                    item["ExampleTranslator"] = zh_ex
                logger.info(f"Generated example for '{word}': {en_ex}")
            except Exception as e:
                fallback_en = f"In the code review, we discussed the implications of using '{actual_word}'."
                fallback_zh = f"在代码评审中，我们讨论了使用“{actual_word}”的影响。"
                if need_example:
                    item["Example"] = fallback_en
                if need_translator:
                    item["ExampleTranslator"] = fallback_zh
                logger.warning(f"Failed to generate example for '{word}', using fallback. Error: {e}")

        # 生成 AIHelp（始终更新，因为可能词形变了）
        item["AIHelp"] = build_ai_help_html(api_key, actual_word)
        progress_callback(idx + 1, total)

    # 保存新文件
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Processed JSON saved to: {output_path}")

# ==============================
# GUI
# ==============================
class QwenVocabEnhancerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Qwen 单词增强器")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        self.config = load_config()
        self.create_widgets()

    def create_widgets(self):
        # JSON 选择
        frame1 = Frame(self.root)
        frame1.pack(pady=5, padx=20, fill=X)
        Label(frame1, text="待处理的 JSON 文件:").pack(anchor=W)
        self.json_path = StringVar(value=self.config.get("last_json", ""))
        Entry(frame1, textvariable=self.json_path, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(frame1, text="选择", command=self.select_json).pack(side=RIGHT)

        # API Key
        frame2 = Frame(self.root)
        frame2.pack(pady=5, padx=20, fill=X)
        Label(frame2, text="通义千问 API Key:").pack(anchor=W)
        self.api_key = StringVar(value=self.config.get("qwen_api_key", ""))
        Entry(frame2, textvariable=self.api_key, show="*").pack(fill=X, pady=(5,0))

        # 输出目录
        frame3 = Frame(self.root)
        frame3.pack(pady=5, padx=20, fill=X)
        Label(frame3, text="输出目录:").pack(anchor=W)
        dir_frame = Frame(frame3)
        dir_frame.pack(fill=X, pady=(5,0))
        default_out = str(Path(self.config.get("export_dir", SCRIPT_DIR / "output")))
        self.export_dir = StringVar(value=default_out)
        Entry(dir_frame, textvariable=self.export_dir, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(dir_frame, text="浏览", command=self.select_export_dir).pack(side=RIGHT)

        # 按钮
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=20)
        Button(btn_frame, text="开始增强", command=self.start_process, width=15, height=2).pack(side=LEFT, padx=10)
        Button(btn_frame, text="显示明文密钥", command=self.toggle_key_visibility, width=15).pack(side=LEFT, padx=10)

        # 进度条
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(pady=10, padx=20, fill=X)
        self.progress_label = Label(self.root, text="")
        self.progress_label.pack()
        self.key_visible = False
        self.key_entry = None

    def select_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if path:
            self.json_path.set(path)

    def select_export_dir(self):
        path = filedialog.askdirectory(initialdir=self.export_dir.get())
        if path:
            self.export_dir.set(path)

    def toggle_key_visibility(self):
        current_widget = self.root.winfo_children()[1].winfo_children()[1] # 粗略定位Entry
        if isinstance(current_widget, Entry):
            if self.key_visible:
                current_widget.config(show="*")
                self.key_visible = False
            else:
                current_widget.config(show="")
                self.key_visible = True

    def start_process(self):
        json_path = self.json_path.get()
        api_key = self.api_key.get().strip()
        export_dir = self.export_dir.get().strip()

        if not Path(json_path).exists():
            messagebox.showerror("错误", "请选择有效的 JSON 文件")
            return
        if not api_key:
            messagebox.showerror("错误", "请输入 Qwen API Key")
            return
        if not export_dir:
            messagebox.showerror("错误", "请选择输出目录")
            return

        # 保存配置
        save_config({
            "last_json": json_path,
            "qwen_api_key": api_key,
            "export_dir": export_dir
        })

        # 准备输出路径
        input_name = Path(json_path).stem
        output_path = Path(export_dir) / f"{input_name}_enhanced.json"
        Path(export_dir).mkdir(parents=True, exist_ok=True)

        self.progress['value'] = 0
        self.progress_label.config(text="处理中...")
        self.root.update()

        # 后台线程处理
        thread = threading.Thread(
            target=self.run_process,
            args=(json_path, output_path, api_key),
            daemon=True
        )
        thread.start()

    def run_process(self, json_path, output_path, api_key):
        try:
            def update_progress(current, total):
                self.root.after(0, lambda: self.progress.config(value=int(100 * current / total)))
            process_json_file(json_path, output_path, api_key, update_progress)
            self.root.after(0, lambda: self.on_success(output_path))
        except Exception as e:
            logger.exception("Processing failed")
            self.root.after(0, lambda: self.on_error(str(e)))

    def on_success(self, output_path):
        self.progress_label.config(text="✅ 完成！")
        messagebox.showinfo("成功", f"增强后的文件已保存：\n{output_path}")

    def on_error(self, error_msg):
        self.progress_label.config(text="❌ 失败")
        messagebox.showerror("错误", f"处理失败：\n{error_msg}")

# ==============================
# 主程序
# ==============================
if __name__ == "__main__":
    if not HTTPXClient:
        root = Tk()
        root.withdraw()
        messagebox.showerror("依赖缺失", "请安装 httpx:\n\npip install httpx")
        root.destroy()
        exit(1)

    # 可选：加载 DB_CONFIG（虽不用，但按要求读取）
    if DB_CONFIG_PATH.exists():
        try:
            with open(DB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                db_config = json.load(f)
        except:
            pass

    root = Tk()
    app = QwenVocabEnhancerGUI(root)
    root.mainloop()
