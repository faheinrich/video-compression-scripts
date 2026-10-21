"""Drag and drop: the two drop areas, dropped folders and hand-picked videos."""
import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMessageBox

from conftest import spin, wait_for
from test_compressor import FakeKeepAwake, fake_worker, make_gui, scan, wait_idle  # noqa: F401  (fixtures)


KEEP_ALIVE = []   # an event only points at its mime data; Python must not free it while the event is used


def mime_for(*paths):
    mime = QMimeData()
    KEEP_ALIVE.append(mime)
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def drag_enter(widget, *paths, pos=(5, 5)):
    event = QDragEnterEvent(QPoint(*pos), Qt.CopyAction, mime_for(*paths), Qt.LeftButton, Qt.NoModifier)
    widget.dragEnterEvent(event)
    return event


def drop(widget, *paths, pos=(5, 5)):
    event = QDropEvent(QPointF(*pos), Qt.CopyAction, mime_for(*paths), Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(event)
    return event


def make_videos(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        path.write_bytes(b"x" * 100)
        paths.append(path)
    return paths


@pytest.fixture
def shown_gui(qapp, make_gui):
    gui = make_gui()
    gui.resize(1300, 800)
    gui.show()
    qapp.processEvents()
    return gui


# --- helpers --------------------------------------------------------------------------------------------------------

def test_collect_videos_takes_files_and_searches_folders(tmp_path):
    from archive_helper.compressor.utils import collect_videos

    a = make_videos(tmp_path / "one", "a.MOV", "b.mp4", "notes.txt", ".hidden.mp4")
    c = make_videos(tmp_path / "two" / "deep", "c.mkv")
    videos, others = collect_videos([tmp_path / "one", c[0], a[0], tmp_path / "missing.mov", tmp_path / "one" / "notes.txt"])
    assert [v.name for v in videos] == ["a.MOV", "b.mp4", "c.mkv"]    # each only once, sorted
    assert others == 2                                                  # the missing path and the text file


def test_common_parent():
    from archive_helper.compressor.utils import common_parent

    assert common_parent([Path("/a/b/x.mov"), Path("/a/b/c/y.mov")]) == Path("/a/b")
    assert common_parent([Path("/a/b/x.mov")]) == Path("/a/b")


# --- scan of hand-picked videos ---------------------------------------------------------------------------------------

def scan_files(qapp, gui, files, dst=""):
    gui.set_selection(files)
    gui.txt_dst.setText(str(dst))
    gui.scan_timer.stop()
    gui.start_unified_scan()
    wait_for(gui.scan_worker.scan_finished)
    qapp.processEvents()


def test_results_of_hand_picked_videos_go_next_to_the_originals(qapp, make_gui, tmp_path):
    files = make_videos(tmp_path / "x", "a.mov") + make_videos(tmp_path / "y" / "z", "b.mp4")
    gui = make_gui()
    scan_files(qapp, gui, files)
    rows = {row.src.name: row for row in gui.model.rows}
    assert rows["a.mov"].dst == tmp_path / "x" / "a_archived.mp4"
    assert rows["b.mp4"].dst == tmp_path / "y" / "z" / "b_archived.mp4"
    assert not any(row.conflict or row.duplicate for row in rows.values())
    assert rows["a.mov"].folder == "x" and rows["b.mp4"].folder == "y/z"          # relative to the common parent


def test_with_a_target_folder_all_results_go_there(qapp, make_gui, tmp_path):
    files = make_videos(tmp_path / "x", "a.mov") + make_videos(tmp_path / "y", "b.mp4")
    gui = make_gui()
    scan_files(qapp, gui, files, dst=tmp_path / "out")
    assert {row.dst for row in gui.model.rows} == {tmp_path / "out" / "a_archived.mp4", tmp_path / "out" / "b_archived.mp4"}


def test_hand_picked_videos_follow_the_same_name_rules(qapp, make_gui, tmp_path):
    files = make_videos(tmp_path / "x", "test.mov", "test.mp4", "clip_archived.mp4", "own.mp4")
    gui = make_gui()
    gui.txt_postfix.setText("")                        # next to the original, same name: own.mp4 would replace itself
    scan_files(qapp, gui, files)
    rows = {row.src.name: row for row in gui.model.rows}
    assert rows["test.mov"].dst.name == "test.mov.mp4" and rows["test.mp4"].dst.name == "test.mp4.mp4"
    assert rows["own.mp4"].conflict and rows["own.mp4"].status == "planned"
    assert "clip_archived.mp4" not in rows                                        # earlier results stay out of the list


def test_earlier_results_among_the_picks_are_skipped_like_in_folder_mode(qapp, make_gui, tmp_path):
    files = make_videos(tmp_path / "x", "a.mov", "a_archived.mp4")
    gui = make_gui()
    scan_files(qapp, gui, files)
    assert [row.src.name for row in gui.model.rows] == ["a.mov"]


def test_existing_results_next_to_the_originals_are_found(qapp, make_gui, tmp_path):
    files = make_videos(tmp_path / "x", "a.mov")
    make_videos(tmp_path / "x", "a_archived.mp4")
    gui = make_gui()
    scan_files(qapp, gui, files)
    assert [(row.src.name, row.status) for row in gui.model.rows] == [("a.mov", "exists")]


# --- drop on the page -------------------------------------------------------------------------------------------------

def test_dragging_over_the_page_shows_the_overlay_and_leaving_hides_it(shown_gui):
    gui = shown_gui
    assert drag_enter(gui, gui.src_dir()).isAccepted() and gui.drop_overlay.isVisible()
    gui.drop_overlay.dragLeaveEvent(None)
    assert not gui.drop_overlay.isVisible()


def test_no_overlay_for_things_that_are_not_files(shown_gui):
    mime = QMimeData()
    KEEP_ALIVE.append(mime)
    mime.setText("just text")
    event = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    shown_gui.dragEnterEvent(event)
    assert not event.isAccepted() and not shown_gui.drop_overlay.isVisible()


def test_nothing_can_be_dropped_while_compressing(qapp, make_gui, tmp_path, fake_worker):
    from test_compressor import started_gui

    gui = started_gui(qapp, make_gui, tmp_path, fake_worker)
    gui.show()
    gui.start_archiving()
    assert not drag_enter(gui, tmp_path).isAccepted() and not gui.drop_overlay.isVisible()
    gui.on_paths_dropped("source", [tmp_path])          # even a drop that arrives anyway changes nothing
    assert gui.txt_src.text() == str(tmp_path / "src")
    gui.stop_archiving()
    wait_idle(qapp, gui)


def test_overlay_has_two_areas_that_do_not_overlap_and_the_list_is_in_source(shown_gui):
    gui = shown_gui
    overlay = gui.drop_overlay
    overlay.setGeometry(gui.rect())
    zones = overlay.zones()
    assert set(zones) == {"source", "target"} and not zones["source"].intersects(zones["target"])
    inside_list = gui.table.mapTo(gui, gui.table.rect().center())
    assert overlay.zone_at(inside_list) == "source"
    assert overlay.zone_at(QPoint(30, 20)) == "source"                               # header, left
    drawer_point = gui.drawer.mapTo(gui, gui.drawer.rect().center())
    assert overlay.zone_at(drawer_point) == "target"                                 # the settings column is Target
    assert zones["target"].left() >= gui.drawer.mapTo(gui, gui.drawer.rect().topLeft()).x()


def test_without_the_settings_column_target_is_the_right_third(shown_gui):
    gui = shown_gui
    gui.btn_settings.setChecked(False)
    gui.drop_overlay.setGeometry(gui.rect())
    zones = gui.drop_overlay.zones()
    assert not zones["source"].intersects(zones["target"])
    assert 0.25 < zones["target"].width() / gui.width() < 0.35


def test_dropping_on_the_overlay_reports_zone_and_paths(shown_gui, tmp_path):
    overlay = shown_gui.drop_overlay
    overlay.setGeometry(shown_gui.rect())
    overlay.show()
    got = []
    overlay.dropped.connect(lambda zone, paths: got.append((zone, paths)))
    folder = tmp_path / "f"
    folder.mkdir()
    drop(overlay, folder, pos=(shown_gui.width() - 30, 20))
    assert got == [("target", [folder])] and not overlay.isVisible()
    overlay.show()
    drop(overlay, folder, pos=(30, 300))
    assert got[-1] == ("source", [folder])


def test_a_dropped_folder_becomes_the_source(qapp, shown_gui, tmp_path):
    make_videos(tmp_path / "in", "a.mov", "b.mp4")
    shown_gui.on_paths_dropped("source", [tmp_path / "in"])
    assert shown_gui.txt_src.text() == str(tmp_path / "in") and shown_gui.selection is None


def test_a_dropped_folder_as_target(shown_gui, tmp_path):
    shown_gui.on_paths_dropped("target", [tmp_path])
    assert shown_gui.txt_dst.text() == str(tmp_path)


def test_a_dropped_file_as_target_uses_its_folder(shown_gui, tmp_path):
    (video,) = make_videos(tmp_path / "somewhere", "a.mov")
    shown_gui.on_paths_dropped("target", [video])
    assert shown_gui.txt_dst.text() == str(tmp_path / "somewhere")


def test_dropped_files_become_a_hand_picked_list(qapp, shown_gui, tmp_path):
    files = make_videos(tmp_path / "x", "a.mov", "b.mp4") + [tmp_path / "x" / "notes.txt"]
    (tmp_path / "x" / "notes.txt").write_text("hi")
    shown_gui.on_paths_dropped("source", files)
    gui = shown_gui
    assert [p.name for p in gui.selection] == ["a.mov", "b.mp4"]
    assert gui.txt_src.text() == "2 Videos ausgewählt" and gui.txt_src.isReadOnly()
    assert not gui.selection_bar.isHidden() and "1 abgelegte" in gui.selection_label.text()
    assert "a.mov" in gui.txt_src.toolTip()
    assert gui.has_source() and gui.has_target()          # no target folder needed: next to the originals


def test_files_without_any_video_change_nothing_and_say_so(qapp, shown_gui, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    (tmp_path / "t.txt").write_text("x")
    shown_gui.on_paths_dropped("source", [tmp_path / "t.txt"])
    assert shown_gui.selection is None and shown and shown_gui.selection_bar.isHidden()


def test_back_to_folder_mode_restores_the_folder(qapp, shown_gui, tmp_path):
    make_videos(tmp_path / "in", "a.mov")
    shown_gui.on_paths_dropped("source", [tmp_path / "in"])
    shown_gui.on_paths_dropped("source", make_videos(tmp_path / "x", "a.mov", "b.mp4"))
    assert shown_gui.selection is not None
    shown_gui.leave_selection()
    assert shown_gui.selection is None and shown_gui.txt_src.text() == str(tmp_path / "in")
    assert not shown_gui.txt_src.isReadOnly() and shown_gui.selection_bar.isHidden()


def test_a_dropped_folder_while_picking_leaves_the_hand_picked_mode(qapp, shown_gui, tmp_path):
    make_videos(tmp_path / "in", "a.mov")
    shown_gui.on_paths_dropped("source", make_videos(tmp_path / "x", "a.mov", "b.mp4"))
    shown_gui.on_paths_dropped("source", [tmp_path / "in"])
    assert shown_gui.selection is None and shown_gui.txt_src.text() == str(tmp_path / "in")


def test_several_dropped_folders_are_searched_for_videos(qapp, shown_gui, tmp_path):
    make_videos(tmp_path / "one", "a.mov")
    make_videos(tmp_path / "two" / "deep", "b.mp4")
    shown_gui.on_paths_dropped("source", [tmp_path / "one", tmp_path / "two"])
    assert [p.name for p in shown_gui.selection] == ["a.mov", "b.mp4"]


def test_the_hand_picked_list_is_not_saved_as_the_default_source(qapp, make_gui, tmp_path):
    gui = make_gui()
    make_videos(tmp_path / "in", "a.mov")
    gui.txt_src.setText(str(tmp_path / "in"))
    gui.set_selection(make_videos(tmp_path / "x", "b.mp4"))
    gui.save_defaults()
    saved = json.loads((tmp_path / "app-home" / "config" / "settings.json").read_text())["compressor"]
    assert saved["src_dir"] == str(tmp_path / "in")


def test_a_run_of_hand_picked_videos_uses_their_common_folder_and_the_chosen_target(qapp, make_gui, tmp_path, fake_worker):
    gui = make_gui()
    files = make_videos(tmp_path / "x", "a.mov") + make_videos(tmp_path / "y", "b.mp4")
    scan_files(qapp, gui, files)
    gui.start_archiving()
    assert gui.is_archiving()
    assert gui.worker.settings is not None
    gui.stop_archiving()
    wait_idle(qapp, gui)


def test_start_button_is_usable_with_hand_picked_videos_and_no_target(qapp, make_gui, tmp_path):
    gui = make_gui()
    scan_files(qapp, gui, make_videos(tmp_path / "x", "a.mov"))
    assert gui.btn_run.isEnabled() and gui.run_blocked_reason() == ""


def test_picking_videos_clears_the_target_and_leaving_brings_it_back(qapp, shown_gui, tmp_path):
    gui = shown_gui
    gui.txt_src.setText(str(tmp_path / "in"))
    gui.txt_dst.setText(str(tmp_path / "archive"))
    gui.set_selection(make_videos(tmp_path / "x", "a.mov") + make_videos(tmp_path / "y", "b.mov"))
    assert gui.txt_dst.text() == "" and "Neben jedem Original" in gui.txt_dst.placeholderText()
    gui.leave_selection()
    assert gui.txt_dst.text() == str(tmp_path / "archive") and "Neben" not in gui.txt_dst.placeholderText()
    assert gui.txt_src.text() == str(tmp_path / "in")


def test_a_target_chosen_for_the_picked_videos_is_used_and_not_saved_as_the_default(qapp, make_gui, tmp_path):
    gui = make_gui()
    gui.txt_dst.setText(str(tmp_path / "archive"))
    gui.set_selection(make_videos(tmp_path / "x", "a.mov"))
    gui.txt_dst.setText(str(tmp_path / "other"))
    gui.save_defaults()
    saved = json.loads((tmp_path / "app-home" / "config" / "settings.json").read_text())["compressor"]
    assert saved["dst_dir"] == str(tmp_path / "archive")                  # the folder-mode target is kept


def test_an_unavailable_target_is_reported_before_anything_starts(qapp, make_gui, tmp_path, fake_worker, monkeypatch):
    from test_compressor import started_gui

    gui = started_gui(qapp, make_gui, tmp_path, fake_worker)
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, so a folder cannot be created below it")
    gui.txt_dst.setText(str(blocker / "target"))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[1:3])))
    gui.start_archiving()
    assert not gui.is_archiving() and len(shown) == 1
    assert shown[0][0] == "Zielordner nicht verfügbar" and "Laufwerk" in shown[0][1]


def test_the_overlay_says_what_a_drop_would_do_for_a_folder_and_for_a_selection(shown_gui, tmp_path):
    gui = shown_gui
    (video,) = make_videos(tmp_path / "x", "a.mov")
    other = make_videos(tmp_path / "x", "b.mov")[0]
    drag_enter(gui, tmp_path / "x")
    overlay = gui.drop_overlay
    assert overlay.source_hint() == "Diesen Ordner als Quelle verwenden"
    assert overlay.target_hint() == "Diesen Ordner für die Ergebnisse verwenden"
    overlay.dragLeaveEvent(None)

    drag_enter(gui, video, other)
    assert "2 abgelegte Elemente" in overlay.source_hint() and "des ersten Elements" in overlay.target_hint()
    overlay.dragLeaveEvent(None)

    drag_enter(gui, video)       # a single file counts as a selection, not as a folder
    assert "1 abgelegte Elemente" in overlay.source_hint()
