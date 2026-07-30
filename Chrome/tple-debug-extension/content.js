(function () {
    const url = new URL(window.location.href);

    // ===== 姓名库 =====
    const LAST_NAMES = ['张', '李', '王', '赵', '钱', '孙', '周', '吴', '郑', '冯', '陈', '褚', '卫', '蒋', '沈', '韩', '杨', '朱', '秦', '尤', '许', '何', '吕', '施'];
    const FIRST_NAMES = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '文', '武', '明', '华', '国', '建', '志', '伟', '芳', '秀', '英', '兰', '梅', '春'];

    function generateRandomName() {
        return LAST_NAMES[Math.floor(Math.random() * LAST_NAMES.length)]
             + FIRST_NAMES[Math.floor(Math.random() * FIRST_NAMES.length)];
    }

    function generateSequentialId(startId, index) {
        return String(startId + index).padStart(3, '0');
    }

    function getCurrentTime() {
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    }

    // ===== 解析 Raw Headers =====
    function parseRawHeaders(rawStr) {
        const headers = {};
        if (!rawStr || !rawStr.trim()) return headers;
        rawStr.trim().split('\n').forEach(line => {
            const idx = line.indexOf(':');
            if (idx > 0) {
                const key = line.substring(0, idx).trim();
                const value = line.substring(idx + 1).trim();
                if (key && value) headers[key] = value;
            }
        });
        return headers;
    }

    // ===== Toast 提示 =====
    function showToast(message, type) {
        let toast = document.getElementById('tple-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'tple-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.className = 'show' + (type ? ' ' + type : '');
        setTimeout(() => { toast.className = ''; }, 2500);
    }

    // ===== 异步初始化 =====
    async function init() {
        const config = await ConfigManager.getConfig();
        if (url.port !== config.debugPort) return;

        // 匹配 iframeIndex 相关页面，自动跳转
        if (
            url.pathname === config.autoRedirectPath ||
            url.hash.includes('/iframeIndex') ||
            (url.pathname === '/tpleditor/design/' && url.hash.startsWith('#/iframeIndex'))
        ) {
            const params = new URLSearchParams(url.search);
            const hashSearch = url.hash.split('?')[1] || '';
            const hashParams = new URLSearchParams(hashSearch);
            for (const [key, value] of hashParams) params.set(key, value);
            const queryString = params.toString();
            const targetUrl = `http://${config.targetHost}:${config.targetPort}/#/iframeIndex${queryString ? '?' + queryString : ''}`;
            if (confirm(`是否打开 ${config.targetHost}:${config.targetPort} 的调试页面？\n\n目标地址：${targetUrl}`)) {
                window.location.replace(targetUrl);
            }
            return;
        }

        if (url.hash.includes('/sbIndex')) return;

        createFloatingMenu(config);
    }

    // ==============================
    // 加载自定义按钮图片
    // ==============================
    function applyButtonImages(toggleBtn, config) {
        const collapsedUrl = config.btnImageCollapsed;
        const expandedUrl = config.btnImageExpanded;
        if (!collapsedUrl && !expandedUrl) return;

        // 尝试加载收缩态图片
        if (collapsedUrl) {
            const img = new Image();
            img.onload = () => {
                toggleBtn.style.backgroundImage = `url("${collapsedUrl}")`;
                toggleBtn.style.backgroundSize = 'cover';
                toggleBtn.style.backgroundPosition = 'center';
                toggleBtn.textContent = '';
                toggleBtn.classList.add('has-custom-image');
            };
            img.onerror = () => {
                console.warn('[TPLE] 收缩态图片加载失败:', collapsedUrl);
            };
            img.src = collapsedUrl;
        }

        // 尝试加载展开态图片
        if (expandedUrl) {
            const img = new Image();
            img.onload = () => {
                toggleBtn.dataset.expandedImageUrl = expandedUrl;
            };
            img.onerror = () => {
                console.warn('[TPLE] 展开态图片加载失败:', expandedUrl);
                toggleBtn.dataset.expandedImageUrl = '';
            };
            img.src = expandedUrl;
        }

        // 监听展开/收缩状态切换，替换背景图
        const observer = new MutationObserver(() => {
            const isExpanded = toggleBtn.classList.contains('expanded');
            if (isExpanded && toggleBtn.dataset.expandedImageUrl) {
                toggleBtn.style.backgroundImage = `url("${toggleBtn.dataset.expandedImageUrl}")`;
            } else if (!isExpanded && collapsedUrl) {
                toggleBtn.style.backgroundImage = `url("${collapsedUrl}")`;
            }
        });
        observer.observe(toggleBtn, { attributes: true, attributeFilter: ['class'] });
    }

    // ==============================
    // 浮动菜单
    // ==============================
    function createFloatingMenu(config) {
        const container = document.createElement('div');
        container.id = 'tple-float-menu';

        const toggleBtn = document.createElement('div');
        toggleBtn.id = 'tple-toggle-btn';
        toggleBtn.textContent = '+';
        toggleBtn.title = '调试工具';

        // 尝试加载自定义按钮图片
        applyButtonImages(toggleBtn, config);

        const menuItems = [
            { text: '🔍 打开调试页面', action: () => openDebugPage(config) },
            { text: '📋 复制 localStorage', action: () => copyLocalStorage() },
            { text: '🏥 模拟批量挂号', action: () => showBatchPanel(config) },
            { text: '🔎 打印 Storage 内容', action: () => dumpAllStorage() }
        ];

        const itemEls = [];
        menuItems.forEach((item) => {
            const el = document.createElement('div');
            el.className = 'tple-menu-item';
            el.textContent = item.text;
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                if (hasMoved) return;
                try { item.action(); } catch (err) { console.error('[TPLE] 菜单动作执行失败:', err); }
                closeMenu();
            });
            container.appendChild(el);
            itemEls.push(el);
        });

        container.appendChild(toggleBtn);

        let menuOpen = false;
        let autoCollapseTimer = null;

        function closeMenu() {
            menuOpen = false;
            toggleBtn.classList.remove('expanded');
            itemEls.forEach(ie => ie.classList.remove('visible'));
            if (autoCollapseTimer) { clearTimeout(autoCollapseTimer); autoCollapseTimer = null; }
        }

        function startAutoCollapse() {
            if (autoCollapseTimer) clearTimeout(autoCollapseTimer);
            const timeout = parseInt(config.autoCollapseTimeout) || 0;
            if (timeout > 0) {
                autoCollapseTimer = setTimeout(() => {
                    if (menuOpen) closeMenu();
                }, timeout * 1000);
            }
        }

        toggleBtn.addEventListener('click', () => {
            if (hasMoved) return;
            menuOpen = !menuOpen;
            toggleBtn.classList.toggle('expanded', menuOpen);
            itemEls.forEach((el, i) => {
                if (menuOpen) {
                    setTimeout(() => el.classList.add('visible'), i * 50);
                } else {
                    el.classList.remove('visible');
                }
            });
            if (menuOpen) startAutoCollapse();
            else if (autoCollapseTimer) { clearTimeout(autoCollapseTimer); autoCollapseTimer = null; }
        });

        // 拖拽功能
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;
        let hasMoved = false;

        toggleBtn.addEventListener('mousedown', (e) => {
            isDragging = true;
            hasMoved = false;
            startX = e.clientX;
            startY = e.clientY;
            const rect = toggleBtn.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
            toggleBtn.classList.add('dragging');
            if (menuOpen) {
                closeMenu();
            }
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const deltaX = e.clientX - startX;
            const deltaY = e.clientY - startY;
            if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) hasMoved = true;
            container.style.right = 'auto';
            container.style.bottom = 'auto';
            container.style.left = `${initialLeft + deltaX}px`;
            container.style.top = `${initialTop + deltaY}px`;
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                toggleBtn.classList.remove('dragging');
            }
        });

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => document.body.appendChild(container));
        } else {
            document.body.appendChild(container);
        }
    }

    // ==============================
    // 功能 1：打开调试页面
    // ==============================
    function openDebugPage(config) {
        window.open(`${url.protocol}//${url.host}${config.debugPath}`, '_blank');
    }

    // ==============================
    // 功能 2：复制 localStorage 数据
    // ==============================
    function copyLocalStorage() {
        var script = [];
        for (var i = 0; i < localStorage.length; i++) {
            var key = localStorage.key(i);
            var value = localStorage.getItem(key);
            script.push(`localStorage.setItem('${key}', ${JSON.stringify(value)});`);
        }
        var token = localStorage.getItem('token');
        if (token) script.push(`document.cookie = "token=${token}; path=/";`);
        var output = script.join('\n');

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(output).then(() => {
                showToast('✅ localStorage 已复制到剪贴板', 'success');
            }).catch(() => fallbackCopy(output));
        } else {
            fallbackCopy(output);
        }
        console.log(output);
    }

    function fallbackCopy(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showToast('✅ localStorage 已复制到剪贴板', 'success');
        } catch (e) {
            showToast('❌ 复制失败，请手动复制', 'error');
        }
        document.body.removeChild(textarea);
    }

    // ===== 调试：打印所有 storage 到控制台 =====
    function dumpAllStorage() {
        console.group('[TPLE] === localStorage ===');
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            const val = localStorage.getItem(key);
            console.log(`  ${key}: ${val.length > 120 ? val.substring(0, 120) + '...' : val}`);
        }
        console.groupEnd();
        console.group('[TPLE] === sessionStorage ===');
        for (let i = 0; i < sessionStorage.length; i++) {
            const key = sessionStorage.key(i);
            const val = sessionStorage.getItem(key);
            console.log(`  ${key}: ${val.length > 120 ? val.substring(0, 120) + '...' : val}`);
        }
        console.groupEnd();
        console.log('[TPLE] === cookies ===');
        console.log(document.cookie);
        showToast('✅ 已打印所有 storage 到控制台', 'success');
    }

    // ==============================
    // 功能 3：模拟批量挂号（手动输入 Headers + Body）
    // ==============================
    const DEFAULT_RAW_HEADERS = `POST /clinic/api/qcss/register/made HTTP/1.1
Accept: application/json, text/plain, */*
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9
Content-Type: application/json;charset=UTF-8
clientid: e5cd7e4891bf95d1d19206ce24a7b32e`;

    const DEFAULT_BODY = JSON.stringify({
        "hasBook": 1,
        "registerTime": "2026-07-30 17:19:00",
        "signTime": "2026-07-30 17:19:00",
        "patientName": "李思思",
        "patientIdNo": "001",
        "sex": "1",
        "age": 0,
        "ageType": "2",
        "hasPay": 0,
        "registerObjId": 1,
        "orderTags": ""
    }, null, 2);

    function showBatchPanel(config) {
        const existing = document.getElementById('tple-batch-panel');
        if (existing) existing.remove();

        const apiUrl = `${url.protocol}//${url.host}${config.batchApiPath}`;

        // 从 storage 读取上次使用的 headers 和 body
        chrome.storage.local.get(['tple_raw_headers', 'tple_request_body'], (result) => {
            const savedHeaders = result.tple_raw_headers || DEFAULT_RAW_HEADERS;
            const savedBody = result.tple_request_body || DEFAULT_BODY;
            buildPanel(config, apiUrl, savedHeaders, savedBody);
        });
    }

    function buildPanel(config, apiUrl, savedHeaders, savedBody) {
        const panel = document.createElement('div');
        panel.id = 'tple-batch-panel';
        panel.innerHTML = `
            <div class="panel-header">
                <span>🏥 模拟批量挂号</span>
                <div class="panel-header-btns">
                    <button class="panel-header-btn" id="tple-save-config" title="保存配置">💾</button>
                    <span class="panel-close" id="tple-panel-close">✕</span>
                </div>
            </div>
            <div class="panel-body">
                <label>接口地址</label>
                <input type="text" id="tple-batch-url" value="${apiUrl}" readonly>
                <div class="panel-row">
                    <div>
                        <label>调用次数</label>
                        <input type="number" id="tple-batch-times" value="${config.batchCallTimes}" min="1" max="500">
                    </div>
                    <div>
                        <label>起始 ID</label>
                        <input type="number" id="tple-batch-start-id" value="${config.batchStartId}" min="0">
                    </div>
                    <div>
                        <label>动态字段</label>
                        <input type="text" id="tple-batch-dynamic" value="patientName,patientIdNo">
                    </div>
                </div>
                <label>📤 请求头 (Raw 格式，从 DevTools Network 复制)</label>
                <textarea id="tple-raw-headers" rows="6" placeholder="粘贴完整 Request Headers...">${savedHeaders}</textarea>
                <label>📥 请求体 (JSON)</label>
                <textarea id="tple-raw-body" rows="8" placeholder="粘贴 JSON 请求体...">${savedBody}</textarea>
                <button class="panel-btn" id="tple-batch-start">🚀 开始批量挂号</button>
                <div class="tple-progress-bar" id="tple-batch-progress" style="display:none">
                    <div class="tple-progress-fill" id="tple-batch-progress-fill"></div>
                </div>
                <div class="tple-result-log" id="tple-batch-result" style="display:none"></div>
            </div>
        `;
        document.body.appendChild(panel);

        // 关闭
        panel.querySelector('#tple-panel-close').addEventListener('click', (e) => {
            e.stopPropagation();
            panel.remove();
        });

        // 保存配置
        panel.querySelector('#tple-save-config').addEventListener('click', (e) => {
            e.stopPropagation();
            const rawHeaders = panel.querySelector('#tple-raw-headers').value;
            const rawBody = panel.querySelector('#tple-raw-body').value;
            chrome.storage.local.set({ tple_raw_headers: rawHeaders, tple_request_body: rawBody });
            showToast('✅ 配置已保存', 'success');
        });

        // 开始批量挂号
        panel.querySelector('#tple-batch-start').addEventListener('click', (e) => {
            e.stopPropagation();
            const rawHeadersStr = panel.querySelector('#tple-raw-headers').value.trim();
            const bodyStr = panel.querySelector('#tple-raw-body').value.trim();
            const times = parseInt(panel.querySelector('#tple-batch-times').value) || 10;
            const startId = parseInt(panel.querySelector('#tple-batch-start-id').value) || 1;
            const dynamicFields = panel.querySelector('#tple-batch-dynamic').value || 'patientName,patientIdNo';

            if (!rawHeadersStr) {
                showToast('❌ 请粘贴请求头', 'error');
                return;
            }

            // 解析 headers
            const headers = parseRawHeaders(rawHeadersStr);
            if (Object.keys(headers).length === 0) {
                showToast('❌ 未解析到有效 Headers，请检查格式', 'error');
                return;
            }

            // 验证 body JSON
            let templateBody;
            try {
                templateBody = JSON.parse(bodyStr);
            } catch (err) {
                showToast('❌ 请求体 JSON 格式错误: ' + err.message, 'error');
                return;
            }

            // 自动保存
            chrome.storage.local.set({ tple_raw_headers: rawHeadersStr, tple_request_body: bodyStr });

            executeBatchRegister(apiUrl, headers, templateBody, times, startId, dynamicFields, panel);
        });
    }

    // ===== 执行批量挂号 =====
    async function executeBatchRegister(apiUrl, headers, templateBody, times, startId, dynamicFields, panel) {
        const btn = panel.querySelector('#tple-batch-start');
        const progressBar = panel.querySelector('#tple-batch-progress');
        const progressFill = panel.querySelector('#tple-batch-progress-fill');
        const resultLog = panel.querySelector('#tple-batch-result');

        btn.disabled = true;
        btn.textContent = '⏳ 执行中...';
        progressBar.style.display = 'block';
        resultLog.style.display = 'block';
        resultLog.innerHTML = '';

        // 确保 Content-Type
        if (!Object.keys(headers).some(k => k.toLowerCase() === 'content-type')) {
            headers['Content-Type'] = 'application/json;charset=UTF-8';
        }

        const fields = dynamicFields.split(',').map(f => f.trim());
        let successCount = 0;

        console.log('[TPLE] 批量挂号开始:', { apiUrl, times, startId, headerCount: Object.keys(headers).length });
        addResultItem(resultLog, `📋 发起 ${times} 次请求 | Headers: ${Object.keys(headers).length} 个字段`, 'info');

        for (let i = 0; i < times; i++) {
            const body = { ...templateBody };
            const currentTime = getCurrentTime();
            if ('registerTime' in body) body.registerTime = currentTime;
            if ('signTime' in body) body.signTime = currentTime;

            let currentPatientId = null;
            for (const field of fields) {
                if (field === 'patientName') {
                    body.patientName = generateRandomName();
                } else if (field === 'patientIdNo') {
                    const pid = generateSequentialId(startId, i);
                    body.patientIdNo = pid;
                    currentPatientId = pid;
                    if ('orderNo' in body) body.orderNo = pid;
                }
            }

            try {
                const response = await fetch(apiUrl, {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify(body),
                    credentials: 'include'
                });

                const respText = await response.text();
                const statusText = response.ok ? '✅' : '⚠️';
                const statusClass = response.ok ? 'success' : 'error';
                const idInfo = currentPatientId ? ` | ID: ${currentPatientId} | ${body.patientName}` : '';
                addResultItem(resultLog, `${statusText} 第${i + 1}次 → ${response.status} ${respText.substring(0, 80)}${idInfo}`, statusClass);

                if (response.ok) successCount++;
            } catch (e) {
                console.error('[TPLE] 请求失败:', e);
                addResultItem(resultLog, `❌ 第${i + 1}次失败: ${e.message}`, 'error');
            }

            progressFill.style.width = `${((i + 1) / times) * 100}%`;
            resultLog.scrollTop = resultLog.scrollHeight;
            await new Promise(r => setTimeout(r, 100));
        }

        btn.disabled = false;
        btn.textContent = '🚀 开始批量挂号';
        addResultItem(resultLog, `🎉 完成！成功 ${successCount}/${times} 次（ID: ${generateSequentialId(startId, 0)} ~ ${generateSequentialId(startId, times - 1)}）`, 'info');
    }

    function addResultItem(container, text, className) {
        const item = document.createElement('div');
        item.className = 'tple-result-item ' + (className || '');
        item.textContent = text;
        container.appendChild(item);
        container.scrollTop = container.scrollHeight;
    }

    // ===== 启动 =====
    init();
})();
