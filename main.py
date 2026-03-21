"""
视频下载工具 - 任务队列模式
服务器负责下载视频并转发给用户

架构：浏览器 -> FastAPI 任务接口 -> 后台下载线程 -> 浏览器拉取文件
"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
import asyncio
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
import webbrowser

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask
import uvicorn
import yt_dlp


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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


def build_format_string(format_id: str | None, quality: int | None) -> str:
    if format_id:
        if "+" in format_id:
            return format_id
        return f"{format_id}+bestaudio/best"
    if quality:
        return f"best[height<={quality}]+bestaudio/best[height<={quality}]/best"
    return "best+bestaudio/best"


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

    format_str = build_format_string(job.format_id, job.quality)

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
    description="服务器中转视频下载服务",
    version="6.0.0",
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


# ============= API 路由 =============

@app.get("/api/info")
async def get_video_info(
    url: str = Query(..., description="视频链接"),
    cookie: str = Query(None, description="Cookie字符串，用于解决登录限制"),
):
    """
    解析视频信息

    返回视频标题、可用格式等信息
    """
    start_time = time.time()
    logger.info("[API] 解析视频: %s", url)

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

        formats = []
        for item in info.get("formats", []):
            height = item.get("height")
            if item.get("vcodec") != "none" and height:
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

        return {
            "title": info.get("title", "Unknown"),
            "formats": formats,
            "thumbnail": info.get("thumbnail"),
            "platform": platform,
            "duration": info.get("duration"),
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
async def start_download_task(request: DownloadStartRequest):
    """
    创建下载任务（异步），立即返回 job_id
    """
    cleanup_expired_jobs()

    if not request.url:
        raise HTTPException(status_code=400, detail="url 不能为空")

    job_id = uuid.uuid4().hex
    job = DownloadJob(
        job_id=job_id,
        url=request.url,
        format_id=request.format_id,
        quality=request.quality,
        cookie=request.cookie,
    )

    with JOB_LOCK:
        DOWNLOAD_JOBS[job_id] = job
        future = DOWNLOAD_EXECUTOR.submit(run_download_job, job_id)
        DOWNLOAD_JOBS[job_id].future = future

    return {
        "job_id": job_id,
        "status": "queued",
    }


@app.get("/api/download")
async def legacy_download_video(
    url: str = Query(..., description="视频链接"),
    format_id: str = Query(None, description="格式ID，如 136 (720p)"),
    quality: int = Query(None, description="分辨率，如 720"),
    cookie: str = Query(None, description="Cookie字符串，用于解决登录限制"),
):
    """
    兼容旧版前端：GET /api/download?url=...&format_id=...
    内部走新任务系统，等待任务完成后直接返回文件流。
    """
    cleanup_expired_jobs()

    job_id = uuid.uuid4().hex
    job = DownloadJob(
        job_id=job_id,
        url=url,
        format_id=format_id,
        quality=quality,
        cookie=cookie,
    )

    with JOB_LOCK:
        DOWNLOAD_JOBS[job_id] = job
        future = DOWNLOAD_EXECUTOR.submit(run_download_job, job_id)
        DOWNLOAD_JOBS[job_id].future = future

    max_wait_seconds = 2 * 60 * 60
    start_wait = time.time()

    while True:
        current = get_job_or_404(job_id)

        if current.status == "ready":
            if not current.file_path:
                raise HTTPException(status_code=500, detail="下载失败：任务完成但文件不存在")

            file_path = Path(current.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=500, detail="下载失败：输出文件不存在")

            filename = current.filename or file_path.name

            return FileResponse(
                path=file_path,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": build_content_disposition(filename),
                    "Cache-Control": "no-cache",
                },
                background=BackgroundTask(mark_job_downloaded, job_id),
            )

        if current.status in {"failed", "canceled", "completed"}:
            raise HTTPException(status_code=500, detail=current.error or f"下载失败: {current.status}")

        if time.time() - start_wait > max_wait_seconds:
            raise HTTPException(status_code=504, detail="下载超时，请稍后重试")

        await asyncio.sleep(0.5)


@app.get("/api/download/{job_id}")
async def get_download_status(job_id: str):
    """
    查询下载任务状态和进度
    """
    cleanup_expired_jobs()
    job = get_job_or_404(job_id)
    return serialize_job(job)


@app.post("/api/download/{job_id}/cancel")
async def cancel_download_task(job_id: str):
    """
    取消下载任务
    """
    job = get_job_or_404(job_id)

    should_cleanup = False

    with JOB_LOCK:
        current = DOWNLOAD_JOBS.get(job_id)
        if not current:
            raise HTTPException(status_code=404, detail="任务不存在")

        if current.status in {"ready", "completed", "failed", "canceled"}:
            return {"job_id": job_id, "status": current.status}

        current.cancel_event.set()
        if current.status == "queued":
            if current.future and current.future.cancel():
                current.status = "canceled"
                current.stage = "canceled"
                current.error = "下载已取消"
                current.updated_at = time.time()
                should_cleanup = True

        if not should_cleanup:
            current.status = "canceling"
            current.stage = "canceling"
            current.updated_at = time.time()

    if should_cleanup:
        cleanup_job_files(job)
        return {"job_id": job_id, "status": "canceled"}
    return {"job_id": job_id, "status": "canceling"}


@app.get("/api/download/{job_id}/file")
async def download_task_file(job_id: str):
    """
    下载任务生成的文件（只允许下载一次）
    """
    job = get_job_or_404(job_id)
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
        "version": "6.0.0",
        "mode": "task-queue",
        "timestamp": time.time(),
        "max_workers": MAX_DOWNLOAD_WORKERS,
        "active_jobs": active_jobs,
        "total_jobs": total_jobs,
    }


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
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    threading.Timer(1.5, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
    print("Server started: http://127.0.0.1:8000")
