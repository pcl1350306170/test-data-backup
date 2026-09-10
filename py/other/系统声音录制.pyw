# system_audio_recorder.pyw
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
import wave
import subprocess
import shutil

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "system_audio_recorder"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 日志配置（仅写入文件，不输出到控制台）
logging.basicConfig(
    filename=PROCESS_LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger()

# 默认参数
DEFAULT_CONFIG = {
    "export_dir": str(SCRIPT_DIR / "output"),
    "recording_duration": 60,
    "auto_split": True
}

CHANNELS = 2
RATE = 48000

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
    except Exception as e:
        logger.error(f"MP3转换失败: {e}")
        return False

def list_audio_devices():
    """列出所有音频设备"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            timeout=10
        )
        stderr_text = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ""
        
        # 提取设备列表的关键部分
        if stderr_text:
            lines = stderr_text.split('\n')
            device_lines = []
            capture = False
            for line in lines:
                if '[dshow' in line.lower() and ('audio' in line.lower() or 'video' in line.lower()):
                    capture = True
                if capture:
                    device_lines.append(line)
                if capture and line.strip() == '' and len(device_lines) > 5:
                    break
            
            if device_lines:
                return '\n'.join(device_lines)
        
        return stderr_text if stderr_text else "未找到音频设备或 FFmpeg 执行失败"
    except Exception as e:
        return f"获取设备列表失败: {str(e)}"

class SystemAudioRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("系统声音录制工具 - FFmpeg 版")
        self.root.geometry("750x600")
        self.root.minsize(700, 550)

        self.is_recording = False
        self.record_thread = None
        self.current_process = None

        self.export_dir = tk.StringVar()
        self.recording_duration = tk.IntVar()
        self.auto_split = tk.BooleanVar()

        self._create_widgets()
        self._load_config()

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        dir_frame = ttk.LabelFrame(main_frame, text="MP3 导出目录", padding="10")
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(dir_frame, textvariable=self.export_dir, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(dir_frame, text="浏览...", command=self._browse_export_dir).pack(side=tk.RIGHT)

        param_frame = ttk.LabelFrame(main_frame, text="录音参数设置", padding="10")
        param_frame.pack(fill=tk.X, pady=10)

        ttk.Label(param_frame, text="单次录音时长（秒）:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(param_frame, from_=10, to=300, increment=10, textvariable=self.recording_duration, width=10).grid(row=0, column=1, padx=10)

        ttk.Checkbutton(param_frame, text="到达时长后自动开始新录音", variable=self.auto_split).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=5)

        device_frame = ttk.LabelFrame(main_frame, text="音频设备信息", padding="10")
        device_frame.pack(fill=tk.X, pady=5)
        
        self.device_info_text = tk.Text(device_frame, wrap=tk.WORD, height=6, font=("Consolas", 9))
        self.device_info_text.pack(fill=tk.BOTH, expand=True)
        self.device_info_text.config(state=tk.DISABLED)
        
        ttk.Button(device_frame, text="刷新设备列表", command=self._refresh_devices).pack(anchor=tk.E, pady=5)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="▶ 开始录音", command=self._toggle_recording, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="📁 打开导出目录", command=self._open_export_dir).pack(side=tk.RIGHT, padx=5)

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
        self.recording_duration.set(config["recording_duration"])
        self.auto_split.set(config["auto_split"])
        self._log("配置加载成功")

    def _save_config(self):
        config = {
            "export_dir": self.export_dir.get(),
            "recording_duration": self.recording_duration.get(),
            "auto_split": self.auto_split.get()
        }
        try:
            CONFIG_PATH.parent.mkdir(exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存: {CONFIG_PATH}")
        except Exception as e:
            self._log(f"保存配置失败: {e}")
            messagebox.showerror("错误", f"无法保存配置:\n{e}")

    def _refresh_devices(self):
        self.device_info_text.config(state=tk.NORMAL)
        self.device_info_text.delete(1.0, tk.END)
        self._log("正在获取音频设备列表...")
        
        devices_info = list_audio_devices()
        
        if devices_info:
            self.device_info_text.insert(tk.END, devices_info)
        else:
            self.device_info_text.insert(tk.END, "未获取到设备信息")
        
        self.device_info_text.config(state=tk.DISABLED)
        self._log("设备列表已更新")

    def _toggle_recording(self):
        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        export_dir = self.export_dir.get().strip()
        if not export_dir:
            messagebox.showerror("错误", "请先设置导出目录！")
            return
        Path(export_dir).mkdir(exist_ok=True)

        try:
            ensure_ffmpeg()
        except EnvironmentError as e:
            messagebox.showerror("错误", str(e))
            return

        self.is_recording = True
        self.start_btn.config(text=" 停止录音")
        self._log("正在启动录音...")
        self.record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self.record_thread.start()

    def _stop_recording(self):
        self.is_recording = False
        if self.current_process:
            try:
                self.current_process.terminate()
            except:
                pass
        self.start_btn.config(text="▶ 开始录音")
        self._log("已停止录音")

    def _record_loop(self):
        try:
            while self.is_recording:
                export_dir = Path(self.export_dir.get())
                now = datetime.now()
                date_str = now.strftime("%Y年%m月%d日%H%M%S")
                rand_num = random.randint(1000, 9999)
                
                wav_path = SCRIPT_DIR / f"temp_{date_str}_{rand_num}.wav"
                mp3_path = export_dir / f"{date_str}-{rand_num}.mp3"
                
                duration = self.recording_duration.get()
                
                self._log(f"🎤 开始录音，时长: {duration}秒...")
                
                success, error_msg = self._record_with_wasapi(wav_path, duration)
                
                if success and self.is_recording:
                    self._log("正在转换为 MP3...")
                    if convert_wav_to_mp3(wav_path, mp3_path):
                        self._log(f"✅ 录音已保存: {mp3_path.name}")
                    else:
                        self._log("❌ MP3 转换失败")
                    
                    if wav_path.exists():
                        wav_path.unlink()
                    
                    if not self.auto_split.get():
                        break
                elif not self.is_recording:
                    if wav_path.exists():
                        wav_path.unlink()
                    break
                else:
                    self._log(f"❌ 录音失败: {error_msg}")
                    if wav_path.exists():
                        wav_path.unlink()
                    break
                    
        except Exception as e:
            self._log(f"录音过程中出错: {e}")
            logger.exception("详细错误信息:")
        finally:
            self.root.after(0, self._stop_recording)

    def _record_with_wasapi(self, output_wav, duration):
        """使用 VB-Cable 录制系统声音"""
        
        try:
            self._log("正在检测设备...")
            
            # 首先获取实际设备列表
            device_list_result = subprocess.run(
                ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                capture_output=True,
                text=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                timeout=10
            )
            
            device_info = device_list_result.stderr.decode('utf-8', errors='ignore')
            logger.debug(f"完整设备信息:\n{device_info}")
            
            # 解析所有音频设备
            import re
            audio_devices = []
            
            # 方法1: 查找 Alternative name
            alt_names = re.findall(r'Alternative name "(.*?)"', device_info)
            for name in alt_names:
                if any(keyword in name.lower() for keyword in ['cable', 'vb-audio', 'virtual', 'line']):
                    audio_devices.append(f"audio={name}")
                    self._log(f"找到 VB-Cable 设备: {name}")
            
            # 方法2: 查找所有 dshow audio 设备
            if not audio_devices:
                dshow_matches = re.findall(r'\[dshow.*?\] "(.*?)"', device_info)
                for name in dshow_matches:
                    if any(keyword in name.lower() for keyword in ['cable', 'vb', 'virtual', 'line', 'mix']):
                        audio_devices.append(f"audio={name}")
                        self._log(f"找到设备: {name}")
            
            # 如果还是没找到，使用第一个音频设备
            if not audio_devices:
                all_audio = re.findall(r'\[dshow.*?audio.*?\] "(.*?)"', device_info, re.IGNORECASE)
                if all_audio:
                    audio_devices.append(f"audio={all_audio[0]}")
                    self._log(f"使用第一个音频设备: {all_audio[0]}")
            
            if not audio_devices:
                self._log(" 未找到任何音频设备")
                self._log("请先点击'刷新设备列表'查看可用设备")
                return False, "未找到音频设备"
            
            # 尝试每个找到的设备
            for device_name in audio_devices:
                self._log(f"尝试使用设备: {device_name}")
                
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "dshow",
                    "-i", device_name,
                    "-t", str(duration),
                    "-acodec", "pcm_s16le",
                    "-ar", str(RATE),
                    "-ac", str(CHANNELS),
                    str(output_wav)
                ]
                
                logger.debug(f"执行命令: {' '.join(cmd)}")
                
                self.current_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                
                try:
                    # 等待5秒看是否能正常启动
                    time.sleep(5)
                    
                    if self.current_process.poll() is None:
                        # 进程还在运行，说明设备可用
                        self._log(f"✅ 设备 '{device_name}' 正常工作，继续录音...")
                        
                        # 等待录音完成
                        try:
                            stdout, stderr = self.current_process.communicate(timeout=duration)
                            if self.current_process.returncode == 0:
                                self._log("✅ 录制成功")
                                return True, ""
                        except subprocess.TimeoutExpired:
                            # 正常情况：录音还在进行
                            return True, ""
                    else:
                        # 进程已退出，获取错误信息
                        stdout, stderr = self.current_process.communicate()
                        error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "未知错误"
                        logger.warning(f"设备 '{device_name}' 失败: {error_msg[:300]}")
                        self._log(f"⚠️ 设备 '{device_name}' 不可用")
                        
                except Exception as e:
                    self.current_process.terminate()
                    logger.warning(f"设备 '{device_name}' 异常: {e}")
            
            self._log("❌ 所有设备均不可用")
            return False, "所有设备均不可用"
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"录制异常: {e}")
            logger.exception("详细堆栈:")
            return False, f"录制异常: {error_msg}"

if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        messagebox.showerror(
            "依赖缺失", 
            "请先安装 FFmpeg:\n\n"
            "1. 下载: https://ffmpeg.org/download.html\n"
            "2. 解压并将 bin 目录添加到系统 PATH\n"
            "3. 重启程序"
        )
        exit(1)

    messagebox.showinfo(
        "使用提示",
        "使用 VB-Cable 录制系统声音的步骤：\n\n"
        "1. 在 Windows 声音设置中：\n"
        "   - 播放设备选择 'CABLE Input (VB-Audio Virtual Cable)'\n"
        "   - 或通过 VB-Audio 控制面板设置\n\n"
        "2. 或者使用 Voicemeeter 等软件将声音路由到 VB-Cable\n\n"
        "3. 点击'开始录音'即可录制系统声音"
    )

    root = tk.Tk()
    app = SystemAudioRecorderApp(root)
    root.mainloop()