import pytest

pytest.register_assert_rewrite("video_helper_core.testing")  # before the first import of it, so its asserts are rewritten

from pathlib import Path

from video_helper_core.testing import requires_exiftool, requires_ffmpeg, spin, wait_for  # noqa: F401

pytest_plugins = ["video_helper_core.testing"]

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_VIDEOS = [REPO_ROOT / "example_resources" / "video1.mp4", REPO_ROOT / "example_resources" / "video2.mp4"]
