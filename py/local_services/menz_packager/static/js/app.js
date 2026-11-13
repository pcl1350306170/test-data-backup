/* 门诊订单打包 — 三栏工作台交互
   对应桌面版 门诊打包.pyw：关键字搜索 → 点选回填 → 打包 → 成品列表 → 历史。
   区别：不弹本机目录对话框（走 /api/browse 受限浏览），日志走 SSE，Node 版本走 PATH 注入。 */
var App = (function () {
  var cfg = {};
  var meta = {version_options: [], roots: []};
  var nodeInfo = {};
  var stream = null;
  var searchData = {svn_dirs: [], projects: []};
  var baseZips = [];
  var histRecords = [];
  var histSel = -1;
  var lastPackage = '';
  var busy = false;
  var picker = {target: '', kind: 'dir', path: '', from: 'svn'};
  var enterHits = [];

  // ── 小工具 ────────────────────────────────────────
  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(msg, ms) {
    var t = $('toast');
    t.textContent = msg;
    t.style.display = 'block';
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.style.display = 'none'; }, ms || 3000);
  }

  function val(id) { return ($(id).value || '').trim(); }
  function setVal(id, v) { if (v != null && v !== '') $(id).value = v; }

  // meta.roots 约定为 [svn_base_dir, git_base_dir]
  function rootOf(which) {
    return (meta.roots || [])[which === 'git' ? 1 : 0] || '';
  }

  // ── 请求封装 ──────────────────────────────────────
  function req(method, url, body) {
    var opt = {method: method, headers: {'Content-Type': 'application/json'}};
    if (body !== undefined) opt.body = JSON.stringify(body || {});
    return fetch(url, opt).then(function (r) {
      return r.text().then(function (txt) {
        var data = {};
        try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = {raw: txt}; }
        return {ok: r.ok, status: r.status, data: data};
      });
    });
  }

  // HTTPException 的 detail 可能是字符串，也可能是 {message, errors}
  function detailOf(res) {
    var d = res.data && res.data.detail;
    if (typeof d === 'string') return {message: d, errors: []};
    if (d && typeof d === 'object') return {message: d.message || '', errors: d.errors || []};
    return {message: '', errors: []};
  }

  function setErrors(list) {
    $('errors').innerHTML = (list || []).map(function (e) {
      return '<div>• ' + esc(e) + '</div>';
    }).join('');
  }

  function setNotice(text) { $('notices').textContent = text || ''; }

  // ── 初始化：配置 / Node / 历史 ────────────────────
  function loadConfig() {
    return req('GET', '/api/config').then(function (res) {
      if (!res.ok) { toast('读取配置失败：' + res.status); return; }
      cfg = res.data.config || {};
      meta = res.data.meta || meta;
      $('svnBaseDir').value = cfg.svn_base_dir || '';
      $('gitBaseDir').value = cfg.git_base_dir || '';
      setVal('projectDir', cfg.project_dir);
      setVal('outputDir', cfg.output_dir);
      setVal('orderInfo', cfg.order_info);
      setVal('baseZip', cfg.base_zip_path);
      setVal('customZip', cfg.custom_zip_name);
      $('is155Plus').checked = !!cfg.is_version_155_plus;
      $('autoCommitSvn').checked = !!cfg.auto_commit_svn;
      buildVersionOptions(cfg.project_version);
      if (res.data.legacy_migrated) toast('已从旧桌面版配置迁移：' + res.data.legacy_migrated, 5000);
    });
  }

  function buildVersionOptions(current) {
    var sel = $('versionSelect');
    var opts = (meta.version_options || []).slice();
    if (current && opts.indexOf(current) < 0) opts.push(current);
    var html = opts.map(function (v) {
      return '<option value="' + esc(v) + '">' + esc(v) + '</option>';
    }).join('');
    html += '<option value="__manual__">手动输入…</option>';
    sel.innerHTML = html;
    if (current && opts.indexOf(current) >= 0) {
      sel.value = current;
      sel.style.display = '';
      $('versionManual').style.display = 'none';
    } else if (current) {
      sel.value = '__manual__';
      sel.style.display = '';
      $('versionManual').style.display = '';
      $('versionManual').value = current;
    }
  }

  function currentVersion() {
    var sel = $('versionSelect');
    return sel.value === '__manual__' ? val('versionManual') : sel.value;
  }

  function loadNodeVersions() {
    return req('GET', '/api/node/versions').then(function (res) {
      if (!res.ok) { toast('Node 版本探测失败'); return; }
      nodeInfo = res.data || {};
      var sel = $('nodeVersion');
      var versions = nodeInfo.versions || [];
      var want = cfg.node_version || nodeInfo.default || '';
      var html = '';
      if (want && versions.indexOf(want) < 0) {
        html += '<option value="' + esc(want) + '">' + esc(want) + '（未检测到）</option>';
      }
      html += versions.map(function (v) {
        var tag = v === nodeInfo.current ? '（nvm 当前）' : '';
        return '<option value="' + esc(v) + '">' + esc(v) + esc(tag) + '</option>';
      }).join('');
      sel.innerHTML = html;
      if (want) sel.value = want;
      var cur = nodeInfo.node_current || nodeInfo.current || '未知';
      $('envInfo').textContent = 'Node 当前 ' + cur + (nodeInfo.nvm_root ? ' · nvm: ' + nodeInfo.nvm_root : '');
    });
  }

  // ── 搜索 ──────────────────────────────────────────
  function doSearch() {
    var keyword = val('keyword');
    if (!keyword) { toast('请输入关键字'); return; }
    setErrors([]);
    setNotice('');
    $('btnSearch').disabled = true;
    req('POST', '/api/search', {keyword: keyword}).then(function (res) {
      $('btnSearch').disabled = false;
      if (!res.ok) {
        var d = detailOf(res);
        toast(d.message || '搜索失败');
        return;
      }
      renderSearch(res.data);
    }).catch(function (e) {
      $('btnSearch').disabled = false;
      toast('搜索请求异常：' + e);
    });
  }

  function renderSearch(data) {
    var svn = data.svn_dirs || [];
    var git = data.projects || [];
    $('svnCount').textContent = svn.length ? svn.length + ' 个' : '';
    $('gitCount').textContent = git.length ? git.length + ' 个' : '';

    $('svnList').innerHTML = svn.length ? svn.map(function (d, i) {
      return '<li data-svn="' + i + '">' +
        '<div class="name">' + esc(d.name) + '</div>' +
        '<div class="sub">更新 ' + esc(d.mtime_str) + '</div></li>';
    }).join('') : '<li class="empty">无匹配 SVN 目录</li>';

    $('gitList').innerHTML = git.length ? git.map(function (d, i) {
      return '<li data-git="' + i + '">' +
        '<div class="name">' + esc(d.name) + '</div>' +
        '<div class="sub">' + esc(d.branch) + (d.version ? ' · ' + esc(d.version) : '') + '</div>' +
        '<div class="sub">更新 ' + esc(d.mtime_str) + '</div></li>';
    }).join('') : '<li class="empty">无匹配 Git 分支</li>';

    searchData = {svn_dirs: svn, projects: git};
    if (data.notice) setNotice(data.notice);

    // 各自只命中一个时直接回填，省一次点击
    var sug = data.suggestion || {};
    if (svn.length === 1) {
      if (sug.output_dir) $('outputDir').value = sug.output_dir;
      if (sug.order_info) $('orderInfo').value = sug.order_info;
      if (sug.base_zip_path) $('baseZip').value = sug.base_zip_path;
      baseZips = data.base_zips || [];
      renderBaseZipQuick();
      refreshFiles(sug.output_dir || '');
    }
    if (git.length === 1) {
      if (sug.project_dir) $('projectDir').value = sug.project_dir;
      if (sug.project_version) setVersion(sug.project_version);
    }
    if (!svn.length && !git.length) setNotice(data.notice || '未找到匹配目录');
  }

  function setVersion(ver) {
    var sel = $('versionSelect');
    if (!ver) return;
    var found = false;
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === ver) { found = true; break; }
    }
    if (found) {
      sel.value = ver;
      $('versionManual').style.display = 'none';
    } else {
      var opt = document.createElement('option');
      opt.value = ver;
      opt.textContent = ver + '（分支推断）';
      sel.insertBefore(opt, sel.options[sel.options.length - 1]);
      sel.value = ver;
    }
    sel.value = ver;
    $('versionManual').style.display = 'none';
  }

  // ── 点选列表项 → /api/prefill 回填 ────────────────
  function bindSearchLists() {
    $('svnList').addEventListener('click', function (e) {
      var li = closestLI(e.target);
      if (!li || !li.hasAttribute('data-svn')) return;
      var item = searchData.svn_dirs[+li.getAttribute('data-svn')];
      if (!item) return;
      selectLi('svnList', li);
      prefill({svn_dir: item.path}, function (d) {
        if (d.output_dir) $('outputDir').value = d.output_dir;
        if (d.order_info) $('orderInfo').value = d.order_info;
        if (d.base_zip_path) $('baseZip').value = d.base_zip_path;
        // 基础包名里的 V 段就是项目版本，不填会拼错成品 ZIP 名
        if (d.project_version) setVersion(d.project_version);
        baseZips = d.base_zips || [];
        renderBaseZipQuick();
        // 项目目录还空着且 Git 只命中一条，顺手补上
        if (!val('projectDir') && searchData.projects.length === 1) {
          var g = searchData.projects[0];
          $('projectDir').value = g.path;
          if (g.version) setVersion(g.version);
        }
        setNotice(d.notice || '');
        refreshFiles();
      });
    });

    $('gitList').addEventListener('click', function (e) {
      var li = closestLI(e.target);
      if (!li || !li.hasAttribute('data-git')) return;
      var item = searchData.projects[+li.getAttribute('data-git')];
      if (!item) return;
      selectLi('gitList', li);
      $('projectDir').value = item.path;
      if (item.version) setVersion(item.version);
      prefill({project_dir: item.path}, function (d) {
        if (d.project_version) setVersion(d.project_version);
        setNotice(d.version_notice || (d.git_branch ? '分支：' + d.git_branch : ''));
      });
    });
  }

  function prefill(params, done) {
    req('POST', '/api/prefill', params).then(function (res) {
      if (!res.ok) { toast(detailOf(res).message || '回填失败'); return; }
      done(res.data || {});
    });
  }

  function renderBaseZipQuick() {
    var box = $('baseZipQuick');
    if (!baseZips.length) { box.innerHTML = ''; return; }
    box.innerHTML = baseZips.map(function (z, i) {
      return '<button class="mini" data-zip="' + i + '" title="' + esc(z.path) + '">' +
        esc(z.name.length > 40 ? z.name.slice(0, 20) + '…' + z.name.slice(-16) : z.name) + '</button>';
    }).join('');
  }

  function selectLi(listId, li) {
    var items = $(listId).querySelectorAll('li');
    for (var i = 0; i < items.length; i++) items[i].classList.remove('selected');
    li.classList.add('selected');
  }

  function closestLI(node) {
    while (node && node.tagName !== 'LI') node = node.parentElement;
    return node && node.hasAttribute('class') && node.className === 'empty' ? null : node;
  }

  // ── 受限目录浏览 ──────────────────────────────────
  function openPicker(targetId, kind, startPath, title, from) {
    picker = {target: targetId, kind: kind, path: startPath || '', from: from || 'svn'};
    if (!picker.path) picker.path = rootOf(from) || (meta.roots || []).filter(function (r) { return r; })[0] || '';
    if (!picker.path) { toast('还没配置可浏览的基础目录'); return; }
    $('modalTitle').textContent = title || (kind === 'zip' ? '选择压缩包' : '选择目录');
    $('modalPick').style.display = kind === 'zip' ? 'none' : '';
    $('modal').classList.remove('hidden');
    loadPicker(picker.path);
  }

  // 打开某个目录失败时退回根目录，避免填了根目录之外的路径就卡死
  function loadPicker(path, allowFallback) {
    var exts = picker.kind === 'zip' ? '.zip' : '';
    req('GET', '/api/browse?path=' + encodeURIComponent(path) + '&exts=' + exts)
      .then(function (res) {
        if (!res.ok) {
          var root = rootOf(picker.from);
          if (allowFallback !== false && root && norm(root) !== norm(path)) {
            setNotice('该路径不在允许范围内，已跳到基础目录：' + root);
            return loadPicker(root, false);
          }
          toast(detailOf(res).message || '无法打开该目录');
          return;
        }
        var d = res.data;
        picker.path = d.path;
        $('modalPath').textContent = d.path;
        $('modalUp').disabled = isRoot(d.path, d.roots);
        $('modalDirs').innerHTML = (d.dirs || []).length ? d.dirs.map(function (x) {
          var tag = x.is_git ? '📁 ' + esc(x.branch || 'git') : (x.is_svn ? '🔷 SVN' : '');
          return '<li data-dir="' + esc(x.path) + '"><div class="name">' + esc(x.name) +
            '</div><div class="sub">' + esc(tag) + (tag ? ' · ' : '') + '更新 ' + esc(x.mtime_str) +
            '</div></li>';
        }).join('') : '<li class="empty">没有子目录</li>';
        $('modalFiles').innerHTML = (picker.kind === 'zip')
          ? ((d.files || []).length ? d.files.map(function (f) {
            return '<li data-file="' + esc(f.path) + '"><div class="name">' + esc(f.name) +
              '</div><div class="sub">' + esc(f.size_str) + ' · ' + esc(f.mtime_str) + '</div></li>';
          }).join('') : '<li class="empty">没有 .zip 文件</li>')
          : '';
      });
  }

  function isRoot(path, roots) {
    var a = norm(path);
    var list = roots || meta.roots || [];
    for (var i = 0; i < list.length; i++) if (norm(list[i]) === a) return true;
    return false;
  }

  function norm(p) { return String(p || '').replace(/[\\/]+$/, '').toLowerCase(); }

  function bindModal() {
    $('modalDirs').addEventListener('click', function (e) {
      var li = e.target.closest ? e.target.closest('li[data-dir]') : null;
      if (li) loadPicker(li.getAttribute('data-dir'));
    });
    $('modalFiles').addEventListener('click', function (e) {
      var li = e.target.closest ? e.target.closest('li[data-file]') : null;
      if (!li) return;
      $(picker.target).value = li.getAttribute('data-file');
      closeModal();
      if (picker.target === 'baseZip') setNotice('');
    });
    $('modalUp').addEventListener('click', function () {
      var p = picker.path.replace(/[\\/]+$/, '');
      var idx = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'));
      if (idx > 0) loadPicker(p.slice(0, idx));
    });
    $('modalPick').addEventListener('click', function () {
      $(picker.target).value = picker.path;
      closeModal();
      if (picker.target === 'outputDir') refreshFiles();
    });
    $('modalClose').addEventListener('click', closeModal);
    $('modal').addEventListener('click', function (e) { if (e.target === $('modal')) closeModal(); });
  }

  function closeModal() { $('modal').classList.add('hidden'); }

  // ── 保存基础目录 ──────────────────────────────────
  function saveDirs() {
    req('POST', '/api/config', {svn_base_dir: val('svnBaseDir'), git_base_dir: val('gitBaseDir')})
      .then(function (res) {
        if (!res.ok) { toast('保存失败'); return; }
        toast('基础目录已保存');
        return req('GET', '/api/config').then(function (r) {
          meta = (r.data && r.data.meta) || meta;
        });
      });
  }

  // ── 打包参数 ──────────────────────────────────────
  function collectParams() {
    return {
      project_dir: val('projectDir'),
      output_dir: val('outputDir'),
      order_info: val('orderInfo'),
      project_version: currentVersion(),
      base_zip_path: val('baseZip'),
      custom_zip_name: val('customZip'),
      is_version_155_plus: $('is155Plus').checked,
      auto_commit_svn: $('autoCommitSvn').checked,
      node_version: $('nodeVersion').value
    };
  }

  function startPack() {
    if (busy) { toast('已有任务在跑'); return; }
    setErrors([]);
    setNotice('');
    lastPackage = '';
    updateCommitBtn();
    req('POST', '/api/package/start', collectParams()).then(function (res) {
      if (!res.ok) {
        var d = detailOf(res);
        if (res.status === 400) {
          setErrors(d.errors.length ? d.errors : [d.message]);
          toast('参数校验未通过');
        } else {
          toast(d.message || '任务未能启动（' + res.status + '）');
        }
        return;
      }
      setBusy(true, 'running');
      clearLog();
    });
  }

  function stopPack() {
    req('POST', '/api/package/stop').then(function (res) {
      if (!res.ok) toast(detailOf(res).message || '停止失败');
    });
  }

  function commitSvn() {
    if (!lastPackage) { toast('还没有成品'); return; }
    $('btnCommit').disabled = true;
    req('POST', '/api/svn/commit', {path: lastPackage}).then(function (res) {
      $('btnCommit').disabled = busy;
      if (!res.ok) { toast(detailOf(res).message || '提交失败'); return; }
      toast(res.data.ok ? '✅ 已提交到 SVN' : '⚠️ 提交未成功，详见日志');
      refreshFiles();
    });
  }

  function setBusy(flag, status) {
    busy = flag;
    $('btnStart').disabled = flag;
    $('btnStop').disabled = !flag;
    setStatus(status || 'idle');
    updateCommitBtn();
  }

  function updateCommitBtn() {
    $('btnCommit').disabled = busy || !lastPackage;
  }

  var STATUS = {
    idle: '空闲', running: '打包中', stopping: '停止中',
    done: '完成', error: '失败', stopped: '已停止'
  };

  function setStatus(status) {
    var pill = $('statusPill');
    pill.textContent = STATUS[status] || status;
    pill.className = 'pill ' + (status || 'idle');
  }

  // ── SSE 日志 ──────────────────────────────────────
  function openStream() {
    closeStream();
    stream = new EventSource('/api/package/progress');
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
        setStatus(st.status || 'idle');
        busy = !!st.busy;
        $('btnStart').disabled = busy;
        $('btnStop').disabled = !busy;
        var pkg = st.result && st.result.package_path;
        if (pkg) { lastPackage = pkg; updateCommitBtn(); showOutput(st.result.output_dir || val('outputDir')); }
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
      case 'result':
        onResult(ev.result || {});
        break;
      case 'status':
        setStatus(ev.status);
        break;
      case 'complete':
        onResult(ev.result || {});
        setNotice('打包完成，用时 ' + (ev.elapsed || 0) + 's');
        setBusy(false, 'done');
        refreshFiles();
        loadHistory();
        break;
      case 'error':
        setErrors([ev.error]);
        setBusy(false, 'error');
        refreshFiles();
        break;
      case 'stopped':
        setBusy(false, 'stopped');
        loadHistory();
        break;
      case 'finish':
        closeStream();
        setTimeout(openStream, 600);   // 重开以接收下一次任务的 init 快照
        break;
      default:
        break;
    }
  }

  function onResult(result) {
    if (result.package_path) {
      lastPackage = result.package_path;
      $('btnCommit').disabled = busy;
    }
    if (result.output_dir) showOutput(result.output_dir);
    if (result.svn_committed != null) {
      setNotice(result.svn_committed ? '已自动提交 SVN' : '成品尚未提交 SVN，可点「提交成品到 SVN」');
    }
  }

  function showOutput(path) {
    if (!path) return;
    $('outputPath').textContent = path;
    refreshFiles(path);
  }

  // ── 成品列表 ──────────────────────────────────────
  function refreshFiles(path) {
    path = path || val('outputDir');
    if (!path) { $('fileList').innerHTML = '<li class="empty">暂无成品</li>'; return; }
    req('GET', '/api/output/files?path=' + encodeURIComponent(path)).then(function (res) {
      if (!res.ok) {
        $('fileList').innerHTML = '<li class="empty">' + esc(detailOf(res).message || '无法读取成品目录') + '</li>';
        return;
      }
      var files = res.data.files || [];
      $('outputPath').textContent = res.data.path + '（' + files.length + ' 个成品）';
      $('fileList').innerHTML = files.length ? files.map(function (f) {
        return '<li><div class="name">' + esc(f.name) + '</div><div class="sub">' +
          esc(f.size_str) + ' · ' + esc(f.mtime_str) + '</div></li>';
      }).join('') : '<li class="empty">目录里还没有成品文件</li>';
    });
  }

  // ── 历史 ──────────────────────────────────────────
  function loadHistory() {
    req('GET', '/api/history').then(function (res) {
      if (!res.ok) return;
      histRecords = res.data.records || [];
      $('histCount').textContent = histRecords.length + ' / ' + (res.data.limit || 100);
      $('historyList').innerHTML = histRecords.length ? histRecords.map(function (r, i) {
        return '<li data-h="' + i + '"><div class="name">' + esc(r.order_info || pkgName(r) || '(未填订单)') + '</div>' +
          '<div class="sub">' + esc(r.timestamp || '') + (r.project_version ? ' · v' + esc(r.project_version) : '') + '</div>' +
          '<div class="sub">' + esc(pkgName(r) || '无成品名') + '</div></li>';
      }).join('') : '<li class="empty">暂无记录</li>';
    });
  }

  function pkgName(r) {
    // 旧桌面版历史里没有 package_name，从成品路径/基础包名回退
    if (r.package_name) return r.package_name;
    var p = r.base_zip_path || '';
    return p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '';
  }

  function applyHistory() {
    if (histSel < 0 || !histRecords[histSel]) { toast('先点击选中一条历史记录'); return; }
    var r = histRecords[histSel];
    setVal('projectDir', r.project_dir);
    setVal('outputDir', r.output_dir);
    setVal('orderInfo', r.order_info);
    setVal('baseZip', r.base_zip_path);
    setVal('customZip', r.custom_zip_name);
    if (r.project_version) setVersion(r.project_version);
    $('is155Plus').checked = !!r.is_version_155_plus;
    if (r.node_version) $('nodeVersion').value = r.node_version;
    // auto_commit_svn 不跟着回填：服务里默认手动提交，避免一点开始就进仓库
    var extra = r.auto_commit_svn ? '（历史记录里的「自动提交 SVN」已忽略，请自行点提交）' : '';
    setNotice('已回填历史记录：' + (r.timestamp || '') + extra);
    refreshFiles(r.output_dir);
    if (r.base_zip_path) {
      var dir = r.base_zip_path.replace(/[\\/][^\\/]+$/, '');
      req('POST', '/api/prefill', {svn_dir: dir}).then(function (res) {
        if (res.ok) { baseZips = res.data.base_zips || []; renderBaseZipQuick(); }
      });
    }
  }

  function deleteHistory() {
    if (histSel < 0) { toast('先选中一条记录'); return; }
    req('DELETE', '/api/history?index=' + histSel).then(function (res) {
      if (!res.ok) { toast(detailOf(res).message || '删除失败'); return; }
      histSel = -1;
      loadHistory();
    });
  }

  function bindHistory() {
    $('historyList').addEventListener('click', function (e) {
      var li = e.target.closest ? e.target.closest('li[data-h]') : null;
      if (!li) return;
      histSel = +li.getAttribute('data-h');
      selectLi('historyList', li);
    });
    $('btnHistApply').addEventListener('click', applyHistory);
    $('btnHistDelete').addEventListener('click', deleteHistory);
  }

  // ── 日志渲染 ──────────────────────────────────────
  function logClass(line) {
    if (line.indexOf('✅') >= 0) return 'ok';
    if (line.indexOf('⚠️') >= 0 || line.indexOf('ℹ️') >= 0) return 'warn';
    if (line.indexOf('❌') >= 0 || line.indexOf('🛑') >= 0) return 'err';
    if (line.indexOf('阶段') >= 0) return 'stage';
    return '';
  }

  function appendLog(line) {
    var box = $('log');
    var span = document.createElement('span');
    if (logClass(line)) span.className = logClass(line);
    span.textContent = line + '\n';
    box.appendChild(span);
    while (box.childNodes.length > 2000) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }

  function renderSnapshot(lines) {
    $('log').innerHTML = '';
    lines.forEach(appendLog);
  }

  function clearLog() { $('log').innerHTML = ''; setNotice(''); }

  // ── 快捷键：1 秒内连按 3 次 Enter 开始打包 ────────
  function bindEnterShortcut() {
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || !$('modal').classList.contains('hidden')) return;
      var tag = (e.target.tagName || '').toUpperCase();
      if (tag === 'BUTTON' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      var now = Date.now();
      enterHits.push(now);
      enterHits = enterHits.filter(function (t) { return now - t < 1000; });
      if (enterHits.length >= 3) {
        enterHits = [];
        startPack();
      }
    });
  }

  // ── 主题 ──────────────────────────────────────────
  function initTheme() {
    var saved = localStorage.getItem('packager-theme');
    if (saved === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      $('btnTheme').textContent = '☀️';
    }
    $('btnTheme').addEventListener('click', function () {
      var dark = document.documentElement.getAttribute('data-theme') === 'dark';
      if (dark) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('packager-theme', 'light');
        $('btnTheme').textContent = '🌓';
      } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('packager-theme', 'dark');
        $('btnTheme').textContent = '☀️';
      }
    });
  }

  // ── 事件绑定 ──────────────────────────────────────
  function bind() {
    $('btnSearch').addEventListener('click', doSearch);
    $('keyword').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(); });
    $('btnSaveDirs').addEventListener('click', saveDirs);
    $('btnStart').addEventListener('click', startPack);
    $('btnStop').addEventListener('click', stopPack);
    $('btnCommit').addEventListener('click', commitSvn);
    $('btnClearLog').addEventListener('click', clearLog);
    $('btnRefreshFiles').addEventListener('click', function () { refreshFiles(); });
    $('btnRefreshNode').addEventListener('click', loadNodeVersions);
    $('outputDir').addEventListener('change', function () { showOutput(val('outputDir')); });
    $('versionSelect').addEventListener('change', function () {
      var manual = this.value === '__manual__';
      $('versionManual').style.display = manual ? '' : 'none';
      if (manual) $('versionManual').focus();
    });
    $('baseZipQuick').addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('button[data-zip]') : null;
      if (!btn) return;
      var z = baseZips[+btn.getAttribute('data-zip')];
      if (!z) return;
      $('baseZip').value = z.path;
      // 换了基础包 = 换了版本，同步修正项目版本下拉
      var m = /-V(\d+\.\d+\.\d+)\./.exec(z.name || '');
      if (m) setVersion(m[1]);
      setNotice('已选基础压缩包 ' + z.name + (m ? '，版本 ' + m[1] : ''));
    });
    bindSearchLists();
    bindModal();
    bindHistory();
    bindEnterShortcut();

    // 选择/浏览按钮
    Array.prototype.forEach.call(document.querySelectorAll('[data-pick]'), function (btn) {
      btn.addEventListener('click', function () {
        var kind = btn.getAttribute('data-kind');
        var from = btn.getAttribute('data-from');
        var target = btn.getAttribute('data-pick');
        var start = val(target);
        if (!start && kind === 'zip') start = val('outputDir') || val('baseZip').replace(/[\\/][^\\/]+$/, '');
        if (!start) start = rootOf(from);
        openPicker(target, kind, start, kind === 'zip' ? '选择基础压缩包（.zip）' : '选择目录', from);
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-browse]'), function (btn) {
      btn.addEventListener('click', function () {
        var target = btn.getAttribute('data-browse');
        var which = btn.getAttribute('data-root');
        openPicker(target, 'dir', val(target) || rootOf(which), '选择基础目录', which);
      });
    });
  }

  function init() {
    initTheme();
    bind();
    loadConfig().then(loadNodeVersions).then(function () {
      loadHistory();
      openStream();
      if (val('outputDir')) showOutput(val('outputDir'));
    });
  }

  return {init: init, toast: toast};
})();

document.addEventListener('DOMContentLoaded', App.init);
