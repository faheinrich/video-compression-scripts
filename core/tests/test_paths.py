import pytest

from video_helper_core import paths


# --- app data paths --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("platform,env,fragment", [
    ("linux", {"XDG_CONFIG_HOME": "XDG"}, "video-helper-tools"),
    ("linux", {}, ".config"),
    ("darwin", {}, "Application Support"),
    ("win32", {"APPDATA": "WIN"}, "Video Helper Tools"),
])
def test_base_dir_per_platform(monkeypatch, tmp_path, platform, env, fragment):
    monkeypatch.delenv(paths.HOME_OVERRIDE_ENV)
    for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(tmp_path / value))
    monkeypatch.setattr(paths.sys, "platform", platform)
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert fragment in str(paths._base_dir("config"))
    assert str(paths._base_dir("cache")) != str(paths._base_dir("config"))


def test_override_redirects_everything(tmp_path):
    assert paths.settings_file().parent == tmp_path / "app-home" / "config"
    assert paths.thumbnail_dir() == tmp_path / "app-home" / "cache" / "thumbnails"


def test_settings_of_the_former_suite_app_are_migrated_once(tmp_path, monkeypatch):
    import json

    monkeypatch.delenv(paths.HOME_OVERRIDE_ENV)
    for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: tmp_path / "home"))
    monkeypatch.setattr(paths, "APP_NAME", "Archive Helper")
    monkeypatch.setattr(paths, "APP_SLUG", "archive-helper")

    old = paths._base_dir("config", paths.LEGACY_APP_NAME, "video-helper-tools") / "settings.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"compressor": {"crf": 23}}))

    new = paths.settings_file()
    assert new != old and json.loads(new.read_text()) == {"compressor": {"crf": 23}}
    # Later edits to the old file must not overwrite the migrated one.
    old.write_text(json.dumps({"compressor": {"crf": 30}}))
    assert json.loads(paths.settings_file().read_text()) == {"compressor": {"crf": 23}}


def test_configure_names_the_apps_folders(monkeypatch):
    monkeypatch.setattr(paths, "APP_NAME", paths.APP_NAME)
    monkeypatch.setattr(paths, "APP_SLUG", paths.APP_SLUG)
    paths.configure("Some Helper", "some-helper")
    assert paths.APP_NAME == "Some Helper" and paths.APP_SLUG == "some-helper"
