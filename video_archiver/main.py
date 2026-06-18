import sys
import os
import i18n
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFontDatabase, QFont

from video_archiver.gui import ArchiverGUI

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Video Archiver Pro")
    app.setApplicationDisplayName("Video Archiver Pro")
    
    font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Nohemi-Regular-BF6438cc58b98fc.otf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            app.setFont(QFont(font_family))
    
    icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "imgs", "logo.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        
    gui = ArchiverGUI()
    gui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
