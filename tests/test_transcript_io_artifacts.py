"""Tests for transcript_io.regenerate_artifacts + transcriber.write_artifacts (TR-E3)."""
from __future__ import annotations

import os

import transcript_io
import transcriber
from transcriber import TranscriptResult


def _v2_doc() -> dict:
    return {
        "schema_version": 2,
        "language": "en",
        "duration": 3.10,
        "edited_at": None,
        "words": [
            {"idx": 0, "w": "hello", "original_w": "hello", "start": 0.0, "end": 0.42, "edited": False, "deleted": False},
            {"idx": 1, "w": "world", "original_w": "world", "start": 0.42, "end": 0.91, "edited": False, "deleted": False},
            {"idx": 2, "w": "again", "original_w": "again", "start": 2.10, "end": 2.55, "edited": False, "deleted": False},
            {"idx": 3, "w": "friend", "original_w": "friend", "start": 2.55, "end": 3.10, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 0.0, "end": 0.91, "text": "hello world", "word_idxs": [0, 1], "speaker": None},
            {"start": 2.10, "end": 3.10, "text": "again friend", "word_idxs": [2, 3], "speaker": None},
        ],
        "bookmarks": [],
    }


def test_regenerate_artifacts_writes_three_files(tmp_path):
    base = str(tmp_path / "abc")
    transcript_io.regenerate_artifacts(_v2_doc(), base)

    assert os.path.exists(base + ".txt")
    assert os.path.exists(base + ".srt")
    assert os.path.exists(base + ".vtt")


def test_txt_reflects_edited_word(tmp_path):
    base = str(tmp_path / "abc")
    data = _v2_doc()
    transcript_io.apply_word_op(data, 0, "set_text", w="HELLO")
    transcript_io.regenerate_artifacts(data, base)

    txt = open(base + ".txt").read()
    assert "HELLO world" in txt
    assert "again friend" in txt


def test_txt_skips_deleted_words(tmp_path):
    base = str(tmp_path / "abc")
    data = _v2_doc()
    transcript_io.apply_word_op(data, 1, "delete")
    transcript_io.regenerate_artifacts(data, base)

    txt = open(base + ".txt").read()
    assert "world" not in txt
    assert "hello" in txt


def test_srt_timestamps_untouched_after_edits(tmp_path):
    base = str(tmp_path / "abc")
    data = _v2_doc()
    transcript_io.apply_word_op(data, 0, "set_text", w="HELLO")
    transcript_io.apply_word_op(data, 1, "delete")
    transcript_io.regenerate_artifacts(data, base)

    srt = open(base + ".srt").read()
    # Timestamps come from segment.start/end, which migration preserves.
    assert "00:00:00,000 --> 00:00:00,910" in srt
    assert "00:00:02,100 --> 00:00:03,100" in srt


def test_vtt_has_header_and_correct_separator(tmp_path):
    base = str(tmp_path / "abc")
    transcript_io.regenerate_artifacts(_v2_doc(), base)

    vtt = open(base + ".vtt").read()
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:00.910" in vtt


def test_inserted_word_appears_in_artifacts(tmp_path):
    base = str(tmp_path / "abc")
    data = _v2_doc()
    transcript_io.apply_word_op(data, 0, "insert_after", w="dear")
    transcript_io.regenerate_artifacts(data, base)

    txt = open(base + ".txt").read()
    assert "hello dear world" in txt


def test_segment_with_all_words_deleted_skipped_in_srt(tmp_path):
    base = str(tmp_path / "abc")
    data = _v2_doc()
    transcript_io.apply_word_op(data, 2, "delete")
    transcript_io.apply_word_op(data, 3, "delete")
    transcript_io.regenerate_artifacts(data, base)

    srt = open(base + ".srt").read()
    # Only one numbered cue should remain (the first segment).
    assert srt.count("\n\n") == 1
    assert "1\n00:00:00,000" in srt
    assert "2\n" not in srt


# ----- transcriber.write_artifacts (now emits schema v2) --------------------

def test_write_artifacts_emits_schema_v2(tmp_path):
    base = str(tmp_path / "abc")
    result = TranscriptResult(
        language="en",
        duration=0.91,
        segments=[
            {
                "start": 0.0,
                "end": 0.91,
                "text": "hello world",
                "words": [
                    {"w": "hello", "start": 0.0, "end": 0.42},
                    {"w": "world", "start": 0.42, "end": 0.91},
                ],
            }
        ],
        words=[
            {"w": "hello", "start": 0.0, "end": 0.42},
            {"w": "world", "start": 0.42, "end": 0.91},
        ],
    )
    transcriber.write_artifacts(result, base)

    data = transcript_io.load(base + ".words.json")
    assert data["schema_version"] == 2
    assert data["bookmarks"] == []
    assert data["words"][0]["original_w"] == "hello"
    assert data["segments"][0]["word_idxs"] == [0, 1]

    # And the .txt/.srt/.vtt exist with expected content.
    assert "hello world" in open(base + ".txt").read()
    assert "hello world" in open(base + ".srt").read()
    assert "hello world" in open(base + ".vtt").read()
