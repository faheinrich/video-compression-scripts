"""Per-user locations for settings and caches.

Paths must not depend on the working directory: an app launched from Finder runs with cwd "/".
"""
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Video Helper Tools"
# Lets tests (or a portable setup) redirect all app data to one folder.
HOME_OVERRIDE_ENV = "VIDEO_HELPER_TOOLS_HOME"


def _base_dir(kind):
    override = os.environ.get(HOME_OVERRIDE_ENV)
    if override:
        return Path(override) / kind
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / ("Caches" if kind == "cache" else "Application Support") / APP_NAME
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA" if kind == "cache" else "APPDATA", str(home))
        return Path(root) / APP_NAME
    xdg = os.environ.get("XDG_CACHE_HOME" if kind == "cache" else "XDG_CONFIG_HOME")
    return Path(xdg or home / (".cache" if kind == "cache" else ".config")) / "video-helper-tools"


def settings_file():
    path = _base_dir("config") / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # One-time migration of the settings.json that older versions wrote into the cwd.
        legacy = Path.cwd() / "settings.json"
        if legacy.is_file():
            shutil.copy2(legacy, path)
    return path


def thumbnail_dir():
    path = _base_dir("cache") / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path
