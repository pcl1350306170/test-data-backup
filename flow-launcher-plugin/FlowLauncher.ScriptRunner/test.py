# -*- coding: utf-8 -*-
"""测试脚本：模拟 Flow Launcher 发送 JSON-RPC 请求"""
import subprocess
import json
import sys

def test_query(query_str):
    """模拟一次 query 请求"""
    rpc_request = json.dumps({"method": "query", "parameters": [query_str]})
    result = subprocess.run(
        [sys.executable, "main.py", rpc_request],
        capture_output=True, text=True,
        cwd=r"d:\CODE\FontEnd\flow-launcher-plugin\FlowLauncher.ScriptRunner"
    )
    print(f"查询: '{query_str}'")
    if result.stdout:
        output = json.loads(result.stdout)
        for item in output.get("result", []):
            print(f"  -> {item['Title']}  |  {item['SubTitle']}")
    if result.stderr:
        print(f"  [错误] {result.stderr.strip()}")
    print()

if __name__ == "__main__":
    print("=== Script Runner 插件测试 ===\n")
    test_query("mz")       # 应匹配"门诊打包"（关键词 mzdb 包含 mz）
    test_query("mzdb")     # 应匹配"门诊打包"
    test_query("门诊")     # 应匹配"门诊打包"（名称包含"门诊"）
    test_query("xyz")      # 无匹配
    test_query("")         # 显示所有命令
