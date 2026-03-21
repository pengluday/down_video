// 视频下载器 - 简化版
// 只作为入口，所有解析和下载功能由后端处理

const API_BASE = 'http://127.0.0.1:9001';
const CLIENT_ID_KEY = 'video_downloader_client_id';
const LICENSE_KEY_KEY = 'video_downloader_license_key';

let currentJobId = null;
let pollTimeout = null;
let selectedFormatId = null;
let videoFormats = [];
let clientId = null;
let isClientIdReady = false;
let licenseKey = null;
let isPro = false;
let pollCount = 0;
const MAX_POLL_COUNT = 3600;

// DOM 元素
const urlInput = document.getElementById('urlInput');
const downloadBtn = document.getElementById('downloadBtn');
const qualitySelect = document.getElementById('qualitySelect');
const statusDiv = document.getElementById('status');
const progressContainer = document.getElementById('progressContainer');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const speedText = document.getElementById('speedText');
const videoInfoDiv = document.getElementById('videoInfo');
const videoTitle = document.getElementById('videoTitle');
const videoPlatform = document.getElementById('videoPlatform');
const videoDuration = document.getElementById('videoDuration');
const formatList = document.getElementById('formatList');
const licenseKeyInput = document.getElementById('licenseKeyInput');
const activateBtn = document.getElementById('activateBtn');
const licenseStatus = document.getElementById('licenseStatus');
const proBadge = document.getElementById('proBadge');

// 生成唯一的客户端ID
function generateClientId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

// 获取或创建客户端ID
async function getOrCreateClientId() {
  try {
    const result = await chrome.storage.local.get(CLIENT_ID_KEY);
    if (result[CLIENT_ID_KEY]) {
      clientId = result[CLIENT_ID_KEY];
    } else {
      clientId = generateClientId();
      await chrome.storage.local.set({ [CLIENT_ID_KEY]: clientId });
    }
    isClientIdReady = true;
    return clientId;
  } catch (error) {
    console.error('获取客户端ID失败:', error);
    return null;
  }
}

// 获取或创建License Key
async function getOrCreateLicenseKey() {
  try {
    const result = await chrome.storage.local.get(LICENSE_KEY_KEY);
    if (result[LICENSE_KEY_KEY]) {
      licenseKey = result[LICENSE_KEY_KEY];
      licenseKeyInput.value = licenseKey;
      await verifyLicenseKey();
    }
  } catch (error) {
    console.error('获取License Key失败:', error);
  }
}

// 验证License Key
async function verifyLicenseKey() {
  if (!licenseKey) {
    isPro = false;
    proBadge.classList.add('hidden');
    return false;
  }

  try {
    const response = await fetch(`${API_BASE}/api/license/verify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        license_key: licenseKey
      })
    });

    const data = await response.json();

    if (data.success && data.is_valid) {
      isPro = true;
      proBadge.classList.remove('hidden');
      showLicenseStatus('success', 'License Key已激活，享受Pro特权！');
      return true;
    } else {
      isPro = false;
      proBadge.classList.add('hidden');
      showLicenseStatus('error', 'License Key无效或已过期');
      return false;
    }
  } catch (error) {
    console.error('验证License Key失败:', error);
    isPro = false;
    proBadge.classList.add('hidden');
    showLicenseStatus('error', '验证失败，请检查网络连接');
    return false;
  }
}

// 激活License Key
async function activateLicenseKey() {
  const key = licenseKeyInput.value.trim().toUpperCase();

  if (!key) {
    showLicenseStatus('error', '请输入License Key');
    return;
  }

  // 验证格式
  const keyFormat = /^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/;
  if (!keyFormat.test(key)) {
    showLicenseStatus('error', 'License Key格式错误，应为XXXX-XXXX-XXXX-XXXX');
    return;
  }

  activateBtn.disabled = true;
  activateBtn.textContent = '激活中...';

  try {
    const response = await fetch(`${API_BASE}/api/license/activate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        license_key: key
      })
    });

    const data = await response.json();

    if (data.success) {
      licenseKey = key;
      await chrome.storage.local.set({ [LICENSE_KEY_KEY]: key });
      isPro = true;
      proBadge.classList.remove('hidden');
      showLicenseStatus('success', '激活成功！享受Pro特权');
    } else {
      isPro = false;
      proBadge.classList.add('hidden');
      showLicenseStatus('error', data.detail || '激活失败');
    }
  } catch (error) {
    console.error('激活License Key失败:', error);
    showLicenseStatus('error', '激活失败，请检查网络连接');
  } finally {
    activateBtn.disabled = false;
    activateBtn.textContent = '激活';
  }
}

// 显示License状态
function showLicenseStatus(type, message) {
  licenseStatus.textContent = message;
  licenseStatus.className = `license-status ${type}`;
  licenseStatus.classList.remove('hidden');

  // 3秒后自动隐藏成功消息
  if (type === 'success') {
    setTimeout(() => {
      licenseStatus.classList.add('hidden');
    }, 3000);
  }
}

// 获取请求头（包含License Key）
function getRequestHeaders() {
  const headers = {
    'Content-Type': 'application/json',
    'X-Client-ID': clientId
  };

  if (licenseKey) {
    headers['X-License-Key'] = licenseKey;
  }

  return headers;
}

// 创建带客户端标识的请求头
function createHeaders() {
  if (!isClientIdReady || !clientId) {
    const headers = {
      'Content-Type': 'application/json',
      'X-Client-ID': generateClientId(),
      'X-Client-Type': 'chrome-extension',
      'X-Client-Version': '2.0.0'
    };
    
    if (licenseKey) {
      headers['X-License-Key'] = licenseKey;
    }
    
    return headers;
  }
  
  const headers = {
    'Content-Type': 'application/json',
    'X-Client-ID': clientId,
    'X-Client-Type': 'chrome-extension',
    'X-Client-Version': '2.0.0'
  };
  
  if (licenseKey) {
    headers['X-License-Key'] = licenseKey;
  }
  
  return headers;
}

// 确保客户端ID已初始化
async function ensureClientIdReady() {
  if (!isClientIdReady) {
    await getOrCreateClientId();
  }
  return clientId;
}

// 请求必要的权限
function requestPermissions(url) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const origin = `${urlObj.protocol}//${urlObj.host}/*`;
    
    chrome.permissions.request({
      origins: [origin]
    }, (granted) => {
      if (granted) {
        resolve(true);
      } else {
        reject(new Error('权限被拒绝'));
      }
    });
  });
}

// 检查是否有权限
function hasPermission(url) {
  return new Promise((resolve) => {
    const urlObj = new URL(url);
    const origin = `${urlObj.protocol}//${urlObj.host}/*`;
    
    chrome.permissions.contains({
      origins: [origin]
    }, (result) => {
      resolve(result);
    });
  });
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', async () => {
  await getOrCreateClientId();
  await getOrCreateLicenseKey();
  
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url) {
      urlInput.value = tab.url;
    }
  } catch (error) {
  }
});

// 激活按钮事件
activateBtn.addEventListener('click', activateLicenseKey);

// 显示状态
function showStatus(message, type = 'loading') {
  statusDiv.textContent = message;
  statusDiv.className = `status ${type}`;
  statusDiv.classList.remove('hidden');
}

// 隐藏状态
function hideStatus() {
  statusDiv.classList.add('hidden');
}

// 显示进度条
function showProgress(percent, speed = null) {
  progressContainer.classList.remove('hidden');
  progressFill.style.width = `${percent}%`;
  progressText.textContent = `${percent.toFixed(1)}%`;
  if (speed) {
    speedText.textContent = speed;
  }
}

// 隐藏进度条
function hideProgress() {
  progressContainer.classList.add('hidden');
  progressFill.style.width = '0%';
  progressText.textContent = '0%';
  speedText.textContent = '0 KB/s';
}

// 格式化时长
function formatDuration(seconds) {
  if (!seconds) return '未知';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

// 解析视频
async function parseVideo() {
  await ensureClientIdReady();
  
  const url = urlInput.value.trim();
  
  if (!url) {
    showStatus('请输入视频链接', 'error');
    return;
  }
  
  downloadBtn.disabled = true;
  downloadBtn.textContent = '解析中...';
  showStatus('正在解析视频信息...');
  hideProgress();
  
  try {
    const hasPerm = await hasPermission(url);
    if (!hasPerm) {
      showStatus('需要访问该网站的权限，请点击允许', 'info');
      try {
        await requestPermissions(url);
      } catch (error) {
        showStatus('需要权限才能继续', 'error');
        downloadBtn.disabled = false;
        downloadBtn.textContent = '解析视频';
        return;
      }
    }
    
    const response = await fetch(`${API_BASE}/api/info?url=${encodeURIComponent(url)}`, {
      method: 'GET',
      headers: createHeaders()
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || '解析失败');
    }
    
    const data = await response.json();
    
    videoTitle.textContent = data.title || '未知标题';
    videoPlatform.textContent = data.platform || '未知';
    videoDuration.textContent = formatDuration(data.duration);
    videoInfoDiv.classList.remove('hidden');
    
    videoFormats = data.formats || [];
    displayFormats(videoFormats);
    
    downloadBtn.textContent = '开始下载';
    downloadBtn.disabled = false;
    downloadBtn.onclick = startDownload;
    
    showStatus('解析完成，请选择格式后下载', 'success');
    setTimeout(hideStatus, 3000);
    
  } catch (error) {
    showStatus(`解析失败: ${error.message}`, 'error');
    downloadBtn.disabled = false;
    downloadBtn.textContent = '解析视频';
  }
}

// 显示格式列表
function displayFormats(formats) {
  formatList.innerHTML = '';
  
  if (!formats || formats.length === 0) {
    formatList.innerHTML = '<p style="color: #666; grid-column: span 2; text-align: center; padding: 20px;">未找到可用格式</p>';
    return;
  }
  
  const displayFormats = formats.slice(0, 8);
  
  displayFormats.forEach((format, index) => {
    const item = document.createElement('div');
    item.className = 'format-item';
    if (index === 0) {
      item.classList.add('selected');
      selectedFormatId = format.format_id;
    }
    
    const sizeText = format.filesize ? 
      `${(format.filesize / 1024 / 1024).toFixed(1)} MB` : 
      '大小未知';
    
    item.innerHTML = `
      <span class="format-resolution">${format.height}p</span>
      <span class="format-size">${sizeText}</span>
    `;
    
    item.onclick = () => {
      document.querySelectorAll('.format-item').forEach(el => el.classList.remove('selected'));
      item.classList.add('selected');
      selectedFormatId = format.format_id;
    };
    
    formatList.appendChild(item);
  });
}

// 开始下载
async function startDownload() {
  await ensureClientIdReady();
  
  const url = urlInput.value.trim();
  
  if (!url) {
    showStatus('请输入视频链接', 'error');
    return;
  }
  
  downloadBtn.disabled = true;
  downloadBtn.textContent = '下载中...';
  showStatus('正在创建下载任务...');
  hideProgress();
  
  try {
    const requestBody = {
      url: url,
      format_id: selectedFormatId || undefined,
      quality: qualitySelect.value ? parseInt(qualitySelect.value) : undefined
    };
    
    const response = await fetch(`${API_BASE}/api/download`, {
      method: 'POST',
      headers: createHeaders(),
      body: JSON.stringify(requestBody)
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || '创建下载任务失败');
    }
    
    const data = await response.json();
    currentJobId = data.job_id;
    
    showStatus('下载任务已创建，正在下载...');
    showProgress(0);
    
    pollCount = 0;
    startPolling(currentJobId);
    
  } catch (error) {
    showStatus(`下载失败: ${error.message}`, 'error');
    downloadBtn.disabled = false;
    downloadBtn.textContent = '开始下载';
  }
}

// 根据阶段获取轮询间隔
function getPollInterval(stage) {
  switch (stage) {
    case 'queued':
      return 3000;
    case 'downloading':
      return 1000;
    case 'merging':
      return 2000;
    case 'processing':
      return 1500;
    case 'ready':
      return 500;
    default:
      return 2000;
  }
}

// 轮询任务状态
async function startPolling(jobId) {
  if (pollTimeout) {
    clearTimeout(pollTimeout);
  }
  
  pollCount++;
  
  if (pollCount > MAX_POLL_COUNT) {
    showStatus('下载超时，请重试', 'error');
    downloadBtn.disabled = false;
    downloadBtn.textContent = '开始下载';
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE}/api/download/${jobId}`, {
      method: 'GET',
      headers: createHeaders()
    });
    
    if (!response.ok) {
      throw new Error('获取任务状态失败');
    }
    
    const job = await response.json();
    
    if (job.progress !== undefined) {
      showProgress(job.progress, job.speed || null);
    }
    
    let statusText = '';
    switch (job.stage) {
      case 'queued':
        statusText = '等待中...';
        break;
      case 'downloading':
        statusText = `下载中... ${job.progress?.toFixed(1) || 0}%`;
        break;
      case 'merging':
        statusText = '合并音视频...';
        break;
      case 'processing':
        statusText = '处理中...';
        break;
      case 'ready':
        statusText = '下载完成，准备保存...';
        break;
      case 'completed':
        statusText = '下载完成！';
        break;
      case 'failed':
        statusText = `下载失败: ${job.error || '未知错误'}`;
        break;
      case 'canceled':
        statusText = '下载已取消';
        break;
      default:
        statusText = job.stage || '处理中...';
    }
    
    showStatus(statusText, job.stage === 'failed' ? 'error' : 'loading');
    
    if (['ready', 'completed', 'failed', 'canceled'].includes(job.stage)) {
      if (job.stage === 'ready' || job.stage === 'completed') {
        await downloadFile(jobId, job.filename);
        showStatus('下载完成！', 'success');
      }
      
      downloadBtn.disabled = false;
      downloadBtn.textContent = '开始下载';
      setTimeout(hideProgress, 2000);
      return;
    }
    
    const nextInterval = getPollInterval(job.stage);
    pollTimeout = setTimeout(() => startPolling(jobId), nextInterval);
    
  } catch (error) {
    const nextInterval = getPollInterval('queued');
    pollTimeout = setTimeout(() => startPolling(jobId), nextInterval);
  }
}

// 下载文件
async function downloadFile(jobId, filename) {
  try {
    const downloadUrl = `${API_BASE}/api/download/${jobId}/file`;
    
    await chrome.downloads.download({
      url: downloadUrl,
      filename: filename || 'video.mp4',
      saveAs: false
    });
    
  } catch (error) {
    showStatus('文件保存失败', 'error');
  }
}

// 绑定按钮事件
downloadBtn.addEventListener('click', () => {
  if (downloadBtn.textContent === '解析视频') {
    parseVideo();
  } else if (downloadBtn.textContent === '开始下载') {
    startDownload();
  }
});

// 清理
window.addEventListener('beforeunload', () => {
  if (pollTimeout) {
    clearTimeout(pollTimeout);
  }
});