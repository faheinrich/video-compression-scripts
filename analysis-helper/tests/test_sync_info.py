import json

def test_info_dialog_renders_with_and_without_results(qapp, monkeypatch, tmp_path):
    from analysis_helper.sync import info

    assert info.SyncInfoDialog().windowTitle()
    monkeypatch.setattr(info, "RESULTS_FILE", tmp_path / "missing.json")
    assert info.load_results() is None
    assert "<table" not in info.build_html()
    info.SyncInfoDialog()


def test_info_results_table_colours_by_share_of_correct_cases():
    from analysis_helper.sync.info import results_table

    data = {"references": {
        "video1.mp4": {"cases": {"clean": {"ok": 10, "total": 10}, "noisy": {"ok": 6, "total": 10}, "hard": {"ok": 1, "total": 10}}},
        "video2.mp4": {"cases": {"clean": {"ok": 10, "total": 10}}},
    }}
    table = results_table(data)
    assert "#23875a" in table and "#b7701a" in table and "#c63f35" in table and "–" in table
    assert results_table({"references": {}}) == ""


def test_info_reads_a_results_file(monkeypatch, tmp_path):
    from analysis_helper.sync import info

    path = tmp_path / "r.json"
    path.write_text(json.dumps({"tolerance_ms": 5, "references": {"video1.mp4": {"cases": {"x": {"ok": 1, "total": 1}}}}}))
    monkeypatch.setattr(info, "RESULTS_FILE", path)
    assert "5 ms" in info.build_html() and "<table" in info.build_html()
    path.write_text("not json")
    assert info.load_results() is None
