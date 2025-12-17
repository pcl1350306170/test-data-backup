# 测试脚本 test_qwen_tts.py
import httpx
import base64
import os

API_KEY = "sk-11e2c92c4d0f423c85231b475581ae1b"
text = "We use the singleton pattern for the configuration manager."

cleaned = text.replace('\n', '。').replace('\r', ' ').replace('\t', ' ')
cleaned = ' '.join(cleaned.split())

payload = {
    "model": "cosyvoice-v1",
    "input": {"text": cleaned},
    "parameters": {
        "voice": "longxiaochun",
        "format": "mp3",
        "sample_rate": 24000
    }
}

resp = httpx.post(
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/text-to-speech",
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    json=payload,
    timeout=30
)

print("Status:", resp.status_code)
print("Response:", resp.text)

if resp.status_code == 200:
    data = resp.json()
    audio = base64.b64decode(data['output']['results'][0]['audio'])
    with open("test.mp3", "wb") as f:
        f.write(audio)
    print("Saved to test.mp3")
