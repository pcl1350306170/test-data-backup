/* ═══ 任务控制模块 ═══ */
const Task = {
  eventSource: null,
  blockStates: {},
  totalBlocks: 0,

  init() {
    document.getElementById('btn-start-task').addEventListener('click', () => this.start());
    document.getElementById('btn-cancel-task').addEventListener('click', () => this.cancel());
    document.getElementById('btn-pause-task').addEventListener('click', () => this.pause());
    document.getElementById('btn-resume-task').addEventListener('click', () => this.resume());
    document.getElementById('btn-retry-task').addEventListener('click', () => this.retry());
    document.getElementById('btn-upload-bgm').addEventListener('click', () =>
      document.getElementById('input-upload-bgm').click());
    document.getElementById('input-upload-bgm').addEventListener('change', e => this.uploadBgm(e));
    document.getElementById('task-bgm-volume').addEventListener('input', e => {
      document.getElementById('bgm-volume-val').textContent = e.target.value;
    });
    document.getElementById('task-bgm').addEventListener('change', e => {
      document.getElementById('bgm-volume-group').style.display = e.target.value ? 'block' : 'none';
    });
    // 检查是否有正在运行的任务
    this.checkStatus();
  },

  async refreshUI() {
    await this.loadScriptOptions();
    await this.loadBgmOptions();
    await this.checkStatus();
  },

  async loadScriptOptions() {
    try {
      const data = await App.api('/api/scripts');
      const sel = document.getElementById('task-script');
      const cur = sel.value;
      sel.innerHTML = '<option value="">-- 请选择脚本 --</option>' +
        data.scripts.map(s =>
          `<option value="${App.escapeHtml(s.path)}">${App.escapeHtml(s.name)}</option>`
        ).join('');
      if (cur) sel.value = cur;
    } catch (e) { /* ignore */ }
  },

  async loadBgmOptions() {
    try {
      const data = await App.api('/api/bgm/list');
      const sel = document.getElementById('task-bgm');
      sel.innerHTML = '<option value="">-- 无 BGM --</option>' +
        data.bgms.map(b =>
          `<option value="${App.escapeHtml(b.path)}">${App.escapeHtml(b.name)}</option>`
        ).join('');
    } catch (e) { /* ignore */ }
  },

  setScript(path) {
    const sel = document.getElementById('task-script');
    sel.value = path;
  },

  async uploadBgm(input) {
    const file = input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      await App.upload('/api/bgm/upload', fd);
      input.value = '';
      await this.loadBgmOptions();
      App.toast('BGM 上传成功', 'success');
    } catch (e) {
      App.toast('上传失败: ' + e.message, 'error');
    }
  },

  async checkStatus() {
    try {
      const status = await App.api('/api/task/status');
      if (status.status !== 'idle') {
        this.updateUI(status);
        if (['generating', 'merging', 'parsing'].includes(status.status)) {
          this.connectSSE();
        }
      }
    } catch (e) { /* ignore */ }
  },

  async start() {
    const scriptPath = document.getElementById('task-script').value;
    if (!scriptPath) { App.toast('请选择脚本', 'info'); return; }
    const outputName = document.getElementById('task-output-name').value.trim();
    const bgmPath = document.getElementById('task-bgm').value || null;
    const bgmVolume = parseInt(document.getElementById('task-bgm-volume').value) || 30;
    const lufs = parseFloat(document.getElementById('task-lufs').value) || -16;
    const gapMs = parseInt(document.getElementById('task-gap-ms').value) || 400;

    try {
      const res = await App.api('/api/task/start', {
        method: 'POST',
        body: { script_path: scriptPath, output_name: outputName, bgm_path: bgmPath, bgm_volume: bgmVolume, lufs, gap_ms: gapMs },
      });
      App.toast('任务已启动: ' + res.output_name, 'success');
      this.blockStates = {};
      this.connectSSE();
      document.getElementById('task-progress').style.display = 'block';
      document.getElementById('btn-start-task').disabled = true;
      document.getElementById('btn-cancel-task').disabled = false;
      document.getElementById('btn-pause-task').disabled = false;
      document.getElementById('btn-pause-task').style.display = 'inline-block';
      document.getElementById('btn-resume-task').style.display = 'none';
      document.getElementById('btn-retry-task').style.display = 'none';
    } catch (e) {
      App.toast('启动失败: ' + e.message, 'error');
    }
  },

  async cancel() {
    try {
      await App.api('/api/task/cancel', { method: 'POST' });
      App.toast('正在停止...', 'info');
    } catch (e) {
      App.toast('停止失败: ' + e.message, 'error');
    }
  },

  async pause() {
    try {
      await App.api('/api/task/pause', { method: 'POST' });
      App.toast('将在当前块完成后暂停', 'info');
      document.getElementById('btn-pause-task').disabled = true;
      document.getElementById('btn-resume-task').style.display = 'inline-block';
    } catch (e) {
      App.toast('暂停失败: ' + e.message, 'error');
    }
  },

  async resume() {
    try {
      await App.api('/api/task/resume', { method: 'POST' });
      App.toast('继续生成', 'success');
      document.getElementById('btn-pause-task').disabled = false;
      document.getElementById('btn-resume-task').style.display = 'none';
    } catch (e) {
      App.toast('继续失败: ' + e.message, 'error');
    }
  },

  async retry() {
    try {
      await App.api('/api/task/retry-failed', { method: 'POST' });
      App.toast('正在重试失败块...', 'info');
      this.connectSSE();
      document.getElementById('btn-start-task').disabled = true;
      document.getElementById('btn-cancel-task').disabled = false;
      document.getElementById('btn-pause-task').disabled = false;
      document.getElementById('btn-pause-task').style.display = 'inline-block';
      document.getElementById('btn-resume-task').style.display = 'none';
      document.getElementById('btn-retry-task').style.display = 'none';
    } catch (e) {
      App.toast('重试失败: ' + e.message, 'error');
    }
  },

  /* ── SSE 连接 ── */
  connectSSE() {
    if (this.eventSource) this.eventSource.close();
    this.eventSource = new EventSource('/api/task/progress');
    this.eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        this.handleEvent(event);
      } catch (err) { /* ignore parse errors */ }
    };
    this.eventSource.onerror = () => {
      // 连接断开时尝试重连（浏览器自动重连）
    };
  },

  handleEvent(event) {
    switch (event.type) {
      case 'status':
        this.updateStatusText(event.message || event.status);
        if (event.status === 'paused') {
          document.getElementById('btn-pause-task').disabled = true;
          document.getElementById('btn-resume-task').style.display = 'inline-block';
        }
        break;

      case 'parsed':
        this.totalBlocks = event.total_blocks;
        this.blockStates = {};
        this.renderBlockList(event.total_blocks);
        this.updateStatusText(`解析完成：${event.total_blocks} 块，${event.total_chars} 字，预估 ${Math.round(event.estimated_sec / 60)} 分钟`);
        break;

      case 'block_status':
        this.blockStates[event.idx] = event.status;
        this.updateBlockItem(event);
        if (event.status === 'generating') {
          const cb = document.getElementById('current-block');
          cb.style.display = 'block';
          cb.textContent = `🎤 [${event.voice}] ${event.text || ''}...`;
        }
        break;

      case 'progress':
        this.updateProgress(event);
        break;

      case 'merge_progress':
        this.updateStatusText(`合并中: ${event.message}`);
        break;

      case 'complete':
        this.onTaskDone('done', event);
        break;

      case 'error':
        this.onTaskDone('failed', event);
        if (event.failed_blocks && event.failed_blocks.length) {
          document.getElementById('btn-retry-task').style.display = 'inline-block';
        }
        break;

      case 'cancelled':
        this.onTaskDone('cancelled', event);
        break;

      case 'heartbeat':
        break;
    }
  },

  onTaskDone(status, event) {
    if (this.eventSource) { this.eventSource.close(); this.eventSource = null; }
    document.getElementById('btn-start-task').disabled = false;
    document.getElementById('btn-cancel-task').disabled = true;
    document.getElementById('btn-pause-task').disabled = true;
    document.getElementById('btn-pause-task').style.display = 'none';
    document.getElementById('btn-resume-task').style.display = 'none';
    document.getElementById('current-block').style.display = 'none';

    if (status === 'done') {
      this.updateStatusText(`✅ 完成！成品: ${event.output}，时长: ${App.formatDuration(event.duration_sec)}`);
      if (event.warning) {
        App.toast('⚠️ ' + event.warning, 'info');
      } else {
        App.toast('播客制作完成！', 'success');
      }
    } else if (status === 'cancelled') {
      this.updateStatusText('⏹ 任务已取消');
      App.toast('任务已取消', 'info');
    } else {
      this.updateStatusText('❌ ' + (event.message || '任务失败'));
      App.toast(event.message || '任务失败', 'error');
    }
  },

  /* ── UI 更新 ── */
  updateUI(status) {
    this.blockStates = status.block_states || {};
    this.totalBlocks = status.total_blocks;
    const running = ['generating', 'merging', 'parsing'].includes(status.status);
    const isPaused = status.status === 'paused';

    document.getElementById('btn-start-task').disabled = running || isPaused;
    document.getElementById('btn-cancel-task').disabled = !(running || isPaused);
    document.getElementById('btn-pause-task').disabled = !running;
    document.getElementById('btn-pause-task').style.display = (running || isPaused) ? 'inline-block' : 'none';
    document.getElementById('btn-resume-task').style.display = isPaused ? 'inline-block' : 'none';
    document.getElementById('btn-retry-task').style.display =
      status.failed_blocks && status.failed_blocks.length && !running && !isPaused ? 'inline-block' : 'none';

    if (status.total_blocks > 0) {
      document.getElementById('task-progress').style.display = 'block';
      this.renderBlockList(status.total_blocks);
      // 恢复块状态
      for (const [idx, s] of Object.entries(status.block_states)) {
        this.updateBlockItem({ idx: parseInt(idx), status: s });
      }
      // 更新进度
      const done = Object.values(status.block_states).filter(s => s === 'done' || s === 'skipped').length;
      this.updateProgress({ done, total: status.total_blocks, percent: Math.round(done / status.total_blocks * 100) });
    }

    if (status.status === 'done' && status.output_path) {
      this.updateStatusText(`✅ 上次完成: ${status.output_path.split(/[\\/]/).pop()}`);
    } else if (status.status === 'failed') {
      this.updateStatusText('❌ ' + (status.error_message || '失败'));
    }
  },

  updateStatusText(msg) {
    const el = document.getElementById('progress-text');
    if (el) el.textContent = msg;
  },

  updateProgress(data) {
    const bar = document.getElementById('progress-bar');
    const pct = document.getElementById('progress-percent');
    const info = document.getElementById('progress-text');
    const eta = document.getElementById('progress-eta');

    bar.style.width = data.percent + '%';
    pct.textContent = data.percent + '%';
    info.textContent = `${data.done}/${data.total}` + (data.failed ? ` （${data.failed} 失败）` : '');
    if (data.eta_sec > 0) {
      eta.textContent = '剩余约 ' + App.formatDuration(data.eta_sec);
    } else {
      eta.textContent = '';
    }
  },

  renderBlockList(total) {
    const el = document.getElementById('block-list');
    let html = '';
    for (let i = 1; i <= total; i++) {
      html += `<div class="block-item" id="block-${i}">
        <span class="block-idx">${i}</span>
        <span class="block-status-icon">⏳</span>
      </div>`;
    }
    el.innerHTML = html;
  },

  updateBlockItem(event) {
    const el = document.getElementById('block-' + event.idx);
    if (!el) return;
    el.className = 'block-item ' + (event.status || '');
    const icons = {
      pending: '⏳', generating: '🔄', done: '✅', skipped: '⏭️', failed: '❌',
    };
    el.querySelector('.block-status-icon').textContent = icons[event.status] || '⏳';
  },
};
