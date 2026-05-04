"""End-to-end pipeline tests for the transcribe worker closure
(``_build_transcribe_target`` in app.py).

These tests don't install the heavy diarization deps. They drive the
full closure with mocked ``extract_audio``, ``run_transcribe``, and
``diarizer`` modules to assert the integration:

  - happy path: extract → transcribe → diarize → write_artifacts
  - TROVE_DIARIZATION=off: extract → transcribe → write_artifacts (no diarize)
  - diarize raises: still writes artifacts; speakers all None
  - cancel before transcribe: no artifacts written
  - diarize returns chunks: speakers land in segments[i].speaker

The goal is to lock in the contract so future refactors of either the
diarizer or the worker can't silently regress speaker labels.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

import app as app_mod
import models_store
import transcribe_jobs
import transcriber


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _Chunk:
    start: float
    end: float
    speaker: str


def _flask_app(tmp_path, monkeypatch):
    """Spin up the Flask app pointed at a temp downloads dir. Returns
    (app, transcribe_manager, downloads_dir)."""
    # Defensive: prior tests in the suite may have set TROVE_TOKEN directly
    # via os.environ (test_safety.py does this). Without this cleanup, every
    # POST below 401s.
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setattr(app_mod, "DOWNLOAD_DIR", tmp_path)
    a = app_mod.create_app()
    return a, a.extensions["trove.transcribe"], tmp_path


def _media_job(job_manager, downloads_dir, *, ext=".mp4"):
    """Submit a fake parent media job whose file_path points at a touched file."""
    media = downloads_dir / f"src{ext}"
    media.write_bytes(b"fake-media")

    def _noop(j):
        j.file_path = str(media)
        j.filename = f"src{ext}"

    jid = job_manager.submit(target=_noop, title="t", url="https://x")
    # Drain the worker so the job lands at DONE
    while True:
        j = job_manager.get(jid)
        if j.status.value in ("done", "error", "cancelled"):
            break
    j = job_manager.get(jid)
    assert j.status.value == "done", f"setup expected DONE, got {j.status.value}"
    return j


def _stub_transcribe(monkeypatch, words):
    """Make transcriber.run_transcribe return a TranscriptResult with
    these words (auto-grouped by the existing pause rule). Also short-
    circuit extract_audio so no real ffmpeg runs."""
    def _fake_extract(src, dst, *, cancel_check=None, register_proc=None, timeout=None):
        # Just touch the destination; the worker checks for existence.
        Path(dst).write_bytes(b"FAKEWAV")
    monkeypatch.setattr(transcriber, "extract_audio", _fake_extract)

    # Build segments from words using the same gap rule as run_transcribe
    segs = []
    if words:
        cur = [words[0]]
        for w in words[1:]:
            if w["start"] - cur[-1]["end"] > 1.0:
                segs.append({
                    "start": cur[0]["start"],
                    "end": cur[-1]["end"],
                    "text": " ".join(x["w"] for x in cur),
                    "words": cur,
                    "speaker": None,
                })
                cur = [w]
            else:
                cur.append(w)
        segs.append({
            "start": cur[0]["start"],
            "end": cur[-1]["end"],
            "text": " ".join(x["w"] for x in cur),
            "words": cur,
            "speaker": None,
        })

    def _fake_run(*, audio_path, model_path, progress_cb=None, cancel_check=None):
        if progress_cb:
            progress_cb(100)
        return transcriber.TranscriptResult(
            language="en",
            duration=words[-1]["end"] if words else 0.0,
            segments=segs,
            words=words,
            error=None,
        )
    monkeypatch.setattr(transcriber, "run_transcribe", _fake_run)


def _wait(transcribe_manager, tjid, timeout=10.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tj = transcribe_manager.get(tjid)
        if tj is None:
            raise RuntimeError("transcribe job vanished")
        if tj.status in (transcribe_jobs.TranscribeStatus.DONE,
                         transcribe_jobs.TranscribeStatus.ERROR,
                         transcribe_jobs.TranscribeStatus.CANCELLED):
            return tj
        time.sleep(0.05)
    raise RuntimeError(f"transcribe didn't finish in {timeout}s")


# ---------------------------------------------------------------------------
# Happy path: with diarization stub returning chunks → speakers populated
# ---------------------------------------------------------------------------

def test_pipeline_with_diarization_stub_writes_speakers(tmp_path, monkeypatch):
    a, tm, dl = _flask_app(tmp_path, monkeypatch)
    jm = a.extensions["trove.jobs"]
    parent = _media_job(jm, dl)

    words = [
        {"w": "hello", "start": 0.0, "end": 0.5},
        {"w": "world", "start": 0.6, "end": 1.0},
    ]
    _stub_transcribe(monkeypatch, words)

    # Stub the diarizer module that the worker imports lazily.
    import diarizer
    monkeypatch.setattr(diarizer, "available", lambda: True)
    # The worker now calls _vad_speech_chunks before diarize() to realign
    # word timestamps against speech boundaries — stub both.
    monkeypatch.setattr(diarizer, "_vad_speech_chunks",
                        lambda _p: [{"start": 0.0, "end": 1.0}])
    monkeypatch.setattr(diarizer, "diarize", lambda *, audio_path: [
        _Chunk(0.0, 0.5, "Speaker 1"),
        _Chunk(0.5, 1.0, "Speaker 2"),
    ])

    base_no_ext = os.path.splitext(parent.file_path)[0]
    wav_path = base_no_ext + ".wav"

    target = None
    # Pull the closure out of create_app's scope by calling the start endpoint
    # via the test client.
    with a.test_client() as c:
        # Need an active model — fake it
        monkeypatch.setattr(models_store, "get_active_path", lambda: tmp_path / "fake.bin")
        rv = c.post(f"/api/transcribe/{parent.id}/start")
        assert rv.status_code == 200, rv.data

    # Find the transcribe job that was created
    tjs = [t for t in tm.snapshot_jobs() if t.parent_job_id == parent.id]
    assert len(tjs) == 1
    tj = _wait(tm, tjs[0].id)
    assert tj.status == transcribe_jobs.TranscribeStatus.DONE, \
        f"expected DONE, got {tj.status} ({tj.error_category}: {tj.error_message})"

    # Diarization outcome must be surfaced on the TranscribeJob
    assert tj.diarization_status == "complete"
    assert tj.diarization_error is None
    assert tj.speaker_count == 2

    # Verify .words.json has speakers
    payload = json.loads(Path(base_no_ext + ".words.json").read_text())
    assert payload["schema_version"] == 2
    speakers = {s.get("speaker") for s in payload["segments"]}
    assert "Speaker 1" in speakers
    assert "Speaker 2" in speakers

    # WAV must be cleaned up
    assert not Path(wav_path).exists(), "temp wav must be removed"


# ---------------------------------------------------------------------------
# Diarization OFF: no chunks called, speakers all None
# ---------------------------------------------------------------------------

def test_pipeline_diarization_off_skips_diarize(tmp_path, monkeypatch):
    a, tm, dl = _flask_app(tmp_path, monkeypatch)
    jm = a.extensions["trove.jobs"]
    parent = _media_job(jm, dl)

    _stub_transcribe(monkeypatch, [
        {"w": "hi", "start": 0.0, "end": 0.5},
    ])

    diarize_called = []
    import diarizer
    monkeypatch.setattr(diarizer, "available", lambda: False)
    monkeypatch.setattr(diarizer, "diarize",
                         lambda *, audio_path: diarize_called.append(audio_path) or [])

    monkeypatch.setattr(models_store, "get_active_path", lambda: tmp_path / "fake.bin")

    with a.test_client() as c:
        rv = c.post(f"/api/transcribe/{parent.id}/start")
        assert rv.status_code == 200

    tjs = [t for t in tm.snapshot_jobs() if t.parent_job_id == parent.id]
    tj = _wait(tm, tjs[0].id)
    assert tj.status == transcribe_jobs.TranscribeStatus.DONE

    assert diarize_called == [], "diarize must not run when available()=False"
    # Feature off → diarization_status stays None (not attempted),
    # not "skipped" or "failed" (those reserve specific meanings).
    assert tj.diarization_status is None
    assert tj.diarization_error is None
    assert tj.speaker_count is None

    base = os.path.splitext(parent.file_path)[0]
    payload = json.loads(Path(base + ".words.json").read_text())
    assert all(s.get("speaker") is None for s in payload["segments"])


# ---------------------------------------------------------------------------
# Diarize raises: must NOT kill the transcribe
# ---------------------------------------------------------------------------

def test_pipeline_diarize_failure_doesnt_kill_transcribe(tmp_path, monkeypatch):
    a, tm, dl = _flask_app(tmp_path, monkeypatch)
    jm = a.extensions["trove.jobs"]
    parent = _media_job(jm, dl)

    _stub_transcribe(monkeypatch, [
        {"w": "hi", "start": 0.0, "end": 0.5},
    ])

    import diarizer
    monkeypatch.setattr(diarizer, "available", lambda: True)
    monkeypatch.setattr(diarizer, "_vad_speech_chunks",
                        lambda _p: [{"start": 0.0, "end": 1.0}])
    def _explode(*, audio_path):
        raise RuntimeError("boom")
    monkeypatch.setattr(diarizer, "diarize", _explode)

    monkeypatch.setattr(models_store, "get_active_path", lambda: tmp_path / "fake.bin")

    with a.test_client() as c:
        rv = c.post(f"/api/transcribe/{parent.id}/start")
        assert rv.status_code == 200

    tjs = [t for t in tm.snapshot_jobs() if t.parent_job_id == parent.id]
    tj = _wait(tm, tjs[0].id)
    assert tj.status == transcribe_jobs.TranscribeStatus.DONE, \
        "diarize failure must NOT promote to ERROR"

    # The transcribe still completes, but the diarization failure is
    # surfaced on the TranscribeJob — not silently swallowed.
    assert tj.diarization_status == "failed"
    assert "boom" in (tj.diarization_error or "")
    assert tj.speaker_count is None

    base = os.path.splitext(parent.file_path)[0]
    payload = json.loads(Path(base + ".words.json").read_text())
    assert all(s.get("speaker") is None for s in payload["segments"])
    # Artifacts still produced
    assert Path(base + ".txt").exists()
    assert Path(base + ".srt").exists()
    assert Path(base + ".vtt").exists()


# ---------------------------------------------------------------------------
# Diarize returns empty (no speech detected) — speakers stay None, no error
# ---------------------------------------------------------------------------

def test_pipeline_diarize_empty_chunks_keeps_speakers_none(tmp_path, monkeypatch):
    a, tm, dl = _flask_app(tmp_path, monkeypatch)
    jm = a.extensions["trove.jobs"]
    parent = _media_job(jm, dl)

    _stub_transcribe(monkeypatch, [
        {"w": "hi", "start": 0.0, "end": 0.5},
    ])

    import diarizer
    monkeypatch.setattr(diarizer, "available", lambda: True)
    # Empty VAD too — matches the "no speech" outcome end-to-end.
    monkeypatch.setattr(diarizer, "_vad_speech_chunks", lambda _p: [])
    monkeypatch.setattr(diarizer, "diarize", lambda *, audio_path: [])  # no speech detected

    monkeypatch.setattr(models_store, "get_active_path", lambda: tmp_path / "fake.bin")

    with a.test_client() as c:
        rv = c.post(f"/api/transcribe/{parent.id}/start")
        assert rv.status_code == 200

    tjs = [t for t in tm.snapshot_jobs() if t.parent_job_id == parent.id]
    tj = _wait(tm, tjs[0].id)
    assert tj.status == transcribe_jobs.TranscribeStatus.DONE
    # Diarizer ran cleanly but found no speech — distinct from "failed".
    assert tj.diarization_status == "empty"
    assert tj.diarization_error is None
    assert tj.speaker_count == 0


# ---------------------------------------------------------------------------
# Cancel mid-flight: no artifacts written
# ---------------------------------------------------------------------------

def test_pipeline_cancel_before_transcribe_writes_no_artifacts(tmp_path, monkeypatch):
    a, tm, dl = _flask_app(tmp_path, monkeypatch)
    jm = a.extensions["trove.jobs"]
    parent = _media_job(jm, dl)

    # extract_audio: simulate the cancelled-mid-extract path
    def _fake_extract(src, dst, *, cancel_check=None, register_proc=None, timeout=None):
        raise RuntimeError("cancelled")
    monkeypatch.setattr(transcriber, "extract_audio", _fake_extract)

    monkeypatch.setattr(models_store, "get_active_path", lambda: tmp_path / "fake.bin")

    with a.test_client() as c:
        rv = c.post(f"/api/transcribe/{parent.id}/start")
        assert rv.status_code == 200

    tjs = [t for t in tm.snapshot_jobs() if t.parent_job_id == parent.id]
    tj = _wait(tm, tjs[0].id)

    base = os.path.splitext(parent.file_path)[0]
    # Critical: a cancelled transcribe must NOT have left artifacts behind
    assert not Path(base + ".words.json").exists(), \
        "cancelled extract must not write a .words.json"
    assert not Path(base + ".txt").exists()


# ---------------------------------------------------------------------------
# Idempotent: clicking start twice doesn't double-submit a transcribe
# ---------------------------------------------------------------------------

def test_pipeline_double_start_is_idempotent(tmp_path, monkeypatch):
    """Two POSTs to /api/transcribe/<id>/start (rapid double-click) must
    not produce two parallel transcribe jobs writing the same WAV."""
    a, tm, dl = _flask_app(tmp_path, monkeypatch)
    jm = a.extensions["trove.jobs"]
    parent = _media_job(jm, dl)

    # Slow extract so the first transcribe is still running when we POST again
    import threading
    block = threading.Event()
    def _slow_extract(src, dst, *, cancel_check=None, register_proc=None, timeout=None):
        block.wait(timeout=5)
        Path(dst).write_bytes(b"FAKEWAV")
    monkeypatch.setattr(transcriber, "extract_audio", _slow_extract)

    _stub_transcribe(monkeypatch, [{"w": "x", "start": 0.0, "end": 0.5}])
    monkeypatch.setattr(models_store, "get_active_path", lambda: tmp_path / "fake.bin")

    with a.test_client() as c:
        r1 = c.post(f"/api/transcribe/{parent.id}/start")
        r2 = c.post(f"/api/transcribe/{parent.id}/start")
        assert r1.status_code == 200 and r2.status_code == 200

    # Only one transcribe job should exist for this parent
    tjs = [t for t in tm.snapshot_jobs() if t.parent_job_id == parent.id]
    assert len(tjs) == 1, f"expected 1 transcribe job, got {len(tjs)}"

    # Let it finish
    block.set()
    _wait(tm, tjs[0].id)
