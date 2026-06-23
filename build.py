import os
import sys
import subprocess
import platform

def main():
    print("Starting build process for Video Helper Tools...")
    
    # Ensure pyinstaller is installed
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    separator = ";" if platform.system() == "Windows" else ":"
    
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--name", "Video Helper Tools",
        "--windowed",
        "--icon", f"docs/icons/video-helper-tools-512.png",
        "--add-data", f"docs{separator}docs",
        "--add-data", f"settings.json{separator}.",
        "--hidden-import", "PyQt5",
        "--hidden-import", "PyQt5.QtCore",
        "--hidden-import", "PyQt5.QtGui",
        "--hidden-import", "PyQt5.QtWidgets",
        "--hidden-import", "cv2",
        "--hidden-import", "torch",
        "--hidden-import", "torchaudio",
        "main.py"
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    
    print("Build complete. Check the 'dist' directory.")

if __name__ == "__main__":
    main()
