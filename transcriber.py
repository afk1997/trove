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


import json as _json


def _load_pywhispercpp_model(model_path: str):
    """Indirection so tests can monkeypatch."""
    from pywhispercpp.model import Model
    return Model(model_path, n_threads=os.cpu_count() or 4, print_progress=False)


def run_transcribe(*, audio_path: str, model_path: str,
                   progress_cb=None, cancel_check=None) -> TranscriptResult:
    """Run whisper.cpp on audio_path with model at model_path.

    progress_cb(pct: int)        — called periodically with 0..100
    cancel_check() -> bool       — checked before/after work; if True, abort

    Returns a TranscriptResult. On cancel, .error == "cancelled" with empty
    segments/words.
    """
    if cancel_check and cancel_check():
        return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")

    if progress_cb:
        progress_cb(2)  # signal "starting"

    try:
        model = _load_pywhispercpp_model(model_path)
    except Exception as e:
        return TranscriptResult(language="", duration=0.0, segments=[], words=[],
                                error=f"model_load_error: {e}")

    if cancel_check and cancel_check():
        return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")

    if progress_cb:
        progress_cb(10)

    try:
        # word_timestamps=True asks whisper.cpp for word-level timing
        raw_segments = model.transcribe(audio_path, word_timestamps=True)
    except Exception as e:
        return TranscriptResult(language="", duration=0.0, segments=[], words=[],
                                error=f"transcribe_error: {e}")

    if cancel_check and cancel_check():
        return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")

    segments = []
    words = []
    duration = 0.0
    for seg in raw_segments:
        seg_start = float(getattr(seg, "t0", 0.0))
        seg_end = float(getattr(seg, "t1", 0.0))
        duration = max(duration, seg_end)
        seg_words = []
        for w in (getattr(seg, "words", None) or []):
            wd = {
                "w": getattr(w, "text", "").strip(),
                "start": float(getattr(w, "t0", 0.0)),
                "end": float(getattr(w, "t1", 0.0)),
            }
            seg_words.append(wd)
            words.append(wd)
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": getattr(seg, "text", "").strip(),
            "words": seg_words,
        })

    try:
        language = model.detected_language() or ""
    except Exception:
        language = ""

    if progress_cb:
        progress_cb(100)

    return TranscriptResult(
        language=language,
        duration=duration,
        segments=segments,
        words=words,
        error=None,
    )


def write_artifacts(result: TranscriptResult, base_path: str) -> None:
    """Write .txt / .srt / .vtt / .words.json next to the media file.

    base_path is the path WITHOUT extension, e.g. 'downloads/abc123'.
    """
    # .txt — segments joined
    txt = "\n\n".join(s["text"] for s in result.segments)
    with open(base_path + ".txt", "w") as f:
        f.write(txt + ("\n" if txt and not txt.endswith("\n") else ""))

    # .words.json — for the viewer page
    with open(base_path + ".words.json", "w") as f:
        _json.dump({
            "language": result.language,
            "duration": result.duration,
            "segments": result.segments,
            "words": result.words,
        }, f)

    # .srt
    with open(base_path + ".srt", "w") as f:
        for i, seg in enumerate(result.segments, 1):
            f.write(f"{i}\n")
            f.write(f"{_format_timestamp(seg['start'], srt=True)} --> {_format_timestamp(seg['end'], srt=True)}\n")
            f.write(seg["text"] + "\n\n")

    # .vtt
    with open(base_path + ".vtt", "w") as f:
        f.write("WEBVTT\n\n")
        for seg in result.segments:
            f.write(f"{_format_timestamp(seg['start'], srt=False)} --> {_format_timestamp(seg['end'], srt=False)}\n")
            f.write(seg["text"] + "\n\n")


def _format_timestamp(seconds: float, *, srt: bool) -> str:
    """SRT uses , as decimal sep; VTT uses ."""
    if seconds < 0: seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    sep = "," if srt else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"
