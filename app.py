import os
import uuid
import time
import shutil
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, after_this_request
import yt_dlp
import re

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
MAX_DURATION_SECONDS = 120 * 60  # 2 hours
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Check for FFmpeg (System PATH or Winget default)
try:
    import shutil
    if shutil.which('ffmpeg'):
        FFMPEG_AVAILABLE = True
    else:
        # Fallback: Check standard Winget install location
        winget_path = os.path.expanduser(r'~\AppData\Local\Microsoft\WinGet\Links')
        ffmpeg_exe = os.path.join(winget_path, 'ffmpeg.exe')
        if os.path.exists(ffmpeg_exe):
            print(f"Found FFmpeg at: {ffmpeg_exe}")
            os.environ["PATH"] += os.pathsep + winget_path
            FFMPEG_AVAILABLE = True
        else:
            FFMPEG_AVAILABLE = False
except:
    FFMPEG_AVAILABLE = False

if not FFMPEG_AVAILABLE:
    print("WARNING: FFmpeg not found. High quality stream merging will be disabled.")

def cleanup_file(file_path):
    """
    Attempts to delete the file after a short delay to ensure the handle is closed.
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Deleted temporary file: {file_path}")
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")

def cleanup_old_files():
    """
    Scans the download folder and deletes files older than 2 hours (7200 seconds).
    """
    try:
        current_time = time.time()
        for filename in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, filename)
            # Check if it's a file
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > 7200:  # 2 hours
                    try:
                        os.remove(file_path)
                        print(f"Auto-deleted old file: {filename}")
                    except Exception as e:
                        print(f"Failed to delete old file {filename}: {e}")
    except Exception as e:
        print(f"Error during storage cleanup: {e}")

import sqlite3

# Database Setup
DB_NAME = 'flux_archive.db'

def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS feedback
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      rating INTEGER, 
                      comment TEXT, 
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

# Initialize DB on start
init_db()

@app.route('/feedback', methods=['POST'])
def save_feedback():
    try:
        data = request.json
        rating = data.get('rating')
        comment = data.get('comment')
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO feedback (rating, comment) VALUES (?, ?)", (rating, comment))
        conn.commit()
        conn.close()
            
        return {'status': 'success'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}

@app.route('/')
def index():
    return render_template('index.html', ffmpeg_missing=not FFMPEG_AVAILABLE)

# Global store for progress tracking
progress_status = {}

def get_progress_hook(uid):
    def hook(d):
        if d['status'] == 'downloading':
            # Remove ANSI escape codes (weird characters)
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            
            raw_p = d.get('_percent_str', '0%').replace('%','')
            
            # Calculate speed in MB/s from raw bytes/sec if available
            speed_float = d.get('speed')
            if speed_float:
                speed_str = f"{speed_float / 1024 / 1024:.2f} MB/s"
            else:
                speed_str = d.get('_speed_str', 'N/A').strip()
            
            p = ansi_escape.sub('', raw_p).strip()
            
            progress_status[uid] = {
                'state': 'downloading',
                'percent': p,
                'speed': speed_str,
                'msg': f"Downloading... {p}%"
            }
        elif d['status'] == 'finished':
            progress_status[uid] = {
                'state': 'merging',
                'percent': 100,
                'msg': "Merging High-Quality Streams..."
            }
    return hook

@app.route('/progress/<uid>')
def get_progress(uid):
    return progress_status.get(uid, {'state': 'waiting', 'percent': 0, 'msg': 'Initializing...'})

@app.route('/download', methods=['POST'])
def download_video():
    # Run maintenance: clean up any old files
    cleanup_old_files()

    video_url = request.form.get('url')
    # Get client-generated ID for progress tracking
    client_uid = request.form.get('uid')
    
    if not video_url:
        flash('Please provide a valid YouTube URL', 'error')
        return redirect(url_for('index'))

    # Generate a unique ID for the FILE (internal use)
    download_id = str(uuid.uuid4())
    
    # PATH to cookies.txt
    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')

    # Configure yt-dlp to just get info first (for validation and duration check)
    ydl_opts_info = {
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 30,
        'retries': 10,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }
    
    # Inject cookies if file exists
    if os.path.exists(cookie_path):
        print(f"DEBUG: Found cookies.txt at {cookie_path}")
        ydl_opts_info['cookiefile'] = cookie_path
    else:
        print(f"DEBUG: cookies.txt NOT FOUND at {cookie_path}")
        print(f"DEBUG: Current Directory listed: {os.listdir('.')}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            try:
                info_dict = ydl.extract_info(video_url, download=False)
            except Exception as e:
                flash(f'Error fetching video info: {str(e)}', 'error')
                return redirect(url_for('index'))

            duration = info_dict.get('duration', 0)
            if duration > MAX_DURATION_SECONDS:
                flash(f'Video is too long. Max duration is {MAX_DURATION_SECONDS//60} minutes.', 'error')
                return redirect(url_for('index'))

            title = info_dict.get('title', 'video')
            # Truncate title to prevent long filenames (common in TikTok/Instagram)
            if isinstance(title, str) and len(title) > 50:
                title = title[:50]
            
            # Sanitize title for download filename
            safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()

    except Exception as e:
        flash(f'An unexpected error occurred during validation: {str(e)}', 'error')
        return redirect(url_for('index'))

    # Determine format based on FFmpeg availability
    if FFMPEG_AVAILABLE:
        # Prioirty: Best video + Best audio (Force best quality), fallback to best single file
        format_selector = 'bestvideo+bestaudio/best'
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{download_id}.%(ext)s')
    else:
        # Best single file (No FFmpeg needed) - usually 720p max
        format_selector = 'best[ext=mp4]/best'
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{download_id}.mp4')
        flash('FFmpeg not installed. Downloaded standard quality (720p). Install FFmpeg for 1080p/4K.', 'error')

    # Configure yt-dlp for actual download
    ydl_opts_download = {
        'format': format_selector,
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'nopart': True,  # Fix for [WinError 32]: Write directly to final filename
        'force_overwrites': True,
        'socket_timeout': 30,
        'retries': 10,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        },
        'progress_hooks': [get_progress_hook(client_uid)] if client_uid else [],
        
        # Speed & Quality Optimizations
        'concurrent_fragment_downloads': 8, # Download 8 segments at once (Major speed boost for DASH)
        'buffersize': 1024 * 1024, # 1MB Buffer
    }

    if os.path.exists(cookie_path):
        ydl_opts_download['cookiefile'] = cookie_path

    if FFMPEG_AVAILABLE:
         ydl_opts_download['merge_output_format'] = 'mp4'

    final_filename_pattern = os.path.join(DOWNLOAD_FOLDER, f'{download_id}.mp4')

    try:
        if client_uid:
            progress_status[client_uid] = {'state': 'starting', 'percent': 0, 'msg': 'Connecting to YouTube...'}
            
        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
            ydl.download([video_url])
            
        if client_uid:
             progress_status[client_uid] = {'state': 'complete', 'percent': 100, 'msg': 'Download Complete!'}
             
    except Exception as e:
        if client_uid:
             progress_status[client_uid] = {'state': 'error', 'percent': 0, 'msg': 'Error occurred'}
        flash(f'Download failed: {str(e)}', 'error')
        return redirect(url_for('index'))


    # Determine the actual file path. 
    # If not merging, the extension might be embedded in the output.
    # We explicitly set mp4 above for the fallback, so it should be there.
    # However, let's verify what file strictly exists.
    
    # Retry loop to wait for file system (FFmpeg merge might lag slightly)
    final_filename = None
    for _ in range(5):
        if os.path.exists(final_filename_pattern):
            final_filename = final_filename_pattern
            break
        # Fallback search if extension differed
        possible_files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.startswith(download_id)]
        if possible_files:
            final_filename = os.path.join(DOWNLOAD_FOLDER, possible_files[0])
            break
        time.sleep(1)

    if not final_filename:
        flash('Error: Processed file not found.', 'error')
        return redirect(url_for('index'))
    
    try:
        return_filename = f"{safe_title}.mp4" if safe_title else "download.mp4"
        
        response = send_file(
            final_filename, 
            as_attachment=True, 
            download_name=return_filename,
            mimetype='video/mp4'
        )
        
        
        # Register cleanup to run after response closes
        response.call_on_close(lambda: cleanup_file(final_filename))
        
        return response

    except Exception as e:
        flash(f'Error sending file: {str(e)}', 'error')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
