/* ═══ 成品管理模块 ═══ */
const Player = {
  podcasts: [],
  _expandedAudio: null,  // 当前展开 audio 的 podcast name
  _remergeSSE: null,
  _modalTask: "",        // modal 当前关联的音频任务目录名

  init() {
    document.getElementById('btn-refresh-podcasts').addEventListener('click', () => this.loadList());
    document.getElementById('btn-clean-audio').addEventListener('click', () => this.cleanAudio());
    // Modal 事件
    document.getElementById('btn-modal-close').addEventListener('click', () => this._closeModal());
    document.getElementById('remerge-modal').addEventListener('click', (e) => {
      if (e.target === e.currentTarget) this._closeModal();
    });
    document.getElementById('btn-modal-remerge').addEventListener('click', () => this._startRemerge());
    document.getElementById('btn-modal-remerge-cancel').addEventListener('click', () => this._cancelRemerge());
    document.getElementById('modal-remerge-bgm-volume').addEventListener('input', e => {
      document.getElementById('modal-bgm-volume-val').textContent = e.target.value;
    });
    document.getElementById('modal-remerge-bgm').addEventListener('change', e => {
      document.getElementById('modal-bgm-volume-group').style.display = e.target.value ? 'block' : 'none';
    });
  },

  async loadList() {
    try {
      const data = await App.api('/api/audio/podcast');
      this.podcasts = data.podcasts;
      this.render();
    } catch (e) {
      App.toast('加载成品列表失败: ' + e.message, 'error');
    }
  },

  render() {
    const el = document.getElementById('podcast-list');
    if (!this.podcasts.length) {
      el.innerHTML = '<div class="podcast-empty">暂无成品播客</div>';
      return;
    }
    el.innerHTML = this.podcasts.map(p => {
      const baseName = p.name.replace(/\.mp3$/i, '');
      const isExpanded = this._expandedAudio === p.name;
      return `
      <div class="podcast-row" data-name="${App.escapeHtml(p.name)}">
        <div class="podcast-row-main">
          <button class="btn-play-sm" data-file="${App.escapeHtml(p.name)}" title="播放/暂停">
            ${isExpanded ? '⏸' : '▶'}
          </button>
          <div class="podcast-row-info">
            <span class="podcast-row-name">${App.escapeHtml(baseName)}</span>
            <span class="podcast-row-meta">${App.formatSize(p.size)} · ${p.modified}</span>
          </div>
          <div class="podcast-row-actions">
            <button class="btn-icon remerge-btn" data-task="${App.escapeHtml(baseName)}" title="更换BGM重新合并">🔄 换BGM</button>
            <a class="btn-icon" href="/api/audio/download?file=${encodeURIComponent(p.name)}" download title="下载">💾</a>
          </div>
        </div>
        ${isExpanded ? `<div class="podcast-row-audio"><audio controls autoplay preload="auto" src="/api/audio/play?file=${encodeURIComponent(p.name)}"></audio></div>` : ''}
      </div>`;
    }).join('');

    // 绑定事件
    el.querySelectorAll('.btn-play-sm').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const name = e.currentTarget.dataset.file;
        this._toggleAudio(name);
      });
    });
    el.querySelectorAll('.remerge-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const task = e.currentTarget.dataset.task;
        this._openModal(task);
      });
    });
    // 自动聚焦展开的 audio
    if (this._expandedAudio) {
      const audio = el.querySelector('.podcast-row-audio audio');
      if (audio) audio.play().catch(() => {});
    }
  },

  _toggleAudio(name) {
    if (this._expandedAudio === name) {
      this._expandedAudio = null;
    } else {
      this._expandedAudio = name;
    }
    this.render();
  },

  async cleanAudio() {
    if (!confirm('确定清理所有中间产物（wav 文件）？\n此操作不可恢复。')) return;
    try {
      const res = await App.api('/api/audio/clean', { method: 'POST' });
      App.toast(`已清理 ${res.cleaned} 个文件`, 'success');
    } catch (e) {
      App.toast('清理失败: ' + e.message, 'error');
    }
  },

  /* ── Modal 重新合并 ── */

  _openModal(taskName) {
    this._modalTask = taskName;
    document.getElementById('modal-audio-task').textContent = taskName;
    document.getElementById('remerge-modal').style.display = 'flex';
    document.getElementById('modal-remerge-progress').style.display = 'none';
    document.getElementById('btn-modal-remerge').disabled = false;
    document.getElementById('btn-modal-remerge-cancel').disabled = true;
    // 加载 BGM 列表
    this._loadModalBgm();
  },

  _closeModal() {
    document.getElementById('remerge-modal').style.display = 'none';
    if (this._remergeSSE) { this._remergeSSE.close(); this._remergeSSE = null; }
  },

  async _loadModalBgm() {
    try {
      const data = await App.api('/api/bgm/list');
      const sel = document.getElementById('modal-remerge-bgm');
      sel.innerHTML = '<option value="">-- 无 BGM --</option>' +
        data.bgms.map(b =>
          `<option value="${App.escapeHtml(b.path)}">${App.escapeHtml(b.name)}</option>`
        ).join('');
      // 恢复上次配置
      const saved = App.config.bgm_path || '';
      if (saved && sel.querySelector(`option[value="${CSS.escape(saved)}"]`)) {
        sel.value = saved;
      }
      const vol = App.config.bgm_volume;
      if (vol !== undefined && vol !== null) {
        document.getElementById('modal-remerge-bgm-volume').value = vol;
        document.getElementById('modal-bgm-volume-val').textContent = vol;
      }
      document.getElementById('modal-bgm-volume-group').style.display = sel.value ? 'block' : 'none';
    } catch (e) { /* ignore */ }
  },

  async _startRemerge() {
    const audioTask = this._modalTask;
    if (!audioTask) { App.toast('未关联音频任务', 'info'); return; }

    const bgmPath = document.getElementById('modal-remerge-bgm').value || null;
    const bgmVolume = parseInt(document.getElementById('modal-remerge-bgm-volume').value) || 30;
    const lufs = parseFloat(document.getElementById('modal-remerge-lufs').value) || -16;
    const gapMs = parseInt(document.getElementById('modal-remerge-gap-ms').value) || 400;

    try {
      await App.api('/api/task/remerge', {
        method: 'POST',
        body: { audio_task: audioTask, bgm_path: bgmPath, bgm_volume: bgmVolume, lufs, gap_ms: gapMs, output_name: '' },
      });
      App.toast('合并已启动', 'success');
      document.getElementById('btn-modal-remerge').disabled = true;
      document.getElementById('btn-modal-remerge-cancel').disabled = false;
      document.getElementById('modal-remerge-progress').style.display = 'block';
      this._setModalText('正在合并...');
      this._connectRemergeSSE();
    } catch (e) {
      App.toast('启动失败: ' + e.message, 'error');
    }
  },

  async _cancelRemerge() {
    try {
      await App.api('/api/task/cancel', { method: 'POST' });
      this._setModalText('正在停止...');
    } catch (e) {
      App.toast('停止失败: ' + e.message, 'error');
    }
  },

  _connectRemergeSSE() {
    if (this._remergeSSE) this._remergeSSE.close();
    this._remergeSSE = new EventSource('/api/task/progress');
    this._remergeSSE.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        this._handleRemergeEvent(event);
      } catch (err) { /* ignore */ }
    };
    this._remergeSSE.onerror = () => { /* 自动重连 */ };
  },

  _handleRemergeEvent(event) {
    if (event.type === 'merge_progress') {
      this._setModalText(`合并中: ${event.message}`);
    } else if (event.type === 'status' && event.status === 'merging') {
      this._setModalText(event.message || '正在合并...');
    } else if (event.type === 'complete') {
      this._onRemergeDone('done', event);
    } else if (event.type === 'error') {
      this._onRemergeDone('failed', event);
    } else if (event.type === 'cancelled') {
      this._onRemergeDone('cancelled', event);
    }
  },

  _onRemergeDone(status, event) {
    if (this._remergeSSE) { this._remergeSSE.close(); this._remergeSSE = null; }
    document.getElementById('btn-modal-remerge').disabled = false;
    document.getElementById('btn-modal-remerge-cancel').disabled = true;

    if (status === 'done') {
      this._setModalText(`✅ 合并完成！${event.output || ''} (${App.formatDuration(event.duration_sec)})`);
      App.toast('重新合并完成！', 'success');
      this.loadList();
      setTimeout(() => this._closeModal(), 2000);
    } else if (status === 'cancelled') {
      this._setModalText('⏹ 已取消');
      App.toast('合并已取消', 'info');
    } else {
      this._setModalText('❌ ' + (event.message || '合并失败'));
      App.toast(event.message || '合并失败', 'error');
    }
  },

  _setModalText(msg) {
    const el = document.getElementById('modal-remerge-text');
    if (el) el.textContent = msg;
  },
};
