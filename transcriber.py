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


# Gap (in seconds) between consecutive words that triggers a new paragraph.
_PARAGRAPH_GAP_SECONDS = 1.0


def run_transcribe(*, audio_path: str, model_path: str,
                   progress_cb=None, cancel_check=None) -> TranscriptResult:
    """Run whisper.cpp on audio_path with model at model_path.

    progress_cb(pct: int)        — called periodically with 0..100
    cancel_check() -> bool       — checked before/after work; if True, abort

    Returns a TranscriptResult. On cancel, .error == "cancelled" with empty
    segments/words.

    Word-level timestamps come from setting `token_timestamps=True` plus
    `max_len=1` and `split_on_word=True`, which makes pywhispercpp emit
    one Segment per word. We then group consecutive words into pseudo-
    paragraphs by speech-pause gap.
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
        # token_timestamps + max_len=1 + split_on_word=True → one Segment per word
        raw_segments = model.transcribe(
            audio_path,
            token_timestamps=True,
            max_len=1,
            split_on_word=True,
        )
    except Exception as e:
        return TranscriptResult(language="", duration=0.0, segments=[], words=[],
                                error=f"transcribe_error: {e}")

    if cancel_check and cancel_check():
        return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")

    # Each Segment is a word: {.t0 (centiseconds), .t1, .text}.
    # Convert to seconds and build word array, then group into paragraphs.
    words = []
    duration = 0.0
    for seg in raw_segments:
        # whisper.cpp uses centiseconds (1/100 sec); pywhispercpp passes through
        t0 = float(getattr(seg, "t0", 0)) / 100.0
        t1 = float(getattr(seg, "t1", 0)) / 100.0
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        words.append({"w": text, "start": t0, "end": t1})
        duration = max(duration, t1)

    # Group consecutive words into paragraph-like segments
    segments = []
    if words:
        current_words = [words[0]]
        for w in words[1:]:
            gap = w["start"] - current_words[-1]["end"]
            if gap > _PARAGRAPH_GAP_SECONDS:
                # Flush current paragraph
                segments.append(_build_segment(current_words))
                current_words = [w]
            else:
                current_words.append(w)
        if current_words:
            segments.append(_build_segment(current_words))

    try:
        language = ""
        # detected_language is a method on Model in some versions, attribute in others
        if hasattr(model, "detected_language"):
            dl = model.detected_language
            language = (dl() if callable(dl) else dl) or ""
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


def _build_segment(words: list[dict], speaker: str | None = None) -> dict:
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": " ".join(w["w"] for w in words),
        "words": words,
        "speaker": speaker,
    }


def apply_speakers(result: "TranscriptResult", chunks: list) -> None:
    """Assign a speaker to each word and regroup ``result.segments``.

    Each word in ``result.words`` is tagged with the speaker of the
    diarization chunk whose [start, end) interval contains the word's
    start time. Then segments are rebuilt so that a paragraph break is
    produced on EITHER a speaker change OR the existing pause-gap rule.

    ``chunks`` items must have ``.start``, ``.end``, ``.speaker`` attrs
    (e.g. ``diarizer.SpeakerChunk``). No-op when chunks is empty.
    """
    if not result.words or not chunks:
        return
    sorted_chunks = sorted(chunks, key=lambda c: c.start)
    for w in result.words:
        ws = float(w["start"])
        spk = None
        for c in sorted_chunks:
            if c.start <= ws < c.end:
                spk = c.speaker
                break
            if c.start > ws:
                break
        w["speaker"] = spk

    new_segs: list[dict] = []
    current = [result.words[0]]
    cur_spk = result.words[0].get("speaker")
    for w in result.words[1:]:
        gap = float(w["start"]) - float(current[-1]["end"])
        wspk = w.get("speaker")
        if wspk != cur_spk or gap > _PARAGRAPH_GAP_SECONDS:
            new_segs.append(_build_segment(current, cur_spk))
            current = [w]
            cur_spk = wspk
        else:
            current.append(w)
    if current:
        new_segs.append(_build_segment(current, cur_spk))
    result.segments = new_segs


def write_artifacts(result: TranscriptResult, base_path: str) -> None:
    """Write .words.json (schema v2) + .txt / .srt / .vtt next to the media.

    base_path is the path WITHOUT extension, e.g. 'downloads/abc123'.

    The .words.json is emitted directly in schema v2 so freshly-transcribed
    files don't have to be migrated on first open. .txt/.srt/.vtt are
    rendered via ``transcript_io.regenerate_artifacts`` so the same code
    path is used after edits.
    """
    import transcript_io as _tio

    # Build flat words array with editor metadata.
    flat_words = []
    for i, w in enumerate(result.words):
        flat_words.append({
            "idx": i,
            "w": w["w"],
            "original_w": w["w"],
            "start": w["start"],
            "end": w["end"],
            "edited": False,
            "deleted": False,
        })

    # Build segments referencing words by idx (positional cursor matches the
    # grouping done above by run_transcribe).
    cursor = 0
    v2_segments = []
    for seg in result.segments:
        n = len(seg.get("words", []))
        v2_segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg.get("text", ""),
            "word_idxs": list(range(cursor, cursor + n)),
            "speaker": seg.get("speaker"),
        })
        cursor += n

    data = {
        "schema_version": _tio.SCHEMA_VERSION,
        "language": result.language,
        "duration": result.duration,
        "edited_at": None,
        "words": flat_words,
        "segments": v2_segments,
        "bookmarks": [],
    }

    _tio.save(base_path + ".words.json", data)
    _tio.regenerate_artifacts(data, base_path)
