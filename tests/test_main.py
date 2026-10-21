import sys

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent


def test_main_starts_the_window_and_applies_the_macos_path_fix(qapp, monkeypatch):
    import main

    shown = []
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(sys, "platform", "darwin")
    class FakeApplication:
        def __new__(cls, argv):
            return qapp

        instance = staticmethod(lambda: qapp)

    monkeypatch.setattr(main, "QApplication", FakeApplication)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    monkeypatch.setattr(main.VideoHelperToolsSuite, "show", lambda self: shown.append(self))
    monkeypatch.setenv("PATH", "/usr/bin")
    with pytest.raises(SystemExit) as stop:
        main.main()
    assert stop.value.code == 0 and len(shown) == 1
    import os
    assert "/opt/homebrew/bin" in os.environ["PATH"].split(os.pathsep)
    shown[0].close()


def test_main_hands_over_to_the_whisper_server(monkeypatch):
    import main
    from video_helper_tools.transcriber import run_minimal_whisper_server as server

    received = []
    monkeypatch.setattr(sys, "argv", ["main.py", main.WHISPER_SERVER_FLAG, "--port", "1"])
    monkeypatch.setattr(server, "main", lambda: received.append(list(sys.argv)))
    main.main()
    assert received == [["main.py", "--port", "1"]]


def test_title_bar_double_click_toggles_maximized(qapp):
    import main

    window = main.VideoHelperToolsSuite()
    bar = window.findChild(main.TitleBar)
    event = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    calls = []
    window.showMaximized = lambda: calls.append("max")
    window.showNormal = lambda: calls.append("normal")
    bar.mouseDoubleClickEvent(event)
    assert calls == ["max"]
    window.close()


def test_about_dialog_names_the_app(qapp, monkeypatch):
    import main
    from PySide6.QtWidgets import QMessageBox

    texts = []
    monkeypatch.setattr(QMessageBox, "setText", lambda self, text: texts.append(text))
    window = main.VideoHelperToolsSuite()
    window.show_about()
    assert any("Video Helper Tools" in t for t in texts)
    window.close()
