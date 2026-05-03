"""Tests for the ``trove`` CLI.

We don't spin up a real HTTP server — the CLI is a thin urllib
wrapper around the v1 API, so we monkeypatch ``cli.get`` /
``cli.post`` and assert that the right URL + body shapes go out and
that argument parsing wires up correctly.
"""
from __future__ import annotations
import io
import sys
import json
import subprocess
import pytest
import cli


def test_banner_only_prints_to_tty(monkeypatch, capsys):
    """Banner must NOT pollute stdout/stderr when piped (so
    `trove --json list | jq` and CI logs stay clean)."""
    import cli as _cli
    # Pretend stderr is not a tty.
    class FakeStderr:
        def isatty(self): return False
        def write(self, *_): raise AssertionError("banner wrote to non-tty")
        def flush(self): pass
    monkeypatch.setattr(_cli.sys, "stderr", FakeStderr())
    _cli._print_banner("anything")  # would AssertionError if it wrote


def test_banner_writes_to_tty(monkeypatch):
    import cli as _cli
    written = []
    class FakeStderr:
        def isatty(self): return True
        def write(self, s): written.append(s)
        def flush(self): pass
    monkeypatch.setattr(_cli.sys, "stderr", FakeStderr())
    _cli._print_banner("self-hosted media")
    blob = "".join(written)
    assert "TROVE".lower() not in blob.lower()  # block letters, not text
    assert "█" in blob
    assert "self-hosted media" in blob


def _cli_subcommand_names() -> set[str]:
    """Return the set of CLI subcommand names by parsing `--help` output
    (no reliance on argparse private internals)."""
    out = subprocess.run(
        [sys.executable, "cli.py", "--help"],
        capture_output=True, text=True, check=True,
    ).stdout
    # Each subcommand appears on its own line indented under
    # "positional arguments:" → "<command>". Match the leading word.
    in_block = False
    names: set[str] = set()
    for line in out.splitlines():
        # Section header is exactly "  <command>" (not the usage line,
        # which contains "<command>" embedded mid-line).
        if line.strip() == "<command>":
            in_block = True
            continue
        if in_block:
            if not line.startswith(" "):
                break
            stripped = line.strip()
            if not stripped:
                continue
            tok = stripped.split()[0]
            if tok and not tok.startswith("-"):
                names.add(tok)
    return names


def test_cli_has_full_mcp_feature_parity():
    """Every MCP tool must have a CLI counterpart declared in
    cli.MCP_TO_CLI, and every value in that map must actually be a
    registered CLI subcommand. This catches drift in either direction:
    adding an MCP tool without a CLI command, OR removing a CLI command
    that the map still claims exists."""
    # 1. Live MCP tool list (from the actual FastMCP instance).
    import asyncio
    import mcp_server
    server = mcp_server._build_server()
    mcp_tools = {t.name for t in asyncio.run(server.list_tools())}

    # 2. Every MCP tool must be in the parity map.
    unmapped = mcp_tools - cli.MCP_TO_CLI.keys()
    assert not unmapped, (
        f"MCP tools without a CLI mapping in cli.MCP_TO_CLI: {unmapped}"
    )
    extra = cli.MCP_TO_CLI.keys() - mcp_tools
    assert not extra, (
        f"cli.MCP_TO_CLI references tools the MCP server does not expose: {extra}"
    )

    # 3. Every mapped CLI command must actually be registered.
    cli_names = _cli_subcommand_names()
    missing = set(cli.MCP_TO_CLI.values()) - cli_names
    assert not missing, f"CLI missing subcommands declared in MCP_TO_CLI: {missing}"


def test_main_with_empty_argv_is_deterministic(monkeypatch, capsys):
    """`main([])` must NOT print the banner+help shortcut (which is
    only for bare-shell `trove`). It must hit argparse and exit cleanly
    regardless of the host process's sys.argv."""
    monkeypatch.setattr(sys, "argv", ["trove"])  # would trigger shortcut if main([]) used `not argv`
    with pytest.raises(SystemExit) as exc:
        cli.main([])  # no subcommand → argparse error
    assert exc.value.code != 0


# ---- new-command smoke tests ---------------------------------------
#
# These exercise the actual CLI command callbacks (cmd_get,
# cmd_transcript_status, cmd_cancel_transcribe, cmd_model_progress)
# against a fake HTTP transport. They lock in the user-visible output
# of the new MCP-parity commands.

class _FakeHeaders:
    def get(self, key, default=""): return "application/json"


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
        self.headers = _FakeHeaders()
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return json.dumps(self._payload).encode()


def _fake_urlopen_factory(get_payloads, post_payloads=None):
    post_payloads = post_payloads or {}
    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = getattr(req, "get_method", lambda: "GET")()
        bag = post_payloads if method == "POST" else get_payloads
        for path, payload in bag.items():
            if url.endswith(path):
                return _FakeResp(payload)
        raise AssertionError(f"unexpected {method} {url}")
    return fake


def test_cmd_get_renders_human_summary(monkeypatch, capsys):
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen_factory({
        "/api/v1/jobs/abc123": {
            "id": "abc123", "status": "downloading", "url": "https://x/y",
            "title": "Demo clip", "format_choice": "audio",
            "progress_pct": 42, "downloaded_bytes": 1, "total_bytes": 2,
            "human": {"summary": "downloading · 42% · 1.0 KB / 2.0 KB · 5.0 KB/s",
                      "elapsed": "0:08", "eta": "0:03"},
        },
    }))
    rc = cli.main(["get", "abc123"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "abc123" in out and "downloading" in out
    assert "downloading · 42%" in out
    assert "elapsed:   0:08" in out and "eta: 0:03" in out


def test_cmd_transcript_status_renders_audio_duration(monkeypatch, capsys):
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen_factory({
        "/api/v1/transcripts/t9": {
            "id": "t9", "status": "running", "parent_job_id": "p1",
            "model_used": "ggml-tiny.bin", "progress_pct": 60,
            "language_detected": "en",
            "human": {"summary": "running · 60% · elapsed 0:30 · model=ggml-tiny.bin",
                      "audio_duration": "9:12", "elapsed": "0:30"},
        },
    }))
    rc = cli.main(["transcript-status", "t9"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "running · 60%" in out
    assert "9:12" in out
    assert "lang:     en" in out


def test_cmd_cancel_transcribe_posts(monkeypatch, capsys):
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen_factory(
        get_payloads={},
        post_payloads={"/api/v1/transcripts/t9/cancel": {
            "id": "t9", "status": "cancelled", "parent_job_id": "p1",
            "progress_pct": 0, "model_used": "ggml-tiny.bin",
            "human": {"elapsed": "0:05"},
        }},
    ))
    rc = cli.main(["transcribe-cancel", "t9"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "t9" in out and "cancelled" in out


def test_cmd_model_progress_idle_and_in_flight(monkeypatch, capsys):
    # Idle case
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen_factory({
        "/api/v1/models/install-progress": {"downloading": False, "done": False},
    }))
    assert cli.main(["model-progress"]) == 0
    assert "(no install in progress)" in capsys.readouterr().out
    # In-flight case
    monkeypatch.setattr(cli.urllib.request, "urlopen", _fake_urlopen_factory({
        "/api/v1/models/install-progress": {
            "downloading": True, "done": False, "name": "ggml-base.bin",
            "received": 5_242_880, "total": 10_485_760,
        },
    }))
    assert cli.main(["model-progress"]) == 0
    out = capsys.readouterr().out
    assert "ggml-base.bin" in out and "50%" in out and "downloading" in out


def test_json_flag_works_in_either_position():
    """Regression: argparse only honours --json in the position it's
    declared on. The fix uses parents=[json_parent] so it works as
    both `trove --json health` and `trove health --json`."""
    parser = cli.build_parser()
    a = parser.parse_args(["--json", "health"])
    b = parser.parse_args(["health", "--json"])
    assert a.json is True and b.json is True
    c = parser.parse_args(["fetch", "https://x", "--mp3", "--json"])
    d = parser.parse_args(["--json", "fetch", "https://x", "--mp3"])
    assert c.json is True and d.json is True
    assert c.mp3 is True and d.mp3 is True


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    monkeypatch.setenv("TROVE_URL", "http://127.0.0.1:5000")


def test_parser_accepts_all_subcommands():
    p = cli.build_parser()
    for argv in (
        ["health"],
        ["fetch", "https://x", "--mp3", "--transcribe", "--wait"],
        ["list"],
        ["pause", "abc"], ["resume", "abc"],
        ["cancel", "abc"], ["rm", "abc"],
        ["transcribe", "abc", "--wait"],
        ["transcripts"],
        ["transcript", "tid", "-f", "srt", "-o", "/tmp/x.srt"],
        ["models"],
        ["model-install", "ggml-tiny.bin", "--wait"],
        ["model-use", "ggml-tiny.bin"],
        ["model-rm", "ggml-tiny.bin"],
    ):
        ns = p.parse_args(argv)
        assert ns.cmd == argv[0]
        assert callable(ns.func)


def test_headers_include_token_when_set(monkeypatch):
    monkeypatch.setenv("TROVE_TOKEN", "abc123")
    h = cli._headers()
    assert h["Authorization"] == "Bearer abc123"


def test_headers_skip_token_when_unset():
    h = cli._headers()
    assert "Authorization" not in h


def test_fetch_posts_correct_body(monkeypatch, capsys):
    captured = {}
    def fake_post(path, body=None, **kw):
        captured["path"] = path
        captured["body"] = body
        return {"id": "newid1", "title": "t", "url": "https://x", "status": "queued"}
    monkeypatch.setattr(cli, "post", fake_post)
    rc = cli.main(["fetch", "https://x", "--mp3", "--transcribe", "--title", "Hi"])
    assert rc == 0
    assert captured["path"] == "/api/v1/jobs"
    assert captured["body"] == {
        "url": "https://x", "format": "audio",
        "auto_transcribe": True, "title": "Hi",
    }
    out = capsys.readouterr().out
    assert "newid1" in out


def test_list_renders_table(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get", lambda p, **kw: {"jobs": [
        {"id": "j1", "status": "done", "title": "Clip A",
         "url": "https://x", "downloaded_bytes": 100, "total_bytes": 100,
         "fragment_index": 0, "fragment_count": 0},
    ]})
    rc = cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "j1" in out and "done" in out and "Clip A" in out


def test_list_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get", lambda p, **kw: {"jobs": []})
    rc = cli.main(["--json", "list"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"jobs": []}


def test_transcript_writes_to_output_file(monkeypatch, tmp_path):
    out_path = tmp_path / "out.srt"
    captured = {}
    def fake_get(path, stream_to=None, **kw):
        captured["path"] = path
        captured["stream_to"] = stream_to
        if stream_to:
            open(stream_to, "wb").write(b"1\n00:00\n--> 00:01\nhello\n")
        return {"saved_to": stream_to}
    monkeypatch.setattr(cli, "get", fake_get)
    rc = cli.main(["transcript", "tid", "-f", "srt", "-o", str(out_path)])
    assert rc == 0
    assert captured["path"] == "/api/v1/transcripts/tid/export.srt"
    assert out_path.exists()


def test_trove_error_formatted(monkeypatch, capsys):
    def boom(p, **kw):
        raise cli.TroveError(404, {"error": "not_found"}, "/api/v1/jobs/x")
    monkeypatch.setattr(cli, "get", boom)
    rc = cli.main(["list"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not_found" in err and "404" in err


def test_unreachable_server_exits_clearly(monkeypatch, capsys):
    import urllib.error
    def boom(*a, **kw):
        raise urllib.error.URLError("Connection refused")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SystemExit) as exc:
        cli._request("GET", "/api/v1/health")
    assert "trove serve" in str(exc.value)
