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
    body = r.data.decode()
    assert 'data-status="error"' in body
    assert 'data-category="unsupported_url"' in body
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


def test_index_renders_with_deck_assets(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode()
    assert 'css/deck.css' in body
    assert 'vendor/gsap.min.js' in body
    assert 'js/deck.js' in body
    assert 'id="deck"' in body
    # Footer attribution must be gone.
    assert 'averygan/reclip' not in body


def test_card_partial_emits_data_attributes(client, monkeypatch):
    import json as _json
    fake_stdout = _json.dumps({
        "title": "T", "thumbnail": "https://x/y.jpg", "duration": 30,
        "uploader": "U",
        "formats": [{"format_id": "137", "height": 1080, "vcodec": "avc1", "tbr": 5000}],
    })

    class FakeCompleted:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())
    r = client.post("/api/info-card", data={"url": "https://www.youtube.com/watch?v=abc"})
    assert r.status_code == 200
    body = r.data.decode()
    assert 'data-status="ready"' in body
    assert 'data-title="T"' in body
    assert 'data-uploader="U"' in body
    assert 'data-formats=' in body
