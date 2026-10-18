"""ffprobe/exiftool helpers of the compressor, checked against small generated files."""
import json
import subprocess

import pytest

from conftest import requires_exiftool, requires_ffmpeg


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def clip(path, vcodec=("libx264",), acodec=("aac",), extra=(), size="320x240", rate=25, audio=True):
    inputs = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration=1"]
    if audio:
        inputs += ["-f", "lavfi", "-i", "sine=duration=1"]
    ffmpeg(*inputs, "-c:v", *vcodec, *(["-c:a", *acodec] if audio else []), *extra, str(path))
    return path


@requires_ffmpeg
def test_check_dependencies_lists_what_is_missing(monkeypatch):
    from video_helper_tools.compressor import utils

    assert "ffmpeg" not in utils.check_dependencies()
    monkeypatch.setenv("PATH", "")
    assert utils.check_dependencies() == ["ffmpeg", "ffprobe", "exiftool"]


@requires_ffmpeg
def test_resolution_and_fps(tmp_path):
    from video_helper_tools.compressor.utils import get_resolution_and_fps

    assert get_resolution_and_fps(clip(tmp_path / "a.mp4", size="640x360", rate=30)) == ("640", "360", 30.0)
    width, height, fps = get_resolution_and_fps(clip(tmp_path / "b.mp4", rate="30000/1001"))
    assert (width, height) == ("320", "240") and fps == pytest.approx(29.97)
    assert get_resolution_and_fps(tmp_path / "missing.mp4") == (None, None, None)
    (tmp_path / "text.mp4").write_text("nope")
    assert get_resolution_and_fps(tmp_path / "text.mp4") == (None, None, None)


@requires_ffmpeg
def test_describe_streams(tmp_path):
    from video_helper_tools.compressor.utils import describe_streams

    text = describe_streams(clip(tmp_path / "a.mp4", size="640x360", rate=30))
    assert text.startswith("h264") and "640x360" in text and "30.00 fps" in text and text.endswith("audio aac")
    assert describe_streams(tmp_path / "missing.mp4") == ""


@requires_ffmpeg
@pytest.mark.parametrize("name,vcodec,vtag,acodec,expected", [
    ("hvc1.mp4", ("libx265", "-tag:v", "hvc1"), None, ("aac",), True),
    ("hev1.mp4", ("libx265", "-tag:v", "hev1"), None, ("aac",), False),   # Photos rejects hev1
    ("h264.mov", ("libx264",), None, ("aac",), True),
    ("h264.mkv", ("libx264",), None, ("aac",), False),                    # wrong container
    ("opus.mp4", ("libx264",), None, ("libopus", "-strict", "-2"), False),
    ("pcm.mov", ("libx264",), None, ("pcm_s16le",), True),                # PCM only valid in QuickTime
    ("pcm.mp4", ("libx264",), None, ("pcm_s16le",), False),
])
def test_is_photos_compatible(tmp_path, name, vcodec, vtag, acodec, expected):
    from video_helper_tools.compressor.utils import is_photos_compatible

    path = tmp_path / name
    try:
        clip(path, vcodec=vcodec, acodec=acodec, extra=["-x265-params", "log-level=none"] if "x265" in vcodec[0] else [])
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot create the test file")
    assert is_photos_compatible(path) is expected


@requires_ffmpeg
def test_is_photos_compatible_without_audio_and_for_broken_files(tmp_path):
    from video_helper_tools.compressor.utils import is_photos_compatible

    assert is_photos_compatible(clip(tmp_path / "mute.mp4", audio=False))
    assert not is_photos_compatible(tmp_path / "missing.mp4")


@requires_ffmpeg
def test_audio_streams_with_and_without_tracks(tmp_path):
    from video_helper_tools.compressor.utils import get_audio_streams

    assert get_audio_streams(clip(tmp_path / "a.mp4")) == [("aac", None)]
    assert get_audio_streams(clip(tmp_path / "mute.mp4", audio=False)) == []
    assert get_audio_streams(tmp_path / "missing.mp4") == []


@requires_ffmpeg
def test_display_rotation_and_hdr_color_of_plain_clip(tmp_path):
    from video_helper_tools.compressor.utils import get_display_rotation, get_hdr_color

    plain = clip(tmp_path / "a.mp4")
    assert get_display_rotation(plain) == 0 and get_hdr_color(plain) is None
    assert get_display_rotation(tmp_path / "missing.mp4") == 0 and get_hdr_color(tmp_path / "missing.mp4") is None


@requires_ffmpeg
@pytest.mark.parametrize("angle", [90, 180, 270])
def test_display_rotation_reads_the_display_matrix(tmp_path, angle):
    from video_helper_tools.compressor.utils import get_display_rotation

    plain = clip(tmp_path / "a.mp4")
    ffmpeg("-display_rotation", str(angle), "-i", str(plain), "-c", "copy", str(tmp_path / "r.mp4"))
    assert get_display_rotation(tmp_path / "r.mp4") == angle


@requires_ffmpeg
@pytest.mark.parametrize("transfer,is_hdr", [("arib-std-b67", True), ("smpte2084", True), ("bt709", False)])
def test_hdr_color_detection(tmp_path, transfer, is_hdr):
    from video_helper_tools.compressor.utils import get_hdr_color

    path = tmp_path / "c.mov"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=1",
           "-vf", f"setparams=color_primaries=bt2020:color_trc={transfer}:colorspace=bt2020nc,format=yuv420p10le",
           "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=none", "-tag:v", "hvc1", str(path))
    color = get_hdr_color(path)
    assert (color is not None) is is_hdr
    if is_hdr:
        assert color["color_trc"] == transfer and color["color_primaries"] == "bt2020"


@requires_ffmpeg
@requires_exiftool
def test_compression_settings_round_trip(tmp_path):
    from video_helper_tools.compressor.utils import EXIFTOOL_CONFIG, read_compression_settings, settings_tag_argument

    tagged, plain = clip(tmp_path / "tagged.mp4"), clip(tmp_path / "plain.mp4")
    record = {"version": 1, "encoder": "libx265", "crf": 24, "max_res": None, "note": "ünïcode"}
    subprocess.run(["exiftool", "-config", str(EXIFTOOL_CONFIG), settings_tag_argument(record), str(tagged),
                    "-overwrite_original", "-q"], check=True)
    found = read_compression_settings([tagged, plain])
    assert found == {str(tagged): record}
    assert read_compression_settings([]) == {}


def test_corrupt_settings_tag_is_ignored(monkeypatch, tmp_path):
    from video_helper_tools.compressor import utils

    class Result:
        stdout = json.dumps([{"SourceFile": "a", "CompressionSettings": "{broken"},
                             {"SourceFile": "b", "CompressionSettings": '{"crf": 1}'}, {"SourceFile": "c"}])

    monkeypatch.setattr(utils.subprocess, "run", lambda *a, **k: Result())
    assert utils.read_compression_settings(["a", "b", "c"]) == {"b": {"crf": 1}}
    monkeypatch.setattr(utils.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "not json"})())
    assert utils.read_compression_settings(["a"]) == {}


def test_open_in_finder_chooses_file_or_parent(monkeypatch, tmp_path):
    from video_helper_tools.compressor import utils

    calls = []
    monkeypatch.setattr(utils.subprocess, "run", lambda cmd, *a, **k: calls.append(cmd))
    existing = tmp_path / "x.mp4"
    existing.write_bytes(b"1")
    utils.open_in_finder(existing)
    utils.open_in_finder(tmp_path / "gone.mp4")
    utils.open_in_finder(tmp_path / "no" / "such" / "gone.mp4")
    assert calls == [["open", "-R", str(existing)], ["open", str(tmp_path)]]


def test_format_size_units():
    from video_helper_tools.compressor.utils import format_size

    assert format_size(0) == "0.00 B" and format_size(1024 ** 3) == "1.00 GB" and format_size(3 * 1024 ** 4) == "3.00 TB"
