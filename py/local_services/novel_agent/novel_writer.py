# -*- coding: utf-8 -*-
"""
本地 AI 小说生成核心模块
- 阶段1: 生成结构化大纲 (JSON)
- 阶段2: 按大纲逐章写正文, 存盘, 记录进度
- 支持: 暂停(章间生效) / 停止(立即) / 断点续写(从第N章) / 单章重写
"""
import json
import os
import re
import threading
import time
import datetime
import requests
import json5

CONFIG = {
    "ollama_host": "http://127.0.0.1:11434",
    "model": "mynovel:latest",
    "num_ctx": 16384,
    "num_predict": 2048,
    "temperature": 0.9,
    "repeat_penalty": 1.3,
    "frequency_penalty": 0.4,
    "outline_predict": 1024,
    "chapter_chars": 2000,
    "books_dir": "books",
}

class JobCancelled(Exception):
    pass

class OLLAMAError(Exception):
    pass

def load_config(cfg: dict):
    CONFIG.update(cfg)

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------- 调用模型
def chat(messages, options=None, on_chunk=None, cancel_event=None, read_timeout=3600):
    """流式调用 Ollama /api/chat。返回完整文本。"""
    opts = {
        "num_ctx": CONFIG["num_ctx"],
        "num_predict": CONFIG["num_predict"],
        "temperature": CONFIG["temperature"],
        "repeat_penalty": CONFIG["repeat_penalty"],
        "frequency_penalty": CONFIG["frequency_penalty"],
    }
    if options:
        opts.update(options)
    payload = {
        "model": CONFIG["model"],
        "messages": messages,
        "stream": True,
        "options": opts,
    }
    url = CONFIG["ollama_host"].rstrip("/") + "/api/chat"
    try:
        resp = requests.post(url, json=payload, stream=True, timeout=(15, read_timeout))
    except requests.exceptions.ConnectionError as e:
        raise OLLAMAError("无法连接 Ollama 服务（%s），请确认服务已启动" % CONFIG["ollama_host"])
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", "")
        except Exception:
            err = resp.text[:200]
        raise OLLAMAError("Ollama 返回错误 %s: %s" % (resp.status_code, err))

    text = ""
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if cancel_event is not None and cancel_event.is_set():
                raise JobCancelled()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            piece = (obj.get("message") or {}).get("content") or ""
            if piece:
                text += piece
                if on_chunk:
                    on_chunk(piece)
    except JobCancelled:
        raise
    except requests.exceptions.RequestException as e:
        raise OLLAMAError("请求中断: %s" % e)
    return text

def check_ollama():
    url = CONFIG["ollama_host"].rstrip("/") + "/api/version"
    try:
        r = requests.get(url, timeout=8)
        return r.status_code == 200
    except Exception:
        return False

# ---------------------------------------------------------------- 大纲生成
# 扁平结构：7B 模型对多层嵌套 JSON 稳定输出能力差，用一层数组更容易成功
OUTLINE_PROMPT = """你是一名小说大纲策划。根据用户要求生成大纲，只输出一个 JSON 对象，不要任何解释或多余文字。JSON 结构（字段名必须完全一致）：
{{
  "title": "书名",
  "genre": "题材",
  "target_words": 全书目标字数(数字),
  "synopsis": "全书简介，150字以内",
  "world": "世界观/背景设定，100字以内",
  "characters": [{{"name":"角色名","role":"主角/配角/反派","desc":"人物设定，50字以内"}}],
  "chapters": [{{"volume":"所属卷名","title":"章节标题","points":"本章核心情节要点，60字以内","hook":"本章结尾钩子，20字以内"}}]
}}
要求：章节数量与目标字数匹配（每章约{chapter_chars}字）；情节有起伏、有伏笔有回收；角色行为前后一致。

用户要求：{spec}"""

def parse_outline_json(raw: str):
    """从模型输出中提取第一个完整 JSON 对象（先标准解析，再宽容解析）。"""
    s = raw.strip()
    start = s.find("{")
    if start < 0:
        raise OLLAMAError("模型未返回 JSON 大纲（开头无 {）。原始输出前200字：%s" % s[:200])
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                block = s[start:i + 1]
                try:
                    return json.loads(block)
                except Exception:
                    try:
                        # json5 容忍尾逗号、未加引号的键等小错误
                        return json5.loads(block)
                    except Exception as e:
                        raise OLLAMAError("大纲 JSON 解析失败: %s。片段：%s" % (e, block[:200]))
    raise OLLAMAError("未找到完整的 JSON 对象。原始输出前200字：%s" % s[:200])

def normalize_outline(o: dict) -> dict:
    """把扁平 chapters 按 volume 字段分组为 volumes（兼容原结构）。"""
    if "volumes" in o and o["volumes"]:
        return o
    chapters = o.get("chapters", [])
    volumes = []
    order = []
    groups = {}
    for ch in chapters:
        v = ch.get("volume") or "第一卷"
        if v not in groups:
            groups[v] = {"title": v, "summary": "", "chapters": []}
            order.append(v)
        groups[v]["chapters"].append(ch)
    for v in order:
        volumes.append(groups[v])
    o["volumes"] = volumes
    return o

def generate_outline(spec: dict, log=None, cancel_event=None) -> dict:
    """生成大纲。spec: {genre, style, total_words, chapter_chars, extra}"""
    def _log(msg):
        if log:
            log(msg)
    parts = []
    if spec.get("genre"):
        parts.append("题材：" + spec["genre"])
    if spec.get("style"):
        parts.append("风格：" + spec["style"])
    if spec.get("total_words"):
        parts.append("全书目标字数约" + str(spec["total_words"]) + "字")
    if spec.get("chapter_chars"):
        parts.append("每章约" + str(spec["chapter_chars"]) + "字")
    if spec.get("extra"):
        parts.append("补充要求：" + spec["extra"])
    spec_text = "；".join(parts) if parts else "自由发挥，题材自定"
    prompt = OUTLINE_PROMPT.format(chapter_chars=CONFIG["chapter_chars"], spec=spec_text)

    _log("开始生成大纲（模型：%s）…" % CONFIG["model"])
    _log("请求内容：%s" % spec_text)
    # 结构化输出用更保守的参数：低温+低惩罚，减少提前结束与格式错误
    outline_opts = {
        "num_predict": CONFIG["outline_predict"],
        "temperature": 0.7,
        "repeat_penalty": 1.1,
        "frequency_penalty": 0.0,
    }
    raw = chat(
        [{"role": "user", "content": prompt}],
        options=outline_opts,
        on_chunk=lambda c: None,
        cancel_event=cancel_event,
    )
    try:
        outline = parse_outline_json(raw)
    except OLLAMAError as e:
        # 输出被截断或格式损坏：让模型基于残缺内容补全为完整 JSON
        _log("大纲 JSON 不完整（%s），尝试自动修复…" % e)
        fix_prompt = (
            "下面是一份被截断或有错误的小说大纲 JSON，请把它补全为一份完整、可解析的 JSON 对象，"
            "字段名保持：title, genre, target_words, synopsis, world, characters, chapters（每项含 volume,title,points,hook）。"
            "不要新增字段，不要解释，只输出 JSON。\n\n内容：\n" + raw[:3000]
        )
        raw2 = chat(
            [{"role": "user", "content": fix_prompt}],
            options=outline_opts,
            on_chunk=lambda c: None,
            cancel_event=cancel_event,
        )
        outline = parse_outline_json(raw2)
        _log("修复完成。")
    outline = normalize_outline(outline)
    _log("大纲生成完成：《%s》，共 %d 卷 %d 章" % (
        outline.get("title", "未命名"),
        len(outline.get("volumes", [])),
        sum(len(v.get("chapters", [])) for v in outline.get("volumes", [])),
    ))
    return outline

# ---------------------------------------------------------------- 上下文组装
def _safe_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t ]+', "_", title).strip("_")
    return name or "未命名"

def _brief(outline: dict) -> dict:
    """压缩大纲为常驻设定文本块。"""
    chars = outline.get("characters", [])
    char_lines = "；".join(
        "%s(%s)：%s" % (c.get("name", ""), c.get("role", ""), c.get("desc", ""))
        for c in chars[:10]
    )
    return {
        "title": outline.get("title", "未命名"),
        "genre": outline.get("genre", ""),
        "synopsis": outline.get("synopsis", ""),
        "world": outline.get("world", ""),
        "characters": char_lines,
    }

def _plot_progress(book_dir: str, max_lines=12) -> str:
    """读取剧情流水（压缩历史），只取最近 max_lines 行。"""
    p = os.path.join(book_dir, "剧情流水.md")
    if not os.path.exists(p):
        return "（尚未发生任何剧情）"
    with open(p, "r", encoding="utf-8") as f:
        lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    return "\n".join(lines[-max_lines:]) if lines else "（尚未发生任何剧情）"

def _last_ending(book_dir: str, n: int, tail_chars=400) -> str:
    """取上一章文件结尾，用于衔接。"""
    for i in range(n - 1, 0, -1):
        pat = os.path.join(book_dir, "章节", "%03d_*.md" % i)
        files = __import__("glob").glob(pat)
        if files:
            with open(files[0], "r", encoding="utf-8") as f:
                text = f.read().strip()
            return text[-tail_chars:] if text else "（无）"
    return "（本书第一章，无前文）"

def _chapter_files(book_dir: str):
    d = os.path.join(book_dir, "章节")
    if not os.path.isdir(d):
        return []
    return sorted(__import__("glob").glob(os.path.join(d, "*.md")))

def chapter_prompt(outline: dict, vol: dict, chap: dict, n: int, book_dir: str, chapter_chars: int) -> str:
    b = _brief(outline)
    progress = _plot_progress(book_dir)
    ending = _last_ending(book_dir, n)
    return f"""你是资深中文小说作家，正在创作长篇小说《{b['title']}》。请严格按下面的上下文写本章正文。

【全书设定】
题材：{b['genre']}
简介：{b['synopsis']}
世界观：{b['world']}
主要人物：{b['characters']}

【剧情进度】（已发生的事，保持连贯，不要推翻）
{progress}

【本章任务】
所属卷：{vol.get('title','')}（{vol.get('summary','')}）
本章标题：{chap.get('title','')}
本章要点：{chap.get('points','')}
本章结尾钩子：{chap.get('hook','')}
目标篇幅：约{chapter_chars}字

【上一章结尾】（衔接用）
{ending}

写作要求：
1. 只输出本章正文，不要输出标题、注释或任何解释；
2. 情节严格围绕本章要点展开，不偏离、不跳戏；
3. 不重复前文内容，不使用重复句式，不使用模板化套话；
4. 对话自然，描写有画面感，细节服务于情节；
5. 写到要点完成、落在结尾钩子上就自然收尾，不要无限展开。"""

# ---------------------------------------------------------------- 章节写作
def write_chapter(outline: dict, vol: dict, chap: dict, n: int, book_dir: str,
                  log=None, on_chunk=None, cancel_event=None) -> str:
    """写第 n 章正文（不含章标题行）。"""
    prompt = chapter_prompt(outline, vol, chap, n, book_dir, CONFIG["chapter_chars"])
    text = chat(
        [{"role": "user", "content": prompt}],
        on_chunk=on_chunk,
        cancel_event=cancel_event,
    )
    return text.strip()

def save_chapter(book_dir: str, n: int, title: str, text: str):
    d = os.path.join(book_dir, "章节")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%03d_%s.md" % (n, _safe_name(title)))
    with open(path, "w", encoding="utf-8") as f:
        f.write("# %s\n\n%s\n" % (title, text))
    return path

def load_progress(book_dir: str) -> dict:
    p = os.path.join(book_dir, "progress.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_progress(book_dir: str, progress: dict):
    progress["updated_at"] = now_str()
    with open(os.path.join(book_dir, "progress.json"), "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------- 任务执行
def run_outline_job(spec: dict, job: dict):
    """大纲任务。job: {id,type,state,log,cancel_event,pause_event,...}"""
    job["state"] = "running"
    try:
        outline = generate_outline(spec, log=job["log"], cancel_event=job["cancel_event"])
        title = outline.get("title", "未命名")
        book_dir = os.path.join(CONFIG["books_dir"], _safe_name(title))
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, "大纲.json"), "w", encoding="utf-8") as f:
            json.dump(outline, f, ensure_ascii=False, indent=2)
        with open(os.path.join(book_dir, "大纲.md"), "w", encoding="utf-8") as f:
            f.write("# %s\n\n## 简介\n%s\n\n## 世界观\n%s\n\n## 人物\n" % (title, outline.get("synopsis",""), outline.get("world","")))
            for c in outline.get("characters", []):
                f.write("- %s（%s）：%s\n" % (c.get("name",""), c.get("role",""), c.get("desc","")))
            f.write("\n## 分卷章节\n")
            for v in outline.get("volumes", []):
                f.write("\n### %s\n%s\n" % (v.get("title",""), v.get("summary","")))
                for ch in v.get("chapters", []):
                    f.write("- %s：%s（钩子：%s）\n" % (ch.get("title",""), ch.get("points",""), ch.get("hook","")))
        total = sum(len(v.get("chapters", [])) for v in outline.get("volumes", []))
        save_progress(book_dir, {
            "book_title": title, "total_chapters": total, "completed": 0,
            "chapters": [], "started_at": now_str(),
        })
        if not os.path.exists(os.path.join(book_dir, "剧情流水.md")):
            open(os.path.join(book_dir, "剧情流水.md"), "w", encoding="utf-8").close()
        job["book_dir"] = book_dir
        job["result"] = {"title": title, "total_chapters": total, "book_dir": book_dir}
        job["log"]("大纲已保存到 %s" % book_dir)
        job["state"] = "done"
    except JobCancelled:
        job["state"] = "stopped"
        job["log"]("任务已停止。")
    except Exception as e:
        job["state"] = "error"
        job["log"]("任务失败：%s" % e)

def run_novel_job(book: str, start_chapter: int, job: dict):
    """按大纲逐章写正文。book 为书名（books 目录下的子目录名）。"""
    book_dir = os.path.join(CONFIG["books_dir"], book)
    op = os.path.join(book_dir, "大纲.json")
    if not os.path.exists(op):
        job["state"] = "error"
        job["log"]("未找到大纲文件：%s" % op)
        return
    with open(op, "r", encoding="utf-8") as f:
        outline = json.load(f)

    progress = load_progress(book_dir)
    completed = progress.get("completed", 0)
    if not start_chapter:
        start_chapter = completed + 1

    chapters = []
    for v in outline.get("volumes", []):
        for ch in v.get("chapters", []):
            chapters.append((v, ch))
    total = len(chapters)
    if total == 0:
        job["state"] = "error"
        job["log"]("大纲没有任何章节。")
        return

    job["state"] = "running"
    job["total"] = total
    job["log"]("开始写作《%s》，共 %d 章，从第 %d 章开始…" % (outline.get("title",""), total, start_chapter))
    job["log"]("预计每章 %d 字，本机速度约1字/秒，请耐心等待。" % CONFIG["chapter_chars"])

    flow_path = os.path.join(book_dir, "剧情流水.md")
    flow_lines = []
    if os.path.exists(flow_path):
        with open(flow_path, "r", encoding="utf-8") as f:
            flow_lines = [x for x in f.read().splitlines() if x.strip()]

    try:
        for idx in range(start_chapter - 1, total):
            # 暂停检查（章间生效）
            while job["pause_event"].is_set():
                if job["cancel_event"].is_set():
                    raise JobCancelled()
                time.sleep(1)
            if job["cancel_event"].is_set():
                raise JobCancelled()

            n = idx + 1
            vol, chap = chapters[idx]
            job["current_chapter"] = n
            job["log"]("── 第 %d/%d 章《%s》开始…" % (n, total, chap.get("title","")))
            # 写作（每50字符上报一次进度）
            last_report = [0]
            def _chunk(c):
                job["chunk_chars"] = job.get("chunk_chars", 0) + len(c.replace(" ", ""))
                if job["chunk_chars"] - last_report[0] >= 100:
                    last_report[0] = job["chunk_chars"]
                    job["log"]("  第 %d 章已写约 %d 字…" % (n, job["chunk_chars"]))
            text = write_chapter(outline, vol, chap, n, book_dir,
                                 log=None, on_chunk=_chunk,
                                 cancel_event=job["cancel_event"])
            path = save_chapter(book_dir, n, chap.get("title", ""), text)
            # 更新进度与剧情流水
            flow_lines.append("第%03d章《%s》：%s" % (n, chap.get("title",""), chap.get("points","")))
            with open(flow_path, "w", encoding="utf-8") as f:
                f.write("\n".join(flow_lines) + "\n")
            progress = load_progress(book_dir)
            chs = progress.get("chapters", [])
            chs.append({"n": n, "title": chap.get("title", ""), "file": path})
            save_progress(book_dir, {
                "book_title": outline.get("title", ""),
                "total_chapters": total,
                "completed": n,
                "chapters": chs,
                "started_at": progress.get("started_at", now_str()),
            })
            job["completed"] = n
            job["chunk_chars"] = 0
            job["log"]("第 %d 章完成（约%d字），已保存。进度 %d/%d" % (
                n, len(text.replace(" ", "")), n, total))
        job["state"] = "done"
        job["log"]("全部章节写作完成！")
    except JobCancelled:
        job["state"] = "stopped"
        job["log"]("任务已停止。已完成的章节已保存，可从下一章继续。")
    except Exception as e:
        job["state"] = "error"
        job["log"]("任务失败（已写章节已保存）：%s" % e)

def run_chapter_job(book: str, n: int, job: dict):
    """单章重写：用已有大纲重写第 n 章，覆盖原文件。"""
    book_dir = os.path.join(CONFIG["books_dir"], book)
    op = os.path.join(book_dir, "大纲.json")
    if not os.path.exists(op):
        job["state"] = "error"; job["log"]("未找到大纲：%s" % op); return
    with open(op, "r", encoding="utf-8") as f:
        outline = json.load(f)
    chapters = []
    for v in outline.get("volumes", []):
        for ch in v.get("chapters", []):
            chapters.append((v, ch))
    if n < 1 or n > len(chapters):
        job["state"] = "error"; job["log"]("章节号 %d 超出范围（共 %d 章）。" % (n, len(chapters))); return
    job["state"] = "running"
    job["log"]("重写第 %d 章《%s》…" % (n, chapters[n-1][1].get("title","")))
    try:
        vol, chap = chapters[n - 1]
        def _chunk(c):
            job["chunk_chars"] = job.get("chunk_chars", 0) + len(c.replace(" ", ""))
        text = write_chapter(outline, vol, chap, n, book_dir,
                             on_chunk=_chunk, cancel_event=job["cancel_event"])
        save_chapter(book_dir, n, chap.get("title", ""), text)
        job["log"]("第 %d 章重写完成。" % n)
        job["state"] = "done"
    except JobCancelled:
        job["state"] = "stopped"; job["log"]("已停止。")
    except Exception as e:
        job["state"] = "error"; job["log"]("失败：%s" % e)
