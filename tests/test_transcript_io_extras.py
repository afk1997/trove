"""Tests for the find_replace / speaker / bookmark helpers (TR-E7, E10, E11)."""
from __future__ import annotations

import pytest

import transcript_io


def _doc():
    return {
        "schema_version": 2,
        "language": "en",
        "duration": 4.0,
        "edited_at": None,
        "words": [
            {"idx": 0, "w": "the", "original_w": "the", "start": 0.0, "end": 0.4, "edited": False, "deleted": False},
            {"idx": 1, "w": "fox", "original_w": "fox", "start": 0.4, "end": 0.8, "edited": False, "deleted": False},
            {"idx": 2, "w": "runs", "original_w": "runs", "start": 0.8, "end": 1.2, "edited": False, "deleted": False},
            {"idx": 3, "w": "The", "original_w": "The", "start": 1.2, "end": 1.6, "edited": False, "deleted": False},
            {"idx": 4, "w": "dog", "original_w": "dog", "start": 1.6, "end": 2.0, "edited": False, "deleted": False},
            {"idx": 5, "w": "barks", "original_w": "barks", "start": 2.0, "end": 2.4, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 0.0, "end": 1.2, "text": "the fox runs", "word_idxs": [0, 1, 2], "speaker": None},
            {"start": 1.2, "end": 2.4, "text": "The dog barks", "word_idxs": [3, 4, 5], "speaker": None},
            {"start": 2.4, "end": 4.0, "text": "and that is that", "word_idxs": [], "speaker": "Bob"},
        ],
        "bookmarks": [],
    }


# ----- find_replace --------------------------------------------------------

def test_find_replace_case_sensitive_only_matches_exact_case():
    d = _doc()
    out = transcript_io.find_replace(d, "the", "THE")
    assert out["count"] == 1
    assert out["indices"] == [0]
    assert d["words"][0]["w"] == "THE"
    assert d["words"][0]["edited"] is True
    # "The" not touched
    assert d["words"][3]["w"] == "The"


def test_find_replace_case_insensitive_matches_both():
    d = _doc()
    out = transcript_io.find_replace(d, "the", "THE", case_sensitive=False)
    assert out["count"] == 2
    assert set(out["indices"]) == {0, 3}
    assert d["words"][0]["w"] == "THE"
    assert d["words"][3]["w"] == "THE"


def test_find_replace_skips_deleted_words():
    d = _doc()
    d["words"][0]["deleted"] = True
    out = transcript_io.find_replace(d, "the", "X", case_sensitive=False)
    assert 0 not in out["indices"]
    assert d["words"][0]["w"] == "the"  # untouched


def test_find_replace_empty_find_is_noop():
    d = _doc()
    out = transcript_io.find_replace(d, "", "X")
    assert out == {"count": 0, "indices": []}


def test_find_replace_clears_edited_when_text_returns_to_original():
    d = _doc()
    transcript_io.find_replace(d, "the", "THE")
    assert d["words"][0]["edited"] is True
    transcript_io.find_replace(d, "THE", "the")
    assert d["words"][0]["w"] == "the"
    assert d["words"][0]["edited"] is False


def test_find_replace_substring_within_word():
    d = _doc()
    # 'barks' -> 'barked' via 's' -> 'ed' is too greedy; use a clearer case
    out = transcript_io.find_replace(d, "ar", "AR")
    assert out["count"] == 1
    assert d["words"][5]["w"] == "bARks"


# ----- apply_speaker -------------------------------------------------------

def test_apply_speaker_sets_one_segment_no_propagate():
    d = _doc()
    changed = transcript_io.apply_speaker(d, 0, "Alice", propagate=False)
    assert changed == [0]
    assert d["segments"][0]["speaker"] == "Alice"
    assert d["segments"][1]["speaker"] is None


def test_apply_speaker_propagates_until_existing_label():
    d = _doc()
    changed = transcript_io.apply_speaker(d, 0, "Alice", propagate=True)
    # Both null segments (0, 1) get Alice; segment 2 already has "Bob" so we stop.
    assert changed == [0, 1]
    assert d["segments"][0]["speaker"] == "Alice"
    assert d["segments"][1]["speaker"] == "Alice"
    assert d["segments"][2]["speaker"] == "Bob"


def test_apply_speaker_clearing_does_not_propagate():
    d = _doc()
    d["segments"][0]["speaker"] = "Alice"
    changed = transcript_io.apply_speaker(d, 0, None, propagate=True)
    assert changed == [0]
    assert d["segments"][0]["speaker"] is None
    # Don't accidentally null-out Bob
    assert d["segments"][2]["speaker"] == "Bob"


def test_apply_speaker_no_change_returns_empty_list():
    d = _doc()
    d["segments"][0]["speaker"] = "Alice"
    assert transcript_io.apply_speaker(d, 0, "Alice", propagate=False) == []


def test_apply_speaker_out_of_range_raises():
    d = _doc()
    with pytest.raises(ValueError):
        transcript_io.apply_speaker(d, 99, "x")


# ----- bookmarks -----------------------------------------------------------

def test_add_bookmark_assigns_id_and_keeps_sorted():
    d = _doc()
    a = transcript_io.add_bookmark(d, 5.0, "later")
    b = transcript_io.add_bookmark(d, 1.0, "earlier")
    c = transcript_io.add_bookmark(d, 3.0, "middle")
    assert {a["id"], b["id"], c["id"]} == {a["id"], b["id"], c["id"]}
    assert all(bm["id"].startswith("bm_") for bm in d["bookmarks"])
    times = [bm["time"] for bm in d["bookmarks"]]
    assert times == sorted(times)


def test_update_bookmark_changes_fields_and_resorts():
    d = _doc()
    a = transcript_io.add_bookmark(d, 1.0, "a")
    transcript_io.add_bookmark(d, 5.0, "b")
    out = transcript_io.update_bookmark(d, a["id"], time=10.0, note="moved")
    assert out["time"] == 10.0
    assert out["note"] == "moved"
    times = [bm["time"] for bm in d["bookmarks"]]
    assert times == sorted(times)


def test_update_bookmark_unknown_returns_none():
    d = _doc()
    assert transcript_io.update_bookmark(d, "bm_nope", note="x") is None


def test_delete_bookmark_removes_and_returns_true():
    d = _doc()
    a = transcript_io.add_bookmark(d, 1.0, "a")
    assert transcript_io.delete_bookmark(d, a["id"]) is True
    assert all(bm["id"] != a["id"] for bm in d["bookmarks"])


def test_delete_bookmark_unknown_returns_false():
    d = _doc()
    assert transcript_io.delete_bookmark(d, "bm_nope") is False
