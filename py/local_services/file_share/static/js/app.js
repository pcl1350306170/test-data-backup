// 局域网共享文件 - 前端逻辑
'use strict';

function $(id) { return document.getElementById(id); }

var App = {
  files: [],
  uploadQueue: [],
  uploading: false,

  // ── 数据加载 ──────────────────────────────────────
  async load() {
    try {
      var res = await fetch('/api/files');
      var data = await res.json();
      this.files = data.files || [];
      this.renderTable();
      this.renderStats(data);
    } catch (e) {
      $('fileBody').innerHTML = '<tr class="empty-row"><td colspan="4">加载失败: ' + e + '</td></tr>';
    }
    this.loadInfo();
  },

  async loadInfo() {
    try {
      var res = await fetch('/api/info');
      var info = await res.json();
      $('dirInfo').textContent = '共享目录: ' + info.shared_dir;
      $('lanInfo').innerHTML =
        '本机访问: <b>http://127.0.0.1:' + info.port + '</b>' +
        ' 　局域网其他PC访问: <b>http://' + info.lan_ip + ':' + info.port + '</b>';
    } catch (e) { /* 忽略 */ }
  },

  renderStats(data) {
    $('stats').innerHTML =
      '<span>共 <b>' + data.files.length + '</b> 个文件</span>' +
      '<span>合计 <b>' + fmtSize(data.total_size) + '</b></span>';
  },

  renderTable() {
    var body = $('fileBody');
    if (!this.files.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="4">共享目录为空，上传文件后显示</td></tr>';
      return;
    }
    var html = '';
    for (var i = 0; i < this.files.length; i++) {
      var f = this.files[i];
      html += '<tr>' +
        '<td class="col-name" title="' + esc(f.name) + '">' + esc(f.name) + '</td>' +
        '<td class="col-size">' + fmtSize(f.size) + '</td>' +
        '<td class="col-time">' + fmtTime(f.mtime) + '</td>' +
        '<td class="col-ops">' +
          '<button class="btn btn-mini" onclick="App.download(' + i + ')">⬇ 下载</button>' +
          '<button class="btn btn-mini" onclick="App.rename(' + i + ')">✏ 重命名</button>' +
          '<button class="btn btn-mini btn-danger" onclick="App.remove(' + i + ')">🗑 删除</button>' +
        '</td></tr>';
    }
    body.innerHTML = html;
  },

  // ── 下载 / 重命名 / 删除 ──────────────────────────
  download(i) {
    var a = document.createElement('a');
    a.href = '/api/download?name=' + encodeURIComponent(this.files[i].name);
    a.download = this.files[i].name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  },

  async rename(i) {
    var f = this.files[i];
    var newName = prompt('重命名（不改变所在目录）:', f.name);
    if (!newName || newName === f.name) return;
    var res = await fetch('/api/rename', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: f.name, new_name: newName.trim() })
    });
    var data = await res.json();
    if (!res.ok) { alert(data.detail || '重命名失败'); return; }
    this.load();
  },

  async remove(i) {
    var f = this.files[i];
    if (!confirm('确认删除「' + f.name + '」？（' + fmtSize(f.size) + '，不可恢复）')) return;
    var res = await fetch('/api/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: f.name })
    });
    if (!res.ok) {
      var data = await res.json();
      alert(data.detail || '删除失败');
      return;
    }
    this.load();
  },

  // ── 上传（队列逐个直传，带进度条） ────────────────
  enqueue(fileList) {
    for (var i = 0; i < fileList.length; i++) {
      this.uploadQueue.push(fileList[i]);
      this.renderProgress(fileList[i], 'queued');
    }
    this.pump();
  },

  async pump() {
    if (this.uploading || !this.uploadQueue.length) return;
    this.uploading = true;
    while (this.uploadQueue.length) {
      var file = this.uploadQueue.shift();
      try {
        await this.uploadOne(file);
        this.renderProgress(file, 'done');
      } catch (e) {
        this.renderProgress(file, 'fail', String(e));
      }
    }
    this.uploading = false;
    this.load();
    setTimeout(function () { clearDoneProgress(); }, 4000);
  },

  uploadOne(file) {
    var self = this;
    return new Promise(function (resolve, reject) {
      var fd = new FormData();
      fd.append('file', file);
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload');
      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          var data = JSON.parse(xhr.responseText);
          if (data.name !== file.name) {
            self.renderProgress(file, 'renamed', data.name);
          }
          resolve(data);
        } else {
          var detail = 'HTTP ' + xhr.status;
          try { detail = JSON.parse(xhr.responseText).detail || detail; } catch (e) {}
          reject(new Error(detail));
        }
      };
      xhr.onerror = function () { reject(new Error('网络错误')); };
      xhr.upload.onprogress = function (ev) {
        if (ev.lengthComputable) {
          self.renderProgress(file, 'uploading', null, ev.loaded / ev.total);
        }
      };
      xhr.send(fd);
    });
  },

  renderProgress(file, state, extra, ratio) {
    var list = $('progressList');
    var key = 'p_' + file.name.replace(/[^\w]/g, '_');
    var row = document.getElementById(key);
    if (!row) {
      row = document.createElement('div');
      row.className = 'progress-row';
      row.id = key;
      row.innerHTML = '<span class="pf-name">' + esc(file.name) + '</span>' +
        '<span class="pf-size">' + fmtSize(file.size) + '</span>' +
        '<div class="pf-bar"><div class="pf-fill"></div></div>' +
        '<span class="pf-state">排队中</span>';
      list.appendChild(row);
    }
    var fill = row.querySelector('.pf-fill');
    var stateEl = row.querySelector('.pf-state');
    if (state === 'uploading') {
      fill.style.width = Math.round(ratio * 100) + '%';
      stateEl.textContent = Math.round(ratio * 100) + '%';
    } else if (state === 'done') {
      fill.style.width = '100%';
      stateEl.textContent = '✅ 完成';
    } else if (state === 'renamed') {
      fill.style.width = '100%';
      stateEl.textContent = '✅ 已存为 ' + extra;
    } else if (state === 'fail') {
      fill.style.width = '100%';
      fill.classList.add('pf-fail');
      stateEl.textContent = '❌ ' + extra;
    }
  },

  // ── 夜间模式 ──────────────────────────────────────
  initTheme() {
    var btn = $('themeToggle');
    if (localStorage.getItem('fs-theme') === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      btn.textContent = '☀️';
    }
    btn.addEventListener('click', function () {
      var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        btn.textContent = '🌙';
        localStorage.setItem('fs-theme', 'light');
      } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        btn.textContent = '☀️';
        localStorage.setItem('fs-theme', 'dark');
      }
    });
  },
};

function clearDoneProgress() {
  var list = $('progressList');
  var rows = list.querySelectorAll('.progress-row');
  for (var i = 0; i < rows.length; i++) {
    var s = rows[i].querySelector('.pf-state').textContent;
    if (s.indexOf('✅') === 0) rows[i].remove();
  }
}

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtSize(n) {
  if (n == null) return '-';
  var units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n >= 100 ? 0 : 1)) + ' ' + units[i];
}

function fmtTime(ts) {
  var d = new Date(ts * 1000);
  function pad(x) { return x < 10 ? '0' + x : x; }
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

// ── 初始化 ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  App.initTheme();
  App.load();

  $('fileInput').addEventListener('change', function () {
    if (this.files.length) { App.enqueue(this.files); this.value = ''; }
  });

  var zone = $('dropZone');
  ['dragenter', 'dragover'].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault(); e.stopPropagation();
      zone.classList.add('dragging');
    });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault(); e.stopPropagation();
      zone.classList.remove('dragging');
    });
  });
  zone.addEventListener('drop', function (e) {
    if (e.dataTransfer && e.dataTransfer.files.length) {
      App.enqueue(e.dataTransfer.files);
    }
  });
});
