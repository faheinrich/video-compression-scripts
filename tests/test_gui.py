from PySide6.QtCore import QUrl

from conftest import EXAMPLE_VIDEOS, requires_ffmpeg, spin


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


@requires_ffmpeg
def test_compare_dialog_shows_rotated_clip_upright(qapp, tmp_path):
    """Portrait phone clips carry a display matrix; Qt 6 applies it, the app must not rotate again."""
    import subprocess
    from PySide6.QtGui import QColor, QImage, QPainter
    from video_helper_tools.compressor.widgets import CompareVideoDialog

    rotated = tmp_path / "portrait.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "90", "-i", str(EXAMPLE_VIDEOS[0]), "-c", "copy", str(rotated)],
        check=True,
    )

    dialog = CompareVideoDialog(rotated, rotated)
    dialog.show()
    spin(2000)
    dialog.player_orig.pause()

    magenta = QColor(255, 0, 255)
    item = dialog.view_orig.video_item
    scene = dialog.view_orig.scene
    scene.setBackgroundBrush(magenta)
    rect = item.boundingRect()
    image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_RGB32)
    image.fill(magenta)
    painter = QPainter(image)
    scene.render(painter, image.rect(), item.mapRectToScene(rect))
    painter.end()
    dialog.reject()

    def is_background(x, y):
        c = image.pixelColor(x, y)
        return c.red() > 240 and c.green() < 20 and c.blue() > 240

    height = image.height()
    # Upright portrait video inside the landscape frame: empty side bars, content in the middle.
    assert all(is_background(3, y) for y in range(0, height, 10))
    assert not any(is_background(image.width() // 2, y) for y in range(0, height, 10))


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


def open_compare_dialog(qapp, wait_ms=2000):
    from video_helper_tools.compressor.widgets import CompareVideoDialog

    dialog = CompareVideoDialog(EXAMPLE_VIDEOS[0], EXAMPLE_VIDEOS[0])
    dialog.show()
    spin(wait_ms)
    return dialog


def test_compare_player_pulls_the_compressed_video_back_in_sync(qapp):
    from video_helper_tools.compressor.widgets import SYNC_TOLERANCE_MS

    dialog = open_compare_dialog(qapp)
    assert dialog.is_playing()
    assert dialog.audio_comp.isMuted() and not dialog.audio_orig.isMuted()
    # Simulate the faster-decoding file running ahead.
    dialog.player_comp.setPosition(dialog.player_orig.position() + 3000)
    spin(700)
    drift = abs(dialog.player_comp.position() - dialog.player_orig.position())
    dialog.reject()
    assert drift <= SYNC_TOLERANCE_MS + 250  # both keep playing between the checks


def test_compare_player_scrubber_and_restart(qapp):
    dialog = open_compare_dialog(qapp)
    assert dialog.slider_pos.maximum() == dialog.player_orig.duration() > 0
    assert dialog.lbl_time.text().endswith("/ 0:26")

    dialog.pause()
    dialog.slider_pos.setValue(15000)  # like a user click/drag on the timeline
    spin(500)
    for player in (dialog.player_orig, dialog.player_comp):
        assert abs(player.position() - 15000) < 300
    assert dialog.lbl_time.text().startswith("0:15")

    dialog.restart()
    spin(500)
    assert dialog.is_playing()
    assert dialog.player_orig.position() < 3000
    dialog.reject()


def test_enter_does_not_trigger_a_dialog_button(qapp):
    from PySide6.QtWidgets import QPushButton

    dialog = open_compare_dialog(qapp, wait_ms=300)
    assert not any(b.isDefault() or b.autoDefault() for b in dialog.findChildren(QPushButton))
    dialog.reject()


def test_player_error_names_side_file_and_format(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from video_helper_tools.compressor.widgets import CompareVideoDialog

    broken = tmp_path / "broken_archived.mp4"
    broken.write_bytes(EXAMPLE_VIDEOS[0].read_bytes()[:200_000])  # like a half-written result
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda parent, title, text: shown.append(text)))
    dialog = CompareVideoDialog(EXAMPLE_VIDEOS[0], broken)
    dialog.show()
    spin(3000)
    dialog.reject()
    assert len(shown) == 1
    assert "komprimierte Version" in shown[0] and "broken_archived.mp4" in shown[0] and "Format:" in shown[0]
