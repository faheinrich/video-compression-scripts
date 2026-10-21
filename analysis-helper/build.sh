#!/usr/bin/env bash
# Builds the Analysis Helper app with PyInstaller. Run from anywhere; the result is in analysis-helper/dist.
set -euo pipefail
cd "$(dirname "$0")"

echo "Starting build process for Analysis Helper..."

# One environment for the whole workspace; only this app's dependencies and the dev tools are installed.
(cd .. && uv sync --package analysis-helper --group dev)

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then SEP=";"; else SEP=":"; fi

uv run --package analysis-helper pyinstaller --noconfirm \
    --name "Analysis Helper" \
    --windowed \
    --icon "resources/app-icon.png" \
    --add-data "resources${SEP}resources" \
    --add-data "docs${SEP}docs" \
    --hidden-import "PySide6.QtMultimedia" \
    --hidden-import "PySide6.QtMultimediaWidgets" \
    --exclude-module "PyQt5" \
    --hidden-import "cv2" \
    --hidden-import "torch" \
    main.py

echo "Build complete. Check the 'dist' directory."

# On a developer's Mac, copy the app to Applications (not on CI, where the app is packaged for a release instead)
if [[ "$OSTYPE" == "darwin"* && -z "${CI:-}" ]]; then
    APP_BUNDLE="dist/Analysis Helper.app"
    if [ -d "$APP_BUNDLE" ]; then
        cp -R "$APP_BUNDLE" /Applications/
        echo "Copied to /Applications/Analysis Helper.app"
    fi
fi
