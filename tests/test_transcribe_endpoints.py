import pytest
from app import create_app


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
