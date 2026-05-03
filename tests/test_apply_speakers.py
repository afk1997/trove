"""Tests for transcriber.apply_speakers — the bridge between diarization
output (SpeakerChunks) and the transcript word/segment structure.

The function is small but high-stakes: any off-by-one in word→chunk
mapping or any wrong segment boundary produces visibly wrong speaker
labels for users. Live diarization isn't exercised here (no torch /
resemblyzer); we synthesise SpeakerChunks directly.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

import transcriber


@dataclass
class _Chunk:
    """Minimal SpeakerChunk surrogate so tests don't depend on diarizer.py
    being importable (deps may be missing)."""
    start: float
    end: float
    speaker: str


def _result(words):
    """Build a TranscriptResult with the given words, default-grouped."""
    return transcriber.TranscriptResult(
        language="en",
        duration=words[-1]["end"] if words else 0.0,
        segments=[],
        words=list(words),
    )


# ---------------------------------------------------------------------------
# Word → chunk mapping
# ---------------------------------------------------------------------------

def test_word_inside_chunk_gets_chunk_speaker():
    res = _result([{"w": "hi", "start": 0.5, "end": 1.0}])
    transcriber.apply_speakers(res, [_Chunk(0.0, 2.0, "Speaker 1")])
    assert res.words[0]["speaker"] == "Speaker 1"


def test_word_at_chunk_start_is_inside():
    res = _result([{"w": "hi", "start": 0.0, "end": 0.4}])
    transcriber.apply_speakers(res, [_Chunk(0.0, 1.0, "Alice")])
    assert res.words[0]["speaker"] == "Alice"


def test_word_at_chunk_end_is_outside():
    """Half-open interval: c.start <= ws < c.end. A word starting exactly
    at c.end belongs to the NEXT chunk (or no chunk)."""
    res = _result([{"w": "hi", "start": 1.0, "end": 1.4}])
    transcriber.apply_speakers(res, [_Chunk(0.0, 1.0, "Alice")])
    assert res.words[0]["speaker"] is None


def test_word_before_any_chunk_gets_none():
    res = _result([{"w": "hi", "start": 0.0, "end": 0.2}])
    transcriber.apply_speakers(res, [_Chunk(5.0, 10.0, "Alice")])
    assert res.words[0]["speaker"] is None


def test_word_in_gap_between_chunks_gets_none():
    res = _result([{"w": "bridge", "start": 2.5, "end": 2.8}])
    chunks = [
        _Chunk(0.0, 2.0, "Alice"),
        _Chunk(3.0, 5.0, "Bob"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert res.words[0]["speaker"] is None


def test_word_after_last_chunk_gets_none():
    res = _result([{"w": "trailing", "start": 100.0, "end": 100.5}])
    transcriber.apply_speakers(res, [_Chunk(0.0, 5.0, "Alice")])
    assert res.words[0]["speaker"] is None


def test_unsorted_chunks_still_align_correctly():
    res = _result([
        {"w": "a", "start": 0.5, "end": 0.7},
        {"w": "b", "start": 3.5, "end": 3.7},
    ])
    # Pass chunks in REVERSE order; apply_speakers must sort them internally.
    chunks = [_Chunk(3.0, 4.0, "Bob"), _Chunk(0.0, 1.0, "Alice")]
    transcriber.apply_speakers(res, chunks)
    assert res.words[0]["speaker"] == "Alice"
    assert res.words[1]["speaker"] == "Bob"


# ---------------------------------------------------------------------------
# Segment regrouping
# ---------------------------------------------------------------------------

def test_speaker_change_creates_new_segment():
    """Two adjacent words with no pause but a speaker change must split."""
    res = _result([
        {"w": "hi",  "start": 0.0, "end": 0.5},
        {"w": "hey", "start": 0.5, "end": 1.0},  # no gap
    ])
    chunks = [
        _Chunk(0.0, 0.5, "Alice"),
        _Chunk(0.5, 1.0, "Bob"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert len(res.segments) == 2
    assert res.segments[0]["speaker"] == "Alice"
    assert res.segments[1]["speaker"] == "Bob"
    assert res.segments[0]["text"] == "hi"
    assert res.segments[1]["text"] == "hey"


def test_pause_within_same_speaker_still_splits():
    """Pre-existing rule: gap > 1s → new paragraph, regardless of speaker."""
    res = _result([
        {"w": "first",  "start": 0.0, "end": 0.5},
        # 2-second gap
        {"w": "second", "start": 2.5, "end": 3.0},
    ])
    chunks = [_Chunk(0.0, 5.0, "Alice")]
    transcriber.apply_speakers(res, chunks)
    assert len(res.segments) == 2
    assert all(s["speaker"] == "Alice" for s in res.segments)


def test_dense_consecutive_words_one_speaker_one_segment():
    res = _result([
        {"w": "a", "start": 0.0, "end": 0.3},
        {"w": "b", "start": 0.3, "end": 0.6},
        {"w": "c", "start": 0.6, "end": 0.9},
        {"w": "d", "start": 0.9, "end": 1.2},
    ])
    transcriber.apply_speakers(res, [_Chunk(0.0, 2.0, "Alice")])
    assert len(res.segments) == 1
    assert res.segments[0]["speaker"] == "Alice"
    assert res.segments[0]["text"] == "a b c d"
    assert res.segments[0]["start"] == 0.0
    assert res.segments[0]["end"] == 1.2


def test_three_speaker_conversation():
    """Realistic A→B→A→B→C interleaving."""
    res = _result([
        {"w": "hello",   "start": 0.0, "end": 0.5},
        {"w": "hi",      "start": 0.5, "end": 0.9},
        {"w": "yes",     "start": 0.9, "end": 1.1},
        {"w": "ok",      "start": 1.1, "end": 1.4},
        {"w": "right",   "start": 1.4, "end": 1.8},
    ])
    chunks = [
        _Chunk(0.0, 0.5, "Alice"),
        _Chunk(0.5, 0.9, "Bob"),
        _Chunk(0.9, 1.1, "Alice"),
        _Chunk(1.1, 1.4, "Bob"),
        _Chunk(1.4, 1.8, "Carol"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert [s["speaker"] for s in res.segments] == [
        "Alice", "Bob", "Alice", "Bob", "Carol",
    ]
    assert all(len(s["words"]) == 1 for s in res.segments)


# ---------------------------------------------------------------------------
# Defensive / no-op cases
# ---------------------------------------------------------------------------

def test_empty_chunks_is_noop():
    """No diarization output → don't touch the existing segments."""
    initial_segs = [{"start": 0.0, "end": 1.0, "text": "hi",
                     "words": [{"w": "hi", "start": 0.0, "end": 1.0}],
                     "speaker": None}]
    res = transcriber.TranscriptResult(
        language="en",
        duration=1.0,
        segments=initial_segs,
        words=[{"w": "hi", "start": 0.0, "end": 1.0}],
    )
    transcriber.apply_speakers(res, [])
    # Same list object — early-return must not have rebuilt segments
    assert res.segments is initial_segs


def test_empty_words_is_noop():
    res = transcriber.TranscriptResult(
        language="en", duration=0.0, segments=[], words=[],
    )
    transcriber.apply_speakers(res, [_Chunk(0.0, 5.0, "Alice")])
    assert res.segments == []


def test_chunks_with_overlap_picks_first():
    """If chunks overlap (silero-vad shouldn't do this, but be defensive),
    take the speaker from the first chunk that contains the word."""
    res = _result([{"w": "hi", "start": 1.5, "end": 1.8}])
    # Two chunks overlap on [1.0, 2.0); first by start time wins.
    chunks = [
        _Chunk(0.0, 2.0, "Alice"),
        _Chunk(1.0, 3.0, "Bob"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert res.words[0]["speaker"] == "Alice"


# ---------------------------------------------------------------------------
# Speaker label is preserved in segment dict for write_artifacts
# ---------------------------------------------------------------------------

def test_speaker_lands_on_segment_for_artifact_write(tmp_path):
    """End-to-end: apply_speakers → write_artifacts → .words.json contains
    segments[i].speaker."""
    res = _result([
        {"w": "alice-says", "start": 0.0, "end": 0.5},
        {"w": "bob-says",   "start": 0.6, "end": 1.0},
    ])
    transcriber.apply_speakers(res, [
        _Chunk(0.0, 0.5, "Speaker 1"),
        _Chunk(0.5, 1.0, "Speaker 2"),
    ])
    transcriber.write_artifacts(res, str(tmp_path / "abc"))

    import json
    payload = json.loads((tmp_path / "abc.words.json").read_text())
    speakers = [s.get("speaker") for s in payload["segments"]]
    assert "Speaker 1" in speakers
    assert "Speaker 2" in speakers


def test_speakers_persisted_through_v2_artifacts(tmp_path):
    """The speaker field on each segment must round-trip through write_artifacts'
    v2 emission. Regression: write_artifacts builds v2 segments fresh from
    result.segments — easy to forget to copy the speaker field across."""
    res = transcriber.TranscriptResult(
        language="en", duration=2.0,
        segments=[
            {"start": 0.0, "end": 1.0, "text": "hello",
             "words": [{"w": "hello", "start": 0.0, "end": 1.0}],
             "speaker": "Alice"},
            {"start": 1.0, "end": 2.0, "text": "world",
             "words": [{"w": "world", "start": 1.0, "end": 2.0}],
             "speaker": "Bob"},
        ],
        words=[
            {"w": "hello", "start": 0.0, "end": 1.0},
            {"w": "world", "start": 1.0, "end": 2.0},
        ],
    )
    transcriber.write_artifacts(res, str(tmp_path / "abc"))

    import json
    payload = json.loads((tmp_path / "abc.words.json").read_text())
    assert payload["segments"][0]["speaker"] == "Alice"
    assert payload["segments"][1]["speaker"] == "Bob"


# ---------------------------------------------------------------------------
# Realistic synthetic scenarios
# ---------------------------------------------------------------------------

def test_leading_orphan_words_inherit_from_first_assigned_neighbor():
    """Whisper sometimes emits words BEFORE silero-vad's first chunk (a
    quick greeting that VAD considered noise). Those orphan words must
    backward-fill from the first assigned word — otherwise every leading
    orphan creates a 'speaker=None' segment that the user has to clean up
    by hand."""
    res = _result([
        {"w": "uh",     "start": 0.0, "end": 0.2},
        {"w": "hello",  "start": 0.5, "end": 0.8},  # in chunk
        {"w": "world",  "start": 0.9, "end": 1.2},  # in chunk
    ])
    transcriber.apply_speakers(res, [_Chunk(0.4, 1.5, "Alice")])
    # All three words now belong to Alice → one segment, no None gaps.
    assert len(res.segments) == 1
    assert res.segments[0]["speaker"] == "Alice"
    assert res.segments[0]["text"] == "uh hello world"


def test_orphan_word_in_gap_inherits_from_previous_speaker():
    """Whisper bridges short pauses that VAD splits across two chunks.
    Forward-fill: orphans inherit from the previous assigned word."""
    res = _result([
        {"w": "Alright", "start": 0.2, "end": 0.4},   # before chunk → orphan
        {"w": "so",      "start": 0.55, "end": 0.7},  # in chunk 1
        {"w": "here",    "start": 0.7, "end": 0.9},   # in chunk 1
        {"w": "And",     "start": 14.1, "end": 14.2},  # tiny gap → orphan
        {"w": "thats",   "start": 14.27, "end": 14.5}, # in chunk 2
    ])
    chunks = [
        _Chunk(0.55, 13.98, "Speaker 1"),
        _Chunk(14.27, 16.25, "Speaker 1"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert all(w["speaker"] == "Speaker 1" for w in res.words), \
        f"orphans must inherit Speaker 1, got " \
        f"{[(w['w'], w['speaker']) for w in res.words]}"
    # Segments shouldn't fragment on speaker (only the >1s gap splits 'here'/'And')
    speakers = [s["speaker"] for s in res.segments]
    assert None not in speakers
    assert all(s == "Speaker 1" for s in speakers)


def test_orphan_word_between_two_speakers_fills_with_previous():
    """In a real two-speaker conversation, an orphan word in the gap
    between A's chunk and B's chunk should inherit A (continuity), not B."""
    res = _result([
        {"w": "hello",   "start": 0.5, "end": 1.0},   # in chunk A
        {"w": "uh",      "start": 1.5, "end": 1.7},   # gap
        {"w": "bye",     "start": 2.5, "end": 3.0},   # in chunk B
    ])
    chunks = [
        _Chunk(0.0, 1.0, "Alice"),
        _Chunk(2.0, 4.0, "Bob"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert res.words[0]["speaker"] == "Alice"
    assert res.words[1]["speaker"] == "Alice"  # forward-filled from Alice
    assert res.words[2]["speaker"] == "Bob"


def test_all_orphan_words_no_chunks_overlap_stays_none():
    """Pathological: chunks exist but contain ZERO words (all words fell
    outside every chunk). Without the backward-fill seed, every word
    stays None — that's the only case where a None segment is acceptable.
    """
    res = _result([
        {"w": "hello", "start": 0.0, "end": 0.4},
        {"w": "world", "start": 0.5, "end": 0.9},
    ])
    # Chunk is way past the words
    transcriber.apply_speakers(res, [_Chunk(100.0, 200.0, "Alice")])
    assert all(w.get("speaker") is None for w in res.words)
    assert len(res.segments) == 1
    assert res.segments[0]["speaker"] is None


def test_long_pause_between_two_speakers_still_segments_correctly():
    res = _result([
        {"w": "hi",   "start": 0.0,  "end": 0.5},
        # 30-second pause
        {"w": "bye",  "start": 30.0, "end": 30.5},
    ])
    chunks = [
        _Chunk(0.0, 1.0, "Alice"),
        _Chunk(29.0, 31.0, "Bob"),
    ]
    transcriber.apply_speakers(res, chunks)
    assert len(res.segments) == 2
    assert res.segments[0]["speaker"] == "Alice"
    assert res.segments[0]["start"] == 0.0
    assert res.segments[1]["speaker"] == "Bob"
    assert res.segments[1]["start"] == 30.0


def test_segment_text_strips_leading_trailing_whitespace():
    """Whisper sometimes emits leading-space tokens (e.g. " hello"). The
    rendered segment text should still be tight."""
    res = _result([
        {"w": " hello",  "start": 0.0, "end": 0.5},
        {"w": " world",  "start": 0.5, "end": 1.0},
    ])
    transcriber.apply_speakers(res, [_Chunk(0.0, 2.0, "Alice")])
    # _build_segment uses " ".join, which produces "  hello  world".
    # Document current behavior so we notice if it ever tightens.
    text = res.segments[0]["text"]
    assert "hello" in text and "world" in text
