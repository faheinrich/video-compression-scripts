"""Dialogs shared by the apps."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from video_helper_core.i18n import tr


class DelayedConfirmBox(QMessageBox):
    """A warning whose confirm button only works after a few seconds, so it cannot be clicked by reflex.
    Cancel is the default button."""

    def __init__(self, parent, title, text, confirm_text, seconds=5):
        super().__init__(parent)
        self.setIcon(QMessageBox.Warning)
        self.setWindowTitle(title)
        self.setText(text)
        self.confirm_text = confirm_text
        self.remaining = seconds
        self.confirm_button = self.addButton(confirm_text, QMessageBox.AcceptRole)
        self.cancel_button = self.addButton(tr("Cancel"), QMessageBox.RejectRole)
        self.setDefaultButton(self.cancel_button)
        self.setEscapeButton(self.cancel_button)
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self.tick)
        self.update_button()
        self.timer.start()

    def update_button(self):
        waiting = self.remaining > 0
        self.confirm_button.setEnabled(not waiting)
        self.confirm_button.setText(f"{self.confirm_text} ({self.remaining})" if waiting else self.confirm_text)

    def tick(self):
        if self.remaining > 0:
            self.remaining -= 1
            self.update_button()
        if self.remaining == 0:
            self.timer.stop()


def confirm_after_delay(parent, title, text, confirm_text, seconds=5):
    """True only if the user waited and then chose the confirm button."""
    box = DelayedConfirmBox(parent, title, text, confirm_text, seconds)
    box.exec()
    return box.clickedButton() is box.confirm_button
