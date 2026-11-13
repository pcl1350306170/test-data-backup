# -*- coding: utf-8 -*-
"""Web 层冒烟测试：通过 HTTP 走完整 load → preview → export → progress。"""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8801"
JSON_PATH = r"C:\Users\PCL13\Downloads\ttl\30d\export_data\44f012b6-a0df-4689-9653-e224774180e3\prod-grok-backend.json"
OUT_DIR = Path(r"D:\CODE\Python\test-data-backup\py\local_services\grok_exporter\web_smoke_output")

LOG = Path(__file__).parent / "web_smoke.log"
_log = LOG.open("w", encoding="utf-8")


def say(*args):
    line = " ".join(str(a) for a in args)
    print(line)
    _log.write(line + "\n")
    _log.flush()


def post(path, body=None):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


say("=" * 60)
say("WEB SMOKE TEST")
say("=" * 60)

say("\n[1] /api/ping")
say(get("/api/ping"))

say("\n[2] /api/load")
load = post("/api/load", {"path": JSON_PATH})
say("  path:", load["path"])
say("  size:", load["size"])
say("  summary:", load["summary"])
say("  sessions:")
for s in load["sessions"]:
    say(f"    #{s['index']} {s['title']} msgs={s['message_count']} strategy={s['ordering_strategy']}")

say("\n[3] /api/preview index=1 format=md")
prev = post("/api/preview", {"index": 1, "format": "md", "scope": "all"})
say("  title:", prev["title"])
say("  message_count:", prev["message_count"])
say("  text 前 200 字符：", prev["text"][:200].replace("\n", "\\n"))

say("\n[4] /api/export （3 会话 / MD+TXT / individual+merged）")
export = post("/api/export", {
    "options": {
        "formats": ["md", "txt"],
        "scope": "all",
        "organization": "both",
        "output_dir": str(OUT_DIR),
        "include_title": True,
        "include_time_meta": True,
        "include_sender_label": True,
        "include_timestamp": True,
        "include_separator": True,
        "preserve_markdown": True,
    },
    "selected": [s["index"] for s in load["sessions"]],
})
task_id = export["task_id"]
say("  task_id:", task_id)
say("  output_dir:", export["output_dir"])

say("\n[5] /api/progress 轮询")
cursor = 0
final = None
for _ in range(60):
    p = get(f"/api/progress?task_id={task_id}&since={cursor}")
    for ev in p["events"]:
        say("  ev:", ev.get("stage"), ev.get("current"), "/", ev.get("total"),
            ev.get("title", ""), ev.get("error", ""))
    cursor = p["next"]
    if p["done"]:
        final = p["result"]
        break
    time.sleep(0.3)
say("  done. result:")
say("   ", json.dumps({k: v for k, v in (final or {}).items() if k != "files"},
                       ensure_ascii=False))
say("    files 数量:", len((final or {}).get("files", [])))

say("\n[6] 验证落盘文件")
files = sorted(p.name for p in OUT_DIR.iterdir()) if OUT_DIR.exists() else []
for f in files:
    say("   ", f)
say("  合计:", len(files))

say("\n[7] /api/state 恢复")
st = get("/api/state")
say("  loaded:", st.get("loaded"), "sessions:", len(st.get("sessions", [])))

say("\nWEB SMOKE OK")
_log.close()
