import os
import json
import subprocess
import re
import hashlib
import time
from pathlib import Path

from video_helper_tools.core.paths import duration_cache_file, thumbnail_dir

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

DEFAULT_POSTFIX = "_archived"
DEFAULT_EXCLUDES = "_archived, _compressed"


def clean_postfix(text):
    """The text appended to result names; path separators would let it escape the target folder."""
    return re.sub(r'[\\/:\x00-\x1f]', "", text).strip()


def parse_excludes(text):
    """Name endings (without extension, case-insensitive) of source videos to skip."""
    return tuple(part.lower() for part in re.split(r"[,;\s]+", text) if part)


def get_thumbnail_path(video_path):
    # Size and mtime are part of the key so a replaced file does not keep showing the old picture.
    try:
        stat = Path(video_path).stat()
        stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        stamp = ""
    video_hash = hashlib.md5(f"{video_path}|{stamp}".encode()).hexdigest()
    return thumbnail_dir() / f"{video_hash}.jpg"


THUMBNAIL_MAX_AGE_DAYS = 90


def prune_thumbnails(max_age_days=THUMBNAIL_MAX_AGE_DAYS):
    """Deletes thumbnails not written for a long time (changed or deleted videos leave orphans); returns the count."""
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for thumb in thumbnail_dir().glob("*.jpg"):
        try:
            if thumb.stat().st_mtime < cutoff:
                thumb.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def clear_caches():
    """Deletes all thumbnails and the duration cache; returns the number of bytes freed."""
    freed = 0
    for path in [*thumbnail_dir().glob("*.jpg"), duration_cache_file()]:
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
        except OSError:
            pass
    return freed

def generate_thumbnail(video_path, output_path):
    # One second in avoids black first frames; clips shorter than that fall back to the
    # first frame. Seeking before -i jumps to a keyframe instead of decoding up to it.
    output_path = Path(output_path)
    for offset in ("1", "0"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", offset, "-i", str(video_path),
               "-frames:v", "1", "-vf", "scale=160:-2", str(output_path)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if output_path.exists() and output_path.stat().st_size > 0:
            return True
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

def _probe(file_path):
    """Return (format_info, first real video stream, first audio stream), or None if unreadable."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,codec_tag_string,r_frame_rate,"
        "color_transfer,color_primaries,color_space:stream_disposition=attached_pic",
        "-of", "json", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    streams = info.get("streams", [])
    # Cover art is reported as a video stream; skip it.
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return info.get("format", {}), video, audio


def get_audio_streams(file_path):
    """(codec_name, name tag) for every audio stream, in file order; [] if unreadable or without audio.

    The name tag is the stream name some recorders write (e.g. ``simple_aac_recording0``); it is not kept when a file is
    re-muxed unless it is set again."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_name:stream_tags=name",
        "-of", "json", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        streams = json.loads(result.stdout).get("streams", [])
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return []
    return [(s.get("codec_name"), (s.get("tags") or {}).get("name")) for s in streams]


# Codec/tag combinations Apple Photos imports (hev1-tagged HEVC is rejected).
PHOTOS_VIDEO = {("hevc", "hvc1"), ("h264", "avc1")}
PHOTOS_AUDIO = {"aac", "alac"}


def is_photos_compatible(file_path):
    probe = _probe(file_path)
    if probe is None:
        return False
    _, video, audio = probe
    suffix = Path(file_path).suffix.lower()
    if suffix not in (".mov", ".mp4", ".m4v") or not video:
        return False
    if (video.get("codec_name"), video.get("codec_tag_string")) not in PHOTOS_VIDEO:
        return False
    if audio is None:
        return True
    codec = audio.get("codec_name", "")
    # Uncompressed PCM (iPhone "lpcm") is only valid in a QuickTime container.
    return codec in PHOTOS_AUDIO or (codec.startswith("pcm_") and suffix == ".mov")


def get_video_info(file_path):
    """Return (duration_s, fps, audio_codec) of the first real video/audio stream; None where unknown."""
    probe = _probe(file_path)
    if probe is None:
        return None, None, None
    fmt, video, audio = probe

    duration = fmt.get("duration")
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


# Settings a result was compressed with are stored in the file itself (custom XMP tag),
# so they survive moving the file and restarting the app.
EXIFTOOL_CONFIG = Path(__file__).with_name("exiftool_vht.config")
SETTINGS_TAG = "XMP-vht:CompressionSettings"


def settings_tag_argument(record):
    return f"-{SETTINGS_TAG}={json.dumps(record, sort_keys=True)}"


def read_compression_settings(paths):
    """Returns {str(path): settings dict} for the files that carry the tag; one exiftool call for all."""
    paths = [str(p) for p in paths]
    if not paths:
        return {}
    cmd = ["exiftool", "-config", str(EXIFTOOL_CONFIG), "-j", f"-{SETTINGS_TAG}", "-charset", "filename=utf8", "-@", "-"]
    try:
        result = subprocess.run(cmd, input="\n".join(paths), capture_output=True, text=True)
        entries = json.loads(result.stdout or "[]")
    except (OSError, json.JSONDecodeError):
        return {}
    found = {}
    for entry in entries:
        raw = entry.get("CompressionSettings")
        if not raw:
            continue
        try:
            found[entry["SourceFile"]] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def describe_streams(file_path):
    """Short codec summary for error messages, e.g. "hevc (Main 10), 3840x2160, 59.94 fps · audio pcm_s24le"."""
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "stream=codec_type,codec_name,profile,width,height,r_frame_rate,pix_fmt", "-of", "json", str(file_path)]
    try:
        streams = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout).get("streams", [])
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return ""
    parts = []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video":
            text = stream.get("codec_name", "?")
            if stream.get("profile"):
                text += f" ({stream['profile']})"
            if stream.get("width"):
                text += f", {stream['width']}x{stream['height']}"
            num, _, den = stream.get("r_frame_rate", "0/0").partition("/")
            if den and float(den) > 0:
                text += f", {float(num) / float(den):.2f} fps"
            if stream.get("pix_fmt"):
                text += f", {stream['pix_fmt']}"
            parts.append(text)
        elif kind == "audio":
            parts.append(f"audio {stream.get('codec_name', '?')}")
        elif kind:
            parts.append(f"{kind} {stream.get('codec_name') or ''}".strip())
    return " · ".join(parts)


def get_display_rotation(file_path):
    """Rotation from the display matrix (e.g. 90 for portrait phone clips stored landscape); 0, 90, 180 or 270."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream_side_data=rotation", "-of", "json", str(file_path)]
    try:
        streams = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout).get("streams", [])
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return 0
    for stream in streams:
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                return int(round(float(side_data["rotation"]))) % 360
    return 0


# HLG (iPhone HDR) and PQ (HDR10); everything else is treated as SDR.
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}


def get_hdr_color(file_path):
    """Colour tags to carry over for HDR sources, or None for SDR."""
    probe = _probe(file_path)
    if probe is None or probe[1] is None:
        return None
    video = probe[1]
    if video.get("color_transfer") not in HDR_TRANSFERS:
        return None
    return {
        "color_trc": video["color_transfer"],
        "color_primaries": video.get("color_primaries") or "bt2020",
        "colorspace": video.get("color_space") or "bt2020nc",
    }


def copy_file_times(src_path, dst_path):
    """Gives dst the access, modification and (on macOS) creation time of src. The Finder shows the
    creation time, so without this a compressed copy looks as if it had been made today."""
    stat = Path(src_path).stat()
    birth = getattr(stat, "st_birthtime", None)
    if birth is not None and birth < stat.st_mtime:
        # macOS moves a file's creation time back whenever the modification time is set to an earlier moment.
        os.utime(dst_path, (stat.st_atime, birth))
    os.utime(dst_path, (stat.st_atime, stat.st_mtime))


class DurationCache:
    """Remembers video durations between runs, keyed by file size and modification time, so a rescan of
    hundreds of videos on a slow disk does not have to open every file again."""

    def __init__(self, path=None):
        from video_helper_tools.core.paths import duration_cache_file
        self.path = Path(path) if path else duration_cache_file()
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = {}
        self.unsaved = 0

    @staticmethod
    def signature(file_path):
        stat = Path(file_path).stat()
        return [stat.st_size, stat.st_mtime_ns]

    def get(self, file_path):
        entry = self.entries.get(str(file_path))
        try:
            if entry and entry[:2] == self.signature(file_path):
                return entry[2]
        except OSError:
            pass
        return None

    def put(self, file_path, duration):
        try:
            self.entries[str(file_path)] = [*self.signature(file_path), duration]
            self.unsaved += 1
        except OSError:
            pass

    def save(self):
        if not self.unsaved:
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.entries), encoding="utf-8")
            os.replace(tmp, self.path)
            self.unsaved = 0
        except OSError:
            pass
