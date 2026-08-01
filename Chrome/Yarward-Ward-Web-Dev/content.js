(function () {
    const url = new URL(window.location.href);

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

    // ===== 判断是否为纯数字IP地址 =====
    function isNumericIP(hostname) {
        return /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname);
    }

    // ==============================
    // 操作弹窗
    // ==============================
    function showOperationDialog(sqlType, title) {
        const existing = document.getElementById('ward-dialog-overlay');
        if (existing) existing.remove();

        const dbHost = url.hostname;
        const apiUrl = 'http://192.168.18.228:28019/yh-mock/create-host-data';

        const overlay = document.createElement('div');
        overlay.id = 'ward-dialog-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'ward-dialog';

        // 操作类型对应的字段配置
        const fieldConfig = {
            insertUser:     { label: '添加的账号名',     name: 'username_emp',     placeholder: '如 gz',          defaultVal: 'gz' },
            deleteip:       { label: '需要删除设备的IP', name: 'deleteip',         placeholder: '如 192.168.3.199', defaultVal: '' },
            addlabelclass:  { label: '添加分类数量',     name: 'addlabelclassnum', placeholder: '如 5',           defaultVal: '5' },
            addlabel:       { label: '添加护理标签数量', name: 'addlabelnum',      placeholder: '如 15',          defaultVal: '15' }
        };
        const field = fieldConfig[sqlType];

        dialog.innerHTML = `
            <div class="ward-dialog-header">
                <span>${title}</span>
                <span class="ward-dialog-close">&times;</span>
            </div>
            <div class="ward-dialog-body">
                <div class="ward-form-row">
                    <div class="ward-form-group">
                        <label>数据库地址</label>
                        <input type="text" name="dbHost" value="${dbHost}" placeholder="自动从页面URL提取">
                    </div>
                    <div class="ward-form-group">
                        <label>端口</label>
                        <input type="text" name="dbPort" value="3306">
                    </div>
                </div>
                <div class="ward-form-row">
                    <div class="ward-form-group">
                        <label>数据库名</label>
                        <input type="text" name="dbName" value="YHDB">
                    </div>
                    <div class="ward-form-group">
                        <label>用户名</label>
                        <input type="text" name="username" value="root">
                    </div>
                </div>
                <div class="ward-form-group">
                    <label>密码</label>
                    <input type="text" name="password" value="Yahua@3585668" list="ward-pwd-list">
                    <datalist id="ward-pwd-list">
                        <option value="Yahua@3585668">4.0</option>
                        <option value="Yahua3585668yh">3.0</option>
                        <option value="123456">123456</option>
                    </datalist>
                </div>
                <div class="ward-form-group">
                    <label>${field.label}</label>
                    <input type="text" name="opValue" value="${field.defaultVal}" placeholder="${field.placeholder}">
                </div>
                <div class="ward-form-group ward-checkbox-row">
                    <label><input type="checkbox" name="directExecution"> 直接执行SQL</label>
                    <span class="ward-hint">勾选后生成并执行SQL，不勾选仅生成SQL</span>
                </div>
                <button class="ward-submit-btn" type="button">确认执行</button>
                <div class="ward-result" style="display:none"></div>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // 阻止表单内点击冒泡到 overlay 导致误关
        dialog.addEventListener('click', (e) => e.stopPropagation());
        // 点击遮罩关闭
        overlay.addEventListener('click', () => overlay.remove());
        // 关闭按钮
        dialog.querySelector('.ward-dialog-close').addEventListener('click', () => overlay.remove());

        // 提交
        dialog.querySelector('.ward-submit-btn').addEventListener('click', async () => {
            const getVal = (n) => dialog.querySelector(`input[name="${n}"]`).value.trim();

            const host = getVal('dbHost');
            if (!host) { showToast('❌ 请输入数据库地址', 'error'); return; }

            const requestData = {
                dbHost: host,
                dbPort: getVal('dbPort'),
                dbName: getVal('dbName'),
                username: getVal('username'),
                password: getVal('password'),
                sqlType: sqlType,
                directExecution: dialog.querySelector('input[name="directExecution"]').checked
            };
            requestData[field.name] = getVal('opValue');

            const btn = dialog.querySelector('.ward-submit-btn');
            const resultDiv = dialog.querySelector('.ward-result');

            btn.disabled = true;
            btn.textContent = '⏳ 处理中...';
            resultDiv.style.display = 'block';
            resultDiv.textContent = '正在请求...';
            resultDiv.className = 'ward-result ward-result-info';

            try {
                const response = await fetch(apiUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestData)
                });
                const res = await response.json();
                if (res.status === 'error') {
                    resultDiv.textContent = '❌ ' + (res.message || '操作失败');
                    resultDiv.className = 'ward-result ward-result-error';
                } else {
                    resultDiv.textContent = '✅ ' + (res.message || '操作成功');
                    resultDiv.className = 'ward-result ward-result-success';
                }
            } catch (e) {
                resultDiv.textContent = '❌ 请求失败: ' + e.message;
                resultDiv.className = 'ward-result ward-result-error';
            }

            btn.disabled = false;
            btn.textContent = '确认执行';
        });
    }

    // ===== 异步初始化 =====
    async function init() {
        const config = await ConfigManager.getConfig();
        // 规则1：端口匹配配置的调试端口
        // 规则2：纯数字IP + 80端口（默认HTTP端口，url.port为空）自动加载
        const portMatch = url.port === config.debugPort;
        const isDefaultIP = isNumericIP(url.hostname) && (url.port === '' || url.port === '80');
        if (!portMatch && !isDefaultIP) return;
        createFloatingMenu(config);
    }

    // ==============================
    // 加载自定义按钮图片
    // ==============================
    function applyButtonImages(toggleBtn, config) {
        const collapsedUrl = config.btnImageCollapsed;
        const expandedUrl = config.btnImageExpanded;
        if (!collapsedUrl && !expandedUrl) return;

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
                console.warn('[Ward] 收缩态图片加载失败:', collapsedUrl);
            };
            img.src = collapsedUrl;
        }

        if (expandedUrl) {
            const img = new Image();
            img.onload = () => {
                toggleBtn.dataset.expandedImageUrl = expandedUrl;
            };
            img.onerror = () => {
                console.warn('[Ward] 展开态图片加载失败:', expandedUrl);
                toggleBtn.dataset.expandedImageUrl = '';
            };
            img.src = expandedUrl;
        }

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
        toggleBtn.title = '病房开发辅助';

        applyButtonImages(toggleBtn, config);

        const menuItems = [
            { text: '👤 添加用户', action: () => showOperationDialog('insertUser', '添加用户') },
            { text: '🗑️ 删除某IP占用的设备', action: () => showOperationDialog('deleteip', '删除某IP占用的设备') },
            { text: '📂 添加护理标签分类', action: () => showOperationDialog('addlabelclass', '添加护理标签分类') },
            { text: '🏷️ 添加护理标签（每分类）', action: () => showOperationDialog('addlabel', '添加护理标签【每个分类下面都添加】') }
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
                try { item.action(); } catch (err) { console.error('[Ward] 菜单动作执行失败:', err); }
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

        function clampPosition(left, top) {
            const btnW = container.offsetWidth;
            const btnH = container.offsetHeight;
            const maxLeft = window.innerWidth - btnW;
            const maxTop = window.innerHeight - btnH;
            return {
                left: Math.max(0, Math.min(left, maxLeft)),
                top: Math.max(0, Math.min(top, maxTop))
            };
        }

        function onDragStart(e) {
            if (e.button !== 0) return;
            isDragging = true;
            hasMoved = false;
            startX = e.clientX;
            startY = e.clientY;
            const rect = container.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;
            toggleBtn.classList.add('dragging');
            if (menuOpen) closeMenu();
            e.preventDefault();
        }

        function onDragMove(e) {
            if (!isDragging) return;
            const deltaX = e.clientX - startX;
            const deltaY = e.clientY - startY;
            if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) hasMoved = true;
            const pos = clampPosition(initialLeft + deltaX, initialTop + deltaY);
            container.style.right = 'auto';
            container.style.bottom = 'auto';
            container.style.left = pos.left + 'px';
            container.style.top = pos.top + 'px';
        }

        function onDragEnd() {
            if (!isDragging) return;
            isDragging = false;
            toggleBtn.classList.remove('dragging');
        }

        toggleBtn.addEventListener('mousedown', onDragStart);
        window.addEventListener('mousemove', onDragMove);
        window.addEventListener('mouseup', onDragEnd);
        window.addEventListener('mouseleave', onDragEnd);

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => document.body.appendChild(container));
        } else {
            document.body.appendChild(container);
        }
    }

    // ===== 启动 =====
    init();
})();
