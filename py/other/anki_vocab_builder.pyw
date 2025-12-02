# anki_vocab_builder.pyw

import os
import json
import logging
import tempfile
import shutil
import hashlib
import time
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
import subprocess
import webbrowser
from gtts import gTTS
import genanki
import threading
import requests

# ==============================
# 配置与常量
# ==============================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "anki_vocab_builder"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

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
# 百度 TTS 工具类
# ==============================
class BaiduTTS:
    def __init__(self, app_id, api_key, secret_key):
        self.app_id = app_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.token = None
        self._get_token()

    def _get_token(self):
        url = "https://openapi.baidu.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }
        try:
            res = requests.post(url, params=params)
            data = res.json()
            self.token = data.get("access_token")
            logger.info("Baidu TTS token acquired")
        except Exception as e:
            logger.error(f"Failed to get Baidu token: {e}")
            self.token = None

    def synthesize(self, text, lang='en', output_path=None):
        if not self.token:
            return False
        # 百度英文发音人：per=4 (英文女声), per=5 (英文男声)
        per = 4 if lang == 'en' else 1
        url = "https://tsn.baidu.com/text2audio"
        data = {
            "tex": text,
            "tok": self.token,
            "cuid": hashlib.md5(b"anki_tool").hexdigest(),
            "ctp": 1,
            "lan": "zh" if lang != "en" else "en",
            "spd": 5,
            "pit": 5,
            "vol": 9,
            "per": per  # 英文发音人
        }
        try:
            res = requests.post(url, data=data)
            if res.headers.get('content-type') == 'audio/mp3':
                with open(output_path, 'wb') as f:
                    f.write(res.content)
                logger.info(f"Baidu TTS audio saved: {output_path}")
                return True
            else:
                error_info = res.json().get("err_msg", "Unknown error")
                logger.error(f"Baidu TTS error: {error_info}")
                return False
        except Exception as e:
            logger.error(f"Baidu TTS failed for '{text}': {e}")
            return False

# ==============================
# Anki 笔记类型定义
# ==============================
MODEL_ID = 1607392319
APKG_MODEL = genanki.Model(
    MODEL_ID,
    'Vocab with Audio',
    fields=[
        {'name': 'Word'},
        {'name': 'Phonetic'},
        {'name': 'Meaning'},
        {'name': 'Example'},
        {'name': 'ExampleTranslator'},  # ← 新增字段
        {'name': 'Audio'},
        {'name': 'ExampleAudio'},
    ],
    templates=[
        {
            'name': 'Card 1',
            'qfmt': '{{Word}}<br>{{Audio}}',
            'afmt': '''
{{Word}}<br>
{{Phonetic}}<br><br>
{{Meaning}}<br><br>
<i>{{Example}}</i><br>
{{ExampleTranslator}}<br><br>  <!-- ← 新增显示 -->
{{Audio}}<br>
{{ExampleAudio}}
''',
        },
    ],
    css='''
.card {
 font-family: Arial, sans-serif;
 font-size: 20px;
 text-align: center;
 color: #333;
 background-color: #fff;
}
'''
)

# ==============================
# 工具函数
# ==============================
def simple_meaning_fallback(word):
    return f"unknown meaning of '{word}'"

def simple_example_fallback(word, meaning):
    if "unknown" in meaning:
        return f"I need to learn the word '{word}'."
    return f"The word '{word}' means {meaning.lower()}."

def clean_filename(text):
    return "".join(c if c.isalnum() else "_" for c in text)[:30]

# ==============================
# 主逻辑：生成 APKG
# ==============================
def generate_apkg(json_path, apkg_name, export_dir, tts_engine, baidu_tts, progress_callback):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            words_data = json.load(f)

        deck_id = abs(hash(apkg_name)) % (10 ** 10)
        deck = genanki.Deck(deck_id, apkg_name)
        media_files = []
        temp_dir = Path(tempfile.mkdtemp())

        total = len(words_data)
        for idx, item in enumerate(words_data):
            word = item.get("Word", "").strip()
            if not word:
                continue

            phonetic = item.get("Phonetic", "").strip()
            meaning = item.get("Meaning", "").strip()
            example = item.get("Example", "").strip()
            example_translator = item.get("ExampleTranslator", "").strip()  # ← 新增

            if not meaning:
                meaning = simple_meaning_fallback(word)
            if not example:
                example = simple_example_fallback(word, meaning)
            if not example_translator:  # ← 新增：若无翻译则使用例句
                example_translator = example

            # 生成音频
            word_clean = clean_filename(word)
            audio_path = ""
            example_audio_path = ""

            # Word audio
            audio_file = temp_dir / f"{word_clean}.mp3"
            success = False
            if tts_engine == "google":
                success = text_to_speech_google(word, 'en', str(audio_file))
            elif tts_engine == "baidu" and baidu_tts:
                success = baidu_tts.synthesize(word, 'en', str(audio_file))
            if success:
                audio_path = f"[sound:{word_clean}.mp3]"
                media_files.append(str(audio_file))

            # Example audio
            example_file = temp_dir / f"example_{word_clean}.mp3"
            success = False
            if tts_engine == "google":
                success = text_to_speech_google(example, 'en', str(example_file))
            elif tts_engine == "baidu" and baidu_tts:
                success = baidu_tts.synthesize(example, 'en', str(example_file))
            if success:
                example_audio_path = f"[sound:example_{word_clean}.mp3]"
                media_files.append(str(example_file))

            note = genanki.Note(
                model=APKG_MODEL,
                fields=[word, phonetic, meaning, example, example_translator, audio_path, example_audio_path]  # ← 新增字段
            )
            deck.add_note(note)
            progress_callback(idx + 1, total)

        # 确保导出目录存在
        export_path = Path(export_dir)
        export_path.mkdir(parents=True, exist_ok=True)
        apkg_path = export_path / f"{apkg_name}.apkg"
        genanki.Package(deck, media_files=media_files).write_to_file(apkg_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"APKG generated: {apkg_path}")
        return str(apkg_path)

    except Exception as e:
        logger.exception("APKG generation failed")
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise e

def text_to_speech_google(text, lang, output_path):
    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(output_path)
        return True
    except Exception as e:
        logger.error(f"gTTS failed: {e}")
        return False

# ==============================
# GUI 界面
# ==============================
class AnkiBuilderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki 单词牌组生成器")
        self.root.geometry("550x420")
        self.root.resizable(False, False)

        self.config = self.load_config()
        self.baidu_tts = None

        # Variables
        self.json_path = StringVar(value=self.config.get("last_json", ""))
        self.apkg_name = StringVar(value=self.config.get("last_apkg_name", "My Vocab Deck"))
        self.export_dir = StringVar(value=self.config.get("export_dir", r"D:\yarward\APKG"))
        self.tts_engine = StringVar(value=self.config.get("tts_engine", "google"))

        self.create_widgets()
        self.update_baidu_status()

    def load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_config(self):
        config = {
            "last_json": self.json_path.get(),
            "last_apkg_name": self.apkg_name.get(),
            "export_dir": self.export_dir.get(),
            "tts_engine": self.tts_engine.get(),
            "baidu_appid": self.config.get("baidu_appid", ""),
            "baidu_secret": self.config.get("baidu_secret", "")
        }
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def select_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if path:
            self.json_path.set(path)

    def select_export_dir(self):
        path = filedialog.askdirectory(initialdir=self.export_dir.get())
        if path:
            self.export_dir.set(path)

    def update_baidu_status(self):
        appid = self.config.get("baidu_appid")
        secret = self.config.get("baidu_secret")
        if appid and secret:
            self.baidu_tts = BaiduTTS(appid, appid, secret)
            self.radio_baidu.config(state='normal')
        else:
            self.baidu_tts = None
            self.radio_baidu.config(state='disabled')
            if self.tts_engine.get() == "baidu":
                self.tts_engine.set("google")

    def start_generate(self):
        json_path = self.json_path.get()
        apkg_name = self.apkg_name.get().strip()
        export_dir = self.export_dir.get().strip()
        tts_engine = self.tts_engine.get()

        if not Path(json_path).exists():
            messagebox.showerror("错误", "请选择有效的 JSON 文件")
            return
        if not apkg_name:
            messagebox.showerror("错误", "请输入 APKG 名称")
            return
        if not export_dir:
            messagebox.showerror("错误", "请选择导出目录")
            return

        self.save_config()

        # 检查百度凭据（如果选了百度）
        if tts_engine == "baidu" and not self.baidu_tts:
            messagebox.showerror("错误", "未配置百度 API 凭据，请在 config 文件中填写 baidu_appid 和 baidu_secret")
            return

        self.btn_generate.config(state='disabled')
        self.progress['value'] = 0
        self.progress_label.config(text="处理中...")

        thread = threading.Thread(
            target=self.run_generation,
            args=(json_path, apkg_name, export_dir, tts_engine),
            daemon=True
        )
        thread.start()

    def run_generation(self, json_path, apkg_name, export_dir, tts_engine):
        try:
            def update_progress(current, total):
                self.root.after(0, lambda: self.progress.config(value=int(100 * current / total)))
            result = generate_apkg(json_path, apkg_name, export_dir, tts_engine, self.baidu_tts, update_progress)
            self.root.after(0, lambda: self.on_success(result))
        except Exception as e:
            self.root.after(0, lambda: self.on_error(str(e)))

    def on_success(self, apkg_path):
        self.btn_generate.config(state='normal')
        self.progress_label.config(text="完成！")
        # 自动打开 APKG 所在目录
        apkg_dir = Path(apkg_path).parent
        try:
            subprocess.run(['explorer', str(apkg_dir)], check=True)
        except Exception as e:
            logger.warning(f"Failed to open directory: {e}")
        # messagebox.showinfo("成功", f"APKG 已生成：\n{apkg_path}\n\n目录已自动打开。")

    def on_error(self, error_msg):
        self.btn_generate.config(state='normal')
        self.progress_label.config(text="失败")
        messagebox.showerror("错误", f"生成失败：\n{error_msg}")

    def create_widgets(self):
        # JSON 选择
        frame1 = Frame(self.root)
        frame1.pack(pady=5, padx=20, fill=X)
        Label(frame1, text="单词 JSON 文件:").pack(anchor=W)
        Entry(frame1, textvariable=self.json_path, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(frame1, text="选择", command=self.select_json).pack(side=RIGHT)

        # APKG 名称
        frame2 = Frame(self.root)
        frame2.pack(pady=5, padx=20, fill=X)
        Label(frame2, text="APKG 名称:").pack(anchor=W)
        Entry(frame2, textvariable=self.apkg_name).pack(fill=X, pady=(5,0))

        # 导出目录
        frame3 = Frame(self.root)
        frame3.pack(pady=5, padx=20, fill=X)
        Label(frame3, text="导出目录:").pack(anchor=W)
        dir_frame = Frame(frame3)
        dir_frame.pack(fill=X, pady=(5,0))
        Entry(dir_frame, textvariable=self.export_dir, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(dir_frame, text="浏览", command=self.select_export_dir).pack(side=RIGHT)

        # TTS 引擎选择
        frame4 = Frame(self.root)
        frame4.pack(pady=10, padx=20, fill=X)
        Label(frame4, text="TTS 引擎:").pack(anchor=W)
        radio_frame = Frame(frame4)
        radio_frame.pack(pady=(5,0))
        self.radio_google = Radiobutton(radio_frame, text="Google TTS", variable=self.tts_engine, value="google")
        self.radio_google.pack(side=LEFT, padx=(0,10))
        self.radio_baidu = Radiobutton(radio_frame, text="百度 TTS", variable=self.tts_engine, value="baidu")
        self.radio_baidu.pack(side=LEFT)

        # 进度条
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(pady=10, padx=20, fill=X)
        self.progress_label = Label(self.root, text="")
        self.progress_label.pack()

        # 生成按钮
        self.btn_generate = Button(self.root, text="生成 APKG", command=self.start_generate, height=2)
        self.btn_generate.pack(pady=15, padx=20, fill=X)

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    root = Tk()
    app = AnkiBuilderGUI(root)
    root.mainloop()
