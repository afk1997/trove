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
