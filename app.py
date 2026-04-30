# app.py
from __future__ import annotations
import os
import re
import unicodedata
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file, abort

from safety import (
    is_safe_url,
    token_required,
    RateLimiter,
    attach_security_headers,
)
from runner import run_info, run_download, classify_error
from jobs import JobManager, Job, JobStatus


DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

JOB_TTL = int(os.environ.get("TROVE_JOB_TTL_SECONDS", "3600"))
MAX_WORKERS = int(os.environ.get("TROVE_MAX_WORKERS", "4"))
RATE_LIMIT_PER_MIN = int(os.environ.get("TROVE_RATE_LIMIT", "30"))


def sanitize_filename(title: str, ext: str) -> str:
    """Produce a safe download_name. Falls back to a placeholder when empty."""
    if not title:
        return f"trove-download{ext}"
    # NFC normalize, drop control chars and bad filename chars, trim length.
    s = unicodedata.normalize("NFC", title)
    s = "".join(ch for ch in s if ch.isprintable())
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    s = s.strip().strip(".")
    s = s[:150].strip()
    return f"{s}{ext}" if s else f"trove-download{ext}"


def create_app() -> Flask:
    app = Flask(__name__)
    attach_security_headers(app)

    rate_limiter = RateLimiter(rate=RATE_LIMIT_PER_MIN, per_seconds=60)
    job_manager = JobManager(
        max_workers=MAX_WORKERS,
        ttl_seconds=JOB_TTL,
        store_path=DOWNLOAD_DIR / "jobs.json",
    )
    job_manager.start_sweeper(interval_seconds=300)
    app.extensions["trove.jobs"] = job_manager
    app.extensions["trove.rate_limiter"] = rate_limiter

    @app.before_request
    def _rate_limit():
        if not request.path.startswith("/api/"):
            return None
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not rate_limiter.allow(ip):
            return jsonify({"error": "rate_limited"}), 429
        return None

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
    @token_required
    def api_file(job_id):
        job = job_manager.get(job_id)
        if job is None or job.status != JobStatus.DONE or not job.file_path:
            return jsonify({"error": "not_ready"}), 404
        return send_file(job.file_path, as_attachment=True, download_name=job.filename or "download")

    # --- HTML fragment endpoints (htmx) ------------------------------------

    @app.post("/api/info-card")
    @token_required
    def api_info_card():
        url = (request.form.get("url") or "").strip()
        format_choice = request.form.get("format", "video")
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
        })

    @app.post("/api/download-card")
    @token_required
    def api_download_card():
        url = (request.form.get("url") or "").strip()
        format_choice = request.form.get("format", "video")
        format_id = request.form.get("format_id") or None
        title = (request.form.get("title") or "").strip()
        thumbnail = (request.form.get("thumbnail") or "").strip()
        if not is_safe_url(url):
            return render_template("partials/card.html", card={
                "kind": "error", "url": url, "category": "unsupported_url",
            }), 400
        try:
            job_id = _enqueue_download(url, format_choice, format_id, title, thumbnail)
        except RuntimeError:
            return render_template("partials/card.html", card={
                "kind": "error", "url": url, "category": "busy",
            }), 503
        job = job_manager.get(job_id)
        return render_template("partials/card.html", card=_card_view(job))

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

        ok = job_manager.resume(job_id, target=_work)
        if not ok:
            return "", 404
        job = job_manager.get(job_id)
        return render_template("partials/card.html", card=_card_view(job))

    # --- helpers -----------------------------------------------------------

    def _enqueue_download(url: str, format_choice: str, format_id, title: str, thumbnail: str = "") -> str:
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

        return job_manager.submit(target=_work, title=title, url=url)

    def _card_view(job: Job) -> dict:
        # Bytes-based percent when we know the total. HLS streams (YouTube) leave
        # total_bytes at 0 — fall back to fragment ratio so the bar still moves.
        percent = 0
        if job.total_bytes > 0:
            percent = min(100, int(job.downloaded_bytes / job.total_bytes * 100))
        elif job.fragment_count > 0 and job.fragment_index > 0:
            percent = min(100, int(job.fragment_index / job.fragment_count * 100))
        return {
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

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app = create_app()
    app.run(host=host, port=port)
