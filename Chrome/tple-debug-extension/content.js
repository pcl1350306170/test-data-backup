(function () {
    const url = new URL(window.location.href);

    // 异步初始化
    async function init() {
        const config = await ConfigManager.getConfig();

        // ===== 条件 1：端口必须是配置的端口 =====
        if (url.port !== config.debugPort) return;

        // ===== 条件 2：匹配 iframeIndex 相关页面，自动跳转 =====
        if (
            url.pathname === config.autoRedirectPath ||
            url.hash.includes('/iframeIndex') ||
            (url.pathname === '/tpleditor/design/' && url.hash.startsWith('#/iframeIndex'))
        ) {
            // 获取所有查询参数（包括 ? 后面的）
            const params = new URLSearchParams(url.search);
            // 如果 hash 中有 ?，也要提取（如 #/iframeIndex?xxx）
            const hashSearch = url.hash.split('?')[1] || '';
            const hashParams = new URLSearchParams(hashSearch);

            // 合并 search 和 hash 中的参数（hash 优先级更高）
            for (const [key, value] of hashParams) {
                params.set(key, value);
            }

            const queryString = params.toString();
            const targetUrl = `http://${config.targetHost}:${config.targetPort}/#/iframeIndex${queryString ? '?' + queryString : ''}`;
            window.location.replace(targetUrl);
            return;
        }

        // ===== 条件 3：如果路由包含 /#/sbIndex，不加载按钮 =====
        if (url.hash.includes('/sbIndex')) {
            return;
        }

        // ===== 否则：注入调试按钮 =====
        const debugButton = document.createElement('div');
        debugButton.id = 'tple-debug-button';
        debugButton.textContent = '打开调试页面';

        // 拖拽功能变量
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;
        let hasMoved = false;

        debugButton.addEventListener('mousedown', (e) => {
            isDragging = true;
            hasMoved = false;
            startX = e.clientX;
            startY = e.clientY;

            const rect = debugButton.getBoundingClientRect();
            initialLeft = rect.left;
            initialTop = rect.top;

            debugButton.classList.add('dragging');
            debugButton.style.transition = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;

            const deltaX = e.clientX - startX;
            const deltaY = e.clientY - startY;

            if (Math.abs(deltaX) > 0 || Math.abs(deltaY) > 0) {
                hasMoved = true;
            }

            debugButton.style.left = `${initialLeft + deltaX}px`;
            debugButton.style.top = `${initialTop + deltaY}px`;
            debugButton.style.right = 'auto';
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                debugButton.classList.remove('dragging');
                debugButton.style.transition = '';
            }
        });

        debugButton.addEventListener('click', () => {
            if (hasMoved) {
                return;
            }

            const debugUrl = `http://${config.targetHost}:${config.targetPort}${config.debugPath}`;
            window.open(debugUrl, '_blank');
        });

        // 确保 DOM 加载完成后再插入（兼容 SPA）
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                document.body.appendChild(debugButton);
            });
        } else {
            document.body.appendChild(debugButton);
        }
    }

    init();
})();
