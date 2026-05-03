"""``trove_client`` — shared HTTP client for the Trove ``/api/v1`` surface.

Both the CLI (``cli.py``) and the MCP server (``mcp_server.py``) depend
on this module instead of on each other. That keeps the MCP server free
of CLI-specific behavior (terminal formatting, exit semantics, banners,
argparse, stdout/stderr conventions) and gives tests one canonical
client to exercise the API through.

Stdlib-only on purpose so neither surface picks up an extra dependency.

Configuration is read from environment at call time (not import time) so
a process can ``monkeypatch.setenv`` mid-test without rebuilding the
client:

    TROVE_URL    Base URL of the running server (default localhost:8899).
    TROVE_TOKEN  Bearer token if the server was started with one.

Quick start:

    from trove_client import TroveClient
    c = TroveClient()                       # picks up TROVE_URL/TROVE_TOKEN
    jobs = c.list_jobs(status="done", limit=5)
    new  = c.submit_download("https://…", fmt="audio")
    txt  = c.export_transcript(tid, "txt")
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator

from config import DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TroveError(RuntimeError):
    """Raised for any non-2xx response from the Trove server.

    Carries the parsed JSON body (if any) so callers can format a
    useful message instead of a bare urllib stack trace. Both the CLI
    and the MCP server depend on this exact shape.
    """
    def __init__(self, status: int, body: Any, url: str):
        self.status = status
        self.body = body
        self.url = url
        msg = body.get("error") if isinstance(body, dict) else str(body)
        super().__init__(f"HTTP {status} {url} -> {msg}")


# ---------------------------------------------------------------------------
# Helpers shared between client + module-level utilities
# ---------------------------------------------------------------------------

def _page_qs(status: str = "", limit: int = 100,
             offset: int = 0, order: str = "newest") -> str:
    """Build ``?status=&limit=&offset=&order=`` for the list endpoints.

    Defaults that match the server-side defaults are omitted so a bare
    ``client.list_jobs()`` produces the canonical ``GET /api/v1/jobs``
    URL — which is what the contract tests pin.
    """
    parts: list[str] = []
    if status:
        parts.append("status=" + urllib.parse.quote(status))
    if limit and int(limit) != 100:
        parts.append(f"limit={int(limit)}")
    if offset:
        parts.append(f"offset={int(offset)}")
    if order and order != "newest":
        parts.append(f"order={order}")
    return ("?" + "&".join(parts)) if parts else ""


def _parse_sse(message: str) -> dict | None:
    """Pull the JSON ``data:`` payload out of one SSE frame, or None.

    Multi-line ``data:`` lines are joined with ``\\n`` per the SSE
    spec before json-decoding, so the server can split a long event
    across lines without breaking us.
    """
    data_lines: list[str] = []
    for line in message.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TroveClient:
    """Synchronous HTTP client over the Trove ``/api/v1`` surface.

    All HTTP plumbing concerns (auth header, JSON encode/decode,
    error mapping, streaming downloads, SSE) live here. CLI commands
    and MCP tools both depend on this class so neither inherits the
    other's UI/transport baggage.

    Construct with no args to pick up TROVE_URL / TROVE_TOKEN from
    the environment lazily (env can change after construction). Pass
    ``base_url`` / ``token`` to pin a specific endpoint — useful in
    tests against a thread-local Flask server on a random port.
    """

    def __init__(self, base_url: str | None = None,
                 token: str | None = None,
                 *, timeout: int = 30):
        # ``None`` here means "fall back to env at call time". An
        # explicit empty string for ``token`` is honored as "no token"
        # (overrides env), which is what tests want.
        self._explicit_base = base_url
        self._explicit_token = token
        self.timeout = timeout

    # ----- env-aware accessors ----------------------------------------

    @property
    def base_url(self) -> str:
        if self._explicit_base is not None:
            return self._explicit_base.rstrip("/")
        return os.environ.get("TROVE_URL", DEFAULT_BASE_URL).rstrip("/")

    @property
    def token(self) -> str:
        if self._explicit_token is not None:
            return self._explicit_token
        return os.environ.get("TROVE_TOKEN", "").strip()

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        tok = self.token
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    # ----- low-level request ------------------------------------------

    def request(self, method: str, path: str, *,
                body: dict | None = None,
                stream_to: str | None = None,
                timeout: int | None = None,
                headers: dict | None = None) -> Any:
        """Issue one HTTP call and parse the response.

        Returns the decoded JSON body for 2xx responses, ``None`` for
        204s, raw text for non-JSON bodies. Raises ``TroveError`` for
        any non-2xx status. When ``stream_to`` is set the response body
        is written verbatim to that file path (used for export
        downloads) and the call returns ``{"saved_to": stream_to}``.

        A network-level failure (server unreachable) raises
        ``SystemExit`` with a friendly hint — both surfaces want to
        bail with a user-readable message rather than a stack trace.
        """
        url = self.base_url + path
        data = None
        # ``headers`` overrides let callers (e.g. cli.py's monkeypatch-
        # friendly shim chain) inject a different header set without
        # bypassing the rest of the request/parse pipeline.
        headers = dict(headers) if headers is not None else self._headers()
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                if stream_to is not None:
                    with open(stream_to, "wb") as out:
                        while True:
                            chunk = resp.read(64 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                    return {"saved_to": stream_to}
                raw = resp.read()
                if resp.status == 204 or not raw:
                    return None
                ct = resp.headers.get("Content-Type", "")
                if ct.startswith("application/json"):
                    return json.loads(raw.decode("utf-8"))
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = raw.decode("utf-8", errors="replace")
            raise TroveError(e.code, parsed, url) from None
        except urllib.error.URLError as e:
            raise SystemExit(
                f"trove: cannot reach {url} ({e.reason}). "
                f"Is the server running? Try: trove serve"
            )

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw)

    def post(self, path: str, body: dict | None = None, **kw):
        return self.request("POST", path, body=body, **kw)

    # ----- jobs (downloads) -------------------------------------------

    def list_jobs(self, *, status: str = "", limit: int = 100,
                  offset: int = 0, order: str = "newest") -> dict:
        return self.get("/api/v1/jobs" + _page_qs(status, limit, offset, order))

    def get_job(self, job_id: str) -> dict:
        return self.get(f"/api/v1/jobs/{job_id}")

    def submit_download(self, url: str, *, fmt: str = "video",
                        auto_transcribe: bool = False,
                        title: str | None = None) -> dict:
        body: dict = {"url": url, "format": fmt,
                      "auto_transcribe": auto_transcribe}
        if title:
            body["title"] = title
        return self.post("/api/v1/jobs", body=body)

    def bulk_download(self, urls, *, fmt: str = "video",
                      auto_transcribe: bool = False) -> dict:
        return self.post("/api/v1/jobs/bulk", body={
            "urls": list(urls), "format": fmt,
            "auto_transcribe": auto_transcribe,
        })

    def pause_job(self, job_id: str):    return self.post(f"/api/v1/jobs/{job_id}/pause")
    def resume_job(self, job_id: str):   return self.post(f"/api/v1/jobs/{job_id}/resume")
    def cancel_job(self, job_id: str):   return self.post(f"/api/v1/jobs/{job_id}/cancel")
    def dismiss_job(self, job_id: str):  return self.post(f"/api/v1/jobs/{job_id}/dismiss")

    def storage_info(self) -> dict:
        return self.get("/api/v1/storage")

    # ----- transcripts ------------------------------------------------

    def list_transcripts(self, *, status: str = "", limit: int = 100,
                         offset: int = 0, order: str = "newest") -> dict:
        return self.get("/api/v1/transcripts" + _page_qs(status, limit, offset, order))

    def get_transcript_status(self, tid: str) -> dict:
        return self.get(f"/api/v1/transcripts/{tid}")

    def transcribe(self, parent_job_id: str) -> dict:
        return self.post(f"/api/v1/jobs/{parent_job_id}/transcribe")

    def cancel_transcribe(self, tid: str):
        return self.post(f"/api/v1/transcripts/{tid}/cancel")

    def export_transcript(self, tid: str, fmt: str = "txt", *,
                          stream_to: str | None = None):
        """Fetch (or stream-save) a finished transcript artifact.

        ``txt|srt|vtt`` return the decoded text body; ``json`` returns
        the parsed v2 schema dict. With ``stream_to`` the bytes are
        written to disk verbatim and ``{"saved_to": …}`` is returned.
        """
        if fmt not in {"txt", "srt", "vtt", "json"}:
            raise ValueError(f"unknown export format: {fmt!r}")
        return self.get(f"/api/v1/transcripts/{tid}/export.{fmt}",
                        stream_to=stream_to)

    def get_transcript_chunk(self, tid: str, fmt: str = "txt", *,
                             offset: int = 0,
                             limit: int | None = None) -> dict:
        """Paginated read of a transcript (server-side ``/chunk``).

        ``fmt`` is one of ``txt|srt|vtt|json``. ``offset`` is a *byte*
        offset for text formats and a *segment* index for ``json``.
        ``limit`` follows the server-side defaults (4000 bytes or 50
        segments) when omitted. Returns the JSON envelope verbatim so
        callers can drive their own pagination loop on
        ``has_more`` / ``offset + returned``.
        """
        if fmt not in {"txt", "srt", "vtt", "json"}:
            raise ValueError(f"unknown export format: {fmt!r}")
        parts = [f"format={fmt}"]
        if offset:
            parts.append(f"offset={int(offset)}")
        if limit is not None:
            parts.append(f"limit={int(limit)}")
        qs = "?" + "&".join(parts)
        return self.get(f"/api/v1/transcripts/{tid}/chunk" + qs)

    def search_transcripts(self, query: str, *, limit: int = 50,
                           context: int = 60) -> dict:
        qs = (f"?q={urllib.parse.quote(query)}"
              f"&limit={int(limit)}&context={int(context)}")
        return self.get("/api/v1/transcripts/search" + qs)

    # ----- models -----------------------------------------------------

    def capabilities(self) -> dict:
        """Fetch the server's feature / limit / scope registry.

        Unauthenticated; safe to call before a token is configured.
        Returns the JSON envelope from ``/api/v1/capabilities``
        verbatim so callers can branch on ``auth_required``,
        ``features.diarization``, ``limits.transcript_chunk.*``, etc.
        """
        return self.get("/api/v1/capabilities")

    def list_models(self) -> dict:                 return self.get("/api/v1/models")
    def install_model(self, name: str) -> dict:    return self.post(f"/api/v1/models/{name}/install")
    def model_install_progress(self) -> dict:      return self.get("/api/v1/models/install-progress")
    def set_active_model(self, name: str) -> dict: return self.post(f"/api/v1/models/{name}/use")
    def remove_model(self, name: str):             return self.post(f"/api/v1/models/{name}/remove")

    # ----- events (SSE) -----------------------------------------------

    def stream_events(self, *, max_events: int | None = None,
                      interval: float | None = None) -> Iterator[dict]:
        """Iterate over SSE event payloads as dicts.

        ``max_events`` mirrors the server's test hook so tests don't
        need to forcibly close the socket. ``interval`` overrides the
        server-side poll cadence. Yielded payloads are the parsed
        ``data:`` JSON of each frame; non-``data`` keepalive lines are
        skipped silently.

        Raises ``SystemExit`` if the server is unreachable, mirroring
        ``request()``. Caller is responsible for catching
        ``KeyboardInterrupt`` if they want a clean Ctrl-C.
        """
        qs: list[str] = []
        if max_events:
            qs.append(f"max_events={int(max_events)}")
        if interval is not None:
            qs.append(f"interval={float(interval)}")
        path = "/api/v1/events" + (("?" + "&".join(qs)) if qs else "")
        url = self.base_url + path
        req = urllib.request.Request(url, headers=self._headers())
        try:
            # timeout=None: SSE streams are deliberately long-lived.
            resp = urllib.request.urlopen(req, timeout=None)
        except urllib.error.URLError as e:
            raise SystemExit(
                f"trove: cannot reach {url} ({e.reason}). "
                f"Is the server running? Try: trove serve"
            )
        with resp:
            buf = b""
            for chunk in iter(lambda: resp.read(1024), b""):
                buf += chunk
                while b"\n\n" in buf:
                    msg, buf = buf.split(b"\n\n", 1)
                    payload = _parse_sse(msg.decode("utf-8", errors="replace"))
                    if payload is not None:
                        yield payload
