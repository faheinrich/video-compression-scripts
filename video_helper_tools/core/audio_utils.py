import subprocess
import librosa
import numpy as np

def extract_audio(video_path, audio_path):
    """Extract audio from video using FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "aac", str(audio_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def load_audio_signal(audio_path, sr=16000):
    """Load audio file using librosa."""
    sig, loaded_sr = librosa.load(str(audio_path), sr=sr, mono=True)
    return sig, loaded_sr

def calculate_shift_fft(sig1, sig2):
    """Calculate the shift between two signals using FFT-based cross-correlation."""
    # Ensure they have the same length for correlation
    n = len(sig1) + len(sig2) - 1
    # Pad to next power of 2 for speed
    size = 1 << (n - 1).bit_length()
    
    f1 = np.fft.fft(sig1, size)
    f2 = np.fft.fft(sig2, size)
    
    # Cross-correlation
    corr = np.fft.ifft(f1 * np.conj(f2))
    shift = np.argmax(np.abs(corr))
    
    if shift > size / 2:
        shift -= size
        
    return shift
