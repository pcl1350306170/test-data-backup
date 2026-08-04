const ConfigManager = {
    DEFAULT_CONFIG: {
        apiBaseUrl: 'http://192.168.18.228:28019',
        btnImageCollapsed: 'https://raw.githubusercontent.com/pcl1350306170/test-data-backup/refs/heads/main/img/T/yh-1.png',
        btnImageExpanded: 'https://raw.githubusercontent.com/pcl1350306170/test-data-backup/refs/heads/main/img/T/yh-2.png',
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
