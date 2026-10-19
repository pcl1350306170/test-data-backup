# -*- coding: utf-8 -*-
"""任务持久化：将任务列表保存到 data/tasks.json（单文件，全量读写）。

状态：pending | running | paused | stopping | cancelled | done | error | interrupted
"""
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
TASKS_PATH = os.path.join(DATA_DIR, "tasks.json")

# 视为"仍在进行中"的状态（重启后需标记为 interrupted）
ACTIVE_STATUSES = {"running", "paused", "stopping"}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_all() -> list:
    _ensure()
    if not os.path.isfile(TASKS_PATH):
        return []
    try:
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_all(tasks: list):
    _ensure()
    tmp = TASKS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TASKS_PATH)


def upsert(task: dict):
    """新增或更新一条任务（按 id 匹配），保持最新在最前。"""
    tasks = load_all()
    task["updated_at"] = _now()
    for i, t in enumerate(tasks):
        if t.get("id") == task.get("id"):
            tasks[i] = task
            break
    else:
        tasks.insert(0, task)
    save_all(tasks)


def get(task_id: str):
    for t in load_all():
        if t.get("id") == task_id:
            return t
    return None


def delete(task_id: str):
    """删除任务记录，返回被删除的任务对象。"""
    tasks = load_all()
    removed = None
    new = []
    for t in tasks:
        if t.get("id") == task_id:
            removed = t
        else:
            new.append(t)
    if removed is not None:
        save_all(new)
    return removed


def mark_interrupted() -> list:
    """服务启动时调用：把进行中状态改为 interrupted，返回被改写的任务列表。"""
    tasks = load_all()
    changed = []
    dirty = False
    for t in tasks:
        if t.get("status") in ACTIVE_STATUSES:
            t["status"] = "interrupted"
            t["updated_at"] = _now()
            changed.append(t)
            dirty = True
    if dirty:
        save_all(tasks)
    return changed
