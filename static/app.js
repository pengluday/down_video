// DOM Elements
const videoUrlInput = document.getElementById('videoUrl');
const analyzeBtn = document.getElementById('analyzeBtn');
const videoPanel = document.getElementById('videoPanel');
const videoThumbnail = document.getElementById('videoThumbnail');
const videoTitle = document.getElementById('videoTitle');
const videoPlatform = document.getElementById('videoPlatform');
const videoDuration = document.getElementById('videoDuration');
const qualitySelect = document.getElementById('qualitySelect');
const downloadBtn = document.getElementById('downloadBtn');
const cancelBtn = document.getElementById('cancelBtn');
const downloadProgress = document.getElementById('downloadProgress');
const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toastMessage');

// State
let currentVideoInfo = null;
let currentVideoUrl = null;

// Event Listeners
analyzeBtn.addEventListener('click', analyzeVideo);
cancelBtn.addEventListener('click', hideVideoPanel);
downloadBtn.addEventListener('click', downloadVideo);

videoUrlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        analyzeVideo();
    }
});

// Analyze Video
async function analyzeVideo() {
    const url = videoUrlInput.value.trim();
    
    if (!url) {
        showToast('请输入视频链接', 'error');
        return;
    }
    
    if (!isValidUrl(url)) {
        showToast('请输入有效的链接地址', 'error');
        return;
    }
    
    currentVideoUrl = url;
    setLoading(true);
    
    try {
        const response = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '分析失败');
        }
        
        const data = await response.json();
        currentVideoInfo = data;
        
        displayVideoInfo(data);
        showToast('视频分析成功！', 'success');
        
    } catch (error) {
        showToast(error.message || '分析失败，请检查链接是否正确', 'error');
        console.error('Analyze error:', error);
    } finally {
        setLoading(false);
    }
}

// Display Video Info
function displayVideoInfo(info) {
    videoThumbnail.src = info.thumbnail || '/static/default-thumb.jpg';
    videoTitle.textContent = info.title;
    videoPlatform.textContent = info.platform;
    
    if (info.duration) {
        videoDuration.textContent = formatDuration(info.duration);
        videoDuration.classList.remove('hidden');
    } else {
        videoDuration.classList.add('hidden');
    }
    
    populateQualityOptions(info.formats);
    
    videoPanel.classList.remove('hidden');
    videoPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Populate Quality Options
function populateQualityOptions(formats) {
    const seenHeights = new Set();
    let options = '';
    
    formats.forEach(f => {
        const height = f.height;
        if (!seenHeights.has(height)) {
            seenHeights.add(height);
            const label = getHeightLabel(height);
            const audioStatus = f.has_audio ? '' : ' (需合并音频)';
            options += `<option value="${f.format_id}">${label}${audioStatus}</option>`;
        }
    });
    
    if (!options) {
        options = '<option value="best">最佳画质</option>';
    }
    
    qualitySelect.innerHTML = options;
}

function getHeightLabel(height) {
    if (height >= 2160) return '4K (2160p)';
    if (height >= 1440) return '2K (1440p)';
    if (height >= 1080) return '1080p';
    if (height >= 720) return '720p';
    if (height >= 480) return '480p';
    if (height >= 360) return '360p';
    return `${height}p`;
}

// Download Video
async function downloadVideo() {
    if (!currentVideoInfo || !currentVideoUrl) return;

    const formatId = qualitySelect.value;

    downloadBtn.disabled = true;
    downloadBtn.querySelector('.btn-text').textContent = '服务器下载中...';
    downloadProgress.classList.remove('hidden');

    try {
        const downloadUrl = `/api/download?url=${encodeURIComponent(currentVideoUrl)}&format_id=${formatId}`;
        
        showToast('服务器正在下载视频，请稍候...', 'info');
        
        // 直接创建下载链接，让浏览器处理下载
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = sanitizeFilename(currentVideoInfo.title) + '.mp4';
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        showToast('视频下载已开始！', 'success');
        hideVideoPanel();
        
    } catch (error) {
        showToast(error.message || '下载失败，请重试', 'error');
        console.error('Download error:', error);
    } finally {
        downloadBtn.disabled = false;
        downloadBtn.querySelector('.btn-text').textContent = '开始下载';
        downloadProgress.classList.add('hidden');
    }
}

function hideVideoPanel() {
    videoPanel.classList.add('hidden');
    currentVideoInfo = null;
}

// Set Loading State
function setLoading(loading) {
    analyzeBtn.disabled = loading;
    analyzeBtn.querySelector('.btn-text').classList.toggle('hidden', loading);
    analyzeBtn.querySelector('.btn-loading').classList.toggle('hidden', !loading);
}

// Show Toast
function showToast(message, type = 'info') {
    toastMessage.textContent = message;
    toast.className = 'toast';
    toast.classList.add(type);
    toast.classList.remove('hidden');
    
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 4000);
}

// Validate URL
function isValidUrl(string) {
    try {
        const url = new URL(string);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_) {
        return false;
    }
}

// Format Duration
function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

// Sanitize Filename
function sanitizeFilename(filename) {
    return filename
        .replace(/[<>:"/\\|?*]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .substring(0, 200);
}

// Smooth scroll for navigation
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});
