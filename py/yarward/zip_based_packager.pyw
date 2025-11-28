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
    "base_zip_path": r"C:\www\test\门诊\801S-订单\前端\1.5.1.zip"
}

class ZipBasedPackagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📦 基于压缩包的打包工具")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        # 初始化变量
        self.project_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.order_info = tk.StringVar()
        self.project_version = tk.StringVar()
        self.base_zip_path = tk.StringVar()
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
            # 验证压缩包内容
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
        """检查当前Node版本并提示用户"""
        try:
            result = subprocess.check_output(["node", "-v"], text=True, encoding='utf-8')
            current_version = result.strip()
            self._log(f"当前Node版本: {current_version}")

            # 检查是否为14+
            version_match = re.search(r'v(\d+)', current_version)
            if version_match:
                major_version = int(version_match.group(1))
                if major_version < 14:
                    messagebox.showwarning(
                        "版本检查",
                        f"当前Node版本: {current_version}\n建议使用 14+ 版本，否则可能打包失败。"
                    )
                    return False
                else:
                    self._log(f"✅ Node版本检查通过: {current_version}")
                    return True
            else:
                self._log("⚠️ 无法解析Node版本", logging.WARNING)
                return True
        except Exception as e:
            self._log(f"检查Node版本失败: {str(e)}", logging.WARNING)
            messagebox.showwarning("版本检查", "无法检测Node版本，请确保已安装Node.js并配置到环境变量中。")
            return False

    def _run_npm_command(self, command):
        """运行npm命令"""
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

            # 读取剩余输出
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
        """删除项目目录中的 dist 和 lib-render-dist 目录"""
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
        """执行打包流程"""
        try:
            # 1. 检查Node版本
            if not self._check_node_version():
                return

            # 2. 清理目录
            if not self._clean_dist_dirs():
                return

            # 3. 执行npm命令
            self._log("🔄 开始执行 npm run build...")
            if not self._run_npm_command("run build"):
                self._log("❌ build 命令执行失败", logging.ERROR)
                return

            self._log("🔄 开始执行 npm run lib-render2...")
            if not self._run_npm_command("run lib-render2"):
                self._log("❌ lib-render2 命令执行失败", logging.ERROR)
                return

            # 4. 验证打包结果
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

            # 5. 处理基础压缩包
            self._process_base_zip(dist_dir, lib_render_dir)

        except Exception as e:
            self._log(f"打包过程中出错: {str(e)}", logging.ERROR)
        finally:
            self.is_packaging = False
            self.root.after(0, self._update_button_states)

    def _process_base_zip(self, dist_dir, lib_render_dir):
        """处理基础压缩包"""
        try:
            base_zip_path = Path(self.base_zip_path.get())
            output_dir = Path(self.output_dir.get())
            output_dir.mkdir(parents=True, exist_ok=True)

            # 解压基础压缩包到临时目录
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # 解压
                with zipfile.ZipFile(base_zip_path, 'r') as zipf:
                    zipf.extractall(temp_path)

                self._log("✅ 基础压缩包解压完成")

                # 5.1 替换 design 目录内容
                design_target = temp_path / "design"
                if design_target.exists():
                    # 删除现有内容
                    for item in design_target.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)

                    # 复制新内容
                    for item in dist_dir.iterdir():
                        dest = design_target / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            shutil.copytree(item, dest)

                    self._log("✅ design 目录内容已替换")

                # 5.2 替换 resource/js/render-design 目录内容
                render_target = temp_path / "resource" / "js" / "render-design"
                if render_target.exists():
                    # 删除现有内容
                    for item in render_target.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)

                    # 复制新内容
                    for item in lib_render_dir.iterdir():
                        dest = render_target / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            shutil.copytree(item, dest)

                    self._log("✅ resource/js/render-design 目录内容已替换")

                # 5.3 生成新压缩包名
                order_info = self.order_info.get()
                version = self.project_version.get()

                # 解析订单信息
                order_match = re.match(r'(\d+)-(.+)', order_info)
                if not order_match:
                    self._log(f"❌ 订单信息格式错误: '{order_info}'，应为 '数字-文本' 格式", logging.ERROR)
                    # 使用默认名称
                    new_zip_name = f"{order_info}.zip"
                    new_zip_path = output_dir / new_zip_name
                    self._log(f"⚠️ 使用默认名称: {new_zip_name}")
                else:
                    full_order_id = order_info  # ← 修改：使用原始订单信息
                    hospital_name = order_match.group(2)  # 例如 "1987南昌市立医院新院区"

                    # 提取年份后两位和订单编号
                    order_parts = full_order_id.split('-')
                    if len(order_parts) != 2:
                        self._log(f"❌ 订单ID格式错误: '{full_order_id}'，应为 '年份-编号' 格式", logging.ERROR)
                        # 使用默认名称
                        new_zip_name = f"{order_info}.zip"
                        new_zip_path = output_dir / new_zip_name
                        self._log(f"⚠️ 使用默认名称: {new_zip_name}")
                    else:
                        year_part = order_parts[0][-2:]  # "25"
                        order_num = order_parts[1]       # "1987"

                        # 提取医院名称拼音首字母
                        pinyin_initials = self._get_pinyin_initials(hospital_name)

                        new_zip_name = f"YM-801S-TLSS-V{version}.{year_part}{order_num}.01001-{pinyin_initials}-FE.zip"
                        new_zip_path = output_dir / new_zip_name

                full_order_id = order_match.group(1)  # 例如 "2025-1987"
                hospital_name = order_match.group(2)  # 例如 "南昌市立医院新院区"

                # 提取年份后两位和订单编号
                order_parts = full_order_id.split('-')
                if len(order_parts) != 2:
                    self._log(f"❌ 订单ID格式错误: '{full_order_id}'，应为 '年份-编号' 格式", logging.ERROR)
                    return

                year_part = order_parts[0][-2:]  # "25"
                order_num = order_parts[1]       # "1987"

                # 提取医院名称拼音首字母
                pinyin_initials = self._get_pinyin_initials(hospital_name)

                new_zip_name = f"YM-801S-TLSS-V{version}.{year_part}{order_num}.01001-{pinyin_initials}-FE.zip"
                new_zip_path = output_dir / new_zip_name

                # 5.4 重新打包
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
        """获取中文文本的拼音首字母（简化处理）"""
        # 由于无法直接处理中文转拼音，这里使用简化的处理方式
        # 实际应用中可能需要安装 pypinyin 库
        # 暂时返回医院名的首字母缩写
        import re

        # 提取中文字符的首字母（这里简化处理）
        # 实际项目中建议使用 pypinyin: pip install pypinyin
        # from pypinyin import lazy_pinyin, Style
        # return ''.join(lazy_pinyin(text, style=Style.FIRST_LETTER)).upper()

        # 简化处理：取汉字首字母
        # 这里用一个简化的映射表（实际项目建议使用 pypinyin）
        initials_map = {
            '南': 'N', '昌': 'C', '市': 'S', '立': 'L', '医': 'Y',
            '院': 'Y', '新': 'X', '区': 'Q', '中': 'Z', '国': 'G'
        }

        result = []
        for char in text:
            if char in initials_map:
                result.append(initials_map[char])
            elif '\u4e00' <= char <= '\u9fff':  # 中文字符
                # 简化：取字符的 Unicode 码点的首字母（实际应使用拼音）
                # 这里返回一个默认值
                result.append('Z')  # 默认值
            else:
                # 非中文字符直接添加
                result.append(char)

        # 过滤掉非字母字符，只保留字母
        letters = [c for c in result if c.isalpha()]
        return ''.join(letters).upper()[:10]  # 限制长度

    def _start_packaging(self):
        """开始打包"""
        if not self.project_dir.get():
            messagebox.showerror("错误", "请先选择项目目录")
            return
        if not self.output_dir.get():
            messagebox.showerror("错误", "请先选择输出目录")
            return
        if not self.base_zip_path.get():
            messagebox.showerror("错误", "请先选择基础压缩包")
            return
        if not self.order_info.get():
            messagebox.showerror("错误", "请输入订单信息")
            return
        if not self.project_version.get():
            messagebox.showerror("错误", "请选择或输入项目版本")
            return

        self.is_packaging = True
        self._update_button_states()
        threading.Thread(target=self._do_packaging, daemon=True).start()

    def _log(self, message, level=logging.INFO):
        """记录日志并更新UI"""
        logging.log(level, message)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def _update_button_states(self):
        """更新按钮状态"""
        state = tk.DISABLED if self.is_packaging else tk.NORMAL
        for btn in [
            self.select_project_btn, self.select_output_btn,
            self.select_zip_btn, self.start_btn, self.save_btn
        ]:
            btn.config(state=state)

    def _save_config(self):
        """保存配置"""
        config = {
            "project_dir": self.project_dir.get(),
            "output_dir": self.output_dir.get(),
            "order_info": self.order_info.get(),
            "project_version": self.project_version.get(),
            "base_zip_path": self.base_zip_path.get()
        }

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self._log("配置已保存")
        except Exception as e:
            self._log(f"保存配置失败: {str(e)}", logging.ERROR)

    def _load_config(self):
        """加载配置"""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)

                self.project_dir.set(config.get("project_dir", DEFAULT_CONFIG["project_dir"]))
                self.output_dir.set(config.get("output_dir", DEFAULT_CONFIG["output_dir"]))
                self.order_info.set(config.get("order_info", DEFAULT_CONFIG["order_info"]))
                self.project_version.set(config.get("project_version", DEFAULT_CONFIG["project_version"]))
                self.base_zip_path.set(config.get("base_zip_path", DEFAULT_CONFIG["base_zip_path"]))

                self._log("配置已加载")
            else:
                # 使用默认值
                for attr, default_val in DEFAULT_CONFIG.items():
                    getattr(self, attr).set(default_val)
                self._log("使用默认配置")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

    def _create_widgets(self):
        """创建UI组件"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 项目目录
        project_frame = ttk.LabelFrame(main_frame, text="📁 项目目录", padding="5")
        project_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(project_frame, textvariable=self.project_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_project_btn = ttk.Button(project_frame, text="浏览...", command=self._select_project_dir)
        self.select_project_btn.pack(side=tk.RIGHT)

        # 输出目录
        output_frame = ttk.LabelFrame(main_frame, text="💾 输出目录", padding="5")
        output_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(output_frame, textvariable=self.output_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_output_btn = ttk.Button(output_frame, text="浏览...", command=self._select_output_dir)
        self.select_output_btn.pack(side=tk.RIGHT)

        # 订单信息
        order_frame = ttk.LabelFrame(main_frame, text="📋 订单信息", padding="5")
        order_frame.pack(fill=tk.X, pady=5)
        ttk.Label(order_frame, text="格式: 2025-1987南昌市立医院新院区").pack(anchor=tk.W)
        ttk.Entry(order_frame, textvariable=self.order_info, width=70).pack(fill=tk.X, pady=5)

        # 项目版本
        version_frame = ttk.LabelFrame(main_frame, text="🔄 项目版本", padding="5")
        version_frame.pack(fill=tk.X, pady=5)
        versions = ["1.5.0", "1.5.1", "1.5.2", "1.5.3"]
        version_combo = ttk.Combobox(
            version_frame,
            textvariable=self.project_version,
            values=versions + ["手动输入"],
            width=10,
            state="readonly"
        )
        version_combo.grid(row=0, column=0, padx=5, pady=5)
        version_combo.bind("<<ComboboxSelected>>", lambda e: self._on_version_selected(version_combo))

        # 手动输入框（当选择"手动输入"时显示）
        self.manual_version_var = tk.StringVar()
        self.manual_version_entry = ttk.Entry(version_frame, textvariable=self.manual_version_var, width=10)
        self.manual_version_entry.grid(row=0, column=1, padx=5, pady=5)
        self.manual_version_entry.grid_remove()  # 初始隐藏

        # 基础压缩包
        zip_frame = ttk.LabelFrame(main_frame, text="📦 基础压缩包", padding="5")
        zip_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(zip_frame, textvariable=self.base_zip_path, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_zip_btn = ttk.Button(zip_frame, text="浏览...", command=self._select_base_zip)
        self.select_zip_btn.pack(side=tk.RIGHT)

        # 操作按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="🚀 开始打包", command=self._start_packaging, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0,10))
        self.save_btn = ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config)
        self.save_btn.pack(side=tk.LEFT)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="📝 打包日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _on_version_selected(self, combo):
        """处理版本选择事件"""
        if combo.get() == "手动输入":
            self.manual_version_entry.grid()
            self.manual_version_entry.focus()
        else:
            self.manual_version_entry.grid_remove()
            # 如果不是手动输入，同步到project_version
            if combo.get() != "手动输入":
                self.project_version.set(combo.get())

if __name__ == "__main__":
    root = tk.Tk()
    app = ZipBasedPackagerApp(root)
    root.mainloop()
