import subprocess
from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt
from matplotlib import pyplot as plt
import shutil

from . import PROJECT_ROOT_DIR


def convert_audio_for_whisper(audio_input_path: Path):
    """
    (This function is not used here and was only copied for reference how to run ffmpeg processes from python.)
    Converts an audio file to a 16kHz, 16-bit, mono wav file to match the requirements for the Whisper tool.
    """
    target_file = audio_input_path.parent / (
        audio_input_path.stem + "_converted.wav"
    )
    if not target_file.exists():
        print(f"Converting {audio_input_path} to {target_file}.")
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(audio_input_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(target_file),
                "-y",
                # "-loglevel",
                # "panic"
            ],
            check=True,
        )


def extract_audio_tracks(video_path: Path, audio_output_path: Path | None = None):
    """
    Extracts all audio tracks from a video file using ffmpeg and saves them as separate files in aac format.
    FIXME WARNING: How to extract all audio tracks? Currently only extracts the first audio track. This may be
     (very) important when dealing with screen recordings (i.e. created in OBS), which may have more audio tracks.
    :param video_path: Path to the video file from which to extract audio.
    :param audio_output_path: Path where the extracted audio file will be saved.
        If None, it will be saved in the same directory as the video file with ".aac" suffix.
    """
    if audio_output_path is None:
        audio_output_path = video_path.with_suffix(".aac")
    subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-map",
            f"0:a:0",  # Extract the first audio track only, todo how to do all? stereo, mono, etc.
            "-c:a",
            "copy",
            str(audio_output_path),
            "-y",
            "-loglevel",
            "panic"
        ],
        check=True,
    )


def calculate_shift_fft(signal1: npt.NDArray[float], signal2: npt.NDArray[float], plot=False):
    """Calculate the shift between two signals using FFT (Fast Fourier Transform).
    This function was created using ChatGPT, other AI friends and stack- and math-overflow,
        so I don't understand everything thats happening here in detail myself.
    :param signal1: First signal to compare, e.g. the original audio track.
    :param signal2: Second signal to compare, e.g. the shifted audio track.
    :param plot: If True, plots the original signals and the cross-correlation.
    :return: The calculated shift in samples between the two signals.
    """
    # Compute the FFT of both signals
    # NOTE: np.fft.fft returns an array of the same length as the input.
    # If signal lengths differ, the cross-spectrum multiplication below will
    # fail unless we explicitly pad/truncate to the same length.
    n1 = int(len(signal1))
    n2 = int(len(signal2))
    print(
        "[calculate_shift_fft] signal lengths:",
        n1,
        n2,
        "dtypes:",
        getattr(signal1, "dtype", None),
        getattr(signal2, "dtype", None),
        "shapes:",
        getattr(signal1, "shape", None),
        getattr(signal2, "shape", None),
    )

    if n1 != n2:
        # To compute cross-correlation via FFT we need a common FFT length.
        # Use max length and zero-pad the shorter signal.
        n = max(n1, n2)
        if n1 < n:
            signal1 = np.pad(signal1, (0, n - n1))
        if n2 < n:
            signal2 = np.pad(signal2, (0, n - n2))
        print(
            "[calculate_shift_fft] padded signals to common length:",
            n,
            "(n1 was",
            n1,
            ", n2 was",
            n2,
            ")",
        )

    fft_signal1 = np.fft.fft(signal1)
    fft_signal2 = np.fft.fft(signal2)
    
    # Compute the cross-spectrum
    cross_spectrum = fft_signal1 * np.conj(fft_signal2)
    
    # Compute the inverse FFT of the cross-spectrum to get the cross-correlation.
    cross_correlation = np.fft.ifft(cross_spectrum)
    
    # Find the index of the maximum in the cross-correlation
    shift = np.argmax(np.abs(cross_correlation))
    
    # Adjust shift for signals longer than half the length (to handle negative shifts)
    if shift > len(signal1) // 2:
        shift -= len(signal1)
    
    if plot:
        # Plot signals and cross-correlation
        time = np.arange(signal1.shape[0])
        fig, axs = plt.subplots(3, 1, figsize=(10, 8))
        axs[0].plot(time, signal1, label="Original Signal")
        axs[0].plot(time, signal2, label="Shifted Signal")
        axs[0].set_title("Signals")
        axs[0].legend()
        axs[2].plot(time, signal1, label="Original Signal")
        axs[2].plot(time - shift, signal2, label="Aligned Shifted Signal")
        axs[2].set_title("Aligned Signals After Calculating Shift")
        axs[2].legend()
        plt.tight_layout()
        plt.show()
    
    return shift


def trim_video(video_path: Path, start_time: float = 0.0, end_time: float | None = None,
               output_path: Path | None = None):
    """ Trim a video using ffmpeg.
    example for debugging: "ffmpeg - i vid2.mp4 - ss 00: 01:00 - t 00: 02:00 vid1_short.mp4 -y"
    
    :param video_path: Path to the video file to be trimmed.
    :param start_time: Start time in seconds from which to trim the video.
    :param end_time: End time in seconds until which to trim the video. If None, the video will be trimmed to its end.
    :param output_path: Path where the trimmed video will be saved.
        If None, it will be saved in the same directory as the original video with "_trimmed" suffix.
    """
    """
    Trim video using ffmpeg
    $ ffmpeg -i input.mp4 -ss 00:05:10 -to 00:15:30 -c:v copy -c:a copy output2.mp4
    """
    
    if output_path is None:
        output_path = video_path.parent / (video_path.stem + "_trimmed.mp4")
    
    start_time = f"{int(start_time // 3600):02}:{int((start_time % 3600) // 60):02}:{int(start_time % 60):02}"
    end_time = f"{int(end_time // 3600):02}:{int((end_time % 3600) // 60):02}:{int(end_time % 60):02}" if end_time is not None else None
    # If no end time is provided, use the duration of the video
    if end_time is None:
        # Get video duration (and other information) using ffprobe
        video_info = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             str(video_path)],
            capture_output=True, text=True, check=True
        )
        duration = float(video_info.stdout.strip())
        # Calculate end time based on start time and duration and format it for ffmpeg arguments
        end_time = f"{int(duration // 3600):02}:{int((duration % 3600) // 60):02}:{int(duration % 60):02}"
    
    print(start_time, "to", end_time)
    
    # Run ffmpeg command to trim the video
    subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-ss",  # start time
            start_time,
            "-to",  # end time
            end_time,
            str(output_path),
            "-y",  # overwrite output file if it exists
            # "-loglevel", # disable logging of ffmpeg
            # "panic"
        ],
        check=True,
    )


def sync_videos(vid_1_path: Path, vid_2_path: Path):
    """
    Synchronize two video files based on their audio tracks. The resulting synchronized
    videos (as well as temporary audio files) will be saved in a "results" folder next to the input video files.
    This has been tested with two short videos, each about two minutes long, further testing is needed with
        longer videos and longer delays.
    pathlib Path-objects are used for file paths as they are easier to work with than manually with strings.
    :param vid_1_path: pathlib Path-object to the first video file.
    :param vid_2_path: pathlib Path-object to the second video file.
    :return: None, but saves synchronized videos in the "results" folder.
    """
    results_folder_path = vid_1_path.parent / Path("results")
    results_folder_path.mkdir(parents=True, exist_ok=True)
    
    aud_1_path = results_folder_path / (vid_1_path.stem + ".aac")
    extract_audio_tracks(vid_1_path, audio_output_path=aud_1_path)
    
    aud_2_path = results_folder_path / (vid_2_path.stem + ".aac")
    extract_audio_tracks(vid_2_path, audio_output_path=aud_2_path)
    
    # We use the sample rate 16kHz. Only relevant here for calculating the shift, more samples may mean longer
    # Processing time? Was not really tested.
    sr = 16000
    
    signal_1, sample_rate = librosa.load(str(aud_1_path), sr=sr, mono=True)
    print(signal_1.shape)  # mono (1 channel)
    print("Duration in seconds", signal_1.shape[0] / sample_rate)  # duration of audio file in seconds
    
    signal_2, sample_rate = librosa.load(str(aud_2_path), sr=sr, mono=True)
    print(signal_2.shape)  # mono (1 channel)
    print("Duration in seconds", signal_2.shape[0] / sample_rate)  # duration of audio file in seconds
    
    # Calculate shift between the audio tracks
    shift = calculate_shift_fft(signal_1, signal_2, plot=True)
    print(f"Calculated shift: {shift} samples, which is {shift / sr:.2f} seconds.")
    
    if shift > 0:
        # vid_1 starts before vid_2, so we need to trim vid_1 and copy vid_2
        start_time = shift / sr
        print(f"Trimming {vid_1_path} by {start_time:.2f} seconds.")
        shutil.copy(vid_2_path, results_folder_path / (vid_2_path.stem + "_sync.mp4"))
        trim_video(vid_1_path, start_time=start_time, output_path=results_folder_path / (vid_1_path.stem + "_sync.mp4"))
    elif shift <= 0:
        # vid_2 starts before vid_1, so we need to trim vid_2 and copy vid_1
        start_time = -shift / sr
        print(f"Trimming {vid_2_path} by {start_time:.2f} seconds.")
        shutil.copy(vid_1_path, results_folder_path / (vid_1_path.stem + "_sync.mp4"))
        trim_video(vid_2_path, start_time=start_time, output_path=results_folder_path / (vid_2_path.stem + "_sync.mp4"))


if __name__ == "__main__":
    vid_1_path = PROJECT_ROOT_DIR / Path("example_videos", "vid1_short.mp4")
    vid_2_path = PROJECT_ROOT_DIR / Path("example_videos", "vid2_short.mp4")
    sync_videos(vid_1_path, vid_2_path)
