# -*- coding: utf-8 -*-
"""
CosyVoice TTS Worker（供 cosyvoice_tts.py 主脚本调用）
=====================================================
必须在 CosyVoice 专用的 conda 环境（python 3.10）中运行：
    conda activate cosyvoice
    python cosyvoice_tts_worker.py --model_dir <模型目录> --text "..." --output out.wav --spk 中文女 [--style 开心]

支持的模型（自动识别目录名）：
  - CosyVoice-300M-SFT     -> CosyVoice  类（SFT 推理）
  - CosyVoice2-0.5B        -> CosyVoice2 类（推荐，支持 instruct2 + zero-shot）
  - Fun-CosyVoice3-0.5B    -> CosyVoice3 类（最新）

推理模式优先级：
  1. --prompt_audio + --prompt_text 同时传入 -> zero-shot 音色复刻
  2. --style 非空 -> instruct2 情感指令模式
  3. 默认 -> SFT 预置音色模式
"""
import argparse
import os
import sys


def _save_first_chunk(generator, output_path, sample_rate):
    """从生成器取第一个音频片段保存为 wav（非流式场景足够）"""
    import torchaudio
    for chunk in generator:
        torchaudio.save(output_path, chunk["tts_speech"], sample_rate)
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", required=True, help="CosyVoice 模型目录绝对路径")
    ap.add_argument("--text", required=True, help="要合成的文本")
    ap.add_argument("--output", required=True, help="输出 wav 绝对路径")
    ap.add_argument("--spk", default="中文女",
                    help="SFT 预置音色，如 中文女/中文男/英文男/英文女/日语男/韩语女/粤语女")
    ap.add_argument("--style", default="",
                    help="情感风格指令（可选），如 开心/温柔/严肃/活泼/深情；空则走普通 SFT")
    ap.add_argument("--prompt_audio", default="",
                    help="参考音频文件路径（zero-shot 音色复刻），需同时提供 --prompt_text")
    ap.add_argument("--prompt_text", default="",
                    help="参考音频对应的文字内容（zero-shot 音色复刻）")
    args = ap.parse_args()

    # 延迟导入，避免解析参数前触发重型依赖
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice, CosyVoice2, CosyVoice3
    except Exception as e:
        print("COSYVOICE_ERR import_failed: %s" % e, file=sys.stderr)
        print("提示: 请确认在 CosyVoice conda 环境中运行，且已正确设置 PYTHONPATH 指向仓库根目录与 third_party/Matcha-TTS", file=sys.stderr)
        sys.exit(2)

    # 根据模型目录名选择对应的推理类
    name = os.path.basename(args.model_dir.rstrip("/\\")).lower()
    try:
        if "cosyvoice3" in name or "fun-cosyvoice3" in name:
            cv = CosyVoice3(args.model_dir, load_jit=False, load_trt=False, fp16=False)
        elif "cosyvoice2" in name or "cosyvoice-2" in name:
            cv = CosyVoice2(args.model_dir, load_jit=False, load_trt=False, fp16=False)
        else:
            cv = CosyVoice(args.model_dir)
    except Exception as e:
        print("COSYVOICE_ERR model_load_failed: %s" % e, file=sys.stderr)
        print("提示: 检查模型目录是否存在且完整: %s" % args.model_dir, file=sys.stderr)
        sys.exit(3)

    # ---------- 推理模式选择 ----------
    style = (args.style or "").strip()
    prompt_audio = (args.prompt_audio or "").strip()
    prompt_text = (args.prompt_text or "").strip()
    used_mode = "sft"

    # 模式 1：Zero-Shot 音色复刻（优先级最高）
    if prompt_audio and prompt_text:
        if not os.path.isfile(prompt_audio):
            print("COSYVOICE_ERR prompt_audio_not_found: %s" % prompt_audio, file=sys.stderr)
            sys.exit(5)
        if not hasattr(cv, "inference_zero_shot"):
            print("COSYVOICE_ERR model_no_zero_shot_support", file=sys.stderr)
            print("提示: 当前模型不支持 zero-shot，请使用 CosyVoice2 或 CosyVoice3", file=sys.stderr)
            sys.exit(5)
        try:
            import torchaudio
            # 加载参考音频并重采样到 16kHz
            speech, sr = torchaudio.load(prompt_audio)
            if sr != 16000:
                speech = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)(speech)
            # 取单声道
            if speech.shape[0] > 1:
                speech = speech.mean(dim=0, keepdim=True)
            prompt_speech_16k = speech.squeeze(0)  # shape: [samples]

            ok = _save_first_chunk(
                cv.inference_zero_shot(args.text, prompt_text, prompt_speech_16k, stream=False),
                args.output, cv.sample_rate)
            used_mode = "zero_shot"
            if not ok:
                print("COSYVOICE_ERR empty_output_zero_shot", file=sys.stderr)
                sys.exit(4)
        except Exception as e:
            print("COSYVOICE_ERR zero_shot_failed: %s" % e, file=sys.stderr)
            sys.exit(4)

    # 模式 2：情感指令模式
    elif style and hasattr(cv, "inference_instruct2"):
        instruct_text = "用%s的语气说这段话。" % style
        try:
            ok = _save_first_chunk(
                cv.inference_instruct2(args.text, instruct_text, args.spk, stream=False),
                args.output, cv.sample_rate)
            used_mode = "instruct2"
            if not ok:
                print("COSYVOICE_ERR empty_output_instruct2", file=sys.stderr)
                sys.exit(4)
        except Exception as e:
            # instruct2 失败降级到 SFT
            print("COSYVOICE_WARN instruct2_failed_fallback_sft: %s" % e, file=sys.stderr)
            ok = _save_first_chunk(
                cv.inference_sft(args.text, args.spk, stream=False),
                args.output, cv.sample_rate)
            if not ok:
                print("COSYVOICE_ERR empty_output_sft", file=sys.stderr)
                sys.exit(4)

    # 模式 3：普通 SFT
    else:
        if style:
            print("COSYVOICE_WARN style_ignored_current_model_no_instruct2", file=sys.stderr)
        if prompt_audio and not prompt_text:
            print("COSYVOICE_WARN prompt_audio_ignored_no_prompt_text", file=sys.stderr)
        ok = _save_first_chunk(
            cv.inference_sft(args.text, args.spk, stream=False),
            args.output, cv.sample_rate)
        if not ok:
            print("COSYVOICE_ERR empty_output_sft", file=sys.stderr)
            sys.exit(4)

    # 主脚本通过该标记判定成功
    print("COSYVOICE_OK", args.output, "mode=%s" % used_mode)


if __name__ == "__main__":
    main()
