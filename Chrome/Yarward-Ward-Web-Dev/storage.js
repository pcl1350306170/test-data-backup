const ConfigManager = {
    DEFAULT_CONFIG: {
        apiBaseUrl: 'http://192.168.18.228:28019',
        btnImageCollapsed: '',
        btnImageExpanded: '',
        autoCollapseTimeout: 10
    },

    async getConfig() {
        return new Promise((resolve) => {
            chrome.storage.sync.get(this.DEFAULT_CONFIG, (result) => {
                resolve({ ...this.DEFAULT_CONFIG, ...result });
            });
        });
    },

    async setConfig(config) {
        return new Promise((resolve) => {
            chrome.storage.sync.set(config, resolve);
        });
    },

    async resetConfig() {
        return new Promise((resolve) => {
            chrome.storage.sync.clear(() => {
                resolve(this.DEFAULT_CONFIG);
            });
        });
    }
};
