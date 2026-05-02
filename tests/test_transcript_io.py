"""Tests for transcript_io: load/save round-trip + v1 -> v2 migration.

These cover TR-E1 of the transcript-editor-v2 plan.
"""
from __future__ import annotations

import json
import os

import pytest

import transcript_io


def _v1_payload() -> dict:
    """Build a representative v1 .words.json payload.

    Matches the shape written by ``transcriber.write_artifacts`` before
    schema_version was introduced: a flat ``words`` array plus a
    ``segments`` list whose items each carry their own nested ``words``.
    """
    flat_words = [
        {"w": "hello", "start": 0.0, "end": 0.42},
        {"w": "world", "start": 0.42, "end": 0.91},
        {"w": "again", "start": 2.10, "end": 2.55},
        {"w": "friend", "start": 2.55, "end": 3.10},
    ]
    return {
        "language": "en",
        "duration": 3.10,
        "segments": [
            {
                "start": 0.0,
                "end": 0.91,
                "text": "hello world",
                "words": [dict(w) for w in flat_words[:2]],
            },
            {
                "start": 2.10,
                "end": 3.10,
                "text": "again friend",
                "words": [dict(w) for w in flat_words[2:]],
            },
        ],
        "words": flat_words,
    }


def _write(tmp_path, payload, name="abc.words.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def test_load_migrates_v1_to_v2(tmp_path):
    path = _write(tmp_path, _v1_payload())

    data = transcript_io.load(path)

    assert data["schema_version"] == 2
    assert data["edited_at"] is None
    assert data["bookmarks"] == []

    # Each word is keyed by idx, retains its original_w, and starts unedited.
    for i, w in enumerate(data["words"]):
        assert w["idx"] == i
        assert w["original_w"] == w["w"]
        assert w["edited"] is False
        assert w["deleted"] is False

    # Segments now reference words by idx and the nested list is gone.
    assert data["segments"][0]["word_idxs"] == [0, 1]
    assert data["segments"][1]["word_idxs"] == [2, 3]
    for seg in data["segments"]:
        assert "words" not in seg
        assert seg["speaker"] is None


def test_load_writes_v1_backup_once(tmp_path):
    path = _write(tmp_path, _v1_payload())
    backup = path.replace(".words.json", ".words.v1.json")

    transcript_io.load(path)

    assert os.path.exists(backup), "first load should snapshot the v1 file"
    backup_payload = json.loads(open(backup).read())
    assert "schema_version" not in backup_payload
    assert backup_payload["segments"][0]["words"][0]["w"] == "hello"

    # Tamper with the backup so we can prove a second load doesn't overwrite it.
    open(backup, "w").write('{"sentinel": true}')
    transcript_io.load(path)
    assert json.loads(open(backup).read()) == {"sentinel": True}


def test_load_rewrites_file_as_v2(tmp_path):
    path = _write(tmp_path, _v1_payload())

    transcript_io.load(path)

    on_disk = json.loads(open(path).read())
    assert on_disk["schema_version"] == 2
    assert on_disk["segments"][0]["word_idxs"] == [0, 1]


def test_load_is_idempotent_on_v2(tmp_path):
    path = _write(tmp_path, _v1_payload())
    first = transcript_io.load(path)
    first_serialized = json.dumps(first, sort_keys=True)
    backup = path.replace(".words.json", ".words.v1.json")
    backup_mtime = os.path.getmtime(backup)

    second = transcript_io.load(path)

    assert second["schema_version"] == 2
    assert json.dumps(second, sort_keys=True) == first_serialized
    # Backup must not be touched on subsequent loads.
    assert os.path.getmtime(backup) == backup_mtime


def test_migrate_handles_empty_words(tmp_path):
    path = _write(tmp_path, {"language": "", "duration": 0.0, "segments": [], "words": []})

    data = transcript_io.load(path)

    assert data["schema_version"] == 2
    assert data["words"] == []
    assert data["segments"] == []
    assert data["bookmarks"] == []


def test_save_is_atomic_round_trip(tmp_path):
    path = str(tmp_path / "abc.words.json")
    payload = {"schema_version": 2, "words": [], "segments": [], "bookmarks": [], "edited_at": None}

    transcript_io.save(path, payload)

    assert json.loads(open(path).read()) == payload
    # tempfiles must not leak alongside the final file.
    leftovers = [n for n in os.listdir(tmp_path) if n.startswith(".tio.")]
    assert leftovers == []


def test_save_does_not_corrupt_existing_file_on_serialization_error(tmp_path):
    path = str(tmp_path / "abc.words.json")
    transcript_io.save(path, {"schema_version": 2, "words": []})
    original = open(path).read()

    class _NotJsonable:
        pass

    with pytest.raises(TypeError):
        transcript_io.save(path, {"bad": _NotJsonable()})

    assert open(path).read() == original
    leftovers = [n for n in os.listdir(tmp_path) if n.startswith(".tio.")]
    assert leftovers == []
