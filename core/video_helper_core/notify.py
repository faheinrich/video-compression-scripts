"""Tells the user a long job is done when they are looking at something else."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

_trays = []   # keeps the icon alive while its message is shown


def notify(window, title, message):
    """Bounces the Dock icon / flashes the taskbar and shows a system notification, unless the window is in front.
    Returns whether the user was notified."""
    if window.isActiveWindow():
        return False
    QApplication.alert(window, 0)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(window.windowIcon(), window)
        tray.show()
        tray.showMessage(title, message, window.windowIcon(), 8000)
        _trays.append(tray)

        def cleanup():
            tray.hide()
            tray.deleteLater()
            if tray in _trays:
                _trays.remove(tray)

        QTimer.singleShot(12000, cleanup)
    return True
