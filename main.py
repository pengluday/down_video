"""
视频下载工具 - 服务器中转模式
服务器负责下载视频并转发给用户

架构：浏览器 → 服务器 → YouTube/TikTok → 服务器 → 浏览器
"""

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import yt_dlp
import logging
import time
import sys
import os
import tempfile
import asyncio
from pathlib import Path
import threading
import uvicorn
import webbrowser

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 临时文件目录
TEMP_DIR = Path(tempfile.gettempdir()) / "video_downloader"
TEMP_DIR.mkdir(exist_ok=True)

# ============= 应用配置 =============

app = FastAPI(
    title="Video Downloader API",
    description="服务器中转视频下载服务",
    version="5.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
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
async def get_video_info(url: str = Query(..., description="视频链接")):
    """
    解析视频信息
    
    返回视频标题、可用格式等信息
    """
    start_time = time.time()
    logger.info(f"[API] 解析视频: {url}")
    
    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        # 提取视频格式
        formats = []
        
        for f in info.get("formats", []):
            height = f.get("height")
            if f.get("vcodec") != "none" and height:
                formats.append({
                    "format_id": f["format_id"],
                    "height": height,
                    "ext": f.get("ext", "mp4"),
                    "has_audio": f.get("acodec") != "none",
                    "filesize": f.get("filesize") or f.get("filesize_approx")
                })
        
        # 按分辨率排序，优先显示有音频的格式
        formats.sort(key=lambda x: (x["height"], x.get("has_audio", False)), reverse=True)
        
        # 提取平台信息
        platform = "unknown"
        if "youtube" in url.lower():
            platform = "youtube"
        elif "tiktok" in url.lower():
            platform = "tiktok"
        elif "bilibili" in url.lower():
            platform = "bilibili"
        
        response = {
            "title": info.get("title", "Unknown"),
            "formats": formats,
            "thumbnail": info.get("thumbnail"),
            "platform": platform,
            "duration": info.get("duration")
        }
        
        elapsed = time.time() - start_time
        logger.info(f"[API] 解析完成，耗时: {elapsed:.2f}s, 找到 {len(formats)} 个格式")
        
        return response
    
    except Exception as e:
        logger.error(f"[API] 解析错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download")
async def download_video(
    url: str = Query(..., description="视频链接"),
    format_id: str = Query(None, description="格式ID，如 136 (720p)"),
    quality: int = Query(None, description="分辨率，如 720")
):
    """
    服务器中转下载
    
    服务器使用 yt-dlp 下载视频，然后转发给浏览器
    """
    start_time = time.time()
    logger.info(f"[Download] 开始下载: {url}, format_id={format_id}, quality={quality}")
    
    try:
        # 构建格式选择字符串
        if format_id:
            format_str = format_id
            if "+" not in format_id:
                # 如果是单独的视频格式，尝试合并音频
                format_str = f"{format_id}+bestaudio/best"
        elif quality:
            format_str = f"best[height<={quality}]+bestaudio/best[height<={quality}]/best"
        else:
            format_str = "best+bestaudio/best"
        
        logger.info(f"[Download] 使用格式: {format_str}")
        
        # 生成临时文件名
        temp_filename = f"video_{int(time.time())}"
        temp_filepath = TEMP_DIR / temp_filename
        
        # yt-dlp 下载选项
        ydl_opts = {
            "format": format_str,
            "outtmpl": str(temp_filepath) + ".%(ext)s",
            "merge_output_format": "mp4",
            "quiet": False,
            "no_warnings": False,
            "noplaylist": True,
            "postprocessor_args": {
                "ffmpeg": ["-c:a", "aac", "-b:a", "192k"]
            },
        }
        
        # 下载视频
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # 获取实际下载的文件路径
            # yt-dlp 可能会返回 requested_downloads 或直接在 info 中
            if "requested_downloads" in info:
                downloaded_file = Path(info["requested_downloads"][0]["filepath"])
            else:
                # 尝试查找文件
                downloaded_file = None
                for ext in [".mp4", ".webm", ".mkv", ".flv"]:
                    potential_file = Path(str(temp_filepath) + ext)
                    if potential_file.exists():
                        downloaded_file = potential_file
                        break
                
                if not downloaded_file:
                    # 最后尝试使用原始路径
                    downloaded_file = Path(str(temp_filepath) + ".mp4")
            
            if not downloaded_file.exists():
                raise HTTPException(status_code=500, detail=f"下载失败：找不到文件 {downloaded_file}")
            
            # 获取文件大小
            file_size = downloaded_file.stat().st_size
            elapsed = time.time() - start_time
            logger.info(f"[Download] 下载完成: {downloaded_file.name}, 大小: {file_size / 1024 / 1024:.2f}MB, 耗时: {elapsed:.2f}s")
            
            # 生成安全的文件名（只使用 ASCII 字符）
            title = info.get("title", "video")
            # 移除非 ASCII 字符，只保留字母、数字、空格、连字符和下划线
            safe_title = "".join(c if c.isascii() and (c.isalnum() or c in (' ', '-', '_')) else '_' for c in title).strip()
            if not safe_title or safe_title == '_':
                safe_title = "video"
            filename = f"{safe_title}.mp4"
            
            # 对文件名进行 URL 编码，支持中文
            from urllib.parse import quote
            encoded_filename = quote(filename)
            
            # 流式返回文件
            def iterfile():
                with open(downloaded_file, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk
                # 传输完成后删除临时文件
                try:
                    downloaded_file.unlink()
                    logger.info(f"[Download] 已删除临时文件: {downloaded_file.name}")
                except Exception as e:
                    logger.warning(f"[Download] 删除临时文件失败: {e}")
            
            return StreamingResponse(
                iterfile(),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                    "Content-Length": str(file_size),
                    "Cache-Control": "no-cache"
                }
            )
    
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"[Download] yt-dlp 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")
    except Exception as e:
        logger.error(f"[Download] 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "video-downloader-api",
        "version": "5.0.0",
        "mode": "server-relay",
        "timestamp": time.time()
    }


# ============= 静态文件服务 =============

STATIC_DIR = Path(__file__).parent / "static"

@app.get("/")
async def root():
    """返回主页"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Video Downloader API", "docs": "/api/docs"}

def get_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

static_path = get_path("static")
app.mount("/static", StaticFiles(directory=static_path), name="static")


# ============= 启动入口 =============

def open_browser():
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    threading.Timer(1.5, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8001)
    print("Server started: http://127.0.0.1:8000")
