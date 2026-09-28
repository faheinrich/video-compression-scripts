import os
import json
import subprocess
import re
import hashlib
from pathlib import Path

def format_size(size_bytes):
    is_negative = size_bytes < 0
    size_bytes = abs(size_bytes)
    
    unit_found = 'B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            unit_found = unit
            break
        size_bytes /= 1024.0
    else:
        unit_found = 'TB'
    
    prefix = "-" if is_negative else ""
    return f"{prefix}{size_bytes:.2f} {unit_found}"

def get_thumbnail_path(video_path):
    thumb_dir = Path("thumbnails")
    thumb_dir.mkdir(exist_ok=True)
    video_hash = hashlib.md5(str(video_path).encode()).hexdigest()
    return thumb_dir / f"{video_hash}.jpg"

def generate_thumbnail(video_path, output_path):
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-ss", "00:00:01",
        "-vframes", "1",
        "-vf", "scale=100:-1",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except Exception:
        return False

def format_duration(seconds):
    if not seconds or seconds == "wird geladen...": return "⏱️ --:--"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"⏱️ {mins:02d}:{secs:02d}"

def check_dependencies():
    missing = []
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        missing.append("ffmpeg")
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
    except Exception:
        missing.append("ffprobe")
    try:
        subprocess.run(["exiftool", "-ver"], capture_output=True, check=True)
    except Exception:
        missing.append("exiftool")
    return missing

def open_in_finder(file_path):
    path = Path(file_path)
    if path.exists():
        subprocess.run(["open", "-R", str(path)])
    else:
        if path.parent.exists():
            subprocess.run(["open", str(path.parent)])

def get_resolution_and_fps(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "csv=p=0", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if not output: return None, None, None
        
        parts = output.split(',')
        if len(parts) >= 3:
            width = parts[0]
            height = parts[1]
            fps_str = parts[2]
            fps = None
            if '/' in fps_str:
                num, den = fps_str.split('/')
                if float(den) > 0:
                    fps = round(float(num) / float(den), 2)
            else:
                fps = round(float(fps_str), 2)
            return width, height, fps
        return None, None, None
    except Exception:
        return None, None, None

def get_video_info(file_path):
    """Return (duration_s, fps, audio_codec) of the first real video/audio stream; None where unknown."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,codec_name,r_frame_rate:stream_disposition=attached_pic",
        "-of", "json", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None, None, None

    streams = info.get("streams", [])
    # Cover art is reported as a video stream; skip it.
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = info.get("format", {}).get("duration")
    duration = float(duration) if duration not in (None, "N/A") else None

    fps = None
    if video:
        num, _, den = video.get("r_frame_rate", "0/0").partition("/")
        if den and float(den) > 0:
            fps = float(num) / float(den)

    return duration, fps, audio.get("codec_name") if audio else None

def parse_ffmpeg_time(log_line):
    match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", log_line)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        return hours * 3600 + minutes * 60 + seconds
    return None
