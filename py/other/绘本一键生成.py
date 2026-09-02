# -*- coding: utf-8 -*-
"""
绘本一键生成 - 串联"音频生成"和"视频合成"的编排脚本
=====================================================
工作流程：
  1. 输入关键字（如"古人-绝句(迟日)-杜甫"）
  2. 自动匹配 JSON 脚本文件
  3. 自动创建输出目录结构
  4. 调用"绘本旁白音频生成器"生成音频
  5. 自动匹配图片目录
  6. 调用"音频合并转视频"生成视频

运行方式：
  python 绘本一键生成.py
"""

import json
import os
import sys
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

# ---------- 路径与配置 ----------
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "绘本一键生成"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

# ---------- 日志（可选依赖） ----------
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

# ---------- 固定目录配置 ----------
JSON_SCRIPTS_DIR = Path(r"D:\CODE\Python\test-data-backup\AI Work Space\AI绘本脚本")
AI_BOOKS_DIR = Path(r"D:\FILES\糖蛋蛋(＾Ｕ＾)ノ~ＹＯ\AI绘本")
IMAGES_BAK_DIR = AI_BOOKS_DIR / "bak"

# 子脚本路径
AUDIO_GEN_SCRIPT = SCRIPT_DIR / "绘本旁白音频生成器.py"
VIDEO_MERGE_SCRIPT = SCRIPT_DIR / "音频合并转视频.pyw"

# Windows subprocess 不弹黑框
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("绘本一键生成")
        root.geometry("700x500")
        root.minsize(600, 450)

        self.keyword_var = tk.StringVar()
        self.json_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.image_dir_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self._stop_flag = False
        self._thread = None

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # 关键字输入
        frm = ttk.LabelFrame(self.root, text="1. 输入关键字")
        frm.pack(fill="x", **pad)
        entry = ttk.Entry(frm, textvariable=self.keyword_var, width=50)
        entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        entry.bind("<Return>", lambda e: self._auto_match())
        ttk.Button(frm, text="匹配", command=self._auto_match).pack(side="right", padx=8, pady=8)

        # 匹配结果
        frm = ttk.LabelFrame(self.root, text="2. 匹配结果（可手动修改）")
        frm.pack(fill="x", **pad)

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="JSON 脚本:", width=10).pack(side="left")
        ttk.Entry(row, textvariable=self.json_path_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览", command=self._browse_json).pack(side="right")

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="输出目录:", width=10).pack(side="left")
        ttk.Entry(row, textvariable=self.output_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览", command=self._browse_output).pack(side="right")

        row = ttk.Frame(frm)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="图片目录:", width=10).pack(side="left")
        ttk.Entry(row, textvariable=self.image_dir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="浏览", command=self._browse_images).pack(side="right")

        # 进度
        frm = ttk.Frame(self.root)
        frm.pack(fill="x", **pad)
        self.progress_bar = ttk.Progressbar(frm, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(8, 4))
        ttk.Label(frm, textvariable=self.status_var, width=15).pack(side="right", padx=4)

        # 按钮
        frm = ttk.Frame(self.root)
        frm.pack(fill="x", **pad)
        self.btn_start = ttk.Button(frm, text="开始生成", command=self._start)
        self.btn_start.pack(side="left", expand=True, padx=8)
        self.btn_stop = ttk.Button(frm, text="停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", expand=True, padx=8)

        # 日志
        frm = ttk.LabelFrame(self.root, text="日志")
        frm.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(frm, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

    def _log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _browse_json(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if p:
            self.json_path_var.set(p)

    def _browse_output(self):
        p = filedialog.askdirectory()
        if p:
            self.output_dir_var.set(p)

    def _browse_images(self):
        p = filedialog.askdirectory()
        if p:
            self.image_dir_var.set(p)

    def _auto_match(self):
        """根据关键字自动匹配 JSON、输出目录、图片目录"""
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入关键字")
            return

        self._log(f"[匹配] 关键字: {keyword}")

        # 1. 匹配 JSON
        json_path = JSON_SCRIPTS_DIR / f"{keyword}.json"
        if json_path.exists():
            self.json_path_var.set(str(json_path))
            self._log(f"  ✓ JSON: {json_path.name}")
        else:
            # 模糊匹配
            matches = [f for f in JSON_SCRIPTS_DIR.glob("*.json") if keyword in f.stem]
            if matches:
                self.json_path_var.set(str(matches[0]))
                self._log(f"  ~ JSON (模糊): {matches[0].name}")
            else:
                self._log(f"  ✗ JSON 未找到")
                messagebox.showwarning("未找到", f"未找到匹配的 JSON 文件:\n{json_path}")
                return

        # 2. 输出目录
        output_dir = AI_BOOKS_DIR / keyword
        output_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir_var.set(str(output_dir))
        self._log(f"  ✓ 输出目录: {output_dir}")

        # 3. 图片目录
        img_dir = IMAGES_BAK_DIR / keyword
        if img_dir.exists():
            self.image_dir_var.set(str(img_dir))
            self._log(f"  ✓ 图片目录: {img_dir.name}")
        else:
            # 模糊匹配
            matches = [d for d in IMAGES_BAK_DIR.iterdir() if d.is_dir() and keyword in d.name]
            if matches:
                self.image_dir_var.set(str(matches[0]))
                self._log(f"  ~ 图片目录 (模糊): {matches[0].name}")
            else:
                self._log(f"  ! 图片目录未找到（视频生成时将跳过）")

        self._log("[匹配完成]")

    def _start(self):
        """开始生成流程"""
        json_path = self.json_path_var.get().strip()
        output_dir = self.output_dir_var.get().strip()
        image_dir = self.image_dir_var.get().strip()

        if not json_path or not os.path.isfile(json_path):
            messagebox.showwarning("提示", "请先匹配或选择 JSON 脚本文件")
            return
        if not output_dir:
            messagebox.showwarning("提示", "请先匹配或选择输出目录")
            return

        self._save_config()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress_var.set(0)
        self._stop_flag = False

        self._thread = threading.Thread(target=self._work, args=(json_path, output_dir, image_dir), daemon=True)
        self._thread.start()

    def _stop(self):
        self._stop_flag = True
        self.status_var.set("正在停止...")
        self._log("[停止] 用户请求停止")

    def _work(self, json_path, output_dir, image_dir):
        """主工作流程"""
        try:
            audio_dir = os.path.join(output_dir, "音频")
            os.makedirs(audio_dir, exist_ok=True)

            # Step 1: 生成音频
            self._update_status("正在生成音频...", 10)
            self._log("=" * 40)
            self._log("[步骤1] 生成音频")

            cmd = [sys.executable, str(AUDIO_GEN_SCRIPT), "--json", json_path, "--output", audio_dir]
            result = self._run_subprocess(cmd)
            if result.returncode != 0:
                self._log(f"[错误] 音频生成失败:\n{result.stderr}")
                self._finish(False, "音频生成失败")
                return
            self._log("[步骤1完成] 音频已生成")
            self._update_status("音频生成完成", 50)

            if self._stop_flag:
                self._finish(False, "已停止")
                return

            # Step 2: 合并音频 + 生成视频
            self._update_status("正在合并音频...", 60)
            self._log("=" * 40)
            self._log("[步骤2] 合并音频并生成视频")

            cmd = [sys.executable, str(VIDEO_MERGE_SCRIPT),
                   "--input", audio_dir,
                   "--output", output_dir,
                   "--video"]
            if image_dir and os.path.isdir(image_dir):
                cmd.extend(["--images", image_dir])
            else:
                self._log("[提示] 无图片目录，跳过视频生成")

            result = self._run_subprocess(cmd)
            if result.returncode != 0:
                self._log(f"[错误] 视频生成失败:\n{result.stderr}")
                self._finish(False, "视频生成失败")
                return

            self._log("[步骤2完成] 视频已生成")
            self._update_status("全部完成", 100)
            self._finish(True, f"全部完成!\n输出目录: {output_dir}")

        except Exception as e:
            self._log(f"[异常] {e}")
            self._finish(False, f"异常: {e}")

    def _run_subprocess(self, cmd):
        """运行子进程并实时输出日志"""
        self._log(f"  命令: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW
        )
        for line in process.stdout:
            if self._stop_flag:
                process.terminate()
                break
            line = line.rstrip()
            if line:
                self._log(f"  {line}")
                # 简单进度估算
                if "[INFO] 生成" in line and "段文本" in line:
                    pass
                elif "[DONE]" in line:
                    pass
        process.wait()
        return process

    def _update_status(self, text, progress):
        self.root.after(0, lambda: self.status_var.set(text))
        self.root.after(0, lambda: self.progress_var.set(progress))

    def _finish(self, success, message):
        self.root.after(0, lambda: self.btn_start.config(state="normal"))
        self.root.after(0, lambda: self.btn_stop.config(state="disabled"))
        self._log("=" * 40)
        self._log(f"[结果] {message}")
        logger.info("任务完成: success=%s, msg=%s", success, message)
        if success:
            self.root.after(0, lambda: messagebox.showinfo("完成", message))
        else:
            self.root.after(0, lambda: messagebox.showerror("失败", message))

    def _save_config(self):
        config = {
            "keyword": self.keyword_var.get(),
            "json_path": self.json_path_var.get(),
            "output_dir": self.output_dir_var.get(),
            "image_dir": self.image_dir_var.get(),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置已保存: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("keyword"):
                    self.keyword_var.set(cfg["keyword"])
                if cfg.get("json_path"):
                    self.json_path_var.set(cfg["json_path"])
                if cfg.get("output_dir"):
                    self.output_dir_var.set(cfg["output_dir"])
                if cfg.get("image_dir"):
                    self.image_dir_var.set(cfg["image_dir"])
                logger.info("已加载配置: %s", CONFIG_PATH)
        except Exception as e:
            logger.error("加载配置失败: %s", e)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
