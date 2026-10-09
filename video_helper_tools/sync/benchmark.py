"""Benchmark for the shift algorithm (calculate_shift_fft) against a known ground truth.

Two excerpts are cut from one reference recording at different start times, so the true
shift is known exactly. Excerpt 2 is then distorted (noise, filters, reverb, codec, ...) to see how
robust the algorithm is. Run with:

    python -m video_helper_tools.sync.benchmark [--tolerance-ms 20] [--seed 0]
"""
import argparse
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import librosa
import numpy as np
from scipy import signal as sps

from .video_synch import calculate_shift_fft

SR = 16000  # the same rate the app uses for the calculation
REFERENCE = Path(__file__).resolve().parents[2] / "example_resources" / "longer-test-audio.flac"
RESULTS_FILE = Path(__file__).resolve().parents[2] / "docs" / "sync-benchmark.json"
EXCERPT_SECONDS = 40.0

# (start of excerpt 1, start of excerpt 2) in seconds of the reference. A negative start means the
# excerpt begins with silence, i.e. the recording started before the reference content.
# True shift = start2 - start1 (positive: video 1 started earlier, see VideoSyncGUI).
OFFSETS = [(0, 0), (0, 0.01), (0.02, 0), (0, 0.25), (1.0, 0), (0, 3.3333), (5.5, 0), (0, 7.77), (12.5, 0), (0, 20),
           (-2.0, 0), (0, -4.5), (3.0, 9.1234)]


def load_reference(path=REFERENCE):
    """Loads the audio of an audio or video file (the first track, mono, 16 kHz)."""
    try:
        audio, _ = librosa.load(str(path), sr=SR, mono=True)
    except Exception:  # containers libsndfile cannot read (mp4, mov): decode with ffmpeg
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp, "audio.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-map", "0:a:0", "-ac", "1", "-ar", str(SR), str(wav)], check=True)
            audio, _ = librosa.load(str(wav), sr=SR, mono=True)
    return audio


def excerpt(reference, start_s, length_s=EXCERPT_SECONDS):
    start, length = round(start_s * SR), round(length_s * SR)
    out = np.zeros(length, dtype=np.float32)
    lo, hi = max(start, 0), min(start + length, len(reference))
    if hi > lo:
        out[lo - start:hi - start] = reference[lo:hi]
    return out


# ---------------------------------------------------------------- distortions

def rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-12)


def butter(kind, cutoff):
    sos = sps.butter(4, cutoff, btype=kind, fs=SR, output="sos")
    return lambda x, rng: sps.sosfilt(sos, x).astype(np.float32)


def noise(snr_db):
    def apply(x, rng):
        return (x + rng.normal(0, rms(x) * 10 ** (-snr_db / 20), len(x))).astype(np.float32)
    return apply


def reverb(rt60):
    def apply(x, rng):
        t = np.arange(int(rt60 * SR)) / SR
        impulse = rng.normal(0, 1, len(t)) * np.exp(-6.9 * t / rt60)
        impulse[0] = 1.0
        wet = sps.fftconvolve(x, impulse / np.sqrt(np.sum(impulse ** 2)))[:len(x)]
        return (0.3 * x + wet).astype(np.float32)
    return apply


def clip(gain):
    return lambda x, rng: np.clip(x * gain, -0.5, 0.5).astype(np.float32)


def quantize(bits):
    levels = 2 ** (bits - 1)
    return lambda x, rng: (np.round(np.clip(x, -1, 1) * levels) / levels).astype(np.float32)


def hum(x, rng):
    t = np.arange(len(x)) / SR
    return (x + 0.3 * rms(x) * (np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 150 * t))).astype(np.float32)


def narrowband(x, rng):  # an 8 kHz phone-like recording
    low = librosa.resample(x, orig_sr=SR, target_sr=8000)
    return librosa.resample(low, orig_sr=8000, target_sr=SR)[:len(x)]


def codec(bitrate):
    """Round trip through low-bitrate AAC, like a video from a phone or an upload service."""
    def apply(x, rng):
        import soundfile
        with tempfile.TemporaryDirectory() as tmp:
            wav, enc = Path(tmp, "a.wav"), Path(tmp, "a.m4a")
            soundfile.write(wav, x, SR)
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", bitrate, str(enc)], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(enc), "-ar", str(SR), str(Path(tmp, "b.wav"))], check=True)
            decoded, _ = soundfile.read(Path(tmp, "b.wav"), dtype="float32")
        decoded = decoded if decoded.ndim == 1 else decoded.mean(axis=1)
        out = np.zeros(len(x), dtype=np.float32)
        out[:min(len(x), len(decoded))] = decoded[:len(x)]
        return out
    return apply


def drift(ppm):
    """Clock drift of the second recorder (the shift is only exact at the start of the excerpt)."""
    def apply(x, rng):
        stretched = sps.resample_poly(x, 10000 + round(ppm / 100), 10000).astype(np.float32)
        return stretched[:len(x)] if len(stretched) >= len(x) else np.pad(stretched, (0, len(x) - len(stretched)))
    return apply


DISTORTIONS = {
    "clean": lambda x, rng: x,
    "gain -30 dB": lambda x, rng: x * 0.0316,
    "inverted polarity": lambda x, rng: -x,
    "noise SNR 20 dB": noise(20),
    "noise SNR 5 dB": noise(5),
    "noise SNR -5 dB": noise(-5),
    "noise SNR -15 dB": noise(-15),
    "noise SNR -25 dB": noise(-25),
    "noise SNR -35 dB": noise(-35),
    "noise SNR -45 dB": noise(-45),
    "lowpass 3 kHz": butter("lowpass", 3000),
    "lowpass 500 Hz": butter("lowpass", 500),
    "highpass 300 Hz": butter("highpass", 300),
    "highpass 2 kHz": butter("highpass", 2000),
    "telephone 8 kHz": narrowband,
    "hard clipping": clip(20),
    "8-bit quantization": quantize(8),
    "50 Hz hum + harmonics": hum,
    "reverb RT60 0.4 s": reverb(0.4),
    "reverb RT60 1.5 s": reverb(1.5),
    "AAC 24 kbps": codec("24k"),
    "clock drift 100 ppm": drift(100),
    "clock drift 1000 ppm": drift(1000),
    "clock drift 5000 ppm": drift(5000),
    "lowpass 3 kHz + noise 5 dB + reverb": lambda x, rng: reverb(0.4)(noise(5)(butter("lowpass", 3000)(x, rng), rng), rng),
}


# ---------------------------------------------------------------- run

def estimate_shift(sig1, sig2):
    with contextlib.redirect_stdout(io.StringIO()):  # calculate_shift_fft prints debug output
        return calculate_shift_fft(sig1, sig2) / SR


def run(reference, distortions=DISTORTIONS, offsets=OFFSETS, tolerance_ms=20.0, seed=0, absolute=False, both=True):
    """Returns {name: [(true_shift_s, estimated_s, error_ms), ...]}.
    With absolute=True the offsets are used as they are (no scaling for short references).
    With both=True the distortion is applied to both excerpts, each with its own randomness (two different
    microphones and rooms); otherwise only excerpt 2 is distorted. Clock drift is always one-sided because it
    describes the difference between two devices."""
    results = {}
    for name, distort in distortions.items():
        rng = np.random.default_rng(seed)
        rows = []
        # Short references get shorter excerpts and proportionally smaller offsets.
        duration = len(reference) / SR
        length, scale = min(EXCERPT_SECONDS, 0.6 * duration), 1.0 if absolute else min(1.0, duration / 64)
        for start1, start2 in offsets:
            start1, start2 = start1 * scale, start2 * scale
            sig1 = excerpt(reference, start1, length)
            if both and not name.startswith("clock drift"):
                sig1 = distort(sig1, rng)
            sig2 = distort(excerpt(reference, start2, length), rng)
            truth, estimate = start2 - start1, estimate_shift(sig1, sig2)
            rows.append((truth, estimate, (estimate - truth) * 1000))
        results[name] = rows
    return results


# ---------------------------------------------------------------- stress cases (not distortions of one recording)

OVERLAPS_S = [10, 3, 1, 0.5]  # seconds of common content between the two excerpts
LOOP_SECONDS = 4


def periodic_reference(reference, exact):
    """A recording that repeats every LOOP_SECONDS, like a drum loop. With exact=False every repetition gets
    its own noise (SNR 10 dB), so the repetitions are similar but not identical."""
    rng = np.random.default_rng(1)
    loop = reference[: LOOP_SECONDS * SR]
    repeats = int(np.ceil(len(reference) / len(loop)))
    parts = [loop if exact else noise(10)(loop, rng) for _ in range(repeats)]
    return np.concatenate(parts)[: len(reference)]


def run_stress(reference, tolerance_ms=20.0, seed=0):
    """Cases beyond a distorted copy: little common content, periodic material. Needs a reference >= 60 s."""
    results = {}
    if len(reference) / SR < 60:
        return results
    length = min(EXCERPT_SECONDS, 0.6 * len(reference) / SR)
    clean = {"clean": DISTORTIONS["clean"]}
    for overlap in OVERLAPS_S:
        offsets = [(0, length - overlap), (length - overlap, 0)]
        rows = run(reference, clean, offsets, tolerance_ms, seed, absolute=True)["clean"]
        results[f"overlap {overlap:g} s of {length:.0f} s"] = rows
    for exact, label in ((False, f"periodic ({LOOP_SECONDS} s loop, SNR 10 dB between repeats)"), (True, f"periodic (exact {LOOP_SECONDS} s loop)")):
        results[label] = run(periodic_reference(reference, exact), clean, OFFSETS, tolerance_ms, seed)["clean"]
    return results


def run_all(reference, tolerance_ms=20.0, seed=0, both=True):
    results = run(reference, tolerance_ms=tolerance_ms, seed=seed, both=both)
    results.update(run_stress(reference, tolerance_ms, seed))
    return results


def statistics(results, tolerance_ms=20.0):
    stats = {}
    for name, rows in results.items():
        errors = np.abs([r[2] for r in rows])
        stats[name] = {"ok": int(np.sum(errors <= tolerance_ms)), "total": len(rows),
                       "median_ms": round(float(np.median(errors)), 1), "max_ms": round(float(errors.max()))}
    return stats


def save_statistics(path, reference_name, duration, stats, tolerance_ms):
    """Merges the results for one reference into a json file (read by the info dialog of the sync tool)."""
    path = Path(path)
    data = json.loads(path.read_text()) if path.exists() else {}
    data["tolerance_ms"] = tolerance_ms
    data.setdefault("references", {})[reference_name] = {"duration_s": round(duration, 1), "cases": stats}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def summarize(results, tolerance_ms=20.0):
    lines = [f"{'case':45} {'ok':>7} {'median |err|':>13} {'max |err|':>11}   (tolerance {tolerance_ms:g} ms)"]
    for name, rows in results.items():
        errors = np.abs([r[2] for r in rows])
        ok = int(np.sum(errors <= tolerance_ms))
        lines.append(f"{name:45} {ok:>3}/{len(rows):<3} {np.median(errors):>10.1f} ms {errors.max():>8.0f} ms")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance-ms", type=float, default=20.0)
    parser.add_argument("--reference", type=Path, default=REFERENCE, help="audio or video file to cut the excerpts from")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--one-sided", action="store_true", help="distort only the second excerpt (default: both)")
    parser.add_argument("--save", type=Path, nargs="?", const=RESULTS_FILE, help=f"merge the statistics into a json file (default {RESULTS_FILE.name})")
    parser.add_argument("--details", action="store_true", help="print every failed case")
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        DISTORTIONS.pop("AAC 24 kbps")
    reference = load_reference(args.reference)
    print(f"reference: {args.reference.name}, {len(reference) / SR:.1f} s")
    started = time.perf_counter()
    results = run_all(reference, tolerance_ms=args.tolerance_ms, seed=args.seed, both=not args.one_sided)
    print(summarize(results, args.tolerance_ms))
    if args.details:
        for name, rows in results.items():
            for truth, estimate, error in rows:
                if abs(error) > args.tolerance_ms:
                    print(f"  FAIL {name}: true {truth:+.4f} s, estimated {estimate:+.4f} s ({error:+.0f} ms)")
    if args.save:
        save_statistics(args.save, args.reference.name, len(reference) / SR, statistics(results, args.tolerance_ms), args.tolerance_ms)
        print(f"saved to {args.save}")
    total = sum(len(rows) for rows in results.values())
    print(f"{total} cases in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()
