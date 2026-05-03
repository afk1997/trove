# app.py
from __future__ import annotations
import os
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file, abort

from safety import (
    is_safe_url,
    token_required,
    token_or_sig_required,
    sign_resource,
    RateLimiter,
    attach_security_headers,
)
from runner import run_info, run_download, classify_error
from jobs import JobManager, Job, JobStatus
import models_store
import machine
from threading import Thread, Lock
import transcribe_jobs
import transcriber
import transcript_io
import time as _time
from util import sanitize_filename, split_urls
from routes.transcript_editor import bp as transcript_editor_bp


def _resolve_download_dir() -> Path:
    """Resolve the on-disk download root.

    Read at create_app() time (NOT at import time) so tests that set
    ``TROVE_DOWNLOAD_DIR`` per-fixture get isolated trees instead of
    accidentally sharing the real ``./downloads`` directory.
    """
    return Path(os.environ.get("TROVE_DOWNLOAD_DIR")
                or (Path(__file__).parent / "downloads"))


DOWNLOAD_DIR = _resolve_download_dir()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

JOB_TTL = int(os.environ.get("TROVE_JOB_TTL_SECONDS", "3600"))
MAX_WORKERS = int(os.environ.get("TROVE_MAX_WORKERS", "4"))
RATE_LIMIT_PER_MIN = int(os.environ.get("TROVE_RATE_LIMIT", "30"))
# Hard cap on URLs accepted in one /api/batch-download request. Each URL
# triggers a synchronous run_info() (~1-2s) and then a queued download,
# so very large pastes would block the request thread for minutes and
# flood the queue. 50 keeps the worst case under ~2 minutes and the
# response payload under ~1 MB. The hero form mirrors the cap so users
# get an inline error before they hit submit.
BATCH_MAX_URLS = int(os.environ.get("TROVE_BATCH_MAX_URLS", "50"))


def create_app() -> Flask:
    app = Flask(__name__)
    attach_security_headers(app)
    # Expose sign_resource() to Jinja so templates can mint signed
    # links for routes reached via direct browser navigation (anchor
    # clicks, <video src>) where the Authorization header isn't sent.
    app.jinja_env.globals["sign_resource"] = sign_resource

    rate_limiter = RateLimiter(rate=RATE_LIMIT_PER_MIN, per_seconds=60)
    # Prefer the module-level DOWNLOAD_DIR so existing tests can use
    # ``monkeypatch.setattr(app, "DOWNLOAD_DIR", ...)``. Fall back to
    # the env-var-aware resolver only if the module global was cleared.
    download_dir = DOWNLOAD_DIR if DOWNLOAD_DIR is not None else _resolve_download_dir()
    download_dir.mkdir(parents=True, exist_ok=True)
    job_manager = JobManager(
        max_workers=MAX_WORKERS,
        ttl_seconds=JOB_TTL,
        store_path=download_dir / "jobs.json",
    )
    app.extensions["trove.jobs"] = job_manager
    app.extensions["trove.download_dir"] = download_dir
    # Expose the batch cap to templates so the hero form can render an
    # inline counter and pre-flight check that mirror the server limit.
    app.jinja_env.globals["BATCH_MAX_URLS"] = BATCH_MAX_URLS
    app.extensions["trove.rate_limiter"] = rate_limiter

    transcribe_manager = transcribe_jobs.TranscribeJobManager(
        max_workers=1,
        store_path=download_dir / "transcribe_jobs.json",
    )
    app.extensions["trove.transcribe"] = transcribe_manager

    # Per-app transcript-edit lock state (keyed by transcript base path).
    # Lives on app.extensions so the transcript-editor blueprint can
    # access it via current_app and so multiple test apps in the same
    # process don't share locks.
    app.extensions["trove.txn_locks"] = {}
    app.extensions["trove.txn_locks_guard"] = Lock()

    # Register split-out blueprints. See routes/__init__.py for why.
    app.register_blueprint(transcript_editor_bp)
    from routes.api_v1 import api_v1_bp
    app.register_blueprint(api_v1_bp)

    # Sweeper has to start AFTER both managers exist because the
    # keep_predicate references transcribe_manager — without it the
    # TTL sweep would unlink the source media for every completed
    # transcript after one idle hour, silently 404-ing the transcript
    # page and dropping the download.
    #
    # Important: walk ALL children, not just the most recent one. A
    # parent may have an older DONE transcribe AND a newer ERROR
    # transcribe (e.g. user re-ran the transcribe with a bigger model
    # and it failed). The older DONE result is still valid and must
    # keep the parent alive. Using ``get_by_parent`` (which returns
    # only the latest) would silently drop those.
    _KEEP_STATUSES = {
        transcribe_jobs.TranscribeStatus.QUEUED,
        transcribe_jobs.TranscribeStatus.RUNNING,
        transcribe_jobs.TranscribeStatus.DONE,
    }

    def _has_active_or_done_transcribe(parent_job) -> bool:
        for tj in transcribe_manager.snapshot_jobs():
            if tj.parent_job_id == parent_job.id and tj.status in _KEEP_STATUSES:
                return True
        return False

    job_manager.start_sweeper(
        interval_seconds=300,
        keep_predicate=_has_active_or_done_transcribe,
    )

    # Idempotent HTMX/JS status polls — exempted from the per-IP rate
    # limit because they fire every 1-2s while a page is open and would
    # otherwise blow the budget within ~30s, 429-ing every subsequent
    # user action (e.g. clicking "pick this model" on the setup page).
    # All exempt paths are read-only GETs that return HTML/JSON status.
    _POLL_EXEMPT_PREFIXES = (
        "/api/status/",
        "/api/status-card/",
        "/api/transcribe/setup-progress",
    )

    def _is_poll_exempt() -> bool:
        if request.method != "GET":
            return False
        path = request.path
        if any(path.startswith(p) for p in _POLL_EXEMPT_PREFIXES):
            return True
        # /api/transcribe/<id>/status — match on suffix to avoid pinning
        # to a specific id format.
        if path.startswith("/api/transcribe/") and path.endswith("/status"):
            return True
        # Cheap v1 status/poll GETs that the CLI + MCP server hammer
        # while waiting on a job. We deliberately do NOT exempt the
        # whole /api/v1/* prefix — file streams (`/jobs/<id>/file`)
        # and export downloads (`/transcripts/<id>/export.*`) are
        # bandwidth-heavy and stay rate-limited so a token-less
        # deployment isn't a free egress vector.
        if path == "/api/v1/health":
            return True
        if path == "/api/v1/jobs" or path == "/api/v1/transcripts":
            return True
        if path == "/api/v1/models" or path == "/api/v1/models/install-progress":
            return True
        # New v1 read-only endpoints used by the CLI/MCP. All cheap +
        # idempotent so they're safe to exempt from per-IP rate
        # limiting (same reasoning as /jobs and /transcripts above).
        if path in (
            "/api/v1/storage",
            "/api/v1/openapi.json",
            "/api/v1/events",
        ) or path.startswith("/api/v1/transcripts/search"):
            return True
        # /api/v1/jobs/<id> and /api/v1/transcripts/<id> — single-resource
        # status reads. Match by prefix-and-no-slash-after-id so we don't
        # accidentally exempt /jobs/<id>/file or /transcripts/<id>/export.*.
        for prefix in ("/api/v1/jobs/", "/api/v1/transcripts/"):
            if path.startswith(prefix) and "/" not in path[len(prefix):]:
                return True
        return False

    @app.before_request
    def _rate_limit():
        if not request.path.startswith("/api/"):
            return None
        # Stash IP on g so the after-request hook can attach
        # X-RateLimit-* headers without recomputing.
        from flask import g as _g
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        _g.trove_rl_ip = ip
        if _is_poll_exempt():
            return None
        if not rate_limiter.allow(ip):
            remaining, retry_after = rate_limiter.remaining(ip)
            resp = jsonify({"error": "rate_limited", "retry_after": round(retry_after, 1)})
            resp.status_code = 429
            resp.headers["X-RateLimit-Limit"] = str(rate_limiter.rate)
            resp.headers["X-RateLimit-Remaining"] = "0"
            resp.headers["X-RateLimit-Window"] = "60"
            resp.headers["Retry-After"] = str(max(1, int(retry_after) + 1))
            return resp
        return None

    @app.after_request
    def _rate_limit_headers(resp):
        # Only attach to /api/* responses, and only when the
        # before-request hook actually computed an IP for this request
        # (i.e. skip static, WS, etc.).
        from flask import g as _g
        if not request.path.startswith("/api/"):
            return resp
        ip = getattr(_g, "trove_rl_ip", None)
        if not ip:
            return resp
        try:
            remaining, retry_after = rate_limiter.remaining(ip)
        except Exception:
            return resp
        resp.headers["X-RateLimit-Limit"] = str(rate_limiter.rate)
        resp.headers["X-RateLimit-Remaining"] = str(min(remaining, rate_limiter.rate))
        resp.headers["X-RateLimit-Window"] = "60"
        if retry_after > 0 and "Retry-After" not in resp.headers:
            resp.headers["Retry-After"] = str(max(1, int(retry_after) + 1))
        return resp

    @app.get("/")
    def index():
        # Rehydrate persisted jobs (paused/done/error) into the queue so the
        # user can resume / re-download / inspect them after a restart.
        # CANCELLED jobs are already dropped at load time.
        initial_cards = []
        for j in job_manager.snapshot_jobs():
            if j.status == JobStatus.CANCELLED:
                continue
            initial_cards.append(_card_view(j))
        return render_template("index.html", initial_cards=initial_cards)

    # --- JSON API (stable, scriptable) -------------------------------------

    @app.post("/api/info")
    @token_required
    def api_info():
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not is_safe_url(url):
            return jsonify({"error": "unsupported_url"}), 400
        result = run_info(url)
        if result.error_category:
            return jsonify({"error": result.error_category}), 400
        return jsonify({
            "title": result.title,
            "thumbnail": result.thumbnail,
            "duration": result.duration,
            "uploader": result.uploader,
            "formats": result.formats,
        })

    @app.post("/api/download")
    @token_required
    def api_download():
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        format_choice = data.get("format", "video")
        format_id = data.get("format_id")
        title = (data.get("title") or "").strip()
        if not is_safe_url(url):
            return jsonify({"error": "unsupported_url"}), 400
        try:
            job_id = _enqueue_download(url, format_choice, format_id, title)
        except RuntimeError:
            return jsonify({"error": "busy"}), 503
        return jsonify({"job_id": job_id})

    @app.get("/api/status/<job_id>")
    @token_required
    def api_status(job_id):
        job = job_manager.get(job_id)
        if job is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify({
            "status": job.status.value,
            "category": job.error_category,
            "filename": job.filename,
        })

    @app.get("/api/file/<job_id>")
    @token_or_sig_required
    def api_file(job_id):
        job = job_manager.get(job_id)
        if job is None or job.status != JobStatus.DONE or not job.file_path:
            return jsonify({"error": "not_ready"}), 404
        return send_file(job.file_path, as_attachment=True, download_name=job.filename or "download")

    # --- HTML fragment endpoints (htmx) ------------------------------------

    def _form_bool(name: str) -> bool:
        """Parse an HTML form checkbox value as a bool.

        htmx + the standard browser form post both send the input's
        ``value`` attribute (default "on") only when the box is checked,
        and omit the field entirely when unchecked. So presence == True.
        We also accept "1"/"true"/"yes" for callers that POST JSON-shaped
        form data.
        """
        raw = (request.form.get(name) or "").strip().lower()
        return raw in {"on", "1", "true", "yes"}

    @app.post("/api/info-card")
    @token_required
    def api_info_card():
        url = (request.form.get("url") or "").strip()
        format_choice = request.form.get("format", "video")
        auto_transcribe = _form_bool("auto_transcribe")
        if not is_safe_url(url):
            return render_template("partials/card.html", card={
                "kind": "error",
                "url": url,
                "category": "unsupported_url",
            }), 400
        result = run_info(url)
        if result.error_category:
            return render_template("partials/card.html", card={
                "kind": "error",
                "url": url,
                "category": result.error_category,
            }), 400
        return render_template("partials/card.html", card={
            "kind": "ready",
            "url": url,
            "title": result.title,
            "thumbnail": result.thumbnail,
            "uploader": result.uploader,
            "duration": result.duration,
            "format": format_choice,
            "formats": result.formats,
            "auto_transcribe": auto_transcribe,
        })

    @app.post("/api/download-card")
    @token_required
    def api_download_card():
        url = (request.form.get("url") or "").strip()
        format_choice = request.form.get("format", "video")
        format_id = request.form.get("format_id") or None
        title = (request.form.get("title") or "").strip()
        thumbnail = (request.form.get("thumbnail") or "").strip()
        auto_transcribe = _form_bool("auto_transcribe")
        if not is_safe_url(url):
            return render_template("partials/card.html", card={
                "kind": "error", "url": url, "category": "unsupported_url",
            }), 400
        try:
            job_id = _enqueue_download(
                url, format_choice, format_id, title, thumbnail,
                auto_transcribe=auto_transcribe,
            )
        except RuntimeError:
            return render_template("partials/card.html", card={
                "kind": "error", "url": url, "category": "busy",
            }), 503
        job = job_manager.get(job_id)
        return render_template("partials/card.html", card=_card_view(job))

    @app.post("/api/batch-download")
    @token_required
    def api_batch_download():
        """Accept a paste-blob of URLs; enqueue each as a download.

        Skips the per-URL `ready` card / format picker — uses the global
        format toggle (mp4 vs mp3, default quality) and optionally
        auto-transcribes each on completion. Renders one card fragment
        per URL, concatenated, so htmx ``afterbegin`` swaps them all
        into the queue at once. Order is reversed so the first URL the
        user pasted ends up at the top of the queue.
        """
        raw = request.form.get("urls") or request.form.get("url") or ""
        format_choice = request.form.get("format", "video")
        auto_transcribe = _form_bool("auto_transcribe")
        urls = split_urls(raw)
        if not urls:
            return render_template("partials/card.html", card={
                "kind": "error", "url": "", "category": "unsupported_url",
            }), 400
        if len(urls) > BATCH_MAX_URLS:
            return render_template("partials/card.html", card={
                "kind": "error", "url": "",
                "category": "too_many_urls",
                "detail": {"count": len(urls), "max": BATCH_MAX_URLS},
            }), 413

        rendered: list[str] = []
        for url in urls:
            if not is_safe_url(url):
                rendered.append(render_template("partials/card.html", card={
                    "kind": "error", "url": url, "category": "unsupported_url",
                }))
                continue
            info = run_info(url)
            if info.error_category:
                rendered.append(render_template("partials/card.html", card={
                    "kind": "error", "url": url, "category": info.error_category,
                }))
                continue
            try:
                job_id = _enqueue_download(
                    url, format_choice, None,
                    info.title or "", info.thumbnail or "",
                    auto_transcribe=auto_transcribe,
                )
            except RuntimeError:
                rendered.append(render_template("partials/card.html", card={
                    "kind": "error", "url": url, "category": "busy",
                }))
                continue
            job = job_manager.get(job_id)
            rendered.append(render_template("partials/card.html", card=_card_view(job)))

        # htmx ``afterbegin`` inserts the response HTML verbatim at the
        # start of the target — the first fragment in the response ends
        # up at the top of the queue. So we keep paste order as-is.
        return "".join(rendered)

    @app.get("/api/status-card/<job_id>")
    @token_required
    def api_status_card(job_id):
        job = job_manager.get(job_id)
        if job is None:
            return "", 404
        # Always return the rendered card so progress updates are visible on every poll.
        return render_template("partials/card.html", card=_card_view(job))

    @app.post("/api/job/<job_id>/cancel")
    @token_required
    def api_job_cancel(job_id):
        ok = job_manager.cancel(job_id)
        if not ok:
            return "", 404
        job = job_manager.get(job_id)
        if job is None:
            return "", 200
        return render_template("partials/card.html", card=_card_view(job))

    @app.post("/api/job/<job_id>/dismiss")
    @token_required
    def api_job_dismiss(job_id):
        ok = job_manager.dismiss(job_id)
        if not ok:
            return "", 404
        # Empty body + outerHTML swap on the client → card removed from the DOM.
        return "", 200

    @app.post("/api/job/<job_id>/pause")
    @token_required
    def api_job_pause(job_id):
        ok = job_manager.pause(job_id)
        if not ok:
            return "", 404
        job = job_manager.get(job_id)
        if job is None:
            return "", 404
        return render_template("partials/card.html", card=_card_view(job))

    @app.post("/api/job/<job_id>/resume")
    @token_required
    def api_job_resume(job_id):
        job = job_manager.get(job_id)
        if job is None:
            return "", 404

        # Reconstruct the work thunk from the persisted resume_args.
        url = job.url
        format_choice = job.format_choice
        format_id = job.format_id
        title = job.title
        thumbnail = job.thumbnail
        out_template = job.out_template or str(DOWNLOAD_DIR / f"{job.id}.%(ext)s")

        def _work(j: Job):
            j.thumbnail = thumbnail
            j.format_choice = format_choice
            j.format_id = format_id
            j.out_template = out_template

            def _on_progress(downloaded, total, speed, eta, frag_idx, frag_count):
                j.downloaded_bytes = downloaded
                j.total_bytes = total
                j.speed = speed
                j.eta = eta
                j.fragment_index = frag_idx
                j.fragment_count = frag_count

            def _register_proc(popen):
                j.process = popen

            result = run_download(
                url=url,
                out_template=out_template,
                format_choice=format_choice,
                format_id=format_id,
                progress_cb=_on_progress,
                register_process=_register_proc,
                was_paused_check=lambda: j._was_paused,
            )
            if result.error_category:
                if not j._was_paused:
                    j.status = JobStatus.ERROR
                    j.error_category = result.error_category
                    j.error_message = result.error_raw
                return
            ext = os.path.splitext(result.file_path)[1] if result.file_path else ""
            j.file_path = result.file_path
            j.filename = sanitize_filename(title, ext)
            _try_auto_transcribe(j)

        ok = job_manager.resume(job_id, target=_work)
        if not ok:
            return "", 404
        job = job_manager.get(job_id)
        return render_template("partials/card.html", card=_card_view(job))

    # --- Transcribe setup -------------------------------------------------

    # In-process state for the model download. One download at a time.
    transcribe_setup_state = {
        "downloading": False,
        "model_name": None,
        "received": 0,
        "total": 0,
        "error": None,
        "done": False,
    }
    transcribe_setup_lock = Lock()

    def _setup_state_snapshot():
        with transcribe_setup_lock:
            return dict(transcribe_setup_state)

    @app.get("/transcribe/setup")
    def transcribe_setup():
        active = models_store.get_active()
        info = machine.probe()
        models_meta = []
        for name, meta in models_store.KNOWN_MODELS.items():
            models_meta.append({
                "name": name,
                "label": meta["label"],
                "size_bytes": meta["size_bytes"],
                "hf_url": meta["hf_url"],
                "sha256": meta["sha256"],
                "stars": meta["stars"],
                "multilingual": meta["multilingual"],
                "rtf": machine.speed_estimate(name),
                "is_active": name == active,
                "is_installed": name in models_store.list_installed(),
            })
        return render_template(
            "transcribe_setup.html",
            machine_info=info,
            models=models_meta,
            active=active,
            settings_mode=active is not None,
            setup_state=_setup_state_snapshot(),
        )

    @app.post("/api/transcribe/setup-model")
    @token_required
    def api_transcribe_setup_model():
        name = request.form.get("name") or (request.get_json(silent=True) or {}).get("name", "")
        if name not in models_store.KNOWN_MODELS:
            return jsonify({"error": "unknown_model"}), 400
        with transcribe_setup_lock:
            if transcribe_setup_state["downloading"]:
                return jsonify({"error": "busy"}), 409
            transcribe_setup_state.update({
                "downloading": True, "model_name": name,
                "received": 0, "total": models_store.KNOWN_MODELS[name]["size_bytes"],
                "error": None, "done": False,
            })

        def _progress(rec, total):
            with transcribe_setup_lock:
                transcribe_setup_state["received"] = rec
                transcribe_setup_state["total"] = total

        def _worker():
            try:
                models_store.download(name, progress_cb=_progress, verify=True)
                models_store.set_active(name)
                with transcribe_setup_lock:
                    transcribe_setup_state["downloading"] = False
                    transcribe_setup_state["done"] = True
            except Exception as e:
                with transcribe_setup_lock:
                    transcribe_setup_state["downloading"] = False
                    transcribe_setup_state["error"] = type(e).__name__ + ": " + str(e)

        Thread(target=_worker, daemon=True, name="trove-model-download").start()
        return ("", 202)

    @app.post("/api/transcribe/setup-model/remove")
    @token_required
    def api_transcribe_setup_model_remove():
        name = request.form.get("name") or (request.get_json(silent=True) or {}).get("name", "")
        if name not in models_store.KNOWN_MODELS:
            return jsonify({"error": "unknown_model"}), 400
        models_store.remove(name)
        return ("", 200)

    @app.get("/api/transcribe/setup-progress")
    @token_required
    def api_transcribe_setup_progress():
        return render_template(
            "partials/transcribe_setup_progress.html",
            state=_setup_state_snapshot(),
        )

    # --- Transcribe lifecycle --------------------------------------------

    @app.post("/api/transcribe/<parent_job_id>/start")
    @token_required
    def api_transcribe_start(parent_job_id):
        # Need an active model installed
        model_path = models_store.get_active_path()
        if model_path is None:
            # First-time consent modal — caller swaps it into the page
            return render_template("partials/transcribe_consent.html"), 200

        parent = job_manager.get(parent_job_id)
        if parent is None or parent.status != JobStatus.DONE or not parent.file_path:
            return jsonify({"error": "parent_not_done"}), 404

        # Idempotent: if a transcribe is already running or queued for this
        # parent, return its current action partial instead of submitting
        # another. Prevents the double-click race where two threads write
        # the same .wav and clobber each other's outputs.
        existing = transcribe_manager.get_by_parent(parent_job_id)
        if existing and existing.status in (
            transcribe_jobs.TranscribeStatus.QUEUED,
            transcribe_jobs.TranscribeStatus.RUNNING,
        ):
            return render_template(
                "partials/transcribe_action.html", tj=existing, parent=parent,
            )

        media_path = parent.file_path
        base_no_ext = os.path.splitext(media_path)[0]  # downloads/<id>
        wav_path = base_no_ext + ".wav"

        tjid = transcribe_manager.submit(
            parent_job_id=parent_job_id,
            model_path=str(model_path),
            target=_build_transcribe_target(media_path, base_no_ext, wav_path),
        )
        tj = transcribe_manager.get(tjid)
        return render_template("partials/transcribe_action.html", tj=tj, parent=parent)

    def _cleanup_orphan_transcribe(transcribe_id):
        """Cancel + dismiss an orphan transcribe job whose parent is gone.

        Cancel flips non-terminal status to CANCELLED; dismiss then accepts
        CANCELLED and pops it. Two-step because dismiss refuses non-terminal.
        """
        transcribe_manager.cancel(transcribe_id)
        transcribe_manager.dismiss(transcribe_id)

    @app.get("/api/transcribe/<transcribe_id>/status")
    @token_required
    def api_transcribe_status(transcribe_id):
        tj = transcribe_manager.get(transcribe_id)
        if tj is None:
            return "", 404
        # If the parent media job has been TTL-swept, the transcribe job
        # is orphaned — clean it up and 404 the polling client.
        parent = job_manager.get(tj.parent_job_id)
        if parent is None:
            _cleanup_orphan_transcribe(transcribe_id)
            return "", 404
        return render_template("partials/transcribe_action.html", tj=tj, parent=parent)

    @app.post("/api/transcribe/<transcribe_id>/cancel")
    @token_required
    def api_transcribe_cancel(transcribe_id):
        tj = transcribe_manager.get(transcribe_id)
        if tj is None:
            return "", 404
        transcribe_manager.cancel(transcribe_id)
        parent = job_manager.get(tj.parent_job_id)
        if parent is None:
            _cleanup_orphan_transcribe(transcribe_id)
            return "", 404
        return render_template("partials/transcribe_action.html", tj=tj, parent=parent)

    @app.post("/api/transcribe/<transcribe_id>/dismiss")
    @token_required
    def api_transcribe_dismiss(transcribe_id):
        ok = transcribe_manager.dismiss(transcribe_id)
        if not ok:
            return "", 404
        return "", 200

    @app.get("/api/transcribe/<transcribe_id>/export.<fmt>")
    @token_or_sig_required
    def api_transcribe_export(transcribe_id, fmt):
        if fmt not in {"txt", "srt", "vtt"}:
            return abort(404)
        tj = transcribe_manager.get(transcribe_id)
        if tj is None or tj.status != transcribe_jobs.TranscribeStatus.DONE:
            return abort(404)
        parent = job_manager.get(tj.parent_job_id)
        if parent is None or not parent.file_path:
            return abort(404)
        base = os.path.splitext(parent.file_path)[0]
        path = base + "." + fmt
        if not os.path.exists(path):
            return abort(404)
        mime = {
            "txt": "text/plain; charset=utf-8",
            "srt": "application/x-subrip",
            "vtt": "text/vtt; charset=utf-8",
        }[fmt]
        download_name = sanitize_filename(parent.title or "transcript", "." + fmt)
        return send_file(path, mimetype=mime, as_attachment=True, download_name=download_name)

    def _resolve_transcribe_paths(transcribe_id):
        """Return (tj, parent, base_path) or (None, None, None) for a 404."""
        tj = transcribe_manager.get(transcribe_id)
        if tj is None or tj.status != transcribe_jobs.TranscribeStatus.DONE:
            return None, None, None
        parent = job_manager.get(tj.parent_job_id)
        if parent is None or not parent.file_path:
            return None, None, None
        base = os.path.splitext(parent.file_path)[0]
        if not os.path.exists(base + ".words.json"):
            return None, None, None
        return tj, parent, base

    @app.get("/transcript/<transcribe_id>")
    @token_or_sig_required
    def transcript_view(transcribe_id):
        tj, parent, base = _resolve_transcribe_paths(transcribe_id)
        if tj is None:
            return abort(404)

        # transcript_io.load auto-migrates v1 files to v2 + writes a backup.
        data = transcript_io.load(base + ".words.json")

        ext = os.path.splitext(parent.file_path)[1].lower()
        is_audio = ext in {".mp3", ".m4a", ".ogg", ".wav", ".flac"}

        # Sign the media URL so the <video src> works even when TROVE_TOKEN
        # is set (browsers can't attach Authorization headers to media src).
        sig = sign_resource(parent.id)
        media_url = f"/api/file/{parent.id}"
        if sig:
            media_url = f"{media_url}?sig={sig}"

        return render_template(
            "transcript.html",
            tj=tj,
            parent=parent,
            data=data,
            is_audio=is_audio,
            media_url=media_url,
            was_edited=bool(data.get("edited_at")),
        )

    # Transcript editor mutation endpoints (word/segment/speaker/bookmark/
    # highlight/note/title/find-replace/reviewed/export-selection) live in
    # routes/transcript_editor.py and were registered above as a Blueprint.
    # --- helpers -----------------------------------------------------------

    def _build_transcribe_target(media_path: str, base_no_ext: str, wav_path: str):
        """Return the per-transcribe ``_work(tj, *, model_path)`` closure.

        Extracted from api_transcribe_start so the auto-transcribe path
        (triggered from inside the download worker on success) can reuse
        the exact same body — extract → transcribe → diarize → artifacts
        with consistent cancel semantics and WAV cleanup.
        """
        def _work(tj, *, model_path):
            def _register_ffmpeg(proc):
                # Stash the live ffmpeg Popen on the TranscribeJob so the
                # /cancel endpoint (which calls TranscribeJobManager.cancel)
                # can kill it mid-extract instead of waiting for it to
                # complete. Cleared (set to None) when extract returns.
                tj.process_handle = proc

            try:
                # 1. Extract audio
                try:
                    transcriber.extract_audio(
                        media_path, wav_path,
                        cancel_check=lambda: tj._cancel_flag,
                        register_proc=_register_ffmpeg,
                    )
                except RuntimeError as e:
                    # extract_audio raises RuntimeError("cancelled") when the
                    # user hit cancel during ffmpeg — treat as a clean abort.
                    if str(e) == "cancelled" or tj._cancel_flag:
                        return
                    raise
                if tj._cancel_flag: return
                transcribe_manager.update_progress(tj.id, 5)

                # 2. Transcribe
                result = transcriber.run_transcribe(
                    audio_path=wav_path,
                    model_path=model_path,
                    progress_cb=lambda pct: transcribe_manager.update_progress(tj.id, pct),
                    cancel_check=lambda: tj._cancel_flag,
                )
                if result.error == "cancelled" or tj._cancel_flag:
                    return
                if result.error:
                    tj.status = transcribe_jobs.TranscribeStatus.ERROR
                    tj.error_category = "transcribe_error"
                    tj.error_message = result.error
                    return

                # 2.5 Diarize (best-effort; failure NEVER kills the transcribe).
                # Only runs when TROVE_DIARIZATION=on AND the optional deps are
                # installed. Default behavior is unchanged from pre-v3.1.
                try:
                    import diarizer
                    if diarizer.available():
                        chunks = diarizer.diarize(audio_path=wav_path)
                        if chunks:
                            transcriber.apply_speakers(result, chunks)
                except Exception as e:
                    app.logger.warning("diarization skipped: %s", e)

                # 3. Write artifacts
                transcriber.write_artifacts(result, base_no_ext)
                tj.duration_seconds = result.duration
                tj.language_detected = result.language
            finally:
                # Always remove the temp WAV — even on cancel/error/exception.
                # The success path used to clean it up, but cancel/error early-
                # returned and leaked a multi-MB file per aborted transcribe.
                try:
                    if os.path.exists(wav_path):
                        os.remove(wav_path)
                except OSError:
                    pass

        return _work

    def _try_auto_transcribe(parent: Job) -> None:
        """Submit a transcribe for a just-completed download, if requested.

        Called from inside the download worker AFTER ``job.file_path`` is
        set and BEFORE the worker returns (i.e. before JobManager flips
        status to DONE). We deliberately do not check ``parent.status`` —
        the caller has just confirmed a successful download and any
        cancel/error path returns earlier without invoking us.

        Degrades gracefully:
        - No active model installed → set ``_auto_transcribe_hint`` so
          the DONE card can render a "set up a model" link, then return.
        - A transcribe for this parent is already queued/running/done →
          no-op (idempotent; protects against double-fires).
        """
        if not parent.auto_transcribe or not parent.file_path:
            return
        # Cancel race: /api/job/<id>/cancel can flip status to CANCELLED
        # while we're inside _work. The download still wrote file_path
        # before the kill landed, but the user clearly doesn't want the
        # follow-up transcribe. Same for ERROR (a late error category set
        # by the runner). PAUSED is benign — pause-then-success races
        # legitimately become DONE in JobManager._run, which is the
        # behavior we want.
        if parent.status in (JobStatus.CANCELLED, JobStatus.ERROR):
            return
        model_path = models_store.get_active_path()
        if model_path is None:
            parent._auto_transcribe_hint = "no_active_model"
            return
        existing = transcribe_manager.get_by_parent(parent.id)
        if existing and existing.status in (
            transcribe_jobs.TranscribeStatus.QUEUED,
            transcribe_jobs.TranscribeStatus.RUNNING,
            transcribe_jobs.TranscribeStatus.DONE,
        ):
            return
        base_no_ext = os.path.splitext(parent.file_path)[0]
        wav_path = base_no_ext + ".wav"
        try:
            transcribe_manager.submit(
                parent_job_id=parent.id,
                model_path=str(model_path),
                target=_build_transcribe_target(parent.file_path, base_no_ext, wav_path),
            )
        except Exception as e:
            # Never let a transcribe-submit failure poison the download
            # job — it's an opportunistic add-on, not the core contract.
            app.logger.warning("auto-transcribe submit failed for %s: %s", parent.id, e)

    def _enqueue_download(
        url: str, format_choice: str, format_id, title: str,
        thumbnail: str = "", *, auto_transcribe: bool = False,
    ) -> str:
        def _work(job: Job):
            job.thumbnail = thumbnail
            job.format_choice = format_choice
            job.format_id = format_id
            out_template = str(DOWNLOAD_DIR / f"{job.id}.%(ext)s")
            job.out_template = out_template

            def _on_progress(downloaded, total, speed, eta, frag_idx, frag_count):
                job.downloaded_bytes = downloaded
                job.total_bytes = total
                job.speed = speed
                job.eta = eta
                job.fragment_index = frag_idx
                job.fragment_count = frag_count

            def _register_proc(popen):
                job.process = popen

            result = run_download(
                url=url,
                out_template=out_template,
                format_choice=format_choice,
                format_id=format_id,
                progress_cb=_on_progress,
                register_process=_register_proc,
                was_paused_check=lambda: job._was_paused,
            )
            if result.error_category:
                if not job._was_paused:
                    job.status = JobStatus.ERROR
                    job.error_category = result.error_category
                    job.error_message = result.error_raw
                return
            ext = os.path.splitext(result.file_path)[1] if result.file_path else ""
            job.file_path = result.file_path
            job.filename = sanitize_filename(title, ext)
            _try_auto_transcribe(job)

        return job_manager.submit(
            target=_work, title=title, url=url, auto_transcribe=auto_transcribe,
        )

    def _card_view(job: Job) -> dict:
        # Bytes-based percent when we know the total. HLS streams (YouTube) leave
        # total_bytes at 0 — fall back to fragment ratio so the bar still moves.
        percent = 0
        if job.total_bytes > 0:
            percent = min(100, int(job.downloaded_bytes / job.total_bytes * 100))
        elif job.fragment_count > 0 and job.fragment_index > 0:
            percent = min(100, int(job.fragment_index / job.fragment_count * 100))
        view = {
            "kind": job.status.value,
            "id": job.id,
            "title": job.title or "Untitled",
            "url": job.url,
            "thumbnail": job.thumbnail or "",
            "filename": job.filename,
            "category": job.error_category,
            "downloaded_bytes": job.downloaded_bytes,
            "total_bytes": job.total_bytes,
            "speed": job.speed,
            "eta": job.eta,
            "fragment_index": job.fragment_index,
            "fragment_count": job.fragment_count,
            "percent": percent,
        }
        # Inject transcribe row HTML for DONE cards
        if job.status == JobStatus.DONE:
            tj = transcribe_manager.get_by_parent(job.id)
            view["transcribe_partial"] = render_template(
                "partials/transcribe_action.html",
                tj=tj,
                parent=job,
            )
            # Surface the "auto-transcribe wanted but no active model"
            # hint so the user knows why a transcribe didn't fire and
            # can click through to /transcribe/setup. The hint is a
            # transient flag set inside the download worker; it doesn't
            # survive a server restart.
            if getattr(job, "_auto_transcribe_hint", None):
                view["auto_transcribe_hint"] = job._auto_transcribe_hint
        return view

    # --- v1 action helpers -----------------------------------------------
    # The /api/v1 blueprint reaches into these via app.extensions so the
    # CLI + MCP server don't need to duplicate the work-thunk construction
    # that lives inside the legacy HTML endpoints. Same in-process state,
    # same managers, same locks — just a JSON-shaped surface on top.

    def _v1_resume_job(job_id: str) -> bool:
        job = job_manager.get(job_id)
        if job is None:
            return False
        url = job.url
        format_choice = job.format_choice
        format_id = job.format_id
        title = job.title
        thumbnail = job.thumbnail
        out_template = job.out_template or str(DOWNLOAD_DIR / f"{job.id}.%(ext)s")

        def _work(j: Job):
            j.thumbnail = thumbnail
            j.format_choice = format_choice
            j.format_id = format_id
            j.out_template = out_template

            def _on_progress(downloaded, total, speed, eta, frag_idx, frag_count):
                j.downloaded_bytes = downloaded
                j.total_bytes = total
                j.speed = speed
                j.eta = eta
                j.fragment_index = frag_idx
                j.fragment_count = frag_count

            def _register_proc(popen):
                j.process = popen

            result = run_download(
                url=url,
                out_template=out_template,
                format_choice=format_choice,
                format_id=format_id,
                progress_cb=_on_progress,
                register_process=_register_proc,
                was_paused_check=lambda: j._was_paused,
            )
            if result.error_category:
                if not j._was_paused:
                    j.status = JobStatus.ERROR
                    j.error_category = result.error_category
                    j.error_message = result.error_raw
                return
            ext = os.path.splitext(result.file_path)[1] if result.file_path else ""
            j.file_path = result.file_path
            j.filename = sanitize_filename(title, ext)
            _try_auto_transcribe(j)

        return job_manager.resume(job_id, target=_work)

    def _v1_start_transcribe(parent_job_id: str) -> str | None:
        """Submit a transcribe for an already-downloaded clip. Returns
        the transcribe id, or None if preconditions fail (the v1 route
        guards parent-state and active-model presence before calling)."""
        parent = job_manager.get(parent_job_id)
        if parent is None or parent.status != JobStatus.DONE or not parent.file_path:
            return None
        model_path = models_store.get_active_path()
        if model_path is None:
            return None
        media_path = parent.file_path
        base_no_ext = os.path.splitext(media_path)[0]
        wav_path = base_no_ext + ".wav"
        return transcribe_manager.submit(
            parent_job_id=parent_job_id,
            model_path=str(model_path),
            target=_build_transcribe_target(media_path, base_no_ext, wav_path),
        )

    app.extensions["trove.actions"] = {
        "enqueue_download": _enqueue_download,
        "resume_job": _v1_resume_job,
        "start_transcribe": _v1_start_transcribe,
    }

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    app = create_app()
    app.run(host=host, port=port)
