import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_VIDEOS = [REPO_ROOT / "example_resoucres" / "video1.mp4", REPO_ROOT / "example_resoucres" / "video2.mp4"]

requires_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)
requires_exiftool = pytest.mark.skipif(not shutil.which("exiftool"), reason="exiftool not installed")


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    # The app reads/writes settings.json and thumbnails/ relative to the cwd.
    monkeypatch.chdir(tmp_path)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))


def spin(ms):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(signal, timeout_ms=120_000):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
