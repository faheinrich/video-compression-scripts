"""The time estimate of the whole folder: what was learned from earlier encodes, and how the main page shows it."""
import json
import time
from pathlib import Path

import pytest

from test_compressor import FakeKeepAwake, fake_worker, make_gui, started_gui, wait_idle  # noqa: F401  (fixtures)

CPU = {'renderer': 'libx265', 'preset': 'fast', 'limit_res': True, 'max_res': 1920, 'limit_fps': True, 'max_fps': 30}


def speeds(tmp_path):
    from archive_helper.compressor.utils import EncodeSpeeds

    return EncodeSpeeds(tmp_path / "speed.json")


def test_nothing_is_known_at_first(tmp_path):
    assert speeds(tmp_path).estimate(CPU, 1, 3600) is None


def test_a_measurement_gives_an_exact_estimate_for_the_same_settings(tmp_path):
    store = speeds(tmp_path)
    store.record(CPU, 1, 100, 50)                         # half a second of work per second of video
    assert store.estimate(CPU, 1, 3600) == (1800, True)
    assert store.estimate({**CPU, 'crf': 12, 'vt_quality': 3}, 1, 3600) == (1800, True)      # quality does not change the key


def test_other_settings_are_not_mixed_up(tmp_path):
    store = speeds(tmp_path)
    store.record(CPU, 1, 100, 50)
    for other in ({**CPU, 'preset': 'slow'}, {**CPU, 'max_res': 1280}, {**CPU, 'limit_fps': False},
                  {**CPU, 'renderer': 'videotoolbox'}):
        assert store.estimate(other, 1, 100) is None


def test_parallel_encodes_divide_the_time_and_a_missing_measurement_is_a_cautious_guess(tmp_path):
    store = speeds(tmp_path)
    store.record(CPU, 2, 100, 150)                        # with two side by side each video took 1.5 s per second
    assert store.estimate(CPU, 2, 400) == (300, True)     # 400 s of video, two at a time
    seconds, exact = store.estimate(CPU, 1, 400)          # one at a time: judged from the two-at-a-time run
    assert not exact and seconds == pytest.approx(300)
    store.record(CPU, 1, 100, 100)
    assert store.estimate(CPU, 1, 400) == (400, True)


def test_recent_measurements_count_more_and_the_file_survives(tmp_path):
    store = speeds(tmp_path)
    for wall in (100, 100, 100, 100, 100, 200):
        store.record(CPU, 1, 100, wall)
    ratio = speeds(tmp_path).entries[store.key(CPU, 1)]["ratio"]                    # read back from disk
    assert 1.0 < ratio < 1.5 and ratio == pytest.approx((1.0 * 4 + 2.0) / 5)


def test_useless_measurements_are_ignored(tmp_path):
    store = speeds(tmp_path)
    store.record(CPU, 1, 0, 10)
    store.record(CPU, 1, None, 10)
    store.record(CPU, 1, 10, 0)
    assert store.entries == {} and not (tmp_path / "speed.json").exists()


def test_a_damaged_file_is_ignored(tmp_path):
    (tmp_path / "speed.json").write_text("not json")
    assert speeds(tmp_path).estimate(CPU, 1, 100) is None


# --- the main page ----------------------------------------------------------------------------------------------------

def gui_with_queue(qapp, make_gui, tmp_path, fake_worker, durations):
    gui = started_gui(qapp, make_gui, tmp_path, fake_worker)
    from archive_helper.compressor.model import VideoRow

    root = tmp_path / "src"
    rows = [VideoRow(src=root / f"{n}.mp4", dst=tmp_path / "dst" / f"{n}_a.mp4", size=100, duration=d, root=root)
            for n, d in enumerate(durations)]
    gui.model.reset(rows)
    gui.scan_items = [{"path": r.src, "dst_path": r.dst, "size": r.size, "exists_compressed": False} for r in rows]
    gui.speeds = speeds(tmp_path)
    gui.spin_jobs.setValue(1)
    return gui


def time_text(gui):
    return gui.summary_values["time"][1].text(), gui.summary_values["time"][1].toolTip()


def test_the_summary_shows_no_time_before_anything_was_measured(qapp, make_gui, tmp_path, fake_worker):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [3600, 3600])
    gui.refresh_summary()
    text, tip = time_text(gui)
    assert text == "–" and "Verschiedene Kompressionen prüfen" in tip


def test_the_summary_shows_the_estimate_of_the_queue(qapp, make_gui, tmp_path, fake_worker):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [3600, 3600])        # two hours of video
    gui.speeds.record(gui.current_run_settings(), gui.spin_jobs.value(), 100, 50)     # 0.5 s per second of video
    gui.refresh_summary()
    text, tip = time_text(gui)
    assert text == "≈ 1 Std. 0 Min." and "bisher gedauert" in tip


def test_videos_not_read_yet_count_like_the_average_and_are_mentioned(qapp, make_gui, tmp_path, fake_worker):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [3600, None])
    gui.speeds.record(gui.current_run_settings(), gui.spin_jobs.value(), 100, 100)
    gui.refresh_summary()
    text, tip = time_text(gui)
    assert text == "≈ 2 Std. 0 Min." and "1 Videos wurden noch nicht gelesen" in tip


def test_changing_settings_updates_the_estimate(qapp, make_gui, tmp_path, fake_worker):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [3600])
    gui.speeds.record(gui.current_run_settings(), gui.spin_jobs.value(), 100, 100)
    gui.refresh_summary()
    assert time_text(gui)[0] != "–"
    gui.combo_preset.setCurrentText("veryslow")
    gui.refresh_summary()
    assert time_text(gui)[0] == "–"                                                    # nothing known for that preset


def test_an_estimate_from_other_parallelism_is_called_a_cautious_guess(qapp, make_gui, tmp_path, fake_worker):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [3600])
    other_jobs = 2 if gui.spin_jobs.value() == 1 else 1
    gui.speeds.record(gui.current_run_settings(), other_jobs, 100, 100)
    gui.refresh_summary()
    assert "vorsichtige Schätzung" in time_text(gui)[1]


def test_an_empty_queue_shows_a_dash(qapp, make_gui):
    gui = make_gui()
    gui.refresh_summary()
    assert time_text(gui)[0] == "–"


def test_finished_videos_teach_the_estimate(qapp, make_gui, tmp_path, fake_worker, monkeypatch):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [100, 100])
    clock = {"now": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    gui.start_archiving()
    first = str(gui.model.rows[0].src)
    gui.on_status_update(first, "running", "", {})
    clock["now"] += 50
    gui.on_status_update(first, "finished", "", {"src_size": 100, "dst_size": 40})
    settings = gui.current_run_settings()
    seconds, exact = gui.speeds.estimate(settings, gui.run_jobs, 100)
    assert exact and seconds == pytest.approx(50 / gui.run_jobs)
    gui.stop_archiving()
    wait_idle(qapp, gui)


def test_a_paused_run_and_a_test_run_teach_nothing(qapp, make_gui, tmp_path, fake_worker, monkeypatch):
    gui = gui_with_queue(qapp, make_gui, tmp_path, fake_worker, [100, 100])
    gui.start_archiving()
    gui.toggle_pause()
    gui.toggle_pause()
    path = str(gui.model.rows[0].src)
    gui.on_status_update(path, "running", "", {})
    gui.on_status_update(path, "finished", "", {"src_size": 100, "dst_size": 40})
    assert gui.speeds.entries == {}
    gui.stop_archiving()
    wait_idle(qapp, gui)

    (tmp_path / "two").mkdir()
    gui = gui_with_queue(qapp, make_gui, tmp_path / "two", fake_worker, [100])
    gui.cb_dry_run.setChecked(True)
    gui.start_archiving()
    path = str(gui.model.rows[0].src)
    gui.on_status_update(path, "running", "", {})
    gui.on_status_update(path, "finished", "", {"src_size": 100, "dst_size": 40})
    assert gui.speeds.entries == {}
    gui.stop_archiving()
    wait_idle(qapp, gui)
