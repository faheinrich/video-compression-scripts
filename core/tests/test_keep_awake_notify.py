import subprocess
import sys

from video_helper_core import keep_awake, notify


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_macos_uses_caffeinate_tied_to_this_process(monkeypatch):
    commands = []
    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.subprocess, "Popen", lambda cmd, **kw: commands.append(cmd) or FakeProcess())
    awake = keep_awake.KeepAwake()
    awake.start()
    awake.start()   # a second start changes nothing
    assert len(commands) == 1 and commands[0][:2] == ["caffeinate", "-i"] and "-w" in commands[0]
    process = awake.process
    awake.stop()
    awake.stop()
    assert process.terminated and awake.process is None and not awake.active


def test_linux_uses_systemd_inhibit_when_available(monkeypatch):
    commands = []
    monkeypatch.setattr(keep_awake.sys, "platform", "linux")
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: "/usr/bin/systemd-inhibit")
    monkeypatch.setattr(keep_awake.subprocess, "Popen", lambda cmd, **kw: commands.append(cmd) or FakeProcess())
    awake = keep_awake.KeepAwake(reason="testing")
    awake.start()
    assert commands[0][0] == "systemd-inhibit" and "--why=testing" in commands[0]
    awake.stop()


def test_linux_without_systemd_inhibit_does_nothing(monkeypatch):
    monkeypatch.setattr(keep_awake.sys, "platform", "linux")
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: None)
    awake = keep_awake.KeepAwake()
    awake.start()
    assert awake.process is None
    awake.stop()


def test_a_missing_program_is_not_an_error(monkeypatch):
    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.subprocess, "Popen", missing)
    awake = keep_awake.KeepAwake()
    awake.start()
    assert awake.process is None
    awake.stop()


def test_no_notification_while_the_window_is_in_front(qapp, monkeypatch):
    class Window:
        def isActiveWindow(self):
            return True

    monkeypatch.setattr(notify.QApplication, "alert", lambda *a: (_ for _ in ()).throw(AssertionError("no alert")))
    assert notify.notify(Window(), "title", "text") is False


def test_background_window_gets_dock_alert_and_a_message(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget

    alerts, messages = [], []

    class Tray:
        def __init__(self, icon, parent):
            pass

        def show(self):
            pass

        def hide(self):
            pass

        def deleteLater(self):
            pass

        def showMessage(self, title, text, icon, ms):
            messages.append((title, text))

    window = QWidget()   # never shown, so not the active window
    monkeypatch.setattr(notify.QApplication, "alert", lambda widget, ms: alerts.append(widget))
    monkeypatch.setattr(notify, "QSystemTrayIcon", Tray)
    Tray.isSystemTrayAvailable = staticmethod(lambda: True)
    assert notify.notify(window, "Archive Helper", "3 of 3 finished") is True
    assert alerts == [window] and messages == [("Archive Helper", "3 of 3 finished")]


def test_background_window_without_tray_still_alerts(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget

    alerts = []
    window = QWidget()
    monkeypatch.setattr(notify.QApplication, "alert", lambda widget, ms: alerts.append(widget))
    monkeypatch.setattr(notify.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    assert notify.notify(window, "t", "m") is True and alerts == [window]
