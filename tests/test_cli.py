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
import pytest
import cli


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
