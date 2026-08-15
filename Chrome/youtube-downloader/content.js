(function () {
    'use strict';

    // ===== 配置 =====
    // 下载服务地址，可替换为其他第三方服务
    // 支持的占位符: {videoId}, {quality}
    const DEFAULT_DOWNLOAD_SERVICE = 'https://www.y2mate.com/youtube/{videoId}';

    // 预设清晰度选项
    const QUALITY_OPTIONS = [
        { label: '最佳质量', value: 'best' },
        { label: '1080p', value: '1080' },
        { label: '720p', value: '720' },
        { label: '480p', value: '480' },
        { label: '360p', value: '360' },
        { label: '仅音频 (MP3)', value: 'audio' }
    ];

    // ===== 工具函数 =====

    /** 获取当前视频 ID */
    function getVideoId() {
        try {
            return new URLSearchParams(window.location.search).get('v');
        } catch {
            return null;
        }
    }

    /** 从 ytInitialPlayerResponse 提取视频信息 */
    function extractVideoInfo() {
        const videoId = getVideoId();
        if (!videoId) return null;

        let title = '';
        let thumbnail = '';

        // 优先从 ytInitialPlayerResponse 获取
        try {
            if (window.ytInitialPlayerResponse) {
                const pr = window.ytInitialPlayerResponse;
                title = pr.videoDetails?.title || '';
                thumbnail = pr.videoDetails?.thumbnail?.thumbnails?.pop()?.url || '';
            }
        } catch (e) {
            console.warn('[YT-Download] 提取 ytInitialPlayerResponse 失败:', e);
        }

        // 备用：从页面 DOM 获取
        if (!title) {
            title = document.title?.replace(' - YouTube', '') || 'YouTube Video';
        }
        if (!thumbnail) {
            thumbnail = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
        }

        return { videoId, title, thumbnail, url: window.location.href };
    }

    /** 构造下载服务 URL */
    function buildDownloadUrl(videoId, quality) {
        return DEFAULT_DOWNLOAD_SERVICE.replace('{videoId}', videoId);
    }

    // ===== Toast 提示 =====
    function showToast(message, type) {
        let toast = document.getElementById('ytd-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'ytd-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.className = 'ytd-toast-show' + (type ? ' ytd-toast-' + type : '');
        setTimeout(() => { toast.className = 'ytd-toast-show'; }, 2500);
    }

    // ===== 下载面板 =====
    let currentPanel = null;

    function closePanel() {
        if (currentPanel) {
            currentPanel.remove();
            currentPanel = null;
        }
    }

    function togglePanel(videoInfo) {
        if (currentPanel) {
            closePanel();
            return;
        }

        const panel = document.createElement('div');
        panel.className = 'ytd-panel';
        currentPanel = panel;

        // 标题
        const header = document.createElement('div');
        header.className = 'ytd-panel-header';
        header.innerHTML = `
            <span class="ytd-panel-title">⬇ 下载视频</span>
            <span class="ytd-panel-close">&times;</span>
        `;
        panel.appendChild(header);

        // 视频信息
        const info = document.createElement('div');
        info.className = 'ytd-panel-info';
        const thumbImg = document.createElement('img');
        thumbImg.className = 'ytd-panel-thumb';
        thumbImg.src = videoInfo.thumbnail;
        thumbImg.alt = 'thumbnail';
        const titleSpan = document.createElement('span');
        titleSpan.className = 'ytd-panel-video-title';
        titleSpan.textContent = videoInfo.title;
        titleSpan.title = videoInfo.title;
        info.appendChild(thumbImg);
        info.appendChild(titleSpan);
        panel.appendChild(info);

        // 清晰度选择
        const qualitySection = document.createElement('div');
        qualitySection.className = 'ytd-panel-section';
        qualitySection.innerHTML = '<div class="ytd-section-label">选择清晰度</div>';

        const qualityList = document.createElement('div');
        qualityList.className = 'ytd-quality-list';

        QUALITY_OPTIONS.forEach(opt => {
            const item = document.createElement('div');
            item.className = 'ytd-quality-item';
            item.innerHTML = `
                <span class="ytd-quality-icon">${opt.value === 'audio' ? '🎵' : '🎬'}</span>
                <span class="ytd-quality-label">${opt.label}</span>
                <span class="ytd-quality-arrow">→</span>
            `;
            item.addEventListener('click', () => {
                chrome.runtime.sendMessage({
                    action: 'download',
                    videoId: videoInfo.videoId,
                    quality: opt.value,
                    title: videoInfo.title
                }, (response) => {
                    if (response && response.success) {
                        showToast('✅ 已打开下载页面', 'success');
                    } else {
                        showToast('❌ ' + (response?.error || '打开下载页失败'), 'error');
                    }
                });
                closePanel();
            });
            qualityList.appendChild(item);
        });

        qualitySection.appendChild(qualityList);
        panel.appendChild(qualitySection);

        // 提示
        const tip = document.createElement('div');
        tip.className = 'ytd-panel-tip';
        tip.textContent = '💡 点击清晰度后将在新标签页打开下载服务，按页面提示即可完成下载';
        panel.appendChild(tip);

        // 关闭按钮事件
        header.querySelector('.ytd-panel-close').addEventListener('click', closePanel);

        // 点击面板外关闭
        document.addEventListener('mousedown', function handler(e) {
            if (currentPanel && !currentPanel.contains(e.target) && !e.target.closest('.ytd-download-btn')) {
                closePanel();
                document.removeEventListener('mousedown', handler);
            }
        });

        document.body.appendChild(panel);
    }

    // ===== 创建下载按钮 =====
    function createDownloadButton(videoInfo) {
        // 移除旧按钮
        const old = document.getElementById('ytd-download-wrapper');
        if (old) old.remove();

        // 查找插入位置：视频标题下方区域（#top-level-buttons-computed 或 #actions 区域）
        const targetSelectors = [
            '#top-level-buttons-computed',
            'ytd-watch-metadata #actions',
            '#menu-container #top-level-buttons',
            'ytd-video-primary-info-renderer #menu-container'
        ];

        let target = null;
        for (const sel of targetSelectors) {
            target = document.querySelector(sel);
            if (target) break;
        }

        if (!target) {
            // 如果找不到精确位置，插入到视频播放器下方
            target = document.querySelector('#above-the-fold') ||
                     document.querySelector('#primary-inner') ||
                     document.querySelector('ytd-watch-flexy #content');
        }
        if (!target) return;

        const wrapper = document.createElement('div');
        wrapper.id = 'ytd-download-wrapper';
        wrapper.className = 'ytd-download-wrapper';

        const btn = document.createElement('button');
        btn.className = 'ytd-download-btn';
        btn.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            <span>下载</span>
        `;
        btn.title = '下载此视频';

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            togglePanel(videoInfo);
        });

        wrapper.appendChild(btn);
        target.appendChild(wrapper);
    }

    // ===== 初始化 =====
    function init() {
        const videoInfo = extractVideoInfo();
        if (!videoInfo) return false;
        createDownloadButton(videoInfo);
        return true;
    }

    // ===== 等待 ytInitialPlayerResponse 就绪 =====
    function waitForPlayerData(callback, maxRetries = 20) {
        let retries = 0;
        const check = () => {
            if (window.ytInitialPlayerResponse || retries >= maxRetries) {
                callback();
            } else {
                retries++;
                setTimeout(check, 300);
            }
        };
        check();
    }

    // ===== YouTube SPA 导航监听 =====
    let lastVideoId = null;

    function onVideoChange() {
        const videoId = getVideoId();
        if (videoId && videoId !== lastVideoId) {
            lastVideoId = videoId;
            closePanel();
            waitForPlayerData(() => init());
        }
    }

    // 监听 URL 变化（YouTube SPA 导航）
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function () {
        originalPushState.apply(this, arguments);
        setTimeout(onVideoChange, 100);
    };
    history.replaceState = function () {
        originalReplaceState.apply(this, arguments);
        setTimeout(onVideoChange, 100);
    };

    window.addEventListener('popstate', () => setTimeout(onVideoChange, 100));

    // 同时使用 MutationObserver 监听页面内容变化
    const pageObserver = new MutationObserver(() => {
        setTimeout(onVideoChange, 300);
    });

    // 观察 yt-page-manager 或 title 变化
    const observeTarget = document.querySelector('title') || document.head;
    if (observeTarget) {
        pageObserver.observe(observeTarget, { childList: true, characterData: true, subtree: true });
    }

    // ===== 启动 =====
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            waitForPlayerData(() => init());
        });
    } else {
        waitForPlayerData(() => init());
    }

    console.log('[YT-Download] YouTube 视频下载助手已加载');
})();
