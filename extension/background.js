// 后台脚本 - 简化版
// 只作为入口，所有解析和下载功能由后端处理

// 监听安装事件
chrome.runtime.onInstalled.addListener(() => {
  console.log('视频下载器已安装');
});

// 监听消息（简化版，主要用于错误处理）
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // 简单的ping响应，用于检查扩展是否正常工作
  if (message.type === 'PING') {
    sendResponse({ success: true });
  }
  
  // 保持消息通道开放以进行异步响应
  return true;
});
