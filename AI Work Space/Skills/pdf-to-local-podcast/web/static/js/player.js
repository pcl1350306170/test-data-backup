/* ═══ 成品管理模块 ═══ */
const Player = {
  podcasts: [],
  _remergeSSE: null,

  init() {
    document.getElementById('btn-refresh-podcasts').addEventListener('click', () => this.loadList());
    document.getElementById('btn-clean-audio').addEventListener('click', () => this.cleanAudio());
    // 重新合并按钮
    document.getElementById('btn-remerge').addEventListener('click', () => this.startRemerge());
    document.getElementById('btn-remerge-cancel').addEventListener('click', () => this.cancelRemerge());
    // BGM 音量滑条
    document.getElementById('remerge-bgm-volume').addEventListener('input', e => {
      document.getElementById('remerge-bgm-volume-val').textContent = e.target.value;
    });
    // BGM 选择切换时显示/隐藏音量
    document.getElementById('remerge-bgm').addEventListener('change', e => {
      document.getElementById('remerge-bgm-volume-group').style.display = e.target.value ? 'block' : 'none';
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
    // 同时刷新重新合并区域的下拉列表
    this.loadRemergeOptions();
  },

  render() {
    const el = document.getElementById('podcast-list');
    if (!this.podcasts.length) {
      el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-dim)">暂无成品播客</div>';
      return;
    }
    el.innerHTML = this.podcasts.map(p => `
      <div class="podcast-item">
        <div class="podcast-header">
          <span class="podcast-name">${App.escapeHtml(p.name)}</span>
          <span class="podcast-meta">${App.formatSize(p.size)} · ${p.modified}</span>
        </div>
        <audio controls preload="none" src="/api/audio/play?file=${encodeURIComponent(p.name)}"></audio>
        <div class="podcast-actions">
          <a class="btn btn-sm" href="/api/audio/download?file=${encodeURIComponent(p.name)}" download>💾 下载</a>
        </div>
      </div>
    `).join('');
  },

  async cleanAudio() {
    if (!confirm('确定清理所有中间产物（wav 文件）？\n此操作不可恢复。')) return;
    try {
      const res = await App.api('/api/audio/clean', { method: 'POST' });
      App.toast(`已清理 ${res.cleaned} 个文件`, 'success');
      this.loadRemergeOptions();
    } catch (e) {
      App.toast('清理失败: ' + e.message, 'error');
    }
  },

  /* ── 重新合并功能 ── */

  async loadRemergeOptions() {
    // 加载音频任务目录
    try {
      const data = await App.api('/api/audio/tasks');
      const sel = document.getElementById('remerge-task');
      const cur = sel.value;
      sel.innerHTML = '<option value="">-- 请选择 --</option>' +
        data.tasks.map(t =>
          `<option value="${App.escapeHtml(t.name)}">${App.escapeHtml(t.name)} (${t.blocks} 块)</option>`
        ).join('');
      if (cur && sel.querySelector(`option[value="${CSS.escape(cur)}"]`)) sel.value = cur;
    } catch (e) { /* ignore */ }
    // 加载 BGM 列表
    try {
      const data = await App.api('/api/bgm/list');
      const sel = document.getElementById('remerge-bgm');
      const cur = sel.value;
      sel.innerHTML = '<option value="">-- 无 BGM --</option>' +
        data.bgms.map(b =>
          `<option value="${App.escapeHtml(b.path)}">${App.escapeHtml(b.name)}</option>`
        ).join('');
      // 恢复上次选择
      const saved = App.config.bgm_path || '';
      if (cur && sel.querySelector(`option[value="${CSS.escape(cur)}"]`)) {
        sel.value = cur;
      } else if (saved && sel.querySelector(`option[value="${CSS.escape(saved)}"]`)) {
        sel.value = saved;
      }
      const vol = App.config.bgm_volume;
      if (vol !== undefined && vol !== null) {
        document.getElementById('remerge-bgm-volume').value = vol;
        document.getElementById('remerge-bgm-volume-val').textContent = vol;
      }
      document.getElementById('remerge-bgm-volume-group').style.display = sel.value ? 'block' : 'none';
    } catch (e) { /* ignore */ }
  },

  async startRemerge() {
    const audioTask = document.getElementById('remerge-task').value;
    if (!audioTask) { App.toast('请先选择音频任务目录', 'info'); return; }

    const bgmPath = document.getElementById('remerge-bgm').value || null;
    const bgmVolume = parseInt(document.getElementById('remerge-bgm-volume').value) || 30;
    const lufs = parseFloat(document.getElementById('remerge-lufs').value) || -16;
    const gapMs = parseInt(document.getElementById('remerge-gap-ms').value) || 400;
    const outputName = document.getElementById('remerge-output-name').value.trim();

    try {
      await App.api('/api/task/remerge', {
        method: 'POST',
        body: { audio_task: audioTask, bgm_path: bgmPath, bgm_volume: bgmVolume, lufs, gap_ms: gapMs, output_name: outputName },
      });
      App.toast('合并已启动', 'success');
      document.getElementById('btn-remerge').disabled = true;
      document.getElementById('btn-remerge-cancel').disabled = false;
      document.getElementById('remerge-progress').style.display = 'block';
      this._setRemergeText('正在合并...');
      this._connectRemergeSSE();
    } catch (e) {
      App.toast('启动失败: ' + e.message, 'error');
    }
  },

  async cancelRemerge() {
    try {
      await App.api('/api/task/cancel', { method: 'POST' });
      this._setRemergeText('正在停止...');
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
      this._setRemergeText(`合并中: ${event.message}`);
    } else if (event.type === 'status' && event.status === 'merging') {
      this._setRemergeText(event.message || '正在合并...');
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
    document.getElementById('btn-remerge').disabled = false;
    document.getElementById('btn-remerge-cancel').disabled = true;

    if (status === 'done') {
      this._setRemergeText(`✅ 合并完成！${event.output || ''} (${App.formatDuration(event.duration_sec)})`);
      App.toast('重新合并完成！', 'success');
      this.loadList();  // 刷新成品列表
    } else if (status === 'cancelled') {
      this._setRemergeText('⏹ 已取消');
      App.toast('合并已取消', 'info');
    } else {
      this._setRemergeText('❌ ' + (event.message || '合并失败'));
      App.toast(event.message || '合并失败', 'error');
    }
  },

  _setRemergeText(msg) {
    const el = document.getElementById('remerge-progress-text');
    if (el) el.textContent = msg;
  },
};
