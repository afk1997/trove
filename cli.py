"""``trove`` — command-line interface for the Trove media downloader / transcript editor.

Talks to a running Trove HTTP server (default ``http://127.0.0.1:5000``)
through the stable ``/api/v1`` JSON API. Configurable via env vars:

    TROVE_URL    Base URL of the running server (default localhost:5000).
    TROVE_TOKEN  Bearer token if the server was started with one.

Stdlib-only on purpose so the CLI installs everywhere Python 3.11+ runs
without pulling extra dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_URL = "http://127.0.0.1:5000"


# ----- HTTP helpers ---------------------------------------------------

class TroveError(RuntimeError):
    """Raised for any non-2xx response from the Trove server. Carries
    the parsed JSON body (if any) so callers can format a useful
    message instead of a bare urllib stack trace."""
    def __init__(self, status: int, body: Any, url: str):
        self.status = status
        self.body = body
        self.url = url
        msg = body.get("error") if isinstance(body, dict) else str(body)
        super().__init__(f"HTTP {status} {url} -> {msg}")


def _base_url() -> str:
    return os.environ.get("TROVE_URL", DEFAULT_URL).rstrip("/")


def _headers() -> dict:
    h = {"Accept": "application/json"}
    tok = os.environ.get("TROVE_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _request(method: str, path: str, *, body: dict | None = None,
             stream_to: str | None = None, timeout: int = 30) -> Any:
    """Issue one HTTP call and parse the response.

    Returns the decoded JSON body for 2xx responses, ``None`` for 204s.
    Raises ``TroveError`` for everything else. When ``stream_to`` is
    set, the response body is written to that file path verbatim
    (used for export downloads).
    """
    url = _base_url() + path
    data = None
    headers = _headers()
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def get(path: str, **kw):    return _request("GET", path, **kw)
def post(path: str, body: dict | None = None, **kw): return _request("POST", path, body=body, **kw)


# ----- formatting -----------------------------------------------------

def _human_bytes(n: int) -> str:
    if n is None or n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _format_job_row(j: dict) -> str:
    pct = ""
    if j.get("total_bytes"):
        pct = f" {int(j['downloaded_bytes'] / j['total_bytes'] * 100):3d}%"
    elif j.get("fragment_count"):
        pct = f" {int(j['fragment_index'] / j['fragment_count'] * 100):3d}%"
    return (
        f"{j['id']:<10}  {j['status']:<11}{pct:>5}  "
        f"{(j.get('title') or j['url'])[:60]}"
    )


def _format_tj_row(t: dict) -> str:
    return (
        f"{t['id']:<10}  {t['status']:<10}  "
        f"{t['progress_pct']:>3}%  parent={t['parent_job_id']:<10}  "
        f"model={t.get('model_used') or '—'}"
    )


# ----- subcommands ----------------------------------------------------

def cmd_serve(args) -> int:
    """Start the Flask dev server in-process."""
    os.environ.setdefault("FLASK_ENV", "development")
    from app import create_app
    app = create_app()
    print(f"trove: serving on http://127.0.0.1:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


def cmd_health(args) -> int:
    out = get("/api/v1/health")
    _print_json(out)
    return 0


def cmd_fetch(args) -> int:
    body = {
        "url": args.url,
        "format": "audio" if args.mp3 else "video",
        "auto_transcribe": bool(args.transcribe),
    }
    if args.title:
        body["title"] = args.title
    job = post("/api/v1/jobs", body=body)
    if getattr(args, "json", False):
        _print_json(job)
    else:
        print(f"queued {job['id']}: {job.get('title') or job['url']}")
    if args.wait:
        return _wait_for_job(job["id"], json_out=getattr(args, "json", False))
    return 0


def _wait_for_job(job_id: str, *, json_out: bool, poll: float = 2.0,
                  timeout: float = 3600) -> int:
    deadline = time.time() + timeout
    last_line = ""
    while time.time() < deadline:
        try:
            job = get(f"/api/v1/jobs/{job_id}")
        except TroveError as e:
            if e.status == 404:
                print(f"trove: job {job_id} disappeared", file=sys.stderr)
                return 1
            raise
        if not json_out:
            line = _format_job_row(job)
            if line != last_line:
                sys.stdout.write("\r" + line + " " * 8)
                sys.stdout.flush()
                last_line = line
        status = job["status"]
        if status in ("done", "error", "cancelled"):
            if not json_out:
                sys.stdout.write("\n")
            if json_out:
                _print_json(job)
            return 0 if status == "done" else 2
        time.sleep(poll)
    print(f"trove: timeout waiting for {job_id}", file=sys.stderr)
    return 3


def cmd_list(args) -> int:
    data = get("/api/v1/jobs")
    if getattr(args, "json", False):
        _print_json(data)
        return 0
    jobs = data["jobs"]
    if not jobs:
        print("(no jobs)")
        return 0
    print(f"{'ID':<10}  {'STATUS':<11}    %   TITLE")
    for j in jobs:
        print(_format_job_row(j))
    return 0


def cmd_job_action(args, action: str) -> int:
    out = post(f"/api/v1/jobs/{args.id}/{action}")
    if out is None:
        print(f"{args.id}: {action}")
    else:
        _print_json(out) if getattr(args, "json", False) else print(_format_job_row(out))
    return 0


def cmd_transcribe(args) -> int:
    tj = post(f"/api/v1/jobs/{args.job_id}/transcribe")
    if getattr(args, "json", False):
        _print_json(tj)
    else:
        print(f"transcribe {tj['id']} for parent {args.job_id}: {tj['status']}")
    if args.wait:
        return _wait_for_transcript(tj["id"], json_out=getattr(args, "json", False))
    return 0


def _wait_for_transcript(tid: str, *, json_out: bool, poll: float = 2.0,
                         timeout: float = 3600) -> int:
    deadline = time.time() + timeout
    last_line = ""
    while time.time() < deadline:
        try:
            tj = get(f"/api/v1/transcripts/{tid}")
        except TroveError as e:
            if e.status == 404:
                print(f"trove: transcript {tid} gone", file=sys.stderr)
                return 1
            raise
        if not json_out:
            line = _format_tj_row(tj)
            if line != last_line:
                sys.stdout.write("\r" + line + " " * 8)
                sys.stdout.flush()
                last_line = line
        if tj["status"] in ("done", "error", "cancelled"):
            if not json_out:
                sys.stdout.write("\n")
            if json_out:
                _print_json(tj)
            return 0 if tj["status"] == "done" else 2
        time.sleep(poll)
    print(f"trove: timeout waiting for {tid}", file=sys.stderr)
    return 3


def cmd_transcripts(args) -> int:
    data = get("/api/v1/transcripts")
    if getattr(args, "json", False):
        _print_json(data)
        return 0
    ts = data["transcripts"]
    if not ts:
        print("(no transcripts)")
        return 0
    print(f"{'ID':<10}  {'STATUS':<10}    %   PARENT     MODEL")
    for t in ts:
        print(_format_tj_row(t))
    return 0


def cmd_transcript(args) -> int:
    path = f"/api/v1/transcripts/{args.id}/export.{args.format}"
    if args.output:
        get(path, stream_to=args.output)
        print(f"saved → {args.output}")
        return 0
    body = get(path)
    if args.format == "json":
        _print_json(body if isinstance(body, dict) else json.loads(body))
    else:
        sys.stdout.write(body if isinstance(body, str) else body.decode("utf-8"))
        if not str(body).endswith("\n"):
            sys.stdout.write("\n")
    return 0


def cmd_models(args) -> int:
    data = get("/api/v1/models")
    if getattr(args, "json", False):
        _print_json(data)
        return 0
    print(f"active: {data.get('active') or '(none)'}")
    print(f"{'NAME':<20}  {'SIZE':>8}  STATE")
    for m in data["models"]:
        state = []
        if m["is_active"]:
            state.append("active")
        elif m["is_installed"]:
            state.append("installed")
        else:
            state.append("not installed")
        print(f"{m['name']:<20}  {_human_bytes(m['size_bytes']):>8}  {','.join(state)}")
    progress = data.get("install_progress") or {}
    if progress.get("downloading"):
        rec = progress.get("received", 0)
        tot = progress.get("total", 0) or 1
        print(f"\ndownloading {progress.get('name')}: "
              f"{int(rec / tot * 100)}% ({_human_bytes(rec)}/{_human_bytes(tot)})")
    return 0


def cmd_model_use(args) -> int:
    out = post(f"/api/v1/models/{args.name}/use")
    print(f"active model → {out['active']}")
    return 0


def cmd_model_install(args) -> int:
    post(f"/api/v1/models/{args.name}/install")
    print(f"trove: installing {args.name} (background)...")
    if args.wait:
        while True:
            p = get("/api/v1/models/install-progress")
            if not p["downloading"]:
                if p.get("error"):
                    print(f"\ntrove: install failed — {p['error']}", file=sys.stderr)
                    return 2
                print(f"\ntrove: {args.name} installed and set active")
                return 0
            rec, tot = p["received"], p["total"] or 1
            sys.stdout.write(f"\r  {int(rec / tot * 100):3d}%  "
                             f"{_human_bytes(rec)}/{_human_bytes(tot)}")
            sys.stdout.flush()
            time.sleep(2)
    return 0


def cmd_model_remove(args) -> int:
    post(f"/api/v1/models/{args.name}/remove")
    print(f"removed {args.name}")
    return 0


# ----- argparse wiring ------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # `--json` lives on a parent parser so it works in EITHER position
    # (`trove --json list` or `trove list --json`). Argparse otherwise
    # only honours it in the position the flag is declared on.
    json_parent = argparse.ArgumentParser(add_help=False)
    # SUPPRESS so when --json appears at the parent level, the
    # subparser's "default False" doesn't quietly stomp it. We read
    # via `getattr(args, 'json', False)` everywhere instead.
    json_parent.add_argument(
        "--json", action="store_true",
        default=argparse.SUPPRESS, help="emit raw JSON output",
    )

    p = argparse.ArgumentParser(
        prog="trove",
        parents=[json_parent],
        description="Trove media-downloader / transcript-editor CLI.",
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    def _sub(name: str, **kw):
        return sub.add_parser(name, parents=[json_parent], **kw)

    s = _sub("serve", help="run the Trove web/API server")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=5000)
    s.set_defaults(func=cmd_serve)

    s = _sub("health", help="check that a Trove server is reachable")
    s.set_defaults(func=cmd_health)

    s = _sub("fetch", help="download a media URL")
    s.add_argument("url")
    s.add_argument("--mp3", action="store_true", help="audio-only (mp3) instead of mp4")
    s.add_argument("--transcribe", action="store_true",
                   help="auto-transcribe on success (requires an active model)")
    s.add_argument("--title", default=None, help="override the auto-detected title")
    s.add_argument("--wait", action="store_true", help="block until done/error")
    s.set_defaults(func=cmd_fetch)

    s = _sub("list", help="list all download jobs")
    s.set_defaults(func=cmd_list)

    for action in ("pause", "resume", "cancel"):
        s = _sub(action, help=f"{action} a download job by id")
        s.add_argument("id")
        s.set_defaults(func=lambda a, action=action: cmd_job_action(a, action))
    s = _sub("rm", help="dismiss a terminal job + delete its file")
    s.add_argument("id")
    s.set_defaults(func=lambda a: cmd_job_action(a, "dismiss"))

    s = _sub("transcribe", help="kick off transcription of a downloaded clip")
    s.add_argument("job_id")
    s.add_argument("--wait", action="store_true")
    s.set_defaults(func=cmd_transcribe)

    s = _sub("transcripts", help="list all transcripts")
    s.set_defaults(func=cmd_transcripts)

    s = _sub("transcript", help="fetch / export a transcript")
    s.add_argument("id")
    s.add_argument("-f", "--format", choices=("txt", "srt", "vtt", "json"), default="txt")
    s.add_argument("-o", "--output", help="write to a file instead of stdout")
    s.set_defaults(func=cmd_transcript)

    s = _sub("models", help="list whisper models")
    s.set_defaults(func=cmd_models)

    s = _sub("model-install", help="download + activate a model")
    s.add_argument("name", help="e.g. ggml-tiny.bin / ggml-base.bin")
    s.add_argument("--wait", action="store_true")
    s.set_defaults(func=cmd_model_install)

    s = _sub("model-use", help="set the active model")
    s.add_argument("name")
    s.set_defaults(func=cmd_model_use)

    s = _sub("model-rm", help="delete an installed model")
    s.add_argument("name")
    s.set_defaults(func=cmd_model_remove)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except TroveError as e:
        msg = e.body.get("error") if isinstance(e.body, dict) else e.body
        print(f"trove: {msg} (HTTP {e.status})", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
