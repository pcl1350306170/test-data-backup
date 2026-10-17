/* ═══ 脚本管理模块 ═══ */
const Scripts = {
  currentPath: null,
  scripts: [],

  init() {
    document.getElementById('btn-new-script').addEventListener('click', () => this.newScript());
    document.getElementById('btn-upload-script').addEventListener('click', () =>
      document.getElementById('input-upload-script').click());
    document.getElementById('input-upload-script').addEventListener('change', e => this.upload(e));
    document.getElementById('btn-delete-script').addEventListener('click', () => this.deleteScript());
    document.getElementById('btn-parse-script').addEventListener('click', () => this.parseScript());
    document.getElementById('btn-send-task').addEventListener('click', () => this.sendToTask());
    // 事件委托：点击脚本列表项
    document.getElementById('script-list').addEventListener('click', (e) => {
      const item = e.target.closest('.file-item');
      if (item) this.select(item.dataset.path);
    });
  },

  async loadList() {
    try {
      const data = await App.api('/api/scripts');
      this.scripts = data.scripts;
      this.renderList();
    } catch (e) {
      App.toast('加载脚本列表失败: ' + e.message, 'error');
    }
  },

  renderList() {
    const el = document.getElementById('script-list');
    if (!this.scripts.length) {
      el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim)">暂无脚本文件</div>';
      return;
    }
    el.innerHTML = '<ul class="file-list">' + this.scripts.map(s => `
      <li class="file-item ${s.path === this.currentPath ? 'active' : ''}"
          data-path="${App.escapeHtml(s.path)}">
        <div class="file-item-name">${App.escapeHtml(s.name)}</div>
        <div class="file-item-meta">${App.formatSize(s.size)} · ${s.modified}</div>
      </li>
    `).join('') + '</ul>';
  },

  async select(path) {
    this.currentPath = path;
    this.renderList();
    try {
      const data = await App.api('/api/scripts/content', { body: { path } });
      document.getElementById('script-editor').value = data.content;
      document.getElementById('parse-result').style.display = 'none';
    } catch (e) {
      App.toast('加载脚本内容失败: ' + e.message, 'error');
    }
  },

  async newScript() {
    const name = prompt('输入脚本文件名（.md）：');
    if (!name) return;
    const fname = name.endsWith('.md') ? name : name + '.md';
    try {
      const res = await App.api('/api/scripts', {
        method: 'POST',
        body: { name: fname, content: '# 新播客脚本\n\n书名：\n目标时长：30分钟\n---\n' },
      });
      await this.loadList();
      this.select(res.path);
      App.toast('脚本已创建', 'success');
    } catch (e) {
      App.toast('创建失败: ' + e.message, 'error');
    }
  },

  async upload(input) {
    const file = input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      await App.upload('/api/scripts/upload', fd);
      input.value = '';
      await this.loadList();
      App.toast('上传成功', 'success');
    } catch (e) {
      App.toast('上传失败: ' + e.message, 'error');
    }
  },

  async deleteScript() {
    if (!this.currentPath) { App.toast('请先选择脚本', 'info'); return; }
    if (!confirm('确定删除此脚本？')) return;
    try {
      await App.api('/api/scripts/delete', { method: 'POST', body: { path: this.currentPath } });
      this.currentPath = null;
      document.getElementById('script-editor').value = '';
      await this.loadList();
      App.toast('已删除', 'success');
    } catch (e) {
      App.toast('删除失败: ' + e.message, 'error');
    }
  },

  async parseScript() {
    if (!this.currentPath) { App.toast('请先选择脚本', 'info'); return; }
    // 先保存当前编辑内容
    const content = document.getElementById('script-editor').value;
    try {
      await App.api('/api/scripts', { method: 'POST', body: { path: this.currentPath, content } });
    } catch (e) { /* 保存失败也继续尝试解析 */ }

    const box = document.getElementById('parse-result');
    box.style.display = 'block';
    box.innerHTML = '解析中...';
    try {
      const res = await App.api('/api/scripts/parse', { method: 'POST', body: { path: this.currentPath } });
      if (!res.ok) { box.innerHTML = '❌ ' + App.escapeHtml(res.error); return; }
      box.innerHTML = `
        <strong>${App.escapeHtml(res.book)}</strong><br>
        📝 总字数：${res.total_chars} 块数：${res.total_blocks}<br>
        ⏱️ 预估时长：${res.estimated_min} 分钟（${res.estimated_sec} 秒）<br>
        🎤 使用音色：${res.voices_used.join('、') || '无'}
        ${res.warnings.length ? '<br>⚠️ ' + res.warnings.length + ' 条警告' : ''}
      `;
    } catch (e) {
      box.innerHTML = '❌ 解析失败: ' + App.escapeHtml(e.message);
    }
  },

  async sendToTask() {
    if (!this.currentPath) { App.toast('请先选择脚本', 'info'); return; }
    // 先保存
    const content = document.getElementById('script-editor').value;
    try {
      await App.api('/api/scripts', { method: 'POST', body: { path: this.currentPath, content } });
    } catch (e) { /* ignore */ }
    // 跳转到任务 Tab 并加入脚本队列
    App.switchTab('task');
    Task.setScript(this.currentPath);
  },
};
