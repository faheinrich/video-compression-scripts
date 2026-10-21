# Changelog

All notable changes to the two apps and the shared core. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases are tagged per app:
`archive-v<version>` for Archive Helper, `analysis-v<version>` for Analysis Helper.

## [Unreleased]

### Both apps
- The overview page shows the version at the bottom left. At start the app asks GitHub once (in the background, no
  other data is sent) whether a newer release of the app exists and then shows "New version vX.Y.Z available" in
  orange next to it, linking to the release. Set `VIDEO_HELPER_TOOLS_NO_UPDATE_CHECK=1` to switch the check off.
- The About dialog links to the repository.
- Fixed: the tool names on the overview page are centred below their icons (a wide name pushed the icon aside).
- macOS packages are named `...-macOS-silicon.zip` (Apple Silicon only); the release notes now describe how to open
  an unsigned app on macOS 15 and later (System Settings > Privacy & Security > Open Anyway).

### Archive Helper
- Fixed: on macOS the native window title was drawn over the back button in the title bar and probably swallowed
  clicks on it. The native title is left empty there.
- Fixed: the quality hint under the Small / Archive / High buttons changed its length and moved the controls below it
  while the CRF slider was dragged. The hint now has a fixed height.

### Analysis Helper
- Fixed: the same title bar problem as in Archive Helper (shared window shell).

### Development
- Tests no longer run again for release tags; every test has a 300 s timeout and every CI job a 25 minute limit,
  after a test hung once on Linux.
- Added this changelog; removed the outdated roadmap.

## [archive-v0.0.1] and [analysis-v0.0.1] - 2026-10-21

The former single app "Video Helper Tools" is split in two apps that share the package `core`
(window shell, translations, styles, app data paths). The repository is a uv workspace with one lock file.
Each app now keeps its own settings and caches (`Archive Helper`, `Analysis Helper` in the per-user folders);
settings of the former app are copied once on first start.

### Archive Helper
- **Compress & Archive**: batch compression with FFmpeg (HEVC tagged `hvc1` for Apple Photos, optional VideoToolbox),
  metadata kept with ExifTool (capture date, GPS, camera data) and the file creation time copied; all audio streams and
  their names are kept; HDR sources stay HDR; resolution and frame-rate limits; results that would be larger than the
  original are skipped.
- Table view with auto-scan, summary, settings drawer, row numbers in processing order, draggable columns,
  "process next", replace / swap / delete actions, CSV export.
- Compare viewer with synchronised players, timeline and zoom; can also show just the original.
- The settings used are stored inside each result and shown in the table.
- Editable result postfix and a list of name endings to skip in the source folder; warning for videos that would get the
  same target name.
- Durations are read in parallel and cached; thumbnails are cached per file version, pruned after 90 days and can be
  cleared from the menu. The start button shows why it is disabled.
- **Backup (rsync)**: GUI around `rsync` with progress.
- German and English interface.

### Analysis Helper
- **Sync Videos**: shift between two recordings from their audio by FFT cross-correlation (linear, so shifts larger than
  half the signal length work), with waveform view and preview. The Info button explains the algorithm and shows its
  measured accuracy; `python -m analysis_helper.sync.benchmark` reproduces it with synthetic ground truth.
- **Transcribe Audio**: Whisper transcription of speech segments found by Silero VAD, written to ELAN `.eaf` files;
  local or remote server, the local server starts from the app bundle.
- German and English interface.

### Releases
- GitHub workflow builds macOS, Linux and Windows packages per app when its tag is pushed; the tag must match the
  version in the app's `pyproject.toml`.

[Unreleased]: https://github.com/faheinrich/video-helper-tools/compare/archive-v0.0.1...HEAD
[archive-v0.0.1]: https://github.com/faheinrich/video-helper-tools/releases/tag/archive-v0.0.1
[analysis-v0.0.1]: https://github.com/faheinrich/video-helper-tools/releases/tag/analysis-v0.0.1
