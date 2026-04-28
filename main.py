from flask import Flask, request, jsonify
import yt_dlp
import os

app = Flask(__name__)

# 健康检查（Railway/Render 需要）
@app.route('/')
def health():
    return jsonify({'status': 'ok', 'service': 'yt-dlp-backend'})

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'error': 'Missing URL'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # 提取格式（优先视频格式）
            formats = []
            seen_qualities = set()

            for f in info.get('formats', []):
                # 过滤有效格式
                has_video = f.get('vcodec') != 'none'
                has_audio = f.get('acodec') != 'none'

                if not has_video and not has_audio:
                    continue

                quality = f.get('quality_label') or f.get('height', 'audio')
                if quality in seen_qualities and has_video:
                    continue
                if has_video:
                    seen_qualities.add(quality)

                # 估算文件大小
                filesize = f.get('filesize') or f.get('filesize_approx')
                size_str = f"~{filesize // 1024 // 1024}MB" if filesize else "~Unknown"

                formats.append({
                    'formatId': f['format_id'],
                    'quality': f"{quality}p" if isinstance(quality, int) else str(quality),
                    'mimeType': f"video/{f.get('ext', 'mp4')}" if has_video else f"audio/{f.get('ext', 'mp3')}",
                    'hasAudio': has_audio,
                    'fileSizeApprox': size_str
                })

            # 限制返回数量，避免 JSON 过大
            formats = formats[:8]

            # 平台检测
            extractor = info.get('extractor', 'unknown')
            platform_map = {
                'youtube': 'youtube',
                'tiktok': 'tiktok',
                'instagram': 'instagram',
                'twitter': 'twitter',
                'vimeo': 'vimeo',
                'reddit': 'reddit',
                'facebook': 'facebook'
            }
            platform = platform_map.get(extractor, extractor)

            return jsonify({
                'platform': platform,
                'title': info.get('title', 'Unknown'),
                'author': info.get('uploader', 'Unknown'),
                'duration': info.get('duration_string') or str(info.get('duration', 'Unknown')),
                'thumbnail': info.get('thumbnail', ''),
                'originalUrl': url,
                'formats': formats
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('formatId')

    if not url or not format_id:
        return jsonify({'error': 'Missing URL or formatId'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': format_id,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # 找到对应格式的直链
            format_info = next((f for f in info['formats'] if f['format_id'] == format_id), None)
            if not format_info:
                return jsonify({'error': 'Format not found'}), 404

            direct_url = format_info.get('url')
            if not direct_url:
                return jsonify({'error': 'No direct URL available'}), 500

            ext = format_info.get('ext', 'mp4')
            content_type = 'audio/mpeg' if ext in ['mp3', 'm4a', 'webm'] else 'video/mp4'

            return jsonify({
                'success': True,
                'directUrl': direct_url,
                'filename': f"{info.get('title', 'video').replace(' ', '_')}.{ext}",
                'contentType': content_type,
                'platform': info.get('extractor', 'unknown')
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
