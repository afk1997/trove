import pytest
from app import create_app
import time as _time


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    import app as _app
    import models_store
    # Repoint both data dirs at the per-test temp dir so jobs.json /
    # transcribe_jobs.json don't pollute across test runs.
    (tmp_path / "downloads").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    return app.test_client()


def test_setup_page_renders_first_time(client):
    """No model installed -> setup wizard mode."""
    res = client.get("/transcribe/setup")
    assert res.status_code == 200
    body = res.data.decode()
    assert "transcribe" in body.lower()
    assert "machine" in body.lower()
    for label in ("tiny", "base", "small", "medium"):
        assert label in body.lower()


def test_setup_page_renders_settings_when_model_installed(client, monkeypatch, tmp_path):
    import models_store
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")
    res = client.get("/transcribe/setup")
    assert res.status_code == 200
    body = res.data.decode().lower()
    assert "settings" in body or "active" in body


def test_setup_model_endpoint_unknown_model_400(client):
    res = client.post("/api/transcribe/setup-model", data={"name": "ggml-foo.bin"})
    assert res.status_code == 400


def test_setup_progress_endpoint_returns_status(client):
    """Polling endpoint returns 200 even when no download is in-flight (idle)."""
    res = client.get("/api/transcribe/setup-progress")
    assert res.status_code == 200


def test_setup_progress_requires_token_when_set(tmp_path, monkeypatch):
    """When TROVE_TOKEN is set, the polling endpoint must enforce it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    import models_store
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    c = app.test_client()
    # Without bearer header → 401
    assert c.get("/api/transcribe/setup-progress").status_code == 401
    # With it → 200
    assert c.get("/api/transcribe/setup-progress",
                 headers={"Authorization": "Bearer secret"}).status_code == 200


def test_setup_model_endpoint_busy_returns_409(client, monkeypatch):
    """Two parallel POSTs to setup-model: first 202, second 409."""
    import models_store
    # Block urlopen so the worker thread stays in 'downloading' state
    import threading
    block = threading.Event()

    class _SlowResp:
        headers = {"Content-Length": "100"}
        def read(self, n=-1):
            block.wait(timeout=1)
            return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(models_store, "urlopen", lambda *a, **kw: _SlowResp())
    r1 = client.post("/api/transcribe/setup-model", data={"name": "ggml-tiny.bin"})
    assert r1.status_code == 202
    r2 = client.post("/api/transcribe/setup-model", data={"name": "ggml-base.bin"})
    assert r2.status_code == 409
    block.set()


def test_setup_model_remove_endpoint(client, tmp_path):
    import models_store
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "ggml-base.bin").write_bytes(b"x")
    res = client.post("/api/transcribe/setup-model/remove", data={"name": "ggml-base.bin"})
    assert res.status_code == 200
    assert not (tmp_path / "models" / "ggml-base.bin").exists()


def test_setup_model_remove_unknown_400(client):
    res = client.post("/api/transcribe/setup-model/remove", data={"name": "ggml-foo.bin"})
    assert res.status_code == 400


def test_setup_model_progress_advances(client, monkeypatch, tmp_path):
    """End-to-end: kick off a download against a fake HF, poll progress until done."""
    import models_store
    payload = b"X" * 5_000_000  # 5 MB

    class _FakeResp:
        def __init__(self, data):
            self._buf = data
            self._idx = 0
            self.headers = {"Content-Length": str(len(data))}
        def read(self, n=-1):
            chunk = self._buf[self._idx:self._idx + (n if n > 0 else len(self._buf) - self._idx)]
            self._idx += len(chunk)
            _time.sleep(0.01)  # slow it down so we can observe progress
            return chunk
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(models_store, "urlopen",
                        lambda url, timeout=None: _FakeResp(payload))

    res = client.post("/api/transcribe/setup-model", data={"name": "ggml-tiny.bin"})
    assert res.status_code == 202

    # Poll for ~5s until done
    deadline = _time.monotonic() + 5
    while _time.monotonic() < deadline:
        body = client.get("/api/transcribe/setup-progress").data.decode()
        if "installed" in body or "couldn't reach" in body:
            break
        _time.sleep(0.1)

    final = client.get("/api/transcribe/setup-progress").data.decode()
    # Expected: error (sha256 mismatch since payload is fake) — that's OK, we're
    # testing that the polling endpoint returns something terminal.
    assert "couldn't reach" in final or "installed" in final


def test_setup_settings_mode_shows_active_marker(client, tmp_path):
    import models_store
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")

    body = client.get("/transcribe/setup").data.decode()
    assert "✓ ACTIVE" in body
    # Other models render a "switch to this" or "pick this" button (since they're not installed)
    assert "pick this model" in body or "switch to this" in body
    # Header reads settings, not setup
    assert "settings" in body.lower()


def test_transcribe_start_no_model_returns_consent_modal(client):
    """If no model is installed, /api/transcribe/<parent>/start renders the consent modal."""
    res = client.post("/api/transcribe/abc1/start")
    assert res.status_code == 200
    body = res.data.decode().lower()
    assert "consent" in body or "transcribe" in body or "huggingface" in body or "trove" in body


def test_transcribe_start_unknown_parent_404(client, tmp_path):
    """Even with model installed, an unknown parent job → 404."""
    import models_store
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")

    res = client.post("/api/transcribe/unknownjob/start")
    assert res.status_code == 404


def test_transcribe_status_unknown_returns_404(client):
    res = client.get("/api/transcribe/unknown/status")
    assert res.status_code == 404


def test_transcribe_cancel_unknown_returns_404(client):
    res = client.post("/api/transcribe/unknown/cancel")
    assert res.status_code == 404


def test_transcribe_dismiss_unknown_returns_404(client):
    res = client.post("/api/transcribe/unknown/dismiss")
    assert res.status_code == 404


def test_done_card_includes_transcribe_action(client):
    """A DONE job's status-card response includes the in-card transcribe row."""
    from jobs import Job, JobStatus
    jm = client.application.extensions["trove.jobs"]
    with jm._lock:
        jm._jobs["donejob9"] = Job(
            id="donejob9", url="https://e.com", title="Done Already",
            status=JobStatus.DONE, file_path="/tmp/x.mp4", filename="x.mp4",
        )
    body = client.get("/api/status-card/donejob9").data.decode()
    assert "clip-transcribe-row" in body
    assert "▸ transcribe" in body


def test_transcript_page_renders(client, tmp_path, monkeypatch):
    """A complete TranscribeJob with on-disk artifacts renders the viewer."""
    import json as _j
    from jobs import Job, JobStatus
    from transcribe_jobs import TranscribeJob, TranscribeStatus

    # Set up a parent media job + on-disk file + words.json
    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    media = download_dir / "abc1.mp4"
    media.write_bytes(b"fake")
    words_json = download_dir / "abc1.words.json"
    words_json.write_text(_j.dumps({
        "language": "en",
        "duration": 12.0,
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello world",
                      "words": [{"w": "hello", "start": 0.0, "end": 0.5},
                                {"w": "world", "start": 0.5, "end": 1.0}]}],
        "words": [{"w": "hello", "start": 0.0, "end": 0.5},
                  {"w": "world", "start": 0.5, "end": 1.0}],
    }))

    monkeypatch.setattr("app.DOWNLOAD_DIR", download_dir)

    jm = client.application.extensions["trove.jobs"]
    tjm = client.application.extensions["trove.transcribe"]
    with jm._lock:
        jm._jobs["abc1"] = Job(id="abc1", url="https://x", title="Hello",
                                status=JobStatus.DONE,
                                file_path=str(media), filename="abc1.mp4")
    with tjm._lock:
        tjm._jobs["t1"] = TranscribeJob(id="t1", parent_job_id="abc1",
                                         model_used="ggml-base.bin",
                                         status=TranscribeStatus.DONE)

    res = client.get("/transcript/t1")
    assert res.status_code == 200
    body = res.data.decode()
    # v3 four-zone document layout
    assert 'class="transcript-doc"' in body
    assert 'id="t-doc-header"' in body
    assert 'id="t-doc-toolbar"' in body
    assert 'id="t-player-bar"' in body
    assert 'id="t-body"' in body
    # contenteditable paragraph + word spans
    assert 'class="t-seg-body"' in body
    assert 'contenteditable="plaintext-only"' in body
    assert "<video" in body or "<audio" in body
    assert 'data-start="0.0"' in body
    assert "hello" in body and "world" in body


def _setup_done_transcribe(client, tmp_path):
    """Helper: build a parent media + done TranscribeJob + on-disk side-files."""
    from jobs import Job, JobStatus
    from transcribe_jobs import TranscribeJob, TranscribeStatus

    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    media = download_dir / "xx9.mp4"
    media.write_bytes(b"fake")
    (download_dir / "xx9.txt").write_text("hello world\n")
    (download_dir / "xx9.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
    (download_dir / "xx9.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n")

    jm = client.application.extensions["trove.jobs"]
    tjm = client.application.extensions["trove.transcribe"]
    with jm._lock:
        jm._jobs["xx9"] = Job(id="xx9", url="https://x", title="HW",
                              status=JobStatus.DONE,
                              file_path=str(media), filename="xx9.mp4")
    with tjm._lock:
        tjm._jobs["tx9"] = TranscribeJob(id="tx9", parent_job_id="xx9",
                                          model_used="ggml-base.bin",
                                          status=TranscribeStatus.DONE)


def test_export_txt(client, tmp_path):
    _setup_done_transcribe(client, tmp_path)
    res = client.get("/api/transcribe/tx9/export.txt")
    assert res.status_code == 200
    assert res.mimetype == "text/plain"
    assert b"hello world" in res.data


def test_export_srt(client, tmp_path):
    _setup_done_transcribe(client, tmp_path)
    res = client.get("/api/transcribe/tx9/export.srt")
    assert res.status_code == 200
    assert "x-subrip" in res.mimetype


def test_export_vtt(client, tmp_path):
    _setup_done_transcribe(client, tmp_path)
    res = client.get("/api/transcribe/tx9/export.vtt")
    assert res.status_code == 200
    assert "vtt" in res.mimetype
    assert b"WEBVTT" in res.data


def test_export_unknown_format_404(client, tmp_path):
    _setup_done_transcribe(client, tmp_path)
    res = client.get("/api/transcribe/tx9/export.json")
    assert res.status_code == 404


def test_export_unknown_id_404(client):
    res = client.get("/api/transcribe/zzz/export.txt")
    assert res.status_code == 404


def test_signed_file_url_works_under_token(tmp_path, monkeypatch):
    """When TROVE_TOKEN is set, /api/file/<id>?sig=<hmac> serves without bearer.

    This is the path the transcript page's <video src> uses, since browsers
    can't attach Authorization headers to media src.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    import models_store
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    c = app.test_client()

    from jobs import Job, JobStatus
    media = tmp_path / "abc1.mp4"
    media.write_bytes(b"M4A-FAKE")
    jm = app.extensions["trove.jobs"]
    with jm._lock:
        jm._jobs["abc1"] = Job(id="abc1", url="https://x", title="x",
                               status=JobStatus.DONE,
                               file_path=str(media), filename="abc1.mp4")

    # Without sig and without bearer → 401
    assert c.get("/api/file/abc1").status_code == 401
    # With bearer → 200
    assert c.get("/api/file/abc1",
                 headers={"Authorization": "Bearer secret"}).status_code == 200
    # With matching sig → 200
    from safety import sign_resource
    sig = sign_resource("abc1")
    assert sig  # token is set, so sig is non-empty
    assert c.get(f"/api/file/abc1?sig={sig}").status_code == 200
    # With wrong sig → 401
    assert c.get("/api/file/abc1?sig=deadbeef").status_code == 401


def test_transcribe_start_idempotent_for_running_parent(client, tmp_path, monkeypatch):
    """Two POSTs to /start in quick succession yield only one TranscribeJob."""
    import models_store
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")

    from jobs import Job, JobStatus
    from pathlib import Path
    media = tmp_path / "abc2.mp4"
    media.write_bytes(b"x")
    jm = client.application.extensions["trove.jobs"]
    with jm._lock:
        jm._jobs["abc2"] = Job(id="abc2", url="https://x", title="x",
                               status=JobStatus.DONE,
                               file_path=str(media), filename="abc2.mp4")

    # Patch extract_audio + run_transcribe to block briefly so the first
    # transcribe stays RUNNING when the second POST arrives.
    import transcriber
    import time as _t
    def _slow_extract(src, dst):
        _t.sleep(0.4)
        Path(dst).write_bytes(b"WAV-FAKE")
    monkeypatch.setattr(transcriber, "extract_audio", _slow_extract)
    monkeypatch.setattr(transcriber, "_load_pywhispercpp_model",
                        lambda p: type("M", (), {
                            "transcribe": lambda self, *a, **kw: [],
                            "detected_language": lambda self: "en",
                        })())

    r1 = client.post("/api/transcribe/abc2/start")
    assert r1.status_code == 200
    # Give the worker a moment to set status=RUNNING
    _t.sleep(0.1)
    r2 = client.post("/api/transcribe/abc2/start")
    assert r2.status_code == 200
    # Only one TranscribeJob should exist for this parent
    tjm = client.application.extensions["trove.transcribe"]
    with tjm._lock:
        jobs_for_parent = [j for j in tjm._jobs.values() if j.parent_job_id == "abc2"]
    assert len(jobs_for_parent) == 1


def test_transcribe_status_orphaned_returns_404(client, tmp_path):
    """If parent job is gone, status endpoint dismisses the orphan and 404s."""
    from transcribe_jobs import TranscribeJob, TranscribeStatus
    tjm = client.application.extensions["trove.transcribe"]
    with tjm._lock:
        tjm._jobs["orphan1"] = TranscribeJob(
            id="orphan1", parent_job_id="ghost",
            model_used="ggml-base.bin", status=TranscribeStatus.RUNNING,
        )
    res = client.get("/api/transcribe/orphan1/status")
    assert res.status_code == 404
    # Should have been dismissed
    with tjm._lock:
        assert "orphan1" not in tjm._jobs


# ---------------------------------------------------------------------------
# Auth-boundary regression tests: /transcript/<id> and /api/transcribe/<id>/
# export.<fmt> were previously unauthenticated, leaking transcript content
# (and signed media URLs) to anyone who could guess a transcribe_id.
# ---------------------------------------------------------------------------

def _seed_done_transcribe(app, tmp_path, parent_id="abc9", tj_id="tj9"):
    """Set up a parent job + DONE transcribe job + minimal artifacts on disk."""
    from jobs import Job, JobStatus
    from transcribe_jobs import TranscribeJob, TranscribeStatus
    media = tmp_path / "downloads" / f"{parent_id}.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"M4A-FAKE")
    base = str(media.with_suffix(""))
    # Minimal v2 transcript artifact so _resolve_transcribe_paths returns it
    # AND the transcript template renders (segments need start/end/word_idxs;
    # words need idx/w/start/end/original_w/edited/deleted).
    import json
    (media.parent / f"{parent_id}.words.json").write_text(json.dumps({
        "schema_version": 2,
        "language": "en",
        "duration": 1.0,
        "title": None,
        "highlights": [],
        "notes": [],
        "words": [{
            "idx": 0, "w": "hi", "original_w": "hi",
            "start": 0.0, "end": 0.5,
            "edited": False, "deleted": False,
        }],
        "segments": [{
            "start": 0.0, "end": 0.5,
            "word_idxs": [0], "text": "hi",
            "speaker": None, "reviewed": False,
        }],
    }))
    (media.parent / f"{parent_id}.txt").write_text("hi\n")
    (media.parent / f"{parent_id}.srt").write_text("1\n00:00:00,000 --> 00:00:00,500\nhi\n\n")
    (media.parent / f"{parent_id}.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nhi\n\n")
    jm = app.extensions["trove.jobs"]
    tjm = app.extensions["trove.transcribe"]
    with jm._lock:
        jm._jobs[parent_id] = Job(
            id=parent_id, url="https://x", title="x",
            status=JobStatus.DONE,
            file_path=str(media), filename=f"{parent_id}.mp4",
        )
    with tjm._lock:
        tjm._jobs[tj_id] = TranscribeJob(
            id=tj_id, parent_job_id=parent_id,
            model_used="ggml-base.bin",
            status=TranscribeStatus.DONE,
        )
    return base


def test_transcript_view_requires_token_or_sig(tmp_path, monkeypatch):
    """/transcript/<id> must reject anonymous access when TROVE_TOKEN is set."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    import app as _app
    import models_store
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    c = app.test_client()
    _seed_done_transcribe(app, tmp_path, parent_id="abc9", tj_id="tj9")

    # No bearer, no sig → 401
    assert c.get("/transcript/tj9").status_code == 401
    # Bearer → 200
    assert c.get("/transcript/tj9",
                 headers={"Authorization": "Bearer secret"}).status_code == 200
    # Matching sig (transcribe_id is the resource) → 200
    from safety import sign_resource
    sig = sign_resource("tj9")
    assert sig
    assert c.get(f"/transcript/tj9?sig={sig}").status_code == 200
    # Wrong sig → 401
    assert c.get("/transcript/tj9?sig=deadbeef").status_code == 401


def test_export_requires_token_or_sig(tmp_path, monkeypatch):
    """/api/transcribe/<id>/export.<fmt> must reject anonymous access under TROVE_TOKEN."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    import app as _app
    import models_store
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")
    app = create_app()
    c = app.test_client()
    _seed_done_transcribe(app, tmp_path, parent_id="abc8", tj_id="tj8")

    # No auth → 401 for every format
    for fmt in ("txt", "srt", "vtt"):
        assert c.get(f"/api/transcribe/tj8/export.{fmt}").status_code == 401
    # Bearer → 200
    assert c.get("/api/transcribe/tj8/export.txt",
                 headers={"Authorization": "Bearer secret"}).status_code == 200
    # Matching sig → 200
    from safety import sign_resource
    sig = sign_resource("tj8")
    assert c.get(f"/api/transcribe/tj8/export.srt?sig={sig}").status_code == 200
    # Wrong sig → 401
    assert c.get("/api/transcribe/tj8/export.vtt?sig=deadbeef").status_code == 401


def test_csp_frame_ancestors_is_locked_down(client):
    """Clickjacking guard: CSP must NOT allow framing from arbitrary origins."""
    res = client.get("/")
    csp = res.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp
    assert "frame-ancestors 'none'" in csp
    assert "frame-ancestors *" not in csp
