document.addEventListener('DOMContentLoaded', async () => {
    const form = document.getElementById('configForm');
    const messageDiv = document.getElementById('message');
    const resetBtn = document.getElementById('resetBtn');

    const inputs = {
        apiBaseUrl: document.getElementById('apiBaseUrl'),
        btnImageCollapsed: document.getElementById('btnImageCollapsed'),
        btnImageExpanded: document.getElementById('btnImageExpanded'),
        autoCollapseTimeout: document.getElementById('autoCollapseTimeout')
    };

    // 加载配置
    const config = await ConfigManager.getConfig();

    inputs.apiBaseUrl.value = config.apiBaseUrl;
    inputs.btnImageCollapsed.value = config.btnImageCollapsed || ConfigManager.DEFAULT_CONFIG.btnImageCollapsed;
    inputs.btnImageExpanded.value = config.btnImageExpanded || ConfigManager.DEFAULT_CONFIG.btnImageExpanded;
    inputs.autoCollapseTimeout.value = config.autoCollapseTimeout ?? 10;

    // 保存配置
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const newConfig = {
            apiBaseUrl: inputs.apiBaseUrl.value.trim(),
            btnImageCollapsed: inputs.btnImageCollapsed.value.trim(),
            btnImageExpanded: inputs.btnImageExpanded.value.trim(),
            autoCollapseTimeout: parseInt(inputs.autoCollapseTimeout.value) || 0
        };

        await ConfigManager.setConfig(newConfig);
        showMessage('配置已保存！', 'success');
    });

    // 重置配置
    resetBtn.addEventListener('click', async () => {
        const defaultConfig = await ConfigManager.resetConfig();

        inputs.apiBaseUrl.value = defaultConfig.apiBaseUrl;
        inputs.btnImageCollapsed.value = ConfigManager.DEFAULT_CONFIG.btnImageCollapsed;
        inputs.btnImageExpanded.value = ConfigManager.DEFAULT_CONFIG.btnImageExpanded;
        inputs.autoCollapseTimeout.value = 10;

        showMessage('已恢复默认配置', 'success');
    });

    function showMessage(text, type) {
        messageDiv.textContent = text;
        messageDiv.className = `message ${type}`;
        setTimeout(() => {
            messageDiv.className = 'message';
        }, 3000);
    }
});
