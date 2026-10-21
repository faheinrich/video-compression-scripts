import pytest

pytest.register_assert_rewrite("video_helper_core.testing")  # before the first import of it, so its asserts are rewritten

pytest_plugins = ["video_helper_core.testing"]
