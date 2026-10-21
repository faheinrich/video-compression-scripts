"""Cross-platform alternative to build.sh (e.g. on Windows without bash): `uv run python build.py`."""
import platform
import subprocess
from pathlib import Path

APP = "analysis-helper"
TITLE = "Analysis Helper"
HERE = Path(__file__).resolve().parent


def main():
    sep = ";" if platform.system() == "Windows" else ":"
    cmd = [
        "pyinstaller", "--noconfirm", "--name", TITLE, "--windowed",
        "--icon", "resources/app-icon.png",
        "--add-data", f"resources{sep}resources",
        "--add-data", f"docs{sep}docs",
        "--hidden-import", "PySide6.QtMultimedia", "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--exclude-module", "PyQt5",
        "--hidden-import", "cv2", "--hidden-import", "torch",
        "main.py",
    ]
    subprocess.check_call(["uv", "sync", "--inexact", "--package", APP, "--group", "dev"], cwd=HERE.parent)
    subprocess.check_call(["uv", "run", "--package", APP, *cmd], cwd=HERE)
    print("Build complete. Check the 'dist' directory.")


if __name__ == "__main__":
    main()
