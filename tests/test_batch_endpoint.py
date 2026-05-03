"""Tests for the multi-URL paste / auto-transcribe flow (Task #5).

We patch ``runner.run_info`` and ``runner.run_download`` so the batch
endpoint returns deterministic title/thumbnail and the download worker
"completes" instantly without spawning yt-dlp. The auto-transcribe
trigger is exercised by inspecting ``transcribe_manager`` after each
download settles.
"""
from __future__ import annotations
import time
import pytest
from app import create_app
from runner import InfoResult, DownloadResult


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


def _stub_info(title="t", thumbnail="thumb.jpg"):
    def _impl(url, *, timeout=60):
        return InfoResult(title=title, thumbnail=thumbnail, duration=10, uploader="u", formats=[])
    return _impl


def _stub_download(out_dir):
    """Stub run_download: write a tiny mp4 file and return success."""
    def _impl(*, url, out_template, format_choice, format_id, progress_cb,
             register_process, was_paused_check):
        # out_template is "<dir>/<job_id>.%(ext)s"
        path = out_template.replace("%(ext)s", "mp4")
        with open(path, "wb") as f:
            f.write(b"\x00" * 8)
        return DownloadResult(file_path=path)
    return _impl


def _wait_for(predicate, timeout=3.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_batch_endpoint_rejects_empty_input(client):
    r = client.post("/api/batch-download", data={"urls": "   \n  "})
    assert r.status_code == 400
    assert b"not supported" in r.data.lower() or b"unsupported" in r.data.lower()


def test_batch_endpoint_enqueues_each_url(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.run_info", _stub_info())
    monkeypatch.setattr("app.run_download", _stub_download(tmp_path))
    raw = "https://example.com/a\nhttps://example.com/b, https://example.com/c"
    r = client.post("/api/batch-download", data={
        "urls": raw,
        "format": "video",
    })
    assert r.status_code == 200
    body = r.data.decode()
    # Three cards rendered (downloading or done — the stub completes fast).
    assert body.count('class="clip') >= 3
    jm = client.application.extensions["trove.jobs"]
    assert _wait_for(
        lambda: sum(1 for j in jm.snapshot_jobs() if j.file_path) == 3
    ), "expected 3 jobs to settle"


def test_batch_endpoint_renders_error_card_for_unsafe_urls(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.run_info", _stub_info())
    monkeypatch.setattr("app.run_download", _stub_download(tmp_path))
    # First URL is private (link-local IP) -> error card; second is OK.
    raw = "http://127.0.0.1/x\nhttps://example.com/ok"
    r = client.post("/api/batch-download", data={"urls": raw, "format": "video"})
    assert r.status_code == 200
    body = r.data.decode()
    assert "is-error" in body
    assert "is-downloading" in body or "is-done" in body


def test_batch_endpoint_skips_auto_transcribe_when_no_active_model(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.run_info", _stub_info())
    monkeypatch.setattr("app.run_download", _stub_download(tmp_path))
    r = client.post("/api/batch-download", data={
        "urls": "https://example.com/a",
        "format": "video",
        "auto_transcribe": "on",
    })
    assert r.status_code == 200
    jm = client.application.extensions["trove.jobs"]
    tm = client.application.extensions["trove.transcribe"]
    assert _wait_for(lambda: any(j.file_path for j in jm.snapshot_jobs()))
    # No transcribe submitted because no active model is installed.
    assert tm.snapshot_jobs() == []
    # The DONE card should carry the no-active-model hint.
    job = jm.snapshot_jobs()[0]
    r2 = client.get(f"/api/status-card/{job.id}")
    assert b"auto-transcribe skipped" in r2.data


def test_batch_endpoint_triggers_auto_transcribe_with_active_model(
    client, monkeypatch, tmp_path,
):
    monkeypatch.setattr("app.run_info", _stub_info())
    monkeypatch.setattr("app.run_download", _stub_download(tmp_path))
    # Install a fake active model so models_store.get_active_path returns it.
    import models_store
    models_store.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    fake = models_store.MODELS_DIR / "ggml-tiny.bin"
    fake.write_bytes(b"x")
    (models_store.MODELS_DIR / "ACTIVE").write_text("ggml-tiny.bin\n")

    # Stub the transcribe pipeline so we don't shell out to ffmpeg/whisper.
    import transcriber
    monkeypatch.setattr(transcriber, "extract_audio",
                        lambda *a, **kw: None)
    class _R:
        error = None
        duration = 1.0
        language = "en"
    monkeypatch.setattr(transcriber, "run_transcribe",
                        lambda **kw: _R())
    monkeypatch.setattr(transcriber, "write_artifacts",
                        lambda result, base: None)

    r = client.post("/api/batch-download", data={
        "urls": "https://example.com/a",
        "format": "video",
        "auto_transcribe": "on",
    })
    assert r.status_code == 200
    tm = client.application.extensions["trove.transcribe"]
    assert _wait_for(lambda: len(tm.snapshot_jobs()) == 1, timeout=4.0), \
        "expected auto-transcribe to be submitted"


def test_auto_transcribe_skipped_on_cancel_race(client, monkeypatch, tmp_path):
    """If the user cancels mid-download but the runner's success races past
    the kill, _try_auto_transcribe MUST NOT fire. Regression for the cancel-
    race surfaced in code review."""
    monkeypatch.setattr("app.run_info", _stub_info())

    # Stub the download to flip the job to CANCELLED right before returning
    # success — emulates the race where the cancel landed too late to stop
    # the runner but before the worker observed the kill.
    def _racing_download(*, url, out_template, format_choice, format_id,
                        progress_cb, register_process, was_paused_check):
        from jobs import JobStatus
        path = out_template.replace("%(ext)s", "mp4")
        with open(path, "wb") as f:
            f.write(b"\x00" * 8)
        # Simulate the cancel arriving here, after the file was written.
        jm = client.application.extensions["trove.jobs"]
        for j in jm.snapshot_jobs():
            if j.url == url:
                j.status = JobStatus.CANCELLED
        return DownloadResult(file_path=path)

    monkeypatch.setattr("app.run_download", _racing_download)

    # Install a fake active model so the only thing blocking auto-transcribe
    # is the cancel guard itself.
    import models_store
    models_store.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (models_store.MODELS_DIR / "ggml-tiny.bin").write_bytes(b"x")
    (models_store.MODELS_DIR / "ACTIVE").write_text("ggml-tiny.bin\n")

    r = client.post("/api/batch-download", data={
        "urls": "https://example.com/cancelme",
        "format": "video",
        "auto_transcribe": "on",
    })
    assert r.status_code == 200
    tm = client.application.extensions["trove.transcribe"]
    # Give the worker a moment to (incorrectly) submit the transcribe.
    time.sleep(0.2)
    assert tm.snapshot_jobs() == [], \
        "auto-transcribe must not fire when the parent download was cancelled"


def test_batch_endpoint_rejects_oversized_paste(client, monkeypatch):
    """Pasting more than BATCH_MAX_URLS must return 413 with a friendly
    too_many_urls error card and never call run_info / run_download.
    Defense-in-depth against accidental or malicious huge pastes."""
    import app as _app
    calls = {"info": 0, "download": 0}

    def _spy_info(url, *, timeout=60):
        calls["info"] += 1
        return InfoResult(title="t", thumbnail="", duration=0, uploader="", formats=[])

    def _spy_download(**kwargs):
        calls["download"] += 1
        return DownloadResult(file_path="")

    monkeypatch.setattr(_app, "run_info", _spy_info)
    monkeypatch.setattr(_app, "run_download", _spy_download)
    monkeypatch.setattr(_app, "BATCH_MAX_URLS", 5)

    raw = ",".join(f"https://example.com/v{i}" for i in range(20))
    r = client.post("/api/batch-download", data={"urls": raw, "format": "video"})
    assert r.status_code == 413
    body = r.data.decode()
    assert "too many urls" in body.lower()
    assert "20" in body and "5" in body  # count and max surfaced
    assert calls["info"] == 0
    assert calls["download"] == 0


def test_batch_endpoint_accepts_paste_at_cap(client, monkeypatch, tmp_path):
    """Exactly BATCH_MAX_URLS should still be accepted (off-by-one guard)."""
    import app as _app
    monkeypatch.setattr(_app, "run_info", _stub_info())
    monkeypatch.setattr(_app, "run_download", _stub_download(tmp_path))
    monkeypatch.setattr(_app, "BATCH_MAX_URLS", 3)
    raw = "\n".join(f"https://example.com/v{i}" for i in range(3))
    r = client.post("/api/batch-download", data={"urls": raw, "format": "video"})
    assert r.status_code == 200
    assert r.data.decode().count('class="clip') >= 3


def test_single_url_through_info_card_carries_auto_transcribe_flag(
    client, monkeypatch, tmp_path,
):
    """Single-URL flow: checkbox state must round-trip via the ready card."""
    monkeypatch.setattr("app.run_info", _stub_info(title="hello"))
    r = client.post("/api/info-card", data={
        "url": "https://example.com/x",
        "format": "video",
        "auto_transcribe": "on",
    })
    assert r.status_code == 200
    # The ready card should embed the auto_transcribe hidden input so the
    # eventual /api/download-card POST preserves the user's choice.
    assert b'name="auto_transcribe"' in r.data
