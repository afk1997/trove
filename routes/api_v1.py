"""Blueprint: stable JSON v1 API for the CLI + MCP server.

Wraps the JobManager / TranscribeJobManager / models_store so external
clients (the ``trove`` CLI and the ``trove-mcp`` MCP server) don't have
to scrape HTML or reach into the on-disk JSON. Every route is JSON-in
/ JSON-out and gated by the same ``token_required`` decorator as the
rest of the API surface.

Complex actions (enqueue download / resume / start transcribe)
delegate to closures stashed on ``app.extensions['trove.actions']`` by
``create_app`` — that's the same indirection pattern the transcript
editor blueprint already uses for the JobManager refs, and it lets us
expose new endpoints without re-implementing the work-thunk logic that
``_enqueue_download`` and ``api_job_resume`` already encapsulate.
"""
from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock, Thread

from flask import (
    Blueprint, Response, current_app, jsonify, request, send_file,
    stream_with_context,
)

import models_store
import transcribe_jobs
import transcript_io
from jobs import JobStatus
from safety import (
    token_or_sig_required, token_required,
    SCOPE_MEDIA, SCOPE_TRANSCRIPT_EXPORT,
)
from util import sanitize_filename

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


# ----- idempotency store ---------------------------------------------
#
# Clients (CLI, MCP, scripts) often retry POST /jobs after a network
# blip. Without an idempotency key they'd silently double-submit and
# the same URL would download twice. Spec mirrors Stripe's
# Idempotency-Key header: caller supplies any opaque string (UUID
# recommended), server returns the *same* job for the same key inside
# the TTL window. In-memory only — self-hosted single-process server,
# so a process restart wipes the cache, which is fine.
_IDEMPOTENCY_TTL_SECONDS = 24 * 3600
_IDEMPOTENCY_CAPACITY    = 512


class _IdempotencyStore:
    def __init__(self, ttl: int = _IDEMPOTENCY_TTL_SECONDS,
                 capacity: int = _IDEMPOTENCY_CAPACITY):
        self._ttl = ttl
        self._cap = capacity
        self._lock = Lock()
        # OrderedDict so we can drop the oldest insert on overflow
        # without scanning the whole map.
        self._items: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def _sweep_locked(self, now: float) -> None:
        # Cheap eager TTL sweep — bounded by capacity (≤512 entries).
        dead = [k for k, (_, exp) in self._items.items() if exp <= now]
        for k in dead:
            del self._items[k]

    def get(self, key: str) -> str | None:
        if not key:
            return None
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            entry = self._items.get(key)
            return entry[0] if entry else None

    def put(self, key: str, job_id: str) -> None:
        if not key:
            return
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            self._items[key] = (job_id, now + self._ttl)
            self._items.move_to_end(key)
            while len(self._items) > self._cap:
                self._items.popitem(last=False)

    def claim(self, key: str) -> tuple[str | None, bool]:
        """Single-flight claim. Returns ``(prior_id, claimed)``.

        - If the key already maps to a real job id, returns
          ``(prior_id, False)`` — caller should replay.
        - If the key is unknown, atomically inserts a sentinel
          placeholder and returns ``(None, True)`` — caller owns the
          enqueue and must call ``finalize()`` or ``release()``.
        - If another request is mid-enqueue (placeholder present),
          returns ``(None, False)`` and the caller must surface a
          ``409 in_flight`` so the client retries after the first one
          completes (rather than silently double-enqueuing).
        """
        if not key:
            return None, True  # no idempotency requested → always proceed
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            entry = self._items.get(key)
            if entry is not None:
                jid = entry[0]
                if jid == _IN_FLIGHT:
                    return None, False  # racing peer is still enqueuing
                return jid, False
            # Reserve the slot atomically so concurrent retries see it.
            self._items[key] = (_IN_FLIGHT, now + self._ttl)
            self._items.move_to_end(key)
            while len(self._items) > self._cap:
                self._items.popitem(last=False)
            return None, True

    def release(self, key: str) -> None:
        """Drop a placeholder reservation (failed enqueue path)."""
        if not key:
            return
        with self._lock:
            entry = self._items.get(key)
            if entry is not None and entry[0] == _IN_FLIGHT:
                del self._items[key]

    def delete(self, key: str) -> None:
        """Unconditionally drop ``key`` (even a finalized job-id entry).

        Used to recover the stale-key path: a prior idempotent POST
        succeeded, but the job has since been TTL-swept / dismissed
        from the JobManager. The mapping is dead; let the next caller
        with the same key submit a fresh job."""
        if not key:
            return
        with self._lock:
            self._items.pop(key, None)


_IN_FLIGHT = "__inflight__"


_idempotency_store = _IdempotencyStore()


# Single-flight model install (mirrors the setup-page flag). Lives at
# module scope because it's a per-process singleton, not per-app.
_install_state: dict = {
    "downloading": False, "name": None,
    "received": 0, "total": 0,
    "error": None, "done": False,
}
_install_lock = Lock()


# ----- view helpers ---------------------------------------------------
# These shape the JSON payload returned to the CLI / MCP server. We
# include both raw machine-friendly fields (bytes, seconds, ratios) and
# a ``human`` block with pre-formatted strings ("12.4 MB", "2:31",
# "5.2 MB/s") so a coding agent can surface progress directly to the
# user without re-implementing formatting on every client.

def _human_bytes(n: int | float | None) -> str:
    if not n or n <= 0:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _human_duration(seconds: float | int | None) -> str:
    """Format seconds as ``H:MM:SS`` (or ``M:SS`` under an hour)."""
    if seconds is None or seconds < 0:
        return "—"
    s = int(seconds)
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _human_speed(bps: float | int | None) -> str:
    if not bps or bps <= 0:
        return "—"
    return f"{_human_bytes(bps)}/s"


def _download_pct(job) -> int:
    """Best-effort percent complete for a download. Prefers byte ratio,
    falls back to fragment ratio (HLS / DASH), 100 when terminal."""
    try:
        from jobs import JobStatus
        if job.status == JobStatus.DONE:
            return 100
    except Exception:
        pass
    if job.total_bytes:
        return min(100, int(job.downloaded_bytes / job.total_bytes * 100))
    if job.fragment_count:
        return min(100, int(job.fragment_index / job.fragment_count * 100))
    return 0


def _job_view(job) -> dict:
    elapsed = max(0.0, time.monotonic() - job.created_at)
    pct = _download_pct(job)
    out = {
        "id": job.id,
        "url": job.url,
        "title": job.title,
        "status": job.status.value,
        "filename": job.filename,
        "thumbnail": job.thumbnail or None,
        "format_choice": job.format_choice,
        # Raw machine-readable progress
        "downloaded_bytes": job.downloaded_bytes,
        "total_bytes": job.total_bytes,
        "speed_bps": job.speed,
        "eta_seconds": job.eta,
        "fragment_index": job.fragment_index,
        "fragment_count": job.fragment_count,
        "progress_pct": pct,
        "elapsed_seconds": round(elapsed, 1),
        "auto_transcribe": job.auto_transcribe,
        "error_category": job.error_category,
        "error_message": job.error_message,
    }
    # Pre-formatted strings for direct display by the agent / CLI.
    out["human"] = {
        "progress": f"{pct}%",
        "downloaded": _human_bytes(job.downloaded_bytes),
        "size": _human_bytes(job.total_bytes),
        "speed": _human_speed(job.speed),
        "eta": _human_duration(job.eta) if job.eta else "—",
        "elapsed": _human_duration(elapsed),
        # One-liner you can drop straight into a chat: e.g.
        # "downloading · 42% · 12.4 MB / 29.7 MB · 5.2 MB/s · ETA 0:03"
        "summary": _summarize_job(job, pct, elapsed),
    }
    return out


def _summarize_job(job, pct: int, elapsed: float) -> str:
    bits = [job.status.value]
    if job.status.value in ("downloading", "queued"):
        bits.append(f"{pct}%")
        if job.total_bytes:
            bits.append(f"{_human_bytes(job.downloaded_bytes)} / "
                        f"{_human_bytes(job.total_bytes)}")
        elif job.downloaded_bytes:
            bits.append(_human_bytes(job.downloaded_bytes))
        if job.speed:
            bits.append(_human_speed(job.speed))
        if job.eta:
            bits.append(f"ETA {_human_duration(job.eta)}")
    elif job.status.value == "done":
        if job.total_bytes:
            bits.append(_human_bytes(job.total_bytes))
        bits.append(f"in {_human_duration(elapsed)}")
    elif job.status.value == "error" and job.error_message:
        bits.append(f"— {job.error_message}")
    return " · ".join(bits)


def _tj_view(tj) -> dict:
    elapsed = max(0.0, time.monotonic() - tj.started_at)
    out = {
        "id": tj.id,
        "parent_job_id": tj.parent_job_id,
        "status": tj.status.value,
        "model_used": tj.model_used,
        "progress_pct": tj.progress_pct,
        "duration_seconds": tj.duration_seconds,
        "language_detected": tj.language_detected,
        "elapsed_seconds": round(elapsed, 1),
        "error_category": tj.error_category,
        "error_message": tj.error_message,
        "diarization_status": tj.diarization_status,
        "diarization_error": tj.diarization_error,
        "speaker_count": tj.speaker_count,
    }
    out["human"] = {
        "progress": f"{tj.progress_pct}%",
        "elapsed": _human_duration(elapsed),
        "audio_duration": _human_duration(tj.duration_seconds)
            if tj.duration_seconds else "—",
        "summary": _summarize_tj(tj, elapsed),
    }
    return out


def _summarize_tj(tj, elapsed: float) -> str:
    bits = [tj.status.value]
    if tj.status.value == "running":
        bits.append(f"{tj.progress_pct}%")
        if tj.duration_seconds:
            bits.append(f"of {_human_duration(tj.duration_seconds)} audio")
        bits.append(f"elapsed {_human_duration(elapsed)}")
        if tj.model_used:
            bits.append(f"model={tj.model_used}")
    elif tj.status.value == "done":
        bits.append(f"in {_human_duration(elapsed)}")
        if tj.language_detected:
            bits.append(f"lang={tj.language_detected}")
    elif tj.status.value == "error" and tj.error_message:
        bits.append(f"— {tj.error_message}")
    return " · ".join(bits)


def _jm():
    return current_app.extensions["trove.jobs"]


def _tm():
    return current_app.extensions["trove.transcribe"]


def _actions():
    return current_app.extensions["trove.actions"]


def _download_dir() -> Path:
    return current_app.extensions["trove.download_dir"]


# ----- pagination + filtering helpers --------------------------------

def _parse_page_args() -> tuple[int, int, str, str | None]:
    """Pull ``?limit=&offset=&order=&status=`` off the request, with
    defensive clamping.

    Back-compat: if the caller does NOT supply ``limit``, we return all
    matching items (legacy behavior). Pre-pagination clients that just
    called ``GET /jobs`` must keep getting the full list. A caller that
    explicitly opts in to paging (``?limit=N``) is clamped to 1-500."""
    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = _UNLIMITED
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 100
        limit = max(1, min(500, limit))
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        offset = 0
    offset = max(0, offset)
    order = request.args.get("order", "newest").lower()
    if order not in ("newest", "oldest"):
        order = "newest"
    status = request.args.get("status")
    return limit, offset, order, status


# Sentinel meaning "no caller-supplied limit; return everything after
# offset". Concrete int so downstream slice math doesn't need a branch.
_UNLIMITED = 10 ** 9


def _paginate(items: list, *, status: str | None, status_attr: str,
              order: str, limit: int, offset: int) -> tuple[list, int]:
    """Apply status filter + ordering + slice. Returns (page, total).

    ``status_attr`` is the attribute path on each item (e.g. ``status``
    on Job/TranscribeJob — both expose ``.status.value``).
    """
    if status:
        wanted = {s.strip().lower() for s in status.split(",") if s.strip()}
        items = [
            it for it in items
            if getattr(it, status_attr).value in wanted
        ]
    # JobManager stores in insertion order; reverse for "newest first".
    if order == "newest":
        items = list(reversed(items))
    total = len(items)
    page = items[offset : offset + limit]
    return page, total


# ----- meta -----------------------------------------------------------

@api_v1_bp.get("/health")
def health():
    """Liveness probe. Unauthenticated on purpose so the CLI can detect
    the server is up before prompting the user for a token."""
    return jsonify({"ok": True, "version": "v1"})


# ----- jobs -----------------------------------------------------------

@api_v1_bp.get("/jobs")
@token_required
def list_jobs():
    """List download jobs.

    Query params (all optional):
      * ``status``: comma-separated filter (e.g. ``done,error``).
      * ``limit``: 1-500, default 100.
      * ``offset``: pagination cursor (0-based).
      * ``order``: ``newest`` (default) or ``oldest``.

    Returns ``{jobs, total, returned, limit, offset}`` so the caller
    can show "showing 20 of 137" and page without re-counting.
    """
    limit, offset, order, status = _parse_page_args()
    page, total = _paginate(
        _jm().snapshot_jobs(),
        status=status, status_attr="status",
        order=order, limit=limit, offset=offset,
    )
    return jsonify({
        "jobs": [_job_view(j) for j in page],
        "total": total, "returned": len(page),
        "limit": _surface_limit(limit, len(page)), "offset": offset,
    })


def _surface_limit(limit: int, returned: int) -> int:
    """Hide the internal _UNLIMITED sentinel from JSON callers — surface
    the actual page size when the caller asked for "everything"."""
    if limit >= _UNLIMITED:
        return returned
    return limit


@api_v1_bp.get("/jobs/<job_id>")
@token_required
def get_job(job_id):
    job = _jm().get(job_id)
    if job is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_job_view(job))


def _submit_one(url: str, *, format_choice: str = "video",
                format_id: str | None = None, title: str = "",
                thumbnail: str = "", auto_transcribe: bool = False
                ) -> tuple[dict | None, dict | None]:
    """Shared download-submission core used by both the single-URL
    POST /jobs path and the bulk POST /jobs/bulk path.

    Returns ``(job_view, None)`` on success or ``(None, error_dict)`` on
    failure. The caller is responsible for HTTP status mapping (single
    posts surface 4xx; bulk posts return per-URL errors in the array).
    """
    from safety import is_safe_url
    from runner import run_info

    if not url:
        return None, {"error": "missing_url"}
    if not is_safe_url(url):
        return None, {"error": "unsupported_url"}

    if not title:
        info = run_info(url)
        if info.error_category:
            return None, {"error": info.error_category}
        title = info.title or url
        if not thumbnail:
            thumbnail = info.thumbnail or ""

    try:
        job_id = _actions()["enqueue_download"](
            url, format_choice, format_id, title, thumbnail,
            auto_transcribe=auto_transcribe,
        )
    except RuntimeError:
        return None, {"error": "busy"}
    return _job_view(_jm().get(job_id)), None


@api_v1_bp.post("/jobs")
@token_required
def submit_job():
    """Enqueue a new download. Body: ``{url, format?, format_id?, title?, auto_transcribe?}``.

    ``format`` defaults to ``"video"`` (mp4); pass ``"audio"`` for mp3.
    ``auto_transcribe=true`` triggers transcription on success when an
    active model is installed.

    Idempotency: if the request includes an ``Idempotency-Key`` header
    AND the same key was used in the last 24h to create a job that
    still exists, the same job is returned (HTTP 200 + ``X-Idempotent-
    Replay: true`` header) instead of creating a duplicate.
    """
    idem_key = request.headers.get("Idempotency-Key", "").strip()
    # Single-flight claim BEFORE enqueue so two concurrent retries with
    # the same key never both reach the worker.
    prior_id, claimed = _idempotency_store.claim(idem_key)
    if prior_id is not None:
        existing = _jm().get(prior_id)
        if existing is not None:
            resp = jsonify(_job_view(existing))
            resp.headers["X-Idempotent-Replay"] = "true"
            return resp, 200
        # Prior id no longer in the manager (TTL'd out / dismissed).
        # ``release()`` only drops placeholders, so use ``delete()`` to
        # evict the finalized mapping before re-claiming — otherwise
        # the second claim would observe the dead entry and 409 forever.
        _idempotency_store.delete(idem_key)
        prior_id, claimed = _idempotency_store.claim(idem_key)
    if not claimed:
        # Another request is still mid-enqueue for this key. Tell the
        # client to retry instead of silently double-enqueuing.
        return jsonify({"error": "in_flight",
                         "message": "An identical request is still being processed."}), 409

    data = request.get_json(silent=True) or {}
    try:
        view, err = _submit_one(
            (data.get("url") or "").strip(),
            format_choice=data.get("format", "video"),
            format_id=data.get("format_id"),
            title=(data.get("title") or "").strip(),
            thumbnail=(data.get("thumbnail") or "").strip(),
            auto_transcribe=bool(data.get("auto_transcribe")),
        )
    except BaseException:
        _idempotency_store.release(idem_key)
        raise
    if err is not None:
        _idempotency_store.release(idem_key)
        # Map error codes to HTTP status. ``busy`` is a real 503 (queue
        # full); everything else is a 400 (caller-side problem).
        code = 503 if err["error"] == "busy" else 400
        return jsonify(err), code
    if idem_key:
        _idempotency_store.put(idem_key, view["id"])
    return jsonify(view), 201


@api_v1_bp.post("/jobs/bulk")
@token_required
def submit_bulk():
    """Enqueue many downloads in one round-trip.

    Body: ``{urls: [...], format?, format_id?, auto_transcribe?}``.
    Each URL gets its own job. Per-URL errors are returned alongside
    successes — the response body is::

        {
          "submitted": 7,
          "failed": 2,
          "results": [
            {"url": "...", "id": "abc123", "title": "..."},
            {"url": "...", "error": "unsupported_url"},
            ...
          ]
        }

    HTTP 207 Multi-Status when any URL failed; 201 when all succeeded;
    400 when the body itself is malformed.
    """
    data = request.get_json(silent=True) or {}
    urls = data.get("urls")
    if not isinstance(urls, list) or not urls:
        return jsonify({"error": "missing_urls"}), 400
    if len(urls) > 100:
        return jsonify({"error": "too_many_urls", "limit": 100}), 400

    fmt = data.get("format", "video")
    fmt_id = data.get("format_id")
    auto_t = bool(data.get("auto_transcribe"))

    results = []
    submitted = failed = 0
    for raw in urls:
        u = (raw or "").strip() if isinstance(raw, str) else ""
        view, err = _submit_one(
            u, format_choice=fmt, format_id=fmt_id,
            auto_transcribe=auto_t,
        )
        if view is not None:
            results.append({"url": u, "id": view["id"], "title": view["title"]})
            submitted += 1
        else:
            results.append({"url": u, **err})
            failed += 1
    status_code = 201 if failed == 0 else 207
    return jsonify({
        "submitted": submitted, "failed": failed, "results": results,
    }), status_code


@api_v1_bp.post("/jobs/<job_id>/pause")
@token_required
def pause_job(job_id):
    if not _jm().pause(job_id):
        return jsonify({"error": "not_found_or_terminal"}), 404
    return jsonify(_job_view(_jm().get(job_id)))


@api_v1_bp.post("/jobs/<job_id>/resume")
@token_required
def resume_job(job_id):
    job = _jm().get(job_id)
    if job is None:
        return jsonify({"error": "not_found"}), 404
    if not _actions()["resume_job"](job_id):
        return jsonify({"error": "not_resumable"}), 409
    return jsonify(_job_view(_jm().get(job_id)))


@api_v1_bp.post("/jobs/<job_id>/cancel")
@token_required
def cancel_job(job_id):
    if not _jm().cancel(job_id):
        return jsonify({"error": "not_found"}), 404
    job = _jm().get(job_id)
    return jsonify(_job_view(job)) if job else ("", 204)


@api_v1_bp.post("/jobs/<job_id>/dismiss")
@token_required
def dismiss_job(job_id):
    if not _jm().dismiss(job_id):
        return jsonify({"error": "not_found_or_active"}), 404
    return ("", 204)


@api_v1_bp.get("/jobs/<job_id>/file")
@token_or_sig_required(SCOPE_MEDIA, kwarg="job_id")
def get_job_file(job_id):
    job = _jm().get(job_id)
    if job is None or job.status != JobStatus.DONE or not job.file_path:
        return jsonify({"error": "not_ready"}), 404
    return send_file(
        job.file_path, as_attachment=True,
        download_name=job.filename or "download",
    )


# ----- transcripts ----------------------------------------------------

@api_v1_bp.get("/transcripts")
@token_required
def list_transcripts():
    """Same pagination + filtering surface as :func:`list_jobs`."""
    limit, offset, order, status = _parse_page_args()
    page, total = _paginate(
        _tm().snapshot_jobs(),
        status=status, status_attr="status",
        order=order, limit=limit, offset=offset,
    )
    return jsonify({
        "transcripts": [_tj_view(t) for t in page],
        "total": total, "returned": len(page),
        "limit": _surface_limit(limit, len(page)), "offset": offset,
    })


@api_v1_bp.get("/transcripts/search")
@token_required
def search_transcripts():
    """Substring search across all completed transcripts.

    Query: ``?q=<phrase>&limit=&context=``.
    Returns matches with a contextual snippet (default ±60 chars) and
    the timing range of the words that contained the hit, so the
    caller can deep-link into the editor at the right point.
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "missing_query"}), 400
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(200, limit))
    try:
        ctx = int(request.args.get("context", "60"))
    except ValueError:
        ctx = 60
    ctx = max(0, min(400, ctx))

    needle = q.lower()
    matches = []
    for tj in _tm().snapshot_jobs():
        if tj.status != transcribe_jobs.TranscribeStatus.DONE:
            continue
        parent = _jm().get(tj.parent_job_id)
        if parent is None or not parent.file_path:
            continue
        words_path = os.path.splitext(parent.file_path)[0] + ".words.json"
        if not os.path.exists(words_path):
            continue
        try:
            data = transcript_io.load(words_path)
        except Exception:
            continue
        words = data.get("words") or []
        # Build a flat text + a per-char index → word map so we can
        # convert string-match offsets back to word ranges (and from
        # there, to start/end timestamps for deep-linking).
        chunks = []
        char_to_widx = []
        for i, w in enumerate(words):
            if w.get("deleted"):
                continue
            text = w.get("w") or ""
            if chunks:
                chunks.append(" ")
                char_to_widx.append(i)
            chunks.append(text)
            char_to_widx.extend([i] * len(text))
        flat = "".join(chunks)
        if not flat:
            continue
        flat_lower = flat.lower()
        start = 0
        while True:
            hit = flat_lower.find(needle, start)
            if hit == -1:
                break
            end = hit + len(needle)
            w_start = char_to_widx[hit] if hit < len(char_to_widx) else 0
            w_end = char_to_widx[end - 1] if end - 1 < len(char_to_widx) else w_start
            snippet_lo = max(0, hit - ctx)
            snippet_hi = min(len(flat), end + ctx)
            snippet = flat[snippet_lo:snippet_hi]
            matches.append({
                "transcript_id": tj.id,
                "parent_job_id": tj.parent_job_id,
                "title": parent.title,
                "snippet": ("…" if snippet_lo > 0 else "") + snippet
                           + ("…" if snippet_hi < len(flat) else ""),
                "start_seconds": float(words[w_start].get("start") or 0.0),
                "end_seconds":   float(words[w_end].get("end") or 0.0),
                "match_offset": hit,
            })
            if len(matches) >= limit:
                break
            start = end
        if len(matches) >= limit:
            break
    return jsonify({"query": q, "matches": matches, "returned": len(matches)})


@api_v1_bp.get("/transcripts/<tid>")
@token_required
def get_transcript(tid):
    tj = _tm().get(tid)
    if tj is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_tj_view(tj))


@api_v1_bp.post("/jobs/<parent_job_id>/transcribe")
@token_required
def start_transcribe(parent_job_id):
    parent = _jm().get(parent_job_id)
    if parent is None or parent.status != JobStatus.DONE or not parent.file_path:
        return jsonify({"error": "parent_not_done"}), 404
    if models_store.get_active_path() is None:
        return jsonify({"error": "no_active_model"}), 409

    # Idempotent: return the existing in-flight transcribe instead of
    # spawning a duplicate. Same guard the HTML start endpoint uses.
    existing = _tm().get_by_parent(parent_job_id)
    if existing and existing.status in (
        transcribe_jobs.TranscribeStatus.QUEUED,
        transcribe_jobs.TranscribeStatus.RUNNING,
    ):
        return jsonify(_tj_view(existing)), 200

    tjid = _actions()["start_transcribe"](parent_job_id)
    if tjid is None:
        return jsonify({"error": "submit_failed"}), 500
    return jsonify(_tj_view(_tm().get(tjid))), 201


@api_v1_bp.post("/transcripts/<tid>/cancel")
@token_required
def cancel_transcript(tid):
    if not _tm().cancel(tid):
        return jsonify({"error": "not_found_or_terminal"}), 404
    return jsonify(_tj_view(_tm().get(tid)))


@api_v1_bp.post("/transcripts/<tid>/dismiss")
@token_required
def dismiss_transcript(tid):
    if not _tm().dismiss(tid):
        return jsonify({"error": "not_found_or_active"}), 404
    return ("", 204)


@api_v1_bp.get("/transcripts/<tid>/export.<fmt>")
@token_or_sig_required(SCOPE_TRANSCRIPT_EXPORT, kwarg="tid")
def export_transcript(tid, fmt):
    """Stream the saved export artifact for a finished transcript.

    ``json`` returns the raw v2 ``.words.json`` (the editor's source
    of truth — useful for programmatic post-processing). ``txt|srt|
    vtt`` return the rendered artifacts.
    """
    # JSON 404s (not Flask's HTML default) so CLI/MCP callers get a
    # parseable error body instead of an HTML page.
    if fmt not in {"txt", "srt", "vtt", "json"}:
        return jsonify({"error": "invalid_format"}), 404
    tj = _tm().get(tid)
    if tj is None or tj.status != transcribe_jobs.TranscribeStatus.DONE:
        return jsonify({"error": "transcript_not_found_or_not_done"}), 404
    parent = _jm().get(tj.parent_job_id)
    if parent is None or not parent.file_path:
        return jsonify({"error": "parent_job_missing"}), 404
    base = os.path.splitext(parent.file_path)[0]
    suffix = ".words.json" if fmt == "json" else ("." + fmt)
    path = base + suffix
    if not os.path.exists(path):
        return jsonify({"error": "artifact_not_on_disk"}), 404
    mime = {
        "txt": "text/plain; charset=utf-8",
        "srt": "application/x-subrip",
        "vtt": "text/vtt; charset=utf-8",
        "json": "application/json",
    }[fmt]
    name = sanitize_filename(parent.title or "transcript", "." + fmt)
    return send_file(path, mimetype=mime, as_attachment=True, download_name=name)


# ----- models ---------------------------------------------------------

@api_v1_bp.get("/models")
@token_required
def list_models():
    active = models_store.get_active()
    installed = set(models_store.list_installed())
    out = []
    for name, meta in models_store.KNOWN_MODELS.items():
        out.append({
            "name": name,
            "label": meta["label"],
            "size_bytes": meta["size_bytes"],
            "stars": meta["stars"],
            "multilingual": meta["multilingual"],
            "is_active": name == active,
            "is_installed": name in installed,
        })
    with _install_lock:
        progress = dict(_install_state)
    return jsonify({"active": active, "models": out, "install_progress": progress})


@api_v1_bp.post("/models/<name>/use")
@token_required
def use_model(name):
    if name not in models_store.KNOWN_MODELS:
        return jsonify({"error": "unknown_model"}), 400
    try:
        models_store.set_active(name)
    except FileNotFoundError:
        return jsonify({"error": "not_installed"}), 409
    return jsonify({"active": name})


@api_v1_bp.post("/models/<name>/remove")
@token_required
def remove_model(name):
    if name not in models_store.KNOWN_MODELS:
        return jsonify({"error": "unknown_model"}), 400
    models_store.remove(name)
    return ("", 204)


@api_v1_bp.post("/models/<name>/install")
@token_required
def install_model(name):
    if name not in models_store.KNOWN_MODELS:
        return jsonify({"error": "unknown_model"}), 400
    with _install_lock:
        if _install_state["downloading"]:
            return jsonify({"error": "busy", "name": _install_state["name"]}), 409
        _install_state.update({
            "downloading": True, "name": name,
            "received": 0, "total": models_store.KNOWN_MODELS[name]["size_bytes"],
            "error": None, "done": False,
        })

    def _progress(rec, total):
        with _install_lock:
            _install_state["received"] = rec
            _install_state["total"] = total

    def _worker():
        try:
            models_store.download(name, progress_cb=_progress, verify=True)
            models_store.set_active(name)
            with _install_lock:
                _install_state["downloading"] = False
                _install_state["done"] = True
        except Exception as e:
            with _install_lock:
                _install_state["downloading"] = False
                _install_state["error"] = type(e).__name__ + ": " + str(e)

    Thread(target=_worker, daemon=True, name="trove-v1-model-install").start()
    return jsonify({"name": name, "downloading": True}), 202


@api_v1_bp.get("/models/install-progress")
@token_required
def install_progress():
    with _install_lock:
        return jsonify(dict(_install_state))


# ----- storage / disk usage ------------------------------------------

def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


@api_v1_bp.get("/storage")
@token_required
def storage_info():
    """Disk-usage report for the download directory.

    Walks the on-disk tree (NOT the JobManager) so orphan files left
    behind by crashes are still counted — this is the same number the
    user would get from ``du -sb downloads/``. Per-job breakdown is
    derived by matching files to job IDs (file basename starts with
    the job id) so the user can see which downloads are taking space.

    Response::

        {
          "download_dir": "/abs/path/downloads",
          "total_bytes": 12345,
          "file_count": 7,
          "by_job": [
            {"id": "abc", "title": "...", "bytes": 1234,
             "files": [{"path": "...", "bytes": 1234}]},
            ...
          ],
          "orphan_bytes": 0,
          "orphan_files": []
        }
    """
    root = _download_dir()
    by_job: dict[str, dict] = {}
    orphan_files: list[dict] = []
    orphan_bytes = 0
    total = 0
    file_count = 0

    # Index known job ids once so file-to-job attribution is O(N+M).
    jobs_by_id = {j.id: j for j in _jm().snapshot_jobs()}

    if root.exists():
        for entry in os.scandir(root):
            if not entry.is_file():
                continue
            # Internal bookkeeping files we never want to surface.
            if entry.name in ("jobs.json", "transcribe_jobs.json"):
                continue
            size = _file_size(entry.path)
            total += size
            file_count += 1
            # Job ids are the prefix of the filename up to the first
            # `.` (e.g. ``abc123.mp4`` or ``abc123.words.json``).
            stem = entry.name.split(".", 1)[0]
            if stem in jobs_by_id:
                slot = by_job.setdefault(stem, {
                    "id": stem,
                    "title": jobs_by_id[stem].title,
                    "bytes": 0,
                    "files": [],
                })
                slot["bytes"] += size
                slot["files"].append({"name": entry.name, "bytes": size})
            else:
                orphan_files.append({"name": entry.name, "bytes": size})
                orphan_bytes += size

    # Sort biggest first so the report is immediately useful.
    by_job_list = sorted(by_job.values(), key=lambda d: d["bytes"], reverse=True)
    orphan_files.sort(key=lambda d: d["bytes"], reverse=True)

    return jsonify({
        "download_dir": str(root),
        "total_bytes": total,
        "file_count": file_count,
        "by_job": by_job_list,
        "orphan_bytes": orphan_bytes,
        "orphan_files": orphan_files,
    })


# ----- OpenAPI schema -------------------------------------------------

# Hand-rolled because pulling in flask-openapi3 / apispec for ~25
# routes is overkill, and we want the doc to read like prose, not
# auto-generated noise. Keep this in sync with the actual handlers
# above — there's a contract test (test_api_v1.py) that asserts every
# registered ``/api/v1/*`` rule appears here.

_OPENAPI_DOC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Trove API",
        "version": "1.0",
        "description": (
            "JSON control surface for the Trove media downloader / "
            "transcript editor. Stable subset shared with the `trove` "
            "CLI and the `trove-mcp` MCP server."
        ),
    },
    "servers": [{"url": "/api/v1"}],
    "paths": {
        "/health":             {"get":  {"summary": "Liveness probe"}},
        "/jobs":               {
            "get":  {"summary": "List download jobs (paginated, filterable)",
                      "parameters": [
                          {"name": "status", "in": "query",
                           "schema": {"type": "string"},
                           "description": "Comma-separated status filter"},
                          {"name": "limit",  "in": "query",
                           "schema": {"type": "integer", "default": 100, "maximum": 500}},
                          {"name": "offset", "in": "query",
                           "schema": {"type": "integer", "default": 0}},
                          {"name": "order",  "in": "query",
                           "schema": {"type": "string", "enum": ["newest", "oldest"]}},
                      ]},
            "post": {"summary": "Submit a download",
                      "parameters": [
                          {"name": "Idempotency-Key", "in": "header",
                           "schema": {"type": "string"},
                           "description": "Opaque key; same key returns same job for 24h."},
                      ]},
        },
        "/jobs/bulk":          {"post": {"summary": "Submit many downloads"}},
        "/jobs/{job_id}":          {"get":  {"summary": "Get one job"}},
        "/jobs/{job_id}/pause":    {"post": {"summary": "Pause a running job"}},
        "/jobs/{job_id}/resume":   {"post": {"summary": "Resume a paused job"}},
        "/jobs/{job_id}/cancel":   {"post": {"summary": "Cancel a job"}},
        "/jobs/{job_id}/dismiss":  {"post": {"summary": "Drop a finished job"}},
        "/jobs/{job_id}/file":     {"get":  {"summary": "Download the produced file"}},
        "/jobs/{parent_job_id}/transcribe": {"post": {"summary": "Start transcription for a downloaded job"}},
        "/transcripts":        {"get":  {"summary": "List transcripts (paginated, filterable)"}},
        "/transcripts/search": {"get":  {"summary": "Substring search across completed transcripts",
                                          "parameters": [
                                              {"name": "q",       "in": "query", "required": True,
                                               "schema": {"type": "string"}},
                                              {"name": "limit",   "in": "query",
                                               "schema": {"type": "integer", "default": 50, "maximum": 200}},
                                              {"name": "context", "in": "query",
                                               "schema": {"type": "integer", "default": 60}},
                                          ]}},
        "/transcripts/{tid}":           {"get":  {"summary": "Get one transcript"}},
        "/transcripts/{tid}/cancel":    {"post": {"summary": "Cancel a transcribe"}},
        "/transcripts/{tid}/dismiss":   {"post": {"summary": "Drop a finished transcribe"}},
        "/transcripts/{tid}/export.{fmt}": {"get": {"summary": "Export txt/srt/vtt/json"}},
        "/storage":            {"get":  {"summary": "Disk-usage report"}},
        "/openapi.json":       {"get":  {"summary": "This document"}},
        "/events":             {"get":  {"summary": "Server-Sent Events stream of jobs+transcripts",
                                          "parameters": [
                                              {"name": "max_events", "in": "query",
                                               "schema": {"type": "integer"},
                                               "description": "Test-only termination cap."},
                                              {"name": "interval", "in": "query",
                                               "schema": {"type": "number", "default": 1.0},
                                               "description": "Poll interval in seconds (0.05-10)."},
                                          ]}},
        "/models":                       {"get":  {"summary": "List installed models"}},
        "/models/install-progress":      {"get":  {"summary": "Poll model install progress"}},
        "/models/{name}/use":            {"post": {"summary": "Mark a model as active"}},
        "/models/{name}/remove":         {"post": {"summary": "Uninstall a model"}},
        "/models/{name}/install":        {"post": {"summary": "Begin installing a model"}},
    },
    "headers_global": {
        "X-RateLimit-Limit":     "Requests allowed per 60s window",
        "X-RateLimit-Remaining": "Requests still available in window",
        "X-RateLimit-Window":    "Window length in seconds (always 60)",
        "Retry-After":           "Seconds to wait when rate-limited",
    },
}


@api_v1_bp.get("/openapi.json")
def openapi():
    return jsonify(_OPENAPI_DOC)


# ----- SSE event stream ----------------------------------------------

def _events_snapshot() -> dict:
    """Cheap full snapshot of jobs + transcripts. Diffing happens at
    the client; the server stays stateless across SSE messages."""
    return {
        "ts": time.time(),
        "jobs":        [_job_view(j) for j in _jm().snapshot_jobs()],
        "transcripts": [_tj_view(t) for t in _tm().snapshot_jobs()],
    }


@api_v1_bp.get("/events")
@token_required
def events():
    """SSE stream of job + transcript snapshots.

    Emits one ``data:`` frame per change (poll-and-diff at 1s by
    default; tunable with ``?interval=``). A heartbeat comment is
    sent every 15s while idle so proxies don't drop the connection.

    ``?max_events=N`` is a *test hook* — the generator exits cleanly
    after N data frames so pytest doesn't have to kill a long-poll.
    """
    try:
        interval = float(request.args.get("interval", "1.0"))
    except ValueError:
        interval = 1.0
    interval = max(0.05, min(10.0, interval))
    try:
        max_events = int(request.args.get("max_events", "0"))
    except ValueError:
        max_events = 0

    def gen():
        last_payload: str | None = None
        emitted = 0
        last_heartbeat = time.monotonic()
        # Always send the initial snapshot so the client has state to
        # render on connect (otherwise it has to sit through one full
        # interval of nothing).
        first = _events_snapshot()
        last_payload = json.dumps(first, sort_keys=True)
        yield f"event: snapshot\ndata: {last_payload}\n\n"
        emitted += 1
        if max_events and emitted >= max_events:
            return
        while True:
            time.sleep(interval)
            try:
                snap = _events_snapshot()
            except Exception:
                # Server tearing down — close cleanly.
                return
            payload = json.dumps(snap, sort_keys=True)
            now = time.monotonic()
            if payload != last_payload:
                yield f"event: snapshot\ndata: {payload}\n\n"
                last_payload = payload
                last_heartbeat = now
                emitted += 1
                if max_events and emitted >= max_events:
                    return
            elif now - last_heartbeat >= 15.0:
                yield ": keepalive\n\n"
                last_heartbeat = now

    resp = Response(stream_with_context(gen()), mimetype="text/event-stream")
    # Defeat proxy buffering so events arrive in real time.
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp
