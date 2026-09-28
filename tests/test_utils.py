import pytest

from conftest import EXAMPLE_VIDEOS, requires_ffmpeg
from video_helper_tools.compressor.utils import format_duration, format_size, get_video_info, parse_ffmpeg_time


@pytest.mark.parametrize(
    "size, expected",
    [(0, "0.00 B"), (1023, "1023.00 B"), (1024, "1.00 KB"), (1536 * 1024, "1.50 MB"), (-2048, "-2.00 KB")],
)
def test_format_size(size, expected):
    assert format_size(size) == expected


def test_parse_ffmpeg_time():
    line = "frame=  120 fps= 60 q=28.0 size=512kB time=00:01:02.50 bitrate=67.1kbits/s speed=2.5x"
    assert parse_ffmpeg_time(line) == pytest.approx(62.5)
    assert parse_ffmpeg_time("no timestamp here") is None


def test_format_duration():
    assert format_duration(75) == "⏱️ 01:15"
    assert format_duration(None) == "⏱️ --:--"


@requires_ffmpeg
def test_get_video_info_reads_example_video():
    duration, fps, audio_codec = get_video_info(EXAMPLE_VIDEOS[0])
    assert duration == pytest.approx(26.9, abs=0.1)
    assert fps == pytest.approx(24)
    assert audio_codec == "aac"


@requires_ffmpeg
def test_get_video_info_without_audio_track(tmp_path):
    import subprocess

    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(EXAMPLE_VIDEOS[0]), "-an", "-c", "copy", str(silent)], check=True)
    duration, fps, audio_codec = get_video_info(silent)
    assert duration == pytest.approx(26.9, abs=0.1)
    assert fps == pytest.approx(24)
    assert audio_codec is None


@requires_ffmpeg
def test_get_video_info_ignores_cover_art(tmp_path):
    # Cover art shows up as an extra video stream (90000 fps); using it would make the
    # compressor add an fps filter and upsample a 24 fps clip to the configured limit.
    import subprocess

    cover, with_cover = tmp_path / "cover.jpg", tmp_path / "with_cover.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(EXAMPLE_VIDEOS[0]), "-frames:v", "1", str(cover)], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(EXAMPLE_VIDEOS[0]), "-i", str(cover),
         "-map", "0", "-map", "1", "-c", "copy", "-disposition:v:1", "attached_pic", str(with_cover)],
        check=True,
    )
    assert get_video_info(with_cover)[1] == pytest.approx(24)


def test_get_video_info_missing_file(tmp_path):
    assert get_video_info(tmp_path / "does-not-exist.mp4") == (None, None, None)


@requires_ffmpeg
@pytest.mark.parametrize("seconds", [0.5, 1.02, 5])
def test_thumbnail_is_created_for_short_and_normal_clips(tmp_path, seconds):
    # Regression: the frame at 1 s was used unconditionally, so sub-second clips got none.
    import subprocess
    from video_helper_tools.compressor.utils import generate_thumbnail

    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(EXAMPLE_VIDEOS[0]), "-t", str(seconds), str(clip)], check=True)
    thumb = tmp_path / "thumb.jpg"
    assert generate_thumbnail(clip, thumb)
    assert thumb.stat().st_size > 0
