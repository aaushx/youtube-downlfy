import shutil
import sys
import os

def check_setup():
    print("Checking system setup...")
    
    # Check Python version
    print(f"Python version: {sys.version}")
    
    # Check FFmpeg
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        print(f"SUCCESS: FFmpeg found at {ffmpeg_path}")
    else:
        print("ERROR: FFmpeg NOT found in system PATH.")
        print("  -> You MUST install FFmpeg for high-quality downloads.")
        print("  -> Download from: https://www.gyan.dev/ffmpeg/builds/")
        print("  -> Add the 'bin' folder to your Windows Environment Variables.")
    
    # Check yt-dlp import
    try:
        import yt_dlp
        print(f"SUCCESS: yt-dlp is installed (version {yt_dlp.version.__version__})")
    except ImportError:
        print("ERROR: yt-dlp is NOT installed.")

    # Check Flask import
    try:
        import flask
        print(f"SUCCESS: Flask is installed (version {flask.__version__})")
    except ImportError:
        print("ERROR: Flask is NOT installed.")

if __name__ == "__main__":
    check_setup()
