"""Cross-platform alternative to build.sh (e.g. on Windows without bash): `uv run python build.py`."""
import platform
import subprocess
from pathlib import Path

APP = "archive-helper"
TITLE = "Archive Helper"
HERE = Path(__file__).resolve().parent


def main():
    sep = ";" if platform.system() == "Windows" else ":"
    cmd = [
        "pyinstaller", "--noconfirm", "--name", TITLE, "--windowed",
        "--icon", "resources/app-icon.png",
        "--add-data", f"resources{sep}resources",
        "--add-data", f"docs{sep}docs",
        # exiftool config for the tag that records the compression settings in each result
        "--add-data", f"archive_helper/compressor/exiftool_vht.config{sep}archive_helper/compressor",
        "--hidden-import", "PySide6.QtMultimedia", "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--exclude-module", "PyQt5",
        "main.py",
    ]
    subprocess.check_call(["uv", "sync", "--inexact", "--package", APP, "--group", "dev"], cwd=HERE.parent)
    subprocess.check_call(["uv", "run", "--package", APP, *cmd], cwd=HERE)
    print("Build complete. Check the 'dist' directory.")


if __name__ == "__main__":
    main()
