import webview
import requests

def analyze(url):
    try:
        res = requests.get(f"http://localhost:8000/api/info?url={url}")
        data = res.json()
        return {'formats': [f"{f['height']}p - {f['format_id']}" for f in data['formats']], 'title': data['title']}
    except Exception as e:
        return {'error': str(e)}

def download(url, fmt, title):
    try:
        res = requests.get(f"http://localhost:8000/api/download?url={url}&format_id={fmt}")
        filename = title[:50] + '.mp4'
        with open(filename, 'wb') as f:
            f.write(res.content)
        return {'success': True, 'filename': filename}
    except Exception as e:
        return {'error': str(e)}

if __name__ == '__main__':
    window = webview.create_window(
        title='Video Downloader',
        html='<!DOCTYPE html><html><head><meta charset="UTF-8"><style>body{font-family:Arial;padding:20px}input,button,select{padding:10px;margin:5px}button{background:#007bff;color:white;border:none;cursor:pointer}button:hover{background:#0056b3}#result{margin-top:20px;padding:10px;background:#f8f9fa}</style></head><body><h2>Video Downloader</h2><input type="text" id="url" placeholder="输入视频链接" style="width:300px;"><button onclick="analyze()">分析</button><div id="result"></div><script>let currentTitle="";function analyze(){const url=document.getElementById("url").value;pywebview.api.analyze(url).then(res=>{const div=document.getElementById("result");if(res.error){div.innerHTML="<p style=color:red>"+res.error+"</p>";}else{currentTitle=res.title;div.innerHTML="<p>"+res.title+"</p><select id=fmt>"+res.formats.map(f=>"<option>"+f+"</option>").join("")+"</select><button onclick=download()>下载</button>";}});}function download(){const url=document.getElementById("url").value;const fmt=document.getElementById("fmt").value.split(" - ")[1];pywebview.api.download(url,fmt,currentTitle).then(res=>{const div=document.getElementById("result");if(res.error){div.innerHTML="<p style=color:red>"+res.error+"</p>";}else{div.innerHTML="<p style=color:green>下载完成: "+res.filename+"</p>";}});}</script></body></html>',
        js_api=locals()
    )
    webview.start()
