import os
from pathlib import Path

WHISPER_SERVER_ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))  # This is your Project Root

# A frozen app bundle cannot run `python -m ...`; it re-launches itself with this flag instead.
WHISPER_SERVER_FLAG = "--whisper-server"
