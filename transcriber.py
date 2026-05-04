"""Transcriber — pywhispercpp wrapper + ffmpeg audio extraction.

extract_audio(src, dst, ...): ffmpeg → 16 kHz mono WAV. Spawned via
    Popen so a long extract can be killed mid-flight when the user
    cancels — see the ``register_proc`` and ``cancel_check`` hooks.
run_transcribe(audio_path, model_path, ...): pywhispercpp run; returns
    a ``TranscriptResult``. Cancellation is best-effort during the
    inference C call (whisper.cpp emits per-segment callbacks; we use
    them to poll the cancel flag and abort early).
"""
from __future__ import annotations
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass


# Default ffmpeg timeout. The old 10-minute limit failed multi-hour
# lectures even though transcoding is faster than realtime — a 90-min
# source on a slow box can blow past 600s. 4h covers any practical
# input; an env override remains for unusual cases.
EXTRACT_AUDIO_TIMEOUT = int(os.environ.get("TROVE_EXTRACT_AUDIO_TIMEOUT", "14400"))


class _Cancelled(Exception):
    """Internal sentinel raised from the whisper segment callback to abort
    inference early when the user cancels mid-transcribe. Caught and
    converted to a cancelled TranscriptResult by ``run_transcribe``."""


@dataclass
class TranscriptResult:
    language: str
    duration: float
    segments: list  # [{"start": float, "end": float, "text": str, "words": [...]}, ...]
    words: list     # [{"start": float, "end": float, "w": str}, ...]
    error: str | None = None


def extract_audio(
    src: str,
    dst: str,
    *,
    cancel_check=None,
    register_proc=None,
    timeout: int | None = None,
) -> None:
    """Extract audio from src into 16 kHz mono PCM WAV at dst.

    Raises RuntimeError if ffmpeg exits non-zero (other than via cancel).

    Cancellation
    ------------
    The previous implementation called ``subprocess.run`` and held the
    GIL for up to the full timeout — so a user clicking "cancel" while
    ffmpeg was running just got an unfulfilled promise. Now ffmpeg is
    spawned via ``Popen``; the caller may pass:

      * ``cancel_check() -> bool`` — polled every 0.25s. When True, the
        ffmpeg process is killed and the (presumed-empty/partial) output
        WAV is unlinked.
      * ``register_proc(proc)`` — called once with the live ``Popen`` so
        the caller can stash the handle on a job for external kill.

    On cancel, raises ``RuntimeError("cancelled")``; the caller is
    expected to treat that as a clean abort, not a transcribe error.
    """
    argv = [
        "ffmpeg", "-y", "-i", src,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        dst,
    ]
    eff_timeout = timeout if timeout is not None else EXTRACT_AUDIO_TIMEOUT
    # ffmpeg writes ongoing progress to stderr — if we left stderr on a
    # PIPE without draining it, the OS pipe buffer fills (~64KB) and
    # ffmpeg blocks forever on its next write while we sit in wait().
    # Discard stdout entirely; capture stderr to a tempfile so we can
    # still surface it on failure. (Reader thread would also work, but
    # tempfile is simpler and ffmpeg never reads back from the file.)
    stderr_fd, stderr_path = tempfile.mkstemp(prefix="trove-ffmpeg-stderr.", suffix=".log")
    proc = None
    rc = None
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fd,
        )
        # The Popen has dup'd the fd; close our handle so stderr is flushed
        # cleanly when ffmpeg exits.
        os.close(stderr_fd)
        stderr_fd = -1

        if register_proc is not None:
            try:
                register_proc(proc)
            except Exception:
                # registration failure must never prevent the extract running
                pass

        started = time.monotonic()
        while True:
            try:
                rc = proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel_check is not None:
                try:
                    cancelled = bool(cancel_check())
                except Exception:
                    # Don't let a flaky cancel_check kill the run.
                    cancelled = False
                if cancelled:
                    proc.kill()
                    try: proc.wait(timeout=2)
                    except subprocess.TimeoutExpired: pass
                    # Best-effort cleanup of the partial WAV we asked for.
                    try:
                        if os.path.exists(dst):
                            os.remove(dst)
                    except OSError:
                        pass
                    raise RuntimeError("cancelled")
            if time.monotonic() - started > eff_timeout:
                proc.kill()
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired: pass
                raise RuntimeError(f"ffmpeg timed out after {eff_timeout}s")
    finally:
        if register_proc is not None:
            try:
                register_proc(None)
            except Exception:
                pass
        if stderr_fd >= 0:
            try: os.close(stderr_fd)
            except OSError: pass
        # Read + delete the stderr capture (only used on failure path below;
        # success path doesn't need it). Read AFTER ffmpeg exits so we get
        # the full content.
        stderr_text = ""
        try:
            with open(stderr_path, "r", errors="replace") as f:
                stderr_text = f.read()
        except OSError:
            pass
        try:
            os.unlink(stderr_path)
        except OSError:
            pass

    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (rc={rc}): {stderr_text.strip()[-300:]}")


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

    # Per-segment callback: poll cancel + nudge progress. Raising from
    # the callback propagates back through the pywhispercpp Cython
    # binding once the whisper.cpp loop checks for Python errors, so
    # this gives us best-effort mid-inference cancellation. (whisper.cpp
    # processes audio in 30-second windows; worst-case latency is one
    # window before the abort takes effect.)
    _seg_count = [0]
    def _on_segment(_seg):
        _seg_count[0] += 1
        if cancel_check and cancel_check():
            raise _Cancelled()
        # Heuristic progress: ramp 10→90 as segments arrive. We can't
        # know the true total ahead of time, so use a saturating curve.
        if progress_cb:
            n = _seg_count[0]
            pct = 10 + min(80, n // 4)
            try: progress_cb(pct)
            except Exception: pass

    try:
        # token_timestamps + max_len=1 + split_on_word=True → one Segment per word
        raw_segments = model.transcribe(
            audio_path,
            token_timestamps=True,
            max_len=1,
            split_on_word=True,
            new_segment_callback=_on_segment,
        )
    except _Cancelled:
        return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")
    except Exception as e:
        # Some Cython bindings wrap our _Cancelled in a different
        # exception type — catch that case explicitly.
        if cancel_check and cancel_check():
            return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")
        return TranscriptResult(language="", duration=0.0, segments=[], words=[],
                                error=f"transcribe_error: {e}")

    if cancel_check and cancel_check():
        return TranscriptResult(language="", duration=0.0, segments=[], words=[], error="cancelled")

    # Each Segment is a word: {.t0 (centiseconds), .t1, .text}.
    # Convert to seconds and build word array, then group into paragraphs.
    #
    # whisper.cpp without DTW (which pywhispercpp's build doesn't expose)
    # sets each word's t1 to the NEXT word's t0 — so a word followed by
    # a long silence inherits a duration that spans the entire silence.
    # That's wrong for the click-to-seek + highlight-tracking UI, where
    # the active-word marker would linger across seconds of silence.
    # Cap each word's emitted duration at WORD_MAX_DURATION; the click
    # target (start) is unaffected, the player's onTimeUpdate just
    # advances off the word once the audio passes its likely end.
    WORD_MAX_DURATION = 1.5
    words = []
    duration = 0.0
    for seg in raw_segments:
        # whisper.cpp uses centiseconds (1/100 sec); pywhispercpp passes through
        t0 = float(getattr(seg, "t0", 0)) / 100.0
        t1 = float(getattr(seg, "t1", 0)) / 100.0
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        if t1 - t0 > WORD_MAX_DURATION:
            t1 = t0 + WORD_MAX_DURATION
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


def realign_words_to_vad(result: "TranscriptResult", vad_chunks: list) -> None:
    """Snap whisper word timestamps to silero-vad speech regions.

    Whisper.cpp without DTW localizes words by cross-attention probability,
    which drifts earlier than the actual audio after every silence. The
    user-visible symptom: in a clip with a 1-second pause between turns,
    the active-word highlight races ahead of the playback by ~0.5 s, and
    the drift compounds as more silences accumulate.

    silero-vad is independently accurate on speech-region boundaries.
    Use its output as ground truth: any word whose ``start`` time falls
    in a non-speech gap is snapped forward to the next speech region's
    start. Word ends are clamped so they don't run into the next word
    or exceed 1.5 s, matching the duration cap applied at transcribe time.

    ``vad_chunks`` items may be dicts (``{"start", "end"}``) or objects
    with ``.start`` / ``.end`` attributes (e.g. ``diarizer.SpeakerChunk``).
    No-op when either input is empty.
    """
    if not result.words or not vad_chunks:
        return

    def _start(c):
        return float(c["start"]) if isinstance(c, dict) else float(getattr(c, "start", 0))

    def _end(c):
        return float(c["end"]) if isinstance(c, dict) else float(getattr(c, "end", 0))

    sorted_vad = sorted(vad_chunks, key=_start)
    words = result.words
    n = len(words)

    def _next_region_after(t: float):
        for c in sorted_vad:
            if _start(c) > t:
                return c
        return None

    def _in_region(t: float) -> bool:
        for c in sorted_vad:
            cs, ce = _start(c), _end(c)
            if cs <= t < ce:
                return True
            if cs > t:
                return False
        return False

    # Snap ONLY isolated gap-words (a single word whose start falls in a
    # silent region between two in-region neighbours). Whisper's biggest
    # alignment error is the first word after a silence — those are
    # routinely emitted ~0.3-0.5 s early, producing the visible "highlight
    # races ahead of the audio" effect.
    #
    # Multi-word gap RUNS are left alone. When whisper reorders a long
    # span of words across a silence (e.g. it places 6 words in the gap
    # before the actual speech region they belong to), nothing we can do
    # here recovers the truth — uniform-offset snapping would shove
    # later words past the vad region's end, then strict monotonicity
    # would chain-bump every following in-region word and crater accuracy.
    # Trying to fix this without ground-truth alignment (DTW) would make
    # things worse on average.
    for i in range(n):
        ws = float(words[i]["start"])
        if _in_region(ws):
            continue
        prev_in = i == 0 or _in_region(float(words[i - 1]["start"]))
        next_in = i == n - 1 or _in_region(float(words[i + 1]["start"]))
        if not (prev_in and next_in):
            continue  # part of a multi-word gap run — leave alone
        next_r = _next_region_after(ws)
        if next_r is None:
            continue  # trailing silence past every region
        words[i]["start"] = _start(next_r)

    # Monotonic-strict: each word.start must be > predecessor's. After
    # the uniform-offset snap a run of words has its original spacing,
    # but two adjacent words can still tie if whisper itself emitted
    # equal timestamps (it does this for very short tokens). Bump the
    # follower by a tiny amount in that case so the editor can still
    # distinguish them.
    for i in range(1, n):
        if words[i]["start"] <= words[i - 1]["start"]:
            words[i]["start"] = words[i - 1]["start"] + 0.01

    # Re-cap word.end so it doesn't run into the next word or exceed 1.5 s.
    WORD_MAX_DURATION = 1.5
    for i, w in enumerate(words):
        max_end = w["start"] + WORD_MAX_DURATION
        if i + 1 < n:
            max_end = min(max_end, words[i + 1]["start"])
        if w["end"] > max_end:
            w["end"] = max_end
        if w["end"] < w["start"]:
            w["end"] = w["start"] + 0.05  # 50 ms minimum so the highlight is visible

    # Segment timestamps are derived from their first/last word, so they
    # stay accurate after realignment if we re-derive them from the
    # (now-corrected) word objects each segment references.
    for seg in result.segments:
        seg_words = seg.get("words") or []
        if seg_words:
            seg["start"] = seg_words[0]["start"]
            seg["end"] = seg_words[-1]["end"]

    result.duration = max(
        result.duration,
        result.words[-1]["end"] if result.words else result.duration,
    )


def apply_speakers(result: "TranscriptResult", chunks: list) -> None:
    """Assign a speaker to each word and regroup ``result.segments``.

    Each word in ``result.words`` is tagged with the speaker of the
    diarization chunk that has MAXIMUM TEMPORAL OVERLAP with the word's
    [start, end) interval. Overlap (rather than start-only containment)
    keeps short words like "I", "yeah", "no" stable when their start
    falls a few ms inside the wrong chunk near a speaker boundary —
    the bulk of the word still belongs to the right speaker, so that's
    who it gets attributed to. Ties (equal overlap) go to the earlier
    chunk for determinism.

    Words that fall OUTSIDE any chunk (whisper detected speech where
    silero-vad didn't, e.g. a brief greeting or a one-word bridge in a
    tiny gap) inherit the speaker of their nearest assigned neighbor:
    forward-fill from the previous assigned word, with leading orphans
    backward-filled from the first assigned word.

    Without that fill step, every orphan word creates its own ``speaker=None``
    segment, fragmenting a single-speaker transcript into a mosaic of
    1-word "None" paragraphs interleaved with the real speaker's content.

    Then segments are rebuilt so that a paragraph break is produced on
    EITHER a speaker change OR the existing pause-gap rule.

    ``chunks`` items must have ``.start``, ``.end``, ``.speaker`` attrs
    (e.g. ``diarizer.SpeakerChunk``). No-op when chunks is empty.
    """
    if not result.words or not chunks:
        return
    sorted_chunks = sorted(chunks, key=lambda c: c.start)
    for w in result.words:
        ws = float(w["start"])
        we = float(w["end"])
        best_overlap = 0.0
        best_spk = None
        for c in sorted_chunks:
            # Chunks are sorted by start; once a chunk starts at or after
            # the word ends, no later chunk can overlap.
            if c.start >= we:
                break
            if c.end <= ws:
                # Entirely before this word; keep scanning forward.
                continue
            ov = min(we, c.end) - max(ws, c.start)
            # Strict ``>`` so that a tie goes to the earlier chunk
            # (preserves the legacy "first wins on overlap" behavior).
            if ov > best_overlap:
                best_overlap = ov
                best_spk = c.speaker
        w["speaker"] = best_spk

    # Pass 2: forward-fill None speakers from the previous assigned word.
    last_spk = None
    for w in result.words:
        if w.get("speaker") is not None:
            last_spk = w["speaker"]
        elif last_spk is not None:
            w["speaker"] = last_spk

    # Pass 3: backward-fill any leading orphans (words that came before
    # ANY assigned word) from the first speaker we ever saw.
    first_spk = None
    for w in result.words:
        s = w.get("speaker")
        if s is not None:
            first_spk = s
            break
    if first_spk is not None:
        for w in result.words:
            if w.get("speaker") is None:
                w["speaker"] = first_spk
            else:
                break

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
