/* CosyVoice TTS Web — 主逻辑 */
var App = (function () {
  var config = {};
  var toastTimer = null;
  var pendingDeleteTaskId = null;
  var pendingDeleteTaskName = '';

  // ── 工具函数 ──────────────────────────────────────
  function $(id) { return document.getElementById(id); }

  function toast(msg, ms) {
    var t = $('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, ms || 2500);
  }

  function show(el) { if (typeof el === 'string') el = $(el); if (el) el.style.display = ''; }
  function hide(el) { if (typeof el === 'string') el = $(el); if (el) el.style.display = 'none'; }

  // ── 夜间模式 ──────────────────────────────────────
  function systemDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function getTheme() {
    var saved = localStorage.getItem('tts_theme');
    return (saved === 'dark' || saved === 'light') ? saved : (systemDark() ? 'dark' : 'light');
  }
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    var btn = $('themeBtn');
    if (btn) {
      btn.textContent = t === 'dark' ? '☀️' : '🌙';
      btn.title = t === 'dark' ? '切换到浅色模式' : '切换到深色模式';
    }
  }
  function toggleTheme() {
    var next = getTheme() === 'dark' ? 'light' : 'dark';
    localStorage.setItem('tts_theme', next);
    applyTheme(next);
  }
  function initTheme() {
    applyTheme(getTheme());
    var btn = $('themeBtn');
    if (btn) btn.addEventListener('click', toggleTheme);
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
        var saved = localStorage.getItem('tts_theme');
        if (saved !== 'dark' && saved !== 'light') applyTheme(e.matches ? 'dark' : 'light');
      });
    }
  }

  // ── Tab 切换 ──────────────────────────────────────
  function initTabs() {
    var tabs = document.querySelectorAll('.tab');
    tabs.forEach(function (btn) {
      btn.addEventListener('click', function () {
        tabs.forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(function (s) { s.classList.remove('active'); });
        var target = $('tab-' + btn.dataset.tab);
        if (target) target.classList.add('active');
        if (btn.dataset.tab === 'results') loadAudioList();
        if (btn.dataset.tab === 'tasks') loadTaskList();
        if (btn.dataset.tab === 'merge' && window.Merge) Merge.refresh();
      });
    });
  }

  // ── 配置加载 ──────────────────────────────────────
  function loadConfig() {
    fetch('/api/config').then(function (r) { return r.json(); }).then(function (data) {
      config = data.config || {};
      // 填充音色下拉
      var spk = $('spkSelect'); spk.innerHTML = '';
      (data.spk_options || []).forEach(function (s) {
        spk.innerHTML += '<option value="' + s + '"' + (s === config.spk ? ' selected' : '') + '>' + s + '</option>';
      });
      // 填充风格下拉
      var style = $('styleSelect'); style.innerHTML = '';
      (data.style_options || []).forEach(function (s) {
        var label = s || '(无)';
        style.innerHTML += '<option value="' + s + '"' + (s === (config.style || '') ? ' selected' : '') + '>' + label + '</option>';
      });
      // 填充语速下拉
      var speed = $('speedSelect'); speed.innerHTML = '';
      (data.speed_options || []).forEach(function (s) {
        speed.innerHTML += '<option value="' + s + '"' + (parseFloat(s) === parseFloat(config.speed || 1) ? ' selected' : '') + '>' + s + 'x</option>';
      });
      // 其他默认值
      if (config.format) $('formatSelect').value = config.format;
      if (config.seg_len) $('segLenInput').value = config.seg_len;
      $('fadeCheck').checked = config.fade !== false;
      $('fadeMsInput').value = config.fade_ms || 0;
      $('tailMsInput').value = config.tail_ms || 900;
      // 设置页
      fillSettings(config);
      // 合并页参数回填
      if (window.Merge) Merge.applyConfig(config);
      // 加载参考音频
      loadPromptAudios();
    }).catch(function (e) { toast('加载配置失败: ' + e.message); });
  }

  function fillSettings(cfg) {
    $('cfg-output-dir').value = cfg.output_dir || '';
    $('cfg-tts-dir').value = cfg.tts_dir || '';
    $('cfg-bgm-dir').value = cfg.bgm_dir || '';
    $('cfg-image-dir').value = cfg.image_dir || '';
    $('cfg-conda-python').value = cfg.conda_python || '';
    $('cfg-model-dir').value = cfg.model_dir || '';
    $('cfg-repo-dir').value = cfg.repo_dir || '';
    $('cfg-worker-script').value = cfg.worker_script || '';
    $('cfg-spk').value = cfg.spk || '';
    $('cfg-speed').value = cfg.speed || 1.0;
    $('cfg-format').value = cfg.format || 'wav';
  }

  function loadPromptAudios() {
    fetch('/api/prompt_audios').then(function (r) { return r.json(); }).then(function (data) {
      var sel = $('promptAudioSelect');
      sel.innerHTML = '<option value="">(不使用 Zero-Shot)</option>';
      (data.audios || []).forEach(function (a) {
        sel.innerHTML += '<option value="' + a.path + '">' + a.name + '</option>';
      });
      if (config.prompt_audio) {
        sel.value = config.prompt_audio;
        $('promptTextInput').value = config.prompt_text || '';
      }
    }).catch(function () { });
  }

  // ── 参考音频联动 ──────────────────────────────────
  function initPromptAudio() {
    $('promptAudioSelect').addEventListener('change', function () {
      if (this.value) {
        $('spkSelect').disabled = true;
        if (!$('promptTextInput').value && config.default_prompt_text) {
          $('promptTextInput').value = config.default_prompt_text;
        }
      } else {
        $('spkSelect').disabled = false;
        $('promptTextInput').value = '';
      }
    });
  }

  // ── 文本操作 ──────────────────────────────────────
  function initTextInput() {
    $('textInput').addEventListener('input', function () {
      $('charCount').textContent = this.value.length + ' 字符';
    });
  }

  function clearText() {
    $('textInput').value = '';
    $('charCount').textContent = '0 字符';
  }

  function importTxt(e) {
    var file = e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (ev) {
      $('textInput').value = ev.target.result;
      $('charCount').textContent = ev.target.result.length + ' 字符';
      toast('已导入: ' + file.name);
    };
    reader.readAsText(file, 'UTF-8');
    e.target.value = '';
  }

  // ── 保存配置 ──────────────────────────────────────
  function saveConfig() {
    var data = {
      output_dir: $('cfg-output-dir').value.trim(),
      tts_dir: $('cfg-tts-dir').value.trim(),
      bgm_dir: $('cfg-bgm-dir').value.trim(),
      image_dir: $('cfg-image-dir').value.trim(),
      conda_python: $('cfg-conda-python').value.trim(),
      model_dir: $('cfg-model-dir').value.trim(),
      repo_dir: $('cfg-repo-dir').value.trim(),
      worker_script: $('cfg-worker-script').value.trim(),
      spk: $('cfg-spk').value.trim(),
      speed: parseFloat($('cfg-speed').value) || 1.0,
      format: $('cfg-format').value,
    };
    fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).then(function (r) { return r.json(); }).then(function () {
      toast('配置已保存');
      loadConfig();
    }).catch(function (e) { toast('保存失败: ' + e.message); });
  }

  // ── 音频列表 ──────────────────────────────────────
  function loadAudioList() {
    fetch('/api/audio/list').then(function (r) { return r.json(); }).then(function (data) {
      var files = data.files || [];
      var listEl = $('audioList');
      var emptyEl = $('audioEmpty');
      if (!files.length) {
        listEl.innerHTML = '';
        show(emptyEl);
        return;
      }
      hide(emptyEl);
      var html = '';
      files.forEach(function (f) {
        var sizeStr = f.size > 1048576 ? (f.size / 1048576).toFixed(1) + 'MB' : (f.size / 1024).toFixed(0) + 'KB';
        html += '<div class="audio-item">';
        html += '<span class="fname" title="' + f.name + '">' + f.name + '</span>';
        html += '<span class="fmeta">' + sizeStr + ' · ' + f.modified + '</span>';
        html += '<span class="ops">';
        html += '<button onclick="App.playAudio(\'' + escHtml(f.name) + '\')">▶ 播放</button>';
        html += '<a href="/api/audio/download?file=' + encodeURIComponent(f.name) + '">⬇ 下载</a>';
        html += '<button class="btn-del" onclick="App.deleteAudio(\'' + escHtml(f.name) + '\')">✕</button>';
        html += '</span></div>';
      });
      listEl.innerHTML = html;
    }).catch(function () { });
  }

  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function playAudio(filename) {
    var player = $('audioPlayer');
    var wrap = $('playerWrap');
    player.src = '/api/audio/play?file=' + encodeURIComponent(filename);
    $('playerName').textContent = filename;
    show(wrap);
    player.play();
  }

  function deleteAudio(filename) {
    if (!confirm('确定删除「' + filename + '」？')) return;
    fetch('/api/audio/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: filename })
    }).then(function (r) {
      if (!r.ok) throw new Error('删除失败');
      return r.json();
    }).then(function () {
      toast('已删除');
      loadAudioList();
    }).catch(function (e) { toast(e.message); });
  }

  // ── 获取当前合成参数 ──────────────────────────────
  function getParams() {
    return {
      text: $('textInput').value.trim(),
      task_name: $('taskNameInput') ? $('taskNameInput').value.trim() : '',
      spk: $('spkSelect').value,
      style: $('styleSelect').value,
      speed: parseFloat($('speedSelect').value) || 1.0,
      format: $('formatSelect').value,
      seg_len: parseInt($('segLenInput').value) || 500,
      fade: $('fadeCheck').checked,
      fade_ms: parseInt($('fadeMsInput').value) || 0,
      tail_ms: parseInt($('tailMsInput').value) || 900,
      prompt_audio: $('promptAudioSelect').value || '',
      prompt_text: $('promptTextInput').value.trim(),
      prefix: $('prefixInput').value.trim(),
    };
  }

  // ── 保存当前合成参数到服务端配置 ──────────────────
  function saveSynthConfig(params) {
    var data = {
      spk: params.spk,
      style: params.style,
      speed: params.speed,
      format: params.format,
      seg_len: params.seg_len,
      fade: params.fade,
      fade_ms: params.fade_ms,
      tail_ms: params.tail_ms,
      prompt_audio: params.prompt_audio,
      prompt_text: params.prompt_text,
    };
    fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).catch(function () { });
  }

  function loadTaskList() {
    fetch('/api/tasks').then(function (r) { return r.json(); }).then(function (data) {
      var tasks = data.tasks || [];
      var listEl = $('taskList');
      var emptyEl = $('taskEmpty');
      var hintEl = $('taskListHint');
      var STATUS_LABELS = {
        idle: '空闲', running: '执行中', paused: '已暂停', stopping: '正在停止…',
        cancelled: '已停止', done: '已完成', error: '失败', interrupted: '待恢复',
      };
      var unfinished = tasks.filter(function (t) { return t.status !== 'done'; }).length;
      var badge = $('taskBadge');
      if (badge) {
        if (unfinished > 0) { badge.textContent = unfinished; show(badge); }
        else hide(badge);
      }
      if (hintEl) hintEl.textContent = '共 ' + tasks.length + ' 个任务';

      if (!tasks.length) { if (listEl) listEl.innerHTML = ''; if (emptyEl) show(emptyEl); return; }
      if (emptyEl) hide(emptyEl);
      var html = '';
      tasks.forEach(function (t) {
        var pct = t.total > 0 ? Math.round(t.completed / t.total * 100) : 0;
        var isActive = (t.id === data.active_task_id);
        var resumable = !isActive && (t.status === 'interrupted' || t.status === 'paused'
          || t.status === 'error');
        html += '<div class="task-card status-' + t.status + '">';
        html += '<div class="task-head">';
        html += '<div class="task-title" title="' + escHtml(t.name || '') + '">' + escHtml(t.name || '(未命名)') + '</div>';
        html += '<span class="status-chip ' + t.status + '">' + (STATUS_LABELS[t.status] || t.status) + (isActive ? ' （当前）' : '') + '</span>';
        html += '</div>';
        html += '<div class="task-meta">';
        html += '<span>🕐 ' + escHtml(t.created_at || '') + '</span>';
        html += '<span>段数 ' + t.completed + '/' + t.total + '</span>';
        html += '<span>成品 ' + t.output_count + ' 个</span>';
        html += '<span>ID: ' + escHtml(t.id) + '</span>';
        html += '</div>';
        if (t.text_preview) {
          html += '<div class="task-preview">' + escHtml(t.text_preview) + (t.text_preview.length >= 60 ? '…' : '') + '</div>';
        }
        html += '<div class="task-progress"><div class="task-progress-bar"><div style="width:' + pct + '%"></div></div>';
        html += '<div class="task-progress-text">' + pct + '%</div></div>';
        if (t.error) html += '<div class="task-error">' + escHtml(t.error) + '</div>';
        html += '<div class="task-actions-row">';
        if (isActive && (t.status === 'running' || t.status === 'paused' || t.status === 'stopping')) {
          html += '<button class="btn" onclick="Task.switchToCurrent()">查看当前进度</button>';
        } else if (resumable) {
          html += '<button class="btn btn-primary" onclick="App.resumeTask(\'' + escHtml(t.id) + '\')">▶ 继续任务</button>';
        }
        if (t.output_count > 0) {
          html += '<button class="btn" onclick="App.viewTaskOutput(\'' + escHtml(t.id) + '\')">查看成品</button>';
          html += '<button class="btn" onclick="App.gotoMergeWithTask(\'' + escHtml(t.id) + '\')">🔗 合并成品</button>';
        }
        html += '<button class="btn" onclick="App.cleanTaskTemp(\'' + escHtml(t.id) + '\')">🧹 清理中间文件</button>';
        html += '<button class="btn btn-danger" onclick="App.openDeleteModal(\'' + escHtml(t.id) + '\', \'' + escHtml(t.name || '(未命名)') + '\', ' + t.output_count + ')">🗑 删除</button>';
        html += '</div></div>';
      });
      listEl.innerHTML = html;
    }).catch(function (e) { toast('加载任务列表失败: ' + e.message); });
  }

  function resumeTask(taskId) {
    fetch('/api/tasks/' + encodeURIComponent(taskId) + '/resume', { method: 'POST' })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error(d.detail || '恢复失败');
          return d;
        });
      }).then(function (d) {
        toast('任务已恢复，共 ' + d.total + ' 段');
        document.querySelector('[data-tab="synthesize"]').click();
        Task.onResumedFromList();
      }).catch(function (e) { toast(e.message, 3000); });
  }

  function viewTaskOutput(taskId) {
    document.querySelector('[data-tab="results"]').click();
    toast('已切换到成品列表（任务ID: ' + taskId + '）');
  }

  // 从任务列表跳到合并页，并预选该任务的成品
  function gotoMergeWithTask(taskId) {
    document.querySelector('[data-tab="merge"]').click();
    // Merge.refresh 是异步渲染列表，稍后再勾选
    setTimeout(function () {
      if (window.Merge) Merge.selectTaskFiles(taskId);
    }, 600);
  }

  function openDeleteModal(taskId, taskName, outputCount) {
    pendingDeleteTaskId = taskId;
    pendingDeleteTaskName = taskName;
    $('modalTaskName').textContent = taskName;
    $('cleanOutputCount').textContent = outputCount > 0 ? (outputCount + ' 个文件') : '无成品';
    $('cleanTempCheck').checked = true;
    $('cleanOutputCheck').checked = false;
    show('modal');
  }
  function closeModal() {
    pendingDeleteTaskId = null;
    hide('modal');
  }
  function confirmDeleteTask() {
    if (!pendingDeleteTaskId) { closeModal(); return; }
    var cleanTemp = $('cleanTempCheck').checked;
    var cleanOutput = $('cleanOutputCheck').checked;
    var url = '/api/tasks/' + encodeURIComponent(pendingDeleteTaskId)
      + '?clean_temp=' + cleanTemp + '&clean_output=' + cleanOutput;
    fetch(url, { method: 'DELETE' }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || '删除失败');
        return d;
      });
    }).then(function (d) {
      var msg = '任务已删除';
      if (d.removed && (d.removed.temp || d.removed.output)) {
        msg += '（中间文件 ' + d.removed.temp + ' 个、成品 ' + d.removed.output + ' 个）';
      }
      toast(msg);
      closeModal();
      loadTaskList();
      loadAudioList();
    }).catch(function (e) { toast(e.message, 3000); });
  }

  function cleanTaskTemp(taskId) {
    if (!confirm('确定清理该任务的中间文件吗？（成品文件不受影响）')) return;
    fetch('/api/tasks/' + encodeURIComponent(taskId) + '/clean_temp', { method: 'POST' })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error(d.detail || '清理失败');
          return d;
        });
      }).then(function (d) {
        var msg = '中间文件已清理';
        if (d.removed && d.removed.temp) {
          msg += '（' + d.removed.temp + ' 个目录）';
        }
        toast(msg);
        loadTaskList();
      }).catch(function (e) { toast(e.message, 3000); });
  }

  // ── 初始化 ──────────────────────────────────────
  function init() {
    initTheme();
    initTabs();
    initTextInput();
    initPromptAudio();
    loadConfig();
    loadTaskList();
    Task.checkStatus();
  }

  document.addEventListener('DOMContentLoaded', init);

  // ── 公开接口 ──────────────────────────────────────
  return {
    toast: toast,
    show: show,
    hide: hide,
    $: $,
    clearText: clearText,
    importTxt: importTxt,
    saveConfig: saveConfig,
    saveSynthConfig: saveSynthConfig,
    loadAudioList: loadAudioList,
    playAudio: playAudio,
    deleteAudio: deleteAudio,
    getParams: getParams,
    getConfig: function () { return config; },
    loadTaskList: loadTaskList,
    resumeTask: resumeTask,
    viewTaskOutput: viewTaskOutput,
    gotoMergeWithTask: gotoMergeWithTask,
    openDeleteModal: openDeleteModal,
    closeModal: closeModal,
    confirmDeleteTask: confirmDeleteTask,
    cleanTaskTemp: cleanTaskTemp,
  };
})();
