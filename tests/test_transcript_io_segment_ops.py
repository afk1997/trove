"""Tests for transcript_io v3 ops: split/merge, rename_speaker, highlights,
notes, reviewed, title, plus v2 -> v2.1 backfill on load."""
from __future__ import annotations

import json

import pytest

import transcript_io


def _fresh_v21() -> dict:
    """Build a small migrated v2.1 doc directly (no disk I/O)."""
    return {
        "schema_version": 2,
        "language": "en",
        "duration": 3.10,
        "edited_at": None,
        "title": None,
        "words": [
            {"idx": 0, "w": "hello", "original_w": "hello", "start": 0.0, "end": 0.42, "edited": False, "deleted": False},
            {"idx": 1, "w": "world", "original_w": "world", "start": 0.42, "end": 0.91, "edited": False, "deleted": False},
            {"idx": 2, "w": "and",   "original_w": "and",   "start": 1.10, "end": 1.30, "edited": False, "deleted": False},
            {"idx": 3, "w": "again", "original_w": "again", "start": 2.10, "end": 2.55, "edited": False, "deleted": False},
            {"idx": 4, "w": "friend","original_w": "friend","start": 2.55, "end": 3.10, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 0.0,  "end": 1.30, "text": "hello world and",
             "word_idxs": [0, 1, 2], "speaker": "Alice", "reviewed": False},
            {"start": 2.10, "end": 3.10, "text": "again friend",
             "word_idxs": [3, 4],    "speaker": "Bob",   "reviewed": False},
        ],
        "bookmarks": [],
        "highlights": [],
        "notes": [],
    }


# ----- migration backfill --------------------------------------------------

def test_load_backfills_v21_defaults_on_old_v2(tmp_path):
    """An old v2 file (no title/highlights/notes/reviewed) gets the new defaults."""
    p = tmp_path / "old.words.json"
    p.write_text(json.dumps({
        "schema_version": 2,
        "language": "en",
        "duration": 1.0,
        "edited_at": None,
        "words": [{"idx": 0, "w": "hi", "original_w": "hi", "start": 0.0, "end": 0.5,
                   "edited": False, "deleted": False}],
        "segments": [{"start": 0.0, "end": 0.5, "text": "hi", "word_idxs": [0], "speaker": None}],
        "bookmarks": [],
    }))
    data = transcript_io.load(str(p))
    assert data["title"] is None
    assert data["highlights"] == []
    assert data["notes"] == []
    assert data["segments"][0]["reviewed"] is False
    # backfill persisted to disk (re-read finds the new keys present)
    on_disk = json.loads(p.read_text())
    assert "title" in on_disk
    assert "highlights" in on_disk
    assert "notes" in on_disk
    assert on_disk["segments"][0]["reviewed"] is False


def test_load_idempotent_on_already_v21(tmp_path):
    p = tmp_path / "new.words.json"
    payload = _fresh_v21()
    p.write_text(json.dumps(payload))
    mtime_before = p.stat().st_mtime_ns
    data = transcript_io.load(str(p))
    assert data["title"] is None
    # No write should have happened (defaults already present).
    assert p.stat().st_mtime_ns == mtime_before


def test_v1_migration_includes_v21_defaults(tmp_path):
    """A v1 file gets full v2.1 shape after migration."""
    p = tmp_path / "v1.words.json"
    p.write_text(json.dumps({
        "language": "en",
        "duration": 1.0,
        "segments": [{"start": 0.0, "end": 0.5, "text": "hi",
                      "words": [{"w": "hi", "start": 0.0, "end": 0.5}]}],
        "words": [{"w": "hi", "start": 0.0, "end": 0.5}],
    }))
    data = transcript_io.load(str(p))
    assert data["schema_version"] == 2
    assert data["title"] is None
    assert data["highlights"] == []
    assert data["notes"] == []
    assert data["segments"][0]["reviewed"] is False


# ----- title ---------------------------------------------------------------

def test_set_title_strips_and_stores():
    data = _fresh_v21()
    out = transcript_io.set_title(data, "  My doc  ")
    assert out == "My doc"
    assert data["title"] == "My doc"


def test_set_title_empty_clears_to_none():
    data = _fresh_v21()
    transcript_io.set_title(data, "x")
    out = transcript_io.set_title(data, "   ")
    assert out is None
    assert data["title"] is None


# ----- split_segment_at_word ----------------------------------------------

def test_split_creates_two_segments_at_position():
    data = _fresh_v21()
    left, right = transcript_io.split_segment_at_word(data, 0, after_word_idx=1)
    assert (left, right) == (0, 1)
    assert len(data["segments"]) == 3
    assert data["segments"][0]["word_idxs"] == [0, 1]
    assert data["segments"][1]["word_idxs"] == [2]
    # Speaker propagated to new right half from original.
    assert data["segments"][1]["speaker"] == "Alice"
    # Original "Bob" segment is now at idx 2.
    assert data["segments"][2]["speaker"] == "Bob"


def test_split_recomputes_segment_bounds_from_word_times():
    data = _fresh_v21()
    transcript_io.split_segment_at_word(data, 0, after_word_idx=1)
    left, right = data["segments"][0], data["segments"][1]
    assert left["start"] == pytest.approx(0.0)
    assert left["end"] == pytest.approx(0.91)
    assert right["start"] == pytest.approx(1.10)
    assert right["end"] == pytest.approx(1.30)


def test_split_rebuilds_text_for_both_halves():
    data = _fresh_v21()
    transcript_io.split_segment_at_word(data, 0, after_word_idx=1)
    assert data["segments"][0]["text"] == "hello world"
    assert data["segments"][1]["text"] == "and"


def test_split_at_last_word_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.split_segment_at_word(data, 0, after_word_idx=2)


def test_split_with_unknown_word_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.split_segment_at_word(data, 0, after_word_idx=99)


def test_split_with_bad_seg_idx_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.split_segment_at_word(data, 99, after_word_idx=0)


def test_split_new_right_half_unreviewed_even_if_left_reviewed():
    data = _fresh_v21()
    data["segments"][0]["reviewed"] = True
    transcript_io.split_segment_at_word(data, 0, after_word_idx=1)
    # Left half keeps reviewed; right is fresh.
    assert data["segments"][0]["reviewed"] is True
    assert data["segments"][1]["reviewed"] is False


# ----- merge_segment_with_prev --------------------------------------------

def test_merge_combines_word_idxs_and_drops_segment():
    data = _fresh_v21()
    new_idx = transcript_io.merge_segment_with_prev(data, 1)
    assert new_idx == 0
    assert len(data["segments"]) == 1
    assert data["segments"][0]["word_idxs"] == [0, 1, 2, 3, 4]
    # Earlier segment's speaker wins.
    assert data["segments"][0]["speaker"] == "Alice"


def test_merge_uses_combined_end_time_and_rebuilds_text():
    data = _fresh_v21()
    transcript_io.merge_segment_with_prev(data, 1)
    assert data["segments"][0]["end"] == pytest.approx(3.10)
    assert data["segments"][0]["text"] == "hello world and again friend"


def test_merge_reviewed_only_when_both_were_reviewed():
    data = _fresh_v21()
    data["segments"][0]["reviewed"] = True
    transcript_io.merge_segment_with_prev(data, 1)
    assert data["segments"][0]["reviewed"] is False
    data2 = _fresh_v21()
    data2["segments"][0]["reviewed"] = True
    data2["segments"][1]["reviewed"] = True
    transcript_io.merge_segment_with_prev(data2, 1)
    assert data2["segments"][0]["reviewed"] is True


def test_merge_first_segment_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.merge_segment_with_prev(data, 0)


def test_merge_out_of_range_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.merge_segment_with_prev(data, 99)


# ----- rename_speaker -----------------------------------------------------

def test_rename_speaker_updates_only_matching_segments():
    data = _fresh_v21()
    changed = transcript_io.rename_speaker(data, old="Alice", new="Anna")
    assert changed == [0]
    assert data["segments"][0]["speaker"] == "Anna"
    assert data["segments"][1]["speaker"] == "Bob"


def test_rename_speaker_can_clear_with_empty_new():
    data = _fresh_v21()
    changed = transcript_io.rename_speaker(data, old="Alice", new="")
    assert changed == [0]
    assert data["segments"][0]["speaker"] is None


def test_rename_speaker_no_matches_returns_empty():
    data = _fresh_v21()
    changed = transcript_io.rename_speaker(data, old="Nobody", new="X")
    assert changed == []


def test_rename_speaker_handles_none_old():
    data = _fresh_v21()
    data["segments"][0]["speaker"] = None
    changed = transcript_io.rename_speaker(data, old=None, new="Carl")
    assert changed == [0]
    assert data["segments"][0]["speaker"] == "Carl"


# ----- highlights ---------------------------------------------------------

def test_add_highlight_appends_and_returns_with_id():
    data = _fresh_v21()
    h = transcript_io.add_highlight(data, 1, 3)
    assert h["id"].startswith("h_")
    assert h["word_idx_start"] == 1
    assert h["word_idx_end"] == 3
    assert data["highlights"] == [h]


def test_add_highlight_inverted_range_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.add_highlight(data, 3, 1)


def test_add_highlight_out_of_range_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.add_highlight(data, 0, 99)
    with pytest.raises(ValueError):
        transcript_io.add_highlight(data, -1, 0)


def test_delete_highlight_removes_by_id():
    data = _fresh_v21()
    h = transcript_io.add_highlight(data, 0, 1)
    assert transcript_io.delete_highlight(data, h["id"]) is True
    assert data["highlights"] == []


def test_delete_highlight_unknown_returns_false():
    data = _fresh_v21()
    assert transcript_io.delete_highlight(data, "h_nope") is False


# ----- notes --------------------------------------------------------------

def test_add_note_appends_and_returns_with_id():
    data = _fresh_v21()
    n = transcript_io.add_note(data, 2, "key insight")
    assert n["id"].startswith("n_")
    assert n["word_idx"] == 2
    assert n["text"] == "key insight"
    assert data["notes"] == [n]


def test_add_note_out_of_range_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.add_note(data, 99, "x")


def test_update_note_changes_text():
    data = _fresh_v21()
    n = transcript_io.add_note(data, 0, "old")
    out = transcript_io.update_note(data, n["id"], "new")
    assert out["text"] == "new"
    assert data["notes"][0]["text"] == "new"


def test_update_note_unknown_returns_none():
    data = _fresh_v21()
    assert transcript_io.update_note(data, "n_nope", "x") is None


def test_delete_note_removes_by_id():
    data = _fresh_v21()
    n = transcript_io.add_note(data, 0, "x")
    assert transcript_io.delete_note(data, n["id"]) is True
    assert data["notes"] == []


def test_delete_note_unknown_returns_false():
    data = _fresh_v21()
    assert transcript_io.delete_note(data, "n_nope") is False


# ----- reviewed -----------------------------------------------------------

def test_set_segment_reviewed_toggles():
    data = _fresh_v21()
    assert transcript_io.set_segment_reviewed(data, 0, True) is True
    assert data["segments"][0]["reviewed"] is True
    # Idempotent: setting same value returns False (no-op).
    assert transcript_io.set_segment_reviewed(data, 0, True) is False
    assert transcript_io.set_segment_reviewed(data, 0, False) is True
    assert data["segments"][0]["reviewed"] is False


def test_set_segment_reviewed_out_of_range_raises():
    data = _fresh_v21()
    with pytest.raises(ValueError):
        transcript_io.set_segment_reviewed(data, 99, True)


# ----- round-trip ---------------------------------------------------------

def test_save_load_round_trip_preserves_v21_fields(tmp_path):
    data = _fresh_v21()
    transcript_io.set_title(data, "Round Trip Doc")
    transcript_io.add_highlight(data, 0, 2)
    transcript_io.add_note(data, 3, "footnote")
    transcript_io.set_segment_reviewed(data, 0, True)
    p = tmp_path / "rt.words.json"
    transcript_io.save(str(p), data)
    reloaded = transcript_io.load(str(p))
    assert reloaded["title"] == "Round Trip Doc"
    assert reloaded["highlights"][0]["word_idx_start"] == 0
    assert reloaded["notes"][0]["text"] == "footnote"
    assert reloaded["segments"][0]["reviewed"] is True
