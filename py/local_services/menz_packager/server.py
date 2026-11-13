# -*- coding: utf-8 -*-
"""门诊订单打包 Web 服务 — FastAPI 入口，端口 8802。

业务实现全部在 order_packager_core（与病房服务共用），本文件只做装配：
    profiles/menz.py  打包流程、搜索、校验
    base_server.py    /api/* 路由与 SSE 进度推送

启动：python server.py  或双击 start.bat（Hub 托管时用 pythonw，不弹浏览器）
访问：http://127.0.0.1:8802
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent))          # py/local_services，用于 import 公共 core

from order_packager_core.base_server import create_app, run_server  # noqa: E402
from order_packager_core.profiles import menz as menz_profile       # noqa: E402

DEFAULT_PORT = 8802

app = create_app(menz_profile.profile, BASE_DIR)

if __name__ == "__main__":
    run_server(app, menz_profile.profile, BASE_DIR, DEFAULT_PORT)
