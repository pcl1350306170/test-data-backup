# -*- coding: utf-8 -*-
"""
md播客脚本保存到资产库
=====================
遍历指定目录下所有 .md 文件，将内容批量保存到远程资产库（geeker/public/assets）。

流程:
    1. 提取 md 一级标题（自动向下查找第一个 `# xxx`）
    2. GET /assets?keyword={标题}  → total>0 视为已存在，跳过
    3. POST /assets 提交完整内容
    4. 成功保存的文件名写入本地配置 saved_files，下次直接跳过不再查接口
    5. 单个文件失败仅记录日志，不中断整体任务
"""

import os
import sys
import json
import queue
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import requests
except ImportError:
    requests = None

# ================== 配置与常量 ==================
SCRIPT_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
SCRIPT_NAME = "md_podcast_to_asset"
CONFIG_DIR = SCRIPT_DIR / "json"
CONFIG_PATH = CONFIG_DIR / f"config_{SCRIPT_NAME}.json"
CONFIG_DIR.mkdir(exist_ok=True)

DEFAULT_INPUT_DIR = r"D:\CODE\Python\test-data-backup\AI Work Space\AI绘本脚本"
DEFAULT_API_BASE = "http://localhost/api/geeker/public/assets"
TITLE_PREFIX = "AI播客脚本- "
FIXED_TYPE = "SOLUTION"
FIXED_TAGS = ["AI播客脚本"]

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


# ================== 工具函数 ==================
def extract_title(md_text: str) -> str:
    """从 md 内容中提取一级标题（第一行以 '# ' 开头），自动向下查找。"""
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


# ================== 主界面 ==================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("md播客脚本保存到资产库")
        root.geometry("820x600")

        # 变量
        self.input_dir = tk.StringVar(value=DEFAULT_INPUT_DIR)
        self.api_base = tk.StringVar(value=DEFAULT_API_BASE)
        self.skip_cache_var = tk.BooleanVar(value=False)  # 忽略已保存记录，强制查询接口
        self.status_var = tk.StringVar(value="就绪")

        # 运行状态
        self.running = False
        self.stop_flag = False
        self.saved_files: set[str] = set()
        self._log_queue: "queue.Queue[str]" = queue.Queue()

        # UI
        self._build_ui()
        self._load_config()

        # 日志队列轮询
        self.root.after(100, self._drain_log_queue)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 顶部：目录选择
        frm_dir = ttk.LabelFrame(self.root, text="md 文件目录")
        frm_dir.pack(fill="x", **pad)
        ttk.Entry(frm_dir, textvariable=self.input_dir).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )
        ttk.Button(frm_dir, text="浏览...", command=self._choose_dir).pack(
            side="left", padx=6, pady=6
        )

        # 接口地址
        frm_api = ttk.LabelFrame(self.root, text="资产库接口地址")
        frm_api.pack(fill="x", **pad)
        ttk.Entry(frm_api, textvariable=self.api_base).pack(
            side="left", fill="x", expand=True, padx=6, pady=6
        )

        # 选项 & 操作
        frm_op = ttk.Frame(self.root)
        frm_op.pack(fill="x", **pad)
        ttk.Checkbutton(
            frm_op,
            text="忽略已保存记录（强制查询接口）",
            variable=self.skip_cache_var,
        ).pack(side="left", padx=6)
        self.btn_start = ttk.Button(frm_op, text="开始", command=self._start)
        self.btn_start.pack(side="right", padx=6)
        self.btn_stop = ttk.Button(frm_op, text="停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", padx=6)
        ttk.Button(frm_op, text="清空日志", command=self._clear_log).pack(side="right", padx=6)

        # 状态栏
        frm_status = ttk.Frame(self.root)
        frm_status.pack(fill="x", **pad)
        ttk.Label(frm_status, textvariable=self.status_var, foreground="#0a6").pack(side="left")

        # 日志框
        frm_log = ttk.LabelFrame(self.root, text="运行日志")
        frm_log.pack(fill="both", expand=True, **pad)
        self.txt_log = scrolledtext.ScrolledText(
            frm_log, wrap="word", height=20, state="disabled", font=("Consolas", 9)
        )
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.input_dir.get() or DEFAULT_INPUT_DIR)
        if d:
            self.input_dir.set(os.path.normpath(d))

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ---------- 日志输出 ----------
    def _log(self, msg: str):
        """线程安全：写入队列，由主线程轮询刷新到 UI。同时写入 logger。"""
        logger.info(msg)
        self._log_queue.put(msg)

    def _drain_log_queue(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.txt_log.configure(state="normal")
                self.txt_log.insert("end", msg + "\n")
                self.txt_log.see("end")
                self.txt_log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    # ---------- 配置持久化 ----------
    def _save_config(self):
        config = {
            "input_dir": self.input_dir.get(),
            "api_base": self.api_base.get(),
            "saved_files": sorted(self.saved_files),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.debug("配置已保存: %s" % CONFIG_PATH)
        except Exception as e:
            logger.error("保存配置失败: %s" % e)

    def _persist_saved_files(self):
        """仅将 saved_files 增量写入配置文件（后台线程可安全调用）。
        避免任务中途崩溃/断电导致已保存记录丢失。
        """
        try:
            cfg = {}
            if CONFIG_PATH.exists():
                try:
                    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                        cfg = json.load(f) or {}
                except Exception:
                    cfg = {}
            cfg["input_dir"] = self.input_dir.get()
            cfg["api_base"] = self.api_base.get()
            cfg["saved_files"] = sorted(self.saved_files)
            # 先写临时文件再替换，避免写入中途崩溃导致 json 损坏
            tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, CONFIG_PATH)
        except Exception as e:
            logger.error("增量保存 saved_files 失败: %s" % e)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if cfg.get("input_dir"):
                    self.input_dir.set(cfg["input_dir"])
                if cfg.get("api_base"):
                    self.api_base.set(cfg["api_base"])
                saved = cfg.get("saved_files") or []
                self.saved_files = set(saved)
                logger.info("已加载配置: %s（本地已保存记录 %d 条）" % (CONFIG_PATH, len(self.saved_files)))
        except Exception as e:
            logger.error("加载配置失败: %s" % e)

    # ---------- 启停 ----------
    def _start(self):
        if self.running:
            return
        if requests is None:
            messagebox.showerror("依赖缺失", "未安装 requests 库，请先执行: pip install requests")
            return

        in_dir = self.input_dir.get().strip()
        api = self.api_base.get().strip()
        if not in_dir or not Path(in_dir).is_dir():
            messagebox.showwarning("提示", "请选择有效的 md 文件目录")
            return
        if not api:
            messagebox.showwarning("提示", "请填写资产库接口地址")
            return

        # 保存配置
        self._save_config()

        self.running = True
        self.stop_flag = False
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_var.set("运行中...")

        t = threading.Thread(target=self._run_task, args=(in_dir, api), daemon=True)
        t.start()

    def _stop(self):
        if not self.running:
            return
        self.stop_flag = True
        self._log("⏹ 用户请求停止，等待当前文件处理完成...")

    def _on_task_done(self, total: int, saved: int, skipped: int, failed: int):
        self.running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_var.set(
            f"完成：共 {total}，新增 {saved}，跳过 {skipped}，失败 {failed}"
        )
        self._save_config()

    # ---------- 核心任务 ----------
    def _run_task(self, in_dir: str, api_base: str):
        total = saved = skipped = failed = 0
        try:
            md_files = sorted(Path(in_dir).glob("*.md"))
            self._log(f"📂 目录: {in_dir}")
            self._log(f"🔗 接口: {api_base}")
            self._log(f"📄 发现 md 文件 {len(md_files)} 个，本地已保存记录 {len(self.saved_files)} 个")

            if not md_files:
                self._log("⚠️ 目录下没有 md 文件")
                return  # 由 finally 统一触发 _on_task_done

            for idx, md_path in enumerate(md_files, 1):
                if self.stop_flag:
                    self._log("⏹ 已停止")
                    break

                total += 1
                name = md_path.name
                self._log(f"[{idx}/{len(md_files)}] 处理: {name}")

                # 1. 本地已保存记录命中，直接跳过
                if name in self.saved_files and not self.skip_cache_var.get():
                    skipped += 1
                    self._log(f"    ↪ 本地记录命中，跳过")
                    continue

                # 2. 读取文件
                try:
                    content = md_path.read_text(encoding="utf-8")
                except Exception as e:
                    failed += 1
                    self._log(f"    ❌ 读取失败: {e}")
                    logger.error("读取失败 %s: %s" % (md_path, e))
                    continue

                # 3. 提取标题
                title = extract_title(content)
                if not title:
                    failed += 1
                    self._log(f"    ❌ 未找到一级标题（# xxx），跳过")
                    logger.warning("未找到一级标题: %s" % md_path)
                    continue

                # 4. 查询是否已存在
                try:
                    exists = self._check_exists(api_base, title)
                except Exception as e:
                    failed += 1
                    self._log(f"    ❌ 查询接口失败: {e}")
                    logger.error("查询接口失败 %s: %s" % (title, e))
                    continue

                if exists:
                    skipped += 1
                    self.saved_files.add(name)
                    self._persist_saved_files()  # 立即落盘
                    self._log(f"    ↪ 远程已存在《{title}》，跳过并写入本地记录")
                    continue

                # 5. 保存
                try:
                    ok = self._save_asset(api_base, title, content)
                except Exception as e:
                    failed += 1
                    self._log(f"    ❌ 保存失败: {e}")
                    logger.error("保存失败 %s: %s" % (title, e))
                    continue

                if ok:
                    saved += 1
                    self.saved_files.add(name)
                    self._persist_saved_files()  # 立即落盘，避免中途崩溃丢失
                    self._log(f"    ✅ 保存成功: {title}")
                else:
                    failed += 1
                    self._log(f"    ❌ 保存失败（接口未返回成功）: {title}")

            self._log(
                f"🎉 任务结束：共 {total}，新增 {saved}，跳过 {skipped}，失败 {failed}"
            )
        except Exception as e:
            logger.exception("任务异常终止")
            self._log(f"💥 任务异常终止: {e}")
        finally:
            self.root.after(0, self._on_task_done, total, saved, skipped, failed)

    # ---------- HTTP 交互 ----------
    def _check_exists(self, api_base: str, keyword: str) -> bool:
        """GET 查询：total>0 视为已存在。"""
        resp = requests.get(api_base, params={"keyword": keyword}, timeout=15)
        resp.raise_for_status()
        data = resp.json() or {}
        if data.get("code") != 200:
            raise RuntimeError(f"接口返回异常 code={data.get('code')} msg={data.get('msg')}")
        total = (data.get("data") or {}).get("total", 0)
        return int(total) > 0

    def _save_asset(self, api_base: str, title: str, content: str) -> bool:
        """POST 保存资产。"""
        payload = {
            "type": FIXED_TYPE,
            "title": f"{TITLE_PREFIX}{title}",
            "description": title,
            "content": content,
            "language": "",
            "tags": FIXED_TAGS,
        }
        resp = requests.post(api_base, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json() or {}
        if data.get("code") != 200:
            logger.error("保存接口返回异常: %s" % data)
            return False
        return True


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
