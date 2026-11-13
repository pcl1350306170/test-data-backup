# -*- coding: utf-8 -*-
"""order_packager_core — 门诊/病房订单打包 Web 服务的公共内核。

被 menz_packager / ward_packager 两个服务共用：
- vcs.py        git 分支扫描、SVN 工作副本查找与提交、基础包查找
- node_env.py   nvm/Volta 版本列表 + PATH 注入（免 UAC 锁版本）
- browse.py     受限目录浏览（替代 Tk 的 filedialog）
- store.py      data/config.json 读写 + 历史记录 + 旧配置迁移
- engine.py     打包任务引擎（后台线程 + SSE 事件广播 + 可中止）
- base_server.py 统一 API 路由工厂
- profiles/     各业务的差异部分（打包步骤、参数校验、搜索逻辑）
"""
from .engine import PackEngine, RunContext
from .store import Store
from .base_server import create_app, run_server

__all__ = ["PackEngine", "RunContext", "Store", "create_app", "run_server"]
