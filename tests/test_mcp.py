"""End-to-end tests for the trove-mcp MCP server.

These spawn the real ``mcp_server.py`` as a subprocess over the
official MCP stdio protocol, so they exercise both the FastMCP
wiring and the underlying HTTP plumbing through cli.py. Skipped
when the optional `mcp` SDK isn't installed.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import pytest

mcp_sdk = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _trove_server(tmp_path):
    """Spin up `python app.py` on a free port in an isolated cwd so
    the MCP server has a real Trove HTTP backend to talk to."""
    port = _free_port()
    env = {**os.environ, "PORT": str(port), "TROVE_RATE_LIMIT": "0"}
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO_ROOT, "app.py")],
        cwd=str(tmp_path), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 15
        import urllib.request
        url = f"http://127.0.0.1:{port}/api/v1/health"
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("trove server did not come up")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _drive_mcp(port: int) -> dict:
    """Open one MCP session and exercise the contract surface."""
    env = {**os.environ, "TROVE_URL": f"http://127.0.0.1:{port}"}
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(REPO_ROOT, "mcp_server.py")],
        env=env,
    )
    out: dict = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            out["tool_names"] = sorted(t.name for t in tools.tools)

            templates = await session.list_resource_templates()
            out["templates"] = sorted(
                t.uriTemplate for t in templates.resourceTemplates
            )

            async def call(name, args=None):
                r = await session.call_tool(name, args or {})
                return json.loads(r.content[0].text)

            out["list_jobs"] = await call("list_jobs")
            out["list_models"] = await call("list_models")
            out["list_transcripts"] = await call("list_transcripts")
            out["get_job_bad"] = await call("get_job", {"job_id": "nope"})
            out["transcribe_bad"] = await call(
                "transcribe", {"parent_job_id": "nope"})
            out["export_bad"] = await call(
                "get_transcript",
                {"transcript_id": "nope", "format": "txt"})
            out["bad_format"] = await call(
                "get_transcript", {"transcript_id": "x", "format": "docx"})
            out["install_bad"] = await call(
                "install_model", {"name": "not-real.bin"})

            jobs_res = await session.read_resource("trove://jobs")
            out["jobs_resource"] = jobs_res.contents[0].text
    return out


@pytest.mark.timeout(60)
def test_mcp_end_to_end(tmp_path):
    """One real client session against a real trove server.

    Locks: tool surface (count + names), resource templates, success
    paths (list_*), and structured-error paths (no stack traces leak).
    """
    with _trove_server(tmp_path) as port:
        result = asyncio.run(_drive_mcp(port))

    expected_tools = {
        "list_jobs", "get_job", "download_media", "pause_download",
        "resume_download", "cancel_download", "dismiss_download",
        "list_transcripts", "get_transcript_status", "transcribe",
        "cancel_transcribe", "get_transcript",
        "list_models", "install_model", "model_install_progress",
        "set_active_model", "remove_model",
    }
    assert set(result["tool_names"]) == expected_tools, result["tool_names"]
    assert "trove://transcript/{tid}" in result["templates"]

    # Success surface
    assert "jobs" in result["list_jobs"]
    assert "models" in result["list_models"]
    assert result["list_models"]["models"], "models list shouldn't be empty"
    assert "transcripts" in result["list_transcripts"]

    # Error surface — every error must be a {error, status?} dict, never
    # a stack trace or HTML body.
    for key in ("get_job_bad", "transcribe_bad", "export_bad", "install_bad"):
        v = result[key]
        assert isinstance(v, dict) and "error" in v, (key, v)
        assert "status" in v, (key, v)
        assert "Traceback" not in str(v), (key, v)
        assert "<html" not in str(v).lower(), (key, v)

    # The export 404 specifically used to leak HTML — pin the JSON body.
    assert result["export_bad"]["status"] == 404
    assert result["export_bad"]["error"] == "transcript_not_found_or_not_done"

    # Pre-tool-side-validation (bad format) doesn't reach HTTP, no status.
    assert result["bad_format"] == {"error": "format must be txt|srt|vtt|json"}

    # Resources return JSON text, not Python repr.
    assert json.loads(result["jobs_resource"])["jobs"] is not None or \
           "jobs" in json.loads(result["jobs_resource"])
