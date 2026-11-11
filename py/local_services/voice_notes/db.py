# -*- coding: utf-8 -*-
"""
语音速记本 - MySQL 存储层
表前缀 vn_，挂在配置指定的库（默认 test）下：
  vn_notes       记录主表（client_id 唯一，跨端去重键）
  vn_categories  分类
  vn_tags        标签字典（仅本地，不回写 GitHub）
  vn_note_tags   记录-标签关联
  vn_tombstones  本地删除墓标（防止下次拉取把删掉的记录复活）
  vn_meta        杂项（最近拉取时间/结果等）
"""
import datetime
import json
import os
import uuid

import pymysql
from pymysql.cursors import DictCursor

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
LEGACY_NOTES = os.path.join(BASE, "notes.json")
LEGACY_CATS = os.path.join(BASE, "categories.json")

DEFAULT_CONFIG = {
    "mysql": {"host": "localhost", "port": 3306, "user": "root", "password": "",
              "database": "test", "charset": "utf8mb4"},
    "github": {"token": "", "repo": "pcl1350306170/pcl1350306170.github.io",
               "path": "application/voice_notes/data/notes.json", "branch": "main", "password": ""},
    "sync": {"pull_on_start": True, "daily_at": "00:00"},
}

DEFAULT_CATS = [
    {"id": "cat_daily", "name": "日常记录"},
    {"id": "cat_xianjian4", "name": "仙剑四游戏同人小说大纲"},
]

# remote_status：local=本地独有 / synced=远端现存 / deleted=远端已删（本地照旧保留）
RS_LOCAL, RS_SYNCED, RS_DELETED = "local", "synced", "deleted"


# ------------------------------------------------------------------ 配置
def _merge(base, extra):
    out = json.loads(json.dumps(base))
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception:
            cfg = {}
    return _merge(DEFAULT_CONFIG, cfg)


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ------------------------------------------------------------------ 连接
def get_conn():
    my = load_config()["mysql"]
    return pymysql.connect(
        host=my.get("host", "localhost"), port=int(my.get("port", 3306)),
        user=my.get("user", "root"), password=my.get("password", ""),
        database=my.get("database", "test"), charset=my.get("charset", "utf8mb4"),
        cursorclass=DictCursor, autocommit=True,
    )


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(s):
    """把 '2026-10-27 09:23:51' / ISO 字符串转成 DATETIME 可用的字符串，失败返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace("T", " ").split(".")[0].split("Z")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s[:len(datetime.datetime.now().strftime(fmt))], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return None


def new_id():
    return uuid.uuid4().hex[:12]


# ------------------------------------------------------------------ 建表 + 旧数据导入
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS vn_categories (
        id VARCHAR(32) NOT NULL PRIMARY KEY,
        name VARCHAR(64) NOT NULL,
        created_at DATETIME NULL,
        UNIQUE KEY uk_cat_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS vn_notes (
        id VARCHAR(32) NOT NULL PRIMARY KEY,
        client_id VARCHAR(64) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        category_id VARCHAR(32) NOT NULL DEFAULT '',
        created_at DATETIME NULL,
        updated_at DATETIME NULL,
        copy_count INT NOT NULL DEFAULT 0,
        last_copied_at DATETIME NULL,
        source VARCHAR(16) NOT NULL DEFAULT 'local',
        remote_status VARCHAR(16) NOT NULL DEFAULT 'local',
        remote_updated_at DATETIME NULL,
        pulled_at DATETIME NULL,
        UNIQUE KEY uk_client (client_id),
        KEY idx_cat (category_id),
        KEY idx_created (created_at),
        KEY idx_remote (remote_status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS vn_tags (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(32) NOT NULL,
        created_at DATETIME NULL,
        UNIQUE KEY uk_tag_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS vn_note_tags (
        note_id VARCHAR(32) NOT NULL,
        tag_id INT NOT NULL,
        PRIMARY KEY (note_id, tag_id),
        KEY idx_tag (tag_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS vn_tombstones (
        client_id VARCHAR(64) NOT NULL PRIMARY KEY,
        deleted_at DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS vn_meta (
        k VARCHAR(32) NOT NULL PRIMARY KEY,
        v TEXT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for sql in SCHEMA:
                cur.execute(sql)
    finally:
        conn.close()
    imported = import_legacy()
    return imported


def import_legacy():
    """首次建表时把旧 notes.json / categories.json 灌进 MySQL（按 client_id 幂等）。"""
    conn = get_conn()
    added = 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM vn_notes")
            if cur.fetchone()["c"]:
                return 0
            if not os.path.exists(LEGACY_NOTES):
                return 0
            try:
                with open(LEGACY_NOTES, "r", encoding="utf-8") as f:
                    legacy = json.load(f) or []
            except Exception:
                legacy = []
            if os.path.exists(LEGACY_CATS):
                try:
                    with open(LEGACY_CATS, "r", encoding="utf-8") as f:
                        for c in json.load(f) or []:
                            name = (c.get("name") or "").strip()
                            if name:
                                # 必须沿用旧 id：记录表里的 category_id 引用的就是这些 id
                                cur.execute("INSERT IGNORE INTO vn_categories (id,name,created_at) VALUES (%s,%s,%s)",
                                            (c.get("id") or new_id(), name, now()))
                except Exception:
                    pass
            used_ids = set()
            for n in legacy:
                content = (n.get("content") or "").strip()
                if not content:
                    continue
                nid = n.get("id") or new_id()
                while nid in used_ids:
                    nid = new_id()
                used_ids.add(nid)
                cur.execute(
                    "INSERT IGNORE INTO vn_notes (id,client_id,content,category_id,created_at,updated_at,"
                    "copy_count,last_copied_at,source,remote_status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'local','local')",
                    (nid, n.get("client_id") or nid, content, (n.get("category_id") or "").strip(),
                     parse_dt(n.get("created_at")), parse_dt(n.get("updated_at")),
                     int(n.get("copy_count") or 0), parse_dt(n.get("last_copied_at"))))
                added += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        # 保证默认分类存在
        with conn.cursor() as cur:
            for c in DEFAULT_CATS:
                cur.execute("INSERT IGNORE INTO vn_categories (id,name,created_at) VALUES (%s,%s,%s)",
                            (c["id"], c["name"], now()))
    finally:
        conn.close()
    return added


# ------------------------------------------------------------------ 分类
def list_categories():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.id, c.name,
                              (SELECT COUNT(*) FROM vn_notes n WHERE n.category_id = c.id) AS count
                           FROM vn_categories c ORDER BY c.id""")
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS c FROM vn_notes WHERE category_id = ''")
            none_cnt = cur.fetchone()["c"]
        out = [{"id": r["id"], "name": r["name"], "count": int(r["count"])} for r in rows]
        out.append({"id": "", "name": "未分类", "count": int(none_cnt)})
        return out
    finally:
        conn.close()


def create_category(name):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM vn_categories WHERE name=%s", (name,))
            hit = cur.fetchone()
            if hit:
                return {"id": hit["id"], "name": name, "existed": True}
            cid = new_id()
            cur.execute("INSERT INTO vn_categories (id,name,created_at) VALUES (%s,%s,%s)", (cid, name, now()))
            return {"id": cid, "name": name, "existed": False}
    finally:
        conn.close()


def delete_category(cat_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vn_categories WHERE id=%s", (cat_id,))
            if not cur.rowcount:
                return False
            cur.execute("UPDATE vn_notes SET category_id='' WHERE category_id=%s", (cat_id,))
            return True
    finally:
        conn.close()


# ------------------------------------------------------------------ 标签
def ensure_tags(names):
    """按名称取/建标签，返回 tag_id 列表。"""
    ids, conn = [], get_conn()
    try:
        with conn.cursor() as cur:
            for raw in names:
                name = (raw or "").strip()[:32]
                if not name:
                    continue
                cur.execute("SELECT id FROM vn_tags WHERE name=%s", (name,))
                hit = cur.fetchone()
                if hit:
                    ids.append(hit["id"])
                else:
                    cur.execute("INSERT INTO vn_tags (name,created_at) VALUES (%s,%s)", (name, now()))
                    ids.append(cur.lastrowid)
        return ids
    finally:
        conn.close()


def list_tags():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT t.id, t.name, COUNT(nt.note_id) AS count
                           FROM vn_tags t LEFT JOIN vn_note_tags nt ON nt.tag_id = t.id
                           GROUP BY t.id, t.name, t.created_at ORDER BY t.name""")
            return [{"id": r["id"], "name": r["name"], "count": int(r["count"])} for r in cur.fetchall()]
    finally:
        conn.close()


def rename_tag(tag_id, name):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE vn_tags SET name=%s WHERE id=%s", (name[:32], tag_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def delete_tag(tag_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vn_tags WHERE id=%s", (tag_id,))
            cur.execute("DELETE FROM vn_note_tags WHERE tag_id=%s", (tag_id,))
            return cur.rowcount > 0
    finally:
        conn.close()


def set_note_tags(note_id, names):
    ids = ensure_tags(names)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vn_note_tags WHERE note_id=%s", (note_id,))
            for tid in ids:
                cur.execute("INSERT IGNORE INTO vn_note_tags (note_id,tag_id) VALUES (%s,%s)", (note_id, tid))
        return ids
    finally:
        conn.close()


def _attach_tags(conn, rows):
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    ph = ",".join(["%s"] * len(ids))
    with conn.cursor() as cur:
        cur.execute("""SELECT nt.note_id, t.name FROM vn_note_tags nt
                       JOIN vn_tags t ON t.id = nt.tag_id
                       WHERE nt.note_id IN (%s) ORDER BY t.name""" % ph, ids)
        mapping = {}
        for r in cur.fetchall():
            mapping.setdefault(r["note_id"], []).append(r["name"])
    for r in rows:
        r["tags"] = mapping.get(r["id"], [])
    return rows


# ------------------------------------------------------------------ 记录查询
def _fmt(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else (v or "")


def list_notes(kw="", category_id=None, tag_ids=None, tag_match="any", remote_status=None,
               start="", end="", limit=100, offset=0, order="desc", show_all=False):
    where, args = ["1=1"], []
    if kw:
        where.append("content LIKE %s")
        args.append("%" + kw.strip() + "%")
    if category_id is not None:
        where.append("category_id = %s")
        args.append(category_id)
    if remote_status:
        ph = ",".join(["%s"] * len(remote_status))
        where.append("remote_status IN (%s)" % ph)
        args.extend(remote_status)
    if tag_ids:
        ph = ",".join(["%s"] * len(tag_ids))
        sub = "id IN (SELECT note_id FROM vn_note_tags WHERE tag_id IN (%s)" % ph
        if tag_match == "all":
            sub += " GROUP BY note_id HAVING COUNT(DISTINCT tag_id) = %d)" % len(tag_ids)
        else:
            sub += ")"
        where.append(sub)
        args.extend(tag_ids)
    if start:
        where.append("created_at >= %s")
        args.append(parse_dt(start + " 00:00:00") if len(start) == 10 else parse_dt(start))
    if end:
        where.append("created_at <= %s")
        args.append(parse_dt(end + " 23:59:59") if len(end) == 10 else parse_dt(end))

    sql = "SELECT * FROM vn_notes WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at %s, id %s" % ("DESC" if order != "asc" else "ASC", "DESC" if order != "asc" else "ASC")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM vn_notes WHERE " + " AND ".join(where), args)
            total = int(cur.fetchone()["c"])
            if not show_all:
                sql += " LIMIT %s OFFSET %s"
                args2 = args + [int(limit), int(offset)]
            else:
                args2 = args
            cur.execute(sql, args2)
            rows = cur.fetchall()
        rows = _attach_tags(conn, rows)
        for r in rows:
            for k in ("created_at", "updated_at", "last_copied_at", "remote_updated_at", "pulled_at"):
                r[k] = _fmt(r.get(k))
    finally:
        conn.close()
    return {"total": total, "notes": rows}


def get_note(note_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM vn_notes WHERE id=%s", (note_id,))
            row = cur.fetchone()
            if not row:
                return None
            _attach_tags(conn, [row])
            row["category_name"] = _cat_name(cur, row.get("category_id"))
            for k in ("created_at", "updated_at", "last_copied_at", "remote_updated_at", "pulled_at"):
                row[k] = _fmt(row.get(k))
            return row
    finally:
        conn.close()


def _cat_name(cur, cat_id):
    if not cat_id:
        return "未分类"
    cur.execute("SELECT name FROM vn_categories WHERE id=%s", (cat_id,))
    hit = cur.fetchone()
    return hit["name"] if hit else "未分类"


def create_note(content, category_id="", client_id="", created_at="", source="local", tags=None):
    nid = new_id()
    cid = (client_id or nid)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM vn_notes WHERE client_id=%s", (cid,))
            hit = cur.fetchone()
            if hit:
                return get_note(hit["id"])
            cur.execute(
                "INSERT INTO vn_notes (id,client_id,content,category_id,created_at,updated_at,copy_count,"
                "last_copied_at,source,remote_status) VALUES (%s,%s,%s,%s,%s,NULL,0,NULL,%s,'local')",
                (nid, cid, content, category_id or "", parse_dt(created_at) or now(), source))
    finally:
        conn.close()
    if tags:
        set_note_tags(nid, tags)
    return get_note(nid)


def update_note(note_id, content=None, category_id=None, tags=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM vn_notes WHERE id=%s", (note_id,))
            if not cur.fetchone():
                return None
            sets, args = [], []
            if content is not None:
                sets.append("content=%s")
                args.append(content)
            if category_id is not None:
                sets.append("category_id=%s")
                args.append(category_id)
            sets.append("updated_at=%s")
            args.append(now())
            args.append(note_id)
            cur.execute("UPDATE vn_notes SET %s WHERE id=%%s" % ",".join(sets), args)
    finally:
        conn.close()
    if tags is not None:
        set_note_tags(note_id, tags)
    return get_note(note_id)


def delete_note(note_id):
    """本地真删，并留墓标防止拉取时复活。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT client_id FROM vn_notes WHERE id=%s", (note_id,))
            hit = cur.fetchone()
            if not hit:
                return False
            cur.execute("INSERT INTO vn_tombstones (client_id,deleted_at) VALUES (%s,%s) "
                        "ON DUPLICATE KEY UPDATE deleted_at=VALUES(deleted_at)", (hit["client_id"], now()))
            cur.execute("DELETE FROM vn_note_tags WHERE note_id=%s", (note_id,))
            cur.execute("DELETE FROM vn_notes WHERE id=%s", (note_id,))
            return True
    finally:
        conn.close()


def record_copy(note_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE vn_notes SET copy_count = copy_count + 1, last_copied_at=%s WHERE id=%s", (now(), note_id))
            if not cur.rowcount:
                return False
    finally:
        conn.close()
    return True


# ------------------------------------------------------------------ 统计 / 元信息
def stats():
    conn = get_conn()
    out = {}
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) AS total, SUM(remote_status='local') AS only_local,
                              SUM(remote_status='deleted') AS remote_deleted, SUM(copy_count) AS copies
                           FROM vn_notes""")
            r = cur.fetchone()
            out["total"] = int(r["total"] or 0)
            out["only_local"] = int(r["only_local"] or 0)
            out["remote_deleted"] = int(r["remote_deleted"] or 0)
            out["copies"] = int(r["copies"] or 0)
            cur.execute("SELECT COUNT(*) AS c FROM vn_tags")
            out["tag_count"] = int(cur.fetchone()["c"])
            cur.execute("""SELECT DATE_FORMAT(created_at, %s) AS ym, COUNT(*) AS c
                           FROM vn_notes WHERE created_at IS NOT NULL
                           GROUP BY ym ORDER BY ym DESC LIMIT 12""", ("%Y-%m",))
            out["by_month"] = [{"ym": x["ym"], "count": int(x["c"])} for x in cur.fetchall()]
            cur.execute("SELECT MAX(pulled_at) AS p FROM vn_notes WHERE pulled_at IS NOT NULL")
            out["last_pulled_at"] = _fmt((cur.fetchone() or {}).get("p"))
    finally:
        conn.close()
    out["categories"] = list_categories()
    out["tags"] = list_tags()
    return out


def meta_get(key, default=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM vn_meta WHERE k=%s", (key,))
            hit = cur.fetchone()
            return hit["v"] if hit else default
    finally:
        conn.close()


def meta_set(key, value):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO vn_meta (k,v) VALUES (%s,%s) ON DUPLICATE KEY UPDATE v=VALUES(v)",
                        (key, str(value)))
    finally:
        conn.close()


def export_all():
    data = list_notes(show_all=True, limit=0, offset=0)["notes"]
    return {"version": 1, "exported_at": now(),
            "categories": list_categories(), "tags": list_tags(), "notes": data}
