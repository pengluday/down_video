# 部署指南 - Cloudflare CDN + VPS 架构

## 架构概览

```
用户浏览器 → Cloudflare CDN → 前端页面 → API 请求 → VPS 解析服务器 → YouTube/TikTok
                                          ↓
                                    返回 CDN 地址 → 用户直接下载
```

## 1. 准备 VPS 服务器

### 1.1 服务器要求
- **配置**: 1核 CPU, 1GB 内存, 20GB 存储
- **系统**: Ubuntu 22.04 LTS
- **带宽**: 1TB/月（仅用于 API 请求，足够）
- **推荐服务商**: 
  - Vultr ($5/月)
  - DigitalOcean ($6/月)
  - AWS Lightsail ($5/月)

### 1.2 安装依赖

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 和 pip
sudo apt install -y python3 python3-pip python3-venv

# 安装 FFmpeg（可选，用于服务器端合并）
sudo apt install -y ffmpeg

# 克隆项目
git clone https://github.com/yourusername/video-downloader.git
cd video-downloader

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 1.3 配置 Systemd 服务

创建服务文件 `/etc/systemd/system/video-downloader.service`:

```ini
[Unit]
Description=Video Downloader API
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/video-downloader
Environment="PATH=/var/www/video-downloader/venv/bin"
ExecStart=/var/www/video-downloader/venv/bin/uvicorn main:app --host 0.0.0.0 --port 9001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable video-downloader
sudo systemctl start video-downloader

# 查看状态
sudo systemctl status video-downloader
sudo journalctl -u video-downloader -f
```

### 1.4 配置 Nginx 反向代理

安装 Nginx：

```bash
sudo apt install -y nginx
```

创建配置文件 `/etc/nginx/sites-available/video-downloader`:

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:9001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # 增加超时时间，因为 yt-dlp 解析可能需要时间
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/video-downloader /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 2. 配置 Cloudflare CDN

### 2.1 添加域名到 Cloudflare

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com)
2. 点击 "Add Site"
3. 输入你的域名 `yourdomain.com`
4. 选择免费计划
5. 按照提示修改域名 DNS 服务器

### 2.2 DNS 配置

在 Cloudflare DNS 设置中添加记录：

| Type | Name | Content | Proxy Status | TTL |
|------|------|---------|--------------|-----|
| A | @ | YOUR_VPS_IP | Proxied | Auto |
| A | api | YOUR_VPS_IP | Proxied | Auto |
| A | www | YOUR_VPS_IP | Proxied | Auto |

### 2.3 SSL/TLS 配置

1. 进入 SSL/TLS 菜单
2. 设置加密模式为 **Full (strict)**
3. 在 "Edge Certificates" 中确保证书已激活

### 2.4 缓存配置

#### 页面规则 (Page Rules)

创建以下页面规则：

**规则 1: 缓存静态资源**
```
URL: *yourdomain.com/static/*
设置: Cache Level - Cache Everything
      Edge Cache TTL - 1 month
```

**规则 2: 不缓存 API**
```
URL: *yourdomain.com/api/*
设置: Cache Level - Bypass
```

#### 缓存规则 (Cache Rules) - 新版

```
规则 1:
  When matching: (http.request.uri.path contains "/static/")
  Then: Cache eligibility - Eligible for cache
         Edge TTL - 30 days

规则 2:
  When matching: (http.request.uri.path contains "/api/")
  Then: Cache eligibility - Bypass cache
```

### 2.5 安全设置

#### 安全级别
- Security Level: Medium
- Challenge Passage: 30 minutes

#### 防火墙规则 (可选)

```
规则 1: 限制 API 请求频率
  If: (http.request.uri.path contains "/api/") and (cf.threat_score > 10)
  Then: Block

规则 2: 只允许特定国家
  If: (http.request.uri.path contains "/api/") and (ip.geoip.country ne "CN")
  Then: Challenge
```

## 3. 配置 HTTPS (SSL 证书)

### 3.1 使用 Certbot

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com -d api.yourdomain.com

# 自动续期测试
sudo certbot renew --dry-run
```

### 3.2 更新 Nginx 配置

Certbot 会自动更新配置，确保包含：

```nginx
server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # ... 其他配置
}

server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

## 4. 前端部署

### 4.1 方案 A: 静态文件托管

将 `static/` 目录内容上传到 Cloudflare Pages：

```bash
# 安装 Wrangler
npm install -g wrangler

# 登录 Cloudflare
wrangler login

# 创建 Pages 项目
cd static
wrangler pages project create video-downloader

# 部署
wrangler pages deploy . --project-name=video-downloader
```

### 4.2 方案 B: 使用 VPS 托管

如果继续使用 VPS 托管静态文件，确保 Nginx 配置正确：

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location / {
        root /var/www/video-downloader/static;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:9001;
        # ... 其他代理配置
    }
}
```

## 5. 更新前端 API 地址

如果使用 Cloudflare Pages 托管前端，需要修改 `static/app.js` 中的 API 地址：

```javascript
// 修改 API 基础 URL
const API_BASE_URL = 'https://api.yourdomain.com';

// 在 fetch 调用中使用
const response = await fetch(`${API_BASE_URL}/api/analyze`, {
    // ...
});
```

## 6. 监控和日志

### 6.1 查看应用日志

```bash
# 实时查看日志
sudo journalctl -u video-downloader -f

# 查看最近 100 行
sudo journalctl -u video-downloader -n 100
```

### 6.2 Nginx 日志

```bash
# 访问日志
sudo tail -f /var/log/nginx/access.log

# 错误日志
sudo tail -f /var/log/nginx/error.log
```

### 6.3 Cloudflare 分析

在 Cloudflare Dashboard 中查看：
- 流量分析
- 安全事件
- 性能指标
- DNS 查询

## 7. 备份和恢复

### 7.1 备份脚本

创建 `/var/www/backup.sh`:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/var/backups/video-downloader"

mkdir -p $BACKUP_DIR

# 备份应用代码
tar -czf $BACKUP_DIR/app_$DATE.tar.gz /var/www/video-downloader

# 备份 Nginx 配置
tar -czf $BACKUP_DIR/nginx_$DATE.tar.gz /etc/nginx/sites-available/

# 保留最近 7 天的备份
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

### 7.2 定时任务

```bash
# 编辑 crontab
sudo crontab -e

# 每天凌晨 3 点备份
0 3 * * * /var/www/backup.sh >> /var/log/backup.log 2>&1
```

## 8. 性能优化

### 8.1 启用 Gzip 压缩

在 Nginx 配置中添加：

```nginx
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_types text/plain text/css text/xml application/json application/javascript application/rss+xml application/atom+xml image/svg+xml;
```

### 8.2 浏览器缓存

```nginx
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
    expires 1M;
    add_header Cache-Control "public, immutable";
}
```

### 8.3 启用 HTTP/2

确保 Nginx 监听指令包含 `http2`：

```nginx
listen 443 ssl http2;
```

## 9. 故障排除

### 9.1 502 Bad Gateway

```bash
# 检查服务状态
sudo systemctl status video-downloader

# 检查端口监听
sudo netstat -tlnp | grep 9001

# 检查防火墙
sudo ufw status
sudo ufw allow 80
sudo ufw allow 443
```

### 9.2 解析超时

增加 Nginx 和 Uvicorn 超时时间：

```nginx
# Nginx
proxy_connect_timeout 120s;
proxy_send_timeout 120s;
proxy_read_timeout 120s;
```

```bash
# Uvicorn
uvicorn main:app --host 0.0.0.0 --port 9001 --timeout-keep-alive 120
```

### 9.3 yt-dlp 更新

```bash
# 手动更新 yt-dlp
source venv/bin/activate
pip install -U yt-dlp

# 重启服务
sudo systemctl restart video-downloader
```

## 10. 成本估算

| 项目 | 费用 | 说明 |
|------|------|------|
| VPS | $5-6/月 | 1核1GB，1TB 流量 |
| Cloudflare | 免费 | CDN + SSL + DDoS 防护 |
| 域名 | $10-15/年 | .com 域名 |
| **总计** | **~$6/月** | 支持数千用户 |

## 总结

按照这个指南部署后：

1. ✅ 用户通过 Cloudflare CDN 访问网站（全球加速）
2. ✅ API 请求发送到 VPS 进行解析（低成本）
3. ✅ 视频直接下载到用户浏览器（零带宽成本）
4. ✅ 自动 HTTPS 和 DDoS 防护
5. ✅ 可扩展性强，可随时增加解析服务器
