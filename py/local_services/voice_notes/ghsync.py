# -*- coding: utf-8 -*-
"""
语音速记本 - GitHub 拉取（单向：仓库 → 本地 MySQL）
- 支持两种远端格式：旧版明文 JSON、新版 AES-GCM 密文信封（与静态页同一套参数）
- 合并策略「本地胜出」：已存在的记录永不覆盖正文/分类，只更新远端存在状态
- 本地删除过的记录（墓标）不会被拉回来；远端删掉的本地照旧保留
"""
import base64
import json
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import db

API = "https://api.github.com"


class SyncError(Exception):
    pass


def _b64d(s):
    return base64.b64decode((s or "").replace("\n", "").replace("\r", "").replace(" ", ""))


def decrypt_env(env, password):
    """信封：{enc:'v1', alg:'AES-GCM', iterations, salt, iv, data}"""
    if not password:
        raise SyncError("远端数据已加密，但未在 config.json 的 github.password 里配置口令")
    try:
        salt, iv, data = _b64d(env["salt"]), _b64d(env["iv"]), _b64d(env["data"])
        key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                         iterations=int(env.get("iterations") or 150000)).derive(password.encode("utf-8"))
        plain = AESGCM(key).decrypt(iv, data, None)
        return json.loads(plain.decode("utf-8"))
    except Exception:
        raise SyncError("解密失败：口令错误或远端密文已损坏")


def fetch_remote():
    """读取仓库里的数据文件，返回解析后的 payload（自动识别明文/密文）。"""
    gh = db.load_config()["github"]
    if not gh.get("token"):
        raise SyncError("未配置 GitHub 令牌（config.json → github.token）")
    url = "%s/repos/%s/contents/%s?ref=%s" % (API, gh["repo"], gh["path"].lstrip("/"), gh.get("branch") or "main")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + gh["token"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "voice-notes-local-sync",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            info = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SyncError("远端文件不存在（%s@%s），请确认手机端已同步过" % (gh["path"], gh.get("branch")))
        if e.code == 401:
            raise SyncError("令牌无效或已过期（HTTP 401）")
        if e.code == 403:
            raise SyncError("被 GitHub 限流或拒绝访问（HTTP 403），稍后再试")
        raise SyncError("读取远端失败：HTTP %d" % e.code)
    except Exception as e:
        raise SyncError("无法连接 GitHub：%s" % e)

    try:
        raw = base64.b64decode(info.get("content", "")).decode("utf-8")
    except Exception:
        raise SyncError("远端内容不是合法的 base64")
    try:
        payload = json.loads(raw)
    except Exception:
        raise SyncError("远端文件不是合法 JSON，可能被手动改坏了")

    if isinstance(payload, dict) and payload.get("enc") == "v1":
        return decrypt_env(payload, gh.get("password") or "")
    return payload


def pull():
    """执行一次拉取合并，返回统计。"""
    payload = fetch_remote()
    if not isinstance(payload, dict):
        raise SyncError("远端数据格式异常（期望 JSON 对象）")
    r_cats = payload.get("categories") or []
    r_notes = payload.get("notes") or []

    conn = db.get_conn()
    stats = {"added": 0, "refreshed": 0, "skipped_local_deleted": 0,
             "marked_remote_deleted": 0, "added_categories": 0, "remote_total": len(r_notes)}
    try:
        with conn.cursor() as cur:
            # 1) 分类：按名称补建，建立 远端catId → 本地catId
            cur.execute("SELECT id, name FROM vn_categories")
            name_to_id = {r["name"]: r["id"] for r in cur.fetchall()}
            remote_id_to_name = {}
            for c in r_cats:
                name = (c.get("name") or "").strip()
                if not name:
                    continue
                remote_id_to_name[c.get("id", "")] = name
                if name not in name_to_id:
                    cid = db.new_id()
                    cur.execute("INSERT IGNORE INTO vn_categories (id,name,created_at) VALUES (%s,%s,%s)",
                                (cid, name, db.now()))
                    name_to_id[name] = cid
                    stats["added_categories"] += 1

            def map_cat(remote_cat_id):
                if not remote_cat_id:
                    return ""
                return name_to_id.get(remote_id_to_name.get(remote_cat_id, ""), "")

            # 2) 本地已有 / 已墓标的 client_id
            cur.execute("SELECT client_id, id, remote_status FROM vn_notes")
            local_by_cid = {r["client_id"]: r for r in cur.fetchall()}
            cur.execute("SELECT client_id FROM vn_tombstones")
            tombstones = {r["client_id"] for r in cur.fetchall()}

            ts = db.now()
            seen = set()
            for rn in r_notes:
                content = (rn.get("content") or "").strip()
                cid = (rn.get("client_id") or rn.get("id") or "").strip()
                if not cid:
                    continue
                seen.add(cid)
                if cid in tombstones:
                    stats["skipped_local_deleted"] += 1
                    continue
                if cid in local_by_cid:
                    # 本地胜出：正文/分类一律不动，只标记「远端现存」
                    cur.execute("UPDATE vn_notes SET remote_status='synced', remote_updated_at=%s, pulled_at=%s "
                                "WHERE client_id=%s",
                                (db.parse_dt(rn.get("updated_at")) or db.parse_dt(rn.get("created_at")), ts, cid))
                    stats["refreshed"] += 1
                    continue
                if not content:
                    continue
                nid = db.new_id()
                cur.execute(
                    "INSERT INTO vn_notes (id,client_id,content,category_id,created_at,updated_at,copy_count,"
                    "last_copied_at,source,remote_status,remote_updated_at,pulled_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'github','synced',%s,%s)",
                    (nid, cid, content, map_cat(rn.get("category_id")),
                     db.parse_dt(rn.get("created_at")) or ts, db.parse_dt(rn.get("updated_at")),
                     int(rn.get("copy_count") or 0), db.parse_dt(rn.get("last_copied_at")),
                     db.parse_dt(rn.get("updated_at")), ts))
                stats["added"] += 1

            # 3) 上次还在远端、这次不见了的 → 标记远端已删（记录保留）
            if seen:
                ph = ",".join(["%s"] * len(seen))
                cur.execute("UPDATE vn_notes SET remote_status='deleted' "
                            "WHERE remote_status='synced' AND client_id NOT IN (%s)" % ph, list(seen))
                stats["marked_remote_deleted"] = cur.rowcount or 0

        stats["ok"] = True
        stats["finished_at"] = ts
        stats["local_total"] = None
        db.meta_set("last_pull_at", ts)
        db.meta_set("last_pull_result", json.dumps(stats, ensure_ascii=False))
        return stats
    finally:
        conn.close()


def status():
    raw = db.meta_get("last_pull_result")
    gh = db.load_config()["github"]
    return {
        "last_pull_at": db.meta_get("last_pull_at", ""),
        "last_pull_result": json.loads(raw) if raw else None,
        "has_token": bool(gh.get("token")),
        "has_password": bool(gh.get("password")),
        "repo": gh.get("repo"),
        "path": gh.get("path"),
        "branch": gh.get("branch"),
    }
