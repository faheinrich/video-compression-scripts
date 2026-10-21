"""Per-user locations for settings and caches.

Paths must not depend on the working directory: an app launched from Finder runs with cwd "/".
"""
import os
import shutil
import sys
from pathlib import Path

# Set by each app (see configure) so the apps keep separate settings and caches.
APP_NAME = "Video Helper Tools"
APP_SLUG = "video-helper-tools"
# The single suite app that came before the separate apps stored its data under this name.
LEGACY_APP_NAME = "Video Helper Tools"
# Lets tests (or a portable setup) redirect all app data to one folder.
HOME_OVERRIDE_ENV = "VIDEO_HELPER_TOOLS_HOME"


def configure(name, slug):
    """Names this app's settings and cache folders (e.g. "Archive Helper", "archive-helper")."""
    global APP_NAME, APP_SLUG
    APP_NAME, APP_SLUG = name, slug


def _base_dir(kind, name=None, slug=None):
    name, slug = name or APP_NAME, slug or APP_SLUG
    override = os.environ.get(HOME_OVERRIDE_ENV)
    if override:
        return Path(override) / kind
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / ("Caches" if kind == "cache" else "Application Support") / name
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA" if kind == "cache" else "APPDATA", str(home))
        return Path(root) / name
    xdg = os.environ.get("XDG_CACHE_HOME" if kind == "cache" else "XDG_CONFIG_HOME")
    return Path(xdg or home / (".cache" if kind == "cache" else ".config")) / slug


def settings_file():
    path = _base_dir("config") / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # One-time migration of the settings of the former single "Video Helper Tools" app.
        legacy = _base_dir("config", LEGACY_APP_NAME, "video-helper-tools") / "settings.json"
        if legacy.is_file() and legacy != path:
            shutil.copy2(legacy, path)
    return path


def thumbnail_dir():
    path = _base_dir("cache") / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def duration_cache_file():
    path = _base_dir("cache") / "durations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
