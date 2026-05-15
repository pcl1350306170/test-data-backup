# audiobook_video_generator.pyw
import os
import json
import logging
import threading
import shutil
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess

# 尝试导入 vlc 用于音频播放
try:
    import vlc
    HAS_VLC = True
except ImportError:
    HAS_VLC = False

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "audiobook_video_generator"
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
    "image_dir": "",
    "audio_path": "",
    "output_dir": str(SCRIPT_DIR / "output"),
    "video_name": "有声绘本",
    "fps": 8,  # 帧率，静态图片使用低帧率提升渲染速度
    "trim_start": 5.0,  # 裁剪开头秒数
    "trim_end": 5.0,  # 裁剪结尾秒数
    "timeline_file": "",  # 时间轴配置文件（可选）
    "use_interactive_mode": False  # 是否使用交互式时间轴编辑模式
}

# 支持的图片格式
SUPPORTED_IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}

# 图片最大分辨率（超过此尺寸会自动缩放）
MAX_IMAGE_SIZE = 1920  # 宽度不超过1920px

# ================== 工具函数 ==================
def ensure_ffmpeg():
    """检查 ffmpeg 是否可用"""
    if not shutil.which("ffmpeg"):
        raise EnvironmentError("未找到 ffmpeg，请安装并确保可在命令行中运行！")

def get_audio_duration(audio_path):
    """获取音频文件时长（秒）- 使用 moviepy"""
    try:
        # moviepy 2.x 使用新的导入方式
        try:
            from moviepy import AudioFileClip
        except ImportError:
            # 兼容 moviepy 1.x
            from moviepy.editor import AudioFileClip
        
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration
        audio_clip.close()
        return duration
    except Exception as e:
        raise Exception(f"无法获取音频时长: {e}")

def trim_audio_file(audio_path, trim_start, trim_end, log_callback=None):
    """裁剪音频文件，返回裁剪后的临时文件路径"""
    try:
        # moviepy 2.x 使用新的导入方式
        try:
            from moviepy import AudioFileClip
            is_moviepy_v2 = True
        except ImportError:
            # 兼容 moviepy 1.x
            from moviepy.editor import AudioFileClip
            is_moviepy_v2 = False
        
        if log_callback:
            log_callback(f"✂️ 正在裁剪音频（前{trim_start}秒，后{trim_end}秒）...")
        
        # 加载音频
        audio_clip = AudioFileClip(str(audio_path))
        original_duration = audio_clip.duration
        
        # 计算裁剪后的时长
        new_duration = original_duration - trim_start - trim_end
        
        if new_duration <= 0:
            audio_clip.close()
            raise Exception(f"裁剪时间过长！音频总时长{original_duration:.2f}秒，裁剪后剩余{new_duration:.2f}秒")
        
        # 裁剪音频（moviepy 2.x 和 1.x 的方式不同）
        if is_moviepy_v2:
            # moviepy 2.x: 使用切片语法 [start:end]
            trimmed_clip = audio_clip[trim_start:original_duration - trim_end]
        else:
            # moviepy 1.x: 使用 subclip 方法
            trimmed_clip = audio_clip.subclip(trim_start, original_duration - trim_end)
        
        # 保存为临时文件
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        trimmed_path = temp_dir / f"trimmed_{Path(audio_path).stem}_{int(time.time())}.mp3"
        
        if log_callback:
            log_callback(f"   原时长: {original_duration:.2f}秒 → 裁剪后: {new_duration:.2f}秒")
        
        # 导出裁剪后的音频
        trimmed_clip.write_audiofile(str(trimmed_path), codec='mp3', logger=None)
        
        # 清理
        trimmed_clip.close()
        audio_clip.close()
        
        if log_callback:
            log_callback(f"✅ 音频裁剪完成: {trimmed_path.name}")
        
        return str(trimmed_path), new_duration
        
    except Exception as e:
        raise Exception(f"音频裁剪失败: {str(e)}")

def get_sorted_images(image_dir):
    """获取排序后的图片列表"""
    image_dir = Path(image_dir)
    images = []
    
    for file in image_dir.iterdir():
        if file.is_file() and file.suffix.lower() in SUPPORTED_IMAGE_FORMATS:
            images.append(file)
    
    # 按文件名自然排序
    images.sort(key=lambda x: x.name)
    
    return images

def load_timeline(timeline_file, images):
    """加载时间轴配置文件，返回每张图片的时长列表"""
    if not timeline_file or not Path(timeline_file).exists():
        return None  # 使用时间轴
    
    try:
        with open(timeline_file, 'r', encoding='utf-8') as f:
            timeline_data = json.load(f)
        
        # 将图片名映射到时
        duration_map = {}
        for img_name, duration in timeline_data.items():
            duration_map[img_name] = float(duration)
        
        # 按图片顺序生成时长列表
        durations = []
        for img in images:
            if img.name in duration_map:
                durations.append(duration_map[img.name])
            else:
                # 如果配置中没有该图片，使用平均时长
                durations.append(None)
        
        return durations
        
    except Exception as e:
        print(f"警告: 无法加载时间轴文件: {e}")
        return None

def resize_image_if_needed(image_path, max_size=MAX_IMAGE_SIZE):
    """如果图片过大，则缩小并返回新路径；否则返回原路径"""
    try:
        from PIL import Image
        
        img = Image.open(str(image_path))
        width, height = img.size
        
        # 如果图片已经小于最大尺寸，直接返回原路径
        if width <= max_size and height <= max_size:
            # 即使是小图片，也要确保宽高是偶数
            if width % 2 == 0 and height % 2 == 0:
                return str(image_path), False
            else:
                # 需要调整到偶数
                new_width = width if width % 2 == 0 else width - 1
                new_height = height if height % 2 == 0 else height - 1
                img = img.crop((0, 0, new_width, new_height))
                
                import tempfile
                temp_dir = Path(tempfile.gettempdir())
                resized_path = temp_dir / f"resized_{Path(image_path).stem}_{int(time.time())}.jpg"
                
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                img.save(str(resized_path), 'JPEG', quality=85, optimize=True)
                img.close()
                
                return str(resized_path), True
        
        # 计算缩放比例
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
        
        # ✅ 确保宽高都是偶数（H.264 编码器要求）
        if new_width % 2 != 0:
            new_width -= 1
        if new_height % 2 != 0:
            new_height -= 1
        
        # 缩放图片
        img_resized = img.resize((new_width, new_height), Image.LANCZOS)
        
        # 保存到临时文件
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        resized_path = temp_dir / f"resized_{Path(image_path).stem}_{int(time.time())}.jpg"
        
        # 转换为RGB模式（处理PNG透明背景等问题）
        if img_resized.mode in ('RGBA', 'P'):
            img_resized = img_resized.convert('RGB')
        
        img_resized.save(str(resized_path), 'JPEG', quality=85, optimize=True)
        img.close()
        
        return str(resized_path), True
        
    except ImportError:
        # 如果没有PIL，返回原路径
        return str(image_path), False
    except Exception as e:
        # 如果处理失败，返回原路径
        print(f"警告: 无法处理图片 {image_path}: {e}")
        return str(image_path), False

# ================== 交互式时间轴编辑器 ==================
class InteractiveTimelineEditor:
    """交互式时间轴编辑器：播放音频，点击图片标记时间戳"""
    
    def __init__(self, parent, images, audio_path, log_callback=None):
        self.parent = parent
        self.images = images
        self.audio_path = audio_path
        self.log_callback = log_callback or (lambda msg: None)
        
        # 状态变量
        self.timestamps = []  # [(image_index, timestamp_seconds), ...]
        self.is_playing = False
        self.play_start_time = 0
        self.audio_duration = 0
        self.current_position = 0
        self.playback_rate = 1.0  # 播放倍速（1.0 = 正常速度）
        
        # 创建窗口 - 使用 parent.root 作为父窗口
        self.window = tk.Toplevel(parent.root)
        self.window.title("⏱️ 交互式时间轴编辑器")
        self.window.geometry("900x700")
        self.window.minsize(800, 600)
        
        # 初始化 vlc 播放器
        if HAS_VLC:
            self.vlc_instance = vlc.Instance()
            self.media_player = self.vlc_instance.media_player_new()
            media = self.vlc_instance.media_new(str(audio_path))
            self.media_player.set_media(media)
            
            # 获取音频时长
            try:
                from moviepy import AudioFileClip
            except ImportError:
                from moviepy.editor import AudioFileClip
            
            audio_clip = AudioFileClip(str(audio_path))
            self.audio_duration = audio_clip.duration
            audio_clip.close()
        
        self._create_widgets()
        self._load_thumbnails()
    
    def _create_widgets(self):
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === 音频控制区 ===
        control_frame = ttk.LabelFrame(main_frame, text="🔊 音频控制", padding="10")
        control_frame.pack(fill=tk.X, pady=5)
        
        btn_frame = ttk.Frame(control_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        self.play_btn = ttk.Button(btn_frame, text="▶️ 播放", command=self._toggle_play, width=10)
        self.play_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="⏹ 停止", command=self._stop, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="↩️ 撤销", command=self._undo, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 重置", command=self._reset, width=10).pack(side=tk.LEFT, padx=5)
        
        # 倍速控制
        speed_frame = ttk.Frame(control_frame)
        speed_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(speed_frame, text="播放倍速:").pack(side=tk.LEFT, padx=(0, 10))
        
        self.speed_var = tk.DoubleVar(value=1.0)
        speed_combo = ttk.Combobox(
            speed_frame,
            textvariable=self.speed_var,
            values=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
            width=8,
            state="readonly"
        )
        speed_combo.pack(side=tk.LEFT, padx=5)
        speed_combo.bind('<<ComboboxSelected>>', lambda e: self._change_speed())
        
        ttk.Label(speed_frame, text="x  (加快标记速度)", foreground="gray").pack(side=tk.LEFT)
        
        # 进度显示
        progress_frame = ttk.Frame(control_frame)
        progress_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(progress_frame, text="当前时间:").pack(side=tk.LEFT)
        self.time_label = ttk.Label(progress_frame, text="00:00.0 / 00:00.0", font=("Consolas", 12))
        self.time_label.pack(side=tk.LEFT, padx=10)
        
        # 进度条
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # === 图片展示区 ===
        image_frame = ttk.LabelFrame(main_frame, text="📸 点击图片标记时间戳（按顺序点击）", padding="10")
        image_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 创建可滚动的图片网格
        canvas_frame = ttk.Frame(image_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(canvas_frame)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.image_buttons = []
        self.thumbnail_images = []  # 保持引用防止被垃圾回收
        self.scrollable_frame = scrollable_frame
        
        # === 时间轴预览区 ===
        timeline_frame = ttk.LabelFrame(main_frame, text="⏱️ 时间轴预览", padding="10")
        timeline_frame.pack(fill=tk.X, pady=5)
        
        self.timeline_text = scrolledtext.ScrolledText(timeline_frame, height=8, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9))
        self.timeline_text.pack(fill=tk.BOTH, expand=True)
        
        # === 底部按钮 ===
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(bottom_frame, text="💾 保存时间轴", command=self._save_timeline).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="❌ 关闭", command=self._close).pack(side=tk.RIGHT, padx=5)
        
        # 绑定键盘快捷键
        self.window.bind('<space>', lambda e: self._toggle_play())
        self.window.bind('<Control-z>', lambda e: self._undo())
        self.window.bind('<Escape>', lambda e: self._close())
        
        # 启动进度更新循环
        self._update_progress()
    
    def _load_thumbnails(self):
        """加载图片缩略图"""
        try:
            from PIL import Image, ImageTk
            
            thumb_size = (150, 100)
            
            for i, img_path in enumerate(self.images):
                try:
                    # 加载并缩放图片
                    img = Image.open(str(img_path))
                    img.thumbnail(thumb_size, Image.LANCZOS)
                    
                    # 转换为 RGB（处理 PNG 透明背景）
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    
                    # 转换为 Tkinter 可用的格式
                    photo = ImageTk.PhotoImage(img)
                    self.thumbnail_images.append(photo)
                    
                    # 创建按钮
                    btn_frame = ttk.Frame(self.scrollable_frame)
                    btn_frame.grid(row=i//4, column=i%4, padx=5, pady=5, sticky="nsew")
                    
                    btn = ttk.Button(btn_frame, image=photo, command=lambda idx=i: self._mark_timestamp(idx))
                    btn.pack(pady=2)
                    
                    label = ttk.Label(btn_frame, text=f"{img_path.name}\n未标记", font=("Arial", 8), foreground="gray")
                    label.pack()
                    
                    self.image_buttons.append({
                        'button': btn,
                        'label': label,
                        'index': i,
                        'marked': False
                    })
                    
                except Exception as e:
                    print(f"警告: 无法加载缩略图 {img_path}: {e}")
            
            # 配置网格列权重
            for col in range(4):
                self.scrollable_frame.grid_columnconfigure(col, weight=1)
                
        except ImportError:
            messagebox.showerror("错误", "需要安装 Pillow 库来显示缩略图\n请运行: pip install Pillow")
            self._close()
    
    def _toggle_play(self):
        """切换播放/暂停"""
        if not HAS_VLC:
            messagebox.showerror("错误", "未安装 python-vlc 库\n请运行: pip install python-vlc")
            return
        
        if self.is_playing:
            self._pause()
        else:
            self._play()
    
    def _play(self):
        """开始播放"""
        if not HAS_VLC:
            return
        
        # 设置播放倍速
        try:
            self.media_player.set_rate(self.playback_rate)
        except Exception:
            pass  # 某些 VLC 版本可能不支持
        
        self.media_player.play()
        self.is_playing = True
        self.play_start_time = time.time() - self.current_position
        self.play_btn.config(text="⏸ 暂停")
        self.log_callback(f"▶️ 开始播放音频 ({self.playback_rate}x)")
    
    def _pause(self):
        """暂停播放"""
        if not HAS_VLC:
            return
        
        self.media_player.pause()
        self.is_playing = False
        self.current_position = time.time() - self.play_start_time
        self.play_btn.config(text="▶️ 播放")
        self.log_callback("⏸ 暂停播放")
    
    def _stop(self):
        """停止播放"""
        if not HAS_VLC:
            return
        
        self.media_player.stop()
        self.is_playing = False
        self.current_position = 0
        self.play_btn.config(text="▶️ 播放")
        self.progress_var.set(0)
        self.time_label.config(text="00:00.0 / 00:00.0")
        self.log_callback("⏹ 停止播放")
    
    def _change_speed(self):
        """改变播放倍速"""
        new_speed = self.speed_var.get()
        old_speed = self.playback_rate
        self.playback_rate = new_speed
        
        # 如果正在播放，立即应用新速度
        if self.is_playing and HAS_VLC:
            try:
                self.media_player.set_rate(new_speed)
            except Exception:
                pass
        
        self.log_callback(f"⚡ 播放速度: {old_speed}x → {new_speed}x")
    
    def _get_current_position(self):
        """获取当前播放位置（秒）"""
        if HAS_VLC and self.media_player.is_playing():
            # VLC 返回毫秒，转换为秒
            return self.media_player.get_time() / 1000.0
        else:
            return self.current_position
    
    def _update_progress(self):
        """更新进度条和时间显示"""
        current = self._get_current_position()
        
        if self.audio_duration > 0:
            progress = (current / self.audio_duration) * 100
            self.progress_var.set(min(progress, 100))
        
        # 格式化时间显示
        current_min = int(current // 60)
        current_sec = current % 60
        total_min = int(self.audio_duration // 60)
        total_sec = self.audio_duration % 60
        
        self.time_label.config(text=f"{current_min:02d}:{current_sec:04.1f} / {total_min:02d}:{total_sec:04.1f}")
        
        # 每 100ms 更新一次
        self.window.after(100, self._update_progress)
    
    def _mark_timestamp(self, image_index):
        """标记时间戳"""
        current_time = self._get_current_position()
        
        # 检查是否按顺序点击
        expected_index = len(self.timestamps)
        if image_index != expected_index:
            messagebox.showwarning(
                "顺序错误",
                f"请按顺序点击！\n\n应该点击第 {expected_index + 1} 张图片\n你点击了第 {image_index + 1} 张"
            )
            return
        
        # 记录时间戳
        self.timestamps.append((image_index, current_time))
        
        # 更新 UI
        btn_info = self.image_buttons[image_index]
        btn_info['marked'] = True
        btn_info['button'].config(style="Accent.TButton")
        
        # 计算上一张图片的时长
        if len(self.timestamps) >= 2:
            prev_idx, prev_time = self.timestamps[-2]
            duration = current_time - prev_time
            btn_info['label'].config(
                text=f"{self.images[image_index].name}\n{prev_time:.1f}s-{current_time:.1f}s\n({duration:.1f}s)",
                foreground="green"
            )
        else:
            btn_info['label'].config(
                text=f"{self.images[image_index].name}\n从 {current_time:.1f}s 开始",
                foreground="blue"
            )
        
        self.log_callback(f"✅ 标记第 {image_index + 1} 页: {self.images[image_index].name} @ {current_time:.1f}s")
        
        # 更新时间轴预览
        self._update_timeline_preview()
        
        # 检查是否完成所有图片
        if len(self.timestamps) == len(self.images):
            messagebox.showinfo(
                "完成",
                f"已标记所有 {len(self.images)} 张图片！\n\n请点击'保存时间轴'生成 JSON 文件"
            )
    
    def _undo(self):
        """撤销最后一个标记"""
        if not self.timestamps:
            messagebox.showinfo("提示", "没有可以撤销的标记")
            return
        
        last_idx, last_time = self.timestamps.pop()
        
        # 重置 UI
        btn_info = self.image_buttons[last_idx]
        btn_info['marked'] = False
        btn_info['button'].config(style="TButton")
        btn_info['label'].config(
            text=f"{self.images[last_idx].name}\n未标记",
            foreground="gray"
        )
        
        self.log_callback(f"↩️ 撤销第 {last_idx + 1} 页的标记")
        self._update_timeline_preview()
    
    def _reset(self):
        """重置所有标记"""
        if not self.timestamps:
            return
        
        if messagebox.askyesno("确认", "确定要重置所有标记吗？"):
            self.timestamps.clear()
            
            for btn_info in self.image_buttons:
                btn_info['marked'] = False
                btn_info['button'].config(style="TButton")
                btn_info['label'].config(
                    text=f"{self.images[btn_info['index']].name}\n未标记",
                    foreground="gray"
                )
            
            self.log_callback("🔄 已重置所有标记")
            self._update_timeline_preview()
    
    def _update_timeline_preview(self):
        """更新时间轴预览文本"""
        self.timeline_text.config(state=tk.NORMAL)
        self.timeline_text.delete(1.0, tk.END)
        
        if not self.timestamps:
            self.timeline_text.insert(tk.END, "尚未标记任何图片...\n\n操作说明：\n1. 点击'播放'开始播放音频\n2. 听到每页内容结束时，点击对应图片\n3. 按顺序从左到右、从上到下点击\n4. 完成后点击'保存时间轴'")
        else:
            for i, (idx, start_time) in enumerate(self.timestamps):
                if i < len(self.timestamps) - 1:
                    end_time = self.timestamps[i + 1][1]
                    duration = end_time - start_time
                    self.timeline_text.insert(tk.END, f"{i+1:3d}. {self.images[idx].name:20s} | {start_time:6.1f}s - {end_time:6.1f}s | {duration:5.1f}s ✅\n")
                else:
                    self.timeline_text.insert(tk.END, f"{i+1:3d}. {self.images[idx].name:20s} | {start_time:6.1f}s - ???     | 等待下一页... ⏳\n")
            
            # 显示统计信息
            marked_count = len(self.timestamps)
            total_count = len(self.images)
            self.timeline_text.insert(tk.END, f"\n{'='*60}\n")
            self.timeline_text.insert(tk.END, f"已标记: {marked_count}/{total_count} 页")
            
            if marked_count == total_count:
                self.timeline_text.insert(tk.END, " ✅ 全部完成！")
        
        self.timeline_text.config(state=tk.DISABLED)
    
    def _save_timeline(self):
        """保存时间轴为 JSON 文件"""
        if not self.timestamps:
            messagebox.showwarning("警告", "尚未标记任何图片！")
            return
        
        if len(self.timestamps) < len(self.images):
            if not messagebox.askyesno(
                "确认",
                f"只标记了 {len(self.timestamps)}/{len(self.images)} 页\n\n未标记的页面将使用平均时长，是否继续？"
            ):
                return
        
        # 生成时间轴数据
        timeline = {}
        
        for i, (idx, start_time) in enumerate(self.timestamps):
            img_name = self.images[idx].name
            
            if i < len(self.timestamps) - 1:
                # 有下一张标记的图片
                end_time = self.timestamps[i + 1][1]
                duration = end_time - start_time
            else:
                # 最后一张标记的图片
                if len(self.timestamps) == len(self.images):
                    # 所有图片都标记了，使用剩余音频时长
                    duration = self.audio_duration - start_time
                else:
                    # 还有未标记的图片，计算平均时长
                    remaining_time = self.audio_duration - start_time
                    remaining_images = len(self.images) - len(self.timestamps)
                    duration = remaining_time / (remaining_images + 1)
            
            timeline[img_name] = round(duration, 2)
        
        # 为未标记的图片分配平均时长
        if len(self.timestamps) < len(self.images):
            marked_end_time = self.timestamps[-1][1] if self.timestamps else 0
            remaining_time = self.audio_duration - marked_end_time
            unmarked_count = len(self.images) - len(self.timestamps)
            avg_duration = remaining_time / unmarked_count if unmarked_count > 0 else 0
            
            for i, img in enumerate(self.images):
                if img.name not in timeline:
                    timeline[img.name] = round(avg_duration, 2)
        
        # 保存到文件
        default_path = Path(self.audio_path).parent / "timeline.json"
        save_path = filedialog.asksaveasfilename(
            title="保存时间轴文件",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=default_path.name,
            initialdir=str(default_path.parent)
        )
        
        if save_path:
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    json.dump(timeline, f, ensure_ascii=False, indent=2)
                
                self.log_callback(f"💾 时间轴已保存: {Path(save_path).name}")
                messagebox.showinfo("成功", f"时间轴已保存:\n{save_path}")
                
                # 自动设置到主窗口的时间轴文件路径
                if hasattr(self.parent, 'timeline_file'):
                    self.parent.timeline_file.set(save_path)
                
            except Exception as e:
                messagebox.showerror("错误", f"保存失败:\n{e}")
    
    def _close(self):
        """关闭窗口"""
        if HAS_VLC:
            self.media_player.stop()
            self.media_player.release()
            self.vlc_instance.release()
        self.window.destroy()

def generate_video_with_moviepy(images, audio_path, output_path, fps, log_callback, timeline_file=None):
    """使用 moviepy 生成视频"""
    try:
        # moviepy 2.x 使用新的导入方式
        try:
            from moviepy import ImageClip, concatenate_videoclips, AudioFileClip
        except ImportError:
            # 兼容 moviepy 1.x
            from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip
        
        log_callback("正在加载图片和音频...")
        
        # 获取音频时长和创建音频片段
        audio_clip = AudioFileClip(str(audio_path))
        audio_duration = audio_clip.duration
        
        # 计算每张图片的展示时长
        num_images = len(images)
        
        # 检查是否使用时间轴配置
        use_timeline = False
        image_durations = None
        
        if timeline_file:
            image_durations = load_timeline(timeline_file, images)
            if image_durations:
                # 检查是否有 None 值（配置中缺少的图片）
                missing_count = image_durations.count(None)
                if missing_count == 0:
                    use_timeline = True
                    log_callback(f"✅ 已加载时间轴配置（{len(image_durations)} 页）")
                else:
                    log_callback(f"⚠️ 时间轴配置不完整（缺少 {missing_count} 页），将使用平均时长")
                    image_durations = None
            else:
                log_callback(f"⚠️ 无法加载时间轴文件，使用平均时长")
        
        if not use_timeline:
            duration_per_image = audio_duration / num_images
        
        log_callback(f" 统计信息:")
        log_callback(f"   - 图片数量: {num_images} 张")
        log_callback(f"   - 音频时长: {audio_duration:.2f} 秒")
        if use_timeline:
            log_callback(f"   - ⏱️ 使用时间轴配置（每页独立时长）")
        else:
            log_callback(f"   - 单图展示时长: {duration_per_image:.2f} 秒")
        log_callback(f"   - 视频帧率: {fps} fps")
        
        # 估算渲染时间
        estimated_time = audio_duration * 0.5  # 粗略估算：每秒音频需要 0.5 秒渲染
        if estimated_time > 60:
            log_callback(f"   ⚠️ 预计渲染时间: {estimated_time/60:.1f} 分钟")
        else:
            log_callback(f"   ⚠️ 预计渲染时间: {estimated_time:.0f} 秒")
        
        # 创建图片视频片段
        log_callback("正在创建视频片段...")
        clips = []
        resized_count = 0
        original_paths = []  # 跟踪需要清理的临时文件
        
        for i, img_path in enumerate(images, 1):
            log_callback(f"   处理图片 {i}/{num_images}: {img_path.name}")
            
            # 检查并压缩图片（如果需要）
            processed_path, was_resized = resize_image_if_needed(img_path)
            if was_resized:
                resized_count += 1
                original_paths.append(processed_path)
            
            # 确定当前图片的展示时长
            if use_timeline and image_durations[i-1] is not None:
                current_duration = image_durations[i-1]
            else:
                current_duration = duration_per_image
            
            # moviepy 2.x 和 1.x 的 ImageClip 创建方式不同
            try:
                # moviepy 2.x: 直接在构造函数中设置 fps
                clip = ImageClip(processed_path, duration=current_duration).with_fps(fps)
            except AttributeError:
                # moviepy 1.x: 使用 set_fps 方法
                clip = ImageClip(processed_path, duration=current_duration)
                clip = clip.set_fps(fps)
            
            clips.append(clip)
        
        if resized_count > 0:
            log_callback(f"✅ 已压缩 {resized_count} 张图片以加速渲染")
        
        # 拼接所有片段
        log_callback("正在拼接视频片段...")
        video_clip = concatenate_videoclips(clips, method="compose")
        
        # 添加音频
        log_callback("正在合成音频轨道...")
        try:
            # moviepy 2.x: 使用 with_audio 方法
            final_clip = video_clip.with_audio(audio_clip)
        except AttributeError:
            # moviepy 1.x: 使用 set_audio 方法
            final_clip = video_clip.set_audio(audio_clip)
        
        # 导出视频
        log_callback(f"正在渲染视频 (这可能需要几分钟)...")
                
        # 使用兼容性更好的导出参数
        try:
            final_clip.write_videofile(
                str(output_path),
                fps=fps,
                codec='libx264',  # H.264 编码，兼容性最好
                audio_codec='aac',  # AAC 音频编码
                preset='medium',  # 使用 medium 预设（比 ultrafast 更兼容）
                threads=4,
                bitrate='2000k',
                ffmpeg_params=[
                    '-profile:v', 'baseline',  # H.264 baseline profile，兼容性最佳
                    '-level', '3.0',  # Level 3.0 支持大多数设备
                    '-pix_fmt', 'yuv420p',  # 标准像素格式
                    '-movflags', '+faststart'  # 优化网络播放
                ],
                logger='bar' if hasattr(final_clip, 'iter_frames') else None
            )
        except Exception as render_error:
            log_callback(f"⚠️ 标准渲染失败，尝试备用方案... {render_error}")
            # 备用方案：使用更基础的参数
            final_clip.write_videofile(
                str(output_path),
                fps=fps,
                codec='libx264',
                audio_codec='aac',
                preset='medium',
                threads=2,
                bitrate='1500k',
                ffmpeg_params=[
                    '-profile:v', 'baseline',
                    '-level', '3.0',
                    '-pix_fmt', 'yuv420p'
                ]
            )
        
        # 清理
        final_clip.close()
        audio_clip.close()
        for clip in clips:
            clip.close()
        
        # 清理临时压缩的图片文件
        for temp_path in original_paths:
            try:
                Path(temp_path).unlink()
            except Exception:
                pass
        
        log_callback("✅ 视频生成完成！")
        return True
        
    except Exception as e:
        raise Exception(f"视频生成失败: {str(e)}")

# ================== 主应用类 ==================
class AudiobookVideoGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("有声绘本视频生成工具")
        self.root.geometry("750x600")
        self.root.minsize(700, 550)

        # 状态
        self.is_generating = False

        # 配置变量（绑定到 UI）
        self.image_dir = tk.StringVar()
        self.audio_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.video_name = tk.StringVar()
        self.fps = tk.IntVar()
        self.trim_start = tk.DoubleVar()
        self.trim_end = tk.DoubleVar()
        self.timeline_file = tk.StringVar()

        # 创建 UI
        self._create_widgets()
        self._load_config()

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 素材路径选择 ===
        input_frame = ttk.LabelFrame(main_frame, text="📁 素材路径设置", padding="10")
        input_frame.pack(fill=tk.X, pady=5)

        # 图片文件夹
        ttk.Label(input_frame, text="图片文件夹:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.image_dir, width=55).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(input_frame, text="浏览...", command=self._browse_image_dir).grid(row=0, column=2, pady=5)

        # 音频文件
        ttk.Label(input_frame, text="音频文件:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.audio_path, width=55).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(input_frame, text="浏览...", command=self._browse_audio_file).grid(row=1, column=2, pady=5)

        # === 输出设置 ===
        output_frame = ttk.LabelFrame(main_frame, text="💾 输出设置", padding="10")
        output_frame.pack(fill=tk.X, pady=5)

        # 输出目录
        ttk.Label(output_frame, text="输出目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(output_frame, textvariable=self.output_dir, width=55).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(output_frame, text="浏览...", command=self._browse_output_dir).grid(row=0, column=2, pady=5)

        # 视频名称
        ttk.Label(output_frame, text="视频名称:").grid(row=1, column=0, sticky=tk.W, pady=5)
        name_entry = ttk.Entry(output_frame, textvariable=self.video_name, width=55)
        name_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Label(output_frame, text=".mp4").grid(row=1, column=2, sticky=tk.W, pady=5)

        # 帧率设置
        ttk.Label(output_frame, text="视频帧率:").grid(row=2, column=0, sticky=tk.W, pady=5)
        fps_combo = ttk.Combobox(output_frame, textvariable=self.fps, values=[4, 8, 12, 15, 24], width=10, state="readonly")
        fps_combo.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(output_frame, text="fps（静态图片推荐 4-8 fps）", foreground="gray").grid(row=2, column=2, sticky=tk.W, pady=5)

        # 音频裁剪设置
        trim_frame = ttk.Frame(output_frame)
        trim_frame.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=5)
        ttk.Label(trim_frame, text="音频裁剪:").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(trim_frame, text="开头:").pack(side=tk.LEFT)
        ttk.Spinbox(trim_frame, from_=0, to=60, increment=0.5, textvariable=self.trim_start, width=8, format="%.1f").pack(side=tk.LEFT, padx=5)
        ttk.Label(trim_frame, text="秒  |  结尾:").pack(side=tk.LEFT)
        ttk.Spinbox(trim_frame, from_=0, to=60, increment=0.5, textvariable=self.trim_end, width=8, format="%.1f").pack(side=tk.LEFT, padx=5)
        ttk.Label(trim_frame, text="秒", foreground="gray").pack(side=tk.LEFT)

        # 时间轴配置文件
        timeline_frame = ttk.Frame(output_frame)
        timeline_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=5)
        ttk.Label(timeline_frame, text="时间轴:").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Entry(timeline_frame, textvariable=self.timeline_file, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Button(timeline_frame, text="浏览...", command=self._browse_timeline_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(timeline_frame, text="创建模板", command=self._create_timeline_template).pack(side=tk.LEFT)
        
        # 交互式编辑器按钮
        interactive_btn = ttk.Button(
            timeline_frame,
            text="🎯 交互式编辑",
            command=self._open_interactive_editor,
            style="Accent.TButton"
        )
        interactive_btn.pack(side=tk.LEFT, padx=10)

        # === 控制按钮 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        self.generate_btn = ttk.Button(btn_frame, text="🎬 开始生成视频", command=self._start_generation, style="Accent.TButton")
        self.generate_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="📁 打开输出目录", command=self._open_output_dir).pack(side=tk.RIGHT, padx=5)

        # === 日志区域 ===
        log_frame = ttk.LabelFrame(main_frame, text="📝 生成日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, message):
        """记录日志并更新 UI"""
        logger.info(message)
        def update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, update)

    def _browse_image_dir(self):
        """选择图片文件夹"""
        path = filedialog.askdirectory(title="选择图片文件夹")
        if path:
            self.image_dir.set(path)
            self._log(f"图片文件夹设为: {path}")

    def _browse_audio_file(self):
        """选择音频文件"""
        path = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.flac *.aac *.ogg"),
                ("All files", "*.*")
            ]
        )
        if path:
            self.audio_path.set(path)
            self._log(f"音频文件设为: {Path(path).name}")

    def _browse_output_dir(self):
        """选择输出目录"""
        path = filedialog.askdirectory(title="选择视频输出目录")
        if path:
            self.output_dir.set(path)
            self._log(f"输出目录设为: {path}")

    def _browse_timeline_file(self):
        """选择时间轴配置文件"""
        path = filedialog.askopenfilename(
            title="选择时间轴配置文件",
            filetypes=[
                ("JSON files", "*.json"),
                ("All files", "*.*")
            ]
        )
        if path:
            self.timeline_file.set(path)
            self._log(f"时间轴文件设为: {Path(path).name}")

    def _create_timeline_template(self):
        """创建时间轴配置模板"""
        image_dir = self.image_dir.get().strip()
        if not image_dir or not Path(image_dir).exists():
            messagebox.showwarning("警告", "请先选择图片文件夹！")
            return
        
        images = get_sorted_images(image_dir)
        if len(images) == 0:
            messagebox.showwarning("警告", "图片文件夹为空！")
            return
        
        # 创建模板
        template = {}
        for img in images:
            template[img.name] = 10.0  # 默认每页 10 秒
        
        # 保存到图片文件夹
        output_path = Path(image_dir) / "timeline_template.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        
        self.timeline_file.set(str(output_path))
        messagebox.showinfo("成功", f"已创建时间轴模板:\n{output_path}\n\n请编辑该文件，设置每页的展示时长（秒）")
        self._log(f"✅ 时间轴模板已创建: {output_path.name}")
    
    def _open_interactive_editor(self):
        """打开交互式时间轴编辑器"""
        # 检查 vlc 是否可用
        if not HAS_VLC:
            messagebox.showerror(
                "依赖缺失",
                "交互式编辑器需要 python-vlc 库\n\n请运行以下命令安装:\npip install python-vlc\n\n注意：还需要安装 VLC 播放器软件"
            )
            return
        
        # 验证必要参数
        image_dir = self.image_dir.get().strip()
        audio_path = self.audio_path.get().strip()
        
        if not image_dir or not Path(image_dir).exists():
            messagebox.showwarning("警告", "请先选择图片文件夹！")
            return
        
        if not audio_path or not Path(audio_path).exists():
            messagebox.showwarning("警告", "请先选择音频文件！")
            return
        
        # 获取图片列表
        images = get_sorted_images(image_dir)
        if len(images) == 0:
            messagebox.showwarning("警告", "图片文件夹内没有支持的图片文件！")
            return
        
        self._log("🎯 打开交互式时间轴编辑器...")
        
        # 创建编辑器窗口
        editor = InteractiveTimelineEditor(
            self,
            images,
            audio_path,
            log_callback=lambda msg: self._log(msg)
        )

    def _open_output_dir(self):
        """打开输出目录"""
        output_path = self.output_dir.get().strip()
        if not output_path or not os.path.exists(output_path):
            messagebox.showwarning("警告", "输出目录不存在！")
            return
        try:
            os.startfile(output_path)
        except Exception:
            import subprocess
            subprocess.call(["open", output_path]) if os.name == 'posix' else subprocess.call(["xdg-open", output_path])

    def _load_config(self):
        """加载配置"""
        config = DEFAULT_CONFIG.copy()
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    config.update(saved)
            except Exception as e:
                self._log(f"加载配置失败: {e}")
        
        self.image_dir.set(config["image_dir"])
        self.audio_path.set(config["audio_path"])
        self.output_dir.set(config["output_dir"])
        self.video_name.set(config["video_name"])
        self.fps.set(config["fps"])
        self.trim_start.set(config.get("trim_start", 5.0))
        self.trim_end.set(config.get("trim_end", 5.0))
        self.timeline_file.set(config.get("timeline_file", ""))
        self._log("✅ 配置加载成功")
        
        # 检查 vlc 可用性
        if not HAS_VLC:
            self._log("⚠️ 未检测到 python-vlc，交互式编辑器将不可用")
            self._log("   安装命令: pip install python-vlc")
            self._log("   注意：还需要安装 VLC 播放器软件")

    def _save_config(self):
        """保存配置"""
        config = {
            "image_dir": self.image_dir.get(),
            "audio_path": self.audio_path.get(),
            "output_dir": self.output_dir.get(),
            "video_name": self.video_name.get(),
            "fps": self.fps.get(),
            "trim_start": round(self.trim_start.get(), 1),
            "trim_end": round(self.trim_end.get(), 1),
            "timeline_file": self.timeline_file.get(),
            "use_interactive_mode": False
        }
        try:
            CONFIG_PATH.parent.mkdir(exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log(f"✅ 配置已保存: {CONFIG_PATH}")
        except Exception as e:
            self._log(f"❌ 保存配置失败: {e}")
            messagebox.showerror("错误", f"无法保存配置:\n{e}")

    def _validate_inputs(self):
        """验证输入参数"""
        errors = []
        
        # 检查图片文件夹
        image_dir = self.image_dir.get().strip()
        if not image_dir:
            errors.append("请选择图片文件夹")
        elif not Path(image_dir).exists():
            errors.append("图片文件夹不存在")
        else:
            images = get_sorted_images(image_dir)
            if len(images) == 0:
                errors.append("图片文件夹内没有支持的图片文件")
        
        # 检查音频文件
        audio_path = self.audio_path.get().strip()
        if not audio_path:
            errors.append("请选择音频文件")
        elif not Path(audio_path).exists():
            errors.append("音频文件不存在")
        
        # 检查输出目录
        output_dir = self.output_dir.get().strip()
        if not output_dir:
            errors.append("请选择输出目录")
        else:
            Path(output_dir).mkdir(exist_ok=True)
        
        # 检查视频名称
        video_name = self.video_name.get().strip()
        if not video_name:
            errors.append("请输入视频名称")
        
        if errors:
            error_msg = "❌ 配置错误:\n\n" + "\n".join(f"• {err}" for err in errors)
            messagebox.showerror("配置错误", error_msg)
            return False
        
        return True

    def _start_generation(self):
        """开始生成视频"""
        if self.is_generating:
            messagebox.showwarning("提示", "视频正在生成中，请稍候...")
            return
        
        # 验证输入
        if not self._validate_inputs():
            return
        
        # 启动生成线程
        self.is_generating = True
        self.generate_btn.config(text="⏳ 生成中...", state=tk.DISABLED)
        self._log("🚀 开始生成视频...")
        
        thread = threading.Thread(target=self._generate_video_thread, daemon=True)
        thread.start()

    def _generate_video_thread(self):
        """在后台线程中生成视频"""
        trimmed_audio_path = None  # 用于跟踪临时文件
        try:
            # 获取参数
            image_dir = self.image_dir.get().strip()
            audio_path = self.audio_path.get().strip()
            output_dir = self.output_dir.get().strip()
            video_name = self.video_name.get().strip()
            fps = self.fps.get()
            trim_start = self.trim_start.get()
            trim_end = self.trim_end.get()
            timeline_file = self.timeline_file.get().strip()
            
            # 获取图片列表
            images = get_sorted_images(image_dir)
            self._log(f"📸 找到 {len(images)} 张图片")
            
            # 检查是否需要裁剪音频
            effective_audio_path = audio_path
            if trim_start > 0 or trim_end > 0:
                try:
                    trimmed_audio_path, audio_duration = trim_audio_file(
                        audio_path, trim_start, trim_end,
                        lambda msg: self._log(msg)
                    )
                    effective_audio_path = trimmed_audio_path
                    self._log(f"   裁剪后音频时长: {audio_duration:.2f} 秒")
                except Exception as e:
                    self._log(f"⚠️ 音频裁剪失败，使用原始音频: {e}")
                    # 如果裁剪失败，使用原始音频
                    self._log("🔊 读取原始音频文件...")
                    audio_duration = get_audio_duration(audio_path)
                    self._log(f"   音频时长: {audio_duration:.2f} 秒")
            else:
                # 不需要裁剪
                self._log("🔊 读取音频文件...")
                audio_duration = get_audio_duration(audio_path)
                self._log(f"   音频时长: {audio_duration:.2f} 秒")
            
            # 计算输出路径
            output_path = Path(output_dir) / f"{video_name}.mp4"
            
            # 生成视频
            success = generate_video_with_moviepy(
                images, effective_audio_path, output_path, fps,
                lambda msg: self._log(msg),
                timeline_file if timeline_file and Path(timeline_file).exists() else None
            )
            
            if success:
                self._log(f"✅ 视频已保存: {output_path.name}")
                self._log(f"📂 位置: {output_path}")
                
                # 自动打开输出目录
                self.root.after(0, lambda: self._open_output_dir())
                self.root.after(0, lambda: messagebox.showinfo("成功", f"视频生成完成！\n\n{output_path.name}"))
            else:
                self._log("❌ 视频生成失败")
                self.root.after(0, lambda: messagebox.showerror("错误", "视频生成失败，请查看日志"))
        
        except Exception as e:
            error_msg = f"生成过程出错: {str(e)}"
            self._log(f"❌ {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("错误", error_msg))
        
        finally:
            # 清理临时裁剪的音频文件
            if trimmed_audio_path and Path(trimmed_audio_path).exists():
                try:
                    Path(trimmed_audio_path).unlink()
                    self._log(f"🗑️ 已清理临时音频文件")
                except Exception:
                    pass
            
            self.is_generating = False
            self.root.after(0, lambda: self.generate_btn.config(text="🎬 开始生成视频", state=tk.NORMAL))

# ================== 启动程序 ==================
if __name__ == "__main__":
    try:
        import shutil
    except ImportError:
        messagebox.showerror("依赖缺失", "Python 标准库异常，请检查 Python 环境")
        exit(1)

    root = tk.Tk()
    app = AudiobookVideoGeneratorApp(root)
    root.mainloop()
