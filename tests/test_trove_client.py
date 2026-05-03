"""Tests for ``trove_client.TroveClient``.

Two layers of coverage:

1. Pure-unit tests that monkeypatch ``urllib.request.urlopen`` so we
   can assert the client builds the right URL / headers / body without
   touching the network.

2. One end-to-end integration test that spins up the real Flask app
   on a random port via ``wsgiref.simple_server`` in a daemon thread
   and exercises the v1 surface through the client. Mirrors the audit
   recommendation: "tests -> TroveClient against Flask test server."

Stdlib-only on purpose (matches the no-deps property of the client).
"""
from __future__ import annotations

import io
import json
import os
import socket
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from trove_client import TroveClient, TroveError, _page_qs, _parse_sse


# ---------------------------------------------------------------------------
# Pure-unit tests (monkeypatched urlopen)
# ---------------------------------------------------------------------------

class _FakeResp:
    """Minimal stand-in for ``urlopen``'s context-manager response."""
    def __init__(self, status: int = 200, body: bytes = b"",
                 content_type: str = "application/json"):
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):  return self
    def __exit__(self, *a): return False
    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            data, self._body = self._body, b""
            return data
        data, self._body = self._body[:n], self._body[n:]
        return data


@pytest.fixture
def captured(monkeypatch):
    """Capture every ``urlopen`` call's request + return a canned body."""
    calls: list[dict] = []

    def fake_urlopen(req, timeout=None):
        calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(req.header_items()),
            "data": req.data,
            "timeout": timeout,
        })
        body = calls[-1].get("_resp_body", b'{"ok": true}')
        return _FakeResp(200, body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


def test_base_url_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://example.test:9000/")
    c = TroveClient()
    # Trailing slash trimmed, so concatenating ``+ "/api/v1/..."`` is safe.
    assert c.base_url == "http://example.test:9000"


def test_base_url_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://from-env")
    c = TroveClient(base_url="http://from-arg/")
    assert c.base_url == "http://from-arg"


def test_token_header_attached_when_set(captured, monkeypatch):
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().get("/api/v1/health")
    assert captured[0]["headers"]["Authorization"] == "Bearer hunter2"


def test_token_header_omitted_when_unset(captured, monkeypatch):
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().get("/api/v1/health")
    assert "Authorization" not in captured[0]["headers"]


def test_explicit_token_overrides_env(captured, monkeypatch):
    """An explicit ``token=`` arg must win over TROVE_TOKEN — both
    "use this token" and "explicitly no token" cases."""
    monkeypatch.setenv("TROVE_TOKEN", "from-env")
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient(token="from-arg").get("/api/v1/health")
    assert captured[0]["headers"]["Authorization"] == "Bearer from-arg"
    TroveClient(token="").get("/api/v1/health")
    assert "Authorization" not in captured[1]["headers"]


def test_post_sends_json_body(captured, monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().submit_download("https://y", fmt="audio",
                                  auto_transcribe=True, title="T")
    call = captured[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://x/api/v1/jobs"
    assert call["headers"]["Content-type"] == "application/json"
    assert json.loads(call["data"]) == {
        "url": "https://y", "format": "audio",
        "auto_transcribe": True, "title": "T",
    }


def test_bulk_download_serializes_url_list(captured, monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().bulk_download(("https://a", "https://b"),
                                fmt="video", auto_transcribe=False)
    call = captured[0]
    assert call["url"] == "http://x/api/v1/jobs/bulk"
    body = json.loads(call["data"])
    # ``urls`` must be a list (JSON has no tuples) so the wire shape
    # matches what /jobs/bulk validates.
    assert body["urls"] == ["https://a", "https://b"]


def test_list_jobs_default_path_omits_query(captured, monkeypatch):
    """Defaults that match server defaults must NOT appear in the URL —
    contract tests pin the canonical bare path."""
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().list_jobs()
    assert captured[0]["url"] == "http://x/api/v1/jobs"


def test_list_jobs_paginated_qs(captured, monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().list_jobs(status="done,error", limit=5,
                            offset=10, order="oldest")
    assert captured[0]["url"] == (
        "http://x/api/v1/jobs?status=done%2Cerror&limit=5&offset=10&order=oldest"
    )


def test_search_transcripts_url_encodes_query(captured, monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://x")
    TroveClient().search_transcripts("hello world & friends",
                                     limit=10, context=20)
    assert captured[0]["url"] == (
        "http://x/api/v1/transcripts/search"
        "?q=hello%20world%20%26%20friends&limit=10&context=20"
    )


def test_export_transcript_rejects_unknown_format(monkeypatch):
    monkeypatch.setenv("TROVE_URL", "http://x")
    with pytest.raises(ValueError):
        TroveClient().export_transcript("tid", "pdf")


def test_204_response_returns_none(monkeypatch):
    """Non-content responses (job actions like /pause /cancel) must
    yield ``None`` rather than blow up on JSON-decoding empty bytes."""
    monkeypatch.setenv("TROVE_URL", "http://x")
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _FakeResp(204, b"", "text/plain"))
    assert TroveClient().pause_job("j1") is None


def test_http_error_raises_trove_error_with_parsed_body(monkeypatch):
    """Server-side JSON error bodies must surface verbatim on the
    TroveError so the CLI can print ``trove: <msg> (HTTP <status>)``."""
    import urllib.error
    err_body = json.dumps({"error": "not_found"}).encode()

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", hdrs=None,
            fp=io.BytesIO(err_body),
        )

    monkeypatch.setenv("TROVE_URL", "http://x")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(TroveError) as exc:
        TroveClient().get_job("zzz")
    assert exc.value.status == 404
    assert exc.value.body == {"error": "not_found"}


def test_unreachable_server_raises_systemexit_with_hint(monkeypatch):
    """Network-level failures must bail with the ``trove serve`` hint
    so users aren't dumped a urllib stack trace."""
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setenv("TROVE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        TroveClient().get("/api/v1/health")
    assert "trove serve" in str(exc.value)


def test_export_transcript_stream_to_writes_file(monkeypatch, tmp_path):
    """``stream_to`` writes raw bytes to disk and returns a marker
    dict — the path the CLI's ``trove transcript -o`` relies on."""
    monkeypatch.setenv("TROVE_URL", "http://x")
    body = b"1\n00:00 --> 00:01\nhello\n"
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _FakeResp(200, body, "text/plain"))
    out = tmp_path / "ex.srt"
    res = TroveClient().export_transcript("tid", "srt", stream_to=str(out))
    assert res == {"saved_to": str(out)}
    assert out.read_bytes() == body


def test_page_qs_helper_canonical_shape():
    assert _page_qs() == ""
    assert _page_qs(status="done") == "?status=done"
    assert _page_qs(limit=100) == ""  # default omitted
    assert _page_qs(limit=5, offset=2, order="oldest") == "?limit=5&offset=2&order=oldest"


def test_parse_sse_extracts_data_payload():
    frame = "event: snapshot\ndata: {\"jobs\": []}\n"
    assert _parse_sse(frame) == {"jobs": []}
    # Multi-line data: per the SSE spec, joined with \n before decoding.
    multi = "data: {\"a\":\ndata: 1}\n"
    assert _parse_sse(multi) == {"a": 1}
    # Frames with no ``data:`` lines (heartbeats) → None, not error.
    assert _parse_sse("event: ping\n") is None


# ---------------------------------------------------------------------------
# End-to-end: real Flask app on a random port, exercised via the client.
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    """Spin up the real Flask app via wsgiref on a random port.

    Yields the base URL. Daemon thread → no teardown noise. Stdlib-only
    so the test fits the same no-deps profile as the client itself.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    import app as _app
    import models_store
    # Pin every persisted-state directory under tmp_path so the live
    # server starts with a clean slate. Without these, create_app()
    # picks up real downloads/ + models/ from the project root.
    monkeypatch.setattr(_app, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path / "models")

    from app import create_app
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    class _Quiet(WSGIRequestHandler):
        def log_message(self, *a, **kw): pass  # silence per-request stderr

    port = _free_port()
    httpd = make_server("127.0.0.1", port, create_app(), handler_class=_Quiet)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        # Tiny readiness wait — wsgiref binds before serve_forever loops.
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), 0.1):
                    break
            except OSError:
                time.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_e2e_health_through_client(live_server):
    """Smoke test: client → real Flask app → JSON response."""
    c = TroveClient(base_url=live_server)
    health = c.get("/api/v1/health")
    assert health.get("ok") is True


def test_e2e_list_jobs_pagination_shape(live_server):
    """``list_jobs`` against an empty server returns the canonical
    paginated envelope — pins the shape both CLI and MCP rely on."""
    c = TroveClient(base_url=live_server)
    res = c.list_jobs(limit=5)
    assert set(res.keys()) >= {"jobs", "total", "returned", "limit", "offset"}
    assert res["jobs"] == []
    assert res["total"] == 0


def test_e2e_storage_info_through_client(live_server):
    c = TroveClient(base_url=live_server)
    rep = c.storage_info()
    assert "download_dir" in rep and "total_bytes" in rep
    assert rep["file_count"] == 0
