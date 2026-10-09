<p align="center">
  <img src="docs/armadillo-logo.png" alt="Video Helper Tools Logo" width="280">
</p>

# Video Helper Tools

Video Helper Tools is a unified suite of desktop and command-line utilities for working with videos and audio.
It combines three workflows into one project:

- **Compress & Archive** — batch-compress videos while preserving important metadata.
- **Sync Videos** — align two recordings using their audio tracks.
- **Transcribe Audio** — generate ELAN annotations from speech using Whisper and VAD.

The main entry point is a PySide6 (Qt 6) application that exposes all tools from a single landing page.

## Overview

This repository is designed as a practical helper toolkit rather than a single-purpose encoder or transcription app.
It is intended for:

- archiving large video collections,
- comparing original vs. processed video results,
- synchronizing multi-camera recordings,
- and producing transcription data for later manual review in ELAN.

## Features

### Compress & Archive

- Batch video compression with FFmpeg
- Metadata preservation with ExifTool
- Optional hardware acceleration on supported systems
- Automatic handling of cases where the compressed file would be larger than the original
- Support for resolution and frame-rate reduction to save storage
- GUI with live logs, progress display, and side-by-side preview
- HEVC output tagged `hvc1` so it imports into Apple Photos

### Sync Videos

- Extracts audio from two videos with FFmpeg
- Calculates offset between tracks
- Applies the detected shift to synchronize clips
- Includes a GUI for waveform visualization and preview before saving

### Transcribe Audio

- Uses Whisper-based transcription via a FastAPI server
- Voice Activity Detection with Silero VAD
- Writes results into ELAN `.eaf` files for later annotation
- Supports single-file and batch-style workflows through the GUI
- Can run locally or against a remote server

## Installation

### Python dependencies

The project is managed with [uv](https://docs.astral.sh/uv/). Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`; the Python version is pinned in `.python-version`.

```bash
uv sync
```

This creates `.venv` with the exact locked versions (including PyInstaller from the `dev` group).

### External dependencies

Some features rely on system tools that must be installed separately:

- **FFmpeg** / `ffprobe`
- **ExifTool**

Example installation commands:

```bash
# macOS
brew install ffmpeg exiftool

# Ubuntu / Debian
sudo apt update
sudo apt install ffmpeg libimage-exiftool-perl
```

## Running the suite

Start the combined desktop application with:

```bash
uv run main.py
```

This opens a PySide6 (Qt 6) window with a landing page for:

- Compress & Archive
- Sync Videos
- Transcribe Audio
- Backup (Rsync)

Saved defaults are stored per user, independent of the working directory: on macOS in `~/Library/Application Support/Video Helper Tools/settings.json` (thumbnails in `~/Library/Caches/Video Helper Tools/`). A `settings.json` from older versions in the current directory is copied there on first start.

## Running the tests

```bash
uv run pytest
```

The tests run headless (Qt `offscreen` platform) against the sample videos: GUI startup, video playback in the compare/sync players, a full compress run, and transcription with a mocked Whisper server. Tests needing FFmpeg or ExifTool are skipped if those tools are missing.

## Building a Standalone Application

You can package the application into a standalone macOS `.app` bundle or Windows `.exe` using PyInstaller.

To build the app, run the included script:

```bash
# macOS / Linux
./build.sh

# Windows (or cross-platform)
uv run python build.py
```

The bundled executable will be created in the `dist` directory. Please note that because of dependencies like PyTorch and OpenCV, the resulting application bundle will be large.

## Transcription workflow

The transcription workflow uses a client/server setup:

1. Start the Whisper FastAPI server.
2. Run the transcription client against a file or folder.
3. Review and correct the generated ELAN output if needed.

Both steps are installed as commands by `uv sync`:

```bash
uv run run-whisper-server
```

and then:

```bash
uv run annotate-to-elan --video_path YOURVIDEOFILE
```

If you need to point the client to a different host:

```bash
uv run annotate-to-elan --video_path YOURVIDEOFILE --url YOURHOST --port YOURPORT
```

## Project structure

The application is organized around a modular package named `video_helper_tools`.

- `main.py` — launches the combined GUI suite
- `video_helper_tools.compressor` — compression and archive workflow
- `video_helper_tools.sync` — audio-based video synchronization workflow
- `video_helper_tools.transcriber` — Whisper transcription and ELAN export workflow
- `video_helper_tools.rsync_gui` — GUI wrapper around `rsync` for folder backups
- `tests/` — headless pytest suite
- `docs/` — standalone documentation for each tool
- `example_resources/` — sample source media files

## Example assets

The repository includes sample media and screenshots to help demonstrate the tools:

- `example_resources/` contains two short sample videos (also used by the tests)
- `docs/armadillo-logo.png` is the project logo
- `docs/gui-demo-screenshot.png` shows the transcription GUI
- `docs/sync-gui-demo.png` shows the synchronization GUI

## Requirements

Python dependencies are declared in `pyproject.toml` (GUI: `PySide6`; audio/video: `numpy`, `librosa`, `matplotlib`, `opencv-python`; transcription: `torch`, `silero-vad`, `transformers`, `fastapi`, `uvicorn`, `pympi-ling`). FFmpeg, ffprobe and ExifTool come from your system installation (see above).

## Roadmap

- [x] Combine tools into a single suite
- [ ] Implement batch mode improvements for transcription
- [ ] Automatic subtitle insertion
- [ ] Visual quality vs. file size comparison tools
- [ ] Saveable default settings for each tab

## Who?
This project was created by and is maintained by me, Fabian Heinrich.

## License

This project is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/?ref=chooser-v1).