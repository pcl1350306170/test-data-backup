/* Grok 会话导出工具 - 前端逻辑 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    loaded: false,
    path: '',
    size: 0,
    sessions: [],         // 元信息列表
    selected: new Set(),  // 选中的会话 index
    search: '',
    sortBy: 'index',
    sortDesc: false,
    taskId: null,
    polling: null,
    lastResultDir: '',
  };

  // ── 通用：toast / fetch 包装 ─────────────────────
  let toastTimer = null;
  function toast(msg, type = '') {
    const el = $('#toast');
    el.textContent = msg;
    el.className = 'toast ' + type;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
      body: opts.body && typeof opts.body !== 'string' ? JSON.stringify(opts.body) : opts.body,
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        if (j && j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  // ── ① 文件选择 ────────────────────────────────────
  $('#btn-pick-file').addEventListener('click', async () => {
    try {
      const r = await api('/api/pick_file', { method: 'POST', body: {} });
      if (r.path) { $('#path-input').value = r.path; await loadJson(r.path); }
    } catch (e) { toast('打开文件对话框失败：' + e.message, 'err'); }
  });

  $('#btn-load-path').addEventListener('click', async () => {
    const p = $('#path-input').value.trim();
    if (!p) return toast('请输入 JSON 文件路径', 'err');
    await loadJson(p);
  });

  $('#btn-reload').addEventListener('click', async () => {
    if (!state.path) return toast('尚未加载文件', 'err');
    await loadJson(state.path);
  });

  // 拖拽 → 上传文件
  const zone = $('#drop-zone');
  ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation();
    zone.classList.add('dragover');
  }));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation();
    zone.classList.remove('dragover');
  }));
  zone.addEventListener('drop', async (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.json')) return toast('请拖入 .json 文件', 'err');
    await uploadFile(file);
  });

  async function uploadFile(file) {
    try {
      toast('上传中…');
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/upload', { method: 'POST', body: fd });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || ('HTTP ' + res.status));
      }
      const data = await res.json();
      applyLoadResult(data);
      toast('上传解析完成', 'ok');
    } catch (e) {
      toast('上传失败：' + e.message, 'err');
    }
  }

  async function loadJson(path) {
    try {
      const data = await api('/api/load', { method: 'POST', body: { path } });
      applyLoadResult(data);
      toast('加载成功', 'ok');
    } catch (e) {
      $('#file-info').textContent = '加载失败：' + e.message;
      toast('加载失败：' + e.message, 'err');
    }
  }

  function applyLoadResult(data) {
    state.loaded = true;
    state.path = data.path;
    state.size = data.size;
    state.sessions = data.sessions;
    state.selected = new Set(data.sessions.map(s => s.index));
    $('#file-info').innerHTML = formatFileInfo(data);
    $('#stat-conv').textContent = data.summary.conversation_count;
    $('#stat-msg').textContent = data.summary.message_count;
    $('#stat-user').textContent = data.summary.human_count;
    $('#stat-grok').textContent = data.summary.grok_count;
    if (!$('#output-dir').value) $('#output-dir').value = data.default_output_dir;
    renderSessionTable();
  }

  function formatFileInfo(data) {
    const sizeMb = (data.size / 1024 / 1024).toFixed(2);
    return `<strong>路径：</strong>${data.path}<br><strong>大小：</strong>${data.size.toLocaleString()} 字节（${sizeMb} MB）`;
  }

  // ── ③ 会话表 ──────────────────────────────────────
  function filteredSortedSessions() {
    const q = state.search.trim().toLowerCase();
    let list = state.sessions.filter(s => !q || s.title.toLowerCase().includes(q));
    const k = state.sortBy;
    list.sort((a, b) => {
      const av = a[k], bv = b[k];
      if (av === bv) return a.index - b.index;
      return av < bv ? -1 : 1;
    });
    if (state.sortDesc) list.reverse();
    return list;
  }

  function renderSessionTable() {
    const tbody = $('#session-tbody');
    const list = filteredSortedSessions();
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty">' + (state.loaded ? '无匹配会话' : '尚未加载数据') + '</td></tr>';
    } else {
      tbody.innerHTML = list.map(s => `
        <tr data-index="${s.index}">
          <td><input type="checkbox" class="row-check" data-index="${s.index}" ${state.selected.has(s.index) ? 'checked' : ''}></td>
          <td>${s.index}</td>
          <td class="title-cell" title="${escapeAttr(s.title)}">${escapeHtml(s.title)}</td>
          <td class="w-num">${s.message_count}</td>
          <td class="w-num">${s.human_count}</td>
          <td class="w-num">${s.grok_count}</td>
          <td class="w-time">${s.create_time}</td>
          <td class="w-time">${s.modify_time}</td>
          <td><button class="link-btn" data-preview="${s.index}">预览</button></td>
        </tr>
      `).join('');
    }
    $$('#session-tbody .row-check').forEach(cb => {
      cb.addEventListener('change', () => {
        const idx = Number(cb.dataset.index);
        if (cb.checked) state.selected.add(idx); else state.selected.delete(idx);
        updateSelectionCount();
      });
    });
    $$('#session-tbody [data-preview]').forEach(btn => {
      btn.addEventListener('click', () => openPreview(Number(btn.dataset.preview)));
    });
    updateSelectionCount();
  }

  function updateSelectionCount() {
    $('#selection-count').textContent = `已选 ${state.selected.size} / ${state.sessions.length}`;
    $('#check-all').checked = state.sessions.length > 0 && state.selected.size === state.sessions.length;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }

  $('#btn-select-all').addEventListener('click', () => {
    state.sessions.forEach(s => state.selected.add(s.index));
    renderSessionTable();
  });
  $('#btn-select-none').addEventListener('click', () => {
    state.selected.clear();
    renderSessionTable();
  });
  $('#check-all').addEventListener('change', (e) => {
    if (e.target.checked) state.sessions.forEach(s => state.selected.add(s.index));
    else state.selected.clear();
    renderSessionTable();
  });
  $('#search-input').addEventListener('input', (e) => { state.search = e.target.value; renderSessionTable(); });
  $('#sort-by').addEventListener('change', (e) => { state.sortBy = e.target.value; renderSessionTable(); });
  $('#sort-desc').addEventListener('change', (e) => { state.sortDesc = e.target.checked; renderSessionTable(); });

  // ── ⑤ 导出目录 ────────────────────────────────────
  $('#btn-pick-dir').addEventListener('click', async () => {
    try {
      const r = await api('/api/pick_dir', { method: 'POST', body: {} });
      if (r.path) $('#output-dir').value = r.path.replace(/\//g, '\\');
    } catch (e) { toast('打开目录对话框失败：' + e.message, 'err'); }
  });

  // ── ⑥ 导出操作 ────────────────────────────────────
  function collectOptions() {
    const formats = $$('.opt-format').filter(c => c.checked).map(c => c.value);
    const scope = ($$('input[name=scope]').find(c => c.checked) || {}).value || 'all';
    const org = ($$('input[name=org]').find(c => c.checked) || {}).value || 'individual';
    return {
      formats,
      scope,
      organization: org,
      output_dir: $('#output-dir').value.trim(),
      include_title: $('#opt-title').checked,
      include_time_meta: $('#opt-time-meta').checked,
      include_sender_label: $('#opt-sender-label').checked,
      include_timestamp: $('#opt-timestamp').checked,
      include_separator: $('#opt-separator').checked,
      preserve_markdown: $('#opt-preserve-md').checked,
    };
  }

  $('#btn-export').addEventListener('click', async () => {
    const opts = collectOptions();
    if (!opts.formats.length) return toast('请至少勾选一种导出格式', 'err');
    if (!state.selected.size) return toast('请至少选择一个会话', 'err');
    if (!state.loaded) return toast('请先加载 JSON 文件', 'err');

    $('#export-log').innerHTML = '';
    $('#export-result').classList.remove('show', 'ok', 'error');
    setProgress(0, '准备中…');
    $('#btn-export').disabled = true;
    $('#btn-cancel').disabled = false;

    try {
      const r = await api('/api/export', {
        method: 'POST',
        body: { options: opts, selected: Array.from(state.selected) },
      });
      state.taskId = r.task_id;
      state.lastResultDir = r.output_dir;
      startPolling(r.task_id);
    } catch (e) {
      toast('启动导出失败：' + e.message, 'err');
      $('#btn-export').disabled = false;
      $('#btn-cancel').disabled = true;
    }
  });

  $('#btn-cancel').addEventListener('click', async () => {
    if (!state.taskId) return;
    try { await api('/api/cancel', { method: 'POST', body: { task_id: state.taskId } }); toast('已请求取消'); }
    catch (e) { toast('取消失败：' + e.message, 'err'); }
  });

  $('#btn-open-dir').addEventListener('click', async () => {
    const dir = state.lastResultDir || $('#output-dir').value.trim();
    if (!dir) return toast('导出目录为空', 'err');
    try { await api('/api/open_dir', { method: 'POST', body: { path: dir } }); }
    catch (e) { toast('打开失败：' + e.message, 'err'); }
  });

  function startPolling(taskId) {
    let cursor = 0;
    const tick = async () => {
      try {
        const r = await api(`/api/progress?task_id=${taskId}&since=${cursor}`);
        for (const ev of r.events) handleEvent(ev);
        cursor = r.next;
        if (r.done) {
          finishExport(r.result);
          return;
        }
      } catch (e) {
        logLine('轮询失败：' + e.message, 'err');
        finishExport({ error: e.message });
        return;
      }
      state.polling = setTimeout(tick, 600);
    };
    tick();
  }

  function handleEvent(ev) {
    const total = ev.total || 0;
    const cur = ev.current || 0;
    if (total) setProgress(cur / total * 100, `${ev.stage} · ${ev.title || ''} (${cur}/${total})`);
    if (ev.stage === 'ok') logLine(`[OK] ${ev.title}`, 'ok');
    else if (ev.stage === 'error') logLine(`[ERR] ${ev.title}: ${ev.error}`, 'err');
    else if (ev.stage === 'cancelled') logLine(`[CANCEL] ${ev.title}`, 'err');
    else if (ev.stage === 'fatal') logLine(`[FATAL] ${ev.error}`, 'err');
  }

  function finishExport(result) {
    clearTimeout(state.polling);
    state.polling = null;
    state.taskId = null;
    $('#btn-export').disabled = false;
    $('#btn-cancel').disabled = true;
    const box = $('#export-result');
    box.classList.add('show');
    if (result && result.error) {
      box.classList.add('error');
      box.textContent = '导出异常：' + result.error;
      setProgress(100, '失败');
      return;
    }
    const ok = result?.success || 0;
    const fail = result?.failed || 0;
    const cancel = result?.cancelled || 0;
    const files = (result?.files || []).length;
    if (fail === 0 && cancel === 0) {
      box.classList.add('ok');
      setProgress(100, '完成');
    } else {
      box.classList.add('error');
    }
    box.innerHTML = `成功 <strong>${ok}</strong> · 失败 <strong>${fail}</strong> · 取消 <strong>${cancel}</strong> · 文件 <strong>${files}</strong> 个<br>输出目录：${escapeHtml(result?.output_dir || '')}`;
    if ((result?.errors || []).length) {
      box.innerHTML += '<br>失败详情：<br>' + result.errors.map(e => `· ${escapeHtml(e.title)} — ${escapeHtml(e.error)}`).join('<br>');
    }
  }

  function setProgress(pct, text) {
    $('#progress-fill').style.width = Math.max(0, Math.min(100, pct)) + '%';
    if (text != null) $('#progress-text').textContent = text;
  }

  function logLine(text, cls = '') {
    const li = document.createElement('li');
    li.textContent = text;
    if (cls) li.className = cls;
    $('#export-log').appendChild(li);
    $('#export-log').scrollTop = $('#export-log').scrollHeight;
  }

  // ── 预览 ──────────────────────────────────────────
  async function openPreview(index) {
    const sess = state.sessions.find(s => s.index === index);
    if (!sess) return;
    $('#preview-title').textContent = sess.title;
    $('#preview-content').textContent = '加载中…';
    $('#preview-modal').classList.remove('hidden');
    await renderPreview(index);
  }
  async function renderPreview(index) {
    const format = $('#preview-format').value;
    const scope = ($$('input[name=scope]').find(c => c.checked) || {}).value || 'all';
    try {
      const r = await api('/api/preview', { method: 'POST', body: { index, format, scope } });
      $('#preview-content').textContent = r.text;
    } catch (e) {
      $('#preview-content').textContent = '预览失败：' + e.message;
    }
  }
  $('#preview-format').addEventListener('change', () => {
    const cur = $$('#session-tbody .row-check').find(c => c.checked);
    const idx = Number($('#preview-title').dataset.index || 0);
    if (idx) renderPreview(idx);
  });
  $('#btn-close-preview').addEventListener('click', () => {
    $('#preview-modal').classList.add('hidden');
    $('#preview-title').dataset.index = '';
  });
  // 给 title 元素存一下当前预览 index
  const _oldOpen = openPreview;
  openPreview = (idx) => { $('#preview-title').dataset.index = idx; _oldOpen(idx); };

  // 点击遮罩关闭
  $('.modal-mask')?.addEventListener('click', () => $('#btn-close-preview').click());

  // ── 初始化：恢复上次状态 ─────────────────────────
  (async function init() {
    try {
      const st = await api('/api/state');
      if (st.loaded) {
        applyLoadResult({
          path: st.path, size: st.size,
          summary: st.summary, sessions: st.sessions,
          default_output_dir: st.default_output_dir,
        });
        $('#path-input').value = st.path;
        toast('已恢复上次加载的 JSON', 'ok');
      }
    } catch (e) {
      console.warn('恢复状态失败：', e);
    }
  })();
})();
