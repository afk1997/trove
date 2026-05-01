import os
import pathlib
import subprocess
import pytest
from app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    app = create_app()
    return app.test_client()


def test_argument_injection_url_rejected_json(client, monkeypatch):
    called = []
    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: called.append(a) or _ok(""))
    r = client.post("/api/info", json={"url": "--exec=touch /tmp/pwned"})
    assert r.status_code == 400
    assert called == []


def test_argument_injection_url_rejected_card(client, monkeypatch):
    called = []
    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: called.append(a) or _ok(""))
    r = client.post("/api/info-card", data={"url": "--exec=touch /tmp/pwned"})
    assert r.status_code == 400
    assert b"not supported" in r.data.lower() or b"unsupported" in r.data.lower()
    assert called == []


def test_request_json_none_returns_400(client):
    r = client.post("/api/info", data="not json", content_type="text/plain")
    assert r.status_code == 400


def test_token_required_blocks_when_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    app = create_app()
    client = app.test_client()
    assert client.post("/api/info", json={"url": "https://www.youtube.com/"}).status_code == 401
    r = client.post(
        "/api/info",
        json={"url": "https://www.youtube.com/"},
        headers={"Authorization": "Bearer secret"},
    )
    # Will hit network; we accept any non-401 (200 or 400).
    assert r.status_code != 401


def test_csp_no_unsafe_inline_script(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    script = csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script
    assert "'nonce-" in script


# ----- helpers ---------------------------------------------------------------


class _Completed:
    def __init__(self, stderr=""):
        self.returncode = 1 if stderr else 0
        self.stdout = ""
        self.stderr = stderr


def _ok(stderr=""):
    return _Completed(stderr=stderr)


def test_pause_endpoint_returns_card_html(client):
    import time as _time
    jm = client.application.extensions["trove.jobs"]
    jid = jm.submit(
        target=lambda j: _time.sleep(2),
        title="Test", url="https://example.com/v",
    )
    res = client.post(f"/api/job/{jid}/pause")
    assert res.status_code == 200
    body = res.data.decode()
    # card.html paused branch not yet added (Task 11), so just verify body is not empty
    assert body.strip()


def test_pause_endpoint_404_unknown(client):
    res = client.post("/api/job/unknownid12/pause")
    assert res.status_code == 404


def test_resume_endpoint_returns_card_html(client):
    from jobs import Job, JobStatus
    jm = client.application.extensions["trove.jobs"]
    j = Job(
        id="pausedjob1", url="https://example.com/v", title="Test",
        status=JobStatus.PAUSED,
        format_choice="video", format_id=None,
        out_template="/tmp/test.%(ext)s",
    )
    with jm._lock:
        jm._jobs["pausedjob1"] = j
    res = client.post("/api/job/pausedjob1/resume")
    assert res.status_code == 200
    body = res.data.decode()
    assert body.strip()  # rendered card (specific class checks once template is updated in T11)


def test_resume_endpoint_404_unknown(client):
    res = client.post("/api/job/unknownid12/resume")
    assert res.status_code == 404


def test_index_renders_persisted_paused_jobs(client):
    """A persisted PAUSED job should appear in the queue on GET /."""
    from jobs import Job, JobStatus
    jm = client.application.extensions["trove.jobs"]
    j = Job(
        id="persisted1", url="https://example.com/v", title="Persisted Title",
        status=JobStatus.PAUSED,
        format_choice="video", format_id=None,
        out_template="/tmp/persisted.%(ext)s",
        downloaded_bytes=5 * 1048576, total_bytes=10 * 1048576,
    )
    with jm._lock:
        jm._jobs["persisted1"] = j

    res = client.get("/")
    assert res.status_code == 200
    body = res.data.decode()
    assert 'data-job-id="persisted1"' in body
    assert "is-paused" in body
    assert "Persisted Title" in body
    assert "▶</span> resume" in body  # decorative glyph wrapped per a11y


def test_dismiss_endpoint_returns_empty_200(client):
    """POST /api/job/<id>/dismiss on a DONE job returns empty 200; the job
    is then unknown to subsequent requests.
    """
    from jobs import Job, JobStatus
    jm = client.application.extensions["trove.jobs"]
    with jm._lock:
        jm._jobs["dismissme"] = Job(
            id="dismissme", url="https://e.com", title="Done",
            status=JobStatus.DONE, file_path=None, filename="x.mp4",
        )

    res = client.post("/api/job/dismissme/dismiss")
    assert res.status_code == 200
    assert res.data == b""
    assert client.get("/api/status-card/dismissme").status_code == 404


def test_dismiss_endpoint_404_for_unknown_id(client):
    res = client.post("/api/job/unknownid12/dismiss")
    assert res.status_code == 404


def test_dismiss_endpoint_404_for_running_job(client):
    """Dismiss on a non-terminal job (DOWNLOADING) refuses with 404."""
    from jobs import Job, JobStatus
    jm = client.application.extensions["trove.jobs"]
    with jm._lock:
        jm._jobs["livejob1"] = Job(
            id="livejob1", url="https://e.com", title="Live",
            status=JobStatus.DOWNLOADING,
        )
    res = client.post("/api/job/livejob1/dismiss")
    assert res.status_code == 404
    # Job still present
    with jm._lock:
        assert "livejob1" in jm._jobs


def test_index_persisted_done_cards_marked_already_downloaded(client):
    """Persisted DONE cards must carry data-auto-downloaded so the JS auto-
    downloader doesn't re-trigger every saved file on next htmx swap.
    """
    from jobs import Job, JobStatus
    jm = client.application.extensions["trove.jobs"]
    with jm._lock:
        jm._jobs["donejob1"] = Job(
            id="donejob1", url="https://e.com", title="Done Already",
            status=JobStatus.DONE, file_path="/tmp/x.mp4", filename="x.mp4",
        )
    body = client.get("/").data.decode()
    assert "is-done" in body
    assert 'data-auto-downloaded="1"' in body
    # Sanity: a freshly-completed download via htmx swap (status-card path)
    # must NOT carry the marker — the JS attaches it on first auto-click.
    fresh = client.get("/api/status-card/donejob1").data.decode()
    assert "is-done" in fresh
    assert 'data-auto-downloaded' not in fresh
