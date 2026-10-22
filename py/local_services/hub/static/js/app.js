/* 本地服务大厅前端：状态轮询 + 一键启停 + 日志查看 */
var Hub = (function () {
  var services = [];
  var logSid = null;
  var timer = null;
  var pendingStart = {};   // sid -> t0，统计启动耗时
  var lanIps = [];
  var modalSid = null;
  var modalMode = 'log';   // log | check

  var STATUS_LABELS = {
    running: '● Hub 启动中',
    external: '● 外部启动',
    unresponsive: '● 无响应',
    stopped: '○ 未运行',
  };

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(msg, ms) {
    var t = $('toast');
    t.textContent = msg;
    t.style.display = 'block';
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.style.display = 'none'; }, ms || 2500);
  }

  // 服务地址用当前页面的 host 拼，手机/其他电脑访问时点开也是局域网地址
  function svcUrl(s) {
    var scheme = s.scheme || 'http';
    return scheme + '://' + location.hostname + ':' + s.port + '/';
  }

  // 只有从 Hub 所在机器访问时，“打开目录”才有意义
  function isLocal() {
    var h = location.hostname;
    return h === 'localhost' || h === '127.0.0.1' || lanIps.indexOf(h) >= 0;
  }

  function fmtUptime(startedAt) {
    var t = new Date(String(startedAt).replace(' ', 'T'));
    if (isNaN(t.getTime())) return '';
    var m = Math.floor((Date.now() - t.getTime()) / 60000);
    if (m < 1) return '<1分钟';
    if (m < 60) return m + '分钟';
    return Math.floor(m / 60) + '小时' + (m % 60 ? ' ' + (m % 60) + '分' : '');
  }

  function loadHubInfo() {
    fetch('/api/hub/info').then(function (r) { return r.json(); }).then(function (d) {
      lanIps = d.lan_ips || [];
      var el = $('hubAddr');
      if (lanIps.length) {
        var url = 'http://' + lanIps[0] + ':' + d.port;
        el.innerHTML = '手机/其他设备访问：<a href="' + url + '" target="_blank">' + url + '</a>';
      }
    }).catch(function () { });
  }

  function load() {
    fetch('/api/services').then(function (r) { return r.json(); }).then(function (d) {
      services = d.services || [];
      services.forEach(function (s) {
        if (pendingStart[s.id] && s.status === 'running') {
          toast(s.name + ' 启动成功，用时 ' + ((Date.now() - pendingStart[s.id]) / 1000).toFixed(1) + 's');
          delete pendingStart[s.id];
        } else if (pendingStart[s.id] && s.status === 'stopped'
                   && Date.now() - pendingStart[s.id] > 15000) {
          toast(s.name + ' 未能启动，请查看日志', 4000);
          delete pendingStart[s.id];
        }
      });
      render();
    }).catch(function () { });
  }

  function render() {
    var html = '';
    services.forEach(function (s) {
      html += '<div class="svc-card">';
      html += '<div class="svc-head"><span class="svc-icon">' + s.icon + '</span>' +
        '<span class="svc-name">' + esc(s.name) + '</span>' +
        '<span class="status-chip ' + s.status + '">' + (STATUS_LABELS[s.status] || s.status) + '</span></div>';
      html += '<div class="svc-desc">' + esc(s.desc) + '</div>';
      html += '<div class="svc-meta">端口 ' + s.port;
      if (s.started_at) {
        html += ' · ' + (s.claimed ? '接管于 ' : '启动于 ') + esc(s.started_at);
        var up = fmtUptime(s.started_at);
        if (up) html += ' · 已运行 ' + up;
      }
      if (s.pid) html += ' · PID ' + s.pid;
      html += '</div>';
      html += '<div class="svc-meta">' + esc(s.path) + '</div>';

      html += '<div class="svc-actions">';
      if (s.status === 'stopped') {
        html += '<button class="btn btn-primary" onclick="Hub.start(\'' + s.id + '\')">▶ 启动</button>';
      } else {
        html += '<a class="btn btn-primary" href="' + svcUrl(s) + '" target="_blank">↗ 打开</a>';
        if (s.status === 'running') {
          html += '<button class="btn btn-danger" onclick="Hub.stop(\'' + s.id + '\')">⏹ 停止</button>';
          html += '<button class="btn" onclick="Hub.showLog(\'' + s.id + '\')">📜 日志</button>';
        } else if (s.status === 'external') {
          html += '<button class="btn" onclick="Hub.claim(\'' + s.id + '\')">🙋 接管</button>';
        } else if (s.status === 'unresponsive') {
          html += '<button class="btn btn-danger" onclick="Hub.stop(\'' + s.id + '\')">⏹ 强停</button>';
        }
      }
      html += '<button class="btn" onclick="Hub.runCheck(\'' + s.id + '\')">🔧 自检</button>';
      if (isLocal()) html += '<button class="btn" onclick="Hub.openFolder(\'' + s.id + '\')">📁</button>';
      html += '</div></div>';
    });
    $('cardGrid').innerHTML = html || '<div class="svc-desc">注册表为空</div>';
  }

  function start(sid) {
    pendingStart[sid] = Date.now();
    doStart(sid, false);
    setTimeout(load, 4000);
    setTimeout(load, 9000);
  }

  function doStart(sid, force) {
    toast('启动中，首次拉起约需几秒…');
    fetch('/api/services/' + sid + '/start?force=' + (force ? 1 : 0), { method: 'POST' })
      .then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, d: d }; });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.d.detail || '启动失败');
        if (res.d.need_confirm) {
          delete pendingStart[sid];
          var bad = res.d.checks.filter(function (c) { return !c.ok; });
          var msg = '预检未通过：\n' + bad.map(function (c) {
            return '❌ ' + c.label + ' — ' + c.detail;
          }).join('\n') + '\n\n仍要启动吗？';
          if (confirm(msg)) { pendingStart[sid] = Date.now(); doStart(sid, true); }
        }
        setTimeout(load, 1200);
      }).catch(function (e) {
        delete pendingStart[sid];
        toast(e.message, 3500);
        load();
      });
  }

  function stop(sid) {
    if (!confirm('确定停止该服务？未保存的任务会中断。')) return;
    fetch('/api/services/' + sid + '/stop', { method: 'POST' }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (res) {
      if (!res.ok) throw new Error(res.d.detail || '停止失败');
      setTimeout(load, 1200);
    }).catch(function (e) { toast(e.message, 3500); load(); });
  }

  function claim(sid) {
    var s = services.filter(function (x) { return x.id === sid; })[0];
    if (!confirm('接管后 Hub 将管理该进程（端口 ' + (s ? s.port : '?') + ' 的监听进程），可一键停止。\n注意：停止会连同其控制台窗口一起关闭。确认接管？')) return;
    fetch('/api/services/' + sid + '/claim', { method: 'POST' }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (res) {
      if (!res.ok) throw new Error(res.d.detail || '接管失败');
      toast('已接管 PID ' + res.d.pid);
      load();
    }).catch(function (e) { toast(e.message, 3500); });
  }

  function openFolder(sid) {
    fetch('/api/services/' + sid + '/open_folder', { method: 'POST' })
      .catch(function (e) { toast('打开失败: ' + e.message, 3000); });
  }

  function runCheck(sid) {
    var s = services.filter(function (x) { return x.id === sid; })[0];
    fetch('/api/services/' + sid + '/check').then(function (r) { return r.json(); })
      .then(function (d) {
        modalMode = 'check'; modalSid = sid;
        $('logModalTitle').textContent = '依赖自检 — ' + (s ? s.name : sid);
        $('logBox').textContent = d.checks.length
          ? d.checks.map(function (c) {
              return (c.ok ? '✅' : '❌') + ' ' + c.label + '\n    ' + c.detail;
            }).join('\n')
          : '该服务未配置检查项';
        $('logModal').style.display = 'flex';
      }).catch(function () { });
  }

  function exportFL() {
    fetch('/api/hub/export/quickfolder').then(function (r) { return r.json(); })
      .then(function (d) {
        var text = JSON.stringify(d.entries, null, 4);
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            toast('QuickFolderOpen 配置片段已复制到剪贴板');
          }).catch(function () { showExportFallback(text); });
        } else { showExportFallback(text); }
      }).catch(function () { });
  }

  function showExportFallback(text) {
    modalMode = 'check'; modalSid = null;
    $('logModalTitle').textContent = 'QuickFolderOpen 配置片段（手动复制）';
    $('logBox').textContent = text;
    $('logModal').style.display = 'flex';
  }

  function showLog(sid) {
    modalMode = 'log'; modalSid = sid; logSid = sid;
    var s = services.filter(function (x) { return x.id === sid; })[0];
    $('logModalTitle').textContent = '运行日志 — ' + (s ? s.name : sid);
    $('logModal').style.display = 'flex';
    refreshLog();
  }

  function refreshLog() {
    if (modalMode !== 'log' || !modalSid) return;
    fetch('/api/services/' + modalSid + '/log?tail=300').then(function (r) { return r.json(); })
      .then(function (d) {
        var box = $('logBox');
        box.textContent = d.text || '(暂无日志)';
        box.scrollTop = box.scrollHeight;
      }).catch(function () { });
  }

  function closeLog() {
    modalSid = null; logSid = null;
    $('logModal').style.display = 'none';
  }

  // ── 夜间模式 ──────────────────────────────────────
  function initTheme() {
    var saved = localStorage.getItem('hub-theme');
    var btn = $('themeToggle');
    if (saved === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      btn.textContent = '☀️';
      btn.title = '切换日间模式';
    }
    btn.addEventListener('click', toggleTheme);
  }

  function toggleTheme() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var btn = $('themeToggle');
    if (isDark) {
      document.documentElement.removeAttribute('data-theme');
      btn.textContent = '🌙';
      btn.title = '切换夜间模式';
      localStorage.setItem('hub-theme', 'light');
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
      btn.textContent = '☀️';
      btn.title = '切换日间模式';
      localStorage.setItem('hub-theme', 'dark');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    loadHubInfo();
    load();
    timer = setInterval(load, 5000);
  });

  return {
    start: start, stop: stop, claim: claim, openFolder: openFolder,
    runCheck: runCheck, exportFL: exportFL,
    showLog: showLog, refreshLog: refreshLog, closeLog: closeLog,
  };
})();
