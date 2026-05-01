import pytest
from app import create_app
import time as _time


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    import models_store
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
