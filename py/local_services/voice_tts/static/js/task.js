/* CosyVoice TTS Web — 任务控制 + SSE 进度 */
var Task = (function () {
  var eventSource = null;
  var currentTaskId = null;
  var currentTaskName = '';

  function $(id) { return document.getElementById(id); }

  // ── UI 状态切换 ──────────────────────────────────
  function setUIIdle() {
    $('btnStart').disabled = false;
    $('btnTest').disabled = false;
    App.hide('btnPause');
    App.hide('btnResume');
    App.hide('btnStop');
    App.hide('activeTaskBar');
  }

  function setUIRunning() {
    // 保持按钮可用，允许随时追加任务
    $('btnStart').disabled = false;
    $('btnTest').disabled = false;
    App.show('btnStop');
    App.show('btnPause');
    App.hide('btnResume');
    App.show('progressSection');
    App.show('logSection');
    showActiveBar('running');
  }

  function setUIPaused() {
    App.hide('btnPause');
    App.show('btnResume');
    App.show('btnStop');
    showActiveBar('paused');
  }

  function showActiveBar(status) {
    if (!currentTaskId) { App.hide('activeTaskBar'); return; }
    var labels = {
      running: '执行中', paused: '已暂停', stopping: '正在停止…',
      done: '已完成', error: '失败', cancelled: '已停止', interrupted: '待恢复',
    };
    $('atbName').textContent = currentTaskName + ' (' + currentTaskId + ')';
    $('atbStatus').textContent = labels[status] || status;
    App.show('activeTaskBar');
  }

  function updateProgress(current, total, percent) {
    $('progressBar').style.width = (percent || 0) + '%';
    $('progressText').textContent = current + '/' + total;
    $('progressPercent').textContent = (percent || 0) + '%';
  }

  function appendLog(msg) {
    var box = $('logBox');
    box.textContent += msg + '\n';
    box.scrollTop = box.scrollHeight;
  }

  function clearLog() {
    $('logBox').textContent = '';
  }

  // ── SSE 连接 ──────────────────────────────────────
  function connectSSE() {
    disconnectSSE();
    eventSource = new EventSource('/api/task/progress');
    eventSource.onmessage = function (e) {
      try { handleEvent(JSON.parse(e.data)); } catch (err) { }
    };
    eventSource.onerror = function () {
      if (eventSource && eventSource.readyState === EventSource.CLOSED) {
        checkStatus();
      }
    };
  }

  function disconnectSSE() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function handleEvent(event) {
    switch (event.type) {
      case 'started':
        if (event.task_id) currentTaskId = event.task_id;
        clearLog();
        setUIRunning();
        updateProgress(0, event.total, 0);
        if (event.resumed && event.resumed > 0) {
          appendLog('已跳过 ' + event.resumed + ' 段（此前完成）');
        }
        break;

      case 'queued':
        App.toast('任务已加入队列，当前队列共 ' + event.queue_size + ' 个任务');
        appendLog('[队列] 任务 ' + event.task_name + ' 已加入等待队列');
        loadQueue();
        break;

      case 'auto_start':
        currentTaskId = event.task_id || currentTaskId;
        currentTaskName = event.task_name || '';
        appendLog('[自动] 开始执行队列任务: ' + event.task_name);
        setUIRunning();
        updateProgress(0, event.total || 0, 0);
        loadQueue();
        App.loadTaskList();
        break;

      case 'queue_done':
        loadQueue();
        App.loadTaskList();
        break;

      case 'progress':
        updateProgress(event.current, event.total, event.percent);
        if (event.skipped) appendLog('[' + event.current + '/' + event.total + '] 已完成，跳过');
        break;

      case 'log':
        appendLog(event.message);
        break;

      case 'paused':
        setUIPaused();
        App.loadTaskList();
        break;

      case 'resumed':
        setUIRunning();
        break;

      case 'complete':
        updateProgress(event.total, event.total, 100);
        App.loadTaskList();
        if (event.queue_size > 0) {
          // 队列还有后续任务，不跳转结果页，等 auto_start 接管
          App.toast('本任务完成，队列还剩 ' + event.queue_size + ' 个任务待执行', 3000);
          loadQueue();
        } else {
          App.toast('生成完成！共 ' + event.files.length + ' 个文件', 3000);
          setTimeout(function () {
            document.querySelector('[data-tab="results"]').click();
          }, 500);
        }
        break;

      case 'cancelled':
        App.toast(event.queue_size > 0
          ? '任务已停止，继续执行队列中剩余 ' + event.queue_size + ' 个任务'
          : '任务已停止，成品与中间文件已清理');
        App.loadTaskList();
        App.loadAudioList();
        loadQueue();
        break;

      case 'error':
        App.toast('生成失败: ' + event.message, 4000);
        App.loadTaskList();
        if (event.queue_size >= 0) loadQueue();
        break;

      case 'segment_error':
        appendLog('[段 ' + event.index + ' 失败] ' + event.error);
        break;

      case 'heartbeat':
        break;
    }
  }

  // ── 任务操作 ──────────────────────────────────────
  function start() {
    var params = App.getParams();
    if (!params.text) { App.toast('请输入文本内容'); return; }

    // 自动保存当前合成参数（包括音色、风格、语速等）
    App.saveSynthConfig(params);

    currentTaskName = params.task_name || (params.text.slice(0, 20) + (params.text.length > 20 ? '…' : ''));

    clearLog();
    App.show('logSection');
    App.show('progressSection');
    updateProgress(0, 0, 0);

    connectSSE();

    fetch('/api/task/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || '请求失败');
        return d;
      });
    }).then(function (data) {
      currentTaskId = data.task_id;
      if (data.queued) {
        App.toast('任务已加入队列，等待执行');
        loadQueue();
      } else {
        setUIRunning();
        updateProgress(0, data.total, 0);
        App.toast('任务已启动，共 ' + data.total + ' 段');
      }
      App.loadTaskList();
      // 清空任务名输入，避免下一次复用
      var tni = $('taskNameInput'); if (tni) tni.value = '';
    }).catch(function (e) {
      App.toast(e.message, 3000);
      setUIIdle();
      disconnectSSE();
    });
  }

  function stop() {
    fetch('/api/task/stop', { method: 'POST' }).catch(function () { });
  }

  function pause() {
    fetch('/api/task/pause', { method: 'POST' }).catch(function () { });
  }

  function resume() {
    fetch('/api/task/resume', { method: 'POST' }).catch(function () { });
  }

  // 从任务列表点了"继续任务"后，由 App 调过来重建 SSE
  function onResumedFromList() {
    clearLog();
    App.show('logSection');
    App.show('progressSection');
    connectSSE();
    // 拉一次 status 恢复基本 UI
    fetch('/api/task/status').then(function (r) { return r.json(); }).then(function (data) {
      if (data && data.task_id) {
        currentTaskId = data.task_id;
        currentTaskName = data.task_name || '';
        updateProgress(data.completed, data.total, data.progress);
        if (data.logs && data.logs.length) $('logBox').textContent = data.logs.join('\n');
        if (data.status === 'paused') setUIPaused(); else setUIRunning();
      }
      App.loadTaskList();
    }).catch(function () { });
  }

  // 从任务列表点击"查看当前进度"
  function switchToCurrent() {
    document.querySelector('[data-tab="synthesize"]').click();
    if (!eventSource) connectSSE();
  }

  function test() {
    var params = App.getParams();
    $('btnTest').disabled = true;
    $('btnTest').textContent = '测试中…';
    App.toast('正在生成测试音频…');

    fetch('/api/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || '测试失败');
        return d;
      });
    }).then(function (data) {
      App.toast('测试完成: ' + data.filename, 3000);
      setTimeout(function () {
        document.querySelector('[data-tab="results"]').click();
        App.playAudio(data.filename);
      }, 300);
    }).catch(function (e) {
      App.toast(e.message, 3000);
    }).finally(function () {
      $('btnTest').disabled = false;
      $('btnTest').textContent = '🧪 测试';
    });
  }

  // ── 页面刷新恢复（快照兜底） ──────────────────────
  function checkStatus() {
    fetch('/api/task/status').then(function (r) { return r.json(); }).then(function (data) {
      if (!data || !data.status) return;

      if (data.status === 'running' || data.status === 'paused' || data.status === 'stopping') {
        currentTaskId = data.task_id;
        currentTaskName = data.task_name || '';
        App.show('progressSection');
        App.show('logSection');
        updateProgress(data.completed, data.total, data.progress);
        $('logBox').textContent = (data.logs || []).join('\n');
        if (data.status === 'paused') {
          setUIRunning();
          setUIPaused();
        } else {
          setUIRunning();
        }
        connectSSE();
      } else if (data.status === 'done' && data.files && data.files.length) {
        setUIIdle();
        updateProgress(data.total, data.total, 100);
      } else {
        setUIIdle();
      }
    }).catch(function () { });
  }

  // ── 队列显示 ──────────────────────────────────────
  function loadQueue() {
    fetch('/api/task/queue').then(function (r) { return r.json(); }).then(function (data) {
      var queue = data.queue || [];
      var el = $('queueList');
      if (!el) return;
      if (!queue.length) {
        el.innerHTML = '<div class="empty-hint">队列为空</div>';
        return;
      }
      var html = '<ul class="queue-items">';
      queue.forEach(function (t, i) {
        html += '<li>' + (i + 1) + '. ' + esc(t.name) + ' (' + t.total + '段)</li>';
      });
      html += '</ul>';
      el.innerHTML = html;
    }).catch(function () { });
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ── 公开接口 ──────────────────────────────────────
  return {
    start: start,
    stop: stop,
    pause: pause,
    resume: resume,
    test: test,
    checkStatus: checkStatus,
    onResumedFromList: onResumedFromList,
    switchToCurrent: switchToCurrent,
    loadQueue: loadQueue,
  };
})();
