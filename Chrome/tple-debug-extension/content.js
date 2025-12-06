(function () {
    const url = new URL(window.location.href);

    // ===== 条件1：端口必须是 7000 =====
    if (url.port !== '7000') return;

    // ===== 条件2：如果是 iframeIndex2.html 页面，自动跳转 =====
    if (url.pathname === '/tpleditor/resource/html/iframeIndex2.html') {
        // 获取所有查询参数
        const params = new URLSearchParams(url.search);
        const queryString = params.toString();

        // 构造目标 URL
        const targetUrl = `http://localhost:8080/#/iframeIndex${queryString ? '?' + queryString : ''}`;

        // 立即跳转（避免页面渲染）
        window.location.replace(targetUrl);
        return;
    }

    // ===== 条件3：如果路由包含 /#/sbIndex，不加载按钮 =====
    if (url.hash.includes('/sbIndex')) {
        return;
    }

    // ===== 否则：注入调试按钮 =====
    const debugButton = document.createElement('div');
    debugButton.id = 'tple-debug-button';
    debugButton.textContent = '打开调试页面';

    debugButton.addEventListener('click', () => {
        const debugUrl = `http://${url.hostname}:7000/tpleditor/resource/triagetable/#/sbIndex`;
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
})();
