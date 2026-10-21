from PySide6.QtWidgets import QMessageBox

from video_helper_core import dialogs


def test_confirm_button_is_locked_until_the_countdown_is_over(qapp):
    box = dialogs.DelayedConfirmBox(None, "Title", "Text", "Replace originals", seconds=5)
    assert not box.confirm_button.isEnabled() and box.confirm_button.text() == "Replace originals (5)"
    for expected in (4, 3, 2, 1):
        box.tick()
        assert not box.confirm_button.isEnabled() and box.confirm_button.text() == f"Replace originals ({expected})"
    box.tick()
    assert box.confirm_button.isEnabled() and box.confirm_button.text() == "Replace originals"
    assert not box.timer.isActive()
    box.tick()   # further ticks change nothing
    assert box.confirm_button.isEnabled()


def test_cancel_is_the_default_and_the_escape_button(qapp):
    box = dialogs.DelayedConfirmBox(None, "Title", "Text", "Go")
    assert box.defaultButton() is box.cancel_button and box.escapeButton() is box.cancel_button


def test_confirm_after_delay_is_false_unless_the_confirm_button_was_clicked(qapp, monkeypatch):
    assert dialogs.confirm_after_delay(None, "Title", "Text", "Go") is False   # exec is stubbed: nothing clicked

    def click_confirm(box):
        box.clickedButton = lambda: box.confirm_button
        return 0

    monkeypatch.setattr(QMessageBox, "exec", click_confirm)
    assert dialogs.confirm_after_delay(None, "Title", "Text", "Go") is True


def test_test_audio_output_is_silent_but_remembers_volume_and_mute(qapp):
    from PySide6.QtMultimedia import QAudioOutput

    output = QAudioOutput()
    output.setVolume(0.3)
    assert output.volume() == 0.3 and not output.isMuted()
    output.setMuted(True)
    assert output.isMuted()
    # what the sound system gets is silence
    assert QAudioOutput.__mro__[1].volume(output) == 0.0 and QAudioOutput.__mro__[1].isMuted(output)
