/* 门诊前端升级 — 升级页签交互（对应桌面版 门诊升级.pyw 的前端升级页）
   服务器凭据共用 testServer.json；凭据自愈（验证→默认密码轮试→手动输入）在后端 /api/upgrade/auth。
   工具函数与通知复用 App.upgradeApi()，本文件只管升级面板自己的状态。 */
var Up = (function () {
  var api = null;
  var servers = [];
  var dirs = [];
  var zips = [];          // 待升级列表 [{path, name, size_str, checked}]
  var histRecords = [];
  var histSel = -1;
  var busy = false;
  var starting = false;   // 凭据验证中（尚未真正开跑）
  var stream = null;
  var inited = false;

  function $(id) { return document.getElementById(id); }

  // ── 服务器 ────────────────────────────────────────
  function currentHost() {
    var sel = $('upServerSelect');
    return sel.value === '__manual__' ? api.val('upHostManual') : sel.value;
  }

  function loadServers() {
    return api.req('GET', '/api/upgrade/servers').then(function (res) {
      if (!res.ok) { api.toast('读取服务器列表失败'); return; }
      servers = res.data.servers || [];
      var last = res.data.last_server || '';
      var html = servers.map(function (s) {
        return '<option value="' + api.esc(s.host) + '">' + api.esc(s.host) +
          '（' + api.esc(s.name) + '）</option>';
      }).join('');
      html += '<option value="__manual__">手动输入…</option>';
      $('upServerSelect').innerHTML = html;
      if (last && servers.some(function (s) { return s.host === last; })) {
        $('upServerSelect').value = last;
      } else if (servers.length) {
        $('upServerSelect').value = servers[0].host;
      } else {
        $('upServerSelect').value = '__manual__';
      }
      onServerChange();
    });
  }

  function onServerChange() {
    var manual = $('upServerSelect').value === '__manual__';
    $('upHostManualRow').style.display = manual ? '' : 'none';
    if (manual) return;
    var host = $('upServerSelect').value;
    for (var i = 0; i < servers.length; i++) {
      if (servers[i].host === host) {
        $('upUsername').value = servers[i].name || 'root';
        $('upPassword').value = servers[i].password || '';
        return;
      }
    }
  }

  function selectServer(host, username) {
    var sel = $('upServerSelect');
    var found = false;
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === host) { found = true; break; }
    }
    if (found) {
      sel.value = host;
      onServerChange();
    } else {
      sel.value = '__manual__';
      onServerChange();
      $('upHostManual').value = host;
    }
    if (username) $('upUsername').value = username;
  }

  function saveServer() {
    var host = currentHost();
    var password = api.val('upPassword');
    if (!host || !password) { api.toast('请填写服务器地址和密码'); return; }
    api.req('POST', '/api/upgrade/server/save', {
      host: host, username: api.val('upUsername') || 'root', password: password
    }).then(function (res) {
      if (!res.ok) { api.toast(api.detailOf(res).message || '保存失败'); return; }
      api.toast('已保存到 testServer.json（桌面版共用）');
      loadServers().then(function () { selectServer(host); });
    });
  }

  // ── 搜索目录 / 列 ZIP ─────────────────────────────
  function doSearch() {
    var keyword = api.val('upKeyword');
    if (!keyword) { api.toast('请输入关键字'); return; }
    setErrors([]);
    $('btnUpSearch').disabled = true;
    api.req('POST', '/api/upgrade/search', {keyword: keyword}).then(function (res) {
      $('btnUpSearch').disabled = false;
      if (!res.ok) { api.toast(api.detailOf(res).message || '搜索失败'); return; }
      var d = res.data;
      dirs = d.dirs || [];
      $('upDirCount').textContent = dirs.length ? dirs.length + ' 个' : '';
      $('upDirList').innerHTML = dirs.length ? dirs.map(function (x, i) {
        return '<li data-d="' + i + '"><div class="name">' + api.esc(x.name) +
          '</div><div class="sub">更新 ' + api.esc(x.mtime_str) + '</div></li>';
      }).join('') : '<li class="empty">无匹配目录</li>';
      if (d.notice) { setNotice(d.notice); return; }
      // 自动选中最新目录（后端已按 mtime 倒序），与桌面版一致
      var first = $('upDirList').querySelector('li[data-d="0"]');
      if (first) api.selectLi('upDirList', first);
      setNotice('已自动选中最新目录：' + (dirs[0] ? dirs[0].name : ''));
      setZips(d.zips || []);
    }).catch(function (e) {
      $('btnUpSearch').disabled = false;
      api.toast('搜索请求异常：' + e);
    });
  }

  function loadDirZips(path) {
    api.req('POST', '/api/upgrade/search', {dir: path}).then(function (res) {
      if (!res.ok) { api.toast(api.detailOf(res).message || '读取目录失败'); return; }
      setZips(res.data.zips || []);
      setNotice(res.data.total ? '' : '该目录下未找到 YM-801S-*.zip');
    });
  }

  // ── 待升级 ZIP 列表（勾选多选）────────────────────
  function setZips(list) {
    zips = list.map(function (z) {
      return {path: z.path, name: z.name,
              size_str: z.size_str || '', checked: true};
    });
    // 只有一个包时不用再挑，直接保持全选
    renderZips();
  }

  function addZip(path) {
    path = (path || '').trim().replace(/^"|"$/g, '');
    if (!path) { api.toast('请先填写或选择 ZIP 路径'); return; }
    if (!/\.zip$/i.test(path)) { api.toast('只支持 .zip 文件'); return; }
    for (var i = 0; i < zips.length; i++) {
      if (zips[i].path.toLowerCase() === path.toLowerCase()) {
        zips[i].checked = true;
        renderZips();
        api.toast('已在待升级列表中：' + zips[i].name);
        return;
      }
    }
    zips.push({path: path, name: path.replace(/[\\/]+$/, '').split(/[\\/]/).pop(),
               size_str: '', checked: true});
    renderZips();
    setNotice('已添加：' + zips[zips.length - 1].name);
  }

  // 打包页「升级此包」入口：切页签 + 把成品加进列表
  function addPackage(path) {
    api.switchTab('upgrade');
    addZip(path);
  }

  function renderZips() {
    var checked = zips.filter(function (z) { return z.checked; }).length;
    $('upZipCount').textContent = zips.length ? checked + ' / ' + zips.length : '';
    $('upZipList').innerHTML = zips.length ? zips.map(function (z, i) {
      return '<li class="zip-item" data-z="' + i + '" title="' + api.esc(z.path) + '">' +
        '<input type="checkbox" data-c="' + i + '"' + (z.checked ? ' checked' : '') + '>' +
        '<div class="zip-info"><div class="name">' + api.esc(z.name) + '</div>' +
        (z.size_str ? '<div class="sub">' + api.esc(z.size_str) + '</div>' : '') +
        '</div><button class="mini" data-x="' + i + '" title="移除">✕</button></li>';
    }).join('') : '<li class="empty">搜索目录后点选 ZIP，或直接指定文件</li>';
  }

  function checkedZips() {
    return zips.filter(function (z) { return z.checked; }).map(function (z) { return z.path; });
  }

  // ── 升级流程：验证凭据 → 启动任务 ─────────────────
  function setErrors(list) {
    $('upErrors').innerHTML = (list || []).map(function (e) {
      return '<div>• ' + api.esc(e) + '</div>';
    }).join('');
  }

  function setNotice(text) { $('upNotices').textContent = text || ''; }

  function setBusy(flag, status) {
    busy = flag;
    $('btnUpStart').disabled = flag || starting;
    $('btnUpStop').disabled = !flag;
    api.setStatus(status || 'idle');
    if (!flag) {
      $('upProgressWrap').hidden = true;
      $('upProgressBar').style.width = '0';
    }
  }

  function authHint(text) { $('upAuthHint').textContent = text || ''; }

  function start() {
    if (busy || starting) { api.toast('已有升级任务在跑'); return; }
    var host = currentHost();
    if (!host) { api.toast('请选择或输入服务器地址'); return; }
    var paths = checkedZips();
    if (!paths.length) { setErrors(['请先勾选要升级的 ZIP 包']); return; }
    api.askSysNotifyOnStart();
    setErrors([]);
    setNotice('');
    starting = true;
    $('btnUpStart').disabled = true;
    authHint('🔑 正在验证服务器凭据…（旧密码失效会自动轮试默认凭据）');
    api.req('POST', '/api/upgrade/auth', {
      host: host, username: api.val('upUsername'), password: $('upPassword').value.trim()
    }).then(function (res) {
      var d = res.ok ? res.data : {status: 'error', message: api.detailOf(res).message || ('验证请求失败（' + res.status + '）')};
      if (d.status === 'ok') {
        $('upUsername').value = d.username || 'root';
        $('upPassword').value = d.password || '';
        authHint('✅ 凭据已验证');
        // 轮试出的新凭据同步回下拉数据，避免再选一次又填回旧密码
        loadServers().then(function () { selectServer(d.host, d.username); doStart(d, paths); });
        return;
      }
      starting = false;
      $('btnUpStart').disabled = false;
      if (d.status === 'need_password' || d.status === 'auth_failed') {
        $('upPassword').value = '';
        $('upPassword').focus();
        authHint('⚠️ ' + (d.message || '请输入新密码后重试'));
        setErrors([d.message || '密码认证失败，请输入新密码']);
      } else {
        authHint('');
        setErrors([d.message || '凭据验证失败']);
      }
    }).catch(function (e) {
      starting = false;
      $('btnUpStart').disabled = false;
      authHint('');
      setErrors(['凭据验证请求异常：' + e]);
    });
  }

  function doStart(creds, paths) {
    api.req('POST', '/api/upgrade/start', {
      host: creds.host, username: creds.username, password: creds.password, zip_paths: paths
    }).then(function (res) {
      starting = false;
      if (!res.ok) {
        $('btnUpStart').disabled = false;
        var d = api.detailOf(res);
        setErrors(d.errors.length ? d.errors : [d.message || '任务未能启动']);
        return;
      }
      $('upProgressText').textContent = '';
      setBusy(true, 'running');
      clearLog();
    }).catch(function (e) {
      starting = false;
      $('btnUpStart').disabled = false;
      setErrors(['启动请求异常：' + e]);
    });
  }

  function stop() {
    api.req('POST', '/api/upgrade/stop').then(function (res) {
      if (!res.ok) api.toast(api.detailOf(res).message || '停止失败');
    });
  }

  // ── SSE ───────────────────────────────────────────
  function openStream() {
    closeStream();
    stream = new EventSource('/api/upgrade/progress');
    stream.onmessage = function (e) {
      try { handleEvent(JSON.parse(e.data)); } catch (err) { }
    };
    stream.onerror = function () {
      if (stream && stream.readyState === EventSource.CLOSED) setTimeout(openStream, 3000);
    };
  }

  function closeStream() {
    if (stream) { stream.close(); stream = null; }
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case 'init':
        var st = ev.status || {};
        renderSnapshot(st.logs || []);
        busy = !!st.busy;
        setBusy(busy, st.status || 'idle');
        if (st.stage && st.stage.name) setNotice('当前阶段：' + st.stage.name);
        break;
      case 'start':
        clearLog();
        setBusy(true, 'running');
        break;
      case 'stage':
        if (ev.stage) setNotice('阶段 ' + (ev.stage.index || '') + '/' + (ev.stage.total || '') + '：' + ev.stage.name);
        break;
      case 'log':
        appendLog(ev.line);
        break;
      case 'progress':
        $('upProgressWrap').hidden = false;
        $('upProgressBar').style.width = (ev.percent || 0) + '%';
        $('upProgressText').textContent = '上传 ' + (ev.index || '') + '/' + (ev.total || '') +
          '：' + (ev.file || '') + ' ' + (ev.percent || 0) + '%';
        break;
      case 'status':
        api.setStatus(ev.status);
        break;
      case 'complete':
        setBusy(false, 'done');
        setNotice('升级完成，用时 ' + (ev.elapsed || 0) + 's');
        api.notifyDone(ev.result || {}, {title: '✅ 升级完成'});
        loadHistory();
        break;
      case 'error':
        setErrors([ev.error]);
        setBusy(false, 'error');
        break;
      case 'stopped':
        setBusy(false, 'stopped');
        break;
      case 'finish':
        closeStream();
        setTimeout(openStream, 600);   // 重开以接收下一次任务的 init 快照
        break;
      default:
        break;
    }
  }

  // ── 日志 ──────────────────────────────────────────
  function appendLog(line) {
    var box = $('upLog');
    var span = document.createElement('span');
    var cls = api.logClass(line);
    if (cls) span.className = cls;
    span.textContent = line + '\n';
    box.appendChild(span);
    while (box.childNodes.length > 2000) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }

  function renderSnapshot(lines) {
    $('upLog').innerHTML = '';
    lines.forEach(appendLog);
  }

  function clearLog() { $('upLog').innerHTML = ''; }

  // ── 历史 ──────────────────────────────────────────
  function loadHistory() {
    api.req('GET', '/api/upgrade/history').then(function (res) {
      if (!res.ok) return;
      histRecords = res.data.records || [];
      $('upHistCount').textContent = histRecords.length + ' 条';
      $('upHistoryList').innerHTML = histRecords.length ? histRecords.map(function (r, i) {
        return '<li data-h="' + i + '"><div class="name">' + api.esc(r.server || '') +
          (r.svn_dir ? ' [' + api.esc(r.svn_dir) + ']' : '') + '</div>' +
          '<div class="sub">' + api.esc(r.timestamp || '') + '</div>' +
          '<div class="sub">' + api.esc(r.zip_names || '') + '</div></li>';
      }).join('') : '<li class="empty">暂无记录</li>';
    });
  }

  function applyHistory() {
    if (histSel < 0 || !histRecords[histSel]) { api.toast('先点击选中一条历史记录'); return; }
    var r = histRecords[histSel];
    selectServer(r.server || '', r.username);
    var paths = r.zip_paths || [];
    zips = paths.map(function (p) {
      return {path: p, name: p.replace(/[\\/]+$/, '').split(/[\\/]/).pop(),
              size_str: '', checked: true};
    });
    renderZips();
    setNotice('已回填升级历史：' + (r.timestamp || '') + '（文件若已被移动/删除，启动时会提示）');
  }

  function deleteHistory() {
    if (histSel < 0) { api.toast('先选中一条记录'); return; }
    api.req('DELETE', '/api/upgrade/history?index=' + histSel).then(function (res) {
      if (!res.ok) { api.toast(api.detailOf(res).message || '删除失败'); return; }
      histSel = -1;
      loadHistory();
    });
  }

  // ── 绑定 / 初始化 ─────────────────────────────────
  function bind() {
    $('upServerSelect').addEventListener('change', onServerChange);
    $('btnUpSaveServer').addEventListener('click', saveServer);
    $('btnUpSearch').addEventListener('click', doSearch);
    $('upKeyword').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(); });
    $('btnUpAddZip').addEventListener('click', function () {
      addZip(api.val('upZipManual'));
      $('upZipManual').value = '';
    });
    $('upZipManual').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { addZip(api.val('upZipManual')); $('upZipManual').value = ''; }
    });
    $('upDirList').addEventListener('click', function (e) {
      var li = api.closestLI(e.target);
      if (!li || !li.hasAttribute('data-d')) return;
      var item = dirs[+li.getAttribute('data-d')];
      if (!item) return;
      api.selectLi('upDirList', li);
      loadDirZips(item.path);
    });
    $('upZipList').addEventListener('click', function (e) {
      var t = e.target;
      if (t.tagName === 'INPUT' && t.hasAttribute('data-c')) {
        zips[+t.getAttribute('data-c')].checked = t.checked;
        renderZips();
        return;
      }
      var btn = t.closest ? t.closest('button[data-x]') : null;
      if (btn) {
        zips.splice(+btn.getAttribute('data-x'), 1);
        renderZips();
        setNotice('');
      }
    });
    $('btnUpStart').addEventListener('click', start);
    $('btnUpStop').addEventListener('click', stop);
    $('btnUpClearLog').addEventListener('click', clearLog);
    $('upHistoryList').addEventListener('click', function (e) {
      var li = e.target.closest ? e.target.closest('li[data-h]') : null;
      if (!li) return;
      histSel = +li.getAttribute('data-h');
      api.selectLi('upHistoryList', li);
    });
    $('btnUpHistApply').addEventListener('click', applyHistory);
    $('btnUpHistDelete').addEventListener('click', deleteHistory);
  }

  function init() {
    if (inited) return;   // App.init 可能被重复调用，避免叠加监听器
    inited = true;
    api = App.upgradeApi();
    bind();
    loadServers();
    loadHistory();
    openStream();
  }

  return {init: init, start: start, addZip: addZip, addPackage: addPackage};
})();

document.addEventListener('DOMContentLoaded', Up.init);