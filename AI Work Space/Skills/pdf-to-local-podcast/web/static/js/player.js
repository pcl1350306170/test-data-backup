/* ═══ 成品管理模块 ═══ */
const Player = {
  podcasts: [],

  init() {
    document.getElementById('btn-refresh-podcasts').addEventListener('click', () => this.loadList());
    document.getElementById('btn-clean-audio').addEventListener('click', () => this.cleanAudio());
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
    } catch (e) {
      App.toast('清理失败: ' + e.message, 'error');
    }
  },
};
