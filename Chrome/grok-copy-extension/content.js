(function () {
    'use strict';

    if (document.getElementById('grok-copy-btn')) return;

    // ===== 配置 =====
    const clickDelay = 800;
    const scrollStep = 300;
    const scrollWait = 500;

    let isRunning = false;
    let stopRequested = false;

    // ===== Toast =====
    function showToast(message, type) {
        let toast = document.getElementById('grok-copy-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'grok-copy-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.className = 'show' + (type ? ' ' + type : '');
        setTimeout(() => { toast.className = ''; }, 3000);
    }

    function sleep(ms) {
        return new Promise(r => setTimeout(r, ms));
    }

    // ===== 判断元素是否在视口内可见 =====
    function isElementVisible(el) {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 &&
            rect.bottom > 0 && rect.top < window.innerHeight &&
            rect.right > 0 && rect.left < window.innerWidth;
    }

    // ===== 查找 Grok 消息滚动容器 =====
    function findChatScroller() {
        return document.querySelector('[data-testid="chat-transcript-scroller"]') ||
               document.querySelector('[aria-label="Conversation"]');
    }

    // ===== 查找当前可见的 AI 回复复制按钮 =====
    function findVisibleReplyCopyButtons() {
        const buttons = [];
        const allButtons = document.querySelectorAll('button');

        allButtons.forEach(btn => {
            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
            // 匹配 "复制" 或 "复制响应"（排除 "复制代码" 等其他按钮）
            const isCopyBtn = label === '复制' || label === 'copy' ||
                              label === '复制响应' || label === 'copy response';
            if (!isCopyBtn) return;

            // 检查是否在 response-* 容器内（AI 回复）
            const responseContainer = btn.closest('[id^="response-"]');
            if (!responseContainer) return;

            // 检查是否可见（用 getBoundingClientRect，不用 offsetParent）
            if (!isElementVisible(btn)) return;

            buttons.push(btn);
        });

        return buttons;
    }

    // ===== 高亮按钮 =====
    function highlightButton(btn) {
        const orig = btn.style.outline;
        const origOffset = btn.style.outlineOffset;
        btn.style.outline = '3px solid #00bfff';
        btn.style.outlineOffset = '2px';
        setTimeout(() => {
            btn.style.outline = orig;
            btn.style.outlineOffset = origOffset;
        }, 600);
    }

    // ===== 更新按钮状态 =====
    function updateButtonState() {
        const btn = document.getElementById('grok-copy-btn');
        if (!btn) return;
        if (isRunning) {
            btn.classList.add('running');
            btn.textContent = '⏹';
            btn.title = '停止复制';
        } else {
            btn.classList.remove('running');
            btn.textContent = '📋';
            btn.title = '开始批量复制 Grok 回复';
        }
    }

    // ===== 核心：滚动 + 收集 + 点击 =====
    async function startCopyAll() {
        if (isRunning) return;
        isRunning = true;
        stopRequested = false;
        updateButtonState();

        const statusEl = document.getElementById('grok-copy-status');
        const setProgress = (text) => { if (statusEl) statusEl.textContent = text; };

        // 找滚动容器
        const scroller = findChatScroller();
        if (!scroller) {
            showToast('❌ 未找到聊天滚动容器', 'error');
            isRunning = false;
            updateButtonState();
            return;
        }

        console.log(`[Grok Copy] 滚动容器: scrollHeight=${scroller.scrollHeight}, clientHeight=${scroller.clientHeight}`);

        // 先做一轮诊断：当前页面有多少个复制按钮
        const allBtns = document.querySelectorAll('button');
        let totalCopyBtns = 0;
        let inResponseBtns = 0;
        let visibleInResponseBtns = 0;
        allBtns.forEach(btn => {
            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
            const isCopy = label === '复制' || label === 'copy' || label === '复制响应' || label === 'copy response';
            if (!isCopy) return;
            totalCopyBtns++;
            if (btn.closest('[id^="response-"]')) {
                inResponseBtns++;
                if (isElementVisible(btn)) visibleInResponseBtns++;
            }
        });
        console.log(`[Grok Copy] 诊断: 总复制按钮=${totalCopyBtns}, 在response容器内=${inResponseBtns}, 可见且在response内=${visibleInResponseBtns}`);

        // 如果精确匹配找不到，尝试宽松匹配
        let useLooseMatch = false;
        if (visibleInResponseBtns === 0 && totalCopyBtns > 0) {
            console.log('[Grok Copy] ⚠️ 精确匹配(response-*)找不到按钮，切换宽松模式');
            useLooseMatch = true;
        }

        // 滚到顶部
        setProgress('滚动到顶部...');
        scroller.scrollTop = 0;
        await sleep(800);
        if (stopRequested) { finish(); return; }

        const clickedBtns = new Set();
        let totalCopied = 0;
        let stuckCount = 0;
        let loopCount = 0;

        while (true) {
            if (stopRequested) break;
            loopCount++;

            // 收集当前可见的复制按钮
            let visibleBtns;
            if (useLooseMatch) {
                // 宽松模式：所有可见的复制按钮（不限 response-* 容器）
                visibleBtns = [];
                document.querySelectorAll('button').forEach(btn => {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const isCopy = label === '复制' || label === 'copy' || label === '复制响应' || label === 'copy response';
                    if (isCopy && isElementVisible(btn) && !clickedBtns.has(btn)) {
                        visibleBtns.push(btn);
                    }
                });
            } else {
                visibleBtns = findVisibleReplyCopyButtons().filter(btn => !clickedBtns.has(btn));
            }

            // 按 Y 坐标排序
            visibleBtns.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);

            if (visibleBtns.length > 0) {
                console.log(`[Grok Copy] 第${loopCount}轮: 找到 ${visibleBtns.length} 个新按钮`);
            }

            // 逐个点击
            for (const btn of visibleBtns) {
                if (stopRequested) break;
                if (!document.contains(btn)) continue;

                highlightButton(btn);
                try { btn.click(); } catch (e) { console.warn('[Grok Copy] 点击失败:', e); }

                clickedBtns.add(btn);
                totalCopied++;
                setProgress(`${totalCopied} 已复制`);

                await sleep(clickDelay);
            }

            // 向下滚动
            const prevTop = scroller.scrollTop;
            scroller.scrollBy(0, scrollStep);
            await sleep(scrollWait);

            // 检测是否到底
            if (scroller.scrollTop - prevTop < 5) {
                stuckCount++;
                if (stuckCount >= 4) break;
                await sleep(300);
            } else {
                stuckCount = 0;
            }
        }

        console.log(`[Grok Copy] 完成: 共循环${loopCount}轮, 复制${totalCopied}条`);
        finish();

        function finish() {
            isRunning = false;
            stopRequested = false;
            updateButtonState();
            if (totalCopied > 0) {
                showToast(`✅ 完成！共复制 ${totalCopied} 条 AI 回复`);
            } else if (!stopRequested) {
                showToast('⚠️ 未找到复制按钮，请查看控制台诊断信息', 'error');
            }
        }
    }

    function stopCopy() {
        stopRequested = true;
    }

    // ===== 浮动按钮 =====
    function createFloatingButton() {
        const container = document.createElement('div');
        container.id = 'grok-copy-container';

        const btn = document.createElement('div');
        btn.id = 'grok-copy-btn';
        btn.textContent = '📋';
        btn.title = '开始批量复制 Grok 回复';

        const status = document.createElement('span');
        status.id = 'grok-copy-status';
        status.className = 'grok-copy-status';

        container.appendChild(status);
        container.appendChild(btn);

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (hasMoved) return;
            if (isRunning) {
                stopCopy();
            } else {
                startCopyAll();
            }
        });

        // 拖拽
        let isDragging = false, startX, startY, initRight, initBottom;
        let hasMoved = false;

        btn.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            isDragging = true;
            hasMoved = false;
            startX = e.clientX;
            startY = e.clientY;
            const rect = container.getBoundingClientRect();
            initRight = window.innerWidth - rect.right;
            initBottom = window.innerHeight - rect.bottom;
            btn.classList.add('dragging');
            e.preventDefault();
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved = true;
            container.style.right = Math.max(0, initRight - dx) + 'px';
            container.style.bottom = Math.max(0, initBottom - dy) + 'px';
        });

        window.addEventListener('mouseup', () => {
            if (!isDragging) return;
            isDragging = false;
            btn.classList.remove('dragging');
        });

        document.body.appendChild(container);
    }

    createFloatingButton();
    console.log('[Grok Copy] 扩展已加载 v3');
})();
