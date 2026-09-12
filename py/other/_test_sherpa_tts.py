# -*- coding: utf-8 -*-
"""临时测试脚本：验证 sherpa_onnx_tts.pyw 能正常启动"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 模拟 __file__
import sherpa_onnx_tts as mod  # noqa: E402
print("IMPORT_OK")
print(f"SCRIPT_NAME = {mod.SCRIPT_NAME}")
print(f"DEFAULT_MODEL_DIR = {mod.DEFAULT_MODEL_DIR}")
print(f"HAVE_SHERPA_ONNX = {mod.HAVE_SHERPA_ONNX}")
print(f"SID_OPTIONS = {mod.SID_OPTIONS}")
print(f"SPEED_OPTIONS = {mod.SPEED_OPTIONS}")

# 验证模型目录文件定位
model_dir = mod.DEFAULT_MODEL_DIR
if os.path.isdir(model_dir):
    try:
        mp, tp, lp, dd, rf = mod._find_model_files(model_dir)
        print(f"model_path = {os.path.basename(mp)}")
        print(f"tokens_path = {os.path.basename(tp)}")
        print(f"lexicon_path = {os.path.basename(lp) if lp else 'None'}")
        print(f"data_dir = {os.path.basename(dd) if dd else 'None'}")
        print(f"rule_fsts = {[os.path.basename(f) for f in rf]}")
        print("MODEL_FILES_OK")
    except Exception as e:
        print(f"MODEL_FILES_ERROR: {e}")
else:
    print(f"MODEL_DIR_NOT_FOUND: {model_dir}")
