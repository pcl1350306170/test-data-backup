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
    $('btnStart').disabled = true;
    $('btnTest').disabled = true;
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
        setUIRunning();
        updateProgress(0, event.total, 0);
        if (event.resumed && event.resumed > 0) {
          appendLog('已跳过 ' + event.resumed + ' 段（此前完成）');
        }
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
        setUIIdle();
        updateProgress(event.total, event.total, 100);
        App.toast('生成完成！共 ' + event.files.length + ' 个文件', 3000);
        disconnectSSE();
        currentTaskId = null;
        App.loadTaskList();
        setTimeout(function () {
          document.querySelector('[data-tab="results"]').click();
        }, 500);
        break;

      case 'cancelled':
        setUIIdle();
        App.toast('任务已停止，成品与中间文件已清理');
        disconnectSSE();
        App.loadTaskList();
        App.loadAudioList();
        break;

      case 'error':
        setUIIdle();
        App.toast('生成失败: ' + event.message, 4000);
        disconnectSSE();
        App.loadTaskList();
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
    $('btnStart').disabled = true;
    $('btnTest').disabled = true;

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
      setUIRunning();
      updateProgress(0, data.total, 0);
      App.toast('任务已启动，共 ' + data.total + ' 段');
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
  };
})();
