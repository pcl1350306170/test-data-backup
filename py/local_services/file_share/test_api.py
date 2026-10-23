# -*- coding: utf-8 -*-
"""file_share 端到端接口测试"""
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8800"
TMP = os.path.join(os.environ["TEMP"], "fs_test.bin")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  %s %s" % (name, detail))
    else:
        fail += 1
        print("  FAIL  %s %s" % (name, detail))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def upload(filepath, rename=None):
    boundary = "----fstest"
    fname = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        content = f.read()
    body = (
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
         "Content-Type: application/octet-stream\r\n\r\n" % (boundary, fname)).encode("utf-8")
        + content +
        ("\r\n--%s\r\nContent-Disposition: form-data; name=\"rename\"\r\n\r\n%s\r\n--%s--\r\n"
         % (boundary, rename or "", boundary)).encode("utf-8")
    )
    req = urllib.request.Request(BASE + "/api/upload", data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


print("== 1. ping / info ==")
check("ping", get("/api/ping")["ok"])
info = get("/api/info")
check("info.shared_dir", info["shared_dir"] == r"D:\FILES\共享", info["shared_dir"])
check("info.lan_ip", info["lan_ip"] != "127.0.0.1", info["lan_ip"])

print("== 2. 上传 5MB 测试文件 ==")
data = os.urandom(5 * 1024 * 1024)
with open(TMP, "wb") as f:
    f.write(data)
md5_src = hashlib.md5(data).hexdigest()
st, res = upload(TMP)
check("upload", st == 200 and res["size"] == len(data), str(res))
uploaded_name = res["name"]

print("== 3. 列表出现该文件 ==")
files = get("/api/files")["files"]
check("list contains", any(x["name"] == uploaded_name for x in files), uploaded_name)

print("== 4. 下载并比对 MD5 ==")
url = BASE + "/api/download?name=" + urllib.parse.quote(uploaded_name)
with urllib.request.urlopen(url, timeout=30) as r:
    md5_dl = hashlib.md5(r.read()).hexdigest()
check("download md5", md5_dl == md5_src)

print("== 5. 同名冲突自动加时间戳 ==")
st2, res2 = upload(TMP)
check("conflict renamed", st2 == 200 and res2["name"] != uploaded_name
      and res2["name"].startswith("fs_test_"), res2.get("name"))

print("== 6. 重命名 ==")
st3, res3 = post("/api/rename", {"name": res2["name"], "new_name": "fs_test_renamed.bin"})
check("rename", st3 == 200 and res3["ok"])
st4, _ = post("/api/rename", {"name": "fs_test_renamed.bin", "new_name": uploaded_name})
check("rename conflict 409", st4 == 409)

print("== 7. 删除 ==")
for n in [uploaded_name, "fs_test_renamed.bin"]:
    st5, res5 = post("/api/delete", {"name": n})
    check("delete %s" % n, st5 == 200 and res5["ok"])
st6, _ = post("/api/delete", {"name": "not_exist.bin"})
check("delete 404", st6 == 404)

print("== 8. 路径逃逸防护 ==")
for bad in ["../evil.txt", "..\\evil.txt", "a/b.txt", "C:\\Windows\\x.txt"]:
    st7, _ = post("/api/delete", {"name": bad})
    check("reject %r" % bad, st7 == 400)
st8, _ = upload(TMP, rename="../escape.bin")
check("upload reject escape", st8 == 400)
check("no escape file", not os.path.exists(r"D:\FILES\escape.bin"))

os.remove(TMP)
print("\n结果: %d PASS / %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
