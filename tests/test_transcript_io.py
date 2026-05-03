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


def test_load_does_not_mutate_disk(tmp_path):
    """Audit #13 contract: ``load()`` is a pure read. Even on a v1
    file (which load() still normalizes in-memory), the on-disk
    bytes, mtime, and the *absence* of a backup file must all be
    preserved. Persistence is the explicit job of ``migrate()``."""
    path = _write(tmp_path, _v1_payload())
    raw_before = open(path, "rb").read()
    mtime_before = os.path.getmtime(path)
    backup = path.replace(".words.json", ".words.v1.json")

    data = transcript_io.load(path)

    # Caller still sees the canonical v2 shape in memory.
    assert data["schema_version"] == 2
    assert data["segments"][0]["word_idxs"] == [0, 1]
    # But disk is untouched: same bytes, same mtime, no backup.
    assert open(path, "rb").read() == raw_before
    assert os.path.getmtime(path) == mtime_before
    assert not os.path.exists(backup), \
        "load() must never write the v1 backup — that's migrate()'s job"


def test_migrate_writes_v1_backup_once(tmp_path):
    path = _write(tmp_path, _v1_payload())
    backup = path.replace(".words.json", ".words.v1.json")

    assert transcript_io.migrate(path) is True

    assert os.path.exists(backup), "first migrate should snapshot the v1 file"
    backup_payload = json.loads(open(backup).read())
    assert "schema_version" not in backup_payload
    assert backup_payload["segments"][0]["words"][0]["w"] == "hello"

    # Tamper with the backup so we can prove a second migrate doesn't overwrite it.
    open(backup, "w").write('{"sentinel": true}')
    assert transcript_io.migrate(path) is False  # already v2 now
    assert json.loads(open(backup).read()) == {"sentinel": True}


def test_migrate_rewrites_file_as_v2(tmp_path):
    path = _write(tmp_path, _v1_payload())

    assert transcript_io.migrate(path) is True

    on_disk = json.loads(open(path).read())
    assert on_disk["schema_version"] == 2
    assert on_disk["segments"][0]["word_idxs"] == [0, 1]


def test_migrate_is_idempotent_on_v2(tmp_path):
    """A second migrate() on an already-migrated, fully-back-filled
    file must be a true no-op: returns False, no mtime bump on either
    the file or the backup."""
    path = _write(tmp_path, _v1_payload())
    assert transcript_io.migrate(path) is True
    backup = path.replace(".words.json", ".words.v1.json")
    file_mtime   = os.path.getmtime(path)
    backup_mtime = os.path.getmtime(backup)

    assert transcript_io.migrate(path) is False
    assert os.path.getmtime(path)   == file_mtime
    assert os.path.getmtime(backup) == backup_mtime


def test_migrate_all_persists_every_v1_file(tmp_path):
    """The startup sweep must walk every .words.json in the directory
    (and only those — backup files and unrelated names are skipped)."""
    a = _write(tmp_path, _v1_payload(), name="aaa.words.json")
    b = _write(tmp_path, _v1_payload(), name="bbb.words.json")
    # Already-v2 + a backup file + an unrelated name should all be skipped.
    v2_doc = transcript_io.load(_write(tmp_path, _v1_payload(), name="ccc.words.json"))
    transcript_io.save(str(tmp_path / "ccc.words.json"), v2_doc)
    (tmp_path / "ddd.words.v1.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("ignore me")

    written, skipped = transcript_io.migrate_all(str(tmp_path))

    assert written == 2  # only aaa + bbb were still v1 on disk
    assert skipped == []
    for p in (a, b):
        assert json.loads(open(p).read())["schema_version"] == 2

    # Corrupt one and prove the sweep still completes — the broken
    # file appears in ``skipped`` (with a reason for the operator log)
    # rather than raising. Required so a self-hoster can boot the
    # server even with a hand-edited broken artifact.
    (tmp_path / "broken.words.json").write_text("{not json")
    written2, skipped2 = transcript_io.migrate_all(str(tmp_path))
    assert written2 == 0
    assert any(name == "broken.words.json" for name, _ in skipped2)


def test_migrate_all_no_op_on_missing_directory(tmp_path):
    assert transcript_io.migrate_all(str(tmp_path / "does-not-exist")) == (0, [])


def test_create_app_runs_startup_migration_sweep(tmp_path, monkeypatch):
    """Architect nit (#13): integration coverage that ``create_app``
    actually wires ``migrate_all`` into startup. A v1 file dropped into
    the download dir before app boot must be persisted as v2 by the
    time the first request arrives — no GET should ever have to mutate
    disk."""
    # ``app.DOWNLOAD_DIR`` is resolved at module import time, so a
    # plain ``monkeypatch.setenv`` arrives too late once another test
    # in the suite has already imported app. Patch the module attr
    # directly — create_app() prefers the module-level constant.
    import app as _app
    from pathlib import Path as _Path
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", _Path(tmp_path))
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    v1_path = tmp_path / "preexisting.words.json"
    v1_path.write_text(json.dumps(_v1_payload()))
    raw_v1 = v1_path.read_bytes()

    flask_app = _app.create_app()
    try:
        on_disk = json.loads(v1_path.read_text())
        assert on_disk["schema_version"] == 2, \
            "startup sweep must have rewritten the v1 file as v2"
        assert on_disk["segments"][0]["word_idxs"] == [0, 1]
        # Backup snapshot was written exactly once.
        backup = tmp_path / "preexisting.words.v1.json"
        assert backup.exists()
        assert backup.read_bytes() == raw_v1
    finally:
        # Drain any background threads spun up by create_app().
        jm = flask_app.extensions.get("trove.jobs")
        if jm is not None and hasattr(jm, "_executor"):
            jm._executor.shutdown(wait=False, cancel_futures=True)


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
