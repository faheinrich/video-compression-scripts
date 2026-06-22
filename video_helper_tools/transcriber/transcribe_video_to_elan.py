import argparse
import numpy as np
import librosa
import pympi
import requests
from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
from pathlib import Path

import tqdm

from .run_minimal_whisper_server import DEFAULT_SERVER_PORT, TranscriptionRequest, DEFAULT_SERVER_URL
from . import WHISPER_SERVER_ROOT_DIR

whisper_transcription_padding_length_ms = 200


def send_transcription_request(transcription_server_url, audio_signal, sample_rate):
    """Send a transcription request to the server containing the audio signal and sample rate."""
    # Create JSON data for the transcription request
    transcription_request_json = TranscriptionRequest(
        signal=[float(i) for i in audio_signal],
        audio_rate=int(sample_rate),
    ).model_dump()
    
    # Validate the JSON data against the TranscriptionRequest model. Only valid data can be processed by the server.
    assert TranscriptionRequest.model_validate(transcription_request_json), "Invalid JSON data"
    
    # Send the transcription request to the server and receive the response.
    result = requests.post(
        f"{transcription_server_url}/transcribe/",
        json=transcription_request_json,
    )
    if result.status_code == 200:
        # If the request was successful, extract the transcription text from the response json object.
        text = result.json()["transcription_text"]
        return text
    else:
        # If the request failed, print the status code and response text for debugging
        print(result.status_code)
        print(result.text[:1000])
        raise Exception(f"Server Response: Error {result.status_code}")


def transcribe_video(video_file_path: 'Path' or str, server_url: str, server_port: int,
                     padding_ms: int = 200,
                     vad_threshold: float = 0.2,
                     min_speech_duration_ms: int = 100,
                     tier_name: str = "Speech",
                     progress_callback=None,
                     stop_event=None):
    """Transcribe a video file and write the results into an ELAN file.
    :param stop_event: An optional event or object with an is_set() method to signal stopping.
    """
    transcription_server_url = f"http://{server_url}:{server_port}"
    
    # Convert to pathlib Path object if it's a string, easier to work with
    if isinstance(video_file_path, str):
        video_file_path = Path(video_file_path)
    
    # Check if the video file exists, throw an error if not
    assert video_file_path.exists(), f"Video file {video_file_path} does not exist."
    
    # extract audio from video, single audio channel, 16kHz for whisper annotation
    # This requires ffmpeg to be installed on the system.
    audio_path = video_file_path.with_suffix(".wav")
    if not audio_path.exists():
        print(f"Extracting audio from {video_file_path} to {audio_path}.")
        import subprocess
        subprocess.run([
            "ffmpeg", "-i", str(video_file_path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)
        ], check=False)
    
    # load audio signal again, with librosa. Maybe can be done with read_audio from silero...?
    audio_signal, sample_rate = librosa.load(audio_path, sr=16000)
    print(
        f"DEBUG: Loaded audio {audio_path}. dtype: {audio_signal.dtype}, shape: {audio_signal.shape}, sample_rate: {sample_rate}")
    print(f"DEBUG: Audio normalization check. Min: {np.min(audio_signal):.4f}, Max: {np.max(audio_signal):.4f}")
    
    if progress_callback:
        progress_callback(-2, -2, audio_signal=audio_signal, sample_rate=sample_rate)
    
    # Create ELAN object
    eaf = pympi.Elan.Eaf()
    eaf.add_linguistic_type(tier_name)
    
    # Link media files
    eaf.add_linked_file(
        file_path=str(video_file_path),
        mimetype="video/mp4",
    )
    eaf.add_linked_file(
        file_path=str(audio_path),
    )
    eaf.add_tier(tier_id=tier_name, ling=tier_name)
    
    # Voice Activity Detection (VAD)
    silero_vad_model = load_silero_vad(onnx=True)
    wav = read_audio(str(audio_path))  # backend (sox, soundfile, or ffmpeg) required!
    
    if progress_callback:
        progress_callback(-1, -1, "Detecting speech segments with VAD...")
    
    speech_timestamps = get_speech_timestamps(
        audio=wav,
        model=silero_vad_model,
        return_seconds=True,
        sampling_rate=16000,
        threshold=vad_threshold,
        min_speech_duration_ms=min_speech_duration_ms,
        max_speech_duration_s=float("inf"),
        min_silence_duration_ms=100,
        speech_pad_ms=30,
        visualize_probs=False,
        progress_tracking_callback=None,
        window_size_samples=512,
    )
    
    print(f"Found {len(speech_timestamps)} speech segments.")
    if progress_callback:
        progress_callback(0, len(speech_timestamps), f"Found {len(speech_timestamps)} speech segments.",
                          speech_timestamps=speech_timestamps)
    
    for seg_idx, vad in tqdm.tqdm(
        enumerate(speech_timestamps),
        desc="Transcribing audio segments",
        unit="segment",
        total=len(speech_timestamps),
    ):
        if progress_callback:
            progress_callback(seg_idx, len(speech_timestamps))
        
        start_sec = vad["start"]
        end_sec = vad["end"]
        
        signal_index_start = int(
            (start_sec - (padding_ms / 1000)) * sample_rate
        )
        signal_index_end = int(
            (end_sec + (padding_ms / 1000)) * sample_rate
        )
        signal_segment = audio_signal[
            max(signal_index_start, 0): min(signal_index_end, len(audio_signal))
        ]
        
        if stop_event and hasattr(stop_event, "is_set") and stop_event.is_set():
            print("Transcription stopped by user.")
            return
        
        print(
            f"DEBUG: Sending segment {seg_idx}. Length: {len(signal_segment)} samples, Duration: {len(signal_segment) / sample_rate:.2f}s, Min: {np.min(signal_segment):.4f}, Max: {np.max(signal_segment):.4f}")
        
        text = send_transcription_request(transcription_server_url, signal_segment, sample_rate)
        
        transcription = " ".join(text.strip().split())  # remove double spaces
        
        if progress_callback:
            progress_callback(seg_idx, len(speech_timestamps), transcription=transcription, start_sec=start_sec,
                              end_sec=end_sec)
        
        print(transcription)
        
        seg_start_ms = int(start_sec * 1000)
        seg_end_ms = int(end_sec * 1000)
        eaf.add_annotation(
            tier_name,
            seg_start_ms,
            seg_end_ms,
            transcription,
        )
    
    if progress_callback:
        progress_callback(len(speech_timestamps), len(speech_timestamps))
    
    # Write eaf file
    eaf.to_file(file_path=str(video_file_path.with_suffix(".eaf")))
    
    for (
            segment_start_time_ms,
            segment_end_time_ms,
            annotation,
    ) in eaf.get_annotation_data_for_tier(tier_name):
        print(
            f"Segment: {segment_start_time_ms / 1000:.2f}s - {segment_end_time_ms / 1000:.2f}s | {annotation}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Annotate Video and write Results into ELAN File."
    )
    parser.add_argument("-u", "--url", type=str, default=DEFAULT_SERVER_URL, help="Server url.")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_SERVER_PORT, help="Server port.")
    
    parser.add_argument("-vp", "--video_path", default=WHISPER_SERVER_ROOT_DIR / "resources" / "video_test.mp4",
                        type=str,
                        help="Path to the video to transcribe.")
    parser.add_argument("--padding", type=int, default=200, help="Transcription padding in ms.")
    parser.add_argument("--vad_threshold", type=float, default=0.2, help="VAD threshold.")
    parser.add_argument("--min_speech_duration", type=int, default=100, help="Min speech duration in ms.")
    parser.add_argument("--tier_name", type=str, default="Speech", help="ELAN tier name.")
    
    args = parser.parse_args()
    transcribe_video(args.video_path, args.url, args.port,
                     padding_ms=args.padding,
                     vad_threshold=args.vad_threshold,
                     min_speech_duration_ms=args.min_speech_duration,
                     tier_name=args.tier_name)


if __name__ == "__main__":
    main()
