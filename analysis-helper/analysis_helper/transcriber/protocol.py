"""Client/server contract for the Whisper server. Kept free of torch/transformers so clients import fast."""
from typing import List

from pydantic import BaseModel

DEFAULT_SERVER_URL = "127.0.0.1"
DEFAULT_SERVER_PORT = 8080


class TranscriptionRequest(BaseModel):
    signal: List[float]
    audio_rate: int


class TranscriptionResult(BaseModel):
    transcription_text: str
