# 视频下载工具架构设计

## 系统架构图

```
用户浏览器
     │
     │ 访问网站
     ▼
Cloudflare CDN (静态资源加速)
     │
     │ 静态页面 (HTML/CSS/JS)
     ▼
前端 (Next.js / HTML)
     │
     │ API 请求 (/api/analyze, /api/download)
     ▼
解析服务器 (VPS - 低成本)
     │
     │ yt-dlp 解析
     ▼
YouTube / TikTok / Bilibili
     │
     ▼
返回真实视频 CDN 地址
     │
     ▼
用户浏览器 ←──── 直接下载视频 (0 带宽成本)
```

## 核心设计思想

### 1. 零带宽成本
- **服务器只负责解析**：仅处理 API 请求，返回 JSON 数据
- **视频流量不经过服务器**：用户直接从 YouTube/TikTok CDN 下载
- **成本极低**：$5/月的 VPS 即可支持大量用户

### 2. 流量分析
| 环节 | 流量类型 | 成本 |
|------|---------|------|
| Cloudflare CDN | 静态页面 (HTML/CSS/JS) | 免费 |
| 解析服务器 | API 请求 (JSON) | < 1GB/月 |
| 视频下载 | 用户 → YouTube CDN | 服务器不承担 |

### 3. 技术栈
- **前端**: HTML5 + Vanilla JS (可迁移到 Next.js)
- **后端**: Python + FastAPI
- **解析**: yt-dlp
- **部署**: Cloudflare CDN + VPS

## API 设计

### POST /api/analyze
分析视频信息，返回可用画质列表

**Request:**
```json
{
  "url": "https://www.youtube.com/watch?v=xxxxx"
}
```

**Response:**
```json
{
  "success": true,
  "title": "视频标题",
  "platform": "youtube",
  "thumbnail": "https://...",
  "duration": 360,
  "formats": [
    {"quality": "2160p", "height": 2160, "has_audio": false},
    {"quality": "1080p", "height": 1080, "has_audio": true}
  ]
}
```

### POST /api/download
获取指定画质的下载链接

**Request:**
```json
{
  "url": "https://www.youtube.com/watch?v=xxxxx",
  "quality": "2160"
}
```

**Response:**
```json
{
  "success": true,
  "download_type": "direct",
  "download_url": "https://googlevideo.com/...",
  "quality": "2160p",
  "filename": "video.mp4"
}
```

或分离下载：
```json
{
  "success": true,
  "download_type": "separate",
  "video_url": "https://googlevideo.com/video...",
  "audio_url": "https://googlevideo.com/audio...",
  "quality": "2160p",
  "message": "需要 FFmpeg 合并"
}
```

### GET /api/redirect?url=xxx
302 重定向到真实下载地址（解决 CORS 问题）

## 部署架构

### 1. Cloudflare CDN 配置
- **静态资源**: 缓存 HTML/CSS/JS
- **API 请求**: 透传到解析服务器
- **SSL**: 自动 HTTPS

### 2. 解析服务器 (VPS)
- **配置**: 1核 1GB 内存即可
- **带宽**: 仅需处理 API 请求
- **位置**: 选择靠近用户的地区

### 3. 域名配置
```
video-downloader.com     → Cloudflare CDN
├── / (静态页面)         → 缓存
├── /api/* (API)         → 透传到 VPS
└── /static/* (资源)     → 缓存
```

## 优势

1. **成本极低**: 服务器只处理 API，视频流量走 CDN
2. **速度极快**: 用户直接从 YouTube CDN 下载
3. **扩展性强**: 可随时增加解析服务器
4. **维护简单**: 无需管理视频存储
5. **安全可靠**: 不存储用户数据

## 注意事项

1. **CORS 问题**: 使用 302 重定向解决
2. **链接时效**: YouTube 链接有时效性，需及时下载
3. **FFmpeg 合并**: 4K 视频需要用户自行合并音视频
4. **法律合规**: 仅供个人学习使用
