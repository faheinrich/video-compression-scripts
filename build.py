import subprocess
import platform

def main():
    print("Starting build process for Video Helper Tools...")

    separator = ";" if platform.system() == "Windows" else ":"
    
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--name", "Video Helper Tools",
        "--windowed",
        "--icon", f"docs/icons/video-helper-tools-512.png",
        "--add-data", f"docs{separator}docs",
        # exiftool config for the tag that records the compression settings in each result
        "--add-data", f"video_helper_tools/compressor/exiftool_vht.config{separator}video_helper_tools/compressor",
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        # PyInstaller refuses to bundle when several Qt bindings are importable.
        "--exclude-module", "PyQt5",
        "--hidden-import", "cv2",
        "--hidden-import", "torch",
        "main.py"
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    
    print("Build complete. Check the 'dist' directory.")

if __name__ == "__main__":
    main()
