import argparse
import asyncio

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI
from transformers import pipeline
from transformers.utils import is_flash_attn_2_available

from pydantic import BaseModel
from typing import List

DEFAULT_SERVER_URL = "127.0.0.1"
DEFAULT_SERVER_PORT = 8080

class TranscriptionRequest(BaseModel):
    signal: List[float]
    audio_rate: int

class TranscriptionResult(BaseModel):
    transcription_text: str

app = FastAPI()


class TranscriptionHandler:
    def __init__(self, model_name: str = "openai/whisper-large-v3", language: str = "en"):
        self.device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        self.whisper_model = model_name
        self.language = language
        print(f"Loading model {self.whisper_model} on device {self.device} for language {self.language}.")
        
        self.pipe_ifw = pipeline(
            "automatic-speech-recognition",
            model=self.whisper_model,
            torch_dtype=torch.float32 if self.device == "mps" else torch.float16,
            device=self.device,
            model_kwargs=(
                {"attn_implementation": "flash_attention_2"}
                if is_flash_attn_2_available()
                else {}
            ),
            ignore_warning=True,
        )
    
    def transcribe(self, transcription_request: TranscriptionRequest) -> TranscriptionResult:
        print(
            f"DEBUG: Received transcription request. Signal length: {len(transcription_request.signal)}, Sample rate: {transcription_request.audio_rate}")
        signal = np.array(transcription_request.signal, dtype=np.float32)
        print(f"DEBUG: Signal converted to numpy. dtype: {signal.dtype}, shape: {signal.shape}")
        transcription = self.transcribe_insanely_fast_whisper(signal, transcription_request.audio_rate)
        return TranscriptionResult(transcription_text=transcription)
    
    def transcribe_insanely_fast_whisper(self, audio_signal, sample_rate: float, prompt: str = ""):
        assert sample_rate == 16000, "Sample rate must be 16000 for whisper."
        
        # Determine if we should use chunking based on audio length
        # Whisper's native context is 30 seconds.
        audio_duration = len(audio_signal) / sample_rate
        
        # Force audio signal to float32 and ensure it's on CPU if it's not already
        audio_signal = np.array(audio_signal, dtype=np.float32)
        
        # Normalize audio signal to [-1, 1] if it's not already
        max_val = np.max(np.abs(audio_signal))
        if max_val > 1.0:
            audio_signal = audio_signal / max_val
        
        print(
            f"DEBUG: Transcribing {audio_duration:.2f}s of audio. Min: {np.min(audio_signal):.4f}, Max: {np.max(audio_signal):.4f}, Mean: {np.mean(audio_signal):.4f}")
        
        kwargs = {
            "batch_size": 1,  # Reduced batch size for stability
            "return_timestamps": True,
            "generate_kwargs": {"language": self.language, "task": "transcribe", "do_sample": False},
        }
        
        # Only use experimental chunking for long audio
        if audio_duration > 30:
            kwargs["chunk_length_s"] = 30
        
        outputs = self.pipe_ifw(audio_signal, **kwargs)
        
        if "chunks" in outputs:
            text = " ".join([chunk["text"] for chunk in outputs["chunks"]]).strip()
        else:
            text = outputs.get("text", "").strip()
        text = " ".join(text.split())
        return text


transcription_handler = None


@app.post("/transcribe/", response_model=TranscriptionResult)
async def transcribe(transcription_request: TranscriptionRequest) -> TranscriptionResult:
    """ Server request to transcribe audio signal using the transcription handler.
    :param transcription_request: Received transcription request containing audio signal and sample rate.
    :return: TranscriptionResult containing the transcribed text.
    """
    res = transcription_handler.transcribe(transcription_request)
    print(
        f"Transcribing audio ({len(transcription_request.signal) / transcription_request.audio_rate:.2f}s): {res.transcription_text}")
    return res


def run_server(host: str, port: int, model_name: str = "openai/whisper-large-v3", language: str = "en"):
    global transcription_handler
    transcription_handler = TranscriptionHandler(model_name=model_name, language=language)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(app, host=host, port=port, loop=loop)
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())


def main():
    parser = argparse.ArgumentParser(
        description="Simple Whisper Transcription Server"
    )
    parser.add_argument("-u", "--url", type=str, default=DEFAULT_SERVER_URL, help="Server url.")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_SERVER_PORT, help="Server port.")
    parser.add_argument("-m", "--model", type=str, default="openai/whisper-large-v3", help="Whisper model name.")
    parser.add_argument("-l", "--language", type=str, default="en", help="Transcription language.")
    args = parser.parse_args()
    run_server(args.url, args.port, model_name=args.model, language=args.language)


if __name__ == "__main__":
    main()
