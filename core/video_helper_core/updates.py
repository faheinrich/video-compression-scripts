"""Looks once at start whether the app's GitHub repository has a newer release.

Every app has its own tags (archive-v0.0.2, analysis-v0.0.2), so the releases are filtered by the app's tag prefix.
The check runs in a background thread and fails silently (offline, rate limit, ...).
"""
import json
import os
import re
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal

RELEASES_URL = "https://api.github.com/repos/faheinrich/video-helper-tools/releases?per_page=30"
# Set (to anything) to skip the check, e.g. in tests or on machines without network access.
DISABLE_ENV = "VIDEO_HELPER_TOOLS_NO_UPDATE_CHECK"
TIMEOUT_SECONDS = 5


def parse_version(text):
    """"0.0.12" -> (0, 0, 12); missing or non-numeric parts count as 0."""
    numbers = [int(part) for part in re.findall(r"\d+", text)[:3]]
    return tuple(numbers + [0] * (3 - len(numbers)))


def newest_release(releases, tag_prefix):
    """(version, page URL) of the highest published release whose tag starts with tag_prefix, or None."""
    best = None
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease") or not tag.startswith(tag_prefix):
            continue
        version = tag[len(tag_prefix):]
        if best is None or parse_version(version) > parse_version(best[0]):
            best = (version, release.get("html_url", ""))
    return best


def newer_release(releases, tag_prefix, current_version):
    """The release to announce, or None when current_version is the newest (or newer)."""
    best = newest_release(releases, tag_prefix)
    if best and parse_version(best[0]) > parse_version(current_version):
        return best
    return None


def fetch_releases():
    request = urllib.request.Request(RELEASES_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "video-helper-tools-update-check"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


class UpdateChecker(QObject):
    """Emits found(version, url) once if a newer release exists; never raises."""
    found = Signal(str, str)

    def __init__(self, tag_prefix, current_version, parent=None):
        super().__init__(parent)
        self.tag_prefix, self.current_version = tag_prefix, current_version

    def start(self):
        if os.environ.get(DISABLE_ENV):
            return None
        thread = threading.Thread(target=self.run, daemon=True)  # a daemon never keeps the app from quitting
        thread.start()
        return thread

    def run(self):
        try:
            release = newer_release(fetch_releases(), self.tag_prefix, self.current_version)
        except (OSError, ValueError, AttributeError):
            return
        if release:
            self.found.emit(*release)
