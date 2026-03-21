// 视频下载器 - 简化版
// 只作为入口，所有解析和下载功能由后端处理

const API_BASE = 'http://47.99.72.247:9001';
const CLIENT_ID_KEY = 'video_downloader_client_id';

let currentJobId = null;
let pollInterval = null;
let selectedFormatId = null;
let videoFormats = [];
let clientId = null;
let isClientIdReady = false;

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
      console.log('已存在客户端ID:', clientId);
    } else {
      clientId = generateClientId();
      await chrome.storage.local.set({ [CLIENT_ID_KEY]: clientId });
      console.log('已创建新客户端ID:', clientId);
    }
    isClientIdReady = true;
    return clientId;
  } catch (error) {
    console.error('获取客户端ID失败:', error);
    clientId = generateClientId();
    isClientIdReady = true;
    return clientId;
  }
}

// 创建带客户端标识的请求头
function createHeaders() {
  if (!isClientIdReady || !clientId) {
    console.warn('客户端ID未准备好，使用临时ID');
    return {
      'Content-Type': 'application/json',
      'X-Client-ID': generateClientId(),
      'X-Client-Type': 'chrome-extension',
      'X-Client-Version': '2.0.0'
    };
  }
  
  console.log('发送请求，客户端ID:', clientId);
  return {
    'Content-Type': 'application/json',
    'X-Client-ID': clientId,
    'X-Client-Type': 'chrome-extension',
    'X-Client-Version': '2.0.0'
  };
}

// 确保客户端ID已初始化
async function ensureClientIdReady() {
  if (!isClientIdReady) {
    console.log('等待客户端ID初始化...');
    await getOrCreateClientId();
  }
  console.log('客户端ID已就绪:', clientId);
  return clientId;
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', async () => {
  // 初始化客户端ID
  await getOrCreateClientId();
  
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url) {
      // 自动填充当前页面的URL
      urlInput.value = tab.url;
      console.log('已自动填充当前页面URL:', tab.url);
    }
  } catch (error) {
    console.error('获取当前标签页失败:', error);
  }
});

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
  // 确保客户端ID已就绪
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
    const response = await fetch(`${API_BASE}/api/info?url=${encodeURIComponent(url)}`, {
      method: 'GET',
      headers: createHeaders()
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || '解析失败');
    }
    
    const data = await response.json();
    
    // 显示视频信息
    videoTitle.textContent = data.title || '未知标题';
    videoPlatform.textContent = data.platform || '未知';
    videoDuration.textContent = formatDuration(data.duration);
    videoInfoDiv.classList.remove('hidden');
    
    // 保存格式列表
    videoFormats = data.formats || [];
    
    // 显示格式选择
    displayFormats(videoFormats);
    
    // 更改按钮状态
    downloadBtn.textContent = '开始下载';
    downloadBtn.disabled = false;
    downloadBtn.onclick = startDownload;
    
    showStatus('解析完成，请选择格式后下载', 'success');
    setTimeout(hideStatus, 3000);
    
  } catch (error) {
    console.error('解析视频失败:', error);
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
  
  // 只显示前8个格式
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
  // 确保客户端ID已就绪
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
    
    // 开始轮询任务状态
    startPolling(currentJobId);
    
  } catch (error) {
    console.error('创建下载任务失败:', error);
    showStatus(`下载失败: ${error.message}`, 'error');
    downloadBtn.disabled = false;
    downloadBtn.textContent = '开始下载';
  }
}

// 轮询任务状态
function startPolling(jobId) {
  if (pollInterval) {
    clearInterval(pollInterval);
  }
  
  pollInterval = setInterval(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/download/${jobId}`, {
        method: 'GET',
        headers: createHeaders()
      });
      
      if (!response.ok) {
        throw new Error('获取任务状态失败');
      }
      
      const job = await response.json();
      
      // 更新进度
      if (job.progress !== undefined) {
        showProgress(job.progress, job.speed || null);
      }
      
      // 更新状态文本
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
      
      // 任务完成或失败
      if (['ready', 'completed', 'failed', 'canceled'].includes(job.stage)) {
        clearInterval(pollInterval);
        pollInterval = null;
        
        if (job.stage === 'ready' || job.stage === 'completed') {
          // 下载文件
          await downloadFile(jobId, job.filename);
          showStatus('下载完成！', 'success');
        }
        
        downloadBtn.disabled = false;
        downloadBtn.textContent = '开始下载';
        setTimeout(hideProgress, 2000);
      }
      
    } catch (error) {
      console.error('轮询任务状态失败:', error);
    }
  }, 1000);
}

// 下载文件
async function downloadFile(jobId, filename) {
  try {
    const downloadUrl = `${API_BASE}/api/download/${jobId}/file`;
    
    // 使用Chrome下载API，直接保存到默认下载路径
    await chrome.downloads.download({
      url: downloadUrl,
      filename: filename || 'video.mp4',
      saveAs: false
    });
    
  } catch (error) {
    console.error('下载文件失败:', error);
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
  if (pollInterval) {
    clearInterval(pollInterval);
  }
});