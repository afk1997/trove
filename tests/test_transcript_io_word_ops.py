"""Tests for transcript_io.apply_word_op (TR-E2)."""
from __future__ import annotations

import copy

import pytest

import transcript_io
from transcript_io import WordOpError


def _fresh_v2() -> dict:
    """Build a small migrated v2 doc directly (no disk I/O)."""
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


# ----- set_text --------------------------------------------------------------

def test_set_text_marks_edited_when_changed():
    data = _fresh_v2()
    out = transcript_io.apply_word_op(data, 0, "set_text", w="HELLO")
    assert out["w"] == "HELLO"
    assert out["original_w"] == "hello"
    assert out["edited"] is True


def test_set_text_clears_edited_when_reverted():
    data = _fresh_v2()
    transcript_io.apply_word_op(data, 0, "set_text", w="HELLO")
    out = transcript_io.apply_word_op(data, 0, "set_text", w="hello")
    assert out["edited"] is False


def test_set_text_requires_string_w():
    data = _fresh_v2()
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 0, "set_text")
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 0, "set_text", w=123)


# ----- delete ---------------------------------------------------------------

def test_delete_keeps_idx_in_segment():
    data = _fresh_v2()
    transcript_io.apply_word_op(data, 1, "delete")
    assert data["words"][1]["deleted"] is True
    assert data["segments"][0]["word_idxs"] == [0, 1], "deleted word stays in segment for stable IDs"


def test_delete_on_already_deleted_raises():
    data = _fresh_v2()
    transcript_io.apply_word_op(data, 1, "delete")
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 1, "delete")


# ----- insert_after ---------------------------------------------------------

def test_insert_after_appends_to_words_and_segment():
    data = _fresh_v2()
    new = transcript_io.apply_word_op(data, 0, "insert_after", w="dear")
    assert new["idx"] == 4
    assert new["original_w"] == "dear"
    assert new["edited"] is False
    # Inherits zero-duration timestamp from anchor's end.
    assert new["start"] == pytest.approx(0.42)
    assert new["end"] == pytest.approx(0.42)
    assert data["words"][-1] is new
    assert data["segments"][0]["word_idxs"] == [0, 4, 1]


def test_insert_after_uses_fresh_idx_even_with_gaps():
    data = _fresh_v2()
    transcript_io.apply_word_op(data, 0, "insert_after", w="A")
    transcript_io.apply_word_op(data, 0, "insert_after", w="B")
    new_ids = [w["idx"] for w in data["words"] if w["w"] in ("A", "B")]
    assert new_ids == [4, 5]
    assert data["segments"][0]["word_idxs"] == [0, 5, 4, 1]


def test_insert_after_invalid_idx_raises():
    data = _fresh_v2()
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 99, "insert_after", w="oops")


# ----- merge_next -----------------------------------------------------------

def test_merge_next_absorbs_text_and_end():
    data = _fresh_v2()
    out = transcript_io.apply_word_op(data, 0, "merge_next")
    assert out["w"] == "helloworld"
    assert out["end"] == pytest.approx(0.91)
    assert out["edited"] is True
    assert data["words"][1]["deleted"] is True


def test_merge_next_skips_deleted_peer():
    data = _fresh_v2()
    # Insert dummy after 0 then delete the original word 1; merging should
    # find the inserted word (the next non-deleted peer in the segment).
    transcript_io.apply_word_op(data, 0, "insert_after", w="X")
    transcript_io.apply_word_op(data, 1, "delete")
    out = transcript_io.apply_word_op(data, 0, "merge_next")
    assert out["w"] == "helloX"


def test_merge_next_at_segment_tail_raises():
    data = _fresh_v2()
    # idx 1 is the last visible word in the first segment.
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 1, "merge_next")


# ----- general guards ------------------------------------------------------

def test_unknown_op_raises():
    data = _fresh_v2()
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 0, "explode")


def test_out_of_range_idx_raises():
    data = _fresh_v2()
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, -1, "delete")
    with pytest.raises(WordOpError):
        transcript_io.apply_word_op(data, 99, "delete")


def test_ops_do_not_touch_other_words():
    data = _fresh_v2()
    snapshot = copy.deepcopy(data["words"][2:])
    transcript_io.apply_word_op(data, 0, "set_text", w="HI")
    transcript_io.apply_word_op(data, 0, "merge_next")
    transcript_io.apply_word_op(data, 0, "insert_after", w="!")
    assert data["words"][2:4] == snapshot
