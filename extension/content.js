// 多平台视频下载按钮 - Content Script
// 支持 YouTube、TikTok、小红书、抖音、X(Twitter)
// 固定在窗口右侧中间的浮动下载按钮

const API_BASE = 'http://127.0.0.1:9001';
const CLIENT_ID_KEY = 'video_downloader_client_id';
const LICENSE_KEY_KEY = 'video_downloader_license_key';

let videoFormats = [];
let currentUrl = '';
let isMenuOpen = false;
let licenseKey = null;
let isPro = false;
let preParsedData = null;
let isDownloading = false;
let currentPlatform = null;

const PLATFORMS = {
    YOUTUBE: {
        name: 'YouTube',
        hosts: ['www.youtube.com', 'm.youtube.com'],
        isVideoPage: () => window.location.pathname.startsWith('/watch'),
        getVideoUrl: () => window.location.href
    },
    TIKTOK: {
        name: 'TikTok',
        hosts: ['www.tiktok.com'],
        isVideoPage: () => window.location.pathname.startsWith('/@') && window.location.pathname.includes('/video/'),
        getVideoUrl: () => window.location.href
    },
    DOUYIN: {
        name: '抖音',
        hosts: ['www.douyin.com'],
        isVideoPage: () => window.location.pathname.startsWith('/video/'),
        getVideoUrl: () => window.location.href
    },
    XIAOHONGSHU: {
        name: '小红书',
        hosts: ['www.xiaohongshu.com', 'xhslink.com'],
        isVideoPage: () => window.location.pathname.startsWith('/explore/') || window.location.pathname.startsWith('/discovery/item/'),
        getVideoUrl: () => window.location.href
    },
    X: {
        name: 'X',
        hosts: ['x.com'],
        isVideoPage: () => window.location.pathname.includes('/status/'),
        getVideoUrl: () => window.location.href
    }
};

function detectPlatform() {
    const host = window.location.hostname;
    for (const [key, platform] of Object.entries(PLATFORMS)) {
        if (platform.hosts.includes(host)) {
            return { key, ...platform };
        }
    }
    return null;
}

function init() {
    currentPlatform = detectPlatform();
    if (!currentPlatform) {
        console.log('[Video Downloader] 不支持的平台');
        return;
    }
    
    console.log('[Video Downloader] 检测到平台:', currentPlatform.name);
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onReady);
    } else {
        onReady();
    }
}

function onReady() {
    insertFloatingButton();
    
    let lastUrl = location.href;
    new MutationObserver(() => {
        const url = location.href;
        if (url !== lastUrl) {
            lastUrl = url;
            currentUrl = url;
            preParsedData = null;
            videoFormats = [];
            setTimeout(() => {
                removeFloatingButton();
                insertFloatingButton();
            }, 1000);
        }
    }).observe(document, { subtree: true, childList: true });
}

function removeFloatingButton() {
    const btn = document.getElementById('yt-floating-btn');
    if (btn) {
        btn.remove();
    }
}

function insertFloatingButton() {
    if (!currentPlatform || !currentPlatform.isVideoPage()) {
        console.log('[Video Downloader] 非视频页面，跳过');
        return;
    }
    
    if (document.getElementById('yt-floating-btn')) {
        return;
    }

    currentUrl = currentPlatform.getVideoUrl();
    console.log('[Video Downloader] 插入浮动按钮 -', currentPlatform.name);

    const container = document.createElement('div');
    container.id = 'yt-floating-btn';
    container.innerHTML = `
        <div class="floating-menu" id="floating-menu">
            <div class="floating-menu-item" data-q="best">最佳质量</div>
            <div class="floating-menu-item" data-q="720">720p</div>
            <div class="floating-menu-item" data-q="480">480p</div>
            <div class="floating-menu-item" data-q="360">360p</div>
            <div class="floating-menu-item pro" data-q="1080">1080p 🔒</div>
            <div class="floating-menu-item pro" data-q="mp3">MP3 🔒</div>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
            <button class="floating-download" id="floating-download-btn" title="点击下载">
                <span id="btn-icon">⏳</span>
                <span class="quality-badge" id="quality-badge" style="display: none;"></span>
            </button>
            <div class="hint-label" id="hint-label">点击下载 · 展开选质量</div>
        </div>
    `;

    document.body.appendChild(container);
    bindEvents();
    preParseVideo();
}

function bindEvents() {
    const btn = document.getElementById('floating-download-btn');
    const menuItems = document.querySelectorAll('.floating-menu-item');
    const hintLabel = document.getElementById('hint-label');

    // 点击主按钮 - 直接下载
    btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (isMenuOpen) {
            closeMenu();
        } else if (!isDownloading) {
            await handleFastDownload();
        }
    });

    // 点击提示文字 - 展开菜单
    hintLabel.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMenu();
    });

    // 菜单项点击
    menuItems.forEach(item => {
        item.addEventListener('click', async (e) => {
            e.stopPropagation();
            const quality = item.dataset.q;
            
            if (item.classList.contains('pro')) {
                showProModal();
                return;
            }

            await handleDownload(quality);
            closeMenu();
        });
    });

    // 点击其他地方关闭菜单
    document.addEventListener('click', (e) => {
        if (isMenuOpen && !e.target.closest('#yt-floating-btn')) {
            closeMenu();
        }
    });
}

function toggleMenu() {
    const menu = document.getElementById('floating-menu');
    isMenuOpen = !isMenuOpen;
    menu.classList.toggle('show', isMenuOpen);
    
    const hintLabel = document.getElementById('hint-label');
    if (hintLabel) {
        hintLabel.textContent = isMenuOpen ? '选择质量' : '点击下载 · 展开选质量';
    }
}

function closeMenu() {
    const menu = document.getElementById('floating-menu');
    isMenuOpen = false;
    menu.classList.remove('show');
    
    const hintLabel = document.getElementById('hint-label');
    if (hintLabel) {
        hintLabel.textContent = '点击下载 · 展开选质量';
    }
}

function setButtonState(state, text) {
    const btn = document.getElementById('floating-download-btn');
    const icon = document.getElementById('btn-icon');
    const badge = document.getElementById('quality-badge');
    const hintLabel = document.getElementById('hint-label');
    
    if (!btn) return;
    
    // 移除所有状态类
    btn.classList.remove('ready', 'downloading', 'done', 'error');
    
    switch(state) {
        case 'parsing':
            if (icon) icon.textContent = '⏳';
            if (badge) badge.style.display = 'none';
            if (hintLabel) hintLabel.textContent = '解析中...';
            break;
        case 'ready':
            btn.classList.add('ready');
            if (icon) icon.textContent = '⬇';
            if (badge) {
                badge.textContent = text;
                badge.classList.add('hd');
                badge.style.display = 'block';
            }
            if (hintLabel) hintLabel.textContent = '点击下载 · 展开选质量';
            break;
        case 'downloading':
            btn.classList.add('downloading');
            if (icon) icon.textContent = text;
            if (badge) badge.style.display = 'none';
            if (hintLabel) hintLabel.textContent = '下载中...';
            break;
        case 'done':
            btn.classList.add('done');
            if (icon) icon.textContent = '✓';
            if (badge) badge.style.display = 'none';
            if (hintLabel) hintLabel.textContent = '已保存';
            break;
        case 'error':
            btn.classList.add('error');
            if (icon) icon.textContent = '✗';
            if (badge) badge.style.display = 'none';
            if (hintLabel) hintLabel.textContent = text || '失败';
            break;
    }
}

async function preParseVideo() {
    try {
        setButtonState('parsing');
        
        const headers = await getHeaders();
        console.log('[Video Downloader] 预解析:', currentUrl);

        // 尝试快速解析API
        let response = await fetch(`${API_BASE}/api/quick-info?url=${encodeURIComponent(currentUrl)}`, {
            method: 'GET',
            headers: headers
        });

        // 如果快速解析失败，尝试完整解析
        if (!response.ok) {
            console.log('[Video Downloader] 快速解析失败，尝试完整解析...');
            response = await fetch(`${API_BASE}/api/info?url=${encodeURIComponent(currentUrl)}`, {
                method: 'GET',
                headers: headers
            });
        }

        let data = null;
        if (response.ok) {
            data = await response.json();
            console.log('[Video Downloader] 解析成功，formats:', data.formats?.length);
        } else {
            const errorData = await response.json();
            console.warn('[Video Downloader] 解析失败:', errorData.detail);
        }

        // 如果没有格式，使用默认格式（仍然允许下载）
        if (!data || !data.formats || data.formats.length === 0) {
            console.log('[Video Downloader] 使用默认格式');
            data = {
                formats: [{ format_id: 'best', height: 720, ext: 'mp4', has_audio: true }],
                title: 'Video',
                limits: { is_pro: false }
            };
        }

        videoFormats = data.formats;
        preParsedData = data;
        isPro = data.limits?.is_pro || false;
        
        const quality = videoFormats[0].height || 'HD';
        setButtonState('ready', quality);
        updateMenuItems();

    } catch (error) {
        console.error('[Video Downloader] 预解析异常:', error);
        // 即使出错，也允许尝试下载
        videoFormats = [{ format_id: 'best', height: 720, ext: 'mp4', has_audio: true }];
        preParsedData = { formats: videoFormats, limits: { is_pro: false } };
        setButtonState('ready', 'HD');
    }
}

function updateMenuItems() {
    const menuItems = document.querySelectorAll('.floating-menu-item');
    menuItems.forEach(item => {
        if (item.classList.contains('pro') && isPro) {
            item.classList.remove('pro');
            item.innerHTML = item.innerHTML.replace(' 🔒', '');
        }
    });
}

async function handleFastDownload() {
    if (isDownloading) return;
    isDownloading = true;

    try {
        if (!preParsedData) {
            await preParseVideo();
        }

        if (videoFormats.length === 0) {
            throw new Error('无法获取视频信息');
        }

        const format = videoFormats[0];
        await downloadVideo(format);
        setButtonState('done');

        setTimeout(() => {
            const bestFormat = videoFormats[0];
            const quality = bestFormat.height || 'HD';
            setButtonState('ready', quality);
            isDownloading = false;
        }, 3000);

    } catch (error) {
        console.error('[Video Downloader] 下载失败:', error);
        const errorMsg = error.message === 'Extension context invalidated' 
            ? '请确认是否是视频' 
            : error.message;
        setButtonState('error', errorMsg);
        isDownloading = false;
    }
}

async function handleDownload(quality) {
    if (isDownloading) return;
    isDownloading = true;

    try {
        if (!preParsedData) {
            await preParseVideo();
        }

        // 直接使用质量参数下载，后端会自动选择格式
        await downloadVideo({ format_id: 'best', height: quality });
        setButtonState('done');

        setTimeout(() => {
            const bestFormat = videoFormats[0];
            const q = bestFormat.height || 'HD';
            setButtonState('ready', q);
            isDownloading = false;
        }, 3000);

    } catch (error) {
        console.error('[Video Downloader] 下载失败:', error);
        const errorMsg = error.message === 'Extension context invalidated'
            ? '请确认是否是视频'
            : error.message;
        setButtonState('error', errorMsg);
        isDownloading = false;
    }
}

async function downloadVideo(format) {
    const headers = await getHeaders();

    const response = await fetch(`${API_BASE}/api/download`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
            url: currentUrl,
            format_id: format.format_id || 'best',
            quality: format.height
        })
    });

    const data = await response.json();

    if (!response.ok) {
        if (data.detail && data.detail.includes('Pro')) {
            showProModal();
            throw new Error(data.detail);
        }
        throw new Error(data.detail || '下载失败');
    }

    await pollDownloadStatus(data.job_id);
}

async function pollDownloadStatus(jobId) {
    const maxAttempts = 120;
    let attempts = 0;

    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const headers = await getHeaders();
                const response = await fetch(`${API_BASE}/api/download/${jobId}`, {
                    headers: headers
                });
                const data = await response.json();

                const percent = Math.round(data.progress || 0);
                setButtonState('downloading', `${percent}%`);

                if (data.stage === 'ready' || data.stage === 'completed') {
                    await downloadFile(jobId, data.filename);
                    resolve();
                } else if (data.stage === 'failed') {
                    reject(new Error(data.error || '下载失败'));
                } else if (attempts >= maxAttempts) {
                    reject(new Error('下载超时'));
                } else {
                    attempts++;
                    setTimeout(poll, 1000);
                }
            } catch (error) {
                reject(error);
            }
        };

        poll();
    });
}

async function downloadFile(jobId, filename) {
    const headers = await getHeaders();
    
    const response = await fetch(`${API_BASE}/api/download/${jobId}/file`, {
        headers: headers
    });
    
    if (!response.ok) {
        throw new Error('下载文件失败');
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || `video_${jobId}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

function showProModal() {
    if (document.getElementById('pro-modal')) {
        return;
    }

    const modal = document.createElement('div');
    modal.id = 'pro-modal';
    modal.innerHTML = `
        <div class="modal-box">
            <h2>Upgrade to Pro 🚀</h2>
            <ul>
                <li>✔ Download in 1080p HD</li>
                <li>✔ Unlimited downloads</li>
                <li>✔ 5x faster speed</li>
                <li>✔ No ads</li>
            </ul>
            <button class="upgrade-btn" id="upgrade-btn">Upgrade Now</button>
            <button class="free-btn" id="free-btn">Continue with 480p</button>
            <button class="close-btn" id="close-modal-btn">✕</button>
        </div>
    `;

    document.body.appendChild(modal);

    document.getElementById('upgrade-btn').addEventListener('click', () => {
        window.open('http://127.0.0.1:9001/pricing', '_blank');
        closeModal();
    });

    document.getElementById('free-btn').addEventListener('click', async () => {
        await handleDownload('480');
        closeModal();
    });

    document.getElementById('close-modal-btn').addEventListener('click', closeModal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
}

function closeModal() {
    const modal = document.getElementById('pro-modal');
    if (modal) {
        modal.remove();
    }
}

async function getClientId() {
    return new Promise((resolve) => {
        chrome.storage.local.get([CLIENT_ID_KEY], (result) => {
            if (result[CLIENT_ID_KEY]) {
                resolve(result[CLIENT_ID_KEY]);
            } else {
                const clientId = crypto.randomUUID();
                chrome.storage.local.set({ [CLIENT_ID_KEY]: clientId }, () => {
                    resolve(clientId);
                });
            }
        });
    });
}

async function getLicenseKey() {
    return new Promise((resolve) => {
        chrome.storage.local.get([LICENSE_KEY_KEY], (result) => {
            if (result[LICENSE_KEY_KEY]) {
                licenseKey = result[LICENSE_KEY_KEY];
                resolve(licenseKey);
            } else {
                resolve(null);
            }
        });
    });
}

async function getHeaders() {
    const clientId = await getClientId();
    const key = await getLicenseKey();
    
    const headers = {
        'Content-Type': 'application/json',
        'X-Client-ID': clientId
    };
    
    if (key) {
        headers['X-License-Key'] = key;
    }
    
    return headers;
}

init();
