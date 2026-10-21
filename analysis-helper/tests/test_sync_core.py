"""Audio-based video synchronisation: shift calculation, audio extraction, trimming, full sync run."""
import subprocess

import numpy as np
import pytest

from conftest import requires_ffmpeg

SR = 16000


def noise(seconds, seed=0):
    return np.random.default_rng(seed).standard_normal(int(SR * seconds))


@pytest.mark.parametrize("delay_samples", [0, 800, 8000, 24000])
def test_shift_is_minus_the_delay_of_the_second_signal(delay_samples):
    from analysis_helper.sync.video_synch import calculate_shift_fft

    first = noise(3)
    second = np.concatenate([np.zeros(delay_samples), first])
    assert calculate_shift_fft(first, second) == -delay_samples
    assert calculate_shift_fft(second, first) == delay_samples


def test_shift_larger_than_half_the_signal_keeps_its_sign():
    from analysis_helper.sync.video_synch import calculate_shift_fft

    short = noise(1)
    long = np.concatenate([np.zeros(SR * 4), short])
    assert calculate_shift_fft(short, long) == -SR * 4


def test_shift_with_plot_draws_without_error(monkeypatch):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from analysis_helper.sync.video_synch import calculate_shift_fft

    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    first = noise(1)
    assert calculate_shift_fft(first, np.concatenate([np.zeros(100), first]), plot=True) == -100
    plt.close("all")


def make_video(path, seed, delay_ms=0, seconds=4):
    """Black video whose sound is seeded noise, optionally delayed (silence in front)."""
    delay = f",adelay={delay_ms}:all=1" if delay_ms else ""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=160x120:r=10:d={seconds + 1}",
         "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:seed={seed}:sample_rate=44100{delay}",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout)


@requires_ffmpeg
def test_extract_audio_tracks_makes_mono_16k_wav(tmp_path):
    from analysis_helper.sync.video_synch import extract_audio_tracks

    video = make_video(tmp_path / "v.mp4", 1)
    extract_audio_tracks(video)
    wav = tmp_path / "v.wav"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels,sample_rate",
                            "-of", "csv=p=0", str(wav)], capture_output=True, text=True, check=True).stdout.strip()
    assert probe == f"{SR},1"
    target = tmp_path / "chosen.wav"
    extract_audio_tracks(video, target)
    assert target.exists()


@requires_ffmpeg
def test_trim_video_with_start_end_and_default_output(tmp_path):
    from analysis_helper.sync.video_synch import trim_video

    video = make_video(tmp_path / "v.mp4", 1, seconds=6)
    trim_video(video, start_time=2, end_time=4)
    assert duration(tmp_path / "v_trimmed.mp4") == pytest.approx(2, abs=0.5)
    trim_video(video, start_time=3, output_path=tmp_path / "rest.mp4")
    assert duration(tmp_path / "rest.mp4") == pytest.approx(duration(video) - 3, abs=1.0)


@requires_ffmpeg
@pytest.mark.parametrize("first_is_delayed", [False, True])
def test_sync_videos_cuts_the_one_that_starts_earlier(tmp_path, monkeypatch, first_is_delayed):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from analysis_helper.sync.video_synch import sync_videos

    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    delayed = make_video(tmp_path / "delayed.mp4", 7, delay_ms=1500)
    plain = make_video(tmp_path / "plain.mp4", 7)
    first, second = (delayed, plain) if first_is_delayed else (plain, delayed)

    sync_videos(first, second)

    results = tmp_path / "results"
    out_first, out_second = results / f"{first.stem}_sync.mp4", results / f"{second.stem}_sync.mp4"
    assert out_first.exists() and out_second.exists()
    # the delayed recording lost its 1.5 s of silence in front, the other one is kept as is
    assert duration(results / "delayed_sync.mp4") == pytest.approx(duration(delayed) - 1.5, abs=0.6)
    assert duration(results / "plain_sync.mp4") == pytest.approx(duration(plain), abs=0.3)
    plt.close("all")
