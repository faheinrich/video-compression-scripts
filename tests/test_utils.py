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
