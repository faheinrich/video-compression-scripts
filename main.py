import sys
import os
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QMessageBox
from PySide6.QtGui import QIcon, QFontDatabase, QFont, QPixmap
from PySide6.QtCore import Qt, QSize

from video_helper_tools.compressor.gui import ArchiverGUI
from video_helper_tools.sync.gui import VideoSyncGUI
from video_helper_tools.transcriber.gui import WhisperGui
from video_helper_tools.rsync_gui.gui import RsyncSyncGUI
from video_helper_tools.transcriber import WHISPER_SERVER_FLAG
from video_helper_tools.core.i18n import LANGUAGES, DEFAULT_LANGUAGE, current_language, set_language, tr
from video_helper_tools.core.paths import settings_file

BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

TOOLS = {
    "compressor": ArchiverGUI,
    "sync": VideoSyncGUI,
    "transcriber": WhisperGui,
    "rsync": RsyncSyncGUI,
}


def load_settings():
    path = settings_file()
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def saved_language(settings):
    global_settings = settings.get('global', {})
    if 'language' in global_settings:
        return global_settings['language']
    # Older versions stored an index into ["Deutsch", "English", ...].
    legacy = {0: "de", 1: "en"}
    return legacy.get(global_settings.get('language_index'), DEFAULT_LANGUAGE)


class LandingPage(QWidget):
    def __init__(self, open_tool):
        super().__init__()
        self.open_tool = open_tool
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        top_bar.addWidget(QLabel(tr("Language:")))
        self.lang_combo = QComboBox()
        for code, name in LANGUAGES:
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(self.lang_combo.findData(current_language()))
        top_bar.addWidget(self.lang_combo)
        self.about_btn = QPushButton(tr("About"))
        top_bar.addWidget(self.about_btn)
        layout.addLayout(top_bar)

        logo = QLabel()
        logo_path = os.path.join(BASE_DIR, "docs", "armadillo-logo.png")
        if os.path.exists(logo_path):
            logo.setPixmap(QPixmap(logo_path).scaledToWidth(180, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        title = QLabel("Video Helper Tools")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(tr("Choose a tool to start"))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 14px; color: #666;")
        layout.addWidget(subtitle)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(40)
        btn_row.setAlignment(Qt.AlignCenter)
        for name, label, icon in (
            ("compressor", tr("Compress & Archive"), "tool-compressor.svg"),
            ("sync", tr("Sync Videos"), "tool-sync.svg"),
            ("transcriber", tr("Transcribe Audio"), "tool-transcribe.svg"),
            ("rsync", tr("Backup (rsync)"), "tool-sync.svg"),
        ):
            btn_row.addWidget(self.tool_button(name, label, icon))
        layout.addLayout(btn_row)
        layout.addStretch()

    def tool_button(self, name, text, icon_name):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setAlignment(Qt.AlignCenter)
        vbox.setSpacing(10)

        btn = QPushButton()
        btn.setObjectName(f"open_{name}")
        btn.setFixedSize(140, 140)
        btn.setStyleSheet("""
            QPushButton { border: none; background: transparent; border-radius: 20px; }
            QPushButton:hover { background: rgba(0, 0, 0, 0.05); }
            QPushButton:pressed { background: rgba(0, 0, 0, 0.1); }
        """)
        icon_path = Path(BASE_DIR) / "docs" / "icons" / icon_name
        if icon_path.exists():
            btn.setIcon(QIcon(str(icon_path)))
            btn.setIconSize(QSize(120, 120))
        btn.clicked.connect(lambda: self.open_tool(name))

        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 16px; font-weight: bold;")

        vbox.addWidget(btn)
        vbox.addWidget(lbl)
        return container


class VideoHelperToolsSuite(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Helper Tools")
        self.resize(1100, 850)

        icon_path = os.path.join(BASE_DIR, "docs", "icons", "video-helper-tools-512.png")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        set_language(saved_language(load_settings()))
        self.tools = {}  # name -> (tool widget, wrapper with back button)
        self.landing_page = None
        self.build_landing_page()

    @property
    def compressor_tab(self):
        return self.tools.get("compressor", (None, None))[0]

    def build_landing_page(self):
        self.landing_page = LandingPage(self.show_tool)
        self.landing_page.about_btn.clicked.connect(self.show_about)
        self.landing_page.lang_combo.currentIndexChanged.connect(self.change_language)
        self.show_landing()

    def clear_content(self):
        while self.layout.count():
            widget = self.layout.takeAt(0).widget()
            if widget:
                widget.setParent(None)

    def show_landing(self):
        self.clear_content()
        self.layout.addWidget(self.landing_page)

    def show_tool(self, name):
        self.clear_content()
        if name not in self.tools:
            widget = TOOLS[name]()
            self.tools[name] = (widget, self._wrap_with_back(widget))
        self.layout.addWidget(self.tools[name][1])

    def show_compressor(self):
        self.show_tool("compressor")

    def show_sync(self):
        self.show_tool("sync")

    def show_transcribe(self):
        self.show_tool("transcriber")

    def show_rsync(self):
        self.show_tool("rsync")

    def _wrap_with_back(self, widget):
        container = QWidget()
        layout = QVBoxLayout(container)
        top_bar = QHBoxLayout()
        back_btn = QPushButton(tr("← Back"))
        back_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        back_btn.clicked.connect(self.show_landing)
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        layout.addLayout(top_bar)
        layout.addWidget(widget)
        return container

    def busy_tools(self):
        return [widget for widget, _ in self.tools.values() if getattr(widget, "is_busy", lambda: False)()]

    def show_about(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(tr("About Video Helper Tools"))
        msg.setText(tr("<h2>Video Helper Tools</h2><p>A suite of tools for video processing, including compression, syncing, and transcription.</p><p>Version: {version}</p>", version="1.0.0"))
        msg.exec()

    def change_language(self, index):
        code = self.landing_page.lang_combo.itemData(index)
        if code == current_language():
            return
        if self.busy_tools():
            # Rebuilding the tools would abort their running jobs.
            combo = self.landing_page.lang_combo
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(current_language()))
            combo.blockSignals(False)
            QMessageBox.information(self, tr("Language"), tr("Please stop running jobs first (compression, rsync, transcription or the local Whisper server), then change the language."))
            return

        set_language(code)
        try:
            settings = load_settings()
            settings.setdefault('global', {})['language'] = code
            settings['global'].pop('language_index', None)
            with open(settings_file(), 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except OSError as e:
            print(f"Could not save the language setting: {e}")

        # Tool pages translate their texts when built, so rebuild everything.
        self.shutdown_tools()
        for widget, wrapper in self.tools.values():
            wrapper.deleteLater()
        self.tools.clear()
        old_landing = self.landing_page
        self.build_landing_page()
        old_landing.deleteLater()

    def closeEvent(self, event):
        busy = self.busy_tools()
        if busy:
            reply = QMessageBox.question(
                self, tr("Jobs still running"),
                tr("A job is still running. Quit anyway?\nRunning compressions are aborted and their unfinished output files deleted."),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        self.shutdown_tools()
        event.accept()

    def shutdown_tools(self):
        # Embedded tool widgets never receive closeEvent, so stop their jobs/servers here.
        for widget, _ in self.tools.values():
            if hasattr(widget, "shutdown"):
                widget.shutdown()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == WHISPER_SERVER_FLAG:
        from video_helper_tools.transcriber.run_minimal_whisper_server import main as run_whisper_server
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        run_whisper_server()
        return

    # Fix PATH for bundled macOS apps so they can find ffmpeg, ffprobe, and exiftool
    if sys.platform == 'darwin':
        paths = os.environ.get('PATH', '').split(os.pathsep)
        for path in ['/usr/local/bin', '/opt/homebrew/bin']:
            if path not in paths:
                paths.insert(0, path)
        os.environ['PATH'] = os.pathsep.join(paths)

    app = QApplication(sys.argv)
    app.setApplicationName("Video Helper Tools")

    font_path = os.path.join(BASE_DIR, "Nohemi-Regular-BF6438cc58b98fc.otf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            app.setFont(QFont(font_family))

    window = VideoHelperToolsSuite()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
