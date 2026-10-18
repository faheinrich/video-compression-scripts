import json
import shutil
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import spin, wait_for


# --- rsync GUI -------------------------------------------------------------------------------------------------------

@pytest.fixture
def rsync(qapp):
    from video_helper_tools.rsync_gui.gui import RsyncSyncGUI

    gui = RsyncSyncGUI()
    yield gui
    gui.shutdown()


def confirm(monkeypatch, answer=QMessageBox.Yes):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answer))


def test_rsync_needs_both_folders_and_an_existing_source(rsync, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    rsync.start_sync()
    rsync.src_edit.setText(str(tmp_path / "missing"))
    rsync.tgt_edit.setText(str(tmp_path / "target"))
    rsync.start_sync()
    assert len(warnings) == 2 and not rsync.is_busy()


def test_declining_the_confirmation_starts_nothing(rsync, tmp_path, monkeypatch):
    confirm(monkeypatch, QMessageBox.No)
    rsync.src_edit.setText(str(tmp_path))
    rsync.tgt_edit.setText(str(tmp_path / "t"))
    rsync.start_sync()
    assert not rsync.is_busy() and rsync.log_output.toPlainText() == ""


@pytest.mark.skipif(not shutil.which("rsync"), reason="rsync not installed")
def test_rsync_mirrors_a_folder_and_reports_progress(rsync, tmp_path, monkeypatch):
    confirm(monkeypatch)
    src, tgt = tmp_path / "src", tmp_path / "tgt"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("a")
    (src / "sub" / "b.txt").write_text("b")
    tgt.mkdir()
    (tgt / "stale.txt").write_text("deleted by --del")
    rsync.src_edit.setText(str(src))
    rsync.tgt_edit.setText(str(tgt))

    rsync.start_sync()
    assert rsync.is_busy() and rsync.sync_btn.property("mode") == "stop"
    wait_for(rsync.process.finished)
    spin(50)

    assert (tgt / "a.txt").read_text() == "a" and (tgt / "sub" / "b.txt").exists() and not (tgt / "stale.txt").exists()
    assert rsync.values["files"].text() == "2"
    assert rsync.progress.value() == 100 and rsync.sync_btn.property("mode") == "start"
    assert "rsync -av --del" in rsync.log_output.toPlainText()


@pytest.mark.skipif(not shutil.which("rsync"), reason="rsync not installed")
def test_rsync_error_is_shown(rsync, tmp_path, monkeypatch):
    confirm(monkeypatch)
    rsync.src_edit.setText(str(tmp_path))
    rsync.tgt_edit.setText("/proc/definitely/not/writable")
    rsync.start_sync()
    wait_for(rsync.process.finished)
    spin(50)
    assert rsync.values["status"].property("tone") == "warn"


@pytest.mark.skipif(not shutil.which("rsync"), reason="rsync not installed")
def test_stop_kills_a_running_sync(rsync, tmp_path, monkeypatch):
    confirm(monkeypatch)
    monkeypatch.setattr("video_helper_tools.rsync_gui.gui.RSYNC_ARGS", ["-a", "--bwlimit=1"])
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.bin").write_bytes(b"0" * 4_000_000)
    rsync.src_edit.setText(str(src))
    rsync.tgt_edit.setText(str(tmp_path / "tgt"))
    rsync.toggle_sync()
    spin(300)
    rsync.toggle_sync()  # second click stops
    wait_for(rsync.process.finished, 10_000)
    assert not rsync.is_busy()


def test_line_parsing_counts_files_but_not_status_lines(rsync):
    for line in ["sending incremental file list", "photos/", "a.jpg", "  45%  1.2MB/s", "b.jpg", "sent 10 bytes",
                 "total size is 5", "deleting old.jpg", "Transfer starting: 4 files", ""]:
        rsync.handle_line(line)
    assert rsync.files_done == 2 and rsync.progress.value() == 45


def test_log_escapes_html_in_file_names(rsync):
    rsync.append_log("<b>evil</b>.mp4")
    assert "<b>evil</b>.mp4" in rsync.log_output.toPlainText()


def test_browse_buttons_fill_the_fields(rsync, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    rsync.browse_source()
    rsync.browse_target()
    assert rsync.src_edit.text() == rsync.tgt_edit.text() == str(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    rsync.src_edit.clear()
    rsync.browse_source()
    assert rsync.src_edit.text() == ""


def test_elapsed_time_format(rsync):
    import time

    rsync.started_at = time.monotonic() - 3725
    rsync.update_elapsed()
    assert rsync.values["elapsed"].text() == "1:02:05"
    rsync.started_at = time.monotonic() - 65
    rsync.update_elapsed()
    assert rsync.values["elapsed"].text() == "1:05"


# --- sync info dialog ------------------------------------------------------------------------------------------------

def test_info_dialog_renders_with_and_without_results(qapp, monkeypatch, tmp_path):
    from video_helper_tools.sync import info

    assert info.SyncInfoDialog().windowTitle()
    monkeypatch.setattr(info, "RESULTS_FILE", tmp_path / "missing.json")
    assert info.load_results() is None
    assert "<table" not in info.build_html()
    info.SyncInfoDialog()


def test_info_results_table_colours_by_share_of_correct_cases():
    from video_helper_tools.sync.info import results_table

    data = {"references": {
        "video1.mp4": {"cases": {"clean": {"ok": 10, "total": 10}, "noisy": {"ok": 6, "total": 10}, "hard": {"ok": 1, "total": 10}}},
        "video2.mp4": {"cases": {"clean": {"ok": 10, "total": 10}}},
    }}
    table = results_table(data)
    assert "#23875a" in table and "#b7701a" in table and "#c63f35" in table and "–" in table
    assert results_table({"references": {}}) == ""


def test_info_reads_a_results_file(monkeypatch, tmp_path):
    from video_helper_tools.sync import info

    path = tmp_path / "r.json"
    path.write_text(json.dumps({"tolerance_ms": 5, "references": {"video1.mp4": {"cases": {"x": {"ok": 1, "total": 1}}}}}))
    monkeypatch.setattr(info, "RESULTS_FILE", path)
    assert "5 ms" in info.build_html() and "<table" in info.build_html()
    path.write_text("not json")
    assert info.load_results() is None


# --- app data paths --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("platform,env,fragment", [
    ("linux", {"XDG_CONFIG_HOME": "XDG"}, "video-helper-tools"),
    ("linux", {}, ".config"),
    ("darwin", {}, "Application Support"),
    ("win32", {"APPDATA": "WIN"}, "Video Helper Tools"),
])
def test_base_dir_per_platform(monkeypatch, tmp_path, platform, env, fragment):
    from video_helper_tools.core import paths

    monkeypatch.delenv(paths.HOME_OVERRIDE_ENV)
    for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(tmp_path / value))
    monkeypatch.setattr(paths.sys, "platform", platform)
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert fragment in str(paths._base_dir("config"))
    assert str(paths._base_dir("cache")) != str(paths._base_dir("config"))


def test_override_redirects_everything(tmp_path):
    from video_helper_tools.core import paths

    assert paths.settings_file().parent == tmp_path / "app-home" / "config"
    assert paths.thumbnail_dir() == tmp_path / "app-home" / "cache" / "thumbnails"
