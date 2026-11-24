// 视频合并前端逻辑
const $ = (id) => document.getElementById(id);

// ── 夜间模式 ────────────────────────────────────

const THEME_KEY = "video_merger_theme";

function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $("themeToggle").textContent = theme === "dark" ? "☀️" : "🌙";
    $("themeToggle").title = theme === "dark" ? "切换日间模式" : "切换夜间模式";
}

function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(saved || (prefersDark ? "dark" : "light"));
}

initTheme();

$("themeToggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
});

let scanItems = [];      // 扫描结果（当前顺序）
let currentDir = "";
let pollTimer = null;
let lastOutput = "";

// ── 工具 ────────────────────────────────────────────

function fmtDuration(sec) {
    if (!sec) return "-";
    const s = Math.round(sec);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
             : `${m}:${String(ss).padStart(2, "0")}`;
}

function fmtSize(bytes) {
    if (bytes > 1024 ** 3) return (bytes / 1024 ** 3).toFixed(2) + " GB";
    return (bytes / 1024 ** 2).toFixed(1) + " MB";
}

function esc(text) {
    const d = document.createElement("div");
    d.textContent = text == null ? "" : String(text);
    return d.innerHTML;
}

async function postJson(url, body) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
    return data;
}

// ── 配置 / 最近目录 ──────────────────────────────────

async function loadConfig() {
    try {
        const cfg = await (await fetch("/api/config")).json();
        renderRecentDirs(cfg.recent_dirs || []);
    } catch (e) { console.error(e); }
}

function renderRecentDirs(dirs) {
    const box = $("recentDirs");
    if (!dirs.length) { box.innerHTML = ""; return; }
    box.innerHTML = "<span class='recent-label'>最近:</span> " +
        dirs.map((d, i) => `<a href="#" class="recent-link" data-idx="${i}">${esc(d)}</a>`).join(" ");
    box.querySelectorAll(".recent-link").forEach((a) => {
        a.addEventListener("click", (ev) => {
            ev.preventDefault();
            $("dirInput").value = dirs[Number(a.dataset.idx)];
            doScan();
        });
    });
}

// ── 扫描 ────────────────────────────────────────────

async function doScan() {
    const directory = $("dirInput").value.trim().replace(/^"|"$/g, "");
    if (!directory) { alert("请填写目录路径"); return; }
    $("scanBtn").disabled = true;
    $("scanBtn").textContent = "扫描中...";
    try {
        const result = await postJson("/api/scan", { directory });
        if (!result.ok) { alert(result.msg); return; }
        currentDir = result.directory;
        scanItems = result.items.map((it) => ({ ...it, selected: !it.error }));
        window.__analysis = result.analysis;
        renderFiles();
        $("fileCard").style.display = "";
        $("mergeCard").style.display = "";
        $("progressCard").style.display = "none";
        loadConfig();
    } catch (e) {
        alert(e.message);
    } finally {
        $("scanBtn").disabled = false;
        $("scanBtn").textContent = "扫描";
    }
}

// 按当前勾选集合重算兼容性提示（简化：直接展示全量扫描结论 + 提示）
function renderCompat() {
    const analysis = window.__analysis || {};
    const badge = $("compatBadge");
    const detail = $("compatDetail");
    const selected = scanItems.filter((it) => it.selected);
    const selectedErr = selected.filter((it) => it.error);
    const unchecked = scanItems.length - selected.length;

    let ok = analysis.compatible;
    let reasons = (analysis.reasons || []).slice();
    if (selectedErr.length) {
        ok = false;
        reasons.unshift("有 " + selectedErr.length + " 个选中文件探测失败: " + selectedErr.map((x) => x.name).join("、"));
    }

    if (selected.length < 2) {
        badge.textContent = "至少勾选 2 个文件";
        badge.className = "badge badge-warn";
        detail.style.display = "none";
        $("mergeBtn").disabled = true;
        return;
    }
    $("mergeBtn").disabled = false;

    if (ok) {
        badge.textContent = "✓ 参数一致，可无损直拷";
        badge.className = "badge badge-ok";
        detail.style.display = unchecked ? "block" : "none";
        if (unchecked) detail.innerHTML = `已排除 ${unchecked} 个文件（排除后建议重新扫描确认参数一致性）`;
    } else {
        badge.textContent = "⚠ 参数不一致，将自动重编码";
        badge.className = "badge badge-warn";
        detail.style.display = "block";
        detail.innerHTML = reasons.map((r) => "· " + esc(r)).join("<br>") +
            (unchecked ? `<br>· 已排除 ${unchecked} 个文件` : "");
    }
}

function renderFiles() {
    const tbody = $("fileTbody");
    tbody.innerHTML = scanItems.map((it, i) => `
        <tr class="${it.selected ? "" : "row-off"} ${it.error ? "row-err" : ""}">
            <td class="c">${i + 1}</td>
            <td class="c"><input type="checkbox" data-i="${i}" ${it.selected ? "checked" : ""}></td>
            <td title="${esc(it.path)}">${esc(it.name)} <span class="size">${fmtSize(it.size)}</span>${it.error ? `<div class="err">${esc(it.error)}</div>` : ""}</td>
            <td class="c">${fmtDuration(it.duration)}</td>
            <td class="c">${it.width ? it.width + "x" + it.height : "-"}</td>
            <td class="c">${it.fps || "-"}</td>
            <td class="c">${esc([it.vcodec, it.acodec].filter(Boolean).join(" + ")) || "-"}</td>
            <td class="c">
                <button class="mini" data-act="up" data-i="${i}" ${i === 0 ? "disabled" : ""}>↑</button>
                <button class="mini" data-act="down" data-i="${i}" ${i === scanItems.length - 1 ? "disabled" : ""}>↓</button>
                <button class="mini" data-act="toggle" data-i="${i}">${it.selected ? "排除" : "加入"}</button>
            </td>
        </tr>`).join("");

    const totalDur = scanItems.filter((x) => x.selected).reduce((s, x) => s + (x.duration || 0), 0);
    $("tableSummary").textContent =
        `共 ${scanItems.length} 个文件，选中 ${scanItems.filter((x) => x.selected).length} 个，总时长约 ${fmtDuration(totalDur)}`;

    tbody.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        cb.addEventListener("change", () => { scanItems[Number(cb.dataset.i)].selected = cb.checked; renderFiles(); renderCompat(); });
    });
    tbody.querySelectorAll("button.mini").forEach((btn) => {
        btn.addEventListener("click", () => {
            const i = Number(btn.dataset.i), act = btn.dataset.act;
            if (act === "up" && i > 0) { [scanItems[i - 1], scanItems[i]] = [scanItems[i], scanItems[i - 1]]; }
            else if (act === "down" && i < scanItems.length - 1) { [scanItems[i + 1], scanItems[i]] = [scanItems[i], scanItems[i + 1]]; }
            else if (act === "toggle") { scanItems[i].selected = !scanItems[i].selected; }
            renderFiles(); renderCompat();
        });
    });
    renderCompat();
}

// ── 合并 ────────────────────────────────────────────

async function doMerge() {
    const files = scanItems.filter((it) => it.selected).map((it) => it.path);
    if (files.length < 2) { alert("至少选择 2 个视频"); return; }
    if (!confirm(`将按当前顺序拼接 ${files.length} 个视频，确认开始？`)) return;

    $("mergeBtn").disabled = true;
    try {
        const res = await postJson("/api/merge", {
            files,
            directory: currentDir,
            mode: $("mergeMode").value,
            output_name: $("outputName").value.trim(),
        });
        lastOutput = res.output;
        $("progressCard").style.display = "";
        $("resultRow").style.display = "none";
        setProgress(0, `任务已启动（实际模式: ${res.actual_mode === "copy" ? "无损直拷" : "重编码"}）`);
        pollStatus(res.task_id);
    } catch (e) {
        alert(e.message);
        $("mergeBtn").disabled = false;
    }
}

function setPercent(p) {
    $("progressFill").style.width = Math.min(100, Math.max(0, p)) + "%";
    $("progressText").textContent = p.toFixed(1) + "%";
}

function setProgress(p, msg) {
    setPercent(p);
    $("progressMsg").textContent = msg || "";
}

async function pollStatus(taskId) {
    if (pollTimer) clearTimeout(pollTimer);
    try {
        const st = await (await fetch(`/api/merge/status/${taskId}`)).json();
        setPercent(st.percent);
        $("progressMsg").textContent = st.message || "";
        $("taskLog").textContent = (st.logs || []).join("\n");
        $("taskLog").scrollTop = $("taskLog").scrollHeight;

        if (st.status === "running") {
            pollTimer = setTimeout(() => pollStatus(taskId), 1000);
        } else if (st.status === "done") {
            setPercent(100);
            $("resultRow").style.display = "flex";
            $("resultText").textContent = "✅ 已生成: " + st.output;
            $("mergeBtn").disabled = false;
        } else {
            $("progressMsg").textContent = "❌ " + (st.error || "合并失败");
            $("mergeBtn").disabled = false;
        }
    } catch (e) {
        $("progressMsg").textContent = "查询状态失败: " + e.message;
        $("mergeBtn").disabled = false;
    }
}

async function revealOutput() {
    try {
        await postJson("/api/reveal", { path: lastOutput });
    } catch (e) { alert(e.message); }
}

// ── 事件绑定 ────────────────────────────────────────

$("scanBtn").addEventListener("click", doScan);
$("dirInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doScan(); });
$("mergeBtn").addEventListener("click", doMerge);
$("revealBtn").addEventListener("click", revealOutput);

loadConfig();
