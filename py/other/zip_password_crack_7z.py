# zip_password_crack_7z.py

import os
import sys
import json
import time
import shutil
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, scrolledtext

# 修复 Windows GBK 控制台无法输出 emoji 的问题
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "zip_password_crack_7z"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
LOG_DIR = CONFIG_DIR / "logs"
PROCESS_LOG_FILE = LOG_DIR / f"log_{SCRIPT_NAME}.log"

# 确保目录存在
CONFIG_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DEFAULT_PASSWORDS = ["123456", "666666"]

# 默认 7z 路径候选（Windows）
DEFAULT_7Z_PATHS = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]

def find_7z():
    """自动查找 7z.exe"""
    for path in DEFAULT_7Z_PATHS:
        if Path(path).exists():
            return path
    return ""

# ================== 工具函数 ==================

def log_message(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {msg}"
    print(full_msg)
    with open(PROCESS_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(full_msg + "\n")

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                config.setdefault("zip_path", "")
                config.setdefault("passwords", DEFAULT_PASSWORDS.copy())
                config.setdefault("seven_zip_path", find_7z())
                return config
        except Exception as e:
            log_message(f"加载配置失败: {e}")
    return {
        "zip_path": "",
        "passwords": DEFAULT_PASSWORDS.copy(),
        "seven_zip_path": find_7z()
    }

def save_config(zip_path, passwords, seven_zip_path):
    config = {
        "zip_path": str(zip_path),
        "passwords": passwords,
        "seven_zip_path": str(seven_zip_path)
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        log_message("配置已保存")
    except Exception as e:
        log_message(f"保存配置失败: {e}")
        messagebox.showerror("错误", f"无法保存配置:\n{e}")

def try_extract_with_7z(zip_path, password, seven_zip_path, temp_dir):
    """
    使用 7z 尝试解压到临时目录
    返回: (success: bool, output: str)
    """
    if not Path(seven_zip_path).exists():
        raise FileNotFoundError(f"7z 未找到: {seven_zip_path}")

    cmd = [
        seven_zip_path,
        'x',               # 解压完整路径
        '-o' + str(temp_dir),  # 输出目录
        '-p' + password,   # 密码
        '-y',              # 自动确认
        str(zip_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30  # 防止卡死
        )
        output = result.stdout
        success = result.returncode == 0

        # 额外检查：即使 returncode=0，也可能因密码错而跳过所有文件
        if success and "Wrong password" in output:
            success = False

        return success, output
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)

# ================== GUI 主程序 ==================

class ZipPasswordCrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ZIP 密码破解工具（基于 7-Zip）")
        self.root.geometry("750x550")
        self.root.resizable(True, True)

        config = load_config()
        self.zip_path = config["zip_path"]
        self.passwords = config["passwords"]
        self.seven_zip_path = config["seven_zip_path"]

        self.create_widgets()
        self.update_ui()

    def create_widgets(self):
        # 7z 路径设置
        top_frame = tk.Frame(self.root)
        top_frame.pack(pady=5, fill=tk.X, padx=20)

        tk.Label(top_frame, text="7-Zip 路径:", font=("微软雅黑", 9)).pack(side=tk.LEFT)
        self.seven_zip_label = tk.Label(top_frame, text="", fg="green", anchor="w", width=50)
        self.seven_zip_label.pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text="选择 7z.exe", command=self.select_7z).pack(side=tk.RIGHT)

        # ZIP 文件选择
        zip_frame = tk.Frame(self.root)
        zip_frame.pack(pady=5, fill=tk.X, padx=20)
        tk.Label(zip_frame, text="ZIP 文件:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.zip_label = tk.Label(zip_frame, text="未选择", fg="blue", anchor="w", width=50)
        self.zip_label.pack(side=tk.LEFT, padx=10)
        tk.Button(zip_frame, text="选择 ZIP", command=self.select_zip).pack(side=tk.RIGHT)

        # 密码管理
        mid_frame = tk.Frame(self.root)
        mid_frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=20)

        list_frame = tk.Frame(mid_frame)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(list_frame, text="密码库:", font=("微软雅黑", 10)).pack(anchor="w")
        self.password_listbox = tk.Listbox(list_frame, height=10)
        self.password_listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        btn_frame = tk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        tk.Button(btn_frame, text="添加密码", command=self.add_password).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="编辑选中", command=self.edit_password).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="删除选中", command=self.delete_password).pack(side=tk.LEFT, padx=2)

        # 双击编辑
        self.password_listbox.bind('<Double-1>', lambda e: self.edit_password())

        # 操作按钮
        action_frame = tk.Frame(mid_frame)
        action_frame.pack(side=tk.RIGHT, padx=20, fill=tk.Y)
        self.crack_btn = tk.Button(action_frame, text="尝试解压\n(使用7z)", command=self.start_crack,
                  bg="#4CAF50", fg="white", font=("微软雅黑", 10), width=12, height=3)
        self.crack_btn.pack(pady=10)
        tk.Button(action_frame, text="重置密码库", command=self.reset_passwords,
                  bg="#f44336", fg="white", font=("微软雅黑", 10), width=12).pack(pady=10)

        self._crack_thread = None

        # 日志
        log_frame = tk.Frame(self.root)
        log_frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=20)
        tk.Label(log_frame, text="操作日志:", font=("微软雅黑", 10)).pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state='disabled', wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.load_log_to_gui()

    def update_ui(self):
        self.seven_zip_label.config(text=self.seven_zip_path or "未设置")
        self.zip_label.config(text=self.zip_path if self.zip_path else "未选择")
        self.password_listbox.delete(0, tk.END)
        for pwd in self.passwords:
            self.password_listbox.insert(tk.END, pwd)

    def select_7z(self):
        path = filedialog.askopenfilename(
            title="选择 7z.exe",
            filetypes=[("Executable", "7z.exe")]
        )
        if path:
            self.seven_zip_path = path
            self.update_ui()
            save_config(self.zip_path, self.passwords, self.seven_zip_path)
            self.append_log(f"7z 路径已设置: {path}")

    def select_zip(self):
        path = filedialog.askopenfilename(title="选择 ZIP 压缩包", filetypes=[("ZIP files", "*.zip")])
        if path:
            self.zip_path = path
            self.update_ui()
            save_config(self.zip_path, self.passwords, self.seven_zip_path)
            self.append_log(f"已选择 ZIP 文件: {path}")

    def add_password(self):
        pwd = simpledialog.askstring("添加密码", "请输入新密码:")
        if pwd and pwd.strip():
            pwd = pwd.strip()
            if pwd not in self.passwords:
                self.passwords.append(pwd)
                self.update_ui()
                save_config(self.zip_path, self.passwords, self.seven_zip_path)
                self.append_log(f"添加密码: {pwd}")
            else:
                messagebox.showinfo("提示", "密码已存在")
        elif pwd is None:
            return
        else:
            messagebox.showwarning("警告", "密码不能为空")

    def edit_password(self):
        sel = self.password_listbox.curselection()
        if not sel:
            messagebox.showwarning("警告", "请先选择一个密码")
            return
        idx = sel[0]
        old_pwd = self.passwords[idx]
        new_pwd = simpledialog.askstring("编辑密码", "修改密码:", initialvalue=old_pwd)
        if new_pwd is None:
            return
        new_pwd = new_pwd.strip()
        if not new_pwd:
            messagebox.showwarning("警告", "密码不能为空")
            return
        if new_pwd == old_pwd:
            return
        if new_pwd in self.passwords:
            messagebox.showinfo("提示", "该密码已存在")
            return
        self.passwords[idx] = new_pwd
        self.update_ui()
        save_config(self.zip_path, self.passwords, self.seven_zip_path)
        self.append_log(f"编辑密码: {old_pwd} -> {new_pwd}")

    def delete_password(self):
        sel = self.password_listbox.curselection()
        if not sel:
            messagebox.showwarning("警告", "请先选择一个密码")
            return
        idx = sel[0]
        pwd = self.passwords[idx]
        del self.passwords[idx]
        self.update_ui()
        save_config(self.zip_path, self.passwords, self.seven_zip_path)
        self.append_log(f"删除密码: {pwd}")

    def reset_passwords(self):
        if messagebox.askyesno("确认", "重置密码库为默认？当前密码将被覆盖！"):
            self.passwords = DEFAULT_PASSWORDS.copy()
            self.update_ui()
            save_config(self.zip_path, self.passwords, self.seven_zip_path)
            self.append_log("密码库已重置为默认")

    def start_crack(self):
        """启动后台线程执行破解，避免界面卡死"""
        if self._crack_thread and self._crack_thread.is_alive():
            messagebox.showinfo("提示", "正在尝试中，请稍候...")
            return
        if not self.zip_path or not Path(self.zip_path).exists():
            messagebox.showerror("错误", "请选择有效的 ZIP 文件")
            return
        if not self.seven_zip_path or not Path(self.seven_zip_path).exists():
            messagebox.showerror("错误", "请设置有效的 7z.exe 路径")
            return
        if not self.passwords:
            messagebox.showwarning("警告", "密码库为空")
            return

        self.crack_btn.config(state='disabled', text="尝试中...\n请稍候")
        self._crack_thread = threading.Thread(target=self._crack_worker, daemon=True)
        self._crack_thread.start()

    def _crack_worker(self):
        """后台线程：逐个密码尝试解压"""
        passwords = list(self.passwords)  # 拷贝，避免线程不安全
        zip_path = self.zip_path
        seven_zip_path = self.seven_zip_path

        self._ui_log(f"开始使用 7z 尝试解压: {Path(zip_path).name}")
        success = False
        correct_password = None

        temp_dir = SCRIPT_DIR / "temp_unzip"
        temp_dir.mkdir(exist_ok=True)

        try:
            for i, pwd in enumerate(passwords, 1):
                self._ui_log(f"尝试 ({i}/{len(passwords)}): {pwd}")

                # 清空临时目录
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                temp_dir.mkdir()

                try:
                    ok, output = try_extract_with_7z(zip_path, pwd, seven_zip_path, temp_dir)
                    if ok and any(temp_dir.iterdir()):
                        success = True
                        correct_password = pwd
                        self._ui_log(f"[OK] 成功! 密码: {pwd}, 文件已解压至: {temp_dir}")
                        break
                    else:
                        brief = output[:150].replace('\n', ' ') if output else ''
                        self._ui_log(f"[X] 失败: {pwd} | {brief}")
                except Exception as e:
                    self._ui_log(f"[!] 异常: {pwd} | 错误: {e}")
        finally:
            if not success and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

        # 回到主线程更新 UI
        self.root.after(0, self._crack_done, success, correct_password, str(temp_dir))

    def _crack_done(self, success, correct_password, temp_dir_str):
        """主线程：破解完成后恢复按钮并弹窗"""
        self.crack_btn.config(state='normal', text="尝试解压\n(使用7z)")
        if success:
            messagebox.showinfo("成功", f"密码正确!\n密码: {correct_password}\n\n解压结果保存在:\n{temp_dir_str}")
        else:
            self.append_log("所有密码均失败。")
            messagebox.showinfo("结果", "所有密码都尝试过了，没有成功。")

    def _ui_log(self, msg):
        """线程安全地写日志到 GUI"""
        self.root.after(0, self.append_log, msg)

    def append_log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        log_message(msg)

    def load_log_to_gui(self):
        if PROCESS_LOG_FILE.exists():
            try:
                with open(PROCESS_LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-100:]
                    self.log_text.config(state='normal')
                    self.log_text.insert(tk.END, "".join(lines))
                    self.log_text.config(state='disabled')
                    self.log_text.see(tk.END)
            except Exception as e:
                self.append_log(f"加载日志失败: {e}")

# ================== 启动 ==================

if __name__ == "__main__":
    root = tk.Tk()
    app = ZipPasswordCrackerApp(root)
    root.mainloop()
