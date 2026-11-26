// 音频标签编辑 - 前端逻辑
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const state = {
    config: {},
    files: [],
    currentPath: null,
    hasImg: { cover: false, bg: false },
    supportsBg: true,
    img: { cover: { action: "keep", path: "" }, bg: { action: "keep", path: "" } },
    fineRows: [],
    fineDir: null,
    polling: null,
    logLen: 0,
    running: false,
    avatarPath: null,
};

// ---------- 通用 ----------
async function api(method, url, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
        opt.headers["Content-Type"] = "application/json";
        opt.body = JSON.stringify(body);
    }
    const res = await fetch(url, opt);
    let data = null;
    try { data = await res.json(); } catch (e) { /* 无 JSON 体 */ }
    if (!res.ok) {
        const msg = (data && data.detail) ? data.detail : ("请求失败 " + res.status);
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
}

function toast(title, message, level = "info", ms = 3800) {
    const wrap = $("#toast-wrap");
    const el = document.createElement("div");
    el.className = "toast " + level;
    el.innerHTML = '<div class="t-title"></div><div class="t-msg"></div>';
    $(".t-title", el).textContent = title;
    $(".t-msg", el).textContent = message;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), ms);
}

function debounce(fn, ms) {
    let t = null;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function switchTab(name) {
    $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    $$(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + name));
}

// ---------- 配置 ----------
function fillConfig() {
    $$("[data-cfg]").forEach(el => {
        const k = el.dataset.cfg;
        if (!(k in state.config)) return;
        if (el.type === "checkbox") el.checked = !!state.config[k];
        else el.value = state.config[k] == null ? "" : state.config[k];
    });
    $("#fine-dir").textContent = state.config.input_dir || "";
}

const saveConfig = debounce(async () => {
    try { await api("POST", "/api/config", state.config); }
    catch (e) { /* 静默：下次动作会再存 */ }
}, 500);

function bindConfig() {
    $$("[data-cfg]").forEach(el => {
        const evt = el.type === "checkbox" ? "change" : "input";
        el.addEventListener(evt, () => {
            const k = el.dataset.cfg;
            const v = el.type === "checkbox" ? el.checked : el.value.trim();
            state.config[k] = v;
            // 同步同键的其它控件（如 sync_rename 出现两处）
            $$('[data-cfg="' + k + '"]').forEach(o => {
                if (o === el) return;
                if (o.type === "checkbox") o.checked = !!v; else o.value = v;
            });
            if (k === "input_dir") $("#fine-dir").textContent = v;
            saveConfig();
        });
    });
}

// ---------- 文件列表 / 单文件 ----------
async function refreshFiles() {
    const dir = state.config.input_dir || "";
    const box = $("#file-list");
    box.innerHTML = "";
    state.files = [];
    let data;
    try { data = await api("GET", "/api/files?dir=" + encodeURIComponent(dir)); }
    catch (e) { $("#file-count").textContent = "加载失败"; return; }
    if (!data.ok) { $("#file-count").textContent = data.message || "目录不存在"; return; }
    state.files = data.files;
    $("#file-count").textContent = "共 " + data.count + " 个音频";
    data.files.forEach(f => {
        const item = document.createElement("div");
        item.className = "file-item";
        item.dataset.path = f.path;
        item.innerHTML = '<span class="fname"></span> <span class="meta"></span>';
        $(".fname", item).textContent = f.name;
        $(".meta", item).textContent = "｜ 标题: " + (f.title || "（空）") + " ｜ 作者: " + (f.artist || "（空）");
        item.addEventListener("click", () => loadFile(f.path));
        box.appendChild(item);
    });
}

async function loadFile(path) {
    let d;
    try { d = await api("GET", "/api/file?path=" + encodeURIComponent(path)); }
    catch (e) { toast("载入失败", e.message, "error"); return; }
    state.currentPath = d.path;
    state.hasImg = { cover: !!d.cover, bg: !!d.bg };
    state.supportsBg = d.supports_bg !== false;
    state.img = { cover: { action: "keep", path: "" }, bg: { action: "keep", path: "" } };
    $("#loaded-name").textContent = d.name;
    $("#s-title").value = d.title;
    $("#s-artist").value = d.artist;
    $("#s-album").value = d.album;
    $("#s-date").value = d.date;
    $("#s-track").value = d.track;
    $("#s-comment").value = d.comment;
    $$(".img-box").forEach(b => { $(".img-path", b).value = ""; });
    renderImg("cover"); renderImg("bg");
    applyBgAvailability();
    $$(".file-item").forEach(it => it.classList.toggle("active", it.dataset.path === d.path));
}

function renderImg(kind) {
    const box = $('.img-box[data-kind="' + kind + '"]');
    const img = $("img", box), ph = $(".img-ph", box), st = $(".img-state", box);
    const s = state.img[kind];
    img.hidden = true; img.removeAttribute("src");
    if (s.action === "delete") {
        ph.hidden = false; ph.textContent = "（保存后将删除）"; st.textContent = "将删除";
    } else if (s.action === "set") {
        st.textContent = "将更换";
        if (s.path) { img.src = "/api/img?path=" + encodeURIComponent(s.path); img.hidden = false; ph.hidden = true; }
        else { ph.hidden = false; ph.textContent = "（填路径后点更换）"; }
    } else { // keep
        st.textContent = "";
        if (state.currentPath && state.hasImg[kind]) {
            img.src = "/api/preview?path=" + encodeURIComponent(state.currentPath) + "&kind=" + kind + "&t=" + Date.now();
            img.hidden = false; ph.hidden = true;
        } else {
            ph.hidden = false;
            ph.textContent = (kind === "bg" && !state.supportsBg)
                ? "（m4a 仅封面，无背景图）" : "（无图片）";
        }
    }
}

/* m4a 仅封面：禁用背景图槽位 */
function applyBgAvailability() {
    const box = $('.img-box[data-kind="bg"]');
    if (!box) return;
    const en = state.supportsBg;
    $$(".act-set, .act-del, .act-export", box).forEach(b => { b.disabled = !en; });
    const inp = $(".img-path", box);
    if (inp) inp.disabled = !en;
    box.style.opacity = en ? "" : "0.55";
}

function bindImageBoxes() {
    $$(".img-box").forEach(box => {
        const kind = box.dataset.kind;
        $(".act-set", box).addEventListener("click", () => {
            if (!state.currentPath) { toast("提示", "请先在列表中选择一个文件", "warning"); return; }
            const p = $(".img-path", box).value.trim();
            if (!p) { toast("提示", "请填写图片路径", "warning"); return; }
            state.img[kind] = { action: "set", path: p };
            renderImg(kind);
        });
        $(".act-del", box).addEventListener("click", () => {
            if (!state.currentPath) return;
            state.img[kind] = { action: "delete", path: "" };
            renderImg(kind);
        });
        $(".act-export", box).addEventListener("click", () => {
            if (!state.currentPath) { toast("提示", "请先选择文件", "warning"); return; }
            if (!state.hasImg[kind]) { toast("提示", "当前没有可导出的图片", "warning"); return; }
            window.open("/api/export?path=" + encodeURIComponent(state.currentPath) + "&kind=" + kind);
        });
    });
}

async function saveCurrent() {
    if (!state.currentPath) { toast("提示", "请先在列表中选择一个文件", "warning"); return; }
    const body = {
        path: state.currentPath,
        title: $("#s-title").value.trim(), artist: $("#s-artist").value.trim(),
        album: $("#s-album").value.trim(), date: $("#s-date").value.trim(),
        comment: $("#s-comment").value.trim(), track: $("#s-track").value.trim(),
        cover_action: state.img.cover.action, cover_path: state.img.cover.path,
        bg_action: state.img.bg.action, bg_path: state.img.bg.path,
        rename: !!state.config.sync_rename,
    };
    try {
        const d = await api("POST", "/api/file/save", body);
        toast("保存成功", "已写入标签\n" + d.name, "success");
        state.currentPath = d.final_path;
        await refreshFiles();
        await loadFile(d.final_path);
    } catch (e) { toast("保存失败", e.message, "error", 6000); }
}

// ---------- 多文件精修 ----------
async function fetchFineRows() {
    const dir = state.config.input_dir || "";
    const t2s = !!state.config.fine_t2s;
    const fw = state.config.clean_filter_words || "";
    return await api("GET", "/api/fine/list?dir=" + encodeURIComponent(dir)
        + "&t2s=" + t2s + "&filter_words=" + encodeURIComponent(fw));
}

async function loadFine() {
    let d;
    try { d = await fetchFineRows(); }
    catch (e) { toast("加载失败", e.message, "error"); return; }
    if (!d.ok) { toast("提示", d.message || "请先在“文件”页填写目录", "warning"); return; }
    if (state.config.fine_t2s && !d.have_zhconv)
        toast("缺少依赖", "繁转简需要 zhconv：pip install zhconv\n本次加载保留繁体。", "warning", 6000);
    state.fineDir = state.config.input_dir;
    state.fineRows = d.rows.map(r => ({ ...r, check: true, dirty: false }));
    renderFine();
    $("#fine-count").textContent = d.count + " 个文件";
}

function renderFine() {
    const body = $("#fine-body");
    body.innerHTML = "";
    state.fineRows.forEach((r, i) => {
        const tr = document.createElement("tr");
        const tdC = document.createElement("td");
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.checked = r.check;
        cb.addEventListener("change", () => { r.check = cb.checked; });
        tdC.appendChild(cb);
        const tdN = document.createElement("td");
        tdN.className = "orig"; tdN.textContent = r.name;
        const tdT = document.createElement("td");
        const inp = document.createElement("input");
        inp.type = "text"; inp.className = "title"; inp.value = r.title;
        inp.addEventListener("input", () => {
            r.title = inp.value; r.dirty = true; r.fallback = false; refreshMarks();
        });
        r.el = inp;
        tdT.appendChild(inp);
        tr.append(tdC, tdN, tdT);
        body.appendChild(tr);
    });
    refreshMarks();
}

function refreshMarks() {
    const counts = {};
    state.fineRows.forEach(r => {
        const t = (r.title || "").trim();
        if (t) counts[t] = (counts[t] || 0) + 1;
    });
    state.fineRows.forEach(r => {
        if (!r.el) return;
        const t = (r.title || "").trim();
        r.el.classList.remove("fb", "dup");
        if (r.fallback && !r.dirty) r.el.classList.add("fb");
        else if (t && counts[t] > 1) r.el.classList.add("dup");
    });
}

async function recleanFine() {
    if (!state.fineRows.length) { toast("提示", "请先点“加载列表”", "warning"); return; }
    let d;
    try { d = await fetchFineRows(); }
    catch (e) { toast("重新清洗失败", e.message, "error"); return; }
    const byPath = {};
    state.fineRows.forEach(r => { byPath[r.path] = r; });
    let n = 0;
    state.fineRows = d.rows.map(nr => {
        const old = byPath[nr.path];
        if (old && old.dirty) return old;       // 手改过的行保留
        n++;
        return { ...nr, check: old ? old.check : true, dirty: false };
    });
    renderFine();
    toast("已重新清洗", "重算 " + n + " 行（手改过的行已保留）", "success");
}

async function saveFine() {
    if (state.running) return;
    if (!state.fineRows.length) { toast("提示", "请先点“加载列表”", "warning"); return; }
    if (state.fineDir !== state.config.input_dir) {
        toast("提示", "目录已变化，请重新加载列表后再保存", "warning"); return;
    }
    const items = [];
    state.fineRows.forEach(r => {
        if (r.check && (r.title || "").trim()) items.push({ path: r.path, title: r.title.trim() });
    });
    if (!items.length) { toast("提示", "没有可处理的行：请勾选并填写标题", "warning"); return; }
    try {
        const d = await api("POST", "/api/fine/start", { config: state.config, items });
        if (d.skipped && d.skipped.length)
            toast("已跳过空标题", d.skipped.join(", "), "info");
        startPolling();
    } catch (e) { toast("无法启动", e.message, "error", 6000); }
}

// ---------- 批量 ----------
async function startBatch() {
    if (state.running) return;
    const c = state.config;
    const hasAny = c.batch_title_prefix || c.batch_artist || c.batch_album || c.batch_date
        || c.batch_comment || c.batch_cover_path || c.batch_bg_image_path
        || c.batch_random_cover || c.batch_random_bg;
    if (!hasAny) {
        if (!confirm("“参数”页全部留空：不会修改任何文本标签和图片，\n但会重写音轨号 n/N 并备份原文件。\n\n确定继续吗？"))
            return;
    }
    try {
        await api("POST", "/api/batch/start", c);
        startPolling();
    } catch (e) { toast("无法启动", e.message, "error", 6000); }
}

// ---------- JSON 歌曲清单 ----------
async function previewManifest() {
    const text = $("#manifest-text").value.trim();
    if (!text) { toast("提示", "请先粘贴 JSON 清单或选择 JSON 文件", "warning"); return; }
    let d;
    try { d = await api("POST", "/api/manifest/preview", { text, dir: state.config.input_dir || "" }); }
    catch (e) { toast("预览失败", e.message, "error", 7000); return; }
    const box = $("#manifest-preview");
    box.innerHTML = "";
    const sum = document.createElement("div");
    sum.textContent = "目录 " + d.total_files + " 个音频 / 清单 " + d.total_entries
        + " 项 → 匹配 " + d.matched + "（其中清洗回退 " + d.weak + "）"
        + "，未匹配文件 " + d.unmatched_files.length + "，未命中条目 " + d.unmatched_entries.length;
    box.appendChild(sum);
    const ul = document.createElement("div");
    if (d.unmatched_files.length)
        ul.textContent = "未匹配文件：" + d.unmatched_files.slice(0, 30).join("、")
            + (d.unmatched_files.length > 30 ? " …" : "");
    box.appendChild(ul);
    const ul2 = document.createElement("div");
    if (d.unmatched_entries.length)
        ul2.textContent = "未命中条目：" + d.unmatched_entries.slice(0, 30).join("、")
            + (d.unmatched_entries.length > 30 ? " …" : "");
    box.appendChild(ul2);
    if (d.matched) {
        const tbl = document.createElement("table");
        tbl.className = "fine-table manifest-table";
        tbl.innerHTML = '<thead><tr><th>文件</th><th>歌名</th><th>歌手</th><th>专辑</th></tr></thead>';
        const tb = document.createElement("tbody");
        d.rows.slice(0, 15).forEach(r => {
            const tr = document.createElement("tr");
            [r.file + (r.weak ? " ↺" : ""), r.title, r.artist, r.album || "（空）"].forEach(t => {
                const td = document.createElement("td");
                td.textContent = t;
                tr.appendChild(td);
            });
            tb.appendChild(tr);
        });
        tbl.appendChild(tb);
        box.appendChild(tbl);
        if (d.rows.length > 15) {
            const m = document.createElement("div");
            m.textContent = "…仅展示前 15 行（↺=清洗回退匹配）";
            box.appendChild(m);
        }
    }
}

async function startManifest() {
    if (state.running) return;
    const text = $("#manifest-text").value.trim();
    if (!text) { toast("提示", "请先粘贴 JSON 清单或选择 JSON 文件", "warning"); return; }
    try {
        const d = await api("POST", "/api/manifest/start", {
            text, config: state.config, rename: !!state.config.manifest_rename,
        });
        if (d.unmatched_files && d.unmatched_files.length)
            toast("部分未匹配", "有 " + d.unmatched_files.length + " 个文件不在清单中，已跳过", "info", 5000);
        startPolling();
    } catch (e) { toast("无法启动", e.message, "error", 7000); }
}

function bindManifest() {
    $("#btn-manifest-file").addEventListener("click", () => $("#manifest-file").click());
    $("#manifest-file").addEventListener("change", () => {
        const f = $("#manifest-file").files[0];
        if (!f) return;
        const rd = new FileReader();
        rd.onload = () => { $("#manifest-text").value = rd.result; toast("已载入", f.name, "success"); };
        rd.readAsText(f, "utf-8");
        $("#manifest-file").value = "";
    });
    $("#btn-manifest-preview").addEventListener("click", previewManifest);
    $("#btn-manifest-start").addEventListener("click", startManifest);
}

// ---------- 任务轮询 ----------
function setRunning(b) {
    state.running = b;
    ["#btn-batch", "#btn-fine-save", "#btn-fine-load", "#btn-fine-reclean",
     "#btn-manifest-start", "#btn-manifest-preview"]
        .forEach(s => { $(s).disabled = b; });
    $("#btn-stop").disabled = !b;
}

function startPolling() {
    setRunning(true);
    state.logLen = 0;
    $("#log").textContent = "";
    $("#progress-fill").style.width = "0";
    $("#status").textContent = "准备中...";
    switchTab("log");
    clearInterval(state.polling);
    state.polling = setInterval(pollTask, 500);
}

async function pollTask() {
    let st;
    try { st = await api("GET", "/api/task"); }
    catch (e) { return; }
    const logEl = $("#log");
    if (st.logs.length > state.logLen) {
        logEl.textContent += st.logs.slice(state.logLen).join("\n") + "\n";
        state.logLen = st.logs.length;
        logEl.scrollTop = logEl.scrollHeight;
    }
    if (st.total > 0) {
        $("#progress-fill").style.width = (st.idx / st.total * 100) + "%";
        if (st.state === "running") $("#status").textContent = "正在处理 " + st.idx + "/" + st.total;
    }
    if (st.state === "running") return;

    clearInterval(state.polling);
    state.polling = null;
    setRunning(false);
    const mode = st.mode;
    if (st.state === "done") {
        $("#progress-fill").style.width = "100%";
        $("#status").textContent = "完成：成功 " + st.done + "，失败 " + st.failed;
        logEl.textContent += "\n" + "=".repeat(60) + "\n任务结束：成功 " + st.done
            + "，失败 " + st.failed + "，用时 " + st.elapsed.toFixed(1) + " 秒\n" + "=".repeat(60) + "\n";
        logEl.scrollTop = logEl.scrollHeight;
        if (st.failed)
            toast("完成（有失败）", "成功 " + st.done + "，失败 " + st.failed + "\n明细见目录的『标签编辑失败清单.txt』", "warning", 7000);
        else
            toast({ fine: "精修完成", manifest: "清单套用完成" }[mode] || "批量完成",
                "成功 " + st.done + " 个，用时 " + st.elapsed.toFixed(1) + " 秒", "success", 5000);
        refreshFiles();
        if (mode === "fine") loadFine();
    } else if (st.state === "stopped") {
        $("#status").textContent = "已停止";
        logEl.textContent += "\n[停止] " + st.message + "\n已处理的文件均已保存并备份。\n";
        toast("已停止", st.message, "info");
        refreshFiles();
        if (mode === "fine") loadFine();
    } else if (st.state === "empty") {
        $("#status").textContent = "没有可处理的文件";
        $("#progress-fill").style.width = "0";
        toast("没有文件", st.message, "warning");
    } else if (st.state === "error") {
        $("#status").textContent = "出错";
        logEl.textContent += "\n[错误] " + st.message + "\n";
        toast("出错", st.message, "error", 7000);
    }
}

async function stopTask() {
    try { await api("POST", "/api/task/stop"); }
    catch (e) { /* ignore */ }
    $("#status").textContent = "正在停止（等当前文件结束）...";
}

// ---------- 清理备份 ----------
async function cleanupBackups() {
    const dir = state.config.input_dir || "";
    let info;
    try { info = await api("GET", "/api/backup?dir=" + encodeURIComponent(dir)); }
    catch (e) { toast("提示", e.message, "warning"); return; }
    if (!info.exists) { toast("提示", "该目录下没有备份文件夹：_backup_标签编辑", "info"); return; }
    if (info.count === 0) { toast("提示", "备份文件夹已空，无需清理", "info"); return; }
    if (!confirm("将永久删除备份文件夹及其中的 " + info.count + " 个文件：\n" + info.path
        + "\n\n这些是编辑标签前的原始备份，删除后无法通过本工具回退。\n\n确定继续吗？")) return;
    try {
        const d = await api("POST", "/api/cleanup", { dir });
        toast("已清理", "删除 " + d.count + " 个备份文件", "success");
    } catch (e) { toast("清理失败", e.message, "error", 6000); }
}

// ---------- 头像推荐 / 批量图片预览 ----------
async function avatarRandom() {
    const dir = state.config.avatar_dir || "";
    let d;
    try { d = await api("GET", "/api/avatar/random?dir=" + encodeURIComponent(dir)); }
    catch (e) { toast("推荐失败", e.message, "error"); return; }
    if (!d.path) { toast("提示", "头像目录不存在或没有图片", "warning"); return; }
    state.avatarPath = d.path;
    $("#avatar-img").src = "/api/img?path=" + encodeURIComponent(d.path);
    $("#avatar-name").textContent = d.name;
    $("#avatar-suggest").hidden = false;
}

function fillAvatar(which) {
    if (!state.avatarPath) return;
    const k = which === "cover" ? "batch_cover_path" : "batch_bg_image_path";
    state.config[k] = state.avatarPath;
    fillConfig();
    saveConfig();
    toast("已填入", (which === "cover" ? "封面图" : "背景图") + "路径已填入", "success");
}

function previewBatch(which) {
    const k = which === "cover" ? "batch_cover_path" : "batch_bg_image_path";
    const p = state.config[k];
    const box = $("#batch-preview");
    if (!p) { toast("提示", "请先填写图片路径", "warning"); return; }
    const img = document.createElement("img");
    img.src = "/api/img?path=" + encodeURIComponent(p);
    img.title = p;
    img.onerror = () => { toast("预览失败", "图片不存在或格式不支持", "error"); img.remove(); };
    box.innerHTML = "";
    box.appendChild(img);
}

// ---------- 初始化 ----------
async function init() {
    // 页签
    $$(".tab").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));
    bindConfig();
    bindImageBoxes();
    bindManifest();

    $("#btn-refresh").addEventListener("click", refreshFiles);
    $("#btn-cleanup").addEventListener("click", cleanupBackups);
    $("#btn-reload").addEventListener("click", () => { if (state.currentPath) loadFile(state.currentPath); });
    $("#btn-save-current").addEventListener("click", saveCurrent);
    $("#btn-fine-load").addEventListener("click", loadFine);
    $("#btn-fine-reclean").addEventListener("click", recleanFine);
    $("#btn-fine-save").addEventListener("click", saveFine);
    $("#btn-batch").addEventListener("click", startBatch);
    $("#btn-stop").addEventListener("click", stopTask);
    $("#btn-avatar-random").addEventListener("click", avatarRandom);
    $("#btn-avatar-cover").addEventListener("click", () => fillAvatar("cover"));
    $("#btn-avatar-bg").addEventListener("click", () => fillAvatar("bg"));
    $("#btn-preview-cover").addEventListener("click", () => previewBatch("cover"));
    $("#btn-preview-bg").addEventListener("click", () => previewBatch("bg"));

    // 依赖徽章
    try {
        const p = await api("GET", "/api/ping");
        const deps = $("#deps");
        const mk = (label, ok) => {
            const s = document.createElement("span");
            s.className = "badge" + (ok ? "" : " off");
            s.textContent = label + (ok ? " ✓" : " ✗");
            deps.appendChild(s);
        };
        mk("mutagen " + (p.mutagen || ""), !!p.mutagen);
        mk("zhconv", p.have_zhconv);
    } catch (e) { /* ignore */ }

    // 配置
    try { state.config = await api("GET", "/api/config"); }
    catch (e) { state.config = {}; }
    fillConfig();

    // 说明
    try { const t = await api("GET", "/api/tutorial"); $("#help").textContent = t.text; }
    catch (e) { /* ignore */ }

    refreshFiles();
}

init();