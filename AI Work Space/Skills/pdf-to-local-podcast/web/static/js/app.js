/* ═══ 全局工具 & Tab 切换 ═══ */
const App = {
  currentTab: 'scripts',
  config: {},

  async init() {
    // 加载配置
    this.config = await this.api('/api/config');
    // 初始化 Tab 切换
    document.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
    });
    // 初始化各模块
    Scripts.init();
    Voices.init();
    Task.init();
    Player.init();
    Settings.init();
    // 加载初始 Tab 数据
    this.switchTab('scripts');
  },

  switchTab(name) {
    this.currentTab = name;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.toggle('active', s.id === 'tab-' + name));
    // 切换时刷新数据
    if (name === 'scripts') Scripts.loadList();
    if (name === 'voices') Voices.loadList();
    if (name === 'task') Task.refreshUI();
    if (name === 'player') Player.loadList();
    if (name === 'settings') Settings.load();
  },

  /* ── API 封装 ── */
  async api(url, opts = {}) {
    const fetchOpts = { headers: { 'Content-Type': 'application/json' } };
    if (opts.method === 'POST' || opts.method === 'PUT') {
      fetchOpts.method = opts.method;
      fetchOpts.body = JSON.stringify(opts.body);
    } else if (opts.method === 'DELETE') {
      fetchOpts.method = 'DELETE';
    } else if (opts.body) {
      // GET with query params
      const params = new URLSearchParams(opts.body);
      url += '?' + params.toString();
    }
    const resp = await fetch(url, fetchOpts);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || err.message || '请求失败');
    }
    return resp.json();
  },

  async upload(url, formData) {
    const resp = await fetch(url, { method: 'POST', body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || '上传失败');
    }
    return resp.json();
  },

  /* ── Toast 通知 ── */
  toast(msg, type = 'info') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast ' + type + ' show';
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
  },

  /* ── 弹窗 ── */
  openModal(id) { document.getElementById(id).style.display = 'flex'; },
  closeModal(id) { document.getElementById(id).style.display = 'none'; },

  /* ── 工具函数 ── */
  formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  },
  formatDuration(sec) {
    if (!sec) return '--';
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return m + '分' + (s < 10 ? '0' : '') + s + '秒';
  },
  escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  },
};

/* ═══ 设置模块 ═══ */
const Settings = {
  init() {
    document.getElementById('btn-save-config').addEventListener('click', () => this.save());
  },
  load() {
    const c = App.config;
    document.getElementById('cfg-script-dirs').value = (c.script_dirs || []).join('\n');
    document.getElementById('cfg-output-dir').value = c.output_dir || '';
    document.getElementById('cfg-audio-dir').value = c.audio_dir || '';
    document.getElementById('cfg-tts-dir').value = c.tts_dir || '';
    document.getElementById('cfg-conda-python').value = c.conda_python || '';
    document.getElementById('cfg-model-dir').value = c.model_dir || '';
    document.getElementById('cfg-repo-dir').value = c.repo_dir || '';
    document.getElementById('cfg-worker-script').value = c.worker_script || '';
  },
  async save() {
    const dirs = document.getElementById('cfg-script-dirs').value.split('\n').map(s => s.trim()).filter(Boolean);
    const data = {
      script_dirs: dirs,
      output_dir: document.getElementById('cfg-output-dir').value.trim(),
      audio_dir: document.getElementById('cfg-audio-dir').value.trim(),
      tts_dir: document.getElementById('cfg-tts-dir').value.trim(),
      conda_python: document.getElementById('cfg-conda-python').value.trim(),
      model_dir: document.getElementById('cfg-model-dir').value.trim(),
      repo_dir: document.getElementById('cfg-repo-dir').value.trim(),
      worker_script: document.getElementById('cfg-worker-script').value.trim(),
    };
    try {
      await App.api('/api/config', { method: 'POST', body: data });
      App.config = { ...App.config, ...data };
      App.toast('配置已保存', 'success');
    } catch (e) {
      App.toast('保存失败: ' + e.message, 'error');
    }
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
