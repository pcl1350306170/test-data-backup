/* ═══ 任务控制模块 ═══ */
const Task = {
  eventSource: null,
  blockStates: {},
  totalBlocks: 0,
  queue: [],           // 待执行脚本队列 [{path, name}]
  _lastTotalJobs: 1,
  _lastJobIndex: 0,

  init() {
    document.getElementById('btn-start-task').addEventListener('click', () => this.start());
    document.getElementById('btn-cancel-task').addEventListener('click', () => this.cancel());
    document.getElementById('btn-pause-task').addEventListener('click', () => this.pause());
    document.getElementById('btn-resume-task').addEventListener('click', () => this.resume());
    document.getElementById('btn-retry-task').addEventListener('click', () => this.retry());
    document.getElementById('btn-add-to-queue').addEventListener('click', () => this.addToQueue());
    document.getElementById('btn-clear-queue').addEventListener('click', () => this.clearQueue());
    document.getElementById('script-queue').addEventListener('click', e => {
      const btn = e.target.closest('button[data-act]');
      if (!btn) return;
      const i = parseInt(btn.dataset.i);
      if (btn.dataset.act === 'up' && i > 0) {
        [this.queue[i - 1], this.queue[i]] = [this.queue[i], this.queue[i - 1]];
      } else if (btn.dataset.act === 'down' && i < this.queue.length - 1) {
        [this.queue[i + 1], this.queue[i]] = [this.queue[i], this.queue[i + 1]];
      } else if (btn.dataset.act === 'remove') {
        this.queue.splice(i, 1);
      }
      this.renderQueue();
    });
    document.getElementById('btn-upload-bgm').addEventListener('click', () =>
      document.getElementById('input-upload-bgm').click());
    document.getElementById('input-upload-bgm').addEventListener('change', e => this.uploadBgm(e));
    document.getElementById('task-bgm-volume').addEventListener('input', e => {
      document.getElementById('bgm-volume-val').textContent = e.target.value;
      this.saveBgmConfig();
    });
    document.getElementById('task-bgm').addEventListener('change', e => {
      document.getElementById('bgm-volume-group').style.display = e.target.value ? 'block' : 'none';
      this.saveBgmConfig();
    });
    // 检查是否有正在运行的任务
    this.checkStatus();
  },

  async refreshUI() {
    try {
      const saved = JSON.parse(localStorage.getItem('podcast_script_queue') || '[]');
      if (Array.isArray(saved)) this.queue = saved.filter(q => q && q.path);
    } catch (e) { /* ignore */ }
    await this.loadScriptOptions();
    this.renderQueue();
    await this.loadBgmOptions();
    await this.checkStatus();
  },

  async loadScriptOptions() {
    try {
      const data = await App.api('/api/scripts');
      const sel = document.getElementById('task-script-available');
      const cur = sel.value;
      sel.innerHTML = '<option value="">-- 请选择脚本 --</option>' +
        data.scripts.map(s =>
          `<option value="${App.escapeHtml(s.path)}">${App.escapeHtml(s.name)}</option>`
        ).join('');
      if (cur) sel.value = cur;
    } catch (e) { /* ignore */ }
  },

  /* ── 脚本队列（存 localStorage，换页不丢） ── */
  addToQueue() {
    const sel = document.getElementById('task-script-available');
    const path = sel.value;
    if (!path) { App.toast('请先选择脚本', 'info'); return; }
    if (this.queue.some(q => q.path === path)) { App.toast('该脚本已在队列中', 'info'); return; }
    const name = sel.options[sel.selectedIndex].text;
    this.queue.push({ path, name });
    this.renderQueue();
  },

  enqueue(path, name) {
    if (!this.queue.some(q => q.path === path)) {
      this.queue.push({ path, name: name || path.split(/[\\/]/).pop() });
      this.renderQueue();
    }
  },

  clearQueue() {
    this.queue = [];
    this.renderQueue();
  },

  saveQueue() {
    localStorage.setItem('podcast_script_queue', JSON.stringify(this.queue));
  },

  renderQueue() {
    this.saveQueue();
    const el = document.getElementById('script-queue');
    el.innerHTML = this.queue.map((q, i) => `
      <div class="queue-item">
        <span class="queue-idx">${i + 1}</span>
        <span class="queue-name" title="${App.escapeHtml(q.path)}">${App.escapeHtml(q.name)}</span>
        <span class="queue-actions">
          <button data-act="up" data-i="${i}" title="上移">▲</button>
          <button data-act="down" data-i="${i}" title="下移">▼</button>
          <button data-act="remove" data-i="${i}" title="移除">✕</button>
        </span>
      </div>`).join('');
    const hint = document.getElementById('queue-hint');
    if (this.queue.length > 1) {
      hint.style.display = 'block';
      hint.textContent = `共 ${this.queue.length} 个脚本，将按顺序逐个生成（每个完整生成并合并后再开始下一个）`;
    } else {
      hint.style.display = 'none';
    }
    document.getElementById('task-output-name').disabled = this.queue.length > 1;
    if (this.queue.length > 1) document.getElementById('task-output-name').value = '';
  },

  async loadBgmOptions() {
    try {
      const data = await App.api('/api/bgm/list');
      const sel = document.getElementById('task-bgm');
      const cur = sel.value;
      sel.innerHTML = '<option value="">-- 无 BGM --</option>' +
        data.bgms.map(b =>
          `<option value="${App.escapeHtml(b.path)}">${App.escapeHtml(b.name)}</option>`
        ).join('');
      // 恢复上次选择的 BGM（存在后端配置，换浏览器也生效）
      const saved = App.config.bgm_path || '';
      if (cur && sel.querySelector(`option[value="${CSS.escape(cur)}"]`)) {
        sel.value = cur;
      } else if (saved && sel.querySelector(`option[value="${CSS.escape(saved)}"]`)) {
        sel.value = saved;
      } else {
        App.config.bgm_path = '';
        if (saved) this.saveBgmConfig();  // 记录的文件已不在，同步清理后端
      }
      const vol = App.config.bgm_volume;
      if (vol !== undefined && vol !== null) {
        document.getElementById('task-bgm-volume').value = vol;
        document.getElementById('bgm-volume-val').textContent = vol;
      }
      document.getElementById('bgm-volume-group').style.display = sel.value ? 'block' : 'none';
    } catch (e) { /* ignore */ }
  },

  /* 保存 BGM 选择到后端配置（防抖，避免拖动滑条时频繁请求） */
  saveBgmConfig() {
    clearTimeout(this._bgmSaveTimer);
    this._bgmSaveTimer = setTimeout(async () => {
      const data = {
        bgm_path: document.getElementById('task-bgm').value,
        bgm_volume: parseInt(document.getElementById('task-bgm-volume').value) || 0,
      };
      App.config = { ...App.config, ...data };
      try { await App.api('/api/config', { method: 'POST', body: data }); }
      catch (e) { /* ignore */ }
    }, 500);
  },

  setScript(path) {
    this.enqueue(path);
  },

  async uploadBgm(input) {
    const file = input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await App.upload('/api/bgm/upload', fd);
      input.value = '';
      await this.loadBgmOptions();
      // 上传后直接选中并固定为新默认
      const sel = document.getElementById('task-bgm');
      const opt = [...sel.options].find(o => o.value === res.path);
      if (opt) {
        sel.value = res.path;
        document.getElementById('bgm-volume-group').style.display = 'block';
        this.saveBgmConfig();
      }
      App.toast('BGM 上传成功', 'success');
    } catch (e) {
      App.toast('上传失败: ' + e.message, 'error');
    }
  },

  async checkStatus() {
    try {
      const status = await App.api('/api/task/status');
      this._lastTotalJobs = status.total_jobs || 1;
      this._lastJobIndex = status.job_index || 0;
      if (status.status !== 'idle') {
        this.updateUI(status);
        if (['generating', 'merging', 'parsing', 'cancelling'].includes(status.status)
            || (status.status === 'paused' && status.pending_scripts && status.pending_scripts.length)) {
          this.connectSSE();
        }
      }
    } catch (e) { /* ignore */ }
  },

  async start() {
    const paths = this.queue.map(q => q.path);
    if (!paths.length) { App.toast('请先加入至少一个脚本', 'info'); return; }
    const outputName = paths.length === 1
      ? document.getElementById('task-output-name').value.trim() : '';
    const bgmPath = document.getElementById('task-bgm').value || null;
    const bgmVolume = parseInt(document.getElementById('task-bgm-volume').value) || 30;
    const lufs = parseFloat(document.getElementById('task-lufs').value) || -16;
    const gapMs = parseInt(document.getElementById('task-gap-ms').value) || 400;

    try {
      const res = await App.api('/api/task/start', {
        method: 'POST',
        body: { script_paths: paths, output_name: outputName, bgm_path: bgmPath, bgm_volume: bgmVolume, lufs, gap_ms: gapMs },
      });
      App.toast(paths.length > 1
        ? `已提交 ${paths.length} 个任务，按顺序执行` : '任务已启动', 'success');
      this.queue = [];
      this.renderQueue();
      this.blockStates = {};
      this._lastTotalJobs = res.total_jobs || 1;
      this._lastJobIndex = 0;
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
      App.toast(this._lastTotalJobs > this._lastJobIndex + 1
        ? '正在停止，剩余队列将清空...' : '正在停止...', 'info');
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
        // 状态变化时刷新执行队列显示
        this._refreshExecQueue();
        break;

      case 'parsed':
        this.totalBlocks = event.total_blocks;
        this.blockStates = {};
        this.renderBlockList(event.total_blocks);
        if (event.queue) {
          this._lastTotalJobs = event.queue.total;
          this._lastJobIndex = event.queue.job - 1;
          this.updateStatusText(`[${event.queue.job}/${event.queue.total}] ${event.queue.script} 解析完成：${event.total_blocks} 块，预估 ${Math.round(event.estimated_sec / 60)} 分钟`);
        } else {
          this.updateStatusText(`解析完成：${event.total_blocks} 块，${event.total_chars} 字，预估 ${Math.round(event.estimated_sec / 60)} 分钟`);
        }
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
        // 批量模式中非末个任务：保持连接，提示后等下一个脚本开始
        if (event.queue) {
          this._lastTotalJobs = event.queue.total;
          this._lastJobIndex = event.queue.job;
          App.toast(`✅ 第 ${event.queue.job}/${event.queue.total} 个完成: ${event.output}，继续下一个...`, 'success');
          this.updateStatusText(`✅ ${event.queue.job}/${event.queue.total} 完成，即将开始下一个脚本`);
          break;
        }
        this.onTaskDone('done', event);
        break;

      case 'error':
        if (event.queue && event.more) {
          App.toast('❌ ' + event.message + '（已跳过，继续下一个）', 'error');
          this.updateStatusText('❌ ' + event.message + '，队列将继续执行剩余任务');
          document.getElementById('btn-start-task').disabled = true;  // 引擎忙，整批跑完前不可启动新任务
          break;
        }
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
      this.updateStatusText(`✅ 完成！${event.message || ('成品: ' + event.output + '，时长: ' + App.formatDuration(event.duration_sec))}`);
      if (event.warning) {
        App.toast('⚠️ ' + event.warning, 'info');
      } else if (event.batch) {
        App.toast(`全部 ${this._lastTotalJobs} 个任务完成！`, 'success');
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
    const hasPending = status.pending_scripts && status.pending_scripts.length > 0;
    const running = ['generating', 'merging', 'parsing'].includes(status.status) || hasPending;
    const isPaused = status.status === 'paused';

    document.getElementById('btn-start-task').disabled = running || isPaused;
    document.getElementById('btn-cancel-task').disabled = !(running || isPaused || status.status === 'cancelling');
    document.getElementById('btn-pause-task').disabled = !running;
    document.getElementById('btn-pause-task').style.display = (running || isPaused) ? 'inline-block' : 'none';
    document.getElementById('btn-resume-task').style.display = isPaused ? 'inline-block' : 'none';
    document.getElementById('btn-retry-task').style.display =
      status.failed_blocks && status.failed_blocks.length && !running && !isPaused && !hasPending ? 'inline-block' : 'none';

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

    // 执行队列状态显示
    this.renderExecQueue(status);

    // 多任务批次信息展示
    const qEl = document.getElementById('progress-eta');
    if (status.total_jobs > 1 && qEl) {
      const remain = hasPending ? `，剩余 ${status.pending_scripts.length} 个待执行` : '';
      qEl.textContent = `批次 ${Math.min(status.job_index + 1, status.total_jobs)}/${status.total_jobs}${remain}`;
    }

    if (status.status === 'done' && status.output_path) {
      this.updateStatusText(`✅ 上次完成: ${status.output_path.split(/[\\/]/).pop()}`);
    } else if (status.status === 'failed') {
      this.updateStatusText('❌ ' + (status.error_message || '失败'));
    }
  },

  async _refreshExecQueue() {
    try {
      const status = await App.api('/api/task/status');
      this.renderExecQueue(status);
    } catch (e) { /* ignore */ }
  },

  renderExecQueue(status) {
    const el = document.getElementById('exec-queue');
    const curEl = document.getElementById('exec-current');
    const pendEl = document.getElementById('exec-pending');
    const isBusy = ['parsing', 'generating', 'merging', 'paused', 'cancelling', 'validating'].includes(status.status);
    const isDone = ['done', 'failed', 'cancelled'].includes(status.status);

    if (!isBusy && !isDone) { el.style.display = 'none'; return; }
    el.style.display = 'block';

    // 当前任务
    const name = status.output_name || (status.script_path || '').split(/[\\/]/).pop().replace(/\.md$/i, '') || '';
    const statusMap = {
      parsing: '🔍 解析中', generating: '🎤 生成中', merging: '🔗 合并中',
      validating: '✅ 校验中', paused: '⏸ 已暂停', cancelling: '⏹ 停止中',
      done: '✅ 已完成', failed: '❌ 失败', cancelled: '⏹ 已取消',
    };
    const label = statusMap[status.status] || status.status;
    const jobIdx = Math.min((status.job_index || 0) + 1, status.total_jobs || 1);
    const total = status.total_jobs || 1;
    const batchPrefix = total > 1 ? `[${jobIdx}/${total}] ` : '';

    if (isBusy || isDone) {
      curEl.innerHTML = `<span class="exec-label">${batchPrefix}${label}</span> <span class="exec-name">${App.escapeHtml(name)}</span>`;
    } else {
      curEl.innerHTML = '';
    }

    // 排队任务
    const pendings = status.pending_scripts || [];
    if (pendings.length && isBusy) {
      pendEl.innerHTML = `<div class="exec-pending-title">排队中 (${pendings.length})</div>` +
        pendings.map((s, i) => `<div class="exec-pending-item">${jobIdx + i + 1}. ${App.escapeHtml(s)}</div>`).join('');
    } else {
      pendEl.innerHTML = '';
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
