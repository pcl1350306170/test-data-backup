# -*- coding: utf-8 -*-
"""
CosyVoice 独立 Worker
=====================
由主 GUI 脚本（绘本旁白音频生成器.py）通过 subprocess 调用。
必须在 CosyVoice 专用的 conda 环境（python 3.10）中运行：
    conda activate cosyvoice
    python cosyvoice_worker.py --model_dir <模型目录> --text "..." --output out.wav --spk 中文女

支持的模型（自动识别目录名）：
  - CosyVoice-300M-SFT    -> CosyVoice  类（SFT 推理）
  - CosyVoice2-0.5B       -> CosyVoice2 类（推荐，音质更好）
  - Fun-CosyVoice3-0.5B   -> CosyVoice3 类（最新）
"""
import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", required=True, help="CosyVoice 模型目录绝对路径")
    ap.add_argument("--text", required=True, help="要合成的文本")
    ap.add_argument("--output", required=True, help="输出 wav 绝对路径")
    ap.add_argument("--spk", default="中文女", help="SFT 预置音色，如 中文女/中文男/英文男/英文女")
    args = ap.parse_args()

    import torchaudio
    from cosyvoice.cli.cosyvoice import CosyVoice, CosyVoice2, CosyVoice3

    name = os.path.basename(args.model_dir.rstrip("/\\")).lower()

    if "cosyvoice3" in name or "fun-cosyvoice3" in name:
        cv = CosyVoice3(args.model_dir, load_jit=False, load_trt=False, fp16=False)
    elif "cosyvoice2" in name or "cosyvoice-2" in name:
        cv = CosyVoice2(args.model_dir, load_jit=False, load_trt=False, fp16=False)
    else:
        cv = CosyVoice(args.model_dir)

    # 非流式 SFT 合成，只保存第一个音频片段
    for _chunk in cv.inference_sft(args.text, args.spk, stream=False):
        torchaudio.save(args.output, _chunk["tts_speech"], cv.sample_rate)
        break

    print("COSYVOICE_OK", args.output)


if __name__ == "__main__":
    main()
