"""``trove-mcp`` — MCP (Model Context Protocol) server for Trove.

Exposes the Trove HTTP API as a set of MCP tools so a coding agent
(Claude Desktop, Cursor, Replit Agent, etc.) can drive Trove
end-to-end: queue downloads, watch them complete, kick off
transcription, fetch / export transcripts, search and replace
inside transcripts, and manage whisper models.

Transport: stdio (the default for desktop MCP clients).

Configuration (env vars):
    TROVE_URL    Base URL of the Trove server (default localhost:5000).
    TROVE_TOKEN  Bearer token if the server was started with one.

Usage in a client config (Claude Desktop / Cursor):
    {
      "mcpServers": {
        "trove": {
          "command": "trove-mcp",
          "env": { "TROVE_URL": "http://127.0.0.1:5000" }
        }
      }
    }

The server expects the Trove HTTP server to already be running. Each
tool returns a clear error if the server is unreachable so the agent
knows to prompt the user to start it (``trove serve``).
"""
from __future__ import annotations

import os
import sys
from typing import Any

# Reuse the CLI's HTTP plumbing — same env vars, same error mapping,
# same auth header shape — so the two surfaces stay in lockstep.
from cli import TroveError, get, post


def _safe(call):
    """Wrap a TroveError into an MCP-friendly ``{error: str}`` dict so
    the agent always gets a machine-readable response, never a stack
    trace. Any other exception bubbles up to the SDK, which already
    serializes it as a tool error."""
    try:
        return call()
    except TroveError as e:
        msg = e.body.get("error") if isinstance(e.body, dict) else str(e.body)
        return {"error": msg, "status": e.status}
    except SystemExit as e:
        return {"error": str(e)}


def _build_server():
    """Construct the FastMCP server with all tools + resources.

    Lazy-imported so ``import mcp_server`` never fails when the
    optional ``mcp`` SDK isn't installed — only ``main()`` requires
    it. This lets the test suite import the module to inspect tool
    metadata without forcing the dep.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            "trove-mcp: the 'mcp' package is required.\n"
            "  Install with: pip install 'trove[mcp]'  (or just: pip install mcp)"
        ) from e

    mcp = FastMCP("trove")

    # ---- jobs (downloads) -------------------------------------------

    @mcp.tool()
    def list_jobs() -> dict:
        """List all download jobs (queued / downloading / paused / done / error)."""
        return _safe(lambda: get("/api/v1/jobs"))

    @mcp.tool()
    def get_job(job_id: str) -> dict:
        """Get the current state of one download job."""
        return _safe(lambda: get(f"/api/v1/jobs/{job_id}"))

    @mcp.tool()
    def download_media(
        url: str,
        format: str = "video",
        auto_transcribe: bool = False,
        title: str = "",
    ) -> dict:
        """Queue a new media download.

        Args:
            url: The source URL (YouTube, Vimeo, anything yt-dlp supports).
            format: ``"video"`` (mp4) or ``"audio"`` (mp3).
            auto_transcribe: Trigger transcription on success when an
                active model is installed.
            title: Optional override; defaults to the source title.
        """
        body: dict = {"url": url, "format": format,
                      "auto_transcribe": auto_transcribe}
        if title:
            body["title"] = title
        return _safe(lambda: post("/api/v1/jobs", body=body))

    @mcp.tool()
    def pause_download(job_id: str) -> dict:
        """Pause an in-flight download. The .part file is preserved."""
        return _safe(lambda: post(f"/api/v1/jobs/{job_id}/pause"))

    @mcp.tool()
    def resume_download(job_id: str) -> dict:
        """Resume a paused download (re-uses the persisted format/url)."""
        return _safe(lambda: post(f"/api/v1/jobs/{job_id}/resume"))

    @mcp.tool()
    def cancel_download(job_id: str) -> dict:
        """Cancel a download. Removes any partial output."""
        return _safe(lambda: post(f"/api/v1/jobs/{job_id}/cancel"))

    @mcp.tool()
    def dismiss_download(job_id: str) -> dict:
        """Dismiss a terminal job (done/error/cancelled) and delete its file."""
        r = _safe(lambda: post(f"/api/v1/jobs/{job_id}/dismiss"))
        return {"ok": True, "job_id": job_id} if r is None else r

    # ---- transcripts ------------------------------------------------

    @mcp.tool()
    def list_transcripts() -> dict:
        """List all transcribe jobs (queued / running / done / error)."""
        return _safe(lambda: get("/api/v1/transcripts"))

    @mcp.tool()
    def get_transcript_status(transcript_id: str) -> dict:
        """Get the lifecycle state of one transcribe job."""
        return _safe(lambda: get(f"/api/v1/transcripts/{transcript_id}"))

    @mcp.tool()
    def transcribe(parent_job_id: str) -> dict:
        """Kick off transcription for a downloaded clip.

        Idempotent — if a transcribe is already running for this clip,
        returns the existing one instead of starting a duplicate.
        Requires an active whisper model (use ``install_model`` /
        ``set_active_model`` first if needed).
        """
        return _safe(lambda: post(f"/api/v1/jobs/{parent_job_id}/transcribe"))

    @mcp.tool()
    def cancel_transcribe(transcript_id: str) -> dict:
        """Cancel an in-flight transcribe job."""
        return _safe(lambda: post(f"/api/v1/transcripts/{transcript_id}/cancel"))

    @mcp.tool()
    def get_transcript(transcript_id: str, format: str = "txt") -> dict:
        """Fetch a finished transcript.

        Args:
            transcript_id: The transcript id from ``list_transcripts``.
            format: One of ``"txt"`` (plain), ``"srt"`` (subtitles),
                ``"vtt"`` (web subtitles), or ``"json"`` (raw v2 schema
                with word-level timing — useful for programmatic edits).

        Returns:
            ``{format, content}`` for txt/srt/vtt; the parsed JSON tree
            for ``"json"``.
        """
        if format not in {"txt", "srt", "vtt", "json"}:
            return {"error": "format must be txt|srt|vtt|json"}
        body = _safe(lambda: get(f"/api/v1/transcripts/{transcript_id}/export.{format}"))
        if isinstance(body, dict) and body.get("error"):
            return body
        if format == "json":
            return body if isinstance(body, dict) else {"error": "unexpected_response"}
        return {"format": format, "content": body}

    # ---- models -----------------------------------------------------

    @mcp.tool()
    def list_models() -> dict:
        """List known whisper models with installed/active state."""
        return _safe(lambda: get("/api/v1/models"))

    @mcp.tool()
    def install_model(name: str) -> dict:
        """Start downloading a whisper model from HuggingFace.

        Background operation — poll ``model_install_progress`` for status.
        Names are e.g. ``"ggml-tiny.bin"``, ``"ggml-base.bin"``,
        ``"ggml-small.bin"``, ``"ggml-medium.bin"``.
        """
        return _safe(lambda: post(f"/api/v1/models/{name}/install"))

    @mcp.tool()
    def model_install_progress() -> dict:
        """Get the current model-install download progress."""
        return _safe(lambda: get("/api/v1/models/install-progress"))

    @mcp.tool()
    def set_active_model(name: str) -> dict:
        """Mark an installed model as the active one (used for new transcribes)."""
        return _safe(lambda: post(f"/api/v1/models/{name}/use"))

    @mcp.tool()
    def remove_model(name: str) -> dict:
        """Delete an installed model from disk."""
        r = _safe(lambda: post(f"/api/v1/models/{name}/remove"))
        return {"ok": True, "name": name} if r is None else r

    # ---- resources --------------------------------------------------
    # Resources let the agent surface live application state to the user
    # without spending tool-call budget on plain reads.

    @mcp.resource("trove://jobs")
    def jobs_resource() -> str:
        import json as _json
        return _json.dumps(_safe(lambda: get("/api/v1/jobs")), indent=2)

    @mcp.resource("trove://transcripts")
    def transcripts_resource() -> str:
        import json as _json
        return _json.dumps(_safe(lambda: get("/api/v1/transcripts")), indent=2)

    @mcp.resource("trove://transcript/{tid}")
    def transcript_resource(tid: str) -> str:
        import json as _json
        body = _safe(lambda: get(f"/api/v1/transcripts/{tid}/export.json"))
        return _json.dumps(body, indent=2) if isinstance(body, dict) else str(body)

    return mcp


def main() -> int:
    server = _build_server()
    base = os.environ.get("TROVE_URL", "http://127.0.0.1:5000")
    print(f"trove-mcp: Trove API → {base}", file=sys.stderr)
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
