// ===== YouTube 视频下载助手 - Background Service Worker =====

// 默认下载服务地址（可修改为其他服务）
const DOWNLOAD_SERVICES = {
    // y2mate - 常用 YouTube 下载服务
    y2mate: 'https://www.y2mate.com/youtube/{videoId}',
    // savefrom
    savefrom: 'https://en.savefrom.net/1-youtube-video-downloader-{videoId}/',
    // ytbss
    ytbss: 'https://www.ytbs.com/video/{videoId}',
    // ssyoutube (savefrom 短链)
    ssyoutube: 'https://ssyoutube.com/watch?v={videoId}'
};

// 默认使用的服务
const DEFAULT_SERVICE = 'y2mate';

/**
 * 根据 videoId 构造下载服务 URL
 */
function buildDownloadUrl(videoId, serviceName) {
    const service = DOWNLOAD_SERVICES[serviceName] || DOWNLOAD_SERVICES[DEFAULT_SERVICE];
    return service.replace('{videoId}', videoId);
}

/**
 * 监听来自 content script 的消息
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'download' && message.videoId) {
        const url = buildDownloadUrl(message.videoId, message.service);

        // 在新标签页中打开下载服务
        chrome.tabs.create({ url: url, active: true }, (tab) => {
            if (chrome.runtime.lastError) {
                sendResponse({ success: false, error: chrome.runtime.lastError.message });
            } else {
                sendResponse({ success: true, tabId: tab.id });
            }
        });

        return true; // 保持消息通道异步开放
    }

    // 获取配置
    if (message.action === 'getConfig') {
        chrome.storage.sync.get({ downloadService: DEFAULT_SERVICE }, (items) => {
            sendResponse({ service: items.downloadService });
        });
        return true;
    }

    // 保存配置
    if (message.action === 'setConfig') {
        chrome.storage.sync.set({ downloadService: message.service }, () => {
            sendResponse({ success: true });
        });
        return true;
    }
});

// 安装时设置默认配置
chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.sync.set({
        downloadService: DEFAULT_SERVICE
    });
    console.log('[YT-Download] 扩展已安装，默认下载服务:', DEFAULT_SERVICE);
});
