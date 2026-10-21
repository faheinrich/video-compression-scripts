"""The choices of the settings drawer, shared by the main page and the compression lab."""

RENDERERS = ["libx265", "videotoolbox"]  # index = encoder combo index = saved renderer_index
# (CRF for libx265, quality for VideoToolbox); "archive" matches the long-standing defaults.
QUALITY_PRESETS = {"small": (26, 45), "archive": (20, 65), "high": (17, 80)}
RESOLUTIONS = [None, 3840, 2560, 1920, 1280, 720]
FRAME_RATES = [None, 60, 50, 30, 25, 24]
X265_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
