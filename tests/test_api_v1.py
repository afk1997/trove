"""Tests for the /api/v1 JSON blueprint (CLI + MCP backbone).

These cover the stable contract: shapes, status codes, idempotence
guards, and the auth boundary. Heavy operations (real downloads,
real whisper) are stubbed via the same monkeypatch points the
existing endpoint tests use.
"""
from __future__ import annotations
import os
import pytest
from app import create_app
from jobs import Job, JobStatus
import transcribe_jobs


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    app = create_app()
    return app, app.test_client()


# ---- meta -----------------------------------------------------------

def test_health_is_unauthenticated_and_ok(client):
    _, c = client
    r = c.get("/api/v1/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["version"] == "v1"


# ---- jobs read ------------------------------------------------------

def test_list_jobs_returns_list(client):
    # Note: DOWNLOAD_DIR / jobs.json is anchored at __file__'s parent,
    # so persisted state from a running dev server can leak into tests.
    # We assert shape (list of dicts), not emptiness.
    app, c = client
    app.extensions["trove.jobs"]._jobs.clear()
    r = c.get("/api/v1/jobs")
    assert r.status_code == 200
    assert r.get_json() == {"jobs": []}


def test_get_job_404(client):
    _, c = client
    r = c.get("/api/v1/jobs/nope")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_get_job_returns_view_shape(client):
    app, c = client
    jm = app.extensions["trove.jobs"]
    j = Job(id="abc", url="https://x", title="t", status=JobStatus.DONE,
            filename="t.mp4", file_path="/tmp/whatever")
    jm._jobs["abc"] = j
    r = c.get("/api/v1/jobs/abc")
    assert r.status_code == 200
    body = r.get_json()
    assert body["id"] == "abc"
    assert body["status"] == "done"
    assert body["url"] == "https://x"
    # Field set is part of the contract; do not silently drop fields.
    assert {"filename", "downloaded_bytes", "auto_transcribe"}.issubset(body.keys())


# ---- jobs write -----------------------------------------------------

def test_submit_job_validates_url(client):
    _, c = client
    r = c.post("/api/v1/jobs", json={})
    assert r.status_code == 400
    assert r.get_json()["error"] == "missing_url"


def test_submit_job_rejects_argument_injection(client):
    _, c = client
    r = c.post("/api/v1/jobs", json={"url": "--exec=touch /tmp/pwned"})
    assert r.status_code == 400


def test_submit_job_calls_enqueue_with_supplied_title(client, monkeypatch):
    app, c = client
    captured = {}

    def fake_enqueue(url, fmt, fmt_id, title, thumbnail="", *, auto_transcribe=False):
        captured.update(dict(
            url=url, fmt=fmt, fmt_id=fmt_id, title=title,
            thumbnail=thumbnail, auto_transcribe=auto_transcribe,
        ))
        # mimic real submit
        jm = app.extensions["trove.jobs"]
        j = Job(id="newid1", url=url, title=title, status=JobStatus.QUEUED)
        jm._jobs["newid1"] = j
        return "newid1"

    app.extensions["trove.actions"]["enqueue_download"] = fake_enqueue
    r = c.post("/api/v1/jobs", json={
        "url": "https://example.com/video",
        "format": "audio",
        "title": "My clip",
        "auto_transcribe": True,
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body["id"] == "newid1"
    assert captured["title"] == "My clip"
    assert captured["fmt"] == "audio"
    assert captured["auto_transcribe"] is True


def test_submit_job_busy_returns_503(client, monkeypatch):
    app, c = client

    def fake_enqueue(*a, **kw):
        raise RuntimeError("pool full")

    app.extensions["trove.actions"]["enqueue_download"] = fake_enqueue
    r = c.post("/api/v1/jobs", json={"url": "https://e.com", "title": "x"})
    assert r.status_code == 503
    assert r.get_json()["error"] == "busy"


def test_pause_resume_cancel_dismiss(client):
    app, c = client
    jm = app.extensions["trove.jobs"]
    jm._jobs["jid"] = Job(id="jid", url="u", title="t",
                          status=JobStatus.DOWNLOADING)
    # pause
    r = c.post("/api/v1/jobs/jid/pause")
    assert r.status_code == 200
    assert r.get_json()["status"] == "paused"
    # resume — stub the action so we don't really call yt-dlp
    called = {}
    app.extensions["trove.actions"]["resume_job"] = (
        lambda jid: called.setdefault("jid", jid) or True
    )
    r = c.post("/api/v1/jobs/jid/resume")
    assert r.status_code == 200
    assert called["jid"] == "jid"
    # cancel
    r = c.post("/api/v1/jobs/jid/cancel")
    assert r.status_code == 200
    assert r.get_json()["status"] == "cancelled"
    # dismiss
    r = c.post("/api/v1/jobs/jid/dismiss")
    assert r.status_code == 204


def test_pause_404_for_unknown(client):
    _, c = client
    r = c.post("/api/v1/jobs/missing/pause")
    assert r.status_code == 404


def test_dismiss_refuses_active_job(client):
    app, c = client
    jm = app.extensions["trove.jobs"]
    jm._jobs["live"] = Job(id="live", url="u", title="t",
                           status=JobStatus.DOWNLOADING)
    r = c.post("/api/v1/jobs/live/dismiss")
    assert r.status_code == 404


# ---- transcripts ----------------------------------------------------

def test_list_transcripts_returns_list(client):
    app, c = client
    app.extensions["trove.transcribe"]._jobs.clear()
    r = c.get("/api/v1/transcripts")
    assert r.status_code == 200
    assert r.get_json() == {"transcripts": []}


def test_start_transcribe_404_if_parent_not_done(client):
    app, c = client
    jm = app.extensions["trove.jobs"]
    jm._jobs["p"] = Job(id="p", url="u", title="t", status=JobStatus.DOWNLOADING)
    r = c.post("/api/v1/jobs/p/transcribe")
    assert r.status_code == 404
    assert r.get_json()["error"] == "parent_not_done"


def test_start_transcribe_409_when_no_active_model(client, monkeypatch):
    app, c = client
    jm = app.extensions["trove.jobs"]
    jm._jobs["p"] = Job(id="p", url="u", title="t",
                        status=JobStatus.DONE, file_path="/tmp/whatever")
    monkeypatch.setattr("models_store.get_active_path", lambda: None)
    r = c.post("/api/v1/jobs/p/transcribe")
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_active_model"


def test_start_transcribe_idempotent_on_existing(client, monkeypatch, tmp_path):
    app, c = client
    jm = app.extensions["trove.jobs"]
    tm = app.extensions["trove.transcribe"]
    media = tmp_path / "m.mp4"
    media.write_bytes(b"x")
    jm._jobs["p"] = Job(id="p", url="u", title="t",
                        status=JobStatus.DONE, file_path=str(media))
    monkeypatch.setattr("models_store.get_active_path",
                        lambda: tmp_path / "model.bin")
    # Existing in-flight transcribe → return same id, don't spawn.
    existing = transcribe_jobs.TranscribeJob(
        id="t1", parent_job_id="p", model_used="m",
        status=transcribe_jobs.TranscribeStatus.RUNNING,
    )
    tm._jobs["t1"] = existing
    called = {"n": 0}
    app.extensions["trove.actions"]["start_transcribe"] = (
        lambda pid: (called.update(n=called["n"] + 1) or "should_not_use")
    )
    r = c.post("/api/v1/jobs/p/transcribe")
    assert r.status_code == 200
    assert r.get_json()["id"] == "t1"
    assert called["n"] == 0  # idempotent


# ---- models ---------------------------------------------------------

def test_list_models_shape(client):
    _, c = client
    r = c.get("/api/v1/models")
    assert r.status_code == 200
    body = r.get_json()
    assert "active" in body
    assert isinstance(body["models"], list)
    assert all({"name", "label", "is_installed", "is_active"}.issubset(m.keys())
               for m in body["models"])


def test_use_model_unknown_400(client):
    _, c = client
    r = c.post("/api/v1/models/bogus/use")
    assert r.status_code == 400


def test_use_model_not_installed_409(client, monkeypatch, tmp_path):
    _, c = client
    monkeypatch.setattr("models_store.MODELS_DIR", tmp_path)
    r = c.post("/api/v1/models/ggml-tiny.bin/use")
    assert r.status_code == 409
    assert r.get_json()["error"] == "not_installed"


def test_install_progress_endpoint(client):
    _, c = client
    r = c.get("/api/v1/models/install-progress")
    assert r.status_code == 200
    body = r.get_json()
    assert "downloading" in body


# ---- progress / human fields ---------------------------------------

def test_job_view_includes_human_progress(client, monkeypatch):
    """The MCP / CLI clients rely on a ``human`` block + computed
    ``progress_pct`` / ``elapsed_seconds`` so they can give a useful
    live status without re-implementing formatting on every poll."""
    app, c = client
    jm = app.extensions["trove.jobs"]
    from jobs import Job
    job = Job(
        id="hview1", url="https://example.com/v", title="Big sample",
        status=JobStatus.DOWNLOADING,
        downloaded_bytes=12_400_000, total_bytes=29_700_000,
        speed=5_200_000.0, eta=3,
    )
    with jm._lock:
        jm._jobs["hview1"] = job

    r = c.get(f"/api/v1/jobs/{job.id}")
    assert r.status_code == 200
    body = r.get_json()
    # Raw machine-readable fields
    assert body["progress_pct"] == 41
    assert body["elapsed_seconds"] >= 0
    assert body["speed_bps"] == 5_200_000.0
    # Human-readable block
    h = body["human"]
    assert h["progress"] == "41%"
    assert h["downloaded"] == "11.8 MB"  # 12.4M binary
    assert h["size"] == "28.3 MB"        # 29.7M binary
    assert h["speed"] == "5.0 MB/s"
    assert h["eta"] == "0:03"
    assert "downloading" in h["summary"]
    assert "41%" in h["summary"]
    assert "5.0 MB/s" in h["summary"]


def test_transcript_view_includes_human_progress(client):
    app, c = client
    tm = app.extensions["trove.transcribe"]
    tj = transcribe_jobs.TranscribeJob(
        id="t1", parent_job_id="p1", model_used="ggml-tiny.bin",
        progress_pct=42, duration_seconds=552.0, language_detected="en",
        status=transcribe_jobs.TranscribeStatus.RUNNING,
    )
    with tm._lock:
        tm._jobs["t1"] = tj
    r = c.get("/api/v1/transcripts/t1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["progress_pct"] == 42
    assert body["duration_seconds"] == 552.0
    assert body["elapsed_seconds"] >= 0
    h = body["human"]
    assert h["progress"] == "42%"
    assert h["audio_duration"] == "9:12"
    assert "running" in h["summary"]
    assert "42%" in h["summary"]
    assert "ggml-tiny.bin" in h["summary"]


# ---- rate-limit exemption scope ------------------------------------

def _swap_rate_limiter(app, rate=2, window=60):
    """Replace the live rate limiter so we can test the rate-limit
    branch deterministically without reaching for module-level env
    state (RATE_LIMIT_PER_MIN is read at import time)."""
    from safety import RateLimiter
    new = RateLimiter(rate=rate, per_seconds=window)
    # The /before_request closure reads `rate_limiter` from the
    # enclosing scope, but it's also stashed on app.extensions for
    # exactly this purpose. Patch both surfaces.
    app.extensions["trove.rate_limiter"] = new
    # Patch the closure's free var via the function object.
    for fn in app.before_request_funcs.get(None, []):
        if fn.__name__ == "_rate_limit":
            cells = fn.__closure__ or ()
            names = fn.__code__.co_freevars
            for name, cell in zip(names, cells):
                if name == "rate_limiter":
                    cell.cell_contents = new
                    return
    raise RuntimeError("could not find _rate_limit closure to patch")


def test_rate_limit_exempts_status_polls(client):
    app, c = client
    _swap_rate_limiter(app, rate=2)
    # 50 status polls in a row must all succeed (poll exemption).
    for _ in range(50):
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/api/v1/jobs").status_code == 200
        assert c.get("/api/v1/jobs/no-such-id").status_code == 404
        assert c.get("/api/v1/transcripts").status_code == 200


def test_rate_limit_does_not_exempt_file_or_export(client):
    """Bandwidth-heavy GETs must stay rate-limited so a token-less
    deployment isn't a free egress vector. The exemption helper has
    a regression-prone history (see _is_poll_exempt comments)."""
    app, c = client
    _swap_rate_limiter(app, rate=2)
    seen = [c.get("/api/v1/jobs/x/file").status_code for _ in range(5)]
    assert 429 in seen, f"file GET should hit rate limit; got {seen}"
    _swap_rate_limiter(app, rate=2)  # fresh bucket
    seen = [c.get("/api/v1/transcripts/x/export.txt").status_code for _ in range(5)]
    assert 429 in seen, f"export GET should hit rate limit; got {seen}"


# ---- auth boundary --------------------------------------------------

def test_token_required_when_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_TOKEN", "secret-xyz")
    app = create_app()
    c = app.test_client()
    # /health is open
    assert c.get("/api/v1/health").status_code == 200
    # /jobs requires the token
    assert c.get("/api/v1/jobs").status_code in (401, 403)
    # With the right token it works
    r = c.get("/api/v1/jobs", headers={"Authorization": "Bearer secret-xyz"})
    assert r.status_code == 200
