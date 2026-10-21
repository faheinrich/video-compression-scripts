from pathlib import Path

from video_helper_core.i18n import tr
from video_helper_core.shell import AppSpec, SuiteWindow, Tool, load_settings, resource_dir, run, saved_language  # noqa: F401

from . import __version__
from .compressor.gui import ArchiverGUI
from .rsync_gui.gui import RsyncSyncGUI

APP_ROOT = Path(__file__).resolve().parent.parent

SPEC = AppSpec(
    name="Archive Helper",
    version=__version__,
    about=lambda version: tr("<h2>Archive Helper</h2><p>Compress videos for the archive and back up folders with rsync.</p><p>Version: {version}</p>", version=version),
    tools=[
        Tool("compressor", lambda: tr("Compress & Archive"), "tool-compressor.png", ArchiverGUI),
        Tool("rsync", lambda: tr("Backup (rsync)"), "tool-backup.png", RsyncSyncGUI),
    ],
    resources=resource_dir(APP_ROOT),
    tag_prefix="archive-v",
    busy_message=lambda: tr("Please stop running jobs first (compression or rsync), then change the language."),
)


class ArchiveHelperWindow(SuiteWindow):
    def __init__(self):
        super().__init__(SPEC)

    @property
    def compressor_tab(self):
        return self.tools.get("compressor")


def main():
    run(SPEC)
