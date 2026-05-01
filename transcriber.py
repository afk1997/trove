"""Transcriber — pywhispercpp wrapper + ffmpeg audio extraction.

extract_audio(src, dst): ffmpeg → 16 kHz mono WAV
run_transcribe(audio_path, model_path, ...): pywhispercpp run; returns
    {"language", "duration", "segments", "words"} dict.
"""
from __future__ import annotations
import os
import subprocess
from dataclasses import dataclass


@dataclass
class TranscriptResult:
    language: str
    duration: float
    segments: list  # [{"start": float, "end": float, "text": str, "words": [...]}, ...]
    words: list     # [{"start": float, "end": float, "w": str}, ...]
    error: str | None = None


def extract_audio(src: str, dst: str) -> None:
    """Extract audio from src into 16 kHz mono PCM WAV at dst.

    Raises RuntimeError if ffmpeg exits non-zero.
    """
    argv = [
        "ffmpeg", "-y", "-i", src,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        dst,
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {proc.stderr.strip()[-300:]}")
