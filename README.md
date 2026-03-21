# Universal Video Downloader

一个基于 Web 的在线视频下载工具，支持从多个主流平台下载高清视频内容。

## 功能特性

- **多平台支持**: YouTube、Bilibili、TikTok、小红书、抖音
- **高清下载**: 支持最高 4K 分辨率
- **无需安装**: 纯网页端，无需软件或浏览器插件
- **简单易用**: 粘贴链接即可下载
- **任务队列**: 支持异步下载，实时进度查询
- **任务管理**: 支持取消正在进行的下载任务

## 平台特定功能

| 平台 | 支持功能 |
|------|----------|
| YouTube | 4K 视频下载 |
| Bilibili | 4K + 大会员内容 |
| TikTok | 无水印视频 |
| 小红书 | LivePhoto 下载 |
| 抖音 | 视频 + 图文笔记 |

## 技术栈

- **后端**: Python + FastAPI + yt-dlp
- **前端**: HTML5 + CSS3 + JavaScript
- **部署**: Uvicorn

## 架构模式

**任务队列模式**：浏览器提交下载任务，后台异步处理，前端轮询进度

```
浏览器
  ↓ POST /api/download (创建任务)
FastAPI 后端 (localhost:8000)
  ↓ 返回 job_id
浏览器
  ↓ GET /api/download/{job_id} (轮询进度)
后台下载线程 (ThreadPoolExecutor)
  ↓ yt-dlp 下载 + 进度回调
YouTube/TikTok CDN
  ↓ 视频文件
浏览器
  ↓ GET /api/download/{job_id}/file (下载文件)
FastAPI 后端
  ↓ 流式传输
浏览器
```

**特点**：
- 异步任务处理，不阻塞主线程
- 实时进度查询（下载速度、剩余时间、百分比）
- 支持取消正在进行的下载任务
- 自动合并分离的视频和音频
- 音频自动转换为 AAC 格式，确保兼容性
- 任务完成后自动清理临时文件

## 安装运行

### 1. 安装依赖

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 运行服务

```bash
python main.py
```

或

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 访问应用

打开浏览器访问: http://localhost:8000

## API 接口

### 1. 分析视频

```
GET /api/info?url=视频链接&cookie=可选Cookie
```

**参数**：
- `url`: 视频链接（必填）
- `cookie`: Cookie字符串或Cookie文件路径（可选，用于解决登录限制）

**返回示例**：
```json
{
  "title": "视频标题",
  "formats": [
    {
      "format_id": "136",
      "height": 720,
      "ext": "mp4",
      "has_audio": false,
      "filesize": 72351744
    }
  ],
  "thumbnail": "https://...",
  "platform": "youtube",
  "duration": 520
}
```

### 2. 创建下载任务（推荐）

```
POST /api/download
Content-Type: application/json

{
  "url": "视频链接",
  "format_id": "136",
  "quality": 720,
  "cookie": "可选Cookie"
}
```

**参数**：
- `url`: 视频链接（必填）
- `format_id`: 格式 ID（可选，从分析接口获取）
- `quality`: 分辨率（可选，如 720）
- `cookie`: Cookie字符串或Cookie文件路径（可选）

**返回示例**：
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "queued"
}
```

### 3. 查询任务状态

```
GET /api/download/{job_id}
```

**返回示例**：
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "downloading",
  "stage": "downloading",
  "progress": 45.5,
  "speed": "2.5MiB/s",
  "eta": 120,
  "filename": "视频标题.mp4",
  "file_size": 52428800
}
```

**状态说明**：
- `queued`: 排队中
- `downloading`: 下载中
- `merging`: 合并音视频
- `ready`: 下载完成，可获取文件
- `completed`: 文件已下载
- `failed`: 下载失败
- `canceled`: 已取消

### 4. 下载文件

```
GET /api/download/{job_id}/file
```

**说明**：任务状态为 `ready` 时可下载文件，下载后自动标记为 `completed`

**返回**：MP4 文件流

### 5. 取消任务

```
POST /api/download/{job_id}/cancel
```

**返回示例**：
```json
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "canceled"
}
```

### 6. 兼容旧版接口

```
GET /api/download?url=视频链接&format_id=136&cookie=可选Cookie
```

**说明**：兼容旧版前端，内部使用任务系统，等待任务完成后直接返回文件流

### 7. 健康检查

```
GET /api/health
```

**返回示例**：
```json
{
  "status": "ok",
  "service": "video-downloader-api",
  "version": "6.0.0",
  "mode": "task-queue",
  "timestamp": 1234567890.123
}
```

## 工作原理

### 新版流程（任务队列模式）

1. **分析阶段**: 用户粘贴视频链接，服务器解析视频信息（标题、时长、可用画质等）
2. **创建任务**: 用户选择画质后，服务器创建异步下载任务，立即返回任务ID
3. **后台下载**: 后台线程使用 yt-dlp 下载视频，实时更新进度
4. **进度查询**: 前端轮询任务状态，显示下载进度、速度、剩余时间
5. **文件下载**: 任务完成后，前端请求文件下载
6. **自动清理**: 文件下载后自动标记为已完成，定时清理过期任务

### 优势

- **非阻塞**: 下载任务在后台执行，不阻塞主线程
- **实时进度**: 前端可实时查询下载进度、速度、剩余时间
- **任务管理**: 支持取消正在进行的下载任务
- **资源优化**: 自动清理过期任务和临时文件
- **并发控制**: 限制同时下载的任务数量（默认2个）
- **错误处理**: 完善的错误处理和状态管理

## Cookie 配置

### 方式一：通过 API 参数传递

在分析或下载时传递 Cookie 参数：

```javascript
// 分析视频
fetch(`/api/info?url=${url}&cookie=${encodeURIComponent(cookie)}`)

// 创建下载任务
fetch('/api/download', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    url: url,
    format_id: formatId,
    cookie: cookie
  })
})
```

### 方式二：使用 Cookie 文件

1. 从浏览器导出 Cookie 到文件（如 `cookies.txt`）
2. 在 API 中传递文件路径：

```bash
curl "http://localhost:8000/api/info?url=视频链接&cookie=/path/to/cookies.txt"
```

### Cookie 使用场景

- **Bilibili 大会员内容**: 需要登录后的 Cookie
- **YouTube 年龄限制视频**: 需要登录验证
- **地区限制内容**: 通过 Cookie 绕过地区限制
- **私密视频**: 需要访问权限的 Cookie

## 前端集成示例

### 创建下载任务并轮询进度

```javascript
// 创建任务
const response = await fetch('/api/download', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    url: videoUrl,
    format_id: formatId
  })
});
const {job_id} = await response.json();

// 轮询进度
const pollProgress = async () => {
  const status = await fetch(`/api/download/${job_id}`);
  const data = await status.json();
  
  if (data.status === 'downloading') {
    console.log(`进度: ${data.progress}%`);
    console.log(`速度: ${data.speed}`);
    console.log(`剩余时间: ${data.eta}秒`);
    setTimeout(pollProgress, 1000);
  } else if (data.status === 'ready') {
    // 下载文件
    window.location.href = `/api/download/${job_id}/file`;
  }
};

pollProgress();
```

## 注意事项

1. **使用限制**: 本工具仅供个人学习研究使用
2. **版权遵守**: 请遵守相关平台的使用条款和版权法规
3. **权限检查**: 仅下载您有权限使用的内容
4. **Cookie 安全**: Cookie 包含敏感信息，请勿泄露给他人
5. **资源占用**: 服务器需要足够的带宽和存储空间
6. **并发限制**: 同时最多支持 2 个下载任务
7. **任务保留**: 已完成的任务保留 1 小时后自动清理

## macOS 无法打开问题

在 macOS 上，可能会遇到"无法打开"的问题。这是因为 macOS 对下载的文件进行了安全检查，防止未知来源的应用程序运行。

**解决方法**：

```bash
xattr -dr com.apple.quarantine video-downloader-macos-latest/video-downloader
```

## 故障排除

### 1. 视频下载失败

**可能原因**：
- 视频已删除或设为私密
- 地区限制
- 需要登录验证

**解决方法**：
- 检查视频链接是否有效
- 尝试添加 Cookie 参数
- 检查服务器日志获取详细错误信息

### 2. 下载速度慢

**可能原因**：
- 网络带宽限制
- 视频文件过大
- 服务器性能不足

**解决方法**：
- 选择较低的分辨率
- 检查网络连接
- 升级服务器配置

### 3. 任务卡在队列中

**可能原因**：
- 已达到并发下载上限（默认2个）
- 下载线程异常

**解决方法**：
- 等待其他任务完成
- 取消不需要的任务
- 重启服务器

## 更新日志

### v6.0.0 (2026-03-20)
- 🎉 重构为任务队列模式
- ✨ 新增异步下载任务管理
- ✨ 新增实时进度查询
- ✨ 新增任务取消功能
- ✨ 新增 Cookie 支持
- 🐛 修复 YouTube 视频解析问题
- 📝 更新 API 文档

### v5.0.0
- 🎉 初始版本
- ✨ 支持多平台视频下载
- ✨ 支持 4K 高清下载

## License

MIT License
