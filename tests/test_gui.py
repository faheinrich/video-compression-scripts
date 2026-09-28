from PySide6.QtCore import QUrl

from conftest import EXAMPLE_VIDEOS, spin


def test_suite_opens_every_tool_and_switches_language(qapp, monkeypatch):
    import sys
    import main

    # PySide6 only reports exceptions raised inside slots via sys.excepthook.
    slot_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: slot_errors.append(exc))

    window = main.VideoHelperToolsSuite()
    window.show()
    for show in (window.show_compressor, window.show_sync, window.show_transcribe, window.show_rsync, window.show_landing):
        show()
        qapp.processEvents()

    # Regression: switching language used to abort the app from inside a Qt slot.
    for index in range(window.landing_page.lang_combo.count()):
        window.landing_page.lang_combo.setCurrentIndex(index)
        qapp.processEvents()
    window.close()
    assert slot_errors == []


def test_compare_dialog_plays_both_videos(qapp):
    from PySide6.QtMultimedia import QMediaPlayer
    from video_helper_tools.compressor.widgets import CompareVideoDialog

    dialog = CompareVideoDialog(EXAMPLE_VIDEOS[0], EXAMPLE_VIDEOS[1])
    dialog.show()
    spin(2000)

    for player in (dialog.player_orig, dialog.player_comp):
        assert player.error() == QMediaPlayer.Error.NoError
        assert player.duration() > 0
        assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    dialog.toggle_play()
    assert dialog.player_orig.playbackState() == QMediaPlayer.PlaybackState.PausedState

    dialog.reject()
    assert dialog.player_orig.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    assert dialog.player_orig.source().isEmpty()


def test_sync_tool_volume_and_mute(qapp):
    from video_helper_tools.sync.gui import VideoSyncGUI

    sync = VideoSyncGUI()
    sync.player1.setSource(QUrl.fromLocalFile(str(EXAMPLE_VIDEOS[0])))
    spin(1500)
    assert sync.player1.duration() > 0

    sync.set_volume(30)
    assert sync.audio1.volume() == sync.audio2.volume()
    assert abs(sync.audio1.volume() - 0.30) < 0.01

    sync.toggle_mute()
    assert sync.audio1.isMuted() and sync.audio2.isMuted()

    sync.reset_all()
    assert sync.player1.source().isEmpty()
