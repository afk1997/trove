"""``trove-mcp`` — MCP (Model Context Protocol) server for Trove.

Exposes the Trove HTTP API as a set of MCP tools so a coding agent
(Claude Desktop, Cursor, Replit Agent, etc.) can drive Trove
end-to-end: queue downloads, watch them complete, kick off
transcription, fetch / export transcripts, search and replace
inside transcripts, and manage whisper models.

Transport: stdio (the default for desktop MCP clients).

Configuration (env vars):
    TROVE_URL    Base URL of the Trove server (default localhost:8899).
    TROVE_TOKEN  Bearer token if the server was started with one.

Usage in a client config (Claude Desktop / Cursor):
    {
      "mcpServers": {
        "trove": {
          "command": "trove-mcp",
          "env": { "TROVE_URL": "http://127.0.0.1:8899" }
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

# Depend on the shared client, NOT on cli.py — the MCP server should
# never inherit CLI-specific behavior (terminal formatting, exit
# semantics, banners, argparse assumptions, stdout/stderr conventions).
from trove_client import TroveClient, TroveError


# Module-level client. Properties read TROVE_URL / TROVE_TOKEN at call
# time so a re-export of the env var (e.g. via the host MCP client
# config) takes effect on the next tool call without rebuilding.
_client = TroveClient()


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
    def list_jobs(
        status: str = "",
        limit: int = 100,
        offset: int = 0,
        order: str = "newest",
    ) -> dict:
        """List download jobs (paginated, filterable).

        Args:
            status: Comma-separated status filter (e.g. ``"done,error"``).
                Empty string returns all jobs.
            limit: 1-500, default 100.
            offset: Skip this many jobs (use with ``limit`` to page).
            order: ``"newest"`` (default) or ``"oldest"``.

        Returns ``{jobs, total, returned, limit, offset}``.
        """
        return _safe(lambda: _client.list_jobs(
            status=status, limit=limit, offset=offset, order=order))

    @mcp.tool()
    def get_job(job_id: str) -> dict:
        """Get the current state of one download job.

        Returns rich progress data so you can give the user a useful
        live update on every poll:

        - ``status``: queued / downloading / paused / done / error / cancelled
        - ``progress_pct`` (0-100), ``downloaded_bytes``, ``total_bytes``
        - ``speed_bps`` (bytes/sec), ``eta_seconds``, ``elapsed_seconds``
        - ``fragment_index`` / ``fragment_count`` for HLS/DASH streams
        - ``human``: pre-formatted strings — ``progress`` (``"42%"``),
          ``downloaded`` (``"12.4 MB"``), ``size``, ``speed``
          (``"5.2 MB/s"``), ``eta`` (``"0:03"``), ``elapsed``, plus a
          ``summary`` one-liner you can paste straight into a reply
          (e.g. ``"downloading · 42% · 12.4 MB / 29.7 MB · 5.2 MB/s · ETA 0:03"``).
        """
        return _safe(lambda: _client.get_job(job_id))

    @mcp.tool()
    def bulk_download(
        urls: list[str],
        format: str = "video",
        auto_transcribe: bool = False,
    ) -> dict:
        """Queue many downloads in one call.

        Args:
            urls: List of source URLs (max 100).
            format: ``"video"`` or ``"audio"`` — applied to all.
            auto_transcribe: Trigger transcription on each successful download.

        Returns ``{submitted, failed, results}``. Each ``results`` entry
        is either ``{url, id, title}`` (success) or ``{url, error}`` (failure)
        — partial failures don't fail the whole call.
        """
        return _safe(lambda: _client.bulk_download(
            urls, fmt=format, auto_transcribe=auto_transcribe))

    @mcp.tool()
    def storage_info() -> dict:
        """Disk-usage report for the download directory.

        Returns total bytes, file count, per-job breakdown
        (``by_job``, sorted biggest first) and any orphan files left
        behind by crashes.
        """
        return _safe(lambda: _client.storage_info())

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
        return _safe(lambda: _client.submit_download(
            url, fmt=format, auto_transcribe=auto_transcribe,
            title=title or None))

    @mcp.tool()
    def pause_download(job_id: str) -> dict:
        """Pause an in-flight download. The .part file is preserved."""
        return _safe(lambda: _client.pause_job(job_id))

    @mcp.tool()
    def resume_download(job_id: str) -> dict:
        """Resume a paused download (re-uses the persisted format/url)."""
        return _safe(lambda: _client.resume_job(job_id))

    @mcp.tool()
    def cancel_download(job_id: str) -> dict:
        """Cancel a download. Removes any partial output."""
        return _safe(lambda: _client.cancel_job(job_id))

    @mcp.tool()
    def dismiss_download(job_id: str) -> dict:
        """Dismiss a terminal job (done/error/cancelled) and delete its file."""
        r = _safe(lambda: _client.dismiss_job(job_id))
        return {"ok": True, "job_id": job_id} if r is None else r

    # ---- transcripts ------------------------------------------------

    @mcp.tool()
    def list_transcripts(
        status: str = "",
        limit: int = 100,
        offset: int = 0,
        order: str = "newest",
    ) -> dict:
        """List transcribe jobs (paginated, filterable).

        Same paging semantics as ``list_jobs``.
        """
        return _safe(lambda: _client.list_transcripts(
            status=status, limit=limit, offset=offset, order=order))

    @mcp.tool()
    def search_transcripts(query: str, limit: int = 50, context: int = 60) -> dict:
        """Substring-search across all completed transcripts.

        Args:
            query: The phrase to find (case-insensitive).
            limit: Max matches to return (1-200).
            context: Characters of surrounding context per match.

        Returns ``{query, matches, returned}``. Each match has
        ``transcript_id``, ``parent_job_id``, ``title``, ``snippet``,
        ``start_seconds`` and ``end_seconds`` so the agent can deep-link.
        """
        return _safe(lambda: _client.search_transcripts(
            query, limit=limit, context=context))

    @mcp.tool()
    def get_transcript_status(transcript_id: str) -> dict:
        """Get the lifecycle state + progress of one transcribe job.

        Returns: ``status`` (queued/running/done/error/cancelled),
        ``progress_pct``, ``elapsed_seconds``, ``duration_seconds``
        (length of the source audio), ``language_detected``,
        ``model_used``, plus a ``human`` block with pre-formatted
        ``progress``, ``elapsed``, ``audio_duration`` and a
        ``summary`` one-liner (e.g. ``"running · 42% · of 9:12 audio
        · elapsed 1:08 · model=ggml-tiny.bin"``).
        """
        return _safe(lambda: _client.get_transcript_status(transcript_id))

    @mcp.tool()
    def transcribe(parent_job_id: str) -> dict:
        """Kick off transcription for a downloaded clip.

        Idempotent — if a transcribe is already running for this clip,
        returns the existing one instead of starting a duplicate.
        Requires an active whisper model (use ``install_model`` /
        ``set_active_model`` first if needed).
        """
        return _safe(lambda: _client.transcribe(parent_job_id))

    @mcp.tool()
    def cancel_transcribe(transcript_id: str) -> dict:
        """Cancel an in-flight transcribe job."""
        return _safe(lambda: _client.cancel_transcribe(transcript_id))

    @mcp.tool()
    def get_transcript_chunk(transcript_id: str, format: str = "txt",
                             offset: int = 0, limit: int = 0) -> dict:
        """Read a slice of a finished transcript (paginated).

        Designed for context-bounded LLM callers: a 90-minute podcast
        transcript easily exceeds the per-tool reply budget, so this
        returns one page at a time and the agent stitches them.

        Args:
            transcript_id: The transcript id from ``list_transcripts``.
            format: ``txt|srt|vtt`` slice by *byte* offset (matches the
                bytes the export endpoint would serve); ``json`` slices
                by *segment* index over the v2 schema.
            offset: Where to start the page (byte or segment index per
                ``format``). 0 starts from the beginning.
            limit: Page size. ``0`` (the default) lets the server pick:
                4000 bytes for text, 50 segments for json. Capped at
                64000 bytes / 500 segments server-side.

        Returns:
            ``{format, offset, limit, returned, total, has_more, ...}``
            with ``content`` for text formats or ``segments`` + ``words``
            (filtered to those referenced by the returned segments) for
            ``json``. Loop while ``has_more`` is true, advancing
            ``offset`` by ``returned`` each call.
        """
        if format not in {"txt", "srt", "vtt", "json"}:
            return {"error": "format must be txt|srt|vtt|json"}
        kw = {"offset": offset}
        if limit:
            kw["limit"] = limit
        return _safe(lambda: _client.get_transcript_chunk(
            transcript_id, format, **kw))

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
        body = _safe(lambda: _client.export_transcript(transcript_id, format))
        if isinstance(body, dict) and body.get("error"):
            return body
        if format == "json":
            return body if isinstance(body, dict) else {"error": "unexpected_response"}
        return {"format": format, "content": body}

    # ---- meta -------------------------------------------------------

    @mcp.tool()
    def server_capabilities() -> dict:
        """Probe what the connected Trove server supports.

        Returns the feature / limit / scope registry — useful for an
        agent to decide whether diarization is available, what the
        chunk-size caps are, whether the server requires a bearer
        token, and which transcript export formats are supported.
        Safe to call without authentication.
        """
        return _safe(lambda: _client.capabilities())

    # ---- models -----------------------------------------------------

    @mcp.tool()
    def list_models() -> dict:
        """List known whisper models with installed/active state."""
        return _safe(lambda: _client.list_models())

    @mcp.tool()
    def install_model(name: str) -> dict:
        """Start downloading a whisper model from HuggingFace.

        Background operation — poll ``model_install_progress`` for status.
        Names are e.g. ``"ggml-tiny.bin"``, ``"ggml-base.bin"``,
        ``"ggml-small.bin"``, ``"ggml-medium.bin"``.
        """
        return _safe(lambda: _client.install_model(name))

    @mcp.tool()
    def model_install_progress() -> dict:
        """Get the current model-install download progress."""
        return _safe(lambda: _client.model_install_progress())

    @mcp.tool()
    def set_active_model(name: str) -> dict:
        """Mark an installed model as the active one (used for new transcribes)."""
        return _safe(lambda: _client.set_active_model(name))

    @mcp.tool()
    def remove_model(name: str) -> dict:
        """Delete an installed model from disk."""
        r = _safe(lambda: _client.remove_model(name))
        return {"ok": True, "name": name} if r is None else r

    # ---- resources --------------------------------------------------
    # Resources let the agent surface live application state to the user
    # without spending tool-call budget on plain reads.

    @mcp.resource("trove://jobs")
    def jobs_resource() -> str:
        import json as _json
        return _json.dumps(_safe(lambda: _client.list_jobs()), indent=2)

    @mcp.resource("trove://transcripts")
    def transcripts_resource() -> str:
        import json as _json
        return _json.dumps(_safe(lambda: _client.list_transcripts()), indent=2)

    @mcp.resource("trove://transcript/{tid}")
    def transcript_resource(tid: str) -> str:
        import json as _json
        body = _safe(lambda: _client.export_transcript(tid, "json"))
        return _json.dumps(body, indent=2) if isinstance(body, dict) else str(body)

    @mcp.resource("trove://transcript/{tid}/text")
    def transcript_text_resource(tid: str) -> str:
        """Plain-text export of a transcript — handy for the agent to
        ingest as a single string without parsing the v2 JSON tree."""
        body = _safe(lambda: _client.export_transcript(tid, "txt"))
        if isinstance(body, dict) and body.get("error"):
            return f"(error: {body['error']})"
        return body if isinstance(body, str) else str(body)

    @mcp.resource("trove://transcripts/{tid}.txt")
    def transcript_txt_alias_resource(tid: str) -> str:
        """Alias of ``trove://transcript/{tid}/text`` using the
        plural-collection / file-suffix URI shape that mirrors the
        public REST path (``/transcripts/<id>/export.txt``). Both URIs
        are kept so existing MCP clients keep working."""
        return transcript_text_resource(tid)

    @mcp.resource("trove://storage")
    def storage_resource() -> str:
        import json as _json
        return _json.dumps(_safe(lambda: _client.storage_info()), indent=2)

    return mcp


def main() -> int:
    from config import DEFAULT_BASE_URL
    server = _build_server()
    base = os.environ.get("TROVE_URL", DEFAULT_BASE_URL)
    print(f"trove-mcp: Trove API → {base}", file=sys.stderr)
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
