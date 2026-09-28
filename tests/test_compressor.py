import json
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE_VIDEOS, requires_exiftool, requires_ffmpeg, wait_for


def run_archive(qapp, src, dst, renderer_index=0, crf=None):
    from video_helper_tools.compressor.gui import ArchiverGUI

    gui = ArchiverGUI()
    gui.txt_src.setText(str(src))
    gui.txt_dst.setText(str(dst))
    gui.combo_renderer.setCurrentIndex(renderer_index)
    gui.combo_preset.setCurrentText("ultrafast")
    if crf is not None:
        gui.spin_crf.setValue(crf)
    gui.spin_jobs.setValue(2)
    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    qapp.processEvents()
    gui.start_archiving()
    wait_for(gui.worker.finished_all)
    qapp.processEvents()
    return gui


@requires_ffmpeg
@requires_exiftool
def test_archive_run_end_to_end(qapp, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    # Same file name in two folders must not collide.
    shutil.copy(EXAMPLE_VIDEOS[0], src / "a.mp4")
    shutil.copy(EXAMPLE_VIDEOS[1], src / "sub" / "a.mp4")

    gui = run_archive(qapp, src, dst)

    outputs = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*.mp4"))
    assert outputs == ["a_archived.mp4", "sub/a_archived.mp4"]

    # Savings totals must match the real file sizes (each source counted once).
    assert gui.total_src_bytes == sum(p.stat().st_size for p in src.rglob("*.mp4"))
    assert gui.total_dst_bytes == sum(p.stat().st_size for p in dst.rglob("*.mp4"))

    # A second scan finds both outputs and plans nothing.
    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    assert gui.video_data_list == []


RENDERERS = [
    pytest.param(0, id="libx265"),
    pytest.param(1, id="videotoolbox", marks=pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")),
]


@requires_ffmpeg
@requires_exiftool
@pytest.mark.parametrize("renderer_index", RENDERERS)
def test_output_imports_into_apple_photos_with_metadata(qapp, tmp_path, renderer_index):
    from video_helper_tools.compressor.utils import is_photos_compatible

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    clip = src / "IMG_0001.mov"
    shutil.copy(EXAMPLE_VIDEOS[0], clip)
    # iPhone clips carry capture date and location in QuickTime Keys, which Photos reads.
    subprocess.run(
        ["exiftool", "-q", "-overwrite_original", "-Keys:CreationDate=2025:06:15 19:20:57+09:00",
         "-Keys:GPSCoordinates=35.1623 N, 129.1577 E, 8.3", str(clip)],
        check=True,
    )

    run_archive(qapp, src, dst, renderer_index=renderer_index)

    out = dst / "IMG_0001_archived.mp4"
    assert is_photos_compatible(out)
    tags = json.loads(subprocess.run(
        ["exiftool", "-j", "-n", "-Keys:CreationDate", "-Keys:GPSCoordinates", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout)[0]
    assert tags["CreationDate"].startswith("2025:06:15 19:20:57")
    assert tags["GPSCoordinates"].startswith("35.1623 129.1577")


def make_low_bitrate_clip(path, codec_args):
    """Tiny, heavily compressed clip so a lossless (CRF 0) re-encode is guaranteed to be larger."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(EXAMPLE_VIDEOS[0]), "-t", "3",
         *codec_args, "-c:a", "aac", "-b:a", "32k", str(path)],
        check=True,
    )


@requires_ffmpeg
@requires_exiftool
def test_larger_output_keeps_photos_compatible_original(qapp, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    make_low_bitrate_clip(src / "clip.mp4", ["-c:v", "libx264", "-b:v", "50k"])

    run_archive(qapp, src, dst, crf=0)

    assert (dst / "clip_archived.mp4").exists()
    assert (dst / "clip_source.mp4").exists()


@requires_ffmpeg
@requires_exiftool
def test_larger_output_does_not_copy_incompatible_original(qapp, tmp_path):
    from video_helper_tools.compressor.utils import is_photos_compatible

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    # MPEG-4 Part 2 (mp4v) is not importable into Apple Photos.
    make_low_bitrate_clip(src / "clip.mp4", ["-c:v", "mpeg4", "-b:v", "50k"])
    assert not is_photos_compatible(src / "clip.mp4")

    run_archive(qapp, src, dst, crf=0)

    outputs = sorted(p.name for p in dst.iterdir())
    assert outputs == ["clip_archived.mp4"]
    assert all(is_photos_compatible(p) for p in dst.iterdir())
