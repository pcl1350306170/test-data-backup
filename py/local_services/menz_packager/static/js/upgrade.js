/* 门诊升级页签交互 — 前端升级（zip / publish_front.sh）与服务端升级（war / publish_server.sh）
   对应桌面版 门诊升级.pyw 的两个升级页。两者逻辑同构，抽成 createUpgradeController 工厂，
   差异（API 前缀 / 元素 id / 文件类型 / 历史字段 / 通知标题）由 opts 传入：
     Up = 前端升级（沿用原 up* id，行为不变）；Sv = 服务端升级（sv* id）。
   服务器凭据共用 testServer.json；凭据自愈（验证→默认密码轮试→手动输入）在后端 /auth。
   工具函数与通知复用 App.upgradeApi()，本文件只管升级面板自己的状态。 */
function createUpgradeController(opts) {
  var api = null;
  var servers = [];
  var dirs = [];
  var files = [];         // 待升级列表 [{path, name, size_str, checked}]
  var histRecords = [];
  var histSel = -1;
  var busy = false;
  var starting = false;   // 凭据验证中（尚未真正开跑）
  var stream = null;
  var inited = false;
  var ids = opts.ids;
  var extRe = new RegExp(opts.fileExt.replace(/\./g, '\\.') + '$', 'i');

  function $(id) { return document.getElementById(id); }
  function el(key) { return $(ids[key]); }

  // ── 服务器 ────────────────────────────────────────
  function currentHost() {
    var sel = el('serverSelect');
    return sel.value === '__manual__' ? api.val(ids.hostManual) : sel.value;
  }

  function loadServers() {
    return api.req('GET', opts.apiPrefix + '/servers').then(function (res) {
      if (!res.ok) { api.toast('读取服务器列表失败'); return; }
      servers = res.data.servers || [];
      var last = res.data.last_server || '';
      var html = servers.map(function (s) {
        return '<option value="' + api.esc(s.host) + '">' + api.esc(s.host) +
          '（' + api.esc(s.name) + '）</option>';
      }).join('');
      html += '<option value="__manual__">手动输入…</option>';
      el('serverSelect').innerHTML = html;
      if (last && servers.some(function (s) { return s.host === last; })) {
        el('serverSelect').value = last;
      } else if (servers.length) {
        el('serverSelect').value = servers[0].host;
      } else {
        el('serverSelect').value = '__manual__';
      }
      onServerChange();
    });
  }

  function onServerChange() {
    var manual = el('serverSelect').value === '__manual__';
    el('hostManualRow').style.display = manual ? '' : 'none';
    if (manual) return;
    var host = el('serverSelect').value;
    for (var i = 0; i < servers.length; i++) {
      if (servers[i].host === host) {
        el('username').value = servers[i].name || 'root';
        el('password').value = servers[i].password || '';
        return;
      }
    }
  }

  function selectServer(host, username) {
    var sel = el('serverSelect');
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
      el('hostManual').value = host;
    }
    if (username) el('username').value = username;
  }

  function saveServer() {
    var host = currentHost();
    var password = api.val(ids.password);
    if (!host || !password) { api.toast('请填写服务器地址和密码'); return; }
    api.req('POST', opts.apiPrefix + '/server/save', {
      host: host, username: api.val(ids.username) || 'root', password: password
    }).then(function (res) {
      if (!res.ok) { api.toast(api.detailOf(res).message || '保存失败'); return; }
      api.toast('已保存到 testServer.json（桌面版共用）');
      loadServers().then(function () { selectServer(host); });
    });
  }

  // ── 搜索目录 / 列包 ───────────────────────────────
  function doSearch() {
    var keyword = api.val(ids.keyword);
    if (!keyword) { api.toast('请输入关键字'); return; }
    setErrors([]);
    el('btnSearch').disabled = true;
    api.req('POST', opts.apiPrefix + '/search', {keyword: keyword}).then(function (res) {
      el('btnSearch').disabled = false;
      if (!res.ok) { api.toast(api.detailOf(res).message || '搜索失败'); return; }
      var d = res.data;
      dirs = d.dirs || [];
      el('dirCount').textContent = dirs.length ? dirs.length + ' 个' : '';
      el('dirList').innerHTML = dirs.length ? dirs.map(function (x, i) {
        return '<li data-d="' + i + '"><div class="name">' + api.esc(x.name) +
          '</div><div class="sub">更新 ' + api.esc(x.mtime_str) + '</div></li>';
      }).join('') : '<li class="empty">无匹配目录</li>';
      if (d.notice) { setNotice(d.notice); return; }
      // 自动选中最新目录（后端已按 mtime 倒序），与桌面版一致
      var first = el('dirList').querySelector('li[data-d="0"]');
      if (first) api.selectLi(ids.dirList, first);
      setNotice('已自动选中最新目录：' + (dirs[0] ? dirs[0].name : ''));
      setFiles(d[opts.searchKey] || []);
    }).catch(function (e) {
      el('btnSearch').disabled = false;
      api.toast('搜索请求异常：' + e);
    });
  }

  function loadDirFiles(path) {
    api.req('POST', opts.apiPrefix + '/search', {dir: path}).then(function (res) {
      if (!res.ok) { api.toast(api.detailOf(res).message || '读取目录失败'); return; }
      setFiles(res.data[opts.searchKey] || []);
      setNotice(res.data.total ? '' : '该目录下未找到 ' + opts.filePattern);
    });
  }

  // ── 待升级列表（勾选多选）─────────────────────────
  function setFiles(list) {
    files = list.map(function (z) {
      return {path: z.path, name: z.name,
              size_str: z.size_str || '', checked: true};
    });
    renderFiles();
  }

  function addFile(path) {
    path = (path || '').trim().replace(/^"|"$/g, '');
    if (!path) { api.toast('请先填写或选择 ' + opts.fileWord + ' 路径'); return; }
    if (!extRe.test(path)) { api.toast('只支持 ' + opts.fileExt + ' 文件'); return; }
    for (var i = 0; i < files.length; i++) {
      if (files[i].path.toLowerCase() === path.toLowerCase()) {
        files[i].checked = true;
        renderFiles();
        api.toast('已在待升级列表中：' + files[i].name);
        return;
      }
    }
    files.push({path: path, name: path.replace(/[\\/]+$/, '').split(/[\\/]/).pop(),
                size_str: '', checked: true});
    renderFiles();
    setNotice('已添加：' + files[files.length - 1].name);
  }

  // 打包页「升级此包」入口：切页签 + 把成品加进列表
  function addPackage(path) {
    api.switchTab(opts.tabName);
    addFile(path);
  }

  function renderFiles() {
    var checked = files.filter(function (z) { return z.checked; }).length;
    el('fileCount').textContent = files.length ? checked + ' / ' + files.length : '';
    el('fileList').innerHTML = files.length ? files.map(function (z, i) {
      return '<li class="zip-item" data-z="' + i + '" title="' + api.esc(z.path) + '">' +
        '<input type="checkbox" data-c="' + i + '"' + (z.checked ? ' checked' : '') + '>' +
        '<div class="zip-info"><div class="name">' + api.esc(z.name) + '</div>' +
        (z.size_str ? '<div class="sub">' + api.esc(z.size_str) + '</div>' : '') +
        '</div><button class="mini" data-x="' + i + '" title="移除">✕</button></li>';
    }).join('') : '<li class="empty">搜索目录后点选 ' + opts.fileWord + '，或直接指定文件</li>';
  }

  function checkedFiles() {
    return files.filter(function (z) { return z.checked; }).map(function (z) { return z.path; });
  }

  // ── 升级流程：验证凭据 → 启动任务 ─────────────────
  function setErrors(list) {
    el('errors').innerHTML = (list || []).map(function (e) {
      return '<div>• ' + api.esc(e) + '</div>';
    }).join('');
  }

  function setNotice(text) { el('notices').textContent = text || ''; }

  function setBusy(flag, status) {
    busy = flag;
    el('btnStart').disabled = flag || starting;
    el('btnStop').disabled = !flag;
    api.setStatus(opts.tabKey, status || 'idle');
    if (!flag) {
      el('progressWrap').hidden = true;
      el('progressBar').style.width = '0';
    }
  }

  function authHint(text) { el('authHint').textContent = text || ''; }

  function start() {
    if (busy || starting) { api.toast('已有升级任务在跑'); return; }
    var host = currentHost();
    if (!host) { api.toast('请选择或输入服务器地址'); return; }
    var paths = checkedFiles();
    if (!paths.length) { setErrors(['请先勾选要升级的 ' + opts.fileWord + ' 包']); return; }
    api.askSysNotifyOnStart();
    setErrors([]);
    setNotice('');
    starting = true;
    el('btnStart').disabled = true;
    authHint('🔑 正在验证服务器凭据…（旧密码失效会自动轮试默认凭据）');
    api.req('POST', opts.apiPrefix + '/auth', {
      host: host, username: api.val(ids.username), password: el('password').value.trim()
    }).then(function (res) {
      var d = res.ok ? res.data : {status: 'error', message: api.detailOf(res).message || ('验证请求失败（' + res.status + '）')};
      if (d.status === 'ok') {
        el('username').value = d.username || 'root';
        el('password').value = d.password || '';
        authHint('✅ 凭据已验证');
        // 轮试出的新凭据同步回下拉数据，避免再选一次又填回旧密码
        loadServers().then(function () { selectServer(d.host, d.username); doStart(d, paths); });
        return;
      }
      starting = false;
      el('btnStart').disabled = false;
      if (d.status === 'need_password' || d.status === 'auth_failed') {
        el('password').value = '';
        el('password').focus();
        authHint('⚠️ ' + (d.message || '请输入新密码后重试'));
        setErrors([d.message || '密码认证失败，请输入新密码']);
      } else {
        authHint('');
        setErrors([d.message || '凭据验证失败']);
      }
    }).catch(function (e) {
      starting = false;
      el('btnStart').disabled = false;
      authHint('');
      setErrors(['凭据验证请求异常：' + e]);
    });
  }

  function doStart(creds, paths) {
    var body = {host: creds.host, username: creds.username, password: creds.password};
    body[opts.filesKey] = paths;
    api.req('POST', opts.apiPrefix + '/start', body).then(function (res) {
      starting = false;
      if (!res.ok) {
        el('btnStart').disabled = false;
        var d = api.detailOf(res);
        setErrors(d.errors.length ? d.errors : [d.message || '任务未能启动']);
        return;
      }
      el('progressText').textContent = '';
      setBusy(true, 'running');
      clearLog();
    }).catch(function (e) {
      starting = false;
      el('btnStart').disabled = false;
      setErrors(['启动请求异常：' + e]);
    });
  }

  function stop() {
    api.req('POST', opts.apiPrefix + '/stop').then(function (res) {
      if (!res.ok) api.toast(api.detailOf(res).message || '停止失败');
    });
  }

  // ── SSE ───────────────────────────────────────────
  function openStream() {
    closeStream();
    stream = new EventSource(opts.apiPrefix + '/progress');
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
        el('progressWrap').hidden = false;
        el('progressBar').style.width = (ev.percent || 0) + '%';
        el('progressText').textContent = '上传 ' + (ev.index || '') + '/' + (ev.total || '') +
          '：' + (ev.file || '') + ' ' + (ev.percent || 0) + '%';
        break;
      case 'status':
        api.setStatus(opts.tabKey, ev.status);
        break;
      case 'complete':
        setBusy(false, 'done');
        setNotice('升级完成，用时 ' + (ev.elapsed || 0) + 's');
        api.notifyDone(ev.result || {}, {title: opts.doneTitle});
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
    var box = el('log');
    var span = document.createElement('span');
    var cls = api.logClass(line);
    if (cls) span.className = cls;
    span.textContent = line + '\n';
    box.appendChild(span);
    while (box.childNodes.length > 2000) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }

  function renderSnapshot(lines) {
    el('log').innerHTML = '';
    lines.forEach(appendLog);
  }

  function clearLog() { el('log').innerHTML = ''; }

  // ── 历史 ──────────────────────────────────────────
  function loadHistory() {
    api.req('GET', opts.apiPrefix + '/history').then(function (res) {
      if (!res.ok) return;
      histRecords = res.data.records || [];
      el('histCount').textContent = histRecords.length + ' 条';
      el('historyList').innerHTML = histRecords.length ? histRecords.map(function (r, i) {
        return '<li data-h="' + i + '"><div class="name">' + api.esc(r.server || '') +
          (r.svn_dir ? ' [' + api.esc(r.svn_dir) + ']' : '') + '</div>' +
          '<div class="sub">' + api.esc(r.timestamp || '') + '</div>' +
          '<div class="sub">' + api.esc(r[opts.namesKey] || '') + '</div></li>';
      }).join('') : '<li class="empty">暂无记录</li>';
    });
  }

  function applyHistory() {
    if (histSel < 0 || !histRecords[histSel]) { api.toast('先点击选中一条历史记录'); return; }
    var r = histRecords[histSel];
    selectServer(r.server || '', r.username);
    var paths = r[opts.filesKey] || [];
    files = paths.map(function (p) {
      return {path: p, name: p.replace(/[\\/]+$/, '').split(/[\\/]/).pop(),
              size_str: '', checked: true};
    });
    renderFiles();
    setNotice('已回填升级历史：' + (r.timestamp || '') + '（文件若已被移动/删除，启动时会提示）');
  }

  function deleteHistory() {
    if (histSel < 0) { api.toast('先选中一条记录'); return; }
    api.req('DELETE', opts.apiPrefix + '/history?index=' + histSel).then(function (res) {
      if (!res.ok) { api.toast(api.detailOf(res).message || '删除失败'); return; }
      histSel = -1;
      loadHistory();
    });
  }

  // ── 绑定 / 初始化 ─────────────────────────────────
  function bind() {
    el('serverSelect').addEventListener('change', onServerChange);
    el('btnSaveServer').addEventListener('click', saveServer);
    el('btnSearch').addEventListener('click', doSearch);
    el('keyword').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(); });
    el('btnAddFile').addEventListener('click', function () {
      addFile(api.val(ids.fileManual));
      el('fileManual').value = '';
    });
    el('fileManual').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { addFile(api.val(ids.fileManual)); el('fileManual').value = ''; }
    });
    el('dirList').addEventListener('click', function (e) {
      var li = api.closestLI(e.target);
      if (!li || !li.hasAttribute('data-d')) return;
      var item = dirs[+li.getAttribute('data-d')];
      if (!item) return;
      api.selectLi(ids.dirList, li);
      loadDirFiles(item.path);
    });
    el('fileList').addEventListener('click', function (e) {
      var t = e.target;
      if (t.tagName === 'INPUT' && t.hasAttribute('data-c')) {
        files[+t.getAttribute('data-c')].checked = t.checked;
        renderFiles();
        return;
      }
      var btn = t.closest ? t.closest('button[data-x]') : null;
      if (btn) {
        files.splice(+btn.getAttribute('data-x'), 1);
        renderFiles();
        setNotice('');
      }
    });
    el('btnStart').addEventListener('click', start);
    el('btnStop').addEventListener('click', stop);
    el('btnClearLog').addEventListener('click', clearLog);
    el('historyList').addEventListener('click', function (e) {
      var li = e.target.closest ? e.target.closest('li[data-h]') : null;
      if (!li) return;
      histSel = +li.getAttribute('data-h');
      api.selectLi(ids.historyList, li);
    });
    el('btnHistApply').addEventListener('click', applyHistory);
    el('btnHistDelete').addEventListener('click', deleteHistory);
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

  return {init: init, start: start, addZip: addFile, addPackage: addPackage};
}

// 前端升级：沿用原 up* id 与 /api/upgrade/*，行为与重构前一致
var Up = createUpgradeController({
  apiPrefix: '/api/upgrade',
  filesKey: 'zip_paths', namesKey: 'zip_names', searchKey: 'zips',
  fileExt: '.zip', fileWord: 'ZIP', filePattern: 'YM-801S-*.zip',
  tabKey: 'upgrade', tabName: 'upgrade', doneTitle: '✅ 升级完成',
  ids: {
    serverSelect: 'upServerSelect', hostManualRow: 'upHostManualRow', hostManual: 'upHostManual',
    username: 'upUsername', password: 'upPassword', btnSaveServer: 'btnUpSaveServer', authHint: 'upAuthHint',
    keyword: 'upKeyword', btnSearch: 'btnUpSearch', dirCount: 'upDirCount', dirList: 'upDirList',
    fileManual: 'upZipManual', btnAddFile: 'btnUpAddZip', fileCount: 'upZipCount', fileList: 'upZipList',
    btnStart: 'btnUpStart', btnStop: 'btnUpStop', progressWrap: 'upProgressWrap',
    progressBar: 'upProgressBar', progressText: 'upProgressText', errors: 'upErrors', notices: 'upNotices',
    log: 'upLog', btnClearLog: 'btnUpClearLog', histCount: 'upHistCount', historyList: 'upHistoryList',
    btnHistApply: 'btnUpHistApply', btnHistDelete: 'btnUpHistDelete'
  }
});

// 服务端升级：sv* id 与 /api/server-upgrade/*，传 war 跑 publish_server.sh
var Sv = createUpgradeController({
  apiPrefix: '/api/server-upgrade',
  filesKey: 'war_paths', namesKey: 'war_names', searchKey: 'wars',
  fileExt: '.war', fileWord: 'WAR', filePattern: 'YM-801S-OSCS-*.war',
  tabKey: 'server', tabName: 'server', doneTitle: '✅ 服务端升级完成',
  ids: {
    serverSelect: 'svServerSelect', hostManualRow: 'svHostManualRow', hostManual: 'svHostManual',
    username: 'svUsername', password: 'svPassword', btnSaveServer: 'btnSvSaveServer', authHint: 'svAuthHint',
    keyword: 'svKeyword', btnSearch: 'btnSvSearch', dirCount: 'svDirCount', dirList: 'svDirList',
    fileManual: 'svWarManual', btnAddFile: 'btnSvAddWar', fileCount: 'svWarCount', fileList: 'svWarList',
    btnStart: 'btnSvStart', btnStop: 'btnSvStop', progressWrap: 'svProgressWrap',
    progressBar: 'svProgressBar', progressText: 'svProgressText', errors: 'svErrors', notices: 'svNotices',
    log: 'svLog', btnClearLog: 'btnSvClearLog', histCount: 'svHistCount', historyList: 'svHistoryList',
    btnHistApply: 'btnSvHistApply', btnHistDelete: 'btnSvHistDelete'
  }
});

document.addEventListener('DOMContentLoaded', function () { Up.init(); Sv.init(); });