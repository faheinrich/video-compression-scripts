import os
import sys

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMessageBox

from analysis_helper import __version__, app


def test_main_starts_the_window_and_applies_the_macos_path_fix(qapp, monkeypatch):
    from video_helper_core import shell

    shown = []
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(sys, "platform", "darwin")

    class FakeApplication:
        def __new__(cls, argv):
            return qapp

        instance = staticmethod(lambda: qapp)

    monkeypatch.setattr(shell, "QApplication", FakeApplication)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    monkeypatch.setattr(shell.SuiteWindow, "show", lambda self: shown.append(self))
    monkeypatch.setenv("PATH", "/usr/bin")
    with pytest.raises(SystemExit) as stop:
        app.main()
    assert stop.value.code == 0 and len(shown) == 1
    assert "/opt/homebrew/bin" in os.environ["PATH"].split(os.pathsep)
    shown[0].close()


def test_title_bar_double_click_toggles_maximized(qapp):
    from video_helper_core.shell import TitleBar

    window = app.AnalysisHelperWindow()
    bar = window.findChild(TitleBar)
    event = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    calls = []
    window.showMaximized = lambda: calls.append("max")
    window.showNormal = lambda: calls.append("normal")
    bar.mouseDoubleClickEvent(event)
    assert calls == ["max"]
    window.close()


def test_about_dialog_names_the_app_and_version(qapp, monkeypatch):
    texts = []
    monkeypatch.setattr(QMessageBox, "setText", lambda self, text: texts.append(text))
    window = app.AnalysisHelperWindow()
    window.show_about()
    assert any("Analysis Helper" in t and __version__ in t for t in texts)
    window.close()


def test_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    declared = tomllib.loads((Path(app.__file__).parents[1] / "pyproject.toml").read_text())["project"]["version"]
    assert __version__ == declared


def test_suite_opens_every_tool_and_switches_language(qapp, monkeypatch):
    # PySide6 only reports exceptions raised inside slots via sys.excepthook.
    slot_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: slot_errors.append(exc))

    window = app.AnalysisHelperWindow()
    window.show()
    for tool in app.SPEC.tools:
        window.show_tool(tool.key)
        qapp.processEvents()
    window.show_landing()

    # Regression: switching language used to abort the app from inside a Qt slot.
    for index in range(window.landing_page.lang_combo.count()):
        window.landing_page.lang_combo.setCurrentIndex(index)
        qapp.processEvents()
    window.close()
    assert slot_errors == []


def test_language_change_is_refused_while_a_job_runs(qapp, monkeypatch):
    window = app.AnalysisHelperWindow()
    window.show_tool("transcriber")
    monkeypatch.setattr(window.tools["transcriber"], "is_busy", lambda: True)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    combo = window.landing_page.lang_combo
    combo.setCurrentIndex(combo.findData("en"))
    assert shown and combo.currentData() == "de"
    monkeypatch.undo()   # a busy tool would make close() ask whether to quit
    window.close()


def test_whisper_server_flag_starts_the_server_instead_of_the_window(monkeypatch):
    from analysis_helper.transcriber import WHISPER_SERVER_FLAG, run_minimal_whisper_server as server

    received = []
    monkeypatch.setattr(sys, "argv", ["main.py", WHISPER_SERVER_FLAG, "--port", "1"])
    monkeypatch.setattr(server, "main", lambda: received.append(list(sys.argv)))
    app.main()
    assert received == [["main.py", "--port", "1"]]
