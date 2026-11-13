# -*- coding: utf-8 -*-
"""配置与历史记录存储。

- 主配置：{service_dir}/data/config.json（原子写），沿用服务标准目录约定
- 迁移：首次启动时若新配置不存在，只读读取旧 .pyw 的 json/config_xxx.json，
        把关键字、基础目录、历史记录带过来；旧文件保持不动，桌面版仍可用
- 历史记录：仍存在 config.json 的 history_records 里（与桌面版结构一致），按业务键去重，
        上限 100 条
"""
import threading
from pathlib import Path

from .util import read_json, write_json

HISTORY_LIMIT = 100


class Store:
    def __init__(self, service_dir, defaults, legacy_paths=(), allowed_keys=None, reset_keys=()):
        self.service_dir = Path(service_dir)
        self.data_dir = self.service_dir / "data"
        self.config_path = self.data_dir / "config.json"
        self.defaults = dict(defaults)
        self.legacy_paths = [Path(p) for p in (legacy_paths or ())]
        # 迁移时强制回落到默认值的键（桌面版习惯不同，如 auto_commit_svn 在服务里默认关）
        self.reset_keys = set(reset_keys or ())
        self.allowed_keys = set(allowed_keys or self.defaults.keys())
        self.allowed_keys.add("history_records")
        self._lock = threading.RLock()   # 可重入：save/load 内部会再次取锁
        self._mem = None                 # 配置内存缓存，首次 load 时填充
        self.migrated_from = ""

    # ── 基础读写 ──────────────────────────────────────

    def _migrate(self):
        for legacy in self.legacy_paths:
            try:
                if legacy.is_file():
                    data = read_json(legacy)
                    if isinstance(data, dict) and data:
                        cfg = dict(self.defaults)
                        cfg.update({k: v for k, v in data.items()
                                    if k in self.allowed_keys})
                        for k in self.reset_keys:
                            cfg[k] = self.defaults.get(k)
                        self.migrated_from = str(legacy)
                        write_json(self.config_path, cfg)
                        return cfg
            except OSError:
                continue
        return None

    def load(self, force=False):
        with self._lock:
            if self._mem is not None and not force:
                return dict(self._mem)
            cfg = read_json(self.config_path)
            if not isinstance(cfg, dict):
                cfg = self._migrate()
            if not isinstance(cfg, dict):
                cfg = dict(self.defaults)
            merged = dict(self.defaults)
            merged.update(cfg)
            self._mem = merged
            return dict(merged)

    def save(self, cfg):
        with self._lock:
            clean = {k: v for k, v in cfg.items() if k in self.allowed_keys}
            self._mem = dict(self.defaults)
            self._mem.update(clean)
            write_json(self.config_path, self._mem)
            return dict(self._mem)

    def update(self, patch):
        """只接受白名单键，其余忽略（防止页面乱传键把配置撑爆）。"""
        patch = patch or {}
        cfg = self.load()
        applied = {}
        for k, v in patch.items():
            if k in self.allowed_keys:
                cfg[k] = v
                applied[k] = v
        self.save(cfg)
        return {"applied": applied, "ignored": [k for k in patch if k not in applied]}

    def get(self, key, default=None):
        return self.load().get(key, default)

    # ── 历史记录 ──────────────────────────────────────

    def history(self):
        records = self.load().get("history_records") or []
        return records if isinstance(records, list) else []

    def add_history(self, record, dedup_key=""):
        """按 dedup_key（如订单信息/项目类型+目录）去重后插到最前。"""
        with self._lock:
            cfg = self.load()
            records = list(cfg.get("history_records") or [])
            if dedup_key:
                records = [r for r in records if r.get(dedup_key) != record.get(dedup_key)]
            records.insert(0, record)
            cfg["history_records"] = records[:HISTORY_LIMIT]
        self.save(cfg)
        return len(cfg["history_records"])

    def delete_history(self, index):
        with self._lock:
            cfg = self.load()
            records = list(cfg.get("history_records") or [])
            try:
                index = int(index)
            except (TypeError, ValueError):
                return {"ok": False, "error": "序号非法"}
            if not (0 <= index < len(records)):
                return {"ok": False, "error": "序号超出范围"}
            removed = records.pop(index)
            cfg["history_records"] = records
        self.save(cfg)
        return {"ok": True, "removed": removed}

    def clear_history(self):
        with self._lock:
            cfg = self.load()
            count = len(cfg.get("history_records") or [])
            cfg["history_records"] = []
        self.save(cfg)
        return count
