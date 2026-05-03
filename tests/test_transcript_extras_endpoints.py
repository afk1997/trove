"""HTTP endpoint tests for find-replace, speaker, bookmark routes (TR-E7, E10, E11)."""
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


def _seed(client, tmp_path, transcribe_id="textra1", parent_id="pextra1"):
    """Seed a small v2 transcript so endpoints have something to mutate."""
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
        "duration": 4.0,
        "edited_at": None,
        "words": [
            {"idx": 0, "w": "the", "original_w": "the", "start": 0.0, "end": 0.4, "edited": False, "deleted": False},
            {"idx": 1, "w": "fox", "original_w": "fox", "start": 0.4, "end": 0.8, "edited": False, "deleted": False},
            {"idx": 2, "w": "and", "original_w": "and", "start": 0.8, "end": 1.2, "edited": False, "deleted": False},
            {"idx": 3, "w": "the", "original_w": "the", "start": 1.2, "end": 1.6, "edited": False, "deleted": False},
            {"idx": 4, "w": "dog", "original_w": "dog", "start": 1.6, "end": 2.0, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 0.0, "end": 1.2, "text": "the fox and", "word_idxs": [0, 1, 2], "speaker": None},
            {"start": 1.2, "end": 2.0, "text": "the dog",     "word_idxs": [3, 4],    "speaker": None},
        ],
        "bookmarks": [],
    }
    (download_dir / f"{parent_id}.words.json").write_text(json.dumps(payload))
    (download_dir / f"{parent_id}.txt").write_text("the fox and the dog\n")

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


# ----- find-replace --------------------------------------------------------

def test_find_replace_returns_count_and_fragments(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post(
        "/api/transcribe/textra1/find-replace",
        data={"find": "the", "replace": "THE"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["count"] == 2
    assert set(body["fragments"].keys()) == {"0", "3"}
    assert "THE" in body["fragments"]["0"]
    assert "is-edited" in body["fragments"]["0"]

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["words"][0]["w"] == "THE"
    assert on_disk["words"][3]["w"] == "THE"
    assert on_disk["edited_at"] is not None
    txt = open(base + ".txt").read()
    assert "THE fox and" in txt
    assert "THE dog" in txt


def test_find_replace_no_matches_returns_zero_and_does_not_save(client, tmp_path):
    base = _seed(client, tmp_path)
    before = json.loads(open(base + ".words.json").read())
    res = client.post(
        "/api/transcribe/textra1/find-replace",
        data={"find": "zzz", "replace": "x"},
    )
    assert res.status_code == 200
    assert res.get_json() == {"count": 0, "fragments": {}}
    after = json.loads(open(base + ".words.json").read())
    assert after["edited_at"] == before["edited_at"]


def test_find_replace_missing_find_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/textra1/find-replace", data={"replace": "x"})
    assert res.status_code == 400


def test_find_replace_unknown_transcribe_id_returns_404(client):
    res = client.post("/api/transcribe/nope/find-replace", data={"find": "x", "replace": "y"})
    assert res.status_code == 404


# ----- speaker -------------------------------------------------------------

def test_patch_speaker_propagates_and_returns_segment_fragments(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.patch(
        "/api/transcribe/textra1/segment/0/speaker",
        data={"speaker": "Alice", "propagate": "1"},
    )
    assert res.status_code == 200
    body = res.data.decode()
    assert 'data-seg-idx="0"' in body
    assert 'data-seg-idx="1"' in body
    assert "Alice" in body

    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["segments"][0]["speaker"] == "Alice"
    assert on_disk["segments"][1]["speaker"] == "Alice"


def test_patch_speaker_clear_does_not_propagate(client, tmp_path):
    base = _seed(client, tmp_path)
    # Set both first
    client.patch("/api/transcribe/textra1/segment/0/speaker", data={"speaker": "Alice", "propagate": "1"})
    # Now clear segment 0 only
    res = client.patch("/api/transcribe/textra1/segment/0/speaker", data={"speaker": "", "propagate": "1"})
    assert res.status_code == 200
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["segments"][0]["speaker"] is None
    assert on_disk["segments"][1]["speaker"] == "Alice"


def test_patch_speaker_out_of_range_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/textra1/segment/99/speaker", data={"speaker": "x"})
    assert res.status_code == 400


def test_patch_speaker_unknown_transcribe_id_returns_404(client):
    res = client.patch("/api/transcribe/nope/segment/0/speaker", data={"speaker": "x"})
    assert res.status_code == 404


# ----- bookmarks -----------------------------------------------------------

def test_create_bookmark_returns_partial_and_persists(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/textra1/bookmark", data={"time": "12.5", "note": "key insight"})
    assert res.status_code == 200
    body = res.data.decode()
    assert "data-bm-id=\"bm_" in body
    assert "key insight" in body
    on_disk = json.loads(open(base + ".words.json").read())
    assert len(on_disk["bookmarks"]) == 1
    assert on_disk["bookmarks"][0]["time"] == 12.5


def test_create_bookmark_missing_time_returns_400(client, tmp_path):
    _seed(client, tmp_path)
    res = client.post("/api/transcribe/textra1/bookmark", data={"note": "x"})
    assert res.status_code == 400


def test_update_bookmark_changes_note(client, tmp_path):
    base = _seed(client, tmp_path)
    res = client.post("/api/transcribe/textra1/bookmark", data={"time": "1.0", "note": "old"})
    bm_id = json.loads(open(base + ".words.json").read())["bookmarks"][0]["id"]
    res = client.patch(f"/api/transcribe/textra1/bookmark/{bm_id}", data={"note": "new"})
    assert res.status_code == 200
    assert "new" in res.data.decode()
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["bookmarks"][0]["note"] == "new"


def test_update_bookmark_unknown_returns_404(client, tmp_path):
    _seed(client, tmp_path)
    res = client.patch("/api/transcribe/textra1/bookmark/bm_nope", data={"note": "x"})
    assert res.status_code == 404


def test_delete_bookmark_removes(client, tmp_path):
    base = _seed(client, tmp_path)
    client.post("/api/transcribe/textra1/bookmark", data={"time": "1.0", "note": "x"})
    bm_id = json.loads(open(base + ".words.json").read())["bookmarks"][0]["id"]
    res = client.delete(f"/api/transcribe/textra1/bookmark/{bm_id}")
    assert res.status_code == 200
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["bookmarks"] == []


def test_delete_bookmark_unknown_returns_404(client, tmp_path):
    _seed(client, tmp_path)
    res = client.delete("/api/transcribe/textra1/bookmark/bm_nope")
    assert res.status_code == 404


# ----- e2e sweep (TR-E13) --------------------------------------------------

def test_full_edit_cycle_persists_and_regenerates_exports(client, tmp_path):
    """One transcript through every editor mutation; reload and verify state."""
    base = _seed(client, tmp_path, transcribe_id="t_e2e", parent_id="p_e2e")

    # 1. set_text idx 0 ("the" -> "THE")
    assert client.patch("/api/transcribe/t_e2e/word/0", data={"w": "THE"}).status_code == 200
    # 2. insert "quick" after idx 0 -> new word at idx 5, seg 0 word_idxs becomes [0, 5, 1, 2]
    assert client.post("/api/transcribe/t_e2e/word/0/insert-after", data={"w": "quick"}).status_code == 200
    # 3. merge idx 0 ("THE") with its next visible peer in same segment (idx 5 "quick")
    assert client.post("/api/transcribe/t_e2e/word/0/merge-next").status_code == 200
    # 4. delete idx 4 ("dog")
    assert client.delete("/api/transcribe/t_e2e/word/4").status_code == 200
    # 5. set speaker (cascades to seg 1)
    assert client.patch("/api/transcribe/t_e2e/segment/0/speaker",
                        data={"speaker": "Alice", "propagate": "1"}).status_code == 200
    # 6. bookmark
    bm_res = client.post("/api/transcribe/t_e2e/bookmark", data={"time": "1.5", "note": "marker"})
    assert bm_res.status_code == 200
    # 7. find-replace
    fr_res = client.post("/api/transcribe/t_e2e/find-replace",
                         data={"find": "fox", "replace": "FOX"})
    assert fr_res.status_code == 200
    assert fr_res.get_json()["count"] == 1

    # Reload via the GET route -> page must render.
    page = client.get("/transcript/t_e2e")
    assert page.status_code == 200
    html = page.data.decode()
    assert "THE quick" in html
    assert "FOX" in html
    assert "Alice" in html
    assert "marker" in html

    # On-disk state survives.
    on_disk = json.loads(open(base + ".words.json").read())
    assert on_disk["words"][0]["w"] == "THE quick"  # set_text + merge with inserted "quick"
    assert on_disk["words"][1]["w"] == "FOX"
    assert on_disk["words"][4]["deleted"] is True
    assert on_disk["words"][5]["deleted"] is True  # merged-into-anchor peer
    assert on_disk["segments"][0]["speaker"] == "Alice"
    assert on_disk["segments"][1]["speaker"] == "Alice"
    assert len(on_disk["bookmarks"]) == 1
    assert on_disk["edited_at"] is not None

    # Exports regenerated.
    txt = open(base + ".txt").read()
    assert "THE" in txt
    assert "FOX" in txt
    assert "dog" not in txt
