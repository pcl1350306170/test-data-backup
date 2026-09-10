# auto_record_vad_gui.pyw
import os
import json
import logging
import threading
import time
import random
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import pyaudio
import wave
import subprocess
import shutil

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "auto_record_vad_gui"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置（仅写入文件，不输出到控制台）
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger()

# 默认参数
DEFAULT_CONFIG = {
    "export_dir": str(SCRIPT_DIR / "output"),
    "silence_threshold": 500,
    "silence_duration": 1.5,
    "min_recording_duration": 0.8
}

# 录音参数（固定）
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 48000
CHUNK = 1024
TEMP_WAV = SCRIPT_DIR / "temp_recording.wav"

# 支持的虚拟音频设备关键词
VIRTUAL_CABLE_KEYWORDS = [
    'cable output', 'vb-audio', 'voicemeeter', 'virtual audio',
    'stereo mix', 'what you hear', '立体声混音', 'loopback'
]

# ================== 工具函数 ==================
def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise EnvironmentError("未找到 ffmpeg，请安装并确保可在命令行中运行！")

def convert_wav_to_mp3(wav_path, mp3_path):
    try:
        result = subprocess.run([
            "ffmpeg", "-y", "-i", str(wav_path),
            "-acodec", "libmp3lame", "-b:a", "192k", str(mp3_path)
        ], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return result.returncode == 0
    except Exception:
        return False

def rms(data):
    import struct
    count = len(data) // 2
    if count == 0:
        return 0
    shorts = struct.unpack(f'{count}h', data)
    sum_squares = sum(s * s for s in shorts)
    return (sum_squares / count) ** 0.5

# ================== 主应用类 ==================
class AutoRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("自动录音工具 - VB-Cable 模式")
        self.root.geometry("700x550")
        self.root.minsize(650, 500)

        # 状态
        self.is_monitoring = False
        self.monitor_thread = None
        self.p = None
        self.stream = None

        # 配置变量（绑定到 UI）
        self.export_dir = tk.StringVar()
        self.silence_threshold = tk.IntVar()
        self.silence_duration = tk.DoubleVar()
        self.min_recording_duration = tk.DoubleVar()

        # 创建 UI
        self._create_widgets()
        self._load_config()

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 导出目录 ===
        dir_frame = ttk.LabelFrame(main_frame, text="MP3 导出目录", padding="10")
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(dir_frame, textvariable=self.export_dir, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(dir_frame, text="浏览...", command=self._browse_export_dir).pack(side=tk.RIGHT)

        # === 参数设置 ===
        param_frame = ttk.LabelFrame(main_frame, text="录音参数设置", padding="10")
        param_frame.pack(fill=tk.X, pady=10)

        # 音量灵敏度
        ttk.Label(param_frame, text="音量灵敏度（越小越敏感）:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(param_frame, from_=100, to=5000, increment=50, textvariable=self.silence_threshold, width=10).grid(row=0, column=1, padx=10)

        # 等待停止时间
        ttk.Label(param_frame, text="声音停止后等待（秒）:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(param_frame, from_=0.5, to=10, increment=0.1, textvariable=self.silence_duration, width=10, format="%.1f").grid(row=1, column=1, padx=10)

        # 最短录音时长
        ttk.Label(param_frame, text="最短有效录音时长（秒）:").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(param_frame, from_=0.3, to=5, increment=0.1, textvariable=self.min_recording_duration, width=10, format="%.1f").grid(row=2, column=1, padx=10)

        # === 控制按钮 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="▶ 开始监听", command=self._toggle_monitoring, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="📁 打开导出目录", command=self._open_export_dir).pack(side=tk.RIGHT, padx=5)

        # === 日志区域 ===
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, message):
        logger.info(message)
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, update)

    def _browse_export_dir(self):
        path = filedialog.askdirectory(title="选择 MP3 导出目录")
        if path:
            self.export_dir.set(path)
            self._log(f"导出目录设为: {path}")

    def _open_export_dir(self):
        export_path = self.export_dir.get().strip()
        if not export_path or not os.path.exists(export_path):
            messagebox.showwarning("警告", "导出目录不存在！")
            return
        try:
            os.startfile(export_path)
        except Exception:
            import subprocess
            subprocess.call(["open", export_path]) if os.name == 'posix' else subprocess.call(["xdg-open", export_path])

    def _load_config(self):
        config = DEFAULT_CONFIG.copy()
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    config.update(saved)
            except Exception as e:
                self._log(f"加载配置失败: {e}")
        self.export_dir.set(config["export_dir"])
        self.silence_threshold.set(config["silence_threshold"])
        self.silence_duration.set(config["silence_duration"])
        self.min_recording_duration.set(config["min_recording_duration"])
        self._log("配置加载成功")

    def _save_config(self):
        config = {
            "export_dir": self.export_dir.get(),
            "silence_threshold": self.silence_threshold.get(),
            "silence_duration": round(self.silence_duration.get(), 1),
            "min_recording_duration": round(self.min_recording_duration.get(), 1)
        }
        try:
            CONFIG_PATH.parent.mkdir(exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            self._log(f"保存配置失败: {e}")
            messagebox.showerror("错误", f"无法保存配置:\n{e}")

    def _toggle_monitoring(self):
        if not self.is_monitoring:
            self._start_monitoring()
        else:
            self._stop_monitoring()

    def _start_monitoring(self):
        # 验证导出目录
        export_dir = self.export_dir.get().strip()
        if not export_dir:
            messagebox.showerror("错误", "请先设置导出目录！")
            return
        Path(export_dir).mkdir(exist_ok=True)

        # 启动监听线程
        self.is_monitoring = True
        self.start_btn.config(text="⏹ 停止监听")
        self._log("正在启动监听...")
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _stop_monitoring(self):
        self.is_monitoring = False
        self.start_btn.config(text="▶ 开始监听")
        self._log("已停止监听")

    def _monitor_loop(self):
        try:
            # 初始化 PyAudio
            self.p = pyaudio.PyAudio()
            device_index = None
            for i in range(self.p.get_device_count()):
                dev_info = self.p.get_device_info_by_index(i)
                if dev_info['maxInputChannels'] > 0:
                    name_lower = dev_info['name'].lower()
                    if any(kw in name_lower for kw in VIRTUAL_CABLE_KEYWORDS):
                        device_index = i
                        break
            if device_index is None:
                self.root.after(0, lambda: messagebox.showerror(
                    "设备错误",
                    "未找到 VB-Cable 或其他虚拟音频输入设备！\n\n"
                    "请确保已安装 VB-Audio Virtual Cable，并在录音设备中启用 'CABLE Output'。"
                ))
                self.root.after(0, self._stop_monitoring)
                return

            self.stream = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK
            )

            # 获取当前参数
            SILENCE_THRESHOLD = self.silence_threshold.get()
            SILENCE_DURATION = self.silence_duration.get()
            MIN_RECORDING_DURATION = self.min_recording_duration.get()

            recording = False
            frames = []
            last_sound_time = time.time()
            start_time = None

            self._log("✅ 监听已启动，等待声音...")

            while self.is_monitoring:
                try:
                    data = self.stream.read(CHUNK, exception_on_overflow=False)
                except Exception as e:
                    self._log(f"读取音频流失败: {e}")
                    continue

                volume = rms(data)

                if volume > SILENCE_THRESHOLD:
                    last_sound_time = time.time()
                    if not recording:
                        recording = True
                        frames = [data]
                        start_time = time.time()
                        self._log("🔊 检测到声音，开始录制...")
                    else:
                        frames.append(data)
                else:
                    if recording:
                        frames.append(data)
                        silence_elapsed = time.time() - last_sound_time
                        if silence_elapsed >= SILENCE_DURATION:
                            duration = time.time() - start_time
                            if duration >= MIN_RECORDING_DURATION:
                                self._save_recording(frames)
                            else:
                                self._log(f"⚠️ 录音过短 ({duration:.2f}s)，已丢弃")
                            recording = False
                            frames = []

            # 清理
            if recording and frames:
                self._save_recording(frames)

        except Exception as e:
            self._log(f"监听过程中出错: {e}")
        finally:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
            if self.p:
                self.p.terminate()
            self.root.after(0, self._stop_monitoring)

    def _save_recording(self, frames):
        self._log("正在保存录音...")
        try:
            with wave.open(str(TEMP_WAV), 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))

            export_dir = Path(self.export_dir.get())
            now = datetime.now()
            date_str = now.strftime("%Y年%m月%d日%H%M%S")
            rand_num = random.randint(1000, 9999)
            mp3_path = export_dir / f"{date_str}-{rand_num}.mp3"

            ensure_ffmpeg()
            if convert_wav_to_mp3(TEMP_WAV, mp3_path):
                self._log(f"✅ 录音已保存: {mp3_path.name}")
            else:
                self._log("❌ MP3 转换失败")

            if TEMP_WAV.exists():
                TEMP_WAV.unlink()

        except Exception as e:
            self._log(f"保存录音失败: {e}")

# ================== 启动程序 ==================
if __name__ == "__main__":
    try:
        import pyaudio
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 pyaudio:\n\npip install pyaudio")
        exit(1)

    root = tk.Tk()
    app = AutoRecorderApp(root)
    root.mainloop()
