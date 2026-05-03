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

import os
from threading import Lock, Thread

from flask import Blueprint, current_app, jsonify, request, send_file

import models_store
import transcribe_jobs
from jobs import JobStatus
from safety import token_or_sig_required, token_required
from util import sanitize_filename

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


# Single-flight model install (mirrors the setup-page flag). Lives at
# module scope because it's a per-process singleton, not per-app.
_install_state: dict = {
    "downloading": False, "name": None,
    "received": 0, "total": 0,
    "error": None, "done": False,
}
_install_lock = Lock()


# ----- view helpers ---------------------------------------------------

def _job_view(job) -> dict:
    return {
        "id": job.id,
        "url": job.url,
        "title": job.title,
        "status": job.status.value,
        "filename": job.filename,
        "thumbnail": job.thumbnail or None,
        "format_choice": job.format_choice,
        "downloaded_bytes": job.downloaded_bytes,
        "total_bytes": job.total_bytes,
        "speed_bps": job.speed,
        "eta_seconds": job.eta,
        "fragment_index": job.fragment_index,
        "fragment_count": job.fragment_count,
        "auto_transcribe": job.auto_transcribe,
        "error_category": job.error_category,
        "error_message": job.error_message,
    }


def _tj_view(tj) -> dict:
    return {
        "id": tj.id,
        "parent_job_id": tj.parent_job_id,
        "status": tj.status.value,
        "model_used": tj.model_used,
        "progress_pct": tj.progress_pct,
        "duration_seconds": tj.duration_seconds,
        "language_detected": tj.language_detected,
        "error_category": tj.error_category,
        "error_message": tj.error_message,
    }


def _jm():
    return current_app.extensions["trove.jobs"]


def _tm():
    return current_app.extensions["trove.transcribe"]


def _actions():
    return current_app.extensions["trove.actions"]


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
    return jsonify({"jobs": [_job_view(j) for j in _jm().snapshot_jobs()]})


@api_v1_bp.get("/jobs/<job_id>")
@token_required
def get_job(job_id):
    job = _jm().get(job_id)
    if job is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_job_view(job))


@api_v1_bp.post("/jobs")
@token_required
def submit_job():
    """Enqueue a new download. Body: ``{url, format?, format_id?, title?, auto_transcribe?}``.

    ``format`` defaults to ``"video"`` (mp4); pass ``"audio"`` for mp3.
    ``auto_transcribe=true`` triggers transcription on success when an
    active model is installed.
    """
    from safety import is_safe_url
    from runner import run_info

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "missing_url"}), 400
    if not is_safe_url(url):
        return jsonify({"error": "unsupported_url"}), 400

    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = (data.get("title") or "").strip()
    thumbnail = (data.get("thumbnail") or "").strip()
    auto_transcribe = bool(data.get("auto_transcribe"))

    # If the caller didn't supply a title, do a one-shot info probe so
    # the queue card has something useful to display. Fail soft — if
    # info probe errors, fall back to the raw URL as the title.
    if not title:
        info = run_info(url)
        if info.error_category:
            return jsonify({"error": info.error_category}), 400
        title = info.title or url
        if not thumbnail:
            thumbnail = info.thumbnail or ""

    try:
        job_id = _actions()["enqueue_download"](
            url, format_choice, format_id, title, thumbnail,
            auto_transcribe=auto_transcribe,
        )
    except RuntimeError:
        return jsonify({"error": "busy"}), 503
    job = _jm().get(job_id)
    return jsonify(_job_view(job)), 201


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
@token_or_sig_required
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
    return jsonify({"transcripts": [_tj_view(t) for t in _tm().snapshot_jobs()]})


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
@token_or_sig_required
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
