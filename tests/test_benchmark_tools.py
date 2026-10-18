"""The benchmark's own building blocks, on a short synthetic signal (the real benchmark runs separately)."""
import json
import sys

import numpy as np
import pytest

from conftest import requires_ffmpeg
from video_helper_tools.sync import benchmark

SR = benchmark.SR


@pytest.fixture(scope="module")
def reference():
    return np.random.default_rng(3).standard_normal(SR * 70).astype(np.float32) * 0.1


def short():
    return np.random.default_rng(5).standard_normal(SR * 2).astype(np.float32) * 0.1


@pytest.mark.parametrize("name", [n for n in benchmark.DISTORTIONS if not n.startswith("AAC")])
def test_every_distortion_keeps_length_and_type(name):
    x = short()
    out = benchmark.DISTORTIONS[name](x, np.random.default_rng(0))
    assert len(out) == len(x) and np.all(np.isfinite(out))


@requires_ffmpeg
def test_aac_distortion_keeps_length():
    x = short()
    assert len(benchmark.DISTORTIONS["AAC 24 kbps"](x, np.random.default_rng(0))) == len(x)


def test_noise_has_the_requested_snr():
    x = short()
    noisy = benchmark.noise(10)(x, np.random.default_rng(0))
    snr = 20 * np.log10(benchmark.rms(x) / benchmark.rms(noisy - x))
    assert snr == pytest.approx(10, abs=0.7)


def test_clean_and_inverted_polarity():
    x = short()
    assert np.array_equal(benchmark.DISTORTIONS["clean"](x, None), x)
    assert np.array_equal(benchmark.DISTORTIONS["inverted polarity"](x, None), -x)


def test_excerpt_pads_with_silence_outside_the_reference():
    ref = np.ones(SR * 2, dtype=np.float32)
    before = benchmark.excerpt(ref, -1, 2)
    assert before[:SR].max() == 0 and before[SR:].min() == 1
    after = benchmark.excerpt(ref, 1, 2)
    assert after[:SR].min() == 1 and after[SR:].max() == 0
    assert benchmark.excerpt(ref, 10, 1).max() == 0


def test_run_finds_the_known_shift_on_a_clean_copy(reference):
    results = benchmark.run(reference, {"clean": benchmark.DISTORTIONS["clean"]}, [(0, 0), (0, 1.5), (2.0, 0)], absolute=True)
    for truth, estimate, error_ms in results["clean"]:
        assert abs(error_ms) < 1


def test_run_one_sided_and_drift_are_distorted_on_one_excerpt_only(reference):
    one = benchmark.run(reference, {"noise SNR 20 dB": benchmark.DISTORTIONS["noise SNR 20 dB"]}, [(0, 0.5)],
                        absolute=True, both=False)
    drift = benchmark.run(reference, {"clock drift 100 ppm": benchmark.DISTORTIONS["clock drift 100 ppm"]}, [(0, 0.5)],
                          absolute=True)
    assert abs(one["noise SNR 20 dB"][0][2]) < 20 and abs(drift["clock drift 100 ppm"][0][2]) < 20


def test_stress_cases_need_a_long_reference(reference):
    assert benchmark.run_stress(reference[: SR * 30]) == {}
    results = benchmark.run_stress(reference)
    assert len(results) == len(benchmark.OVERLAPS_S) + 2
    assert any(label.startswith("overlap") for label in results) and any("periodic" in label for label in results)


def test_periodic_reference_repeats_only_when_exact(reference):
    exact = benchmark.periodic_reference(reference, True)
    loop = benchmark.LOOP_SECONDS * SR
    assert np.array_equal(exact[:loop], exact[loop:2 * loop]) and len(exact) == len(reference)
    assert not np.array_equal(benchmark.periodic_reference(reference, False)[:loop],
                              benchmark.periodic_reference(reference, False)[loop:2 * loop])


def test_run_all_combines_both_kinds(reference):
    results = benchmark.run_all(reference)
    assert "clean" in results and any("periodic" in name for name in results)


def test_statistics_summary_and_saving(tmp_path):
    results = {"good": [(0, 0, 1.0), (0, 0, -2.0)], "bad": [(0, 0, 100.0), (0, 0, 5.0)]}
    stats = benchmark.statistics(results, 20)
    assert stats["good"] == {"ok": 2, "total": 2, "median_ms": 1.5, "max_ms": 2}
    assert stats["bad"]["ok"] == 1
    text = benchmark.summarize(results, 20)
    assert "good" in text and "tolerance 20 ms" in text

    path = tmp_path / "out.json"
    benchmark.save_statistics(path, "a.flac", 12.34, stats, 20)
    benchmark.save_statistics(path, "b.mp4", 5, stats, 20)  # merged, not replaced
    data = json.loads(path.read_text())
    assert set(data["references"]) == {"a.flac", "b.mp4"} and data["references"]["a.flac"]["duration_s"] == 12.3


def test_load_reference_decodes_video_files_with_ffmpeg(tmp_path):
    from conftest import EXAMPLE_VIDEOS

    audio = benchmark.load_reference(EXAMPLE_VIDEOS[0])
    assert audio.ndim == 1 and len(audio) / SR == pytest.approx(26.9, abs=0.3)


def test_main_prints_and_saves(monkeypatch, tmp_path, capsys, reference):
    out = tmp_path / "bench.json"
    monkeypatch.setattr(benchmark, "load_reference", lambda path: reference[: SR * 20])
    monkeypatch.setattr(benchmark, "DISTORTIONS", {"clean": benchmark.DISTORTIONS["clean"]})
    monkeypatch.setattr(sys, "argv", ["benchmark", "--details", "--one-sided", "--save", str(out), "--tolerance-ms", "0.001"])
    benchmark.main()
    printed = capsys.readouterr().out
    assert "reference:" in printed and "cases in" in printed and "saved to" in printed
    assert json.loads(out.read_text())["references"]
