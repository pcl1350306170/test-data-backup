# anki_vocab_builder.pyw
import asyncio
import os
import json
import logging
import tempfile
import shutil
import time
from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox, ttk
import subprocess
import threading
import base64

# ==============================
# 第三方库导入（带错误提示）
# ==============================
try:
    from gtts import gTTS
except ImportError:
    gTTS = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from google.cloud import texttospeech as google_tts
except ImportError:
    google_tts = None

import genanki
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
        {'name': 'ExampleTranslator'},
        {'name': 'Audio'},
        {'name': 'ExampleAudio'},
        {'name': 'AIHelp'},
        {'name': 'imgExample'},
    ],
    templates=[
        {
            'name': 'Card 1',
            'qfmt': '{{Word}}<br>{{Audio}}',
            'afmt': '''
{{Audio}}{{Word}}<br>
{{Phonetic}}<br><br>
{{Meaning}}<br><br>
{{ExampleAudio}}<i>{{Example}}</i><br>
{{ExampleTranslator}}<br><br>
{{AIHelp}}<br><br>
{{imgExample}}<br><br>
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
# TTS 引擎实现
# ==============================
async def synthesize_edge(text, lang, output_path):
    """使用 Edge TTS（免费），增加重试和延迟"""
    if not edge_tts:
        return False

    voice_map = {
        'en': 'en-US-JennyNeural',
        'zh': 'zh-CN-XiaoxiaoNeural',
    }
    voice = voice_map.get(lang, 'en-US-JennyNeural')

    # 重试次数
    max_retries = 3
    delay = 0.5  # 基础延迟（秒）

    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)

            # 检查文件是否生成成功（大小是否 > 0）
            if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                logger.info(f"Edge TTS success: {output_path}")
                await asyncio.sleep(delay)  # 请求后延迟
                return True
            else:
                logger.warning(f"Edge TTS returned empty file: {output_path}")

        except Exception as e:
            logger.error(f"Edge TTS attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay * (attempt + 1))  # 每次重试延迟递增
            continue

    logger.error(f"Edge TTS failed after {max_retries} attempts for: {text}")
    return False

def synthesize_google_cloud(text, lang, output_path, credentials_json=None):
    """使用 Google Cloud TTS（需凭据）"""
    if not google_tts or not credentials_json:
        return False
    try:
        import os
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_json

        client = google_tts.TextToSpeechClient()
        synthesis_input = google_tts.SynthesisInput(text=text)
        voice = google_tts.VoiceSelectionParams(
            language_code="en-US" if lang == "en" else "zh-CN",
            ssml_gender=google_tts.SsmlVoiceGender.NEUTRAL
        )
        audio_config = google_tts.AudioConfig(audio_encoding=google_tts.AudioEncoding.MP3)
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
        logger.info(f"Google Cloud TTS success: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Google Cloud TTS failed: {e}")
        return False

def synthesize_gtts(text, lang, output_path):
    """使用 gTTS（非官方，有风险）"""
    if not gTTS:
        return False
    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(output_path)
        time.sleep(1.2)  # 防封关键：加延迟
        return True
    except Exception as e:
        logger.error(f"gTTS failed: {e}")
        time.sleep(2)
        return False

# ==============================
# 主逻辑：生成 APKG
# ==============================
def generate_apkg(json_path, apkg_name, export_dir, tts_engine, tts_config, progress_callback):
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
            example_translator = item.get("ExampleTranslator", "").strip()
            ai_help = item.get("AIHelp", "").strip()
            img_example = item.get("imgExample", "").strip()

            if not meaning:
                meaning = simple_meaning_fallback(word)
            if not example:
                example = simple_example_fallback(word, meaning)
            if not example_translator:
                example_translator = example

            # 处理图片
            img_example_path = ""
            if img_example:
                img_path = Path(img_example)
                if img_path.exists():
                    img_filename = img_path.name
                    target_img_path = temp_dir / img_filename
                    shutil.copy2(img_path, target_img_path)
                    media_files.append(str(target_img_path))
                    img_example_path = f"<img src='{img_filename}'>"
                else:
                    img_example_path = img_example

            # 生成音频
            word_clean = clean_filename(word)
            audio_path = ""
            example_audio_path = ""

            # Word audio
            audio_file = temp_dir / f"{word_clean}.mp3"
            success = False
            if tts_engine == "gtts":
                success = synthesize_gtts(word, 'en', str(audio_file))
            elif tts_engine == "edge" and edge_tts:
                import asyncio
                success = asyncio.run(synthesize_edge(word, 'en', str(audio_file)))
                time.sleep(0.5)  # Edge TTS 后延迟
            elif tts_engine == "google_cloud":
                cred_path = tts_config.get("google_cred_path")
                success = synthesize_google_cloud(word, 'en', str(audio_file), cred_path)

            if success:
                audio_path = f"[sound:{word_clean}.mp3]"
                media_files.append(str(audio_file))

            # Example audio
            example_file = temp_dir / f"example_{word_clean}.mp3"
            success = False
            if tts_engine == "gtts":
                success = synthesize_gtts(example, 'en', str(example_file))
            elif tts_engine == "edge" and edge_tts:
                import asyncio
                success = asyncio.run(synthesize_edge(example, 'en', str(example_file)))
                time.sleep(0.5)  # Edge TTS 后延迟
            elif tts_engine == "google_cloud":
                cred_path = tts_config.get("google_cred_path")
                success = synthesize_google_cloud(example, 'en', str(example_file), cred_path)

            if success:
                example_audio_path = f"[sound:example_{word_clean}.mp3]"
                media_files.append(str(example_file))

            note = genanki.Note(
                model=APKG_MODEL,
                fields=[
                    word,
                    phonetic,
                    meaning,
                    example,
                    example_translator,
                    audio_path,
                    example_audio_path,
                    ai_help,
                    img_example_path
                ]
            )
            deck.add_note(note)
            progress_callback(idx + 1, total)

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

# ==============================
# GUI 界面
# ==============================
class AnkiBuilderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Anki 单词牌组生成器")
        self.root.geometry("580x520")
        self.root.resizable(False, False)

        self.config = self.load_config()
        self.create_widgets()
        self.update_tts_options()

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
            "google_cred_path": self.google_cred_path.get(),
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

    def select_google_cred(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if path:
            self.google_cred_path.set(path)

    def update_tts_options(self):
        # 检查各引擎可用性
        self.radio_gtts.config(state='normal' if gTTS else 'disabled')
        self.radio_edge.config(state='normal' if edge_tts else 'disabled')
        self.radio_google_cloud.config(state='normal' if google_tts else 'disabled')

        # 如果当前选中的不可用，回退到可用选项
        current = self.tts_engine.get()
        available = []
        if gTTS: available.append("gtts")
        if edge_tts: available.append("edge")
        if google_tts: available.append("google_cloud")

        if available and current not in available:
            self.tts_engine.set(available[0])

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

        # 检查 Google Cloud 凭据
        if tts_engine == "google_cloud":
            cred_path = self.google_cred_path.get()
            if not cred_path or not Path(cred_path).exists():
                messagebox.showerror("错误", "请提供有效的 Google Cloud 凭据 JSON 文件")
                return

        self.save_config()

        self.btn_generate.config(state='disabled')
        self.progress['value'] = 0
        self.progress_label.config(text="处理中...")

        tts_config = {
            "google_cred_path": self.google_cred_path.get() if tts_engine == "google_cloud" else None
        }

        thread = threading.Thread(
            target=self.run_generation,
            args=(json_path, apkg_name, export_dir, tts_engine, tts_config),
            daemon=True
        )
        thread.start()

    def run_generation(self, json_path, apkg_name, export_dir, tts_engine, tts_config):
        try:
            def update_progress(current, total):
                self.root.after(0, lambda: self.progress.config(value=int(100 * current / total)))
            result = generate_apkg(json_path, apkg_name, export_dir, tts_engine, tts_config, update_progress)
            self.root.after(0, lambda: self.on_success(result))
        except Exception as e:
            self.root.after(0, lambda: self.on_error(str(e)))

    def on_success(self, apkg_path):
        self.btn_generate.config(state='normal')
        self.progress_label.config(text="完成！")
        apkg_dir = Path(apkg_path).parent
        try:
            subprocess.run(['explorer', str(apkg_dir)], check=True)
        except Exception as e:
            logger.warning(f"Failed to open directory: {e}")

    def on_error(self, error_msg):
        self.btn_generate.config(state='normal')
        self.progress_label.config(text="失败")
        messagebox.showerror("错误", f"生成失败：\n{error_msg}")

    def create_widgets(self):
        # JSON 选择
        frame1 = Frame(self.root)
        frame1.pack(pady=5, padx=20, fill=X)
        Label(frame1, text="单词 JSON 文件:").pack(anchor=W)
        self.json_path = StringVar(value=self.config.get("last_json", ""))
        Entry(frame1, textvariable=self.json_path, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(frame1, text="选择", command=self.select_json).pack(side=RIGHT)

        # APKG 名称
        frame2 = Frame(self.root)
        frame2.pack(pady=5, padx=20, fill=X)
        Label(frame2, text="APKG 名称:").pack(anchor=W)
        self.apkg_name = StringVar(value=self.config.get("last_apkg_name", "My Vocab Deck"))
        Entry(frame2, textvariable=self.apkg_name).pack(fill=X, pady=(5,0))

        # 导出目录
        frame3 = Frame(self.root)
        frame3.pack(pady=5, padx=20, fill=X)
        Label(frame3, text="导出目录:").pack(anchor=W)
        dir_frame = Frame(frame3)
        dir_frame.pack(fill=X, pady=(5,0))
        self.export_dir = StringVar(value=self.config.get("export_dir", r"D:\yarward\APKG"))
        Entry(dir_frame, textvariable=self.export_dir, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(dir_frame, text="浏览", command=self.select_export_dir).pack(side=RIGHT)

        # TTS 引擎选择
        frame4 = Frame(self.root)
        frame4.pack(pady=10, padx=20, fill=X)
        Label(frame4, text="TTS 引擎:").pack(anchor=W)
        radio_frame = Frame(frame4)
        radio_frame.pack(pady=(5,0))
        self.tts_engine = StringVar(value=self.config.get("tts_engine", "gtts"))
        self.radio_gtts = Radiobutton(radio_frame, text="gTTS (非官方，有风险)", variable=self.tts_engine, value="gtts")
        self.radio_gtts.pack(anchor=W)
        self.radio_edge = Radiobutton(radio_frame, text="Edge TTS (推荐，免费稳定)", variable=self.tts_engine, value="edge")
        self.radio_edge.pack(anchor=W)
        self.radio_google_cloud = Radiobutton(radio_frame, text="Google Cloud TTS (需API密钥)", variable=self.tts_engine, value="google_cloud")
        self.radio_google_cloud.pack(anchor=W)

        # Google Cloud 凭据
        frame5 = Frame(self.root)
        frame5.pack(pady=5, padx=20, fill=X)
        Label(frame5, text="Google Cloud 凭据 (仅当选择 Google Cloud 时需要):").pack(anchor=W)
        cred_frame = Frame(frame5)
        cred_frame.pack(fill=X, pady=(5,0))
        self.google_cred_path = StringVar(value=self.config.get("google_cred_path", ""))
        Entry(cred_frame, textvariable=self.google_cred_path, state='readonly').pack(side=LEFT, fill=X, expand=True, padx=(0,5))
        Button(cred_frame, text="选择", command=self.select_google_cred).pack(side=RIGHT)

        # 进度条
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(pady=10, padx=20, fill=X)
        self.progress_label = Label(self.root, text="")
        self.progress_label.pack()

        # 生成按钮
        self.btn_generate = Button(self.root, text="生成 APKG", command=self.start_generate, height=2)
        self.btn_generate.pack(pady=15, padx=20, fill=X)

# ==============================
# 安装依赖提示
# ==============================
def check_dependencies():
    missing = []
    if not gTTS:
        missing.append("gTTS")
    if not edge_tts:
        missing.append("edge-tts")
    if not google_tts:
        missing.append("google-cloud-texttospeech")

    if missing:
        msg = "缺少以下依赖库，请在命令行运行安装命令：\n\n"
        msg += "pip install " + " ".join(missing) + "\n\n"
        msg += "安装完成后重启本程序。"
        root = Tk()
        root.withdraw()
        messagebox.showwarning("依赖缺失", msg)
        root.destroy()
        return False
    return True

# ==============================
# 主程序入口
# ==============================
if __name__ == "__main__":
    if not check_dependencies():
        exit(1)
    root = Tk()
    app = AnkiBuilderGUI(root)
    root.mainloop()
