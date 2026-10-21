import sys
from pathlib import Path

from video_helper_core.i18n import tr
from video_helper_core.shell import AppSpec, SuiteWindow, Tool, load_settings, resource_dir, run, saved_language  # noqa: F401

from . import __version__
from .sync.gui import VideoSyncGUI
from .transcriber import WHISPER_SERVER_FLAG
from .transcriber.gui import WhisperGui

APP_ROOT = Path(__file__).resolve().parent.parent

SPEC = AppSpec(
    name="Analysis Helper",
    version=__version__,
    about=lambda version: tr("<h2>Analysis Helper</h2><p>Synchronise videos and transcribe them with Whisper.</p><p>Version: {version}</p>", version=version),
    tools=[
        Tool("sync", lambda: tr("Sync Videos"), "tool-sync.png", VideoSyncGUI),
        Tool("transcriber", lambda: tr("Transcribe Audio"), "tool-transcribe.png", WhisperGui),
    ],
    resources=resource_dir(APP_ROOT),
    busy_message=lambda: tr("Please stop running jobs first (transcription or the local Whisper server), then change the language."),
)


class AnalysisHelperWindow(SuiteWindow):
    def __init__(self):
        super().__init__(SPEC)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == WHISPER_SERVER_FLAG:
        # A frozen app cannot run `python -m ...`, so the local Whisper server is this app started with a flag.
        from .transcriber.run_minimal_whisper_server import main as run_whisper_server
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        run_whisper_server()
        return
    run(SPEC)
