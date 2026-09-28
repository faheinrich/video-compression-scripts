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


def wait_idle(qapp, gui, timeout=120):
    """Waits until the archive thread has really ended (not just emitted finished_all)."""
    deadline = time.monotonic() + timeout
    while gui.is_archiving() and time.monotonic() < deadline:
        spin(20)
    qapp.processEvents()


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
    wait_idle(qapp, gui)
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
@pytest.mark.parametrize("rescan", [False, True], ids=["right-after-run", "after-rescan"])
def test_overwrite_option_reprocesses_existing_results(qapp, make_gui, tmp_path, monkeypatch, rescan):
    from PySide6.QtWidgets import QMessageBox

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    shutil.copy(EXAMPLE_VIDEOS[0], src / "a.mp4")
    gui = make_gui()
    gui.cb_dry_run.setChecked(True)
    run_archive(qapp, gui, src, dst)
    # mtime is copied from the original on purpose, so compare the inode change time.
    first = (dst / "a_archived.mp4").stat().st_ctime_ns
    if rescan:
        gui.start_unified_scan()
        wait_for(gui.scan_worker.scan_finished)
    assert not gui.btn_run.isEnabled()
    if rescan:  # everything already archived: the summary points to the overwrite option
        assert "überschreiben" in gui.progress_text.text()

    gui.cb_overwrite.setChecked(True)
    qapp.processEvents()
    spin(300)
    assert gui.btn_run.isEnabled()
    assert "ersetzen" in gui.progress_text.text()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    gui.start_archiving()
    wait_idle(qapp, gui)
    assert gui.model.rows[0].status == "done"
    assert (dst / "a_archived.mp4").stat().st_ctime_ns != first
    assert not gui.btn_run.isEnabled() or gui.cb_overwrite.isChecked()


def test_failed_videos_are_retried_on_the_next_start(qapp, make_gui, tmp_path):
    from pathlib import Path
    from video_helper_tools.compressor.model import VideoRow

    gui = make_gui()
    gui.scan_items = [{'path': Path("/a/one.mp4"), 'dst_path': Path("/b/one_archived.mp4"), 'size': 1}]
    gui.model.reset([VideoRow(src=Path("/a/one.mp4"), dst=Path("/b/one_archived.mp4"), size=1, status="error")])
    assert [item['path'].name for item in gui.queue_items()] == ["one.mp4"]


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


def make_dummy_videos(folder, sizes):
    folder.mkdir(parents=True, exist_ok=True)
    for name, size in sizes.items():
        (folder / name).write_bytes(b"x" * size)


def queue_names(gui):
    return [item['path'].name for item in gui.queue_items()]


def test_processing_order_follows_table_sort_and_moved_up_videos(qapp, make_gui, tmp_path):
    from PySide6.QtCore import Qt
    from video_helper_tools.compressor.model import COL_FILE, COL_SIZE

    make_dummy_videos(tmp_path / "src", {"a.mp4": 3, "b.mp4": 1, "c.mp4": 2})
    gui = make_gui()
    scan(qapp, gui, tmp_path / "src", tmp_path / "dst")

    gui.table.sortByColumn(COL_SIZE, Qt.AscendingOrder)
    assert queue_names(gui) == ["b.mp4", "c.mp4", "a.mp4"]
    gui.table.sortByColumn(COL_FILE, Qt.DescendingOrder)
    assert queue_names(gui) == ["c.mp4", "b.mp4", "a.mp4"]

    gui.move_up(gui.model.row_for(tmp_path / "src" / "a.mp4"))
    assert queue_names(gui) == ["a.mp4", "c.mp4", "b.mp4"]
    gui.move_up(gui.model.row_for(tmp_path / "src" / "b.mp4"))
    assert queue_names(gui) == ["b.mp4", "a.mp4", "c.mp4"]
    assert gui.model.row_for(tmp_path / "src" / "a.mp4").moved_up


def test_reordering_never_requeues_a_started_video(tmp_path):
    from video_helper_tools.compressor.workers import ArchiveWorker

    items = [{'path': tmp_path / n, 'dst_path': tmp_path / "out" / n} for n in ("a.mp4", "b.mp4", "c.mp4")]
    worker = ArchiveWorker(tmp_path, tmp_path / "out", 1, items, {})
    assert worker.next_item()['path'].name == "a.mp4"
    # The GUI still sees a.mp4 as planned until its "running" status arrives.
    worker.set_queue(list(reversed(items)))
    assert [worker.next_item()['path'].name for _ in range(2)] == ["c.mp4", "b.mp4"]
    assert worker.next_item() is None


@requires_ffmpeg
@requires_exiftool
def test_resorting_during_a_run_changes_the_remaining_order(qapp, make_gui, tmp_path):
    from PySide6.QtCore import Qt
    from video_helper_tools.compressor.model import COL_FILE

    src = tmp_path / "src"
    src.mkdir()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        shutil.copy(EXAMPLE_VIDEOS[0], src / name)
    gui = make_gui()
    gui.cb_dry_run.setChecked(True)
    gui.combo_renderer.setCurrentIndex(0)
    gui.combo_preset.setCurrentText("ultrafast")
    gui.spin_jobs.setValue(1)
    scan(qapp, gui, src, tmp_path / "dst")
    gui.table.sortByColumn(COL_FILE, Qt.AscendingOrder)

    started = []
    gui.start_archiving()
    deadline = time.monotonic() + 120
    while gui.is_archiving() and time.monotonic() < deadline:
        spin(20)
        for row in gui.model.rows:
            if row.status in ("running", "done") and row.src.name not in started:
                started.append(row.src.name)
                if len(started) == 1:
                    gui.table.sortByColumn(COL_FILE, Qt.DescendingOrder)
    assert started == ["a.mp4", "c.mp4", "b.mp4"]
    assert {row.status for row in gui.model.rows} == {"done"}


def test_quality_guidance_is_visible_and_follows_the_value(qapp, make_gui):
    gui = make_gui()
    gui.show()
    gui.btn_advanced.setChecked(True)

    gui.combo_renderer.setCurrentIndex(0)
    gui.slider_crf.setValue(21)
    assert gui.crf_hint.isVisible() and "Sweet Spot" in gui.crf_hint.text()
    gui.slider_crf.setValue(18)
    assert "Visuell verlustfrei" in gui.crf_hint.text()

    gui.combo_renderer.setCurrentIndex(1)
    gui.slider_vt.setValue(70)
    assert gui.vt_hint.isVisible() and "fast visuell verlustfrei" in gui.vt_hint.text()
    gui.slider_vt.setValue(40)
    assert "sichtbare Verluste" in gui.vt_hint.text()


@pytest.fixture
def archived_row(qapp, make_gui, tmp_path, monkeypatch):
    """A GUI with one selected row whose original and result exist; confirmations answered Yes."""
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    from video_helper_tools.compressor.model import VideoRow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    src, dst = tmp_path / "src" / "clip.mov", tmp_path / "dst" / "clip_archived.mp4"
    src.parent.mkdir()
    dst.parent.mkdir()
    src.write_bytes(b"original")
    dst.write_bytes(b"result")
    gui = make_gui()
    gui.scan_items = [{'path': src, 'dst_path': dst, 'size': 8}]
    gui.model.reset([VideoRow(src=src, dst=dst, size=8, status="exists", out_size=6)])
    gui.table.selectRow(0)
    return gui, gui.model.rows[0], src, dst


def menu_texts(menu):
    return {a.text(): a.isEnabled() for a in menu.actions() if a.text()}


def test_file_actions_are_offered_for_archived_videos(archived_row):
    gui, row, _, _ = archived_row
    assert gui.btn_file_actions.isEnabled()
    assert menu_texts(gui.btn_file_actions.menu()) == {
        "Original durch Ergebnis ersetzen…": True, "Original und Ergebnis tauschen…": True,
        "Original löschen…": True, "Ergebnis löschen…": True,
    }
    context = menu_texts(gui.build_row_menu(row))
    assert context["Vergleichen"] and context["Original durch Ergebnis ersetzen…"]


def test_file_actions_are_locked_only_for_the_video_being_compressed(archived_row):
    gui, row, _, _ = archived_row
    gui.model.update(row.src, status="running")
    gui.update_detail_bar()
    assert not gui.btn_file_actions.isEnabled()
    assert not any(enabled for text, enabled in menu_texts(gui.build_row_menu(row)).items() if text.endswith("…"))


def test_swap_original_and_result(archived_row):
    gui, row, src, dst = archived_row
    gui.handle_compare_action("swap", row)
    assert (src.read_bytes(), dst.read_bytes()) == (b"result", b"original")


def test_replace_original_with_result(archived_row):
    gui, row, src, dst = archived_row
    gui.handle_compare_action("overwrite", row)
    assert not src.exists()
    assert (src.parent / dst.name).read_bytes() == b"result"


def test_delete_original_and_delete_result(archived_row):
    gui, row, src, dst = archived_row
    gui.handle_compare_action("del_comp", row)
    assert not dst.exists() and src.exists()
    assert gui.model.rows[0].status == "planned"  # can be compressed again
    dst.write_bytes(b"result")
    gui.model.update(row.src, out_size=6, status="exists")
    gui.handle_compare_action("del_orig", row)
    assert not src.exists() and dst.exists()


@requires_ffmpeg
@requires_exiftool
def test_settings_are_stored_in_the_result_and_shown_after_a_restart(qapp, make_gui, tmp_path):
    from video_helper_tools.compressor.model import COL_SETTINGS
    from video_helper_tools.compressor.utils import is_photos_compatible, read_compression_settings

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    shutil.copy(EXAMPLE_VIDEOS[0], src / "clip.mp4")
    gui = make_gui()
    gui.cb_dry_run.setChecked(True)
    gui.combo_res.setCurrentIndex(gui.combo_res.findData(1280))
    run_archive(qapp, gui, src, dst, crf=23)

    result = dst / "clip_archived.mp4"
    stored = read_compression_settings([result])[str(result)]
    assert stored == {"version": 1, "encoder": "libx265", "crf": 23, "preset": "ultrafast", "max_res": 1280,
                      "max_fps": 30, "copy_aac": True, "dry_run": True}
    assert is_photos_compatible(result)
    assert gui.model.rows[0].settings == stored  # shown right away

    restarted = make_gui()  # a fresh window, like after restarting the app
    scan(qapp, restarted, src, dst)
    restarted.settings_worker.wait(30_000)
    qapp.processEvents()
    assert restarted.model.rows[0].settings == stored
    shown = restarted.model.index(0, COL_SETTINGS).data()
    assert "CRF 23" in shown and "1280 px" in shown


@requires_ffmpeg
def test_results_made_before_settings_were_recorded_show_a_dash(qapp, make_gui, tmp_path):
    from video_helper_tools.compressor.model import COL_SETTINGS

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    shutil.copy(EXAMPLE_VIDEOS[0], src / "clip.mp4")
    shutil.copy(EXAMPLE_VIDEOS[0], dst / "clip_archived.mp4")  # old result without the tag
    gui = make_gui()
    scan(qapp, gui, src, dst)
    gui.settings_worker.wait(30_000)
    qapp.processEvents()
    assert gui.model.rows[0].settings is None
    assert gui.model.index(0, COL_SETTINGS).data() == "–"


def test_settings_summary_for_videotoolbox():
    from video_helper_tools.compressor.model import describe_settings

    text = describe_settings({"encoder": "videotoolbox", "vt_quality": 65, "max_res": None, "max_fps": 30, "copy_aac": True})
    assert text == "Mac-GPU · Qualität 65 · volle Auflösung · 30 fps"


def test_size_sorting_handles_files_larger_than_2_gb(qapp):
    # Regression: sizes above 2**31 bytes were compared as truncated 32-bit numbers.
    from pathlib import Path
    from PySide6.QtCore import Qt
    from video_helper_tools.compressor.model import COL_SIZE, VideoFilterProxy, VideoRow, VideoTableModel

    MB, GB = 1024 ** 2, 1024 ** 3
    sizes = [int(610.65 * MB), int(868.43 * MB), int(5.95 * GB), int(6.80 * GB), int(83.58 * MB), int(107.24 * MB)]
    model, proxy = VideoTableModel(), VideoFilterProxy()
    proxy.setSourceModel(model)
    model.reset([VideoRow(src=Path(f"/v/{i}.mp4"), dst=Path(f"/o/{i}.mp4"), size=s) for i, s in enumerate(sizes)])
    for order in (Qt.AscendingOrder, Qt.DescendingOrder):
        proxy.sort(COL_SIZE, order)
        shown = [proxy.index(r, COL_SIZE).data(Qt.UserRole + 1).size for r in range(proxy.rowCount())]
        assert shown == sorted(sizes, reverse=order == Qt.DescendingOrder)


def test_compare_is_locked_while_the_result_is_being_rewritten(archived_row):
    gui, row, _, _ = archived_row
    gui.model.update(row.src, status="running")
    assert not menu_texts(gui.build_row_menu(row))["Vergleichen"]
