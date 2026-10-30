/* CosyVoice TTS Web — 音频合并（任务成品分组拼接） */
var Merge = (function () {
  var eventSource = null;
  var filesCache = [];      // /api/audio/list 结果
  var running = false;
  var lastOutDir = '';      // 本次/上次合并的实际输出目录
  var lastAutoSource = '';  // 上次选任务时自动填入的来源名（用于判断用户是否手改过）
  var lastAutoTitle = '';   // 上次选任务时自动填入的标题
  var selectedTaskNames = [];  // 选任务时该任务的全部成品名（用于完整性校验）
  var selectedTaskLabel = '';  // 当前选中任务的名字
  var pendingSel = null;       // 文件列表未加载完时暂存的任务选择

  function $(id) { return document.getElementById(id); }

  // ── 初始化 ──────────────────────────────────────
  function init() {
    $('mergeTaskSelect').addEventListener('change', function () {
      if (this.value) selectTaskFiles(this.value);
      else updateCount();
    });
    $('mergeSourceName').addEventListener('change', function () {
      lastAutoSource = this.value.trim();   // 手动改过，以用户值为准
      saveSettings();
    });
    $('mergeBgmSelect').addEventListener('change', function () {
      if (this.value) $('mergeBgmPath').value = this.value;
      saveSettings();
    });
    $('mergeBgmVolume').addEventListener('input', function () {
      $('mergeBgmVolLabel').textContent = this.value;
    });
    ['mergeBgmPath', 'mergeCoverPath', 'mergeBgImagePath',
     'metaTitle', 'metaArtist', 'metaAlbum', 'metaDate', 'metaComment'].forEach(function (id) {
      $(id).addEventListener('change', function () {
        if (id === 'metaTitle') lastAutoTitle = this.value.trim();
        saveSettings();
      });
    });
    $('mergeDuration').addEventListener('change', saveSettings);
    $('mergeFormat').addEventListener('change', saveSettings);
    $('mergeStartNum').addEventListener('change', saveSettings);
    checkStatus();
  }

  // ── 刷新列表 ──────────────────────────────────────
  function refresh() {
    loadFileList();
    loadTaskOptions();
    loadMediaOptions();
  }

  function loadFileList() {
    // limit=0：拉取完整列表。成品目录文件数超过默认上限时，
    // 任务的成品会被截断，导致选任务后只勾中一部分。
    fetch('/api/audio/list?limit=0').then(function (r) { return r.json(); }).then(function (data) {
      filesCache = data.files || [];
      var checked = checkedNames();
      var el = $('mergeFileList');
      if (!filesCache.length) {
        el.innerHTML = '<div class="empty-hint">output 目录暂无音频文件</div>';
        updateCount();
        return;
      }
      var html = '';
      filesCache.forEach(function (f) {
        var sizeStr = f.size > 1048576 ? (f.size / 1048576).toFixed(1) + 'MB' : (f.size / 1024).toFixed(0) + 'KB';
        var c = checked.indexOf(f.name) >= 0 ? ' checked' : '';
        var base = f.base || f.name;
        var dirTag = f.dir ? '<span class="fc-dir">' + esc(f.dir) + '</span>' : '';
        html += '<label class="fc-item"><input type="checkbox" value="' + esc(f.name) + '"' + c + ' onchange="Merge.onFileCheckChange()">' +
          '<span class="fc-name" title="' + esc(f.name) + '">' + esc(base) + dirTag + '</span>' +
          '<span class="fc-meta">' + sizeStr + '</span></label>';
      });
      el.innerHTML = html;
      // 列表是异步加载的：若加载完成前已选了任务，渲染后要补上勾选
      if (pendingSel) {
        var p = pendingSel;
        pendingSel = null;
        applyTaskSelection(p.names, p.label);
      }
      updateCount();
    }).catch(function () { });
  }

  function loadTaskOptions() {
    fetch('/api/tasks').then(function (r) { return r.json(); }).then(function (data) {
      var sel = $('mergeTaskSelect');
      var cur = sel.value;
      sel.innerHTML = '<option value="">（手动勾选下方文件）</option>';
      (data.tasks || []).forEach(function (t) {
        if (t.output_count > 0) {
          sel.innerHTML += '<option value="' + esc(t.id) + '">' +
            esc(t.name || t.id) + '（' + t.output_count + ' 个成品）</option>';
        }
      });
      if (cur) sel.value = cur;
    }).catch(function () { });
  }

  function loadMediaOptions() {
    fetch('/api/media_files?kind=audio').then(function (r) { return r.json(); }).then(function (data) {
      var sel = $('mergeBgmSelect');
      sel.innerHTML = '<option value="">(不叠加)</option>';
      (data.files || []).forEach(function (f) {
        sel.innerHTML += '<option value="' + esc(f.path) + '">' + esc(f.name) + '</option>';
      });
      var saved = ($('mergeBgmPath').value || '').trim();
      if (saved) {
        var known = (data.files || []).some(function (f) { return f.path === saved; });
        if (known) sel.value = saved;
      }
    }).catch(function () { });
    // 图片选择已改为弹窗预览模式，不再加载下拉
    updateImagePreview('cover');
    updateImagePreview('bgimg');
  }

  // ── 文件勾选 ──────────────────────────────────────
  function checkedBoxes() {
    return Array.prototype.slice.call(
      $('mergeFileList').querySelectorAll('input[type=checkbox]:checked'));
  }
  function checkedNames() {
    return checkedBoxes().map(function (b) { return b.value; });
  }
  function selectAll(on) {
    $('mergeFileList').querySelectorAll('input[type=checkbox]').forEach(function (b) {
      b.checked = !!on;
    });
    invalidateTaskSelection();
    updateCount();
  }

  /** 单个勾选变化（列表 inline onchange 入口） */
  function onFileCheckChange() {
    invalidateTaskSelection();
    updateCount();
  }
  function updateCount() {
    var n = checkedBoxes().length;
    var txt = '已选 ' + n + ' 个文件';
    if (selectedTaskNames.length && n !== selectedTaskNames.length) {
      txt += '（任务「' + selectedTaskLabel + '」共 ' + selectedTaskNames.length +
        ' 个成品，未全部选中！）';
    }
    $('mergeFileCount').textContent = txt;
  }

  /** 手动改过勾选后，就不再拿任务完整性去校验 */
  function invalidateTaskSelection() {
    selectedTaskNames = [];
    selectedTaskLabel = '';
  }

  /**
   * 校验已勾选文件是否覆盖当前任务的全部成品。
   * 返回缺失文件名数组（空 = 完整）。防止列表被截断/文件丢失时默默合并不完整内容。
   */
  function missingTaskFiles() {
    if (!selectedTaskNames.length) return [];
    var picked = {};
    checkedNames().forEach(function (n) { picked[n] = 1; });
    return selectedTaskNames.filter(function (n) { return !picked[n]; });
  }

  function selectTaskFiles(taskId) {
    fetch('/api/tasks/' + encodeURIComponent(taskId)).then(function (r) {
      if (!r.ok) throw new Error('任务不存在');
      return r.json();
    }).then(function (t) {
      var names = t.output_files || [];
      if (!filesCache.length) {
        // 文件列表还没加载完（直接选了任务），先暂存，渲染后再勾选
        pendingSel = { names: names, label: t.name || t.id };
        selectedTaskNames = names.slice();
        selectedTaskLabel = pendingSel.label;
        syncTaskName(t.name || '');
        updateCount();
        App.toast('已选择任务「' + selectedTaskLabel + '」，等待文件列表加载后自动勾选 ' +
          names.length + ' 个成品');
        return;
      }
      applyTaskSelection(names, t.name || t.id);
      syncTaskName(t.name || '');
    }).catch(function (e) { App.toast(e.message); });
  }

  /** 把任务的成品全部勾上，其余取消，并报告找不到的文件 */
  function applyTaskSelection(names, label) {
    var boxes = Array.prototype.slice.call(
      $('mergeFileList').querySelectorAll('input[type=checkbox]'));
    var inList = {};
    boxes.forEach(function (b) { inList[b.value] = b; });
    var missing = [];
    names.forEach(function (n) {
      if (inList[n]) inList[n].checked = true;
      else missing.push(n);
    });
    boxes.forEach(function (b) {
      if (names.indexOf(b.value) < 0) b.checked = false;
    });
    selectedTaskNames = names.slice();
    selectedTaskLabel = label;
    updateCount();
    if (missing.length) {
      App.toast('任务「' + label + '」有 ' + missing.length + '/' + names.length +
        ' 个成品在列表中找不到（已被删除或未加载），已选中 ' +
        (names.length - missing.length) + ' 个', 8000);
    } else {
      App.toast('已勾选任务「' + label + '」的 ' + names.length + ' 个成品');
    }
  }

  /**
   * 切换任务时同步「来源名」与「标题」。
   * 规则：为空、或仍是上次选任务自动填入的值 → 跟新任务名走；
   * 用户手改过则不覆盖（避免丢失自定义命名）。
   */
  function syncTaskName(name) {
    name = (name || '').trim();
    if (!name) return;
    var srcEl = $('mergeSourceName');
    var cur = srcEl.value.trim();
    if (!cur || cur === lastAutoSource) {
      srcEl.value = name;
      lastAutoSource = name;
    }
    var tEl = $('metaTitle');
    var curT = tEl.value.trim();
    if (!curT || curT === lastAutoTitle || curT === lastAutoSource) {
      tEl.value = name;
      lastAutoTitle = name;
    }
    saveSettings();
  }

  // ── 参数收集 / 持久化 ─────────────────────────────
  function getMergeParams(test) {
    var bgm = ($('mergeBgmPath').value || '').trim() || $('mergeBgmSelect').value || '';
    var cover = ($('mergeCoverPath').value || '').trim();
    var bgimg = ($('mergeBgImagePath').value || '').trim();
    return {
      files: checkedNames(),
      test: !!test,
      target_duration: parseInt($('mergeDuration').value) || 20,
      format: $('mergeFormat').value,
      source_name: ($('mergeSourceName').value || '').trim(),
      start_num: ($('mergeStartNum').value || '1').trim(),
      output_dir: ($('mergeOutputDir').value || '').trim(),
      bgm_path: bgm,
      bgm_volume: parseInt($('mergeBgmVolume').value) || 0,
      cover_path: cover,
      bg_image_path: bgimg,
      metadata: {
        title: $('metaTitle').value.trim(),
        artist: $('metaArtist').value.trim(),
        album: $('metaAlbum').value.trim(),
        date: $('metaDate').value.trim(),
        comment: $('metaComment').value.trim(),
      },
    };
  }

  function saveSettings() {
    var data = {
      merge_target_duration: parseInt($('mergeDuration').value) || 20,
      merge_format: $('mergeFormat').value,
      merge_bgm_path: ($('mergeBgmPath').value || '').trim(),
      merge_bgm_volume: parseInt($('mergeBgmVolume').value) || 0,
      merge_cover_path: ($('mergeCoverPath').value || '').trim(),
      merge_bg_image_path: ($('mergeBgImagePath').value || '').trim(),
      merge_start_num: ($('mergeStartNum').value || '1').trim(),
      merge_output_dir: ($('mergeOutputDir').value || '').trim(),
      meta_title: $('metaTitle').value.trim(),
      meta_artist: $('metaArtist').value.trim(),
      meta_album: $('metaAlbum').value.trim(),
      meta_date: $('metaDate').value.trim(),
      meta_comment: $('metaComment').value.trim(),
    };
    fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).catch(function () { });
  }

  // 配置加载完成后回填（由 App.loadConfig 调用）
  function applyConfig(cfg) {
    if (!cfg) return;
    if (cfg.merge_target_duration) $('mergeDuration').value = cfg.merge_target_duration;
    if (cfg.merge_format) $('mergeFormat').value = cfg.merge_format;
    $('mergeBgmPath').value = cfg.merge_bgm_path || '';
    $('mergeBgmVolume').value = cfg.merge_bgm_volume != null ? cfg.merge_bgm_volume : 30;
    $('mergeBgmVolLabel').textContent = $('mergeBgmVolume').value;
    $('mergeCoverPath').value = cfg.merge_cover_path || '';
    $('mergeBgImagePath').value = cfg.merge_bg_image_path || '';
    $('mergeStartNum').value = cfg.merge_start_num || '1';
    $('mergeOutputDir').value = cfg.merge_output_dir || '';
    // 刷新后来源名从配置重置（来源名不做持久化），重新认得“上次自动填入的值”
    lastAutoSource = ($('mergeSourceName').value || '').trim();
    $('metaTitle').value = cfg.meta_title || '';
    lastAutoTitle = cfg.meta_title || '';
    $('metaArtist').value = cfg.meta_artist || '';
    $('metaAlbum').value = cfg.meta_album || '';
    $('metaDate').value = cfg.meta_date || '';
    $('metaComment').value = cfg.meta_comment || '';
    loadMediaOptions();
  }

  // ── 图片弹窗预览 ─────────────────────────────────────
  var pickerTarget = null;  // 'cover' | 'bgimg'

  function openImagePicker(target) {
    pickerTarget = target;
    var modal = $('imgPickerModal');
    var grid = $('imgPickerGrid');
    var empty = $('imgPickerEmpty');
    grid.innerHTML = '<div class="empty-hint">加载中...</div>';
    empty.style.display = 'none';
    modal.style.display = '';

    fetch('/api/media_files?kind=image').then(function (r) { return r.json(); }).then(function (data) {
      var files = data.files || [];
      if (!files.length) {
        grid.innerHTML = '';
        empty.style.display = '';
        return;
      }
      var html = '';
      files.forEach(function (f) {
        var src = '/api/image_preview?path=' + encodeURIComponent(f.path);
        html += '<div class="img-pick-item" data-path="' + esc(f.path) + '" title="' + esc(f.name) + '">' +
          '<img src="' + src + '" loading="lazy" alt="' + esc(f.name) + '">' +
          '<span>' + esc(f.name) + '</span></div>';
      });
      grid.innerHTML = html;
      grid.querySelectorAll('.img-pick-item').forEach(function (el) {
        el.addEventListener('click', function () {
          pickImage(this.getAttribute('data-path'));
        });
      });
    }).catch(function () {
      grid.innerHTML = '<div class="empty-hint">加载失败</div>';
    });
  }

  function closeImagePicker() {
    document.getElementById('imgPickerModal').style.display = 'none';
    pickerTarget = null;
  }
  
  function pickImage(path) {
    if (!pickerTarget) return;
    var inputId = pickerTarget === 'cover' ? 'mergeCoverPath' : 'mergeBgImagePath';
    document.getElementById(inputId).value = path;
    saveSettings();
    updateImagePreview(pickerTarget);
    closeImagePicker();
  }

  function clearImage(target) {
    var inputId = target === 'cover' ? 'mergeCoverPath' : 'mergeBgImagePath';
    $(inputId).value = '';
    saveSettings();
    updateImagePreview(target);
  }

  function updateImagePreview(target) {
    var inputId = target === 'cover' ? 'mergeCoverPath' : 'mergeBgImagePath';
    var wrapId = target === 'cover' ? 'coverPreviewWrap' : 'bgimgPreviewWrap';
    var path = ($(inputId).value || '').trim();
    var wrap = $(wrapId);
    if (!path) {
      wrap.innerHTML = '';
      return;
    }
    var src = '/api/image_preview?path=' + encodeURIComponent(path);
    wrap.innerHTML = '<img src="' + src + '" class="img-preview-thumb" alt="preview">' +
      '<span class="img-preview-name">' + esc(path.split(/[\\/]/).pop()) + '</span>';
  }

  // ── 预览分组 ──────────────────────────────────────
  function preview() {
    var files = checkedNames();
    if (!files.length) { App.toast('请先勾选要合并的文件'); return; }
    var miss = missingTaskFiles();
    if (miss.length) {
      App.toast('当前任务还有 ' + miss.length + ' 个成品未选中（如 ' + miss[0] +
        '），合并内容会不完整，请先刷新列表或重新选择任务', 8000);
      return;
    }
    fetch('/api/merge/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: files, target_duration: parseInt($('mergeDuration').value) || 20 })
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || '预览失败');
        return d;
      });
    }).then(function (d) {
      var el = $('mergePreview');
      App.show(el);
      if (!d.groups.length) { el.innerHTML = '<div class="hint">未能解析音频时长</div>'; return; }
      var mins = (d.total_seconds / 60).toFixed(1);
      var html = '<div class="mp-summary">总时长 ' + mins + ' 分钟 → ' + d.num_groups + ' 组' +
        (d.skipped ? '（' + d.skipped + ' 个文件已失效被跳过）' : '') + '</div>';
      d.groups.forEach(function (g, i) {
        html += '<details class="mp-group"><summary>第 ' + (i + 1) + ' 组 · ' +
          g.count + ' 个文件 · ' + (g.seconds / 60).toFixed(1) + ' 分钟</summary>';
        html += '<ul class="mp-files">' + g.files.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul></details>';
      });
      el.innerHTML = html;
    }).catch(function (e) { App.toast(e.message, 3000); });
  }

  // ── 开始 / 停止 ─────────────────────────────────────
  function start(test, isConfirm) {
    var params = getMergeParams(test);
    if (!params.files.length) { App.toast('请先勾选要合并的文件'); return; }
    if (!params.metadata.title) { App.toast('必须输入标题'); return; }
    var miss = missingTaskFiles();
    if (miss.length && !isConfirm) {
      App.toast('当前任务还有 ' + miss.length + ' 个成品未选中（如 ' + miss[0] +
        '），合并内容会不完整。可点“刷新列表”后重新选择任务', 8000);
      return;
    }
    if (isConfirm) params.confirm = true;

    saveSettings();
    connectSSE();
    setRunning(true);
    $('mergeLogBox').textContent = '';
    App.show('mergeProgressSection');
    App.show('mergeLogSection');
    updateProgress(0, 0, 0);

    fetch('/api/merge/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || '启动失败');
        return d;
      });
    }).then(function (d) {
      if (d.need_confirm) {
        setRunning(false);
        disconnectSSE();
        if (window.confirm(d.message || '输出目录已存在，是否继续使用？')) {
          start(test, true);
        }
        return;
      }
      App.toast((test ? '测试合并' : '合并') + '已启动，共 ' + d.total + ' 组');
    }).catch(function (e) {
      App.toast(e.message, 3000);
      setRunning(false);
      disconnectSSE();
    });
  }

  function stop() {
    fetch('/api/merge/stop', { method: 'POST' }).catch(function () { });
  }

  function setRunning(on) {
    running = on;
    $('btnMergeStart').disabled = on;
    $('btnMergeTest').disabled = on;
    if (on) App.show('btnMergeStop'); else App.hide('btnMergeStop');
  }

  // ── SSE ─────────────────────────────────────────
  function connectSSE() {
    disconnectSSE();
    eventSource = new EventSource('/api/merge/progress');
    eventSource.onmessage = function (e) {
      try { handleEvent(JSON.parse(e.data)); } catch (err) { }
    };
    eventSource.onerror = function () {
      if (eventSource && eventSource.readyState === EventSource.CLOSED) checkStatus();
    };
  }
  function disconnectSSE() {
    if (eventSource) { eventSource.close(); eventSource = null; }
  }

  function handleEvent(event) {
    switch (event.type) {
      case 'started':
        setRunning(true);
        updateProgress(0, event.total, 0);
        if (event.out_dir) { lastOutDir = event.out_dir; }
        break;
      case 'progress':
        updateProgress(event.current, event.total, event.percent);
        break;
      case 'log':
        appendLog(event.message);
        break;
      case 'group_error':
        appendLog('[第 ' + event.index + ' 组失败] ' + event.error);
        break;
      case 'complete':
        setRunning(false);
        updateProgress(event.total, event.total, 100);
        if (event.out_dir) { lastOutDir = event.out_dir; }
        showResultBar(lastOutDir, (event.files || []).length);
        App.toast('合并完成！共输出 ' + event.files.length + ' 个文件到 ' + (lastOutDir || '输出目录'), 6000);
        disconnectSSE();
        break;
      case 'cancelled':
        setRunning(false);
        App.toast('合并已停止');
        disconnectSSE();
        break;
      case 'error':
        setRunning(false);
        App.toast('合并失败: ' + event.message, 4000);
        disconnectSSE();
        break;
      case 'heartbeat':
        break;
    }
  }

  // ── 输出目录展示与打开 ──────────────────
  function showResultBar(dir, count) {
    var bar = $('mergeResultBar');
    if (!bar) return;
    if (!dir) { App.hide('mergeResultBar'); return; }
    $('mergeResultDir').textContent = dir;
    $('mergeResultDir').title = dir;
    $('mergeResultCount').textContent = count > 0 ? ('共 ' + count + ' 个文件') : '';
    App.show('mergeResultBar');
  }

  function openDir(path) {
    if (!path) { App.toast('目录为空'); return; }
    fetch('/api/system/open_dir', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || '打开失败');
        return d;
      });
    }).catch(function (e) { App.toast(e.message, 3000); });
  }

  function openResultDir() { openDir(lastOutDir); }

  function openRootDir() {
    var dir = ($('mergeOutputDir').value || '').trim();
    if (dir) { openDir(dir); return; }
    // 输入框为空时用配置里的默认根目录
    fetch('/api/merge/output_dir').then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.root_dir) { openDir(d.root_dir); }
      else { App.toast('未配置输出根目录'); }
    }).catch(function () { App.toast('打开失败'); });
  }

  function updateProgress(current, total, percent) {
    $('mergeProgressBar').style.width = (percent || 0) + '%';
    $('mergeProgressText').textContent = current + '/' + total;
    $('mergeProgressPercent').textContent = (percent || 0) + '%';
  }

  function appendLog(msg) {
    var box = $('mergeLogBox');
    box.textContent += msg + '\n';
    box.scrollTop = box.scrollHeight;
  }

  // ── 页面刷新恢复 ────────────────────────────────────
  function checkStatus() {
    fetch('/api/merge/status').then(function (r) { return r.json(); }).then(function (d) {
      if (d.out_dir) { lastOutDir = d.out_dir; }
      if (d.status === 'running' || d.status === 'stopping') {
        App.show('mergeProgressSection');
        App.show('mergeLogSection');
        updateProgress(d.current, d.total, d.progress);
        $('mergeLogBox').textContent = (d.logs || []).join('\n');
        setRunning(true);
        connectSSE();
      } else if (d.status === 'done') {
        App.show('mergeLogSection');
        $('mergeLogBox').textContent = (d.logs || []).join('\n');
        showResultBar(d.out_dir, (d.files || []).length);
        setRunning(false);
      }
    }).catch(function () { });
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  document.addEventListener('DOMContentLoaded', init);

  return {
    refresh: refresh,
    selectAll: selectAll,
    updateCount: updateCount,
    onFileCheckChange: onFileCheckChange,
    selectTaskFiles: selectTaskFiles,
    preview: preview,
    start: start,
    stop: stop,
    applyConfig: applyConfig,
    checkStatus: checkStatus,
    openImagePicker: openImagePicker,
    closeImagePicker: closeImagePicker,
    clearImage: clearImage,
    openRootDir: openRootDir,
    openResultDir: openResultDir,
    openDir: openDir,
  };
})();
