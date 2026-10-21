/* ═══ 音色管理模块 ═══ */
const Voices = {
  voices: [],

  init() {
    document.getElementById('btn-scan-voices').addEventListener('click', () => this.scan());
    document.getElementById('btn-add-voice').addEventListener('click', () => this.showAddDialog());
    document.getElementById('btn-confirm-add-voice').addEventListener('click', () => this.confirmAdd());
    // 事件委托：音色卡片删除按钮
    document.getElementById('voice-list').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-delete-voice]');
      if (btn) this.remove(btn.dataset.deleteVoice);
    });
  },

  async loadList() {
    try {
      const data = await App.api('/api/voices');
      this.voices = data.voices;
      this.render();
    } catch (e) {
      App.toast('加载音色列表失败: ' + e.message, 'error');
    }
  },

  render() {
    const el = document.getElementById('voice-list');
    if (!this.voices.length) {
      el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-dim)">暂无注册音色，点击"扫描 TTS 目录"或"手动注册"</div>';
      return;
    }
    el.innerHTML = this.voices.map(v => `
      <div class="voice-card">
        <div class="voice-card-header">
          <span class="voice-card-name">${App.escapeHtml(v.name)}</span>
          <span class="voice-card-type">${App.escapeHtml(v.type)}</span>
        </div>
        <div class="voice-card-file">🎵 ${App.escapeHtml(v.audio_file)}</div>
        <div class="voice-card-actions">
          <button class="btn btn-sm btn-danger" data-delete-voice="${App.escapeHtml(v.name)}">删除</button>
        </div>
      </div>
    `).join('');
  },

  async scan() {
    try {
      const data = await App.api('/api/voices/scan');
      const list = data.unregistered;
      const el = document.getElementById('scan-results');
      if (!list.length) {
        el.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">TTS 目录中所有音频均已注册</div>';
      } else {
        el.innerHTML = list.map(item => `
          <div class="scan-item">
            <span class="scan-item-name">${App.escapeHtml(item.filename)}</span>
            <span class="scan-item-type">${App.escapeHtml(item.inferred_type)}</span>
            <button class="btn btn-sm btn-primary"
              data-register-file="${App.escapeHtml(item.filename)}"
              data-register-type="${App.escapeHtml(item.inferred_type)}">
              注册
            </button>
          </div>
        `).join('');
        // 事件委托：扫描结果注册按钮
        el.addEventListener('click', (e) => {
          const btn = e.target.closest('[data-register-file]');
          if (btn) this.quickRegister(btn.dataset.registerFile, btn.dataset.registerType);
        }, { once: true });
      }
      App.openModal('scan-modal');
    } catch (e) {
      App.toast('扫描失败: ' + e.message, 'error');
    }
  },

  async quickRegister(filename, inferredType) {
    const name = prompt('音色名称：', filename.replace(/\.[^.]+$/, ''));
    if (!name) return;
    try {
      await App.api('/api/voices', {
        method: 'POST',
        body: { name, audio_file: filename, type: inferredType },
      });
      App.toast('已注册: ' + name, 'success');
      await this.loadList();
      // 刷新扫描结果
      this.scan();
    } catch (e) {
      App.toast('注册失败: ' + e.message, 'error');
    }
  },

  async showAddDialog() {
    // 加载可扫描的音频文件到下拉列表
    try {
      const data = await App.api('/api/voices/scan');
      const sel = document.getElementById('voice-audio-file');
      sel.innerHTML = '<option value="">-- 选择音频文件 --</option>' +
        data.unregistered.map(item =>
          `<option value="${App.escapeHtml(item.filename)}">${App.escapeHtml(item.filename)} (${App.escapeHtml(item.inferred_type)})</option>`
        ).join('');
    } catch (e) { /* ignore */ }
    document.getElementById('voice-name').value = '';
    document.getElementById('voice-prompt-text').value = '';
    document.getElementById('voice-type').value = '通用男声';
    App.openModal('voice-modal');
  },

  async confirmAdd() {
    const name = document.getElementById('voice-name').value.trim();
    const audioFile = document.getElementById('voice-audio-file').value;
    const type = document.getElementById('voice-type').value;
    const promptText = document.getElementById('voice-prompt-text').value.trim();
    if (!name) { App.toast('请输入音色名称', 'info'); return; }
    if (!audioFile) { App.toast('请选择参考音频', 'info'); return; }
    try {
      await App.api('/api/voices', {
        method: 'POST',
        body: { name, audio_file: audioFile, type, prompt_text: promptText || null },
      });
      App.closeModal('voice-modal');
      App.toast('已注册: ' + name, 'success');
      await this.loadList();
    } catch (e) {
      App.toast('注册失败: ' + e.message, 'error');
    }
  },

  async remove(name) {
    if (!confirm('确定删除音色「' + name + '」？')) return;
    try {
      await App.api('/api/voices/' + encodeURIComponent(name), { method: 'DELETE' });
      App.toast('已删除: ' + name, 'success');
      await this.loadList();
    } catch (e) {
      App.toast('删除失败: ' + e.message, 'error');
    }
  },
};

