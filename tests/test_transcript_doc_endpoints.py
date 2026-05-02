"""HTTP endpoint tests for the v3 transcript-document routes (TR-D)."""
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


def _seed(client, tmp_path, transcribe_id="td1", parent_id="pd1"):
    """Three-segment fixture for split/merge/highlight/note coverage."""
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
        "duration": 6.0,
        "edited_at": None,
        "title": None,
        "words": [
            {"idx": 0, "w": "alpha", "original_w": "alpha", "start": 0.0, "end": 0.5, "edited": False, "deleted": False},
            {"idx": 1, "w": "beta",  "original_w": "beta",  "start": 0.5, "end": 1.0, "edited": False, "deleted": False},
            {"idx": 2, "w": "gamma", "original_w": "gamma", "start": 1.0, "end": 1.5, "edited": False, "deleted": False},
            {"idx": 3, "w": "delta", "original_w": "delta", "start": 2.0, "end": 2.5, "edited": False, "deleted": False},
            {"idx": 4, "w": "epsilon","original_w":"epsilon","start": 2.5,"end": 3.0, "edited": False, "deleted": False},
            {"idx": 5, "w": "zeta",  "original_w": "zeta",  "start": 4.0, "end": 4.5, "edited": False, "deleted": False},
            {"idx": 6, "w": "eta",   "original_w": "eta",   "start": 4.5, "end": 5.0, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "alpha beta gamma",
             "word_idxs": [0, 1, 2], "speaker": "Alice", "reviewed": False},
            {"start": 2.0, "end": 3.0, "text": "delta epsilon",
             "word_idxs": [3, 4],    "speaker": "Bob",   "reviewed": False},
            {"start": 4.0, "end": 5.0, "text": "zeta eta",
             "word_idxs": [5, 6],    "speaker": "Alice", "reviewed": False},
        ],
        "bookmarks": [],
        "highlights": [],
        "notes": [],
    }
    (download_dir / f"{parent_id}.words.json").write_text(json.dumps(payload))
    (download_dir / f"{parent_id}.txt").write_text("alpha beta gamma\n\ndelta epsilon\n\nzeta eta\n")

    jm = client.application.extensions["trove.jobs"]
    tjm = client.application.extensions["trove.transcribe"]
    with jm._lock:
        jm._jobs[parent_id] = Job(
            id=parent_id, url="https://x", title="Doc Title",
            status=JobStatus.DONE,
            file_path=str(media), filename=f"{parent_id}.mp4",
        )
    with tjm._lock:
        tjm._jobs[transcribe_id] = TranscribeJob(
            id=transcribe_id, parent_job_id=parent_id,
            model_used="ggml-base.bin", status=TranscribeStatus.DONE,
        )
    return base


# ----- title ---------------------------------------------------------------

def test_title_patch_persists_and_echoes(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/title", data={"title": "New Title"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["title"] == "New Title"
    assert body["effective"] == "New Title"
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["title"] == "New Title"


def test_title_patch_blank_falls_back_to_parent(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/title", data={"title": "  "})
    assert res.status_code == 200
    body = res.get_json()
    assert body["title"] is None
    assert body["effective"] == "Doc Title"


def test_title_patch_missing_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/title", data={})
    assert res.status_code == 400


def test_title_patch_unknown_id_returns_404(client):
    res = client.patch("/api/transcribe/nope/title", data={"title": "x"})
    assert res.status_code == 404


# ----- segment split -------------------------------------------------------

def test_segment_split_returns_two_segment_fragments(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post(
        "/api/transcribe/td1/segment/0/split",
        data={"after_word_idx": "1"},
    )
    assert res.status_code == 200
    html = res.data.decode()
    assert 'data-seg-idx="0"' in html
    assert 'data-seg-idx="1"' in html

    on_disk = json.loads(open(base + ".words.json").read())
    assert len(on_disk["segments"]) == 4
    assert on_disk["segments"][0]["word_idxs"] == [0, 1]
    assert on_disk["segments"][1]["word_idxs"] == [2]
    # Right half inherits speaker from original.
    assert on_disk["segments"][1]["speaker"] == "Alice"


def test_segment_split_invalid_after_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    # word 99 doesn't belong to segment 0
    res = client.post("/api/transcribe/td1/segment/0/split", data={"after_word_idx": "99"})
    assert res.status_code == 400
    # last word in segment 0 is idx 2 → cannot split
    res = client.post("/api/transcribe/td1/segment/0/split", data={"after_word_idx": "2"})
    assert res.status_code == 400


def test_segment_split_missing_after_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/segment/0/split", data={})
    assert res.status_code == 400


def test_segment_split_unknown_id_returns_404(client):
    res = client.post("/api/transcribe/nope/segment/0/split", data={"after_word_idx": "0"})
    assert res.status_code == 404


# ----- segment merge-prev --------------------------------------------------

def test_segment_merge_prev_returns_merged_fragment(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/segment/1/merge-prev")
    assert res.status_code == 200
    assert 'data-seg-idx="0"' in res.data.decode()

    on_disk = json.loads(open(base + ".words.json").read())
    assert len(on_disk["segments"]) == 2
    assert on_disk["segments"][0]["word_idxs"] == [0, 1, 2, 3, 4]
    assert on_disk["segments"][0]["speaker"] == "Alice"


def test_segment_merge_prev_first_segment_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/segment/0/merge-prev")
    assert res.status_code == 400


def test_segment_merge_prev_unknown_id_returns_404(client):
    res = client.post("/api/transcribe/nope/segment/1/merge-prev")
    assert res.status_code == 404


# ----- speaker rename (global) --------------------------------------------

def test_speaker_rename_updates_all_matching(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch(
        "/api/transcribe/td1/speaker-rename",
        data={"old": "Alice", "new": "Anna"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["updated"] == [0, 2]  # both Alice segments
    assert 'data-seg-idx="0"' in body["html"]
    assert 'data-seg-idx="2"' in body["html"]
    assert "Anna" in body["html"]

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["segments"][0]["speaker"] == "Anna"
    assert on_disk["segments"][1]["speaker"] == "Bob"  # untouched
    assert on_disk["segments"][2]["speaker"] == "Anna"


def test_speaker_rename_no_matches_returns_empty_updated(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch(
        "/api/transcribe/td1/speaker-rename",
        data={"old": "Nobody", "new": "X"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["updated"] == []
    assert body["html"] == ""


def test_speaker_rename_clear_to_empty(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch(
        "/api/transcribe/td1/speaker-rename",
        data={"old": "Bob", "new": ""},
    )
    assert res.status_code == 200
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["segments"][1]["speaker"] is None


def test_speaker_rename_missing_fields_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/speaker-rename", data={"old": "x"})
    assert res.status_code == 400


def test_speaker_rename_unknown_id_returns_404(client):
    res = client.patch("/api/transcribe/nope/speaker-rename",
                       data={"old": "a", "new": "b"})
    assert res.status_code == 404


# ----- highlights ---------------------------------------------------------

def test_highlight_create_returns_dict_and_persists(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/highlight",
                      data={"word_idx_start": "1", "word_idx_end": "3"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["id"].startswith("h_")
    assert body["word_idx_start"] == 1
    assert body["word_idx_end"] == 3
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["highlights"] == [body]


def test_highlight_create_invalid_range_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/highlight",
                      data={"word_idx_start": "5", "word_idx_end": "1"})
    assert res.status_code == 400


def test_highlight_create_missing_fields_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/highlight", data={})
    assert res.status_code == 400


def test_highlight_delete_removes(client, tmp_path):
    base = _seed(client, tmp_path)
    create = client.post("/api/transcribe/td1/highlight",
                         data={"word_idx_start": "0", "word_idx_end": "1"})
    h_id = create.get_json()["id"]
    res = client.delete(f"/api/transcribe/td1/highlight/{h_id}")
    assert res.status_code == 200
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["highlights"] == []


def test_highlight_delete_unknown_returns_404(client, tmp_path):
    _seed(client, tmp_path)
    res = client.delete("/api/transcribe/td1/highlight/h_nope")
    assert res.status_code == 404


def test_highlight_unknown_transcribe_id_returns_404(client):
    res = client.post("/api/transcribe/nope/highlight",
                      data={"word_idx_start": "0", "word_idx_end": "0"})
    assert res.status_code == 404


# ----- notes --------------------------------------------------------------

def test_note_create_returns_dict_and_persists(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/note",
                      data={"word_idx": "2", "text": "hello"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["id"].startswith("n_")
    assert body["word_idx"] == 2
    assert body["text"] == "hello"
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["notes"] == [body]


def test_note_create_out_of_range_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/note", data={"word_idx": "99", "text": "x"})
    assert res.status_code == 400


def test_note_create_missing_word_idx_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/note", data={"text": "x"})
    assert res.status_code == 400


def test_note_update_changes_text(client, tmp_path):
    base = _seed(client, tmp_path)
    create = client.post("/api/transcribe/td1/note",
                         data={"word_idx": "0", "text": "old"})
    n_id = create.get_json()["id"]
    res = client.patch(f"/api/transcribe/td1/note/{n_id}", data={"text": "new"})
    assert res.status_code == 200
    assert res.get_json()["text"] == "new"
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["notes"][0]["text"] == "new"


def test_note_update_missing_text_returns_400(client, tmp_path):
    base = _seed(client, tmp_path)
    create = client.post("/api/transcribe/td1/note",
                         data={"word_idx": "0", "text": "x"})
    n_id = create.get_json()["id"]
    res = client.patch(f"/api/transcribe/td1/note/{n_id}", data={})
    assert res.status_code == 400


def test_note_update_unknown_returns_404(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/note/n_nope", data={"text": "x"})
    assert res.status_code == 404


def test_note_delete_removes(client, tmp_path):
    base = _seed(client, tmp_path)
    create = client.post("/api/transcribe/td1/note",
                         data={"word_idx": "0", "text": "x"})
    n_id = create.get_json()["id"]
    res = client.delete(f"/api/transcribe/td1/note/{n_id}")
    assert res.status_code == 200
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["notes"] == []


def test_note_delete_unknown_returns_404(client, tmp_path):
    _seed(client, tmp_path)
    res = client.delete("/api/transcribe/td1/note/n_nope")
    assert res.status_code == 404


def test_note_unknown_transcribe_id_returns_404(client):
    res = client.post("/api/transcribe/nope/note",
                      data={"word_idx": "0", "text": "x"})
    assert res.status_code == 404


# ----- reviewed -----------------------------------------------------------

def test_reviewed_patch_toggles_and_persists(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/segment/0/reviewed", data={"reviewed": "1"})
    assert res.status_code == 200
    body = res.get_json()
    assert body == {"seg_idx": 0, "reviewed": True}
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["segments"][0]["reviewed"] is True
    # Now uncheck.
    res = client.patch("/api/transcribe/td1/segment/0/reviewed", data={"reviewed": "0"})
    assert res.status_code == 200
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["segments"][0]["reviewed"] is False


def test_reviewed_patch_out_of_range_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/td1/segment/99/reviewed", data={"reviewed": "1"})
    assert res.status_code == 400


def test_reviewed_patch_unknown_id_returns_404(client):
    res = client.patch("/api/transcribe/nope/segment/0/reviewed", data={"reviewed": "1"})
    assert res.status_code == 404


# ----- export-selection ---------------------------------------------------

def test_export_selection_returns_text_with_timestamps(client, tmp_path):
    _seed(client, tmp_path)
    # Range covers seg 0 (idx 1, 2) + seg 1 (idx 3): "beta gamma" + "delta"
    res = client.post(
        "/api/transcribe/td1/export-selection",
        data={"word_idx_start": "1", "word_idx_end": "3"},
    )
    assert res.status_code == 200
    assert "text/plain" in res.mimetype
    assert "attachment" in res.headers.get("Content-Disposition", "")
    body = res.data.decode()
    assert "[00:00:00.000] beta gamma" in body
    assert "[00:00:02.000] delta" in body


def test_export_selection_invalid_range_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post(
        "/api/transcribe/td1/export-selection",
        data={"word_idx_start": "5", "word_idx_end": "1"},
    )
    assert res.status_code == 400


def test_export_selection_missing_fields_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/td1/export-selection", data={})
    assert res.status_code == 400


def test_export_selection_unknown_id_returns_404(client):
    res = client.post("/api/transcribe/nope/export-selection",
                      data={"word_idx_start": "0", "word_idx_end": "0"})
    assert res.status_code == 404


# ----- token guard --------------------------------------------------------

def test_doc_endpoints_require_token_when_set(tmp_path, monkeypatch):
    """When TROVE_TOKEN is set, doc endpoints reject unauthenticated calls."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.setenv("TROVE_TOKEN", "secret123")
    import app as _app
    import models_store
    (tmp_path / "downloads").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    client = app.test_client()
    _seed(client, tmp_path)

    # No token → 401/403.
    res = client.patch("/api/transcribe/td1/title", data={"title": "x"})
    assert res.status_code in (401, 403)
    # With token → 200.
    res = client.patch(
        "/api/transcribe/td1/title",
        data={"title": "x"},
        headers={"Authorization": "Bearer secret123"},
    )
    assert res.status_code == 200
