import sys
import os
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSizePolicy, QComboBox
from PyQt5.QtGui import QIcon, QFontDatabase, QFont, QPixmap
from PyQt5.QtCore import Qt, QSize

# We will need to refactor the GUIs to be QWidgets instead of QMainWindows
# For now, let's assume we'll fix that in the next step.
from video_helper_tools.compressor.gui import ArchiverGUI
from video_helper_tools.sync.gui import VideoSyncGUI
from video_helper_tools.transcriber.gui import WhisperGui

class LandingPage(QWidget):
    def __init__(self, open_compressor, open_sync, open_transcriber):
        super().__init__()
        self.open_compressor = open_compressor
        self.open_sync = open_sync
        self.open_transcriber = open_transcriber
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        logo = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), "docs", "armadillo-logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo.setPixmap(pixmap.scaledToWidth(180, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        title = QLabel("Video Helper Tools")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("Choose a tool to start")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 14px; color: #666;")
        layout.addWidget(subtitle)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(40)
        btn_row.setAlignment(Qt.AlignCenter)

        # Move about button to the top of the landing page
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        
        lang_label = QLabel("Language:")
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["Deutsch", "English", "Français", "Español"])
        top_bar.addWidget(lang_label)
        top_bar.addWidget(self.lang_combo)
        
        self.about_btn = QPushButton("About")
        self.about_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        top_bar.addWidget(self.about_btn)
        
        layout.addLayout(top_bar)
        
        def create_tool_button(text, icon_name, callback):
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setAlignment(Qt.AlignCenter)
            vbox.setSpacing(10)

            btn = QPushButton()
            btn.setFixedSize(140, 140)
            btn.setStyleSheet("""
                QPushButton {
                    border: none;
                    background: transparent;
                    border-radius: 20px;
                }
                QPushButton:hover {
                    background: rgba(0, 0, 0, 0.05);
                }
                QPushButton:pressed {
                    background: rgba(0, 0, 0, 0.1);
                }
            """)
            
            icon_path = Path(__file__).resolve().parent / "docs" / "icons" / icon_name
            if icon_path.exists():
                btn.setIcon(QIcon(str(icon_path)))
                btn.setIconSize(QSize(120, 120))
            
            btn.clicked.connect(callback)

            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-size: 16px; font-weight: bold;")

            vbox.addWidget(btn)
            vbox.addWidget(lbl)
            return container

        self.btn_compressor = create_tool_button("Compress & Archive", "tool-compressor.svg", self.open_compressor)
        self.btn_sync = create_tool_button("Sync Videos", "tool-sync.svg", self.open_sync)
        self.btn_transcribe = create_tool_button("Transcribe Audio", "tool-transcribe.svg", self.open_transcriber)

        btn_row.addWidget(self.btn_compressor)
        btn_row.addWidget(self.btn_sync)
        btn_row.addWidget(self.btn_transcribe)
        layout.addLayout(btn_row)
        layout.addStretch()


from PyQt5.QtWidgets import QComboBox

import json

class VideoHelperToolsSuite(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Helper Tools Suite")
        self.resize(1100, 850)
        
        # Set Application Icon
        icon_path = os.path.join(os.path.dirname(__file__), "docs", "icons", "video-helper-tools-512.png")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)
            
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.compressor_tab = None
        self.sync_tab = None
        self.transcription_tab = None

        self.landing_page = LandingPage(self.show_compressor, self.show_sync, self.show_transcribe)
        self.landing_page.about_btn.clicked.connect(self.show_about)
        self.landing_page.lang_combo.currentIndexChanged.connect(self.change_language)
        self.layout.addWidget(self.landing_page)
        
        # Try loading global language on startup
        self.load_global_settings()

    def clear_content(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

    def show_landing(self):
        self.clear_content()
        self.layout.addWidget(self.landing_page)

    def show_compressor(self):
        self.clear_content()
        if self.compressor_tab is None:
            self.compressor_tab = ArchiverGUI()
            
            # Use _wrap_with_back to add standard top bar
            self.compressor_wrapper = self._wrap_with_back(self.compressor_tab)
            
        self.layout.addWidget(self.compressor_wrapper)

    def show_sync(self):
        self.clear_content()
        if self.sync_tab is None:
            self.sync_tab = VideoSyncGUI()
            self.sync_tab = self._wrap_with_back(self.sync_tab)
        self.layout.addWidget(self.sync_tab)

    def show_transcribe(self):
        self.clear_content()
        if self.transcription_tab is None:
            self.transcription_tab = WhisperGui()
            self.transcription_tab = self._wrap_with_back(self.transcription_tab)
        self.layout.addWidget(self.transcription_tab)

    def _wrap_with_back(self, widget):
        container = QWidget()
        layout = QVBoxLayout(container)
        
        top_bar = QHBoxLayout()
        back_btn = QPushButton("← Go Back")
        back_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        back_btn.clicked.connect(self.show_landing)
        top_bar.addWidget(back_btn)
        
        top_bar.addStretch()
        
        lang_label = QLabel("Language:")
        lang_combo = QComboBox()
        lang_combo.addItems(["Deutsch", "English", "Français", "Español"])
        lang_combo.currentIndexChanged.connect(self.change_language)
        top_bar.addWidget(lang_label)
        top_bar.addWidget(lang_combo)
        
        # Load initial language from landing page
        if hasattr(self, 'landing_page'):
            lang_combo.setCurrentIndex(self.landing_page.lang_combo.currentIndex())
        
        layout.addLayout(top_bar)
        layout.addWidget(widget)
        return container
        
    def show_about(self):
        from PyQt5.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("About Video Helper Tools")
        msg.setText("<h2>Video Helper Tools</h2><p>A suite of tools for video processing, including compression, syncing, and transcription.</p><p>Version: 1.0.0</p>")
        msg.exec_()

    def change_language(self, index):
        langs = ["de", "en", "fr", "es"]
        import i18n
        try:
            i18n.set_language(langs[index])
        except AttributeError:
            i18n.set('locale', langs[index])
            
        # Save global language preference
        try:
            settings = {}
            if os.path.exists('settings.json'):
                with open('settings.json', 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            if 'global' not in settings:
                settings['global'] = {}
            settings['global']['language_index'] = index
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            pass
        
        # We need to retranslate the currently active tab if it supports it
        if hasattr(self, 'compressor_tab') and self.compressor_tab is not None:
            if hasattr(self.compressor_tab, 'retranslate_ui'):
                self.compressor_tab.retranslate_ui()
                
    def load_global_settings(self):
        if not os.path.exists('settings.json'):
            return
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
            global_settings = settings.get('global', {})
            if 'language_index' in global_settings:
                # We need to set this on the landing page's combo box
                if hasattr(self, 'landing_page'):
                    self.landing_page.lang_combo.setCurrentIndex(global_settings['language_index'])
        except Exception as e:
            pass

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Video Helper Tools")
    
    # Load custom font if exists
    font_path = os.path.join(os.path.dirname(__file__), "Nohemi-Regular-BF6438cc58b98fc.otf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            app.setFont(QFont(font_family))
            
    window = VideoHelperToolsSuite()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
