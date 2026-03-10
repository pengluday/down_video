# Universal Video Downloader

一个基于 Web 的在线视频下载工具，支持从多个主流平台下载高清视频内容。

## 功能特性

- **多平台支持**: YouTube、Bilibili、TikTok、小红书、抖音
- **高清下载**: 支持最高 4K 分辨率
- **无需安装**: 纯网页端，无需软件或浏览器插件
- **简单易用**: 粘贴链接即可下载

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

**服务器中转模式**：服务器下载视频后转发给客户端

```
浏览器
  ↓ 请求下载
FastAPI 后端 (localhost:8000)
  ↓ yt-dlp 下载
YouTube/TikTok CDN
  ↓ 视频文件
FastAPI 后端
  ↓ 流式传输
浏览器
```

**特点**：
- 服务器负责下载视频、合并音视频、转码
- 支持所有分辨率（包括 4K）
- 自动合并分离的视频和音频
- 音频自动转换为 AAC 格式，确保兼容性
- 视频流量经过服务器

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

### 分析视频
```
GET /api/info?url=视频链接
```

返回示例：
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

### 下载视频
```
GET /api/download?url=视频链接&format_id=136
```

参数：
- `url`: 视频链接
- `format_id`: 格式 ID（从分析接口获取）
- `quality`: 分辨率（可选，如 720）

返回：MP4 文件流

### 健康检查
```
GET /api/health
```

返回示例：
```json
{
  "status": "healthy",
  "mode": "server_relay"
}
```

## 工作原理

1. **分析阶段**: 用户粘贴视频链接，服务器解析视频信息（标题、时长、可用画质等）
2. **下载阶段**: 用户选择画质后，服务器使用 yt-dlp 下载视频
3. **合并阶段**: 如果视频和音频分离，服务器自动合并并转换为 AAC 音频
4. **传输阶段**: 服务器将处理好的视频流式传输给浏览器

**优势**:
- 支持所有分辨率，包括 4K
- 自动处理视频和音频分离的情况
- 音频自动转换为 AAC，确保所有播放器兼容
- 用户无需安装任何软件或插件

**注意事项**:
- 视频流量经过服务器，需要足够的带宽
- 下载时间取决于视频大小和服务器网速
- 服务器需要临时存储空间处理视频

## 注意事项

1. 本工具仅供个人学习研究使用
2. 请遵守相关平台的使用条款和版权法规
3. 仅下载您有权限使用的内容
4. 部分平台可能需要配置 Cookie 才能下载高清内容
5. 服务器需要足够的带宽和存储空间

## 配置 Cookie（可选）

如需下载 Bilibili 大会员内容，可在 `main.py` 中配置 Cookie：

```python
ydl_opts = {
    'cookiesfrombrowser': ('chrome',),  # 使用 Chrome 浏览器的 Cookie
}
```

## License

MIT License