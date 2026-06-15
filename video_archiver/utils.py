import os
import subprocess
import re
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

def get_video_rotation(file_path):
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream_tags=rotate",
            "-of", "default=nw=1:nk=1",
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        rot_str = result.stdout.strip()
        if rot_str:
            return float(rot_str)
    except Exception:
        pass
    return 0.0

def get_video_info(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=r_frame_rate,codec_name,codec_type",
        "-of", "csv=p=0", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        if not output: return None, None, None
        
        lines = output.replace('\r', '').split('\n')
        fps = None
        duration = None
        audio_codec = None
        
        for line in lines:
            parts = line.split(',')
            if "video" in parts:
                for p in parts:
                    if '/' in p:
                        num, den = p.split('/')
                        if float(den) > 0: fps = float(num) / float(den)
            elif "audio" in parts:
                for p in parts:
                    if p != "audio" and p != "stream" and not '/' in p and not p.replace('.', '', 1).isdigit():
                        audio_codec = p
                        break
            else:
                for p in parts:
                    if p.replace('.', '', 1).isdigit() and duration is None:
                        duration = float(p)
        
        if duration is None:
            for line in lines:
                for p in line.split(','):
                    if p.replace('.', '', 1).isdigit():
                        duration = float(p)
                        break
        
        return duration, fps, audio_codec
    except Exception:
        return None, None, None

def parse_ffmpeg_time(log_line):
    match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", log_line)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        return hours * 3600 + minutes * 60 + seconds
    return None
