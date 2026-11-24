# -*- coding: utf-8 -*-
"""前端升级说明 docx 自动生成（仅门诊 /api/upgrade/doc/*，服务端升级不做）。

流程：把模板（默认 前端升级说明-1.5.1.docx）复制到 zip 所在订单目录，
按已斧正的石家庄新句式改写文案，重命名为「{订单号}{医院名}前端升级说明.docx」。

替换项（2026-11 与用户逐条确认）：
- 自动：医院名称 / 订单号（订单目录名解析）、程序名称（取 zip 文件名）、
  版本号（zip 名中 V 段，去 -缩写-FE 后缀）、程序升级说明两处包名
- 新句式：程序升级说明整段重写（4.1/4.2、sh publish_front.sh、缓存校验结尾）、
  备份说明加「1、」前缀、删除数据库升级说明行、文末加模板说明行
- 自动拼接：升级内容（订单信息 + 「 订单定制内容」）
- 保留模板原文（弹窗里可编辑）：操作说明 / 升级后验证方式

实现：纯 zipfile + ElementTree 改写 word/document.xml 的表格文本（venv 无
python-docx/lxml），布局与图片原样保留；序列化前注册原文件全部 xmlns 前缀，
并用原始根标签拼回，避免 Word 因命名空间声明丢失报错。
"""
import copy
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi import HTTPException

from .upgrade import FRONT_REMOTE_DIR, PUBLISH_FRONT_SCRIPT

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOC_ENTRY = "word/document.xml"

END_NOTE = ("以上为研发版本迭代或特殊订单升级说明模板，由于版本迭代修改功能较多，"
            "操作说明可简要填写。")

# plan/generate 共用的可编辑字段定义：key → 弹窗标签 + 说明
FIELD_DEFS = (
    ("hospital_name", "项目名称/医院名称", ""),
    ("order_no", "订单号", ""),
    ("zip_name", "程序名称", "取打出的 zip 文件名"),
    ("version", "版本号", "zip 名中截取，去掉 -缩写-FE 后缀"),
    ("upgrade_content", "升级内容(功能简述)", "默认为「订单信息 + 订单定制内容」，可编辑"),
    ("backup_desc", "备份说明", "新句式：前缀「1、」"),
    ("program_desc", "程序升级说明", "新句式自动改写，可编辑"),
    ("operation", "操作说明", "默认保留模板原文，可编辑"),
    ("verify", "升级后验证方式", "默认保留模板原文，可编辑"),
)

_ORDER_DIR_RE = re.compile(r"^(\d{4}-\d{3,})(.+)$")
_VERSION_RE = re.compile(r"V\d+(?:\.\d+)+")


# ── docx 读取 / 表格行定位 ────────────────────────────────────────

def _load_document(path):
    """返回 (zip内全部条目名, document.xml 原文 str, ElementTree root)。"""
    with zipfile.ZipFile(str(path)) as z:
        names = z.namelist()
        raw = z.read(DOC_ENTRY).decode("utf-8")
    m_root = re.search(r"<[A-Za-z0-9_]*:?document[^>]*>", raw)
    for prefix, uri in re.findall(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"',
                                  m_root.group(0) if m_root else ""):
        if prefix != "xml":
            ET.register_namespace(prefix, uri)
    return names, raw, ET.fromstring(raw)


def _para_text(p):
    parts = []
    for node in p.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "br":
            parts.append("\n")
    return "".join(parts)


def _cell_text(tc):
    lines = [_para_text(p) for p in tc.findall(W + "p")]
    return "\n".join(x for x in lines if x.strip())


def _table_rows(root):
    """按文档顺序返回所有表格行 (tr)，说明文档正文就是一张大表格。"""
    return [tr for tbl in root.iter(W + "tbl") for tr in tbl.findall(W + "tr")]


def _parent_map(root):
    """ElementTree 没有 getparent，预建 child→parent 映射供删行用。"""
    return {child: parent for parent in root.iter() for child in parent}


def _row_cells(tr):
    return tr.findall(W + "tc")


def _find_row(rows, pred):
    for tr in rows:
        if pred([_cell_text(tc) for tc in _row_cells(tr)]):
            return tr
    return None


def _first_text_run_props(tc):
    """取单元格第一个有文字段落的 pPr / 第一个 run 的 rPr 作样式模板。"""
    ppr = rpr = None
    for p in tc.findall(W + "p"):
        if ppr is None:
            ppr = p.find(W + "pPr")
        for r in p.iter(W + "r"):
            if r.find(W + "t") is not None:
                rpr = r.find(W + "rPr")
                break
        if ppr is not None and rpr is not None:
            break
    return ppr, rpr


def _set_cell_text(tc, text):
    """整格重写为多段文本，保留段落/字体样式模板。"""
    ppr, rpr = _first_text_run_props(tc)
    for p in tc.findall(W + "p"):
        tc.remove(p)
    for line in [x for x in (text or "").split("\n")]:
        p = ET.SubElement(tc, W + "p")
        if ppr is not None:
            p.append(copy.deepcopy(ppr))
        r = ET.SubElement(p, W + "r")
        if rpr is not None:
            r.append(copy.deepcopy(rpr))
        t = ET.SubElement(r, W + "t")
        t.text = line
        t.set(XML_SPACE, "preserve")


# ── 派生与句式 ────────────────────────────────────────────────────

def _derive_from_zip(zip_path):
    """订单目录名 → 订单号/医院名；zip 名 → 程序名称/版本号。推导失败给警告不报错。"""
    p = Path(str(zip_path or "").strip().strip('"'))
    warnings = []
    if p.suffix.lower() != ".zip":
        warnings.append("所选文件不是 .zip，包名/版本号需手动填写")
    order_no, hospital = "", ""
    # zip 一般放在订单目录的「前端」子目录里，订单名在上两级，逐层向上找
    for anc in (p.parent, p.parent.parent):
        m = _ORDER_DIR_RE.match(anc.name if str(anc) not in ("", ".") else "")
        if m:
            order_no, hospital = m.group(1), m.group(2)
            break
    if not order_no:
        warnings.append("未在上两级目录找到「订单号+医院名」（如 2026-2261石家庄市中医院），请手动核对")
    mv = _VERSION_RE.search(p.name)
    version = mv.group(0) if mv else ""
    if not version and p.suffix.lower() == ".zip":
        warnings.append("未能从文件名解析版本号，请手动填写")
    return {
        "zip_path": str(p),
        "zip_name": p.name,
        "order_no": order_no,
        "hospital_name": hospital,
        "version": version,
        "target_dir": str(p.parent) if str(p.parent) not in ("", ".") else "",
        "target_name": ("%s%s前端升级说明.docx" % (order_no, hospital)) if order_no and hospital
                       else "前端升级说明.docx",
        "warnings": warnings,
    }


def _program_desc(version, zip_name):
    """按石家庄最终版固化的新句式。"""
    return "\n".join([
        "确保升级时间不影响医院的业务。",
        "升级类型：增量升级",
        "当前发布程序的版本号是：%s" % version,
        "前端（B端）升级：",
        "4.1.将发布的应用复制到%s下。" % FRONT_REMOTE_DIR,
        "4.2.使用控制台命令：cd %s进入升级应用所在目录" % FRONT_REMOTE_DIR,
        "使用单独升级脚本对应用升级：",
        "sh %s %s" % (PUBLISH_FRONT_SCRIPT, zip_name),
        "校验：确认命令执行成功即可；如果不生效可以采用清除缓存、开启浏览器的无痕模式"
        "以及更换浏览器进行操作。",
    ])


def _template_defaults(template_path):
    """读模板各格原文，作为 keep 字段的默认值（弹窗里用户仍可编辑）。"""
    _, _, root = _load_document(template_path)
    rows = _table_rows(root)
    out = {}

    def grab(pred, idx):
        tr = _find_row(rows, pred)
        if tr is not None:
            cells = _row_cells(tr)
            if len(cells) > idx:
                return _cell_text(cells[idx])
        return ""

    out["upgrade_content"] = grab(lambda c: c and c[0].startswith("升级内容"), 1)
    out["backup_desc"] = grab(lambda c: c and c[0].strip() == "备份说明", 1)
    out["operation"] = grab(lambda c: c and c[0].strip() == "操作说明", 1)
    out["verify"] = grab(lambda c: c and c[0].startswith("升级后验证方式"), 1)
    return out


# ── 对外：plan / generate ─────────────────────────────────────────

def make_plan(zip_path, template_path):
    """弹窗初始数据：派生值 + 模板原文 + 目标路径。"""
    tpl = Path(str(template_path or ""))
    if not tpl.is_file():
        raise HTTPException(400, "升级说明模板不存在：%s" % tpl)
    derived = _derive_from_zip(zip_path)
    defaults = _template_defaults(tpl)

    backup = defaults.get("backup_desc", "")
    if backup and not re.match(r"^\d+[、.]", backup):
        backup = "1、" + backup

    # 升级内容默认拼接：完整订单信息（订单号+医院名）+「 订单定制内容」；
    # 订单信息解析不到时回落到模板原文，避免留下光秃秃的「订单定制内容」。
    order_full = (derived["order_no"] + derived["hospital_name"]).strip()
    upgrade_content = (order_full + " 订单定制内容") if order_full \
        else defaults.get("upgrade_content", "")

    values = {
        "hospital_name": derived["hospital_name"],
        "order_no": derived["order_no"],
        "zip_name": derived["zip_name"],
        "version": derived["version"],
        "upgrade_content": upgrade_content,
        "backup_desc": backup,
        "program_desc": _program_desc(derived["version"] or "V×.×.×.×××××.×××××",
                                      derived["zip_name"]),
        "operation": defaults.get("operation", ""),
        "verify": defaults.get("verify", ""),
    }
    fields = [{"key": k, "label": label, "hint": hint, "value": values[k]}
              for k, label, hint in FIELD_DEFS]
    target = Path(derived["target_dir"]) / derived["target_name"] if derived["target_dir"] else None
    return {"fields": fields, "template": str(tpl),
            "target_dir": derived["target_dir"], "target_name": derived["target_name"],
            "target_exists": bool(target and target.is_file()),
            "drop_db_row": True, "append_note": True, "end_note": END_NOTE,
            "warnings": derived["warnings"]}


def _patch_namespaces(serialized, original_raw):
    """ET 会把全部命名空间声明收敛到根标签；在序列化根标签上补回原文件声明但
    未被使用的 xmlns（mc:Ignorable 引用的前缀丢了会导致 Word / 解析器报错）。"""
    m_orig = re.search(r"<[A-Za-z0-9_]*:?document[^>]*>", original_raw)
    m_new = re.search(r"<[A-Za-z0-9_]*:?document[^>]*>", serialized)
    if not (m_orig and m_new):
        raise RuntimeError("document.xml 根标签解析失败")
    new_tag = m_new.group(0)
    declared_uri = {p: u for p, u in
                    re.findall(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', new_tag)}
    extra = ['xmlns:%s="%s"' % (p, u)
             for p, u in re.findall(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', m_orig.group(0))
             if p not in declared_uri]
    merged = new_tag[:-1] + ((" " + " ".join(extra)) if extra else "") + ">"
    body = serialized[:m_new.start()] + merged + serialized[m_new.end():]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + body).encode("utf-8")


def generate(data):
    """按弹窗确认（可能已编辑）的字段写出 docx，返回 {ok, path}。"""
    data = data or {}
    template = Path(str(data.get("template") or ""))
    target_dir = Path(str(data.get("target_dir") or "").strip().strip('"'))
    target_name = str(data.get("target_name") or "").strip()
    if not template.is_file():
        raise HTTPException(400, "模板不存在：%s" % template)
    if not target_dir.is_dir():
        raise HTTPException(400, "目标目录不存在：%s" % target_dir)
    if not target_name.lower().endswith(".docx"):
        raise HTTPException(400, "文件名必须以 .docx 结尾：%s" % target_name)
    target = target_dir / target_name
    if target.is_file() and not data.get("overwrite"):
        raise HTTPException(409, "文件已存在，勾选覆盖或改文件名：%s" % target)

    fields = {f.get("key"): str(f.get("value") or "")
              for f in (data.get("fields") or []) if isinstance(f, dict)}
    drop_db = bool(data.get("drop_db_row", True))
    append_note = bool(data.get("append_note", True))
    note_text = str(data.get("end_note") or END_NOTE)

    names, raw, root = _load_document(template)
    rows = _table_rows(root)
    body = root.find(W + "body")
    defaults = _template_defaults(template)   # 保留项：未编辑则不动原 XML，样式零损失

    def _cell(tr, idx):
        cells = _row_cells(tr)
        return cells[idx] if len(cells) > idx else None

    def apply(row_pred, edits):
        """edits: [(cell_idx, value, only_if_changed_old)]"""
        tr = _find_row(rows, row_pred)
        if tr is None:
            return
        for idx, value, skip_default in edits:
            tc = _cell(tr, idx)
            if tc is None:
                continue
            if skip_default is not None and value == skip_default:
                continue  # 未做修改的保留项：不动原 XML，样式零损失
            _set_cell_text(tc, value)

    # 表头行：医院名称在 cell1，订单号在 cell3
    apply(lambda c: c and c[0].startswith("项目名称/医院名称"),
          [(1, fields.get("hospital_name", ""), None),
           (3, fields.get("order_no", ""), None)])
    # 升级包数据行：模板里第二格是 .zip 文件名的那行
    apply(lambda c: len(c) > 1 and c[1].rstrip().lower().endswith(".zip"),
          [(1, fields.get("zip_name", ""), None),
           (2, fields.get("version", ""), None)])
    apply(lambda c: c and c[0].startswith("升级内容"),
          [(1, fields.get("upgrade_content", ""), defaults.get("upgrade_content", ""))])
    apply(lambda c: c and c[0].strip() == "备份说明",
          [(1, fields.get("backup_desc", ""), None)])
    apply(lambda c: c and c[0].strip() == "程序升级说明",
          [(1, fields.get("program_desc", ""), None)])
    apply(lambda c: c and c[0].strip() == "操作说明",
          [(1, fields.get("operation", ""), defaults.get("operation", ""))])
    apply(lambda c: c and c[0].startswith("升级后验证方式"),
          [(1, fields.get("verify", ""), defaults.get("verify", ""))])

    if drop_db:
        tr = _find_row(rows, lambda c: c and c[0].strip() == "数据库升级说明")
        if tr is not None:
            parents = _parent_map(root)
            parent = parents.get(tr)
            if parent is not None:
                parent.remove(tr)

    if append_note and note_text:
        p = ET.Element(W + "p")
        r = ET.SubElement(p, W + "r")
        t = ET.SubElement(r, W + "t")
        t.text = note_text
        t.set(XML_SPACE, "preserve")
        sect = body.find(W + "sectPr")
        if sect is not None:
            body.insert(list(body).index(sect), p)   # sectPr 必须保持在末尾
        else:
            body.append(p)

    new_xml = _patch_namespaces(ET.tostring(root, encoding="unicode"), raw)
    _write_docx(template, target, names, new_xml)
    return {"ok": True, "path": str(target)}


def _write_docx(template, target, names, new_xml):
    """除 document.xml 外所有条目原样复制；临时文件写完再替换，失败不留半截档。"""
    tmp = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(str(template)) as zin, \
             zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                payload = new_xml if item.filename == DOC_ENTRY else zin.read(item.filename)
                zout.writestr(item, payload)
        tmp.replace(target)
    finally:
        Path(str(tmp)).unlink(missing_ok=True)


def attach_docgen_routes(app, profile, store):
    """仅门诊前端升级使用：/api/upgrade/doc/plan 出弹窗数据，/generate 写文件。"""

    @app.post("/api/upgrade/doc/plan")
    def upgrade_doc_plan(data: dict):
        data = data or {}
        cfg = store.load()
        template = data.get("template") or cfg.get("upgrade_doc_template", "")
        return make_plan(data.get("zip_path", ""), template)

    @app.post("/api/upgrade/doc/generate")
    def upgrade_doc_generate(data: dict):
        return generate(data)
