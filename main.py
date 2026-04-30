from flask import Flask, request, jsonify, Response
import yt_dlp
import os
import tempfile
import shutil

app = Flask(__name__)

# 允许 Vercel 跨域
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    return response

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
        # 使用 Android 客户端降低被识别概率
        'extractor_args': {
            'youtube': {
                'player_client': ['android'],
                'player_skip': ['webpage', 'configs', 'js'],
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            formats = []
            seen_qualities = set()

            for f in info.get('formats', []):
                has_video = f.get('vcodec') != 'none'
                has_audio = f.get('acodec') != 'none'

                if not has_video and not has_audio:
                    continue

                quality = f.get('quality_label') or f.get('height', 'audio')
                if quality in seen_qualities and has_video:
                    continue
                if has_video:
                    seen_qualities.add(quality)

                filesize = f.get('filesize') or f.get('filesize_approx')
                size_str = f"~{filesize // 1024 // 1024}MB" if filesize else "~Unknown"

                # 标记是否合一格式
                is_progressive = has_video and has_audio and f.get('protocol') in ['https', 'http']

                formats.append({
                    'formatId': f['format_id'],
                    'quality': f"{quality}p" if isinstance(quality, int) else str(quality),
                    'mimeType': f"video/{f.get('ext', 'mp4')}" if has_video else f"audio/{f.get('ext', 'mp3')}",
                    'hasAudio': has_audio,
                    'fileSizeApprox': size_str,
                    'isProgressive': is_progressive
                })

            # 限制返回数量
            formats = formats[:10]

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

    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, 'video.%(ext)s')

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': format_id,
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'writesubtitles': False,
            'writeautomaticsub': False,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                    'player_skip': ['webpage', 'configs', 'js'],
                }
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            ydl.download([url])

        # 找到生成的 mp4 文件
        files = os.listdir(temp_dir)
        mp4_files = [f for f in files if f.endswith('.mp4')]

        if not mp4_files:
            return jsonify({'error': 'Download failed: no MP4 generated'}), 500

        file_path = os.path.join(temp_dir, mp4_files[0])
        file_size = os.path.getsize(file_path)

        # 如果文件太大（>50MB），直接返回错误
        if file_size > 50 * 1024 * 1024:
            return jsonify({
                'error': 'File too large for free tier. Please select a lower resolution (144p/240p).'
            }), 413

        # 读取文件并返回
        with open(file_path, 'rb') as f:
            file_data = f.read()

        # 清理临时目录
        shutil.rmtree(temp_dir)
        temp_dir = None

        safe_title = info.get('title', 'video').replace(' ', '_').replace('/', '_')[:50]
        filename = f"{safe_title}.mp4"

        return Response(
            file_data,
            mimetype='video/mp4',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size)
            }
        )

    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'error': f'Download/Merge failed: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
