def test_compressor_defaults_survive_a_different_cwd(qapp, tmp_path, monkeypatch):
    """A Finder-launched app runs with cwd '/'; settings must not depend on the cwd."""
    from archive_helper.compressor.gui import ArchiverGUI

    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()

    monkeypatch.chdir(first)
    gui = ArchiverGUI()
    gui.slider_crf.setValue(27)
    gui.combo_preset.setCurrentText("veryslow")
    gui.save_defaults()
    assert not (first / "settings.json").exists()

    monkeypatch.chdir(second)
    reloaded = ArchiverGUI()
    assert reloaded.slider_crf.value() == 27
    assert reloaded.combo_preset.currentText() == "veryslow"


def test_thumbnails_are_cached_outside_the_cwd(tmp_path):
    from archive_helper.compressor.utils import get_thumbnail_path

    path = get_thumbnail_path(tmp_path / "video.mp4")
    assert path.parent.is_dir()
    assert tmp_path / "thumbnails" != path.parent
    assert not (tmp_path / "thumbnails").exists()
