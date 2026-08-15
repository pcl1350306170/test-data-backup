// ===== YouTube 视频下载助手 - Background Service Worker =====

// 下载服务地址列表（按优先级排序，前面的不可用时自动切换后面的）
const DOWNLOAD_SERVICES = [
    { name: 'cobalt', url: 'https://cobalt.tools/' },
    { name: 'savefrom', url: 'https://en.savefrom.net/1-youtube-video-downloader-{videoId}/' },
    { name: 'ssyoutube', url: 'https://ssyoutube.com/watch?v={videoId}' },
    { name: 'y2mate', url: 'https://www.y2mate.com/youtube/{videoId}' }
];

// 当前使用的服务索引
let currentServiceIndex = 0;

/**
 * 根据 videoId 构造下载服务 URL
 * 如果指定了 serviceIndex 则使用对应服务，否则使用当前可用的服务
 */
function buildDownloadUrl(videoId, serviceIndex) {
    const idx = serviceIndex !== undefined ? serviceIndex : currentServiceIndex;
    const service = DOWNLOAD_SERVICES[idx] || DOWNLOAD_SERVICES[0];
    return {
        url: service.url.replace('{videoId}', videoId),
        name: service.name,
        index: idx
    };
}

/**
 * 监听来自 content script 的消息
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'download' && message.videoId) {
        const serviceIndex = message.serviceIndex !== undefined ? message.serviceIndex : currentServiceIndex;
        const result = buildDownloadUrl(message.videoId, serviceIndex);

        // 在新标签页中打开下载服务
        chrome.tabs.create({ url: result.url, active: true }, (tab) => {
            if (chrome.runtime.lastError) {
                sendResponse({ success: false, error: chrome.runtime.lastError.message });
            } else {
                sendResponse({ success: true, tabId: tab.id, serviceName: result.name, serviceIndex: result.index });
            }
        });

        return true; // 保持消息通道异步开放
    }

    // 切换下载服务
    if (message.action === 'switchService') {
        currentServiceIndex = (currentServiceIndex + 1) % DOWNLOAD_SERVICES.length;
        sendResponse({
            success: true,
            serviceName: DOWNLOAD_SERVICES[currentServiceIndex].name,
            serviceIndex: currentServiceIndex
        });
        return true;
    }

    // 获取服务列表
    if (message.action === 'getServices') {
        sendResponse({
            services: DOWNLOAD_SERVICES.map((s, i) => ({ name: s.name, index: i })),
            currentIndex: currentServiceIndex
        });
        return true;
    }

    // 获取当前配置
    if (message.action === 'getConfig') {
        sendResponse({
            serviceName: DOWNLOAD_SERVICES[currentServiceIndex].name,
            serviceIndex: currentServiceIndex
        });
        return true;
    }
});

// 安装时初始化
chrome.runtime.onInstalled.addListener(() => {
    currentServiceIndex = 0;
    console.log('[YT-Download] 扩展已安装，默认下载服务:', DOWNLOAD_SERVICES[0].name);
});
