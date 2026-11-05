"""Single-video YouTube download adapter."""
import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


def normalize_url(value):
    match = re.search(r'https?://[^\s<>]+', str(value))
    if not match:
        raise ValueError("请输入 YouTube 视频链接")
    parsed = urlsplit(match.group().rstrip(').，。'))
    host = (parsed.hostname or '').lower()
    if parsed.port not in (None, 443, 80) or parsed.username or parsed.password:
        raise ValueError("无效的 YouTube 链接")
    if host == 'youtu.be':
        identifier = parsed.path.strip('/')
    elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
        parts = parsed.path.strip('/').split('/')
        identifier = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else (parts[1] if len(parts) == 2 and parts[0] in {'shorts', 'live', 'embed'} else '')
    else:
        raise ValueError("仅支持 YouTube 单个视频链接")
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier):
        raise ValueError("链接缺少有效的视频 ID，不支持频道或播放列表")
    return 'https://www.youtube.com/watch?v=' + identifier


def download_video(url, output_dir, progress):
    import yt_dlp
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    last_update = [0.0]
    deadline = time.monotonic() + 1200
    def hook(data):
        if time.monotonic() > deadline:
            raise RuntimeError('YouTube 下载超过 20 分钟，请检查网络后重试')
        if data.get('status') == 'downloading' and time.monotonic() - last_update[0] < 2:
            return
        last_update[0] = time.monotonic()
        if data.get('status') == 'downloading':
            total = data.get('total_bytes') or data.get('total_bytes_estimate')
            percent = f" {data.get('downloaded_bytes', 0) / total:.0%}" if total else ''
            progress('正在下载 YouTube 视频' + percent)
        elif data.get('status') == 'finished':
            progress('媒体下载完成，正在合并音视频')
    class Logger:
        def debug(self, message): pass
        def warning(self, message): pass
        def error(self, message): pass
    options = {
        'format': 'bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]',
        'outtmpl': str(output_dir / '%(id)s.%(ext)s'),
        'noplaylist': True, 'socket_timeout': 30, 'retries': 2,
        'fragment_retries': 2, 'quiet': True, 'logger': Logger(),
        'merge_output_format': 'mp4', 'progress_hooks': [hook],
        'js_runtimes': {'node': {}}, 'cachedir': False,
        'match_filter': lambda info, **kw: '暂不支持直播，请等待直播结束' if info.get('is_live') else None,
    }
    if os.environ.get('YOUTUBE_COOKIE_FILE'):
        options['cookiefile'] = os.environ['YOUTUBE_COOKIE_FILE']
    if os.environ.get('YOUTUBE_PROXY'):
        options['proxy'] = os.environ['YOUTUBE_PROXY']
    if not shutil.which('ffmpeg'):
        raise RuntimeError('YouTube 音视频合并需要安装 ffmpeg')
    progress('正在解析 YouTube 视频')
    try:
        with yt_dlp.YoutubeDL(options) as client:
            info = client.extract_info(normalize_url(url), download=True)
    except yt_dlp.utils.DownloadError as exc:
        text = str(exc)
        if 'Sign in' in text or 'cookies' in text or '403' in text:
            raise RuntimeError('YouTube 拒绝下载：请检查网络，或通过 YOUTUBE_COOKIE_FILE 配置有效的登录 Cookie 文件') from None
        raise RuntimeError('YouTube 下载失败，请检查链接、网络和 yt-dlp 版本') from None
    if not info:
        raise RuntimeError('无法下载直播或不可用的视频')
    files = [p for p in output_dir.iterdir() if p.stem == info['id'] and p.suffix in {'.mp4', '.webm', '.mkv'}]
    if not files:
        raise RuntimeError('下载未产生完整视频文件')
    return files
