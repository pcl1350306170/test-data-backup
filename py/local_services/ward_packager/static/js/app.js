/* 病房订单打包 — 三栏工作台交互
   对应桌面版 病房打包.pyw：类型 + 关键字搜索 → 点选回填 → bash deploy.sh → 产物剪切进 SVN。
   与门诊页共用后端路由（order_packager_core/base_server），差异在参数字段与推断信息面板。 */
var App = (function () {
  var cfg = {};
  var meta = {project_types: ['web', '床头', '床旁', '护理看板'], roots: []};
  var nodeInfo = {};
  var stream = null;
  var searchData = {svn_dirs: [], projects: []};
  var histRecords = [];
  var histSel = -1;
  var lastPackage = '';
  var workDir = '';
  var ptype = '床旁';
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

  // 病房 roots 约定为 [svn_base_dir, code_base_dir]
  function rootOf(which) {
    return (meta.roots || [])[which === 'code' ? 1 : 0] || '';
  }

  function deployScript() {
    return (ptype === 'web' && $('isNewVersion').checked) ? 'deploy-micro.sh' : 'deploy.sh';
  }

  function setKv(id, text, missing) {
    var el = $(id);
    el.textContent = text || '—';
    el.className = missing ? 'miss' : '';
  }

  // dist 里没产物通常不是错：上一次打包已经把 tar.gz 剪切进 SVN 了
  function setPackageInfo(name) {
    var el = $('infoPackage');
    el.textContent = name || '项目 dist 内暂无（可能已剪切进 SVN）';
    el.className = '';
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

  // ── 初始化 ────────────────────────────────────────
  function loadConfig() {
    return req('GET', '/api/config').then(function (res) {
      if (!res.ok) { toast('读取配置失败：' + res.status); return; }
      cfg = res.data.config || {};
      meta = res.data.meta || meta;
      ptype = cfg.project_type || ptype;
      $('svnBaseDir').value = cfg.svn_base_dir || '';
      $('codeBaseDir').value = cfg.code_base_dir || '';
      setVal('projectDir', cfg.project_dir);
      setVal('svnDir', cfg.svn_dir);
      $('isNewVersion').checked = !!cfg.is_new_version;
      $('autoCommitSvn').checked = !!cfg.auto_commit_svn;
      renderTypes();
      if (res.data.legacy_migrated) toast('已从旧桌面版配置迁移：' + res.data.legacy_migrated, 5000);
    });
  }

  function renderTypes() {
    var list = meta.project_types || ['web', '床头', '床旁', '护理看板'];
    $('types').innerHTML = list.map(function (t) {
      return '<button type="button" data-type="' + esc(t) + '" class="' +
        (t === ptype ? 'on' : '') + '">' + esc(t) + '</button>';
    }).join('');
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
        return '<option value="' + esc(v) + '">' + esc(v) +
          (v === nodeInfo.current ? '（nvm 当前）' : '') + '</option>';
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
    req('POST', '/api/search', {
      keyword: keyword, project_type: ptype, is_new_version: $('isNewVersion').checked
    }).then(function (res) {
      $('btnSearch').disabled = false;
      if (!res.ok) { toast(detailOf(res).message || '搜索失败'); return; }
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
      return '<li data-svn="' + i + '"><div class="name">' + esc(d.name) + '</div>' +
        '<div class="sub">更新 ' + esc(d.mtime_str) + '</div></li>';
    }).join('') : '<li class="empty">无匹配 SVN 目录</li>';

    $('gitList').innerHTML = git.length ? git.map(function (d, i) {
      return '<li data-git="' + i + '"><div class="name">' + esc(d.name) + '</div>' +
        '<div class="sub">' + esc(d.branch) + (d.version ? ' · ' + esc(d.version) : '') + '</div>' +
        '<div class="sub">更新 ' + esc(d.mtime_str) + '</div></li>';
    }).join('') : '<li class="empty">无匹配 Git 分支</li>';

    searchData = {svn_dirs: svn, projects: git};
    setKv('infoScript', data.deploy_script || deployScript());

    // 两侧各自只命中一条时分开回填（不要求两边都有结果）
    var sug = data.suggestion || {};
    if (svn.length === 1) {
      setVal('svnDir', sug.svn_dir);
      workDir = sug.svn_work_dir || sug.svn_dir || '';
      setKv('infoWorkDir', workDir);
      refreshFiles(workDir);
    }
    if (git.length === 1) {
      setVal('projectDir', sug.project_dir);
      if (sug.git_branch) setKv('infoBranch', sug.git_branch);
      if (sug.project_version) setKv('infoVersion', sug.project_version);
    }
    if (svn.length === 1 && git.length === 1) {
      setNotice('SVN/Git 各唯一命中，参数已自动回填；不对的话点左侧列表项可重新选择');
    }
    if (!svn.length && !git.length) {
      setNotice(data.notice || '类型「' + ptype + '」下未找到匹配目录，可换个类型或检查基础目录配置');
    }
  }

  // ── 点选列表项 → /api/prefill 回填 ────────────────
  function bindSearchLists() {
    $('svnList').addEventListener('click', function (e) {
      var li = itemOf(e.target, 'data-svn');
      if (!li) return;
      var item = searchData.svn_dirs[+li.getAttribute('data-svn')];
      if (!item) return;
      selectLi('svnList', li);
      $('svnDir').value = item.path;
      prefill({svn_dir: item.path}, function (d) {
        workDir = d.svn_work_dir || item.path;
        setKv('infoWorkDir', workDir);
        setNotice(d.has_frontend ? '已定位前端目录：' + workDir : 'ℹ️ 该 SVN 目录下没有「前端」子目录，产物直接放目录本身');
        if (!d.svn_work_copy) setNotice('⚠️ 该路径向上 5 层都没找到 .svn 工作副本，提交会跳过');
        refreshFiles(workDir);
      });
    });

    $('gitList').addEventListener('click', function (e) {
      var li = itemOf(e.target, 'data-git');
      if (!li) return;
      var item = searchData.projects[+li.getAttribute('data-git')];
      if (!item) return;
      selectLi('gitList', li);
      $('projectDir').value = item.path;
      setKv('infoBranch', item.branch);
      setKv('infoVersion', item.version);
      prefill({project_dir: item.path, project_type: ptype, is_new_version: $('isNewVersion').checked},
        function (d) {
          setKv('infoScript', d.deploy_script + (d.has_deploy_script ? '' : '（缺失）'), !d.has_deploy_script);
          setPackageInfo(d.current_package);
          if (d.project_version) setKv('infoVersion', d.project_version);
          if (d.git_branch) setKv('infoBranch', d.git_branch);
          if (d.has_deploy_script === false) {
            setErrors(['项目目录下缺少 ' + d.deploy_script + '，请确认分支或改选「新版本」']);
          } else {
            setErrors([]);
          }
        });
    });
  }

  function prefill(params, done) {
    req('POST', '/api/prefill', params).then(function (res) {
      if (!res.ok) { toast(detailOf(res).message || '回填失败'); return; }
      done(res.data || {});
    });
  }

  function selectLi(listId, li) {
    var items = $(listId).querySelectorAll('li');
    for (var i = 0; i < items.length; i++) items[i].classList.remove('selected');
    li.classList.add('selected');
  }

  function itemOf(node, attr) {
    while (node && node.tagName !== 'LI') node = node.parentElement;
    return node && node.hasAttribute(attr) ? node : null;
  }

  // ── 受限目录浏览 ──────────────────────────────────
  function openPicker(targetId, kind, startPath, title, from) {
    picker = {target: targetId, kind: kind, path: startPath || '', from: from || 'svn'};
    if (!picker.path) picker.path = rootOf(from) || (meta.roots || []).filter(function (r) { return r; })[0] || '';
    if (!picker.path) { toast('还没配置可浏览的基础目录'); return; }
    $('modalTitle').textContent = title || '选择目录';
    $('modalPick').style.display = kind === 'zip' ? 'none' : '';
    $('modal').classList.remove('hidden');
    loadPicker(picker.path);
  }

  // 路径越界时退回对应基础目录，避免页面卡住
  function loadPicker(path, allowFallback) {
    var exts = picker.kind === 'pkg' ? '.tar.gz,.tgz,.zip' : '';
    req('GET', '/api/browse?path=' + encodeURIComponent(path) + '&exts=' + exts).then(function (res) {
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
      $('modalFiles').innerHTML = (picker.kind === 'pkg')
        ? ((d.files || []).length ? d.files.map(function (f) {
          return '<li data-file="' + esc(f.path) + '"><div class="name">' + esc(f.name) +
            '</div><div class="sub">' + esc(f.size_str) + ' · ' + esc(f.mtime_str) + '</div></li>';
        }).join('') : '<li class="empty">没有打包产物</li>')
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
      var li = itemOf(e.target, 'data-dir');
      if (li) loadPicker(li.getAttribute('data-dir'));
    });
    $('modalFiles').addEventListener('click', function (e) {
      var li = itemOf(e.target, 'data-file');
      if (!li) return;
      $(picker.target).value = li.getAttribute('data-file');
      closeModal();
    });
    $('modalUp').addEventListener('click', function () {
      var p = picker.path.replace(/[\\/]+$/, '');
      var idx = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'));
      if (idx > 0) loadPicker(p.slice(0, idx));
    });
    $('modalPick').addEventListener('click', function () {
      $(picker.target).value = picker.path;
      closeModal();
      if (picker.target === 'svnDir') {
        workDir = picker.path;
        prefill({svn_dir: picker.path}, function (d) {
          workDir = d.svn_work_dir || picker.path;
          setKv('infoWorkDir', workDir);
          refreshFiles(workDir);
        });
      } else if (picker.target === 'projectDir') {
        prefill({project_dir: picker.path, project_type: ptype,
                 is_new_version: $('isNewVersion').checked}, function (d) {
          setKv('infoBranch', d.git_branch);
          setKv('infoVersion', d.project_version);
          setKv('infoScript', d.deploy_script + (d.has_deploy_script ? '' : '（缺失）'), !d.has_deploy_script);
          setPackageInfo(d.current_package);
        });
      }
    });
    $('modalClose').addEventListener('click', closeModal);
    $('modal').addEventListener('click', function (e) { if (e.target === $('modal')) closeModal(); });
  }

  function closeModal() { $('modal').classList.add('hidden'); }

  // ── 保存基础目录 ──────────────────────────────────
  function saveDirs() {
    req('POST', '/api/config', {svn_base_dir: val('svnBaseDir'), code_base_dir: val('codeBaseDir')})
      .then(function (res) {
        if (!res.ok) { toast('保存失败'); return; }
        toast('基础目录已保存');
        return req('GET', '/api/config').then(function (r) {
          meta = (r.data && r.data.meta) || meta;
        });
      });
  }

  // ── 打包 ──────────────────────────────────────────
  function collectParams() {
    return {
      project_type: ptype,
      keyword: val('keyword'),
      project_dir: val('projectDir'),
      svn_dir: val('svnDir'),
      is_new_version: $('isNewVersion').checked,
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
    req('POST', '/api/svn/commit', {path: lastPackage, work_dir: workDir}).then(function (res) {
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

  function updateCommitBtn() { $('btnCommit').disabled = busy || !lastPackage; }

  var STATUS = {
    idle: '空闲', running: '打包中', stopping: '停止中',
    done: '完成', error: '失败', stopped: '已停止'
  };

  function setStatus(status) {
    var pill = $('statusPill');
    pill.textContent = STATUS[status] || status;
    pill.className = 'pill ' + (status || 'idle');
  }

  // ── SSE ───────────────────────────────────────────
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
        if (st.result) onResult(st.result);
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
        loadHistory();
        break;
      case 'error':
        setErrors([ev.error]);
        setBusy(false, 'error');
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
      setKv('infoPackage', result.package_name || lastName(result.package_path));
    }
    if (result.svn_work_dir) {
      workDir = result.svn_work_dir;
      setKv('infoWorkDir', workDir);
    }
    if (result.deploy_script) setKv('infoScript', result.deploy_script);
    if (result.git_branch) setKv('infoBranch', result.git_branch);
    if (result.project_type) { ptype = result.project_type; renderTypes(); }
    if (result.svn_committed != null) {
      setNotice(result.svn_committed ? '已自动提交 SVN' : '成品尚未提交 SVN，可点「提交成品到 SVN」');
    }
    if (workDir) refreshFiles(workDir);
  }

  // ── 成品列表 ──────────────────────────────────────
  function refreshFiles(path) {
    path = path || workDir || val('svnDir');
    if (!path) { $('fileList').innerHTML = '<li class="empty">暂无成品</li>'; return; }
    req('GET', '/api/output/files?path=' + encodeURIComponent(path)).then(function (res) {
      if (!res.ok) {
        $('fileList').innerHTML = '<li class="empty">' + esc(detailOf(res).message || '无法读取成品目录') + '</li>';
        return;
      }
      var files = res.data.files || [];
      $('outputPath').textContent = res.data.path + '（' + files.length + ' 个成品）';
      $('fileList').innerHTML = files.length ? files.map(function (f) {
        var isNew = lastPackage && f.path === lastPackage;
        return '<li><div class="name">' + (isNew ? '🆕 ' : '') + esc(f.name) + '</div><div class="sub">' +
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
        return '<li data-h="' + i + '"><div class="name">' + esc(r.project_type || '') + ' · ' +
          esc(lastName(r.project_dir) || '(未知项目)') + '</div>' +
          '<div class="sub">' + esc(r.timestamp || '') + (r.branch ? ' · ' + esc(r.branch) : '') + '</div>' +
          '<div class="sub">' + esc(r.package_name || '无产物名') + '</div></li>';
      }).join('') : '<li class="empty">暂无记录</li>';
    });
  }

  function lastName(p) {
    return String(p || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '';
  }

  function applyHistory() {
    if (histSel < 0 || !histRecords[histSel]) { toast('先点击选中一条历史记录'); return; }
    var r = histRecords[histSel];
    if (r.project_type) { ptype = r.project_type; renderTypes(); }
    setVal('projectDir', r.project_dir);
    setVal('svnDir', r.svn_dir);
    setVal('keyword', r.keyword);
    $('isNewVersion').checked = !!r.is_new_version;
    if (r.node_version) $('nodeVersion').value = r.node_version;
    setKv('infoBranch', r.branch);
    setNotice('已回填历史记录：' + (r.timestamp || ''));
    if (r.svn_dir) {
      prefill({svn_dir: r.svn_dir, project_type: ptype, is_new_version: !!r.is_new_version}, function (d) {
        workDir = d.svn_work_dir || r.svn_dir;
        setKv('infoWorkDir', workDir);
        setKv('infoScript', d.deploy_script);
        setPackageInfo(d.current_package);
        if (d.project_version) setKv('infoVersion', d.project_version);
        refreshFiles(workDir);
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
      var li = itemOf(e.target, 'data-h');
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
    if (localStorage.getItem('packager-theme') === 'dark') {
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
    $('svnDir').addEventListener('change', function () {
      workDir = val('svnDir');
      setKv('infoWorkDir', workDir);
      refreshFiles(workDir);
    });
    $('isNewVersion').addEventListener('change', function () {
      setKv('infoScript', deployScript());
      if (val('projectDir')) {
        prefill({project_dir: val('projectDir'), project_type: ptype,
                 is_new_version: this.checked}, function (d) {
          setKv('infoScript', d.deploy_script + (d.has_deploy_script ? '' : '（缺失）'), !d.has_deploy_script);
        });
      }
    });
    $('types').addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('button[data-type]') : null;
      if (!btn) return;
      ptype = btn.getAttribute('data-type');
      renderTypes();
      setKv('infoScript', deployScript());
      if (val('keyword')) doSearch();
    });
    bindSearchLists();
    bindModal();
    bindHistory();
    bindEnterShortcut();

    Array.prototype.forEach.call(document.querySelectorAll('[data-pick]'), function (btn) {
      btn.addEventListener('click', function () {
        var kind = btn.getAttribute('data-kind');
        var from = btn.getAttribute('data-from');
        var target = btn.getAttribute('data-pick');
        var start = val(target) || (target === 'svnDir' ? '' : '');
        if (!start) start = rootOf(from);
        openPicker(target, kind, start, '选择目录', from);
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
      setKv('infoScript', deployScript());
      if (val('svnDir')) { workDir = val('svnDir'); setKv('infoWorkDir', workDir); refreshFiles(workDir); }
    });
  }

  return {init: init, toast: toast};
})();

document.addEventListener('DOMContentLoaded', App.init);
