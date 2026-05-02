"""HTTP endpoint tests for word-level transcript edits (TR-E4)."""
from __future__ import annotations

import json

import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    import app as _app
    import models_store
    (tmp_path / "downloads").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    return app.test_client()


def _seed(client, tmp_path, transcribe_id="tword1", parent_id="pword1"):
    """Create a parent media job + DONE TranscribeJob + v2 .words.json."""
    from jobs import Job, JobStatus
    from transcribe_jobs import TranscribeJob, TranscribeStatus

    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    media = download_dir / f"{parent_id}.mp4"
    media.write_bytes(b"fake")
    base = str(download_dir / parent_id)
    payload = {
        "schema_version": 2,
        "language": "en",
        "duration": 1.0,
        "edited_at": None,
        "words": [
            {"idx": 0, "w": "hello", "original_w": "hello", "start": 0.0, "end": 0.4, "edited": False, "deleted": False},
            {"idx": 1, "w": "world", "original_w": "world", "start": 0.4, "end": 0.9, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 0.0, "end": 0.9, "text": "hello world", "word_idxs": [0, 1], "speaker": None},
        ],
        "bookmarks": [],
    }
    (download_dir / f"{parent_id}.words.json").write_text(json.dumps(payload))
    (download_dir / f"{parent_id}.txt").write_text("hello world\n")

    jm = client.application.extensions["trove.jobs"]
    tjm = client.application.extensions["trove.transcribe"]
    with jm._lock:
        jm._jobs[parent_id] = Job(
            id=parent_id, url="https://x", title="x",
            status=JobStatus.DONE,
            file_path=str(media), filename=f"{parent_id}.mp4",
        )
    with tjm._lock:
        tjm._jobs[transcribe_id] = TranscribeJob(
            id=transcribe_id, parent_job_id=parent_id,
            model_used="ggml-base.bin", status=TranscribeStatus.DONE,
        )
    return base


# ----- set_text (PATCH) ----------------------------------------------------

def test_patch_word_updates_text_and_returns_partial(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch("/api/transcribe/tword1/word/0", data={"w": "HELLO"})
    assert res.status_code == 200
    body = res.data.decode()
    assert "HELLO" in body
    assert 'data-idx="0"' in body
    assert "is-edited" in body

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["words"][0]["w"] == "HELLO"
    assert on_disk["words"][0]["edited"] is True
    assert on_disk["edited_at"] is not None
    # Exports regenerated.
    assert "HELLO world" in open(base + ".txt").read()


def test_patch_word_missing_body_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/tword1/word/0", data={})
    assert res.status_code == 400


def test_patch_word_unknown_id_returns_404(client):
    res = client.patch("/api/transcribe/nope/word/0", data={"w": "x"})
    assert res.status_code == 404


def test_patch_word_out_of_range_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/tword1/word/99", data={"w": "x"})
    assert res.status_code == 400


def test_patch_word_requires_token_when_set(client, tmp_path, monkeypatch):
    _seed(client, tmp_path)
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    res = client.patch("/api/transcribe/tword1/word/0", data={"w": "x"})
    assert res.status_code == 401
    res = client.patch(
        "/api/transcribe/tword1/word/0",
        data={"w": "x"},
        headers={"Authorization": "Bearer secret"},
    )
    assert res.status_code == 200


# ----- delete (DELETE) -----------------------------------------------------

def test_delete_word_marks_deleted_and_returns_hidden_span(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.delete("/api/transcribe/tword1/word/1")
    assert res.status_code == 200
    body = res.data.decode()
    assert 'data-idx="1"' in body
    assert "is-deleted" in body
    assert "hidden" in body

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["words"][1]["deleted"] is True
    assert "world" not in open(base + ".txt").read()


def test_delete_word_unknown_id_returns_404(client):
    assert client.delete("/api/transcribe/nope/word/0").status_code == 404


# ----- insert_after (POST) -------------------------------------------------

def test_insert_after_returns_new_partial_with_fresh_idx(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/tword1/word/0/insert-after", data={"w": "dear"})
    assert res.status_code == 200
    body = res.data.decode()
    assert 'data-idx="2"' in body
    assert ">dear<" in body

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["words"][-1]["w"] == "dear"
    assert on_disk["segments"][0]["word_idxs"] == [0, 2, 1]
    assert "hello dear world" in open(base + ".txt").read()


def test_insert_after_unknown_word_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/tword1/word/99/insert-after", data={"w": "x"})
    assert res.status_code == 400


# ----- merge_next (POST) ---------------------------------------------------

def test_merge_next_returns_anchor_plus_oob_peer(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/tword1/word/0/merge-next")
    assert res.status_code == 200
    body = res.data.decode()
    # Anchor span is the primary swap (no oob attribute).
    assert 'data-idx="0"' in body
    assert "helloworld" in body
    # Peer span is OOB so the deleted state is reflected immediately.
    assert 'data-idx="1"' in body
    assert 'hx-swap-oob="outerHTML"' in body
    assert "is-deleted" in body

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["words"][0]["w"] == "helloworld"
    assert on_disk["words"][1]["deleted"] is True


def test_merge_next_at_segment_tail_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/tword1/word/1/merge-next")
    assert res.status_code == 400


def test_merge_next_unknown_id_returns_404(client):
    res = client.post("/api/transcribe/nope/word/0/merge-next")
    assert res.status_code == 404
