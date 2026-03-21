// DOM Elements
const videoUrlInput = document.getElementById("videoUrl");
const cookieInput = document.getElementById("cookieInput");
const analyzeBtn = document.getElementById("analyzeBtn");
const videoPanel = document.getElementById("videoPanel");
const videoThumbnail = document.getElementById("videoThumbnail");
const videoTitle = document.getElementById("videoTitle");
const videoPlatform = document.getElementById("videoPlatform");
const videoDuration = document.getElementById("videoDuration");
const qualitySelect = document.getElementById("qualitySelect");
const downloadBtn = document.getElementById("downloadBtn");
const cancelBtn = document.getElementById("cancelBtn");
const downloadProgress = document.getElementById("downloadProgress");
const progressFill = document.querySelector(".progress-fill");
const progressText = document.querySelector(".progress-text");
const toast = document.getElementById("toast");
const toastMessage = document.getElementById("toastMessage");

// State
let currentVideoInfo = null;
let currentVideoUrl = null;
let currentCookie = null;
let currentJobId = null;
let statusPollTimer = null;

// Event Listeners
analyzeBtn.addEventListener("click", analyzeVideo);
cancelBtn.addEventListener("click", handleCancelClick);
downloadBtn.addEventListener("click", downloadVideo);

videoUrlInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
        analyzeVideo();
    }
});

// Analyze Video
async function analyzeVideo() {
    const url = videoUrlInput.value.trim();
    const cookie = cookieInput.value.trim();

    if (!url) {
        showToast("请输入视频链接", "error");
        return;
    }

    if (!isValidUrl(url)) {
        showToast("请输入有效的链接地址", "error");
        return;
    }

    currentVideoUrl = url;
    currentCookie = cookie;
    setLoading(true);

    try {
        let apiUrl = `/api/info?url=${encodeURIComponent(url)}`;
        if (cookie) {
            apiUrl += `&cookie=${encodeURIComponent(cookie)}`;
        }

        const response = await fetch(apiUrl);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "分析失败");
        }

        const data = await response.json();
        currentVideoInfo = data;
        displayVideoInfo(data);
        showToast("视频分析成功", "success");
    } catch (error) {
        showToast(error.message || "分析失败，请检查链接是否正确", "error");
        console.error("Analyze error:", error);
    } finally {
        setLoading(false);
    }
}

// Display Video Info
function displayVideoInfo(info) {
    videoThumbnail.src = info.thumbnail || "/static/default-thumb.jpg";
    videoTitle.textContent = info.title;
    videoPlatform.textContent = info.platform;

    if (info.duration) {
        videoDuration.textContent = formatDuration(info.duration);
        videoDuration.classList.remove("hidden");
    } else {
        videoDuration.classList.add("hidden");
    }

    populateQualityOptions(info.formats);
    resetProgressUI();
    videoPanel.classList.remove("hidden");
    videoPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Populate Quality Options
function populateQualityOptions(formats) {
    const seenHeights = new Set();
    let options = "";

    formats.forEach((format) => {
        const height = format.height;
        if (!seenHeights.has(height)) {
            seenHeights.add(height);
            const label = getHeightLabel(height);
            const audioStatus = format.has_audio ? "" : " (需合并音频)";
            options += `<option value="${format.format_id}">${label}${audioStatus}</option>`;
        }
    });

    if (!options) {
        options = '<option value="best">最佳画质</option>';
    }

    qualitySelect.innerHTML = options;
}

function getHeightLabel(height) {
    if (height >= 2160) return "4K (2160p)";
    if (height >= 1440) return "2K (1440p)";
    if (height >= 1080) return "1080p";
    if (height >= 720) return "720p";
    if (height >= 480) return "480p";
    if (height >= 360) return "360p";
    return `${height}p`;
}

// Download Video
async function downloadVideo() {
    if (!currentVideoInfo || !currentVideoUrl) return;
    if (currentJobId) {
        showToast("已有下载任务正在进行", "info");
        return;
    }

    setDownloadingState(true);
    updateProgress(0, "任务已创建，准备下载...");

    try {
        const payload = {
            url: currentVideoUrl,
            format_id: qualitySelect.value,
            cookie: currentCookie || null
        };

        const response = await fetch("/api/download", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "创建下载任务失败");
        }

        const data = await response.json();
        currentJobId = data.job_id;
        showToast("下载任务已提交", "success");
        startStatusPolling();
    } catch (error) {
        setDownloadingState(false);
        showToast(error.message || "下载失败，请重试", "error");
        console.error("Download start error:", error);
    }
}

function startStatusPolling() {
    stopStatusPolling();
    checkDownloadStatus();
    statusPollTimer = setInterval(checkDownloadStatus, 1000);
}

function stopStatusPolling() {
    if (statusPollTimer) {
        clearInterval(statusPollTimer);
        statusPollTimer = null;
    }
}

async function checkDownloadStatus() {
    if (!currentJobId) return;

    try {
        const response = await fetch(`/api/download/${currentJobId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "获取任务状态失败");
        }

        const status = await response.json();
        renderTaskStatus(status);

        if (status.status === "ready") {
            stopStatusPolling();
            updateProgress(100, "下载完成，正在传输文件...");
            triggerBrowserDownload(currentJobId, status.filename);
            showToast("下载完成，浏览器已开始保存文件", "success");
            currentJobId = null;
            setDownloadingState(false);
            setTimeout(() => {
                resetProgressUI();
            }, 3000);
            return;
        }

        if (status.status === "failed" || status.status === "canceled" || status.status === "completed") {
            stopStatusPolling();
            const message = status.error || getStatusText(status.status);
            if (status.status === "failed") {
                showToast(message, "error", 6000);
            } else {
                showToast(message, "info");
            }
            currentJobId = null;
            setDownloadingState(false);
            setTimeout(() => {
                resetProgressUI();
            }, 1500);
        }
    } catch (error) {
        console.error("Status polling error:", error);
        stopStatusPolling();
        setDownloadingState(false);
        showToast(error.message || "任务状态查询失败", "error");
        currentJobId = null;
    }
}

function renderTaskStatus(status) {
    const progressValue = Number.isFinite(status.progress) ? status.progress : 0;
    const speedText = status.speed ? ` | 速度 ${status.speed}` : "";
    const etaText = Number.isFinite(status.eta) ? ` | 剩余 ${formatETA(status.eta)}` : "";
    const statusText = `${getStageText(status)}${speedText}${etaText}`;
    updateProgress(progressValue, statusText);
}

async function handleCancelClick() {
    if (!currentJobId) {
        hideVideoPanel();
        return;
    }

    try {
        const response = await fetch(`/api/download/${currentJobId}/cancel`, { method: "POST" });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "取消任务失败");
        }

        const data = await response.json();
        if (data.status === "canceled") {
            stopStatusPolling();
            showToast("下载已取消", "info");
            currentJobId = null;
            setDownloadingState(false);
            resetProgressUI();
        } else {
            updateProgress(undefined, "正在取消任务...");
            showToast("正在取消下载任务", "info");
        }
    } catch (error) {
        showToast(error.message || "取消失败", "error");
        console.error("Cancel task error:", error);
    }
}

function triggerBrowserDownload(jobId) {
    const link = document.createElement("a");
    link.href = `/api/download/${jobId}/file`;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function getStageText(status) {
    if (status.stage === "queued" || status.status === "queued") return "排队中...";
    if (status.stage === "downloading" || status.status === "downloading") return "正在下载视频...";
    if (status.stage === "processing") return "正在处理视频...";
    if (status.stage === "merging") return "正在合并音视频...";
    if (status.stage === "canceling" || status.status === "canceling") return "正在取消...";
    if (status.stage === "ready" || status.status === "ready") return "任务完成";
    return getStatusText(status.status);
}

function getStatusText(status) {
    if (status === "completed") return "文件已下载";
    if (status === "canceled") return "下载已取消";
    if (status === "failed") return "下载失败";
    if (status === "canceling") return "正在取消";
    return "处理中";
}

function updateProgress(percent, text) {
    downloadProgress.classList.remove("hidden");

    if (Number.isFinite(percent)) {
        const fixed = Math.max(0, Math.min(100, percent));
        progressFill.style.width = `${fixed}%`;
    }

    if (text) {
        progressText.textContent = text;
    }
}

function resetProgressUI() {
    progressFill.style.width = "0%";
    progressText.textContent = "正在下载...";
    downloadProgress.classList.add("hidden");
}

function setDownloadingState(isDownloading) {
    downloadBtn.disabled = isDownloading;
    qualitySelect.disabled = isDownloading;
    downloadBtn.querySelector(".btn-text").textContent = isDownloading ? "任务进行中..." : "开始下载";
    cancelBtn.textContent = isDownloading ? "取消下载" : "取消";
    if (!isDownloading) {
        qualitySelect.disabled = false;
    }
}

function hideVideoPanel() {
    stopStatusPolling();
    currentJobId = null;
    videoPanel.classList.add("hidden");
    currentVideoInfo = null;
    currentCookie = null;
    setDownloadingState(false);
    resetProgressUI();
}

// Set Loading State
function setLoading(loading) {
    analyzeBtn.disabled = loading;
    analyzeBtn.querySelector(".btn-text").classList.toggle("hidden", loading);
    analyzeBtn.querySelector(".btn-loading").classList.toggle("hidden", !loading);
}

// Show Toast
function showToast(message, type = "info", duration = 4000) {
    toastMessage.textContent = message;
    toast.className = "toast";
    toast.classList.add(type);
    toast.classList.remove("hidden");

    setTimeout(() => {
        toast.classList.add("hidden");
    }, duration);
}

// Validate URL
function isValidUrl(string) {
    try {
        const url = new URL(string);
        return url.protocol === "http:" || url.protocol === "https:";
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
        return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }
    return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function formatETA(seconds) {
    if (seconds <= 0) return "即将完成";
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remain = seconds % 60;
    if (minutes < 60) return `${minutes}m ${remain}s`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}m`;
}

// Smooth scroll for navigation
document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute("href"));
        if (target) {
            target.scrollIntoView({
                behavior: "smooth",
                block: "start"
            });
        }
    });
});
