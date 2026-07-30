document.addEventListener('DOMContentLoaded', async () => {
    const form = document.getElementById('configForm');
    const messageDiv = document.getElementById('message');
    const resetBtn = document.getElementById('resetBtn');

    const inputs = {
        debugPort: document.getElementById('debugPort'),
        targetHost: document.getElementById('targetHost'),
        targetPort: document.getElementById('targetPort'),
        debugPath: document.getElementById('debugPath'),
        autoRedirectPath: document.getElementById('autoRedirectPath'),
        btnImageCollapsed: document.getElementById('btnImageCollapsed'),
        btnImageExpanded: document.getElementById('btnImageExpanded'),
        autoCollapseTimeout: document.getElementById('autoCollapseTimeout')
    };

    // 加载配置
    const config = await ConfigManager.getConfig();

    inputs.debugPort.value = config.debugPort;
    inputs.targetHost.value = config.targetHost;
    inputs.targetPort.value = config.targetPort;
    inputs.debugPath.value = config.debugPath;
    inputs.autoRedirectPath.value = config.autoRedirectPath;
    inputs.btnImageCollapsed.value = config.btnImageCollapsed || '';
    inputs.btnImageExpanded.value = config.btnImageExpanded || '';
    inputs.autoCollapseTimeout.value = config.autoCollapseTimeout ?? 10;

    // 保存配置
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const newConfig = {
            debugPort: inputs.debugPort.value,
            targetHost: inputs.targetHost.value,
            targetPort: inputs.targetPort.value,
            debugPath: inputs.debugPath.value,
            autoRedirectPath: inputs.autoRedirectPath.value,
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

        inputs.debugPort.value = defaultConfig.debugPort;
        inputs.targetHost.value = defaultConfig.targetHost;
        inputs.targetPort.value = defaultConfig.targetPort;
        inputs.debugPath.value = defaultConfig.debugPath;
        inputs.autoRedirectPath.value = defaultConfig.autoRedirectPath;
        inputs.btnImageCollapsed.value = '';
        inputs.btnImageExpanded.value = '';
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
