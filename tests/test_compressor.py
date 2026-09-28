import shutil

from conftest import EXAMPLE_VIDEOS, requires_exiftool, requires_ffmpeg, wait_for


@requires_ffmpeg
@requires_exiftool
def test_archive_run_end_to_end(qapp, tmp_path):
    from video_helper_tools.compressor.gui import ArchiverGUI

    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    # Same file name in two folders must not collide.
    shutil.copy(EXAMPLE_VIDEOS[0], src / "a.mp4")
    shutil.copy(EXAMPLE_VIDEOS[1], src / "sub" / "a.mp4")

    gui = ArchiverGUI()
    gui.txt_src.setText(str(src))
    gui.txt_dst.setText(str(dst))
    gui.combo_renderer.setCurrentIndex(0)
    gui.combo_preset.setCurrentText("ultrafast")
    gui.spin_jobs.setValue(2)

    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    qapp.processEvents()
    assert len(gui.video_data_list) == 2

    gui.start_archiving()
    wait_for(gui.worker.finished_all)
    qapp.processEvents()

    outputs = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*.mp4"))
    assert outputs == ["a_archived.mp4", "sub/a_archived.mp4"]

    # Savings totals must match the real file sizes (each source counted once).
    assert gui.total_src_bytes == sum(p.stat().st_size for p in src.rglob("*.mp4"))
    assert gui.total_dst_bytes == sum(p.stat().st_size for p in dst.rglob("*.mp4"))

    # A second scan finds both outputs and plans nothing.
    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    assert gui.video_data_list == []
