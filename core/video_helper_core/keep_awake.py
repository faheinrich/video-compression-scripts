"""Keeps the computer from going to sleep while a long job runs (compression, backup)."""
import os
import shutil
import subprocess
import sys


class KeepAwake:
    """start() / stop() are safe to call repeatedly. Nothing happens when the platform offers no way to do it."""

    def __init__(self, reason="a job is running"):
        self.reason = reason
        self.process = None
        self.active = False

    def start(self):
        if self.active:
            return
        self.active = True
        if sys.platform == "darwin":
            # -i: no idle sleep (the display may still go off); -w: ends by itself when this app does
            self.process = self._spawn(["caffeinate", "-i", "-w", str(os.getpid())])
        elif sys.platform == "win32":
            import ctypes

            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif shutil.which("systemd-inhibit"):
            watch = f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 5; done"
            self.process = self._spawn(["systemd-inhibit", "--what=sleep", "--who=Video Helper",
                                        f"--why={self.reason}", "sh", "-c", watch])

    def stop(self):
        if not self.active:
            return
        self.active = False
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS alone clears the request
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.process = None

    @staticmethod
    def _spawn(command):
        try:
            return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None
