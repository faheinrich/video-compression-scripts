import pytest

from video_helper_tools.sync import benchmark

pytestmark = pytest.mark.skipif(not benchmark.REFERENCE.exists(), reason="reference audio missing")

TOLERANCE_MS = 20.0
# Distortions the algorithm must always survive; the full list is the benchmark's job (python -m video_helper_tools.sync.benchmark).
MUST_PASS = ["clean", "gain -30 dB", "noise SNR 5 dB", "lowpass 3 kHz", "highpass 300 Hz", "telephone 8 kHz", "clock drift 100 ppm"]


def test_shift_matches_ground_truth():
    reference = benchmark.load_reference()
    results = benchmark.run(reference, {name: benchmark.DISTORTIONS[name] for name in MUST_PASS})
    for name, rows in results.items():
        for truth, estimate, error_ms in rows:
            assert abs(error_ms) <= TOLERANCE_MS, f"{name}: true {truth:+.3f} s, estimated {estimate:+.3f} s"


def test_shift_larger_than_half_the_signal():
    # A circular correlation reports these with the opposite sign.
    reference = benchmark.load_reference()
    offsets = [(0, 25), (25, 0), (-3, 22), (0, -25)]
    results = benchmark.run(reference, {"clean": benchmark.DISTORTIONS["clean"]}, offsets)
    for truth, estimate, error_ms in results["clean"]:
        assert abs(error_ms) <= TOLERANCE_MS, f"true {truth:+.3f} s, estimated {estimate:+.3f} s"
