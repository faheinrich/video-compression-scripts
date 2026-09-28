import json
import shutil
import subprocess
import sys
import time

import pytest

from conftest import EXAMPLE_VIDEOS, requires_exiftool, requires_ffmpeg, spin, wait_for


@pytest.fixture
def make_gui(qapp):
    """Creates ArchiverGUIs and stops their background threads afterwards."""
    from video_helper_tools.compressor.gui import ArchiverGUI

    created = []

    def factory():
        gui = ArchiverGUI()
        created.append(gui)
        return gui

    yield factory
    for gui in created:
        gui.shutdown()


def scan(qapp, gui, src, dst):
    gui.txt_src.setText(str(src))
    gui.txt_dst.setText(str(dst))
    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    qapp.processEvents()


def run_archive(qapp, gui, src, dst, renderer_index=0, crf=None):
    gui.combo_renderer.setCurrentIndex(renderer_index)
    gui.combo_preset.setCurrentText("ultrafast")
    if crf is not None:
        gui.slider_crf.setValue(crf)
    gui.spin_jobs.setValue(2)
    scan(qapp, gui, src, dst)
    gui.start_archiving()
    wait_for(gui.worker.finished_all)
    qapp.processEvents()
    return gui


@requires_ffmpeg
@requires_exiftool
def test_archive_run_end_to_end(qapp, make_gui, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    # Same file name in two folders must not collide.
    shutil.copy(EXAMPLE_VIDEOS[0], src / "a.mp4")
    shutil.copy(EXAMPLE_VIDEOS[1], src / "sub" / "a.mp4")

    gui = run_archive(qapp, make_gui(), src, dst)

    outputs = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*.mp4"))
    assert outputs == ["a_archived.mp4", "sub/a_archived.mp4"]
    assert {row.status for row in gui.model.rows} == {"done"}
    assert sorted(row.folder for row in gui.model.rows) == ["", "sub"]

    # Savings totals must match the real file sizes (each source counted once).
    assert gui.total_src_bytes == sum(p.stat().st_size for p in src.rglob("*.mp4"))
    assert gui.total_dst_bytes == sum(p.stat().st_size for p in dst.rglob("*.mp4"))
    gui.refresh_summary()
    assert "%" in gui.summary_values["saving"][1].text()
    assert gui.progress_text.text().startswith("Fertig")

    # A second scan finds both outputs and plans nothing.
    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    assert {row.status for row in gui.model.rows} == {"exists"}
    assert not gui.btn_run.isEnabled()


@requires_ffmpeg
def test_every_thumbnail_arrives(qapp, make_gui, tmp_path):
    # Regression: thumbnails were delivered through a lambda bound to the pool job's
    # short-lived signals object; most got lost and the app crashed on larger folders.
    src = tmp_path / "src"
    src.mkdir()
    for i in range(30):
        shutil.copy(EXAMPLE_VIDEOS[i % 2], src / f"clip_{i:02d}.mp4")
    gui = make_gui()
    scan(qapp, gui, src, tmp_path / "dst")

    deadline = time.monotonic() + 60
    while len(gui.model.thumbnails) < 30 and time.monotonic() < deadline:
        spin(100)
    assert len(gui.model.thumbnails) == 30


@requires_ffmpeg
@requires_exiftool
def test_overwrite_option_requeues_existing_results(qapp, make_gui, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    shutil.copy(EXAMPLE_VIDEOS[0], src / "a.mp4")
    gui = run_archive(qapp, make_gui(), src, dst)
    # mtime is copied from the original on purpose, so compare the inode change time.
    first = (dst / "a_archived.mp4").stat().st_ctime_ns

    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    assert not gui.btn_run.isEnabled()
    gui.cb_overwrite.setChecked(True)
    assert gui.btn_run.isEnabled()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    gui.start_archiving()
    wait_for(gui.worker.finished_all)
    qapp.processEvents()
    assert gui.model.rows[0].status == "done"
    assert (dst / "a_archived.mp4").stat().st_ctime_ns != first


@requires_ffmpeg
def test_scan_starts_automatically_once_both_folders_are_set(qapp, make_gui, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(EXAMPLE_VIDEOS[0], src / "clip.mp4")

    gui = make_gui()
    gui.txt_src.setText(str(src))
    spin(700)
    assert gui.scan_worker is None  # target still missing

    gui.txt_dst.setText(str(tmp_path / "dst"))
    spin(700)
    if gui.is_scanning():
        wait_for(gui.scan_worker.scan_finished, 10_000)
    qapp.processEvents()
    assert [row.src.name for row in gui.model.rows] == ["clip.mp4"]
    assert gui.btn_run.isEnabled()

    gui.duration_worker.wait(10_000)
    qapp.processEvents()
    assert gui.model.rows[0].duration == pytest.approx(26.9, abs=0.1)


@requires_ffmpeg
def test_home_relative_paths_are_expanded(qapp, make_gui, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "src").mkdir()
    shutil.copy(EXAMPLE_VIDEOS[0], tmp_path / "src" / "clip.mp4")
    gui = make_gui()
    scan(qapp, gui, "~/src", "~/dst")
    assert [row.src.name for row in gui.model.rows] == ["clip.mp4"]
    assert gui.model.rows[0].dst == tmp_path / "dst" / "clip_archived.mp4"


def test_quality_presets_and_custom_values(qapp, make_gui):
    gui = make_gui()
    gui.apply_quality_preset("small")
    assert (gui.slider_crf.value(), gui.slider_vt.value()) == (26, 45)
    assert gui.quality_buttons["small"].isChecked()

    # "Custom" follows the selected encoder's value.
    gui.combo_renderer.setCurrentIndex(1)  # VideoToolbox
    gui.slider_vt.setValue(70)
    assert not any(b.isChecked() for b in gui.quality_buttons.values())
    assert "70" in gui.quality_hint.text()
    gui.combo_renderer.setCurrentIndex(0)  # CPU still matches "small"
    assert gui.quality_buttons["small"].isChecked()

    gui.apply_quality_preset("archive")
    assert gui.quality_buttons["archive"].isChecked()


def test_only_the_selected_encoders_quality_controls_are_shown(qapp, make_gui):
    gui = make_gui()
    gui.show()
    gui.btn_advanced.setChecked(True)
    gui.combo_renderer.setCurrentIndex(0)
    assert gui.cpu_quality.isVisible() and not gui.gpu_quality.isVisible()
    gui.combo_renderer.setCurrentIndex(1)
    assert gui.gpu_quality.isVisible() and not gui.cpu_quality.isVisible()


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("renderer_index", [0, 1])
def test_settings_drawer_fits_without_clipping(qapp, make_gui, language, renderer_index):
    # Regression: long checkbox labels made the drawer content wider than the drawer.
    from video_helper_tools.core import i18n

    i18n.set_language(language)
    gui = make_gui()
    gui.resize(1200, 800)
    gui.show()
    gui.btn_advanced.setChecked(True)
    gui.combo_renderer.setCurrentIndex(renderer_index)
    qapp.processEvents()
    content = gui.drawer_scroll.widget()
    assert content.minimumSizeHint().width() <= gui.drawer_scroll.viewport().width()


def test_parallel_videos_accept_custom_values(qapp, make_gui):
    gui = make_gui()
    assert [gui.spin_jobs.itemText(i) for i in range(gui.spin_jobs.count())] == ["1", "2", "3", "4", "6", "8"]
    gui.spin_jobs.setValue(5)
    assert gui.spin_jobs.value() == 5
    gui.spin_jobs.setCurrentText("12")
    assert gui.spin_jobs.value() == 12


def test_status_filter_and_search(qapp, make_gui):
    from pathlib import Path
    from video_helper_tools.compressor.model import VideoRow

    gui = make_gui()
    gui.model.reset([
        VideoRow(src=Path("/a/one.mp4"), dst=Path("/b/one_archived.mp4"), size=10, status="planned"),
        VideoRow(src=Path("/a/two.mp4"), dst=Path("/b/two_archived.mp4"), size=20, status="exists", out_size=8),
        VideoRow(src=Path("/a/three.mp4"), dst=Path("/b/three_archived.mp4"), size=30, status="error"),
    ])
    gui.refresh_summary()
    assert gui.filter_buttons["error"].isVisibleTo(gui)
    assert not gui.filter_buttons["skipped"].isVisibleTo(gui)

    gui.set_filter("done")
    assert gui.proxy.rowCount() == 1
    gui.set_filter("all")
    gui.proxy.set_text_filter("thr")
    assert gui.proxy.rowCount() == 1


def test_folder_outside_the_source_root_does_not_break_the_row():
    from pathlib import Path
    from video_helper_tools.compressor.model import VideoRow

    row = VideoRow(src=Path("/elsewhere/clip.mp4"), dst=Path("/b/clip_archived.mp4"), size=1, root=Path("/src"))
    assert row.folder == ""


RENDERERS = [
    pytest.param(0, id="libx265"),
    pytest.param(1, id="videotoolbox", marks=pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")),
]


@requires_ffmpeg
@requires_exiftool
@pytest.mark.parametrize("renderer_index", RENDERERS)
def test_output_imports_into_apple_photos_with_metadata(qapp, make_gui, tmp_path, renderer_index):
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

    run_archive(qapp, make_gui(), src, dst, renderer_index=renderer_index)

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
def test_larger_output_keeps_photos_compatible_original(qapp, make_gui, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    make_low_bitrate_clip(src / "clip.mp4", ["-c:v", "libx264", "-b:v", "50k"])

    run_archive(qapp, make_gui(), src, dst, crf=0)

    assert (dst / "clip_archived.mp4").exists()
    assert (dst / "clip_source.mp4").exists()


@requires_ffmpeg
@requires_exiftool
def test_larger_output_does_not_copy_incompatible_original(qapp, make_gui, tmp_path):
    from video_helper_tools.compressor.utils import is_photos_compatible

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    # MPEG-4 Part 2 (mp4v) is not importable into Apple Photos.
    make_low_bitrate_clip(src / "clip.mp4", ["-c:v", "mpeg4", "-b:v", "50k"])
    assert not is_photos_compatible(src / "clip.mp4")

    gui = run_archive(qapp, make_gui(), src, dst, crf=0)

    outputs = sorted(p.name for p in dst.iterdir())
    assert outputs == ["clip_archived.mp4"]
    assert all(is_photos_compatible(p) for p in dst.iterdir())
    assert "Apple" in "\n".join(gui.model.rows[0].log)
