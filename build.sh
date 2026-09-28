#!/usr/bin/env bash

echo "Starting build process for Video Helper Tools..."

# Installs runtime deps plus the dev group (pyinstaller) into .venv
uv sync

# Determine separator based on OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    SEP=";"
else
    SEP=":"
fi

echo "Using PyInstaller to package the application..."
uv run pyinstaller --noconfirm \
    --name "Video Helper Tools" \
    --windowed \
    --icon "docs/icons/video-helper-tools-512.png" \
    --add-data "docs${SEP}docs" \
    --add-data "video_helper_tools/compressor/exiftool_vht.config${SEP}video_helper_tools/compressor" \
    --hidden-import "PySide6.QtMultimedia" \
    --hidden-import "PySide6.QtMultimediaWidgets" \
    --exclude-module "PyQt5" \
    --hidden-import "cv2" \
    --hidden-import "torch" \
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
