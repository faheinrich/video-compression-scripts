import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from conftest import requires_ffmpeg, spin
from test_sync_core import duration, make_video

pytestmark = requires_ffmpeg


@pytest.fixture
def sync(qapp):
    from video_helper_tools.sync.gui import VideoSyncGUI

    gui = VideoSyncGUI()
    yield gui
    gui.reset_all()


@pytest.fixture
def pair(tmp_path):
    """Video 2 starts its sound 1.5 s later than video 1."""
    return make_video(tmp_path / "first.mp4", 7), make_video(tmp_path / "second.mp4", 7, delay_ms=1500)


def load(sync, pair):
    sync.vid1_edit.setText(str(pair[0]))
    sync.vid2_edit.setText(str(pair[1]))
    sync.load_videos()
    spin(800)


def test_loading_without_both_paths_does_nothing(sync, pair):
    sync.vid1_edit.setText(str(pair[0]))
    sync.load_videos()
    assert sync.vid1_path is None
    sync.calculate_sync()
    assert sync.shift == 0


def test_loading_builds_waveforms_and_shows_them(sync, pair):
    load(sync, pair)
    assert all(pixmap is not None and not pixmap.isNull() for pixmap in sync.wf_pixmaps)
    assert sync.wf_pixmaps[0].width() == pytest.approx(400, abs=15)  # 100 px per second, 4 s
    sync.update_duration()
    assert sync.duration > 0 and sync.scrub_slider.maximum() == sync.duration
    sync.waveform_label1.resize(300, 60)
    for pos in (0, 1500, 3900, 99999):  # also positions beyond the waveform
        sync.update_waveforms(pos)
    assert sync.waveform_label1.pixmap() is not None


def test_calculate_sync_finds_the_delay(sync, pair):
    load(sync, pair)
    sync.calculate_sync()
    assert sync.shift == pytest.approx(-1.5, abs=0.02)
    assert "-1.50" in sync.shift_label.text() or "-1,50" in sync.shift_label.text()
    sync.adjust_shift(0.1)
    assert sync.shift == pytest.approx(-1.4, abs=0.02)


@pytest.mark.parametrize("shift", [1.2, -1.2])
def test_scrubbing_positions_both_players_with_the_shift(sync, pair, shift):
    load(sync, pair)
    sync.shift = shift
    sync.scrub_start()
    assert sync.is_scrubbing
    sync.scrub_slider.setValue(1000)
    sync.scrub_stop()
    spin(400)
    assert not sync.is_scrubbing
    first, second = sync.player1.position(), sync.player2.position()
    assert abs((first - second) - int(shift * 1000)) < 300


def test_play_sync_starts_both_and_stop_ends_them(sync, pair):
    from PySide6.QtMultimedia import QMediaPlayer

    load(sync, pair)
    sync.shift = -0.5
    sync.play_sync()
    spin(800)
    assert sync.player1.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    sync.update_slider()
    assert sync.scrub_slider.value() >= 0
    sync.shift = 0.5
    sync.play_sync()
    spin(500)
    sync.update_slider()
    sync.stop_playback()
    assert sync.player2.playbackState() == QMediaPlayer.PlaybackState.StoppedState


@pytest.mark.parametrize("shift,trimmed", [(-1.5, "second"), (1.5, "first")])
def test_save_trims_the_video_that_starts_earlier(sync, pair, tmp_path, monkeypatch, shift, trimmed):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    load(sync, pair)
    sync.shift = shift
    target = tmp_path / "out" / "deeper"
    sync.target_edit.setText(str(target))
    sync.save_synced_videos()

    first, second = target / "first_sync.mp4", target / "second_sync.mp4"
    assert first.exists() and second.exists() and shown
    untouched, cut = (first, second) if trimmed == "second" else (second, first)
    original = {"first": pair[0], "second": pair[1]}[trimmed]
    assert duration(cut) == pytest.approx(duration(original) - 1.5, abs=0.7)
    assert untouched.stat().st_size > 0


def test_save_asks_for_videos_and_folder_first(sync, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    sync.save_synced_videos()
    assert len(warned) == 1


def test_browse_dialogs_fill_the_fields(sync, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(tmp_path / "v.mp4"), "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    sync.browse_file(sync.vid1_edit)
    sync.browse_folder()
    assert sync.vid1_edit.text().endswith("v.mp4") and sync.target_edit.text() == str(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    sync.vid2_edit.clear()
    sync.browse_file(sync.vid2_edit)
    sync.target_edit.clear()
    sync.browse_folder()
    assert sync.vid2_edit.text() == "" and sync.target_edit.text() == ""


def test_info_button_opens_the_dialog(sync, monkeypatch):
    from video_helper_tools.sync import gui as sync_gui

    opened = []
    monkeypatch.setattr(sync_gui.SyncInfoDialog, "exec", lambda self: opened.append(self) or 0)
    sync.show_info()
    assert len(opened) == 1


def test_mute_button_label_toggles(sync):
    before = sync.mute_btn.text()
    sync.toggle_mute()
    assert sync.mute_btn.text() != before
    sync.toggle_mute()
    assert sync.mute_btn.text() == before


def test_reset_clears_everything(sync, pair):
    load(sync, pair)
    sync.shift = 2
    sync.reset_all()
    assert sync.shift == 0 and sync.vid1_edit.text() == "" and sync.vid1_path is None and sync.scrub_slider.value() == 0
