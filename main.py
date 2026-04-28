from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import tempfile

app = Flask(__name__)

# 健康检查
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

            formats = []
            seen_qualities = set()

            # 优先合一格式（视频+音频一体，无需合并）
            progressive_formats = []
            dash_formats = []

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

                fmt = {
                    'formatId': f['format_id'],
                    'quality': f"{quality}p" if isinstance(quality, int) else str(quality),
                    'mimeType': f"video/{f.get('ext', 'mp4')}" if has_video else f"audio/{f.get('ext', 'mp3')}",
                    'hasAudio': has_audio,
                    'fileSizeApprox': size_str
                }

                # 合一格式（progressive）：同时有视频和音频，且是https直链
                if has_video and has_audio and f.get('protocol') in ['https', 'http']:
                    progressive_formats.append(fmt)
                else:
                    dash_formats.append(fmt)

            # 优先展示合一格式（用户可直接下载MP4），再展示DASH格式
            formats = progressive_formats[:4] + dash_formats[:4]

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

    try:
        # 策略1：优先尝试合一格式（22=720p, 18=360p）
        # 策略2：如果用户选的格式是DASH，尝试用yt-dlp下载并合并

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': format_id,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # 找到对应格式
            format_info = next((f for f in info['formats'] if f['format_id'] == format_id), None)
            if not format_info:
                return jsonify({'error': 'Format not found'}), 404

            # 如果是合一格式（有视频有音频，且是https/http），直接返回直链
            has_video = format_info.get('vcodec') != 'none'
            has_audio = format_info.get('acodec') != 'none'
            is_progressive = has_video and has_audio and format_info.get('protocol') in ['https', 'http']

            if is_progressive:
                direct_url = format_info.get('url')
                ext = format_info.get('ext', 'mp4')
                return jsonify({
                    'success': True,
                    'directUrl': direct_url,
                    'filename': f"{info.get('title', 'video').replace(' ', '_')}.{ext}",
                    'contentType': 'video/mp4',
                    'platform': info.get('extractor', 'unknown'),
                    'isProgressive': True
                })

            # 如果是DASH格式（视频音频分离），需要下载合并
            # 由于Railway免费版限制，这里返回提示，建议用户选择720p或360p格式
            return jsonify({
                'success': False,
                'error': 'This format requires server-side merging (DASH stream). Please select 720p or 360p format for direct MP4 download.',
                'suggestedFormats': ['22', '18']
            }), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
