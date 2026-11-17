/* 门诊订单打包 — 三栏工作台交互
   对应桌面版 门诊打包.pyw：关键字搜索 → 点选回填 → 打包 → 成品列表 → 历史。
   区别：不弹本机目录对话框（走 /api/browse 受限浏览），日志走 SSE，Node 版本走 PATH 注入。
   一个服务打三种成品（模板 / 播报机 / web运维端），类型只影响 Git 目录范围、基础包前缀与构建脚本。 */
var App = (function () {
  var cfg = {};
  var meta = {version_options: [], roots: [], project_kinds: []};
  var nodeInfo = {};
  var stream = null;
  var searchData = {svn_dirs: [], projects: []};
  var baseZips = [];
  var histRecords = [];
  var histSel = -1;
  var lastPackage = '';
  var busy = false;
  var kind = '模板';
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

  // ── 打包项目类型 ────────────────────────────────
  function kindList() {
    return meta.project_kinds || [];
  }

  function hasKind(name) {
    var list = kindList();
    for (var i = 0; i < list.length; i++) if (list[i].name === name) return true;
    return false;
  }

  // 后端是唯一规则源（meta.project_kinds），页面只做展示与联动
  function kindRule(name) {
    var list = kindList();
    for (var i = 0; i < list.length; i++) if (list[i].name === (name || kind)) return list[i];
    return list[0] || {name: '模板', zip_prefix: 'YM-801S-TLSS-', build_script: 'build',
                       node_version: '', render_lib: true, dirs: ['template']};
  }

  function renderKinds() {
    $('kinds').innerHTML = kindList().map(function (r) {
      return '<button type="button" data-kind="' + esc(r.name) + '" class="' +
        (r.name === kind ? 'on' : '') + '" title="目录 ' + esc((r.dirs || []).join('/')) +
        '* ・ npm run ' + esc(r.build_script) + '">' + esc(r.name) + '</button>';
    }).join('');
  }

  function applyKindUI() {
    var r = kindRule();
    // lib-render2 只适用于模板，其他类型藏起来并强制不勾选
    $('row155').style.display = r.render_lib ? '' : 'none';
    if (!r.render_lib) $('is155Plus').checked = false;
    $('baseZipLabel').textContent = '基础压缩包（' + r.zip_prefix + '****-FE.zip）';
    $('orderHint').textContent = '例：2026-2082上饶市人民医院 → ' + r.zip_prefix +
      'V1.5.1.262082.01001-SRSRMYY-FE.zip';
    var hint = '「' + kind + '」：Git 目录 ' + (r.dirs || []).join('/') + '*，基础包 ' +
      r.zip_prefix + '*，跑 npm run ' + r.build_script;
    if (r.node_version) hint += '，建议用 Node ' + r.node_version;
    if (r.render_lib) hint += '；1.5.5 及以上不跑 lib-render2';
    $('kindHint').textContent = hint;
  }

  // 切类型时带出该类型建议的 Node；建议为空的类型回到配置/默认版本（仍可手动改）
  function syncNodeWithKind() {
    var want = kindRule().node_version || cfg.node_version || nodeInfo.default || '';
    var sel = $('nodeVersion');
    if (!want) return;
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === want) {
        sel.value = want;
        return;
      }
    }
    toast('「' + kind + '」建议 Node ' + want + '，本机未检测到，保持当前版本', 5000);
  }

  function setKind(name, opt) {
    opt = opt || {};
    if (!name || !hasKind(name)) return;
    if (name === kind && !opt.force) return;
    kind = name;
    renderKinds();
    applyKindUI();
    if (opt.node !== false) syncNodeWithKind();
    if (opt.persist !== false) req('POST', '/api/config', {project_kind: kind});
    var r = kindRule();
    setNotice('已切换为「' + kind + '」：基础包 ' + r.zip_prefix + '****-FE.zip，构建 npm run ' +
      r.build_script + '；建议重新搜索一次，列出的 Git 项目会跟着变');
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
      if (hasKind(cfg.project_kind)) kind = cfg.project_kind;
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
      renderKinds();
      applyKindUI();
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
    req('POST', '/api/search', {keyword: keyword, project_kind: kind}).then(function (res) {
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
    if (!svn.length && !git.length) {
      setNotice(data.notice || '未找到匹配目录');
    } else if (!git.length) {
      setNotice('SVN 有 ' + svn.length + ' 个目录，但「' + kind + '」下没匹配到 Git 分支' +
        '（只看目录名 ' + (kindRule().dirs || []).join('/') + '* 的仓库），类型不对就切一下重试');
    }
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
      prefill({svn_dir: item.path, project_kind: kind}, function (d) {
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
      prefill({project_dir: item.path, project_kind: kind}, function (d) {
        if (d.project_version) setVersion(d.project_version);
        setNotice(d.version_notice || (d.git_branch ? '分支：' + d.git_branch : ''));
        if (d.has_build_script === false) {
          toast('⚠️ 该项目没有 npm run ' + (d.build_script || kindRule().build_script) +
                '，现有：' + ((d.available_scripts || []).join('、') || '无'), 6000);
        }
      });
    });
  }

  // 手工选了项目目录：除回填分支/版本外，还要核对目录属于哪个类型（后端会反推）
  function syncProjectDir(path) {
    prefill({project_dir: path, project_kind: kind}, function (d) {
      if (d.project_version) setVersion(d.project_version);
      if (d.dir_kind && d.dir_kind !== kind) {
        setKind(d.dir_kind, {persist: true, force: true});
        toast(d.kind_notice || ('目录属于「' + d.dir_kind + '」，已自动切换类型'), 6000);
        return;
      }
      if (d.has_build_script === false) {
        toast('⚠️ 该项目没有 npm run ' + (d.build_script || kindRule().build_script) +
              '，现有：' + ((d.available_scripts || []).join('、') || '无'), 6000);
        return;
      }
      setNotice(d.git_branch ? '分支 ' + d.git_branch + '，构建 npm run ' + kindRule().build_script
                             : '没读到 git 分支，请确认选的是仓库目录');
    });
  }

  // 手工选了基础压缩包：前缀与类型不配时先提醒，别等到校验才看到
  function checkBaseZip(name) {
    var rule = kindRule();
    if (!name || name.indexOf(rule.zip_prefix) === 0) return;
    var owner = '其他';
    kindList().forEach(function (k) {
      if (name.indexOf(k.zip_prefix) === 0) owner = k.name;
    });
    toast('⚠️ 这是「' + owner + '」的基础包，与当前类型「' + kind + '」不配（应以 ' +
          rule.zip_prefix + ' 开头）', 6000);
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
      if (picker.target === 'baseZip') checkBaseZip(li.getAttribute('data-file'));
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
      if (picker.target === 'projectDir') syncProjectDir(picker.path);
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
      project_kind: kind,
      project_dir: val('projectDir'),
      output_dir: val('outputDir'),
      order_info: val('orderInfo'),
      project_version: currentVersion(),
      base_zip_path: val('baseZip'),
      custom_zip_name: val('customZip'),
      // 非模板类型没有 lib-render2，勾了也不带上，避免后端白跑一步
      is_version_155_plus: kindRule().render_lib ? $('is155Plus').checked : false,
      auto_commit_svn: $('autoCommitSvn').checked,
      node_version: $('nodeVersion').value
    };
  }

  function startPack() {
    if (busy) { toast('已有任务在跑'); return; }
    askSysNotifyOnStart();
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

  // ── 打包完成通知（右下角卡片）──────────────────
  var NOTIFY_MS = 10000;   // 自动消失时间，鼠标悬停暂停计时
  var NOTIFY_MAX = 3;      // 最多同时保留几条

  function notifyDone(result) {
    var pkg = result.package_path || lastPackage;
    if (!pkg) return;
    var name = result.package_name || pkg.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
    // 通知统一用后端默认图（本地文件，不走外网随机头像）
    var url = '/api/notify/icon';
    addNotifyCard(name, pkg, url);
    sendSysNotify(name, pkg, url);
  }

  function addNotifyCard(name, pkg, avatarUrl) {
    var card = document.createElement('div');
    card.className = 'notify-card';

    var avatar = document.createElement('img');
    avatar.className = 'notify-avatar';
    avatar.alt = '';
    // 头像来自远程 URL，断网/图挂了就地换成默认图标，不留碎图
    avatar.onerror = function () {
      var fb = document.createElement('div');
      fb.className = 'notify-avatar notify-avatar-fallback';
      fb.textContent = '📦';
      if (avatar.parentNode === card) card.replaceChild(fb, avatar);
    };
    card.appendChild(avatar);

    var body = document.createElement('div');
    body.className = 'notify-body';
    var title = document.createElement('div');
    title.className = 'notify-title';
    title.textContent = '✅ 打包完成';
    var nameEl = document.createElement('div');
    nameEl.className = 'notify-name';
    nameEl.textContent = name;
    nameEl.title = pkg;
    var actions = document.createElement('div');
    actions.className = 'notify-actions';
    var openBtn = document.createElement('button');
    openBtn.className = 'mini';
    openBtn.textContent = '打开包目录';
    openBtn.addEventListener('click', function () { openPackageDir(pkg, openBtn); });
    var closeBtn = document.createElement('button');
    closeBtn.className = 'mini notify-close';
    closeBtn.textContent = '✕';
    closeBtn.title = '关闭通知';
    closeBtn.addEventListener('click', function () { dismissNotify(card); });
    actions.appendChild(openBtn);
    actions.appendChild(closeBtn);
    body.appendChild(title);
    body.appendChild(nameEl);
    body.appendChild(actions);
    card.appendChild(body);

    $('notifyStack').appendChild(card);
    if (avatarUrl) avatar.src = avatarUrl; else avatar.onerror();
    trimNotify();
    armNotifyTimer(card);
  }

  // 悬停暂停：记住剩余时间，移开后接着倒计时（至少再给 1.2s，不会一移开就没了）
  function armNotifyTimer(card) {
    card._left = NOTIFY_MS;
    card._tick = function () {
      card._since = Date.now();
      card._timer = setTimeout(function () { dismissNotify(card); }, card._left);
    };
    card.addEventListener('mouseenter', function () {
      clearTimeout(card._timer);
      card._left = Math.max(1200, card._left - (Date.now() - card._since));
    });
    card.addEventListener('mouseleave', card._tick);
    card._tick();
  }

  function dismissNotify(card) {
    if (!card || card._closing) return;
    card._closing = true;
    clearTimeout(card._timer);
    card.className = 'notify-card out';
    setTimeout(function () {
      if (card.parentNode) card.parentNode.removeChild(card);
    }, 200);
  }

  function trimNotify() {
    var cards = $('notifyStack').querySelectorAll('.notify-card');
    for (var i = 0; i < cards.length - NOTIFY_MAX; i++) dismissNotify(cards[i]);
  }

  function openPackageDir(pkg, btn) {
    btn.disabled = true;
    req('POST', '/api/open/dir', {path: pkg}).then(function (res) {
      btn.disabled = false;
      if (!res.ok) { toast(detailOf(res).message || '打开目录失败'); return; }
      toast('已在资源管理器中选中该包：' + (res.data.dir || ''));
    }).catch(function (e) {
      btn.disabled = false;
      toast('打开目录请求异常：' + e);
    });
  }

  // ── Windows 系统通知（Notification API，页内卡片之外的系统级弹窗）──
  var SYS_NOTIFY_KEY = 'packager-sys-notify';   // '0' = 用户手动关闭

  function sysNotifySupported() { return 'Notification' in window; }

  function sysNotifyOn() {
    return sysNotifySupported() && Notification.permission === 'granted'
      && localStorage.getItem(SYS_NOTIFY_KEY) !== '0';
  }

  function renderSysNotifyBtn() {
    var btn = $('btnSysNotify');
    if (!sysNotifySupported()) {
      btn.disabled = true;
      btn.textContent = '🔕 不支持通知';
      btn.title = '当前浏览器不支持系统通知';
      return;
    }
    if (Notification.permission === 'denied') {
      btn.textContent = '🔕 通知被禁';
      btn.title = '通知权限被禁用：点地址栏锁图标 → 站点设置 → 允许通知，再刷新页面';
      return;
    }
    var on = sysNotifyOn();
    btn.textContent = on ? '🔔 系统通知：开' : '🔔 系统通知：关';
    btn.title = on ? '点击关闭 Windows 系统通知（页内卡片不受影响）'
                   : '点击开启 Windows 系统通知（首次需要授权）';
  }

  function initSysNotify() {
    renderSysNotifyBtn();
    $('btnSysNotify').addEventListener('click', function () {
      if (!sysNotifySupported()) return;
      if (Notification.permission === 'denied') {
        toast('通知权限被禁用：点地址栏锁图标 → 站点设置 → 允许通知，再刷新页面');
        return;
      }
      if (Notification.permission !== 'granted') {
        Notification.requestPermission().then(function (p) {
          renderSysNotifyBtn();
          toast(p === 'granted' ? '已开启系统通知，打包完成会弹 Windows 通知'
                                : '未授权通知权限，将只使用页内通知');
        });
        return;
      }
      var off = localStorage.getItem(SYS_NOTIFY_KEY) === '0';
      localStorage.setItem(SYS_NOTIFY_KEY, off ? '1' : '0');
      renderSysNotifyBtn();
      toast(off ? '已开启系统通知' : '已关闭系统通知（页内卡片不受影响）');
    });
  }

  // 点「开始打包」时顺带申请权限（浏览器要求用户手势内发起）
  function askSysNotifyOnStart() {
    if (sysNotifySupported() && Notification.permission === 'default'
        && localStorage.getItem(SYS_NOTIFY_KEY) !== '0') {
      Notification.requestPermission().then(renderSysNotifyBtn);
    }
  }

  function sendSysNotify(name, pkg, avatarUrl) {
    if (!sysNotifyOn()) return;
    try {
      var n = new Notification('✅ 打包完成', {
        body: name,
        icon: avatarUrl || undefined,
        tag: 'packager-done-' + name   // 同一包名替换旧通知，不无限堆叠
      });
      n.onclick = function () {
        window.focus();
        openPackageDir(pkg, {});   // 复用页内按钮逻辑：资源管理器选中该包
        n.close();
      };
    } catch (e) { /* 系统通知失败就静默回落，页内卡片仍在 */ }
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
        notifyDone(ev.result || {});
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
        return '<li data-h="' + i + '"><div class="name">[' + esc(r.project_kind || '模板') + '] ' +
          esc(r.order_info || pkgName(r) || '(未填订单)') + '</div>' +
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
    // 类型先恢复，否则 155 勾选框在别的类型下还藏着，写了值也看不到
    if (r.project_kind) setKind(r.project_kind, {node: false, force: true});
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
      req('POST', '/api/prefill', {svn_dir: dir, project_kind: kind}).then(function (res) {
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
    $('kinds').addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('button[data-kind]') : null;
      if (btn) setKind(btn.getAttribute('data-kind'));
    });
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
    initSysNotify();
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
