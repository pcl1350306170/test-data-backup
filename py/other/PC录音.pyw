# record_system_audio.pyw

import os
import json
import logging
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
import pyaudio
import wave
import subprocess
import shutil


# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "record_system_audio"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# 新增对 VB-Cable 和 VoiceMeeter 的支持
VIRTUAL_CABLE_KEYWORDS = [
    'stereo mix', 'what you hear', '立体声混音', 'loopback',
    'cable output', 'vb-audio', 'voicemeeter', 'virtual audio'
]

# DB_CONFIG_PATH 按规范定义（即使未使用）
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"

# 日志路径
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# 录音参数
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100
CHUNK = 1024
TEMP_WAV = SCRIPT_DIR / "temp_recording.wav"


# ================== 主应用类 ==================
class AudioRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("系统声音录制工具")
        self.root.geometry("750x500")
        self.root.minsize(650, 450)

        # 状态变量
        self.is_recording = False
        self.audio_thread = None
        self.stream = None
        self.p = None
        self.start_time = None

        # 配置变量
        self.export_dir = tk.StringVar(value=str(SCRIPT_DIR / "output"))

        # 创建UI
        self._create_widgets()
        self._load_config()

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 导出目录设置
        dir_frame = ttk.LabelFrame(main_frame, text="MP3 导出目录", padding="10")
        dir_frame.pack(fill=tk.X, pady=5)

        ttk.Entry(dir_frame, textvariable=self.export_dir, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(dir_frame, text="浏览...", command=self._browse_export_dir).pack(side=tk.RIGHT)

        # 控制按钮
        btn_frame = ttk.Frame(main_frame, padding="10")
        btn_frame.pack(fill=tk.X, pady=10)

        self.record_btn = ttk.Button(btn_frame, text="▶ 开始录制", command=self._toggle_recording, style="Accent.TButton")
        self.record_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="📁 打开导出目录", command=self._open_export_dir).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="🧹 清空日志", command=self._clear_log).pack(side=tk.RIGHT, padx=5)

        # 状态显示
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=5)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var, foreground="green").pack(anchor=tk.W)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, message, level=logging.INFO):
        logging.log(level, message)
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, update)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._log("日志显示已清空")

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
            os.startfile(export_path)  # Windows only
        except Exception:
            # macOS / Linux fallback
            import subprocess
            subprocess.call(["open", export_path]) if os.name == 'posix' else subprocess.call(["xdg-open", export_path])

    def _save_config(self):
        config = {"export_dir": self.export_dir.get()}
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            self._log(f"保存配置失败: {e}", logging.ERROR)
            messagebox.showerror("错误", f"无法保存配置:\n{e}")

    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if "export_dir" in config:
                    self.export_dir.set(config["export_dir"])
                self._log("配置加载成功")
            except Exception as e:
                self._log(f"加载配置失败: {e}", logging.WARNING)

    def _toggle_recording(self):
        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        try:
            self.p = pyaudio.PyAudio()
            # 尝试查找“立体声混音”或默认输入设备
            device_index = None
            for i in range(self.p.get_device_count()):
                dev_info = self.p.get_device_info_by_index(i)
                if dev_info['maxInputChannels'] > 0:
                    # 优先匹配包含 "stereo mix" 或 "what you hear" 的设备（Windows）
                    name_lower = dev_info['name'].lower()
                    if any(kw in name_lower for kw in VIRTUAL_CABLE_KEYWORDS):
                        device_index = i
                        break
            if device_index is None:
                messagebox.showerror(
                    "设备错误",
                    "未找到「立体声混音」、「What U Hear」或「Loopback」设备！\n\n"
                    "请按以下步骤启用：\n"
                    "1. 右键点击音量图标 → 声音设置 → 输入设备\n"
                    "2. 点击「更多声音设置」→ 录制选项卡\n"
                    "3. 右键空白处 → 勾选「显示禁用的设备」\n"
                    "4. 启用「立体声混音」并设为默认设备"
                )
                self._log("未找到系统声音录制设备", logging.ERROR)
                return  # ← 直接返回，不启动录音
                # 若未找到，使用默认输入设备（可能录不到系统声音！）
                device_index = self.p.get_default_input_device_info()['index']

            self.stream = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK
            )

            self.is_recording = True
            self.start_time = time.time()
            self.record_btn.config(text="⏹ 结束录制")
            self.status_var.set("● 正在录制...")
            self._log("开始录制系统声音...")

            # 启动录音线程
            self.audio_thread = threading.Thread(target=self._record_audio, daemon=True)
            self.audio_thread.start()

        except Exception as e:
            self._log(f"启动录音失败: {e}", logging.ERROR)
            messagebox.showerror("录音错误", f"无法启动录音:\n{e}\n\n请确保已启用「立体声混音」设备！")
            self.is_recording = False

    def _record_audio(self):
        frames = []
        while self.is_recording:
            try:
                data = self.stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
            except Exception as e:
                self._log(f"录音过程中出错: {e}", logging.WARNING)
                break

        # 保存为临时 WAV
        try:
            with wave.open(str(TEMP_WAV), 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))
            self._log(f"临时音频已保存: {TEMP_WAV}")
        except Exception as e:
            self._log(f"保存 WAV 失败: {e}", logging.ERROR)

    def _stop_recording(self):
        self.is_recording = False
        self.status_var.set("正在停止...")

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p:
            self.p.terminate()

        # 转换为 MP3
        self.root.after(100, self._convert_to_mp3)

    def _convert_to_mp3(self):
        export_dir = self.export_dir.get().strip()
        if not export_dir:
            messagebox.showerror("错误", "请先设置 MP3 导出目录！")
            self._reset_ui()
            return

        os.makedirs(export_dir, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mp3_path = os.path.join(export_dir, f"recording_{timestamp}.mp3")

        # 检查 ffmpeg 是否可用
        if not shutil.which("ffmpeg"):
            self._log("错误: 未找到 ffmpeg，请安装 ffmpeg 并加入系统 PATH！", logging.ERROR)
            messagebox.showerror("依赖缺失", "请先安装 ffmpeg 并确保可在命令行中运行！")
            self._reset_ui()
            return

        # 调用 ffmpeg 转 MP3
        try:
            self._log(f"正在转换为 MP3: {mp3_path}")
            result = subprocess.run([
                "ffmpeg", "-y",
                "-i", str(TEMP_WAV),
                "-acodec", "libmp3lame",
                "-b:a", "192k",
                mp3_path
            ], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

            if result.returncode == 0:
                self._log(f"✅ MP3 导出成功: {mp3_path}")
                messagebox.showinfo("完成", f"录音已保存为:\n{mp3_path}")
            else:
                raise RuntimeError(f"FFmpeg 错误:\n{result.stderr}")

        except Exception as e:
            self._log(f"MP3 转换失败: {e}", logging.ERROR)
            messagebox.showerror("转换失败", f"无法生成 MP3 文件:\n{e}")

        finally:
            # 清理临时文件
            if TEMP_WAV.exists():
                try:
                    TEMP_WAV.unlink()
                except Exception as e:
                    self._log(f"清理临时文件失败: {e}", logging.WARNING)
            self._reset_ui()

    def _reset_ui(self):
        self.record_btn.config(text="▶ 开始录制")
        self.status_var.set("就绪")


# ================== 启动程序 ==================
if __name__ == "__main__":
    # 检查必要依赖
    try:
        import pyaudio
    except ImportError:
        messagebox.showerror("依赖缺失", "请先安装 pyaudio:\n\npip install pyaudio")
        exit(1)

    root = tk.Tk()
    app = AudioRecorderApp(root)
    root.mainloop()
