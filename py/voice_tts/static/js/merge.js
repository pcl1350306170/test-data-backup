/* CosyVoice TTS Web — 音频合并（任务成品分组拼接） */
var Merge = (function () {
  var eventSource = null;
  var filesCache = [];      // /api/audio/list 结果
  var running = false;

  function $(id) { return document.getElementById(id); }

  // ── 初始化 ──────────────────────────────────────
  function init() {
    $('mergeTaskSelect').addEventListener('change', function () {
      if (this.value) selectTaskFiles(this.value);
      else updateCount();
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
      $(id).addEventListener('change', saveSettings);
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
    fetch('/api/audio/list').then(function (r) { return r.json(); }).then(function (data) {
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
        html += '<label class="fc-item"><input type="checkbox" value="' + esc(f.name) + '"' + c + ' onchange="Merge.updateCount()">' +
          '<span class="fc-name" title="' + esc(f.name) + '">' + esc(f.name) + '</span>' +
          '<span class="fc-meta">' + sizeStr + '</span></label>';
      });
      el.innerHTML = html;
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
    updateCount();
  }
  function updateCount() {
    $('mergeFileCount').textContent = '已选 ' + checkedBoxes().length + ' 个文件';
  }

  function selectTaskFiles(taskId) {
    fetch('/api/tasks/' + encodeURIComponent(taskId)).then(function (r) {
      if (!r.ok) throw new Error('任务不存在');
      return r.json();
    }).then(function (t) {
      var names = t.output_files || [];
      $('mergeFileList').querySelectorAll('input[type=checkbox]').forEach(function (b) {
        b.checked = names.indexOf(b.value) >= 0;
      });
      updateCount();
      if (!$('mergeSourceName').value.trim()) {
        $('mergeSourceName').value = t.name || '';
      }
      App.toast('已勾选任务「' + (t.name || t.id) + '」的 ' + names.length + ' 个成品');
    }).catch(function (e) { App.toast(e.message); });
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
    $('metaTitle').value = cfg.meta_title || '';
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
        App.toast('合并完成！共输出 ' + event.files.length + ' 个文件', 3000);
        disconnectSSE();
        App.loadAudioList();
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
    selectTaskFiles: selectTaskFiles,
    preview: preview,
    start: start,
    stop: stop,
    applyConfig: applyConfig,
    checkStatus: checkStatus,
    openImagePicker: openImagePicker,
    closeImagePicker: closeImagePicker,
    clearImage: clearImage,
  };
})();
