import os
import re
import json
from flask import Flask, request, jsonify, send_file
import yt_dlp

app = Flask(__name__)

def sanitize_filename(title):
    """清理文件名中的特殊字符"""
    if not title:
        return "video"
    
    # 移除危险字符：# @ < > : " / \ | ? *
    cleaned = re.sub(r'[<>:"/\\|?*#@]', '', title)
    
    # 替换连续空格为单个空格
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # 去除首尾空格
    cleaned = cleaned.strip()
    
    # 限制长度 100 字符
    cleaned = cleaned[:100]
    
    # 如果清理后为空，用默认名
    if not cleaned:
        cleaned = "video"
    
    return cleaned

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()
        url = data.get('url')

        if not url:
            return jsonify({"error": "Missing URL"}), 400

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extractor_args': {
                'tiktok': {
                    'player_client': ['android'],
                }
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get('formats', []):
            # 只包含有视频流的格式
            if f.get('vcodec') != 'none':
                is_progressive = f.get('acodec') != 'none'
                
                # 估算文件大小
                filesize = f.get('filesize') or f.get('filesize_approx')
                size_str = "~Unknown"
                if filesize:
                    if filesize < 1024*1024:
                        size_str = f"~{filesize/1024:.0f}KB"
                    else:
                        size_str = f"~{filesize/(1024*1024):.0f}MB"
                
                formats.append({
                    'formatId': f.get('format_id'),
                    'quality': f"{f.get('height', 'unknown')}p" if f.get('height') else f.get('format_note', 'unknown'),
                    'mimeType': f.get('ext', 'mp4'),
                    'hasAudio': is_progressive,
                    'fileSizeApprox': size_str,
                    'isProgressive': is_progressive,
                    'height': f.get('height', 0),
                })

        # 按分辨率排序
        formats.sort(key=lambda x: x.get('height', 0), reverse=True)

        return jsonify({
            'platform': 'TikTok' if 'tiktok' in url else 'Unknown',
            'title': info.get('title', 'Unknown'),
            'author': info.get('uploader', 'Unknown'),
            'duration': info.get('duration_string', 'Unknown'),
            'thumbnail': info.get('thumbnail', ''),
            'originalUrl': url,
            'formats': formats,
        })

    except Exception as e:
        print(f"Analyze error: {str(e)}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

@app.route('/download', methods=['POST'])
def download():
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('formatId')

        if not url or not format_id:
            return jsonify({"error": "Missing URL or formatId"}), 400

        # 先分析获取最新格式列表（避免格式ID过期）
        analyze_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extractor_args': {
                'tiktok': {
                    'player_client': ['android'],
                }
            },
        }

        with yt_dlp.YoutubeDL(analyze_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            available_formats = info.get('formats', [])
            title = info.get('title', 'video')

        # 清理文件名
        safe_title = sanitize_filename(title)

        # 检查请求的 formatId 是否仍然可用
        format_ids = [f.get('format_id') for f in available_formats]
        
        if format_id not in format_ids:
            # 格式已过期，回退到最佳可用格式
            # 优先找 isProgressive=True 且分辨率最高的
            progressive = [f for f in available_formats if f.get('acodec') != 'none' and f.get('vcodec') != 'none']
            if progressive:
                # 按分辨率排序，取最高
                best = max(progressive, key=lambda f: f.get('height', 0) or 0)
                format_id = best.get('format_id')
                print(f"Format expired, fallback to {format_id}")
            else:
                # 没有渐进式格式，取第一个
                format_id = available_formats[0].get('format_id') if available_formats else format_id

        # 下载选项
        ydl_opts = {
            'format': format_id,
            'outtmpl': f'/tmp/{safe_title}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'tiktok': {
                    'player_client': ['android'],
                }
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)

            # 检查实际下载的文件（yt-dlp 可能会改变扩展名）
            actual_file = downloaded_file
            if not os.path.exists(actual_file):
                # 尝试找 /tmp/ 下的匹配文件
                tmp_files = [f for f in os.listdir('/tmp/') if f.startswith(safe_title)]
                if tmp_files:
                    actual_file = os.path.join('/tmp/', sorted(tmp_files)[-1])

            if not os.path.exists(actual_file):
                return jsonify({"error": "Download failed - file not created"}), 500

            file_size = os.path.getsize(actual_file)
            if file_size == 0:
                return jsonify({"error": "Download failed - empty file"}), 500

            print(f"Download success: {actual_file}, size: {file_size} bytes")

            # 确定 MIME 类型
            mime_type = 'video/mp4'
            if actual_file.endswith('.webm'):
                mime_type = 'video/webm'
            elif actual_file.endswith('.mkv'):
                mime_type = 'video/x-matroska'

            # 发送文件，使用清理后的文件名
            return send_file(
                actual_file,
                mimetype=mime_type,
                as_attachment=True,
                download_name=f"{safe_title}.mp4"
            )

    except Exception as e:
        print(f"Download error: {str(e)}")
        return jsonify({"error": f"Download failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
