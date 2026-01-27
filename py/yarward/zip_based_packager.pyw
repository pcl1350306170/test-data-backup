# zip_based_packager.pyw

import os
import subprocess
import json
import platform
import zipfile
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import logging
from datetime import datetime
import threading
import re

# ================== 尝试导入 pypinyin ==================
try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False
    print("警告：未安装 pypinyin，医院名拼音首字母将使用简化逻辑")

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "zip_based_packager"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)
DB_CONFIG_PATH = (SCRIPT_DIR.parent) / "json" / "DB_CONFIG.json"
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

# 默认配置
DEFAULT_CONFIG = {
    "project_dir": r"C:\www\yh\门诊\template1.5.0",
    "output_dir": r"D:\yarward\svn\2025-1987南昌市立医院新院区\前端",
    "order_info": "2025-1987南昌市立医院新院区",
    "project_version": "1.5.1",
    "base_zip_path": r"C:\www\test\门诊\801S-订单\前端\1.5.1.zip",
    "custom_zip_name": ""  # ← 新增：自定义ZIP名称
}

class ZipBasedPackagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📦 基于压缩包的打包工具")
        self.root.geometry("900x750")
        self.root.minsize(800, 750)

        # 初始化变量
        self.project_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.order_info = tk.StringVar()
        self.project_version = tk.StringVar()
        self.base_zip_path = tk.StringVar()
        self.custom_zip_name = tk.StringVar()
        self.is_packaging = False

        # 创建UI
        self._create_widgets()

        # 加载配置
        self._load_config()

    def _select_project_dir(self):
        dir_path = filedialog.askdirectory(
            title="选择项目目录",
            initialdir=self.project_dir.get()
        )
        if dir_path:
            package_json = Path(dir_path) / "package.json"
            if not package_json.exists():
                messagebox.showerror("错误", "所选目录不是Node项目（未找到package.json）")
                return
            self.project_dir.set(dir_path)
            self._log(f"选择项目目录: {dir_path}")

    def _select_output_dir(self):
        dir_path = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=self.output_dir.get()
        )
        if dir_path:
            self.output_dir.set(dir_path)
            self._log(f"选择输出目录: {dir_path}")

    def _select_base_zip(self):
        file_path = filedialog.askopenfilename(
            title="选择基础压缩包",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            initialdir=self.base_zip_path.get()
        )
        if file_path:
            try:
                with zipfile.ZipFile(file_path, 'r') as zipf:
                    files = zipf.namelist()
                    if not any(f.startswith('design/') for f in files) or not any(f.startswith('resource/') for f in files):
                        messagebox.showerror("错误", "压缩包必须包含 'design' 和 'resource' 目录")
                        return
            except Exception as e:
                messagebox.showerror("错误", f"验证压缩包失败: {e}")
                return
            self.base_zip_path.set(file_path)
            self._log(f"选择基础压缩包: {file_path}")

    def _check_node_version(self):
        """检查当前Node版本并提示用户是否继续"""
        try:
            result = subprocess.check_output(["node", "-v"], text=True, encoding='utf-8')
            current_version = result.strip()
            self._log(f"当前Node版本: {current_version}")

            version_match = re.search(r'v(\d+)', current_version)
            if version_match:
                major_version = int(version_match.group(1))
                if major_version < 14:
                    # 弹出确认对话框
                    confirm = messagebox.askyesno(
                        "Node版本过低",
                        f"检测到当前Node版本为 {current_version}，建议使用 v14 或更高版本。\n\n"
                        "是否仍要继续打包？\n（某些构建步骤可能失败）"
                    )
                    if not confirm:
                        self._log("用户取消打包：Node版本过低", logging.WARNING)
                        return False
                    else:
                        self._log("用户选择继续打包，尽管Node版本低于14", logging.WARNING)
                        return True
                else:
                    self._log(f"✅ Node版本检查通过: {current_version}")
                    return True
            else:
                self._log("⚠️ 无法解析Node版本", logging.WARNING)
                return True
        except Exception as e:
            self._log(f"检查Node版本失败: {str(e)}", logging.WARNING)
            messagebox.showwarning("版本检查", "无法检测Node版本，请确保已安装Node.js并配置到环境变量中。")
            return True  # 允许继续，但有风险

    def _run_npm_command(self, command):
        project_dir = self.project_dir.get()
        if not project_dir:
            messagebox.showerror("错误", "请先选择项目目录")
            return False

        try:
            self._log(f"开始执行命令: npm {command}")

            process = subprocess.Popen(
                ["npm"] + command.split(),
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                shell=platform.system() == "Windows"
            )

            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        self._log(line.strip())

            if process.stdout:
                remaining = process.stdout.read()
                if remaining:
                    self._log(remaining.strip())

            if process.returncode == 0:
                self._log(f"✅ 命令 'npm {command}' 执行成功")
                return True
            else:
                self._log(f"❌ 命令 'npm {command}' 执行失败，返回代码: {process.returncode}", logging.ERROR)
                return False

        except Exception as e:
            self._log(f"执行命令出错: {str(e)}", logging.ERROR)
            return False

    def _clean_dist_dirs(self):
        project_dir = Path(self.project_dir.get())
        for dir_name in ["dist", "lib-render-dist"]:
            dir_path = project_dir / dir_name
            if dir_path.exists():
                try:
                    shutil.rmtree(dir_path)
                    self._log(f"✅ 删除目录: {dir_path}")
                except Exception as e:
                    self._log(f"❌ 删除目录失败 {dir_path}: {e}", logging.ERROR)
                    return False
        return True

    def _do_packaging(self):
        try:
            if not self._check_node_version():
                return

            if not self._clean_dist_dirs():
                return

            self._log("🔄 开始执行 npm run build...")
            if not self._run_npm_command("run build"):
                self._log("❌ build 命令执行失败", logging.ERROR)
                return

            self._log("🔄 开始执行 npm run lib-render2...")
            if not self._run_npm_command("run lib-render2"):
                self._log("❌ lib-render2 命令执行失败", logging.ERROR)
                return

            project_dir = Path(self.project_dir.get())
            dist_dir = project_dir / "dist"
            lib_render_dir = project_dir / "lib-render-dist"

            if not dist_dir.exists():
                self._log("❌ 打包后未找到 dist 目录", logging.ERROR)
                return
            if not lib_render_dir.exists():
                self._log("❌ 打包后未找到 lib-render-dist 目录", logging.ERROR)
                return

            self._log("✅ 项目打包完成")
            self._process_base_zip(dist_dir, lib_render_dir)

        except Exception as e:
            self._log(f"打包过程中出错: {str(e)}", logging.ERROR)
        finally:
            self.is_packaging = False
            self.root.after(0, self._update_button_states)

    def _process_base_zip(self, dist_dir, lib_render_dir):
        try:
            base_zip_path = Path(self.base_zip_path.get())
            output_dir = Path(self.output_dir.get())
            output_dir.mkdir(parents=True, exist_ok=True)

            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                with zipfile.ZipFile(base_zip_path, 'r') as zipf:
                    zipf.extractall(temp_path)

                self._log("✅ 基础压缩包解压完成")

                design_target = temp_path / "design"
                if design_target.exists():
                    for item in design_target.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    for item in dist_dir.iterdir():
                        dest = design_target / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            shutil.copytree(item, dest)
                    self._log("✅ design 目录内容已替换")

                render_target = temp_path / "resource" / "js" / "render-design"
                if render_target.exists():
                    for item in render_target.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    for item in lib_render_dir.iterdir():
                        dest = render_target / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            shutil.copytree(item, dest)
                    self._log("✅ resource/js/render-design 目录内容已替换")

                order_info = self.order_info.get()
                version = self.project_version.get()
                custom_name = self.custom_zip_name.get().strip()

                if custom_name:
                    new_zip_name = custom_name
                    if not new_zip_name.lower().endswith('.zip'):
                        new_zip_name += '.zip'
                else:
                    if len(order_info) >= 9:
                        order_id = order_info[:9]
                        hospital_name = order_info[9:]
                        self._log(f"解析订单号: {order_id}, 医院名: {hospital_name}")

                        order_parts = order_id.split('-')
                        if len(order_parts) == 2:
                            year_part = order_parts[0][-2:]
                            order_num = order_parts[1]
                            pinyin_initials = self._get_pinyin_initials(hospital_name)
                            new_zip_name = f"YM-801S-TLSS-V{version}.{year_part}{order_num}.01001-{pinyin_initials}-FE.zip"
                        else:
                            self._log(f"⚠️ 订单号格式不匹配: '{order_id}'，使用默认名称", logging.WARNING)
                            new_zip_name = f"{version}.zip"
                    else:
                        self._log(f"⚠️ 订单信息长度不足9位: '{order_info}'，使用默认名称", logging.WARNING)
                        new_zip_name = f"{version}.zip"

                new_zip_path = output_dir / new_zip_name

                with zipfile.ZipFile(new_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(temp_path):
                        for file in files:
                            file_path = Path(root) / file
                            arc_name = file_path.relative_to(temp_path).as_posix()
                            zipf.write(file_path, arc_name)

                self._log(f"✅ 新压缩包已生成: {new_zip_path}")
                self._log("🎉 打包完成！")

        except Exception as e:
            self._log(f"处理基础压缩包时出错: {str(e)}", logging.ERROR)

    def _get_pinyin_initials(self, text):
        """获取中文文本的拼音首字母（优先使用 pypinyin）"""
        if HAS_PINYIN:
            try:
                initials = lazy_pinyin(text, style=Style.FIRST_LETTER)
                result = ''.join(initials).upper()
                # 只保留字母
                result = ''.join(c for c in result if c.isalpha())
                return result or 'UNKNOWN'
            except Exception as e:
                self._log(f"pypinyin 处理失败，回退到简化逻辑: {e}", logging.WARNING)

        # 回退逻辑（原版）
        initials_map = {
            '南': 'N', '昌': 'C', '市': 'S', '立': 'L', '医': 'Y',
            '院': 'Y', '新': 'X', '区': 'Q', '中': 'Z', '国': 'G'
        }
        result = []
        for char in text:
            if char in initials_map:
                result.append(initials_map[char])
            elif '\u4e00' <= char <= '\u9fff':
                result.append('Z')  # 简化兜底
            else:
                result.append(char)
        letters = [c for c in result if c.isalpha()]
        fallback = ''.join(letters).upper()
        self._log(f"⚠️ 使用简化拼音逻辑生成医院首字母: {fallback}", logging.WARNING)
        return fallback or 'UNKNOWN'

    def _start_packaging(self):
        if not self.project_dir.get():
            messagebox.showerror("错误", "请先选择项目目录")
            return
        if not self.output_dir.get():
            messagebox.showerror("错误", "请先选择输出目录")
            return
        if not self.base_zip_path.get():
            messagebox.showerror("错误", "请先选择基础压缩包")
            return
        if not self.project_version.get():
            messagebox.showerror("错误", "请选择或输入项目版本")
            return

        self.is_packaging = True
        self._update_button_states()
        threading.Thread(target=self._do_packaging, daemon=True).start()

    def _log(self, message, level=logging.INFO):
        logging.log(level, message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def _update_button_states(self):
        state = tk.DISABLED if self.is_packaging else tk.NORMAL
        for btn in [
            self.select_project_btn, self.select_output_btn,
            self.select_zip_btn, self.start_btn, self.save_btn
        ]:
            btn.config(state=state)

    def _save_config(self):
        config = {
            "project_dir": self.project_dir.get(),
            "output_dir": self.output_dir.get(),
            "order_info": self.order_info.get(),
            "project_version": self.project_version.get(),
            "base_zip_path": self.base_zip_path.get(),
            "custom_zip_name": self.custom_zip_name.get()
        }

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log("配置已保存")
        except Exception as e:
            self._log(f"保存配置失败: {str(e)}", logging.ERROR)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)

                self.project_dir.set(config.get("project_dir", DEFAULT_CONFIG["project_dir"]))
                self.output_dir.set(config.get("output_dir", DEFAULT_CONFIG["output_dir"]))
                self.order_info.set(config.get("order_info", DEFAULT_CONFIG["order_info"]))
                self.project_version.set(config.get("project_version", DEFAULT_CONFIG["project_version"]))
                self.base_zip_path.set(config.get("base_zip_path", DEFAULT_CONFIG["base_zip_path"]))
                self.custom_zip_name.set(config.get("custom_zip_name", DEFAULT_CONFIG["custom_zip_name"]))
                self._log("配置已加载")
            else:
                for attr, default_val in DEFAULT_CONFIG.items():
                    getattr(self, attr).set(default_val)
                self._log("使用默认配置")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        project_frame = ttk.LabelFrame(main_frame, text="📁 项目目录", padding="5")
        project_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(project_frame, textvariable=self.project_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_project_btn = ttk.Button(project_frame, text="浏览...", command=self._select_project_dir)
        self.select_project_btn.pack(side=tk.RIGHT)

        output_frame = ttk.LabelFrame(main_frame, text="💾 输出目录", padding="5")
        output_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(output_frame, textvariable=self.output_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_output_btn = ttk.Button(output_frame, text="浏览...", command=self._select_output_dir)
        self.select_output_btn.pack(side=tk.RIGHT)

        order_frame = ttk.LabelFrame(main_frame, text="📋 订单信息", padding="5")
        order_frame.pack(fill=tk.X, pady=5)
        ttk.Label(order_frame, text="格式: 前9个字符为订单号，其余为医院名").pack(anchor=tk.W)
        ttk.Entry(order_frame, textvariable=self.order_info, width=70).pack(fill=tk.X, pady=5)

        version_frame = ttk.LabelFrame(main_frame, text="🔄 项目版本", padding="5")
        version_frame.pack(fill=tk.X, pady=5)
        versions = ["1.5.0", "1.5.1", "1.5.2", "1.5.3", "1.5.4"]
        version_combo = ttk.Combobox(
            version_frame,
            textvariable=self.project_version,
            values=versions + ["手动输入"],
            width=10,
            state="readonly"
        )
        version_combo.grid(row=0, column=0, padx=5, pady=5)
        version_combo.bind("<<ComboboxSelected>>", lambda e: self._on_version_selected(version_combo))

        self.manual_version_var = tk.StringVar()
        self.manual_version_entry = ttk.Entry(version_frame, textvariable=self.manual_version_var, width=10)
        self.manual_version_entry.grid(row=0, column=1, padx=5, pady=5)
        self.manual_version_entry.grid_remove()

        custom_frame = ttk.LabelFrame(main_frame, text="🏷️ 自定义ZIP名称", padding="5")
        custom_frame.pack(fill=tk.X, pady=5)
        ttk.Label(custom_frame, text="（留空则自动生成或使用默认名称）").pack(anchor=tk.W)
        ttk.Entry(custom_frame, textvariable=self.custom_zip_name, width=70).pack(fill=tk.X, pady=5)

        zip_frame = ttk.LabelFrame(main_frame, text="📦 基础压缩包", padding="5")
        zip_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(zip_frame, textvariable=self.base_zip_path, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_zip_btn = ttk.Button(zip_frame, text="浏览...", command=self._select_base_zip)
        self.select_zip_btn.pack(side=tk.RIGHT)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="🚀 开始打包", command=self._start_packaging, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0,10))
        self.save_btn = ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config)
        self.save_btn.pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(main_frame, text="📝 打包日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _on_version_selected(self, combo):
        if combo.get() == "手动输入":
            self.manual_version_entry.grid()
            self.manual_version_entry.focus()
        else:
            self.manual_version_entry.grid_remove()
            if combo.get() != "手动输入":
                self.project_version.set(combo.get())

if __name__ == "__main__":
    root = tk.Tk()
    app = ZipBasedPackagerApp(root)
    root.mainloop()
