"""
视频下载工具 - 商业化版本
使用License Key系统替代用户登录系统

架构：浏览器 -> FastAPI 任务接口 -> 后台下载线程 -> 浏览器拉取文件
"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
import asyncio
import logging
import logging.handlers
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
import webbrowser

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
import uvicorn
import yt_dlp

from history import history_db, start_cleanup_scheduler
from models import SubscriptionTier, SubscriptionCreate
from database import init_database
from rate_limiter import (
    check_download_allowed, get_user_limits_info,
    record_download, get_client_ip, RateLimitExceeded, QuotaExceeded
)
from license import (
    create_license, verify_license, activate_license,
    get_license_info, revoke_license, get_license_by_stripe_session
)
from payment import (
    create_customer, create_checkout_session, get_price_info,
    construct_webhook_event, handle_webhook_event, PaymentError
)


# ============= 日志配置 =============
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

def setup_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    root_logger.addHandler(console_handler)
    
    error_handler = logging.StreamHandler(sys.stderr)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    error_file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)
    root_logger.addHandler(error_file_handler)
    
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("stripe").setLevel(logging.WARNING)

setup_logging()
logger = logging.getLogger(__name__)


# 临时文件目录
TEMP_DIR = Path(tempfile.gettempdir()) / "video_downloader"
TEMP_DIR.mkdir(exist_ok=True)

# 下载任务配置
MAX_DOWNLOAD_WORKERS = 2
JOB_RETENTION_SECONDS = 60 * 60
FINAL_STATES = {"ready", "completed", "failed", "canceled"}


@dataclass
class DownloadJob:
    job_id: str
    url: str
    format_id: str | None
    quality: int | None
    cookie: str | None
    user_id: str | None = None
    client_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "queued"
    stage: str = "queued"
    progress: float = 0.0
    speed: str | None = None
    eta: int | None = None
    error: str | None = None
    file_path: str | None = None
    filename: str | None = None
    file_size: int | None = None
    work_dir: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


DOWNLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS)
DOWNLOAD_JOBS: dict[str, DownloadJob] = {}
JOB_LOCK = threading.Lock()


class DownloadStartRequest(BaseModel):
    url: str
    format_id: str | None = None
    quality: int | None = None
    cookie: str | None = None


def sanitize_filename(filename: str) -> str:
    invalid_chars = set('<>:"/\\|?*')
    safe_title = "".join(
        "_" if (ord(c) < 32 or c in invalid_chars) else c
        for c in filename
    )
    safe_title = " ".join(safe_title.split()).strip().strip(".")
    if not safe_title:
        safe_title = "video"
    return safe_title[:200]


def build_content_disposition(filename: str) -> str:
    encoded_filename = quote(filename)
    fallback_ascii = "".join(
        c if c.isascii() and 32 <= ord(c) < 127 and c not in {'"', "\\"} else "_"
        for c in filename
    ).strip()
    if not fallback_ascii:
        fallback_ascii = "video.mp4"
    return f"attachment; filename=\"{fallback_ascii}\"; filename*=UTF-8''{encoded_filename}"


def format_speed(speed_bytes: float | None) -> str | None:
    if not speed_bytes:
        return None
    if speed_bytes > 1024 * 1024:
        return f"{speed_bytes / (1024 * 1024):.2f} MB/s"
    return f"{speed_bytes / 1024:.2f} KB/s"


def build_format_string(format_id: str | None, quality: int | None, max_quality: int = 1080) -> str:
    # 限制质量不超过用户允许的最大值
    if quality and quality > max_quality:
        quality = max_quality
    
    if format_id:
        if "+" in format_id:
            return format_id
        return f"{format_id}+bestaudio/best"
    if quality:
        return f"best[height<={quality}]+bestaudio/best[height<={quality}]/best"
    return f"best[height<={max_quality}]+bestaudio/best[height<={max_quality}]/best"


def cleanup_job_files(job: DownloadJob) -> None:
    try:
        if job.file_path:
            file_path = Path(job.file_path)
            if file_path.exists():
                file_path.unlink()
    except Exception as ex:
        logger.warning("删除任务文件失败: job_id=%s err=%s", job.job_id, ex)

    if job.work_dir:
        try:
            work_dir = Path(job.work_dir)
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
        except Exception as ex:
            logger.warning("删除任务目录失败: job_id=%s err=%s", job.job_id, ex)


def cleanup_expired_jobs() -> None:
    now = time.time()
    expired_jobs: list[DownloadJob] = []

    with JOB_LOCK:
        for job_id, job in list(DOWNLOAD_JOBS.items()):
            if job.status in FINAL_STATES and now - job.updated_at > JOB_RETENTION_SECONDS:
                expired_jobs.append(job)
                del DOWNLOAD_JOBS[job_id]

    for job in expired_jobs:
        cleanup_job_files(job)


def serialize_job(job: DownloadJob) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage": job.stage,
        "progress": round(job.progress, 2),
        "speed": job.speed,
        "eta": job.eta,
        "error": job.error,
        "filename": job.filename,
        "file_size": job.file_size,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def get_job_or_404(job_id: str) -> DownloadJob:
    with JOB_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def run_download_job(job_id: str) -> None:
    with JOB_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job:
            return
        job.status = "downloading"
        job.stage = "downloading"
        job.updated_at = time.time()

    logger.info("[Download] 任务开始: %s", job_id)
    work_dir = TEMP_DIR / f"job_{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    with JOB_LOCK:
        if job_id in DOWNLOAD_JOBS:
            DOWNLOAD_JOBS[job_id].work_dir = str(work_dir)

    # 获取用户限制
    max_quality = 1080
    if job.user_id:
        # user_id可能是License Key
        from license import verify_license
        is_valid, license_info = verify_license(job.user_id)
        if is_valid:
            from models import SUBSCRIPTION_LIMITS, SubscriptionTier
            tier_value = license_info.get('tier', 'free')
            tier = SubscriptionTier(tier_value) if tier_value in [t.value for t in SubscriptionTier] else SubscriptionTier.FREE
            limits = SUBSCRIPTION_LIMITS.get(tier)
            if limits:
                max_quality = limits.max_resolution

    format_str = build_format_string(job.format_id, job.quality, max_quality)

    def progress_hook(data: dict) -> None:
        with JOB_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            if not current:
                return
            cancel_requested = current.cancel_event.is_set()

        if cancel_requested:
            raise yt_dlp.utils.DownloadError("DOWNLOAD_CANCELED")

        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes") or 0
            progress = 0.0
            if total and total > 0:
                progress = min(99.0, downloaded * 100 / total)
            with JOB_LOCK:
                current = DOWNLOAD_JOBS.get(job_id)
                if current:
                    current.progress = progress
                    current.speed = format_speed(data.get("speed"))
                    current.eta = data.get("eta")
                    current.stage = "downloading"
                    current.updated_at = time.time()
        elif data.get("status") == "finished":
            with JOB_LOCK:
                current = DOWNLOAD_JOBS.get(job_id)
                if current:
                    current.progress = max(current.progress, 99.0)
                    current.stage = "processing"
                    current.updated_at = time.time()

    def postprocessor_hook(data: dict) -> None:
        with JOB_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            if not current:
                return
            cancel_requested = current.cancel_event.is_set()

        if cancel_requested:
            raise yt_dlp.utils.DownloadError("DOWNLOAD_CANCELED")

        status = data.get("status")
        if status in {"started", "processing"}:
            with JOB_LOCK:
                current = DOWNLOAD_JOBS.get(job_id)
                if current:
                    current.stage = "merging"
                    current.progress = max(current.progress, 99.0)
                    current.updated_at = time.time()

    ydl_opts = {
        "format": format_str,
        "outtmpl": str(work_dir / "%(title).120B [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "postprocessor_args": {
            "ffmpeg": ["-c:a", "aac", "-b:a", "192k"]
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web", "ios", "tv"],
                "player_skip": ["configs"],
            }
        },
    }

    if job.cookie:
        cookie_path = Path(job.cookie)
        if cookie_path.exists():
            ydl_opts["cookiefile"] = str(cookie_path)
        else:
            ydl_opts["http_headers"] = {"Cookie": job.cookie}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(job.url, download=True)

        with JOB_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            if not current:
                return
            if current.cancel_event.is_set():
                current.status = "canceled"
                current.stage = "canceled"
                current.error = "下载已取消"
                current.updated_at = time.time()
        if current.cancel_event.is_set():
            cleanup_job_files(current)
            return

        downloaded_file: Path | None = None

        if isinstance(info, dict):
            requested_downloads = info.get("requested_downloads") or []
            for item in requested_downloads:
                filepath = item.get("filepath")
                if filepath:
                    candidate = Path(filepath)
                    if candidate.exists():
                        downloaded_file = candidate
                        break

            if not downloaded_file:
                for ext in (".mp4", ".webm", ".mkv", ".flv", ".mov"):
                    files = list(work_dir.glob(f"*{ext}"))
                    if files:
                        downloaded_file = max(files, key=lambda p: p.stat().st_mtime)
                        break

            if not downloaded_file:
                all_files = [p for p in work_dir.glob("*") if p.is_file()]
                if all_files:
                    downloaded_file = max(all_files, key=lambda p: p.stat().st_mtime)

            if not downloaded_file or not downloaded_file.exists():
                raise RuntimeError("下载失败：未找到输出文件")

            title = info.get("title") or "video"
            suffix = downloaded_file.suffix or ".mp4"
            filename = f"{sanitize_filename(title)}{suffix}"
            file_size = downloaded_file.stat().st_size

            with JOB_LOCK:
                current = DOWNLOAD_JOBS.get(job_id)
                if current:
                    current.status = "ready"
                    current.stage = "ready"
                    current.progress = 100.0
                    current.filename = filename
                    current.file_path = str(downloaded_file)
                    current.file_size = file_size
                    current.speed = None
                    current.eta = None
                    current.updated_at = time.time()

            try:
                platform = "unknown"
                if job.url:
                    url_lower = job.url.lower()
                    if "youtube" in url_lower:
                        platform = "youtube"
                    elif "tiktok" in url_lower:
                        platform = "tiktok"
                    elif "bilibili" in url_lower:
                        platform = "bilibili"
                
                history_db.add_record(
                    video_title=title,
                    file_size=file_size,
                    download_url=job.url,
                    platform=platform,
                    duration=info.get("duration"),
                    client_id=job.client_id
                )
                logger.info(f"[History] 已保存下载历史: {title} (客户端: {job.client_id})")
            except Exception as e:
                logger.error(f"[History] 保存历史记录失败: {e}")

            logger.info(
                "[Download] 任务完成: %s 文件=%s 大小=%.2fMB",
                job_id,
                filename,
                file_size / 1024 / 1024,
            )
            return

        raise RuntimeError("下载失败：提取信息返回异常")

    except yt_dlp.utils.DownloadError as ex:
        error_message = str(ex)
        with JOB_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            if current:
                if current.cancel_event.is_set() or "DOWNLOAD_CANCELED" in error_message:
                    current.status = "canceled"
                    current.stage = "canceled"
                    current.error = "下载已取消"
                else:
                    current.status = "failed"
                    current.stage = "failed"
                    current.error = f"下载失败: {error_message}"
                current.updated_at = time.time()
        logger.warning("[Download] 任务失败: %s 错误=%s", job_id, error_message)
    except Exception as ex:
        with JOB_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            if current:
                current.status = "failed"
                current.stage = "failed"
                current.error = f"下载失败: {ex}"
                current.updated_at = time.time()
        logger.exception("[Download] 任务异常: %s", job_id)


def mark_job_downloaded(job_id: str) -> None:
    with JOB_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job:
            return
        job.status = "completed"
        job.stage = "completed"
        job.updated_at = time.time()
    cleanup_job_files(job)
    with JOB_LOCK:
        current = DOWNLOAD_JOBS.get(job_id)
        if not current:
            return
        current.file_path = None
        current.file_size = None


# ============= 应用配置 =============

app = FastAPI(
    title="Video Downloader API",
    description="服务器中转视频下载服务 - 商业化版本",
    version="7.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS 配置 - 允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============= License Key API =============

@app.get("/api/pricing")
async def get_pricing():
    """获取定价信息"""
    return {
        "success": True,
        "pricing": get_price_info(),
        "features": {
            "free": {
                "max_resolution": "480p",
                "daily_downloads": 5,
                "speed": "300KB/s",
                "ads": True,
                "priority": False
            },
            "pro": {
                "max_resolution": "1080p",
                "daily_downloads": "无限",
                "speed": "不限速",
                "ads": False,
                "priority": True
            }
        }
    }


@app.post("/api/subscription/checkout")
async def create_subscription_checkout(
    sub_data: SubscriptionCreate,
    request: Request
):
    """创建订阅结账会话（无需登录）"""
    try:
        # 创建结账会话（不需要用户ID，使用metadata传递）
        success_url = f"http://127.0.0.1:9001/subscription/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = "http://127.0.0.1:9001/subscription/cancel"
        
        # 生成临时License Key（支付成功后激活）
        temp_license_key, _ = create_license(
            tier='pro' if 'yearly' not in sub_data.price_id.lower() else 'pro_yearly',
            expires_days=365
        )
        
        session = create_checkout_session(
            customer_id=None,  # 不需要客户ID
            price_id=sub_data.price_id,
            user_id=None,  # 不需要用户ID
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "license_key": temp_license_key
            }
        )
        
        # 更新License Key的Stripe会话ID
        from license import init_license_db
        import sqlite3
        DB_PATH = Path(__file__).parent / "licenses.db"
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE licenses SET stripe_session_id = ? 
            WHERE license_key = ?
        """, (session.id, temp_license_key))
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "checkout_url": session.url,
            "session_id": session.id
        }
    except PaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.detail)
        )


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe Webhook处理"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少签名"
        )
    
    try:
        event = construct_webhook_event(payload, sig_header)
        handled = handle_webhook_event(event)
        
        return {
            "success": True,
            "handled": handled,
            "event_type": event.type
        }
    except PaymentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.detail)
        )


# ============= 下载 API =============

@app.get("/api/info")
async def get_video_info(
    request: Request,
    url: str = Query(..., description="视频链接"),
    cookie: str = Query(None, description="Cookie字符串，用于解决登录限制")
):
    """
    解析视频信息
    返回视频标题、可用格式等信息
    """
    start_time = time.time()
    client_id = request.headers.get("X-Client-ID", "")
    license_key = request.headers.get("X-License-Key")
    
    logger.info("[API] 解析视频: %s (客户端: %s)", url, client_id)

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web", "ios", "tv"],
                    "player_skip": ["configs"],
                }
            },
        }

        if cookie:
            cookie_path = Path(cookie)
            if cookie_path.exists():
                ydl_opts["cookiefile"] = str(cookie_path)
            else:
                ydl_opts["http_headers"] = {"Cookie": cookie}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # 验证License Key
        license_info = None
        if license_key:
            is_valid, license_info = verify_license(license_key)
            if not is_valid:
                license_info = None

        formats = []
        for item in info.get("formats", []):
            height = item.get("height")
            if item.get("vcodec") != "none" and height:
                # 检查分辨率是否超过用户限制
                limits_info = get_user_limits_info(license_info)
                if height <= limits_info["max_resolution"]:
                    formats.append(
                        {
                            "format_id": item["format_id"],
                            "height": height,
                            "ext": item.get("ext", "mp4"),
                            "has_audio": item.get("acodec") != "none",
                            "filesize": item.get("filesize") or item.get("filesize_approx"),
                        }
                    )

        formats.sort(key=lambda x: (x["height"], x.get("has_audio", False)), reverse=True)

        platform = "unknown"
        url_lower = url.lower()
        if "youtube" in url_lower:
            platform = "youtube"
        elif "tiktok" in url_lower:
            platform = "tiktok"
        elif "bilibili" in url_lower:
            platform = "bilibili"

        elapsed = time.time() - start_time
        logger.info("[API] 解析完成，耗时: %.2fs, 找到 %s 个格式", elapsed, len(formats))

        # 获取用户限制信息
        limits_info = get_user_limits_info(license_info)

        return {
            "title": info.get("title", "Unknown"),
            "formats": formats,
            "thumbnail": info.get("thumbnail"),
            "platform": platform,
            "duration": info.get("duration"),
            "limits": limits_info
        }

    except yt_dlp.utils.DownloadError as ex:
        error_msg = str(ex)
        if "Requested format is not available" in error_msg or "This video is not available" in error_msg:
            raise HTTPException(
                status_code=400,
                detail="该视频无可用的下载格式，可能是已删除或仅限特定地区观看的视频",
            )
        raise HTTPException(status_code=500, detail=error_msg)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/api/download")
async def start_download_task(
    request: Request,
    request_data: DownloadStartRequest
):
    """
    创建下载任务（异步），立即返回 job_id
    需要用户登录，检查配额和权限
    """
    cleanup_expired_jobs()

    if not request_data.url:
        raise HTTPException(status_code=400, detail="url 不能为空")

    # 获取License Key
    license_key = request.headers.get("X-License-Key")
    license_info = None
    if license_key:
        is_valid, license_info = verify_license(license_key)
        if not is_valid:
            license_info = None

    # 检查下载权限
    try:
        ip_address, limits_info = await check_download_allowed(request, license_info)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=e.detail,
            headers=e.headers
        )
    except QuotaExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=e.detail
        )

    # 检查分辨率权限
    if request_data.quality:
        from rate_limiter import check_resolution_allowed
        allowed, reason, max_res = check_resolution_allowed(license_info, request_data.quality)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=reason
            )

    client_id = request.headers.get("X-Client-ID", "")
    job_id = uuid.uuid4().hex
    job = DownloadJob(
        job_id=job_id,
        url=request_data.url,
        format_id=request_data.format_id,
        quality=request_data.quality,
        cookie=request_data.cookie,
        user_id=license_info['license_key'] if license_info else None,
        client_id=client_id,
    )

    with JOB_LOCK:
        DOWNLOAD_JOBS[job_id] = job
        future = DOWNLOAD_EXECUTOR.submit(run_download_job, job_id)
        DOWNLOAD_JOBS[job_id].future = future

    # 记录下载
    record_download(ip_address)

    logger.info("[API] 创建下载任务: %s (客户端: %s, License: %s)", 
                job_id, client_id, license_info['license_key'] if license_info else "未激活")
    
    return {
        "job_id": job_id,
        "status": "queued",
        "limits": limits_info
    }


@app.get("/api/download/{job_id}")
async def get_download_status(
    job_id: str,
    request: Request
):
    """
    查询下载任务状态和进度
    """
    cleanup_expired_jobs()
    job = get_job_or_404(job_id)
    
    client_id = request.headers.get("X-Client-ID", "")
    
    if job.client_id and job.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此任务"
        )
    
    return serialize_job(job)


@app.get("/api/download/{job_id}/file")
async def download_task_file(
    job_id: str,
    request: Request
):
    """
    下载任务生成的文件（只允许下载一次）
    """
    job = get_job_or_404(job_id)
    
    client_id = request.headers.get("X-Client-ID", "")
    
    if job.client_id and job.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此文件"
        )
    
    if job.status != "ready":
        raise HTTPException(status_code=409, detail="任务未完成，无法下载文件")
    if not job.file_path:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    filename = job.filename or file_path.name

    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": build_content_disposition(filename),
            "Cache-Control": "no-cache",
        },
        background=BackgroundTask(mark_job_downloaded, job_id),
    )


# ============= 历史记录 API =============

@app.get("/api/history")
async def get_history(
    request: Request,
    limit: int = Query(100, ge=1, le=500)
):
    """获取当前客户端的下载历史记录"""
    try:
        client_id = request.headers.get("X-Client-ID", "")
        
        if client_id:
            records = history_db.get_records_by_client(client_id, limit=limit)
        else:
            records = history_db.get_records(limit=limit)
        
        return {
            "success": True,
            "records": records,
            "total": len(records)
        }
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


@app.get("/api/history/stats")
async def get_history_stats(request: Request):
    """获取当前客户端的历史记录统计信息"""
    try:
        client_id = request.headers.get("X-Client-ID", "")
        
        if client_id:
            stats = history_db.get_client_stats(client_id)
        else:
            stats = history_db.get_stats()
        
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"获取历史记录统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


# ============= 系统 API =============

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    with JOB_LOCK:
        total_jobs = len(DOWNLOAD_JOBS)
        active_jobs = len(
            [job for job in DOWNLOAD_JOBS.values() if job.status in {"queued", "downloading", "processing", "canceling"}]
        )
    return {
        "status": "ok",
        "service": "video-downloader-api",
        "version": "7.0.0",
        "mode": "commercial",
        "timestamp": time.time(),
        "max_workers": MAX_DOWNLOAD_WORKERS,
        "active_jobs": active_jobs,
        "total_jobs": total_jobs,
    }


@app.get("/api/limits")
async def get_limits(request: Request):
    """获取当前用户的限制信息"""
    license_key = request.headers.get("X-License-Key")
    
    if license_key:
        is_valid, license_info = verify_license(license_key)
        if is_valid:
            limits_info = get_user_limits_info(license_info)
        else:
            limits_info = get_user_limits_info(None)
    else:
        limits_info = get_user_limits_info(None)
    
    return {
        "success": True,
        "limits": limits_info
    }


# ============= License Key API =============

@app.post("/api/license/activate")
async def activate_license_endpoint(request: Request):
    """激活License Key"""
    try:
        data = await request.json()
        license_key = data.get("license_key")
        
        if not license_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少License Key"
            )
        
        success, message = activate_license(license_key)
        
        if success:
            return {
                "success": True,
                "message": message
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/api/license/info")
async def get_license_info_endpoint(request: Request):
    """获取License Key信息"""
    license_key = request.headers.get("X-License-Key")
    
    if not license_key:
        return {
            "success": True,
            "is_pro": False,
            "license": None
        }
    
    is_valid, license_info = verify_license(license_key)
    
    if is_valid:
        return {
            "success": True,
            "is_pro": True,
            "license": license_info
        }
    else:
        return {
            "success": True,
            "is_pro": False,
            "license": None
        }


@app.get("/api/license/by-session/{session_id}")
async def get_license_by_session_endpoint(session_id: str):
    """通过Stripe会话ID获取License Key"""
    license_key = get_license_by_stripe_session(session_id)
    
    if license_key:
        return {
            "success": True,
            "license_key": license_key
        }
    else:
        return {
            "success": False,
            "message": "未找到对应的License Key"
        }


@app.post("/api/license/verify")
async def verify_license_endpoint(request: Request):
    """验证License Key"""
    try:
        data = await request.json()
        license_key = data.get("license_key")
        
        if not license_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少License Key"
            )
        
        is_valid, license_info = verify_license(license_key)
        
        if is_valid:
            return {
                "success": True,
                "is_valid": True,
                "license": license_info
            }
        else:
            return {
                "success": True,
                "is_valid": False,
                "license": None
            }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============= 静态文件服务 =============

def resolve_static_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "static"
    return Path(__file__).resolve().parent / "static"


STATIC_DIR = resolve_static_dir()


@app.get("/")
async def root():
    """返回主页"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Video Downloader API", "docs": "/api/docs"}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============= 启动入口 =============

def open_browser():
    webbrowser.open("http://127.0.0.1:9001")


if __name__ == "__main__":
    # 初始化数据库
    init_database()
    start_cleanup_scheduler()
    threading.Timer(1.5, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=9001)
    print("Server started: http://127.0.0.1:9001")
