#!/usr/bin/env bash

echo "Starting build process for Video Helper Tools..."

# Ensure pyinstaller is installed
pip install pyinstaller

# Determine separator based on OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    SEP=";"
else
    SEP=":"
fi

echo "Using PyInstaller to package the application..."
pyinstaller --noconfirm \
    --name "Video Helper Tools" \
    --windowed \
    --icon "docs/icons/video-helper-tools-512.png" \
    --add-data "docs${SEP}docs" \
    --add-data "settings.json${SEP}." \
    --hidden-import "PyQt5" \
    --hidden-import "PyQt5.QtCore" \
    --hidden-import "PyQt5.QtGui" \
    --hidden-import "PyQt5.QtWidgets" \
    --hidden-import "cv2" \
    --hidden-import "torch" \
    --hidden-import "torchaudio" \
    main.py

echo "Build complete. Check the 'dist' directory."

# If on macOS, copy the app to Applications folder
if [[ "$OSTYPE" == "darwin"* ]]; then
    APP_BUNDLE="dist/Video Helper Tools.app"
    if [ -d "$APP_BUNDLE" ]; then
        echo "Copying application to /Applications..."
        cp -R "$APP_BUNDLE" /Applications/
        echo "Successfully copied to /Applications/Video Helper Tools.app"
    fi
fi
