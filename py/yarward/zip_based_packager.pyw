# zip_based_packager.pyw

import os
import subprocess
import json
import platform
import zipfile
import shutil
import urllib.request
import urllib.error
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
# ──────────── 公共日志模块（可选依赖）────────────
import sys
_PY_DIR = str(SCRIPT_DIR.parent)
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

try:
    from log_utils import get_logger
    logger = get_logger(SCRIPT_NAME)
except Exception:
    class _DummyLogger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    logger = _DummyLogger()
# ────────────────────────────────────────────────

# 默认配置
DEFAULT_CONFIG = {
    "project_dir": r"C:\www\yh\门诊\template1.5.0",
    "output_dir": r"D:\yarward\svn\2025-1987南昌市立医院新院区\前端",
    "order_info": "2025-1987南昌市立医院新院区",
    "project_version": "1.5.1",
    "base_zip_path": r"C:\www\test\门诊\801S-订单\前端\1.5.1.zip",
    "custom_zip_name": "",
    "auto_commit_svn": True,
    "is_version_155_plus": False,
    "history_records": [],
    "enable_wechat_notify": False,   # ✅ 新增：是否启用企业微信通知
    "wechat_webhook": ""              # ✅ 新增：企业微信 Webhook 地址
}

class ZipBasedPackagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📦 基于压缩包的打包工具")
        self.root.geometry("900x1000")
        self.root.minsize(800, 750)

        # 初始化变量
        self.project_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.order_info = tk.StringVar()
        self.project_version = tk.StringVar()
        self.base_zip_path = tk.StringVar()
        self.custom_zip_name = tk.StringVar()
        self.auto_commit_svn = tk.BooleanVar(value=True)
        self.is_version_155_plus = tk.BooleanVar(value=False)
        self.enable_wechat_notify = tk.BooleanVar(value=False)  # ✅ 新增：企业微信通知开关
        self.wechat_webhook = tk.StringVar()                     # ✅ 新增：Webhook 地址
        self.is_packaging = False
        self.history_records = []

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

            # ✅ 根据版本选择不同的打包方式
            if self.is_version_155_plus.get():
                # 1.5.5及以上版本：仅执行 npm run build
                self._log("🔄 检测到1.5.5+版本，执行简化打包流程...")
                if not self._clean_dist_dirs():
                    return
                
                self._log("🔄 开始执行 npm run build...")
                if not self._run_npm_command("run build"):
                    self._log("❌ build 命令执行失败", logging.ERROR)
                    return
                
                project_dir = Path(self.project_dir.get())
                dist_dir = project_dir / "dist"
                
                if not dist_dir.exists():
                    self._log("❌ 打包后未找到 dist 目录", logging.ERROR)
                    return
                
                self._log("✅ 项目打包完成")
                # 1.5.5+ 版本使用新的打包方式（不传 lib_render_dir）
                self._process_base_zip_v155(dist_dir)
            else:
                # 1.5.5以下版本：原有打包流程
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

    def _process_base_zip_v155(self, dist_dir):
        """1.5.5及以上版本的打包方式"""
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

                # 从 dist 目录获取 design 和 resource
                design_source = dist_dir / "design"
                resource_source = dist_dir / "resource"

                # 替换或新建 design 目录
                design_target = temp_path / "design"
                if design_source.exists():
                    if design_target.exists():
                        # 如果已存在，先清空
                        for item in design_target.iterdir():
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                    else:
                        # 不存在则创建
                        design_target.mkdir(parents=True, exist_ok=True)
                    
                    # 复制 design 内容
                    for item in design_source.iterdir():
                        dest = design_target / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            shutil.copytree(item, dest)
                    self._log("✅ design 目录内容已替换/创建")
                else:
                    self._log("⚠️ dist/design 目录不存在，跳过", logging.WARNING)

                # 替换或新建 resource 目录
                resource_target = temp_path / "resource"
                if resource_source.exists():
                    if resource_target.exists():
                        # 如果已存在，先清空
                        for item in resource_target.iterdir():
                            if item.is_file():
                                item.unlink()
                            elif item.is_dir():
                                shutil.rmtree(item)
                    else:
                        # 不存在则创建
                        resource_target.mkdir(parents=True, exist_ok=True)
                    
                    # 复制 resource 内容
                    for item in resource_source.iterdir():
                        dest = resource_target / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            shutil.copytree(item, dest)
                    self._log("✅ resource 目录内容已替换/创建")
                else:
                    self._log("⚠️ dist/resource 目录不存在，跳过", logging.WARNING)

                # 生成ZIP文件名（逻辑不变）
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
                
                # ✅ 新增：添加到历史记录
                self._add_to_history()
                
                # 如果启用了自动提交SVN，则执行提交
                if self.auto_commit_svn.get():
                    self._commit_to_svn(new_zip_path)
                
                # ✅ 新增：发送企业微信通知
                self._send_wechat_notify(new_zip_name)
                
                # ✅ 右下角弹窗提示
                self.root.after(0, lambda: self._show_toast_notification(
                    "打包完成",
                    f"订单: {self.order_info.get()}\n文件: {new_zip_name}"
                ))
                
                self._log("🎉 打包完成！")

        except Exception as e:
            self._log(f"处理基础压缩包时出错: {str(e)}", logging.ERROR)

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
                
                # ✅ 新增：添加到历史记录
                self._add_to_history()
                
                # 如果启用了自动提交SVN，则执行提交
                if self.auto_commit_svn.get():
                    self._commit_to_svn(new_zip_path)
                
                # ✅ 新增：发送企业微信通知
                self._send_wechat_notify(new_zip_name)
                
                # ✅ 右下角弹窗提示
                self.root.after(0, lambda: self._show_toast_notification(
                    "打包完成",
                    f"订单: {self.order_info.get()}\n文件: {new_zip_name}"
                ))
                
                self._log("🎉 打包完成！")

        except Exception as e:
            self._log(f"处理基础压缩包时出错: {str(e)}", logging.ERROR)

    def _add_to_history(self):
        """添加当前打包配置到历史记录（按订单信息去重）"""
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_dir": self.project_dir.get(),
            "output_dir": self.output_dir.get(),
            "order_info": self.order_info.get(),
            "project_version": self.project_version.get(),
            "base_zip_path": self.base_zip_path.get(),
            "custom_zip_name": self.custom_zip_name.get(),
            "auto_commit_svn": self.auto_commit_svn.get(),
            "is_version_155_plus": self.is_version_155_plus.get()
        }
        
        # ✅ 新增：按订单信息去重，删除旧的同名记录
        order_info = self.order_info.get()
        self.history_records = [
            r for r in self.history_records 
            if r['order_info'] != order_info
        ]
        
        # 添加到历史记录开头（最新）
        self.history_records.insert(0, record)
        
        # 只保留最近50条
        if len(self.history_records) > 50:
            self.history_records = self.history_records[:50]
        
        # 刷新UI显示
        self._refresh_history_listbox()
        
        # 保存到配置文件
        self._save_config()
        
        self._log(f"✅ 已添加到历史记录（当前共 {len(self.history_records)} 条，已去重）")
    
    def _refresh_history_listbox(self):
        """刷新历史记录列表框"""
        self.history_listbox.delete(0, tk.END)
        
        for i, record in enumerate(self.history_records):
            display_text = f"[{record['timestamp']}] {record['order_info']} - V{record['project_version']}"
            self.history_listbox.insert(tk.END, display_text)
    
    def _load_history_record(self, event=None):
        """加载选中的历史记录（仅加载配置，不自动打包）"""
        selection = self.history_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        if 0 <= index < len(self.history_records):
            record = self.history_records[index]
            
            # 加载配置到界面
            self.project_dir.set(record['project_dir'])
            self.output_dir.set(record['output_dir'])
            self.order_info.set(record['order_info'])
            self.project_version.set(record['project_version'])
            self.base_zip_path.set(record['base_zip_path'])
            self.custom_zip_name.set(record['custom_zip_name'])
            self.auto_commit_svn.set(record['auto_commit_svn'])
            self.is_version_155_plus.set(record['is_version_155_plus'])
            
            self._log(f"✅ 已加载历史记录: {record['timestamp']} - {record['order_info']}")
            self._log("ℹ️ 配置已加载，请确认后点击「🚀 开始打包」按钮执行打包")
            
            # 切换到配置标签页，方便用户查看和修改
            self.notebook.select(0)
    
    def _delete_history_record(self):
        """删除选中的历史记录"""
        selection = self.history_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的历史记录")
            return
        
        index = selection[0]
        if 0 <= index < len(self.history_records):
            record = self.history_records[index]
            
            confirm = messagebox.askyesno(
                "确认删除",
                f"是否删除以下历史记录？\n\n"
                f"时间: {record['timestamp']}\n"
                f"订单: {record['order_info']}"
            )
            
            if confirm:
                del self.history_records[index]
                self._refresh_history_listbox()
                self._save_config()
                self._log(f"✅ 已删除历史记录: {record['timestamp']}")
                messagebox.showinfo("成功", "历史记录已删除")

    def _send_wechat_notify(self, zip_name, success=True):
        """发送企业微信通知（打包完成后调用）"""
        if not self.enable_wechat_notify.get():
            return
        
        webhook_url = self.wechat_webhook.get().strip()
        if not webhook_url:
            self._log("⚠️ 企业微信通知已启用，但未配置 Webhook 地址", logging.WARNING)
            return
        
        try:
            order_info = self.order_info.get()
            version = self.project_version.get()
            status = "✅ 打包成功" if success else "❌ 打包失败"
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            content = (
                f"{status}\n"
                f"📋 订单: {order_info}\n"
                f"🔄 版本: V{version}\n"
                f"📦 文件: {zip_name}\n"
                f"🕐 时间: {current_time}"
            )
            
            payload = json.dumps({
                "msgtype": "text",
                "text": {"content": content}
            }).encode('utf-8')
            
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                if result.get("errcode") == 0:
                    self._log("✅ 企业微信通知发送成功")
                else:
                    self._log(f"⚠️ 企业微信通知失败: {result.get('errmsg', '未知错误')}", logging.WARNING)
        
        except urllib.error.URLError as e:
            self._log(f"⚠️ 企业微信通知网络错误: {e}", logging.WARNING)
        except Exception as e:
            self._log(f"⚠️ 企业微信通知异常: {e}", logging.WARNING)

    def _commit_to_svn(self, zip_path):
        """将生成的ZIP文件提交到SVN"""
        try:
            output_dir = Path(self.output_dir.get())
            
            # 查找SVN工作副本根目录（从当前目录向上查找）
            svn_working_copy = None
            check_dir = output_dir
            max_depth = 5  # 最多向上查找5层
            
            for _ in range(max_depth):
                if (check_dir / ".svn").exists():
                    svn_working_copy = check_dir
                    break
                parent = check_dir.parent
                if parent == check_dir:  # 已到达根目录
                    break
                check_dir = parent
            
            if not svn_working_copy:
                self._log(f"⚠️ 未找到SVN工作副本（已向上查找{max_depth}层），跳过提交", logging.WARNING)
                self._log(f"   检查路径: {output_dir}", logging.WARNING)
                return
            
            if svn_working_copy != output_dir:
                self._log(f"ℹ️ 在上级目录找到SVN工作副本: {svn_working_copy}")
            
            self._log(f"🔄 开始提交到SVN: {zip_path.name}")
            
            # 第一步：svn add（如果文件是新加的）
            try:
                result = subprocess.run(
                    ["svn", "add", str(zip_path)],
                    cwd=svn_working_copy,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=30
                )
                if result.returncode == 0:
                    self._log(f"✅ SVN Add成功: {result.stdout.strip()}")
                elif "already under version control" in result.stderr.lower():
                    self._log(f"ℹ️ 文件已在版本控制中，跳过Add")
                else:
                    self._log(f"⚠️ SVN Add警告: {result.stderr.strip()}", logging.WARNING)
            except Exception as e:
                self._log(f"⚠️ SVN Add出错: {e}", logging.WARNING)
            
            # 第二步：svn commit
            commit_message = f"自动提交：{zip_path.name} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            result = subprocess.run(
                ["svn", "commit", "-m", commit_message, str(zip_path)],
                cwd=svn_working_copy,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=60
            )
            
            if result.returncode == 0:
                self._log(f"✅ SVN提交成功")
                if result.stdout:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            self._log(f"   {line}")
            else:
                self._log(f"❌ SVN提交失败: {result.stderr.strip()}", logging.ERROR)
                
        except FileNotFoundError:
            self._log("❌ 未找到svn命令，请确保已安装TortoiseSVN命令行工具或Subversion", logging.ERROR)
        except subprocess.TimeoutExpired:
            self._log("❌ SVN操作超时", logging.ERROR)
        except Exception as e:
            self._log(f"❌ SVN提交出错: {str(e)}", logging.ERROR)

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
        if not Path(self.project_dir.get()).exists():
            messagebox.showerror("错误", f"项目目录不存在：\n{self.project_dir.get()}")
            return
        if not self.output_dir.get():
            messagebox.showerror("错误", "请先选择输出目录")
            return
        base_zip = self.base_zip_path.get()
        if not base_zip:
            messagebox.showerror("错误", "请先选择基础压缩包")
            return
        if not Path(base_zip).exists():
            messagebox.showerror("错误", f"基础压缩包不存在：\n{base_zip}\n\n请检查文件路径是否正确，或重新选择。")
            return
        if not self.project_version.get():
            messagebox.showerror("错误", "请选择或输入项目版本")
            return

        # ✅ 自动切换到日志标签页
        self.notebook.select(1)
        
        self.is_packaging = True
        self._update_button_states()
        threading.Thread(target=self._do_packaging, daemon=True).start()

    def _show_toast_notification(self, title, message, duration=60000):
        """右下角弹窗通知，duration 毫秒后自动消失（默认60秒）"""
        try:
            toast = tk.Toplevel(self.root)
            toast.withdraw()  # 先隐藏，设置好再显示
            toast.overrideredirect(True)  # 无边框
            toast.attributes('-topmost', True)  # 置顶

            # 设置样式
            toast.configure(bg='#2b5797', padx=2, pady=2)

            # 关闭按钮
            close_btn = tk.Label(
                toast, text="✕", bg='#2b5797', fg='white',
                font=('Arial', 10, 'bold'), cursor='hand2'
            )
            close_btn.place(relx=1.0, x=-20, y=5)
            close_btn.bind('<Button-1>', lambda e: toast.destroy())

            # 标题
            title_label = tk.Label(
                toast, text=f"📦 {title}", bg='#2b5797', fg='white',
                font=('Microsoft YaHei UI', 12, 'bold'), anchor='w'
            )
            title_label.pack(fill=tk.X, padx=(15, 30), pady=(12, 5))

            # 内容
            msg_label = tk.Label(
                toast, text=message, bg='#2b5797', fg='#e0e0e0',
                font=('Microsoft YaHei UI', 9), anchor='w',
                justify=tk.LEFT, wraplength=280
            )
            msg_label.pack(fill=tk.X, padx=(15, 15), pady=(0, 12))

            # 点击关闭
            for widget in [toast, title_label, msg_label]:
                widget.bind('<Button-1>', lambda e: toast.destroy())

            # 计算位置：右下角
            toast.update_idletasks()
            toast_width = 320
            toast_height = 100
            screen_width = toast.winfo_screenwidth()
            screen_height = toast.winfo_screenheight()
            x = screen_width - toast_width - 20
            y = screen_height - toast_height - 60  # 留出任务栏空间

            toast.geometry(f"{toast_width}x{toast_height}+{x}+{y}")
            toast.deiconify()  # 显示弹窗

            # 自动关闭（默认60秒）
            toast.after(duration, lambda: toast.destroy() if toast.winfo_exists() else None)

        except Exception as e:
            self._log(f"弹窗通知失败: {e}", logging.WARNING)

    def _log(self, message, level=logging.INFO):
        logger.log(level, message)
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
            "custom_zip_name": self.custom_zip_name.get(),
            "auto_commit_svn": self.auto_commit_svn.get(),
            "is_version_155_plus": self.is_version_155_plus.get(),
            "history_records": self.history_records,
            "enable_wechat_notify": self.enable_wechat_notify.get(),
            "wechat_webhook": self.wechat_webhook.get()
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
                self.auto_commit_svn.set(config.get("auto_commit_svn", DEFAULT_CONFIG["auto_commit_svn"]))  # ← 新增：加载SVN配置
                self.is_version_155_plus.set(config.get("is_version_155_plus", DEFAULT_CONFIG["is_version_155_plus"]))
                self.history_records = config.get("history_records", [])
                self.enable_wechat_notify.set(config.get("enable_wechat_notify", DEFAULT_CONFIG["enable_wechat_notify"]))
                self.wechat_webhook.set(config.get("wechat_webhook", DEFAULT_CONFIG["wechat_webhook"]))
                self._refresh_history_listbox()
                self._log("配置已加载")
            else:
                for attr, default_val in DEFAULT_CONFIG.items():
                    if attr != "history_records":  # 跳过历史记录
                        getattr(self, attr).set(default_val)
                self._log("使用默认配置")
        except Exception as e:
            self._log(f"加载配置失败: {str(e)}", logging.ERROR)

    def _create_widgets(self):
        # ✅ 使用 Notebook 创建两个标签页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ========== 标签页1：配置 ==========
        config_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(config_tab, text="⚙️ 打包配置")

        project_frame = ttk.LabelFrame(config_tab, text="📁 项目目录", padding="5")
        project_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(project_frame, textvariable=self.project_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_project_btn = ttk.Button(project_frame, text="浏览...", command=self._select_project_dir)
        self.select_project_btn.pack(side=tk.RIGHT)

        output_frame = ttk.LabelFrame(config_tab, text="💾 输出目录", padding="5")
        output_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(output_frame, textvariable=self.output_dir, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_output_btn = ttk.Button(output_frame, text="浏览...", command=self._select_output_dir)
        self.select_output_btn.pack(side=tk.RIGHT)

        order_frame = ttk.LabelFrame(config_tab, text="📋 订单信息", padding="5")
        order_frame.pack(fill=tk.X, pady=5)
        ttk.Label(order_frame, text="格式: 前9个字符为订单号，其余为医院名").pack(anchor=tk.W)
        ttk.Entry(order_frame, textvariable=self.order_info, width=70).pack(fill=tk.X, pady=5)

        version_frame = ttk.LabelFrame(config_tab, text="🔄 项目版本", padding="5")
        version_frame.pack(fill=tk.X, pady=5)
        versions = ["1.5.0", "1.5.1", "1.5.2",
                    "1.5.3", "1.5.4", "1.5.5", "1.5.6"]
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
        # 手动输入时实时同步到 project_version
        self.manual_version_var.trace_add("write", self._sync_manual_version)
        self.manual_version_entry = ttk.Entry(version_frame, textvariable=self.manual_version_var, width=10)
        self.manual_version_entry.grid(row=0, column=1, padx=5, pady=5)
        self.manual_version_entry.grid_remove()

        custom_frame = ttk.LabelFrame(config_tab, text="🏷️ 自定义ZIP名称", padding="5")
        custom_frame.pack(fill=tk.X, pady=5)
        ttk.Label(custom_frame, text="（留空则自动生成或使用默认名称）").pack(anchor=tk.W)
        ttk.Entry(custom_frame, textvariable=self.custom_zip_name, width=70).pack(fill=tk.X, pady=5)

        zip_frame = ttk.LabelFrame(config_tab, text="📦 基础压缩包", padding="5")
        zip_frame.pack(fill=tk.X, pady=5)
        ttk.Entry(zip_frame, textvariable=self.base_zip_path, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.select_zip_btn = ttk.Button(zip_frame, text="浏览...", command=self._select_base_zip)
        self.select_zip_btn.pack(side=tk.RIGHT)

        # 版本类型
        version_type_frame = ttk.LabelFrame(config_tab, text="📌 版本类型", padding="5")
        version_type_frame.pack(fill=tk.X, pady=5)
        version_type_check = ttk.Checkbutton(
            version_type_frame,
            text="是 1.5.5 及以上版本（仅执行 npm run build）",
            variable=self.is_version_155_plus
        )
        version_type_check.pack(anchor=tk.W, pady=5)
        ttk.Label(version_type_frame, text="提示：勾选后仅执行 build，不执行 lib-render2，并使用新的打包结构", foreground="gray").pack(anchor=tk.W)

        # SVN自动提交
        svn_frame = ttk.LabelFrame(config_tab, text="🔗 SVN自动提交", padding="5")
        svn_frame.pack(fill=tk.X, pady=5)
        svn_check = ttk.Checkbutton(
            svn_frame,
            text="打包完成后自动提交到SVN（需要安装SVN命令行工具）",
            variable=self.auto_commit_svn
        )
        svn_check.pack(anchor=tk.W, pady=5)
        ttk.Label(svn_frame, text="提示：会自动查找输出目录及其上级目录中的SVN工作副本", foreground="gray").pack(anchor=tk.W)

        # 企业微信通知
        wechat_frame = ttk.LabelFrame(config_tab, text="📨 企业微信通知", padding="5")
        wechat_frame.pack(fill=tk.X, pady=5)
        wechat_check = ttk.Checkbutton(
            wechat_frame,
            text="打包完成后发送企业微信通知",
            variable=self.enable_wechat_notify
        )
        wechat_check.pack(anchor=tk.W, pady=(0, 3))
        webhook_row = ttk.Frame(wechat_frame)
        webhook_row.pack(fill=tk.X)
        ttk.Label(webhook_row, text="Webhook:").pack(side=tk.LEFT)
        ttk.Entry(webhook_row, textvariable=self.wechat_webhook, width=70).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        ttk.Label(wechat_frame, text="提示：在企业微信群中添加群机器人，获取 Webhook 地址", foreground="gray").pack(anchor=tk.W, pady=(3, 0))

        # 操作按钮
        btn_frame = ttk.Frame(config_tab)
        btn_frame.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="🚀 开始打包", command=self._start_packaging, style="Accent.TButton")
        self.start_btn.pack(side=tk.LEFT, padx=(0,10))
        self.save_btn = ttk.Button(btn_frame, text="💾 保存配置", command=self._save_config)
        self.save_btn.pack(side=tk.LEFT)

        # ========== 标签页2：日志与历史 ==========
        log_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(log_tab, text="📝 日志与历史")

        # 打包日志
        log_frame = ttk.LabelFrame(log_tab, text="📝 打包日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED, wrap=tk.WORD, height=12)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 历史记录区域
        history_frame = ttk.LabelFrame(log_tab, text="📚 打包历史记录（最近10次）", padding="5")
        history_frame.pack(fill=tk.X, pady=5)

        listbox_frame = ttk.Frame(history_frame)
        listbox_frame.pack(fill=tk.X, pady=5)

        self.history_listbox = tk.Listbox(listbox_frame, height=6, width=80)
        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.history_listbox.yview)
        self.history_listbox.config(yscrollcommand=scrollbar.set)

        self.history_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定双击事件：直接加载并开始打包
        self.history_listbox.bind('<Double-Button-1>', self._load_history_record)

        btn_history_frame = ttk.Frame(history_frame)
        btn_history_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_history_frame, text="📥 加载选中记录", command=self._load_history_record).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_history_frame, text="🗑️ 删除选中记录", command=self._delete_history_record).pack(side=tk.LEFT, padx=5)

        ttk.Label(history_frame, text="💡 提示：双击或点击「加载」可恢复配置，需手动点击「开始打包」执行", foreground="gray").pack(anchor=tk.W)

    def _on_version_selected(self, combo):
        if combo.get() == "手动输入":
            self.manual_version_entry.grid()
            self.manual_version_entry.focus()
        else:
            self.manual_version_entry.grid_remove()
            self.project_version.set(combo.get())

    def _sync_manual_version(self, *args):
        """手动输入版本号时，实时同步到 project_version"""
        val = self.manual_version_var.get().strip()
        if val:
            self.project_version.set(val)

if __name__ == "__main__":
    root = tk.Tk()
    app = ZipBasedPackagerApp(root)
    root.mainloop()
