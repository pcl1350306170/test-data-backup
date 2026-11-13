# -*- coding: utf-8 -*-
"""核心层端到端测试，不依赖 Web 服务。"""
import shutil
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 同时写 stdout 与 UTF-8 日志文件，避开 PowerShell 重定向乱码
_LOG_PATH = Path(__file__).parent / "test_output.log"
_log_file = _LOG_PATH.open("w", encoding="utf-8")
class _Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, s):
        for st in self.streams:
            try: st.write(s)
            except Exception: pass
    def flush(self):
        for st in self.streams:
            try: st.flush()
            except Exception: pass
sys.stdout = _Tee(sys.__stdout__, _log_file)
sys.stderr = _Tee(sys.__stderr__, _log_file)

from core import json_loader, conversation_parser, exporter
from core.exporter import ExportOptions, default_output_dir

JSON = Path(r"C:\Users\PCL13\Downloads\ttl\30d\export_data\44f012b6-a0df-4689-9653-e224774180e3\prod-grok-backend.json")
OUT = Path(r"D:\CODE\Python\test-data-backup\py\local_services\grok_exporter\grok_export_test_output")

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


banner("T1  JSON 加载")
data = json_loader.load_json(JSON)
print("顶层键：", list(data.keys()))

banner("T2  会话解析（13 个会话）")
sessions = conversation_parser.parse_all(data)
print("会话数：", len(sessions))
for s in sessions:
    print(f"  #{s['index']:>2}  {s['title'][:28]:<28}  msgs={len(s['messages']):>3}  "
          f"strategy={s['ordering_strategy']}")

banner("T3  统计")
summ = conversation_parser.summarize(sessions)
print(summ)

banner("T4  sender 大小写归一化（ASSISTANT 必须算 Grok）")
total_assistant_upper = 0
total_assistant_lower = 0
for s in sessions:
    for m in s["messages"]:
        if m["sender_raw"] == "ASSISTANT":
            total_assistant_upper += 1
        elif m["sender_raw"] == "assistant":
            total_assistant_lower += 1
print(f"原始 sender='ASSISTANT' 条数：{total_assistant_upper}")
print(f"原始 sender='assistant' 条数：{total_assistant_lower}")
print(f"归一化后 role='Grok' 总条数：{sum(1 for s in sessions for m in s['messages'] if m['role'] == 'Grok')}")
# 不强要求样本包含大写 ASSISTANT；仅当出现时必须被归一化
if total_assistant_upper > 0:
    upper_as_grok = sum(1 for s in sessions for m in s["messages"]
                        if m["sender_raw"] == "ASSISTANT" and m["role"] == "Grok")
    assert upper_as_grok == total_assistant_upper, "ASSISTANT 必须全部被识别为 Grok"
    print("  大写 ASSISTANT 全部归一化为 Grok ✓")
else:
    print("  本样本不含大写 ASSISTANT，跳过该分支验证（逻辑已由代码 normalize_sender 覆盖）")

banner("T5  单会话 MD 导出 + 文件命名（日期前缀）")
md_opts = ExportOptions({
    "formats": ["md"],
    "scope": "all",
    "organization": "individual",
    "output_dir": str(OUT / "t5"),
})
res = exporter.run_export(sessions[:3], md_opts)
print("文件清单：")
for f in res.files:
    print("  ", Path(f).name)
print(f"success={res.success}, failed={res.failed}, errors={res.errors}")

banner("T6  单会话 TXT 导出")
txt_opts = ExportOptions({
    "formats": ["txt"],
    "scope": "all",
    "organization": "individual",
    "output_dir": str(OUT / "t6"),
})
res = exporter.run_export(sessions[:3], txt_opts)
for f in res.files:
    print("  ", Path(f).name)

banner("T7  MD + TXT 同时导出 + 合并文件")
both_opts = ExportOptions({
    "formats": ["md", "txt"],
    "scope": "all",
    "organization": "both",
    "output_dir": str(OUT / "t7"),
})
res = exporter.run_export(sessions, both_opts)
files = sorted(Path(f).name for f in res.files)
print(f"共生成 {len(files)} 个文件")
print(f"success={res.success}, failed={res.failed}, errors={res.errors}")
print("合并文件应包含两个：")
for f in files:
    if "全部" in f:
        print("  ", f)

banner("T8  scope=grok / scope=user")
for sc in ("grok", "user"):
    o = ExportOptions({"formats": ["md"], "scope": sc, "organization": "individual",
                       "output_dir": str(OUT / f"t8_{sc}")})
    r = exporter.run_export([sessions[0]], o)
    p = Path(r.files[0])
    text = p.read_text(encoding="utf-8")
    if sc == "grok":
        assert "## 1. 用户" not in text, "grok-only 不应包含用户标题"
        assert "## 1. Grok" in text, "grok-only 应含 Grok 标题"
    else:
        assert "## 1. 用户" in text, "user-only 应含用户标题"
        assert "## 1. Grok" not in text, "user-only 不应含 Grok 标题"
    print(f"  scope={sc} 文件 {p.name}，长度={len(text)}")

banner("T9  重名文件追加 _01 序号")
o = ExportOptions({"formats": ["md"], "scope": "all", "organization": "individual",
                   "output_dir": str(OUT / "t9")})
exporter.run_export([sessions[0]], o)
exporter.run_export([sessions[0]], o)  # 第二次必须不覆盖
files = sorted(p.name for p in (OUT / "t9").iterdir())
print("目录文件：", files)
assert len(files) >= 2, "应至少 2 个不重叠文件"

banner("T10 取消粒度（会话级）")
cancel = threading.Event()
events = []
def cb(ev):
    events.append(ev)
    if ev.get("stage") == "ok" and ev.get("current", 0) >= 1:
        cancel.set()
o = ExportOptions({"formats": ["md"], "scope": "all", "organization": "individual",
                   "output_dir": str(OUT / "t10")})
res = exporter.run_export(sessions, o, progress_cb=cb, cancel_event=cancel)
print(f"success={res.success} cancelled={res.cancelled} files={len(res.files)}")
assert res.success >= 1, "应至少完成 1 条会话"
if len(sessions) >= 2:
    assert res.cancelled > 0, "样本多于 1 会话时应记录被取消的会话数"
    assert res.success == 1, f"应在第 1 条后取消，实际 {res.success}"

banner("T11 缺失 conversations / 空数据 容错")
empty = conversation_parser.parse_all({})
assert empty == [], "缺字段应返回空列表"
print("  parse_all({}) ->", empty)

banner("T12 输出编码（UTF-8 无 BOM）")
sample = (OUT / "t5").iterdir()
for p in sample:
    head = p.read_bytes()[:3]
    is_bom = head == b"\xef\xbb\xbf"
    print(f"  {p.name}: BOM={is_bom}")
    assert not is_bom, "不应写入 BOM"

banner("T13 默认导出目录命名（Grok_Export）")
expected = default_output_dir(JSON)
print("  ", expected, "name=", expected.name)
assert expected.name == "Grok_Export"

banner("ALL TESTS PASSED")
print(f"输出目录：{OUT}")
