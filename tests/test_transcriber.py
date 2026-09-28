import os
import shutil
import subprocess
import sys
import types

from conftest import EXAMPLE_VIDEOS, REPO_ROOT, requires_ffmpeg


def test_app_startup_does_not_load_ml_stack():
    # Fresh interpreter: other tests may already have imported torch in this one.
    code = "import sys, main; print(sorted(m for m in ('torch', 'transformers', 'silero_vad') if m in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "[]"


@requires_ffmpeg
def test_transcribe_video_writes_elan_file(tmp_path, monkeypatch):
    """Real audio extraction + silero VAD; the Whisper server is replaced by a fake."""
    import requests
    from video_helper_tools.transcriber.transcribe_video_to_elan import transcribe_video

    requests_sent = []

    def fake_post(url, json):
        requests_sent.append(url)
        return types.SimpleNamespace(
            status_code=200, json=lambda: {"transcription_text": f"segment {len(requests_sent)}"}
        )

    monkeypatch.setattr(requests, "post", fake_post)

    video = tmp_path / "clip.mp4"
    shutil.copy(EXAMPLE_VIDEOS[0], video)
    transcribe_video(video, "127.0.0.1", 8080)

    eaf_files = list(tmp_path.glob("*.eaf"))
    assert len(eaf_files) == 1
    annotations = eaf_files[0].read_text().count("<ANNOTATION_VALUE>")
    assert annotations == len(requests_sent) > 0
