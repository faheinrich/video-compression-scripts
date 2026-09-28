import json


def test_legacy_settings_json_is_migrated_once(tmp_path, monkeypatch):
    from video_helper_tools.core.paths import settings_file

    legacy_dir = tmp_path / "repo"
    legacy_dir.mkdir()
    (legacy_dir / "settings.json").write_text(json.dumps({"compressor": {"crf": 23}}))
    monkeypatch.chdir(legacy_dir)

    path = settings_file()
    assert json.loads(path.read_text()) == {"compressor": {"crf": 23}}

    # Later edits to the old file must not overwrite the migrated one.
    (legacy_dir / "settings.json").write_text(json.dumps({"compressor": {"crf": 30}}))
    assert json.loads(settings_file().read_text()) == {"compressor": {"crf": 23}}


def test_compressor_defaults_survive_a_different_cwd(qapp, tmp_path, monkeypatch):
    """A Finder-launched app runs with cwd '/'; settings must not depend on the cwd."""
    from video_helper_tools.compressor.gui import ArchiverGUI

    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()

    monkeypatch.chdir(first)
    gui = ArchiverGUI()
    gui.spin_crf.setValue(27)
    gui.combo_preset.setCurrentText("veryslow")
    gui.save_defaults()
    assert not (first / "settings.json").exists()

    monkeypatch.chdir(second)
    reloaded = ArchiverGUI()
    assert reloaded.spin_crf.value() == 27
    assert reloaded.combo_preset.currentText() == "veryslow"


def test_thumbnails_are_cached_outside_the_cwd(tmp_path):
    from video_helper_tools.compressor.utils import get_thumbnail_path

    path = get_thumbnail_path(tmp_path / "video.mp4")
    assert path.parent.is_dir()
    assert tmp_path / "thumbnails" != path.parent
    assert not (tmp_path / "thumbnails").exists()
