// YouTube页面下载按钮 - Content Script
// 在YouTube页面中插入下载按钮，提供快速下载功能

const API_BASE = 'http://127.0.0.1:9001';
const CLIENT_ID_KEY = 'video_downloader_client_id';
const LICENSE_KEY_KEY = 'video_downloader_license_key';
const QUALITY_KEY = 'video_downloader_quality';

let videoFormats = [];
let currentUrl = '';
let isMenuOpen = false;
let licenseKey = null;
let isPro = false;

// 初始化
function init() {
    // 等待页面加载完成
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', insertDownloadButton);
    } else {
        insertDownloadButton();
    }

    // 监听URL变化（YouTube是SPA）
    let lastUrl = location.href;
    new MutationObserver(() => {
        const url = location.href;
        if (url !== lastUrl) {
            lastUrl = url;
            currentUrl = url;
            setTimeout(insertDownloadButton, 1000);
        }
    }).observe(document, { subtree: true, childList: true });
}

// 插入下载按钮
function insertDownloadButton() {
    const target = document.querySelector('#info #menu-container #top-level-buttons-computed');
    
    if (!target || document.getElementById('yt-download-btn')) {
        return;
    }

    currentUrl = window.location.href;

    const container = document.createElement('div');
    container.id = 'yt-download-btn';
    container.innerHTML = `
        <button class="yt-fast-download" id="yt-fast-download-btn">⚡ Download</button>
        <button class="yt-dropdown" id="yt-dropdown-btn">▼</button>
        <div class="yt-menu" id="yt-quality-menu" style="display: none;">
            <div class="yt-menu-item" data-q="360">360p</div>
            <div class="yt-menu-item" data-q="480">480p</div>
            <div class="yt-menu-item" data-q="720">720p</div>
            <div class="yt-menu-item pro" data-q="1080">1080p 🔒</div>
            <div class="yt-menu-item pro" data-q="mp3">MP3 🔒</div>
        </div>
    `;

    target.appendChild(container);

    // 绑定事件
    bindEvents();

    // 预解析视频信息
    preParseVideo();
}

// 绑定事件
function bindEvents() {
    const fastBtn = document.getElementById('yt-fast-download-btn');
    const dropdownBtn = document.getElementById('yt-dropdown-btn');
    const menuItems = document.querySelectorAll('.yt-menu-item');

    // 主按钮点击事件
    fastBtn.addEventListener('click', async () => {
        await handleFastDownload();
    });

    // 下拉按钮点击事件
    dropdownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMenu();
    });

    // 菜单项点击事件
    menuItems.forEach(item => {
        item.addEventListener('click', async () => {
            const quality = item.dataset.q;
            
            if (item.classList.contains('pro')) {
                showProModal();
                return;
            }

            await handleDownload(quality);
            toggleMenu();
        });
    });

    // 点击其他地方关闭菜单
    document.addEventListener('click', (e) => {
        if (isMenuOpen && !e.target.closest('#yt-download-btn')) {
            toggleMenu();
        }
    });
}

// 切换菜单显示
function toggleMenu() {
    const menu = document.getElementById('yt-quality-menu');
    isMenuOpen = !isMenuOpen;
    menu.style.display = isMenuOpen ? 'block' : 'none';
}

// 预解析视频信息
async function preParseVideo() {
    try {
        const headers = await getHeaders();

        const response = await fetch(`${API_BASE}/api/info?url=${encodeURIComponent(currentUrl)}`, {
            method: 'GET',
            headers: headers
        });

        if (response.ok) {
            const data = await response.json();
            if (data.success && data.formats) {
                videoFormats = data.formats;
                updateBestQualityLabel();
            }
        }
    } catch (error) {
        console.error('预解析失败:', error);
    }
}

// 更新最佳质量标签
function updateBestQualityLabel() {
    if (videoFormats.length > 0) {
        const bestFormat = videoFormats[0];
        const quality = bestFormat.quality || 'HD';
        const btn = document.getElementById('yt-fast-download-btn');
        if (btn) {
            btn.innerHTML = `⚡ Download ${quality}`;
        }
    }
}

// 处理快速下载
async function handleFastDownload() {
    const btn = document.getElementById('yt-fast-download-btn');
    
    try {
        setLoading();

        // 如果没有预解析，先解析
        if (videoFormats.length === 0) {
            await preParseVideo();
        }

        // 获取最佳格式
        const bestFormat = getBestFormat();
        if (!bestFormat) {
            throw new Error('无法获取视频信息');
        }

        await downloadVideo(bestFormat);
        setDone();

        // 3秒后恢复
        setTimeout(() => {
            btn.innerHTML = '⚡ Download';
        }, 3000);

    } catch (error) {
        console.error('下载失败:', error);
        showError(error.message);
        btn.innerHTML = '⚡ Download';
    }
}

// 处理指定质量下载
async function handleDownload(quality) {
    const btn = document.getElementById('yt-fast-download-btn');
    
    try {
        setLoading();

        // 如果没有预解析，先解析
        if (videoFormats.length === 0) {
            await preParseVideo();
        }

        // 查找指定质量的格式
        const format = videoFormats.find(f => 
            f.quality === quality || f.format_id === quality
        );

        if (!format) {
            throw new Error(`找不到 ${quality} 格式`);
        }

        await downloadVideo(format);
        setDone();

        // 3秒后恢复
        setTimeout(() => {
            btn.innerHTML = '⚡ Download';
        }, 3000);

    } catch (error) {
        console.error('下载失败:', error);
        showError(error.message);
        btn.innerHTML = '⚡ Download';
    }
}

// 获取最佳格式
function getBestFormat() {
    if (videoFormats.length === 0) {
        return null;
    }

    // 获取用户偏好
    const preferredQuality = localStorage.getItem(QUALITY_KEY);
    if (preferredQuality) {
        const preferredFormat = videoFormats.find(f => 
            f.quality === preferredQuality || f.format_id === preferredQuality
        );
        if (preferredFormat) {
            return preferredFormat;
        }
    }

    // 返回第一个（最高质量）
    return videoFormats[0];
}

// 下载视频
async function downloadVideo(format) {
    const headers = await getHeaders();

    const response = await fetch(`${API_BASE}/api/download`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
            url: currentUrl,
            format_id: format.format_id,
            quality: format.quality
        })
    });

    const data = await response.json();

    if (!data.success) {
        // 检查是否是配额限制
        if (data.message && data.message.includes('配额')) {
            showProModal();
            throw new Error(data.message);
        }
        throw new Error(data.message || '下载失败');
    }

    // 开始轮询下载状态
    await pollDownloadStatus(data.job_id);
}

// 轮询下载状态
async function pollDownloadStatus(jobId) {
    const maxAttempts = 60;
    let attempts = 0;

    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const response = await fetch(`${API_BASE}/api/download/${jobId}`);
                const data = await response.json();

                if (data.status === 'completed') {
                    // 下载文件
                    await downloadFile(jobId);
                    resolve();
                } else if (data.status === 'failed') {
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

// 下载文件
async function downloadFile(jobId) {
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
    a.download = `video_${jobId}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

// 设置加载状态
function setLoading() {
    const btn = document.getElementById('yt-fast-download-btn');
    if (btn) {
        btn.innerHTML = '⏳ Downloading...';
        btn.disabled = true;
    }
}

// 设置完成状态
function setDone() {
    const btn = document.getElementById('yt-fast-download-btn');
    if (btn) {
        btn.innerHTML = '✅ Saved';
        btn.disabled = false;
    }
}

// 显示错误
function showError(message) {
    const btn = document.getElementById('yt-fast-download-btn');
    if (btn) {
        btn.innerHTML = '❌ Error';
        setTimeout(() => {
            btn.innerHTML = '⚡ Download';
        }, 2000);
    }
    alert(message);
}

// 显示Pro弹窗
function showProModal() {
    // 检查是否已存在弹窗
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

    // 绑定事件
    document.getElementById('upgrade-btn').addEventListener('click', () => {
        window.open('http://127.0.0.1:9001/pricing', '_blank');
        closeModal();
    });

    document.getElementById('free-btn').addEventListener('click', async () => {
        await handleDownload('480');
        closeModal();
    });

    document.getElementById('close-modal-btn').addEventListener('click', closeModal);

    // 点击背景关闭
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
}

// 关闭弹窗
function closeModal() {
    const modal = document.getElementById('pro-modal');
    if (modal) {
        modal.remove();
    }
}

// 获取客户端ID
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

// 获取License Key
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

// 获取请求头
async function getHeaders() {
    const clientId = await getClientId();
    const licenseKey = await getLicenseKey();
    
    const headers = {
        'Content-Type': 'application/json',
        'X-Client-ID': clientId
    };
    
    if (licenseKey) {
        headers['X-License-Key'] = licenseKey;
    }
    
    return headers;
}

// 启动
init();