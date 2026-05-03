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


# ----- MCP <-> CLI parity map ----------------------------------------
#
# Single source of truth pinning every MCP tool to its CLI counterpart.
# A test in tests/test_cli.py introspects the live FastMCP server and
# fails if anything here drifts — adding a new MCP tool forces adding
# either a CLI command for it or an explicit "no_cli_equivalent"
# acknowledgement here.
MCP_TO_CLI: dict[str, str] = {
    "list_jobs":               "list",
    "get_job":                 "get",
    "download_media":          "fetch",
    "bulk_download":           "fetch",   # `trove fetch URL [URL...]` covers both
    "pause_download":          "pause",
    "resume_download":         "resume",
    "cancel_download":         "cancel",
    "dismiss_download":        "rm",
    "list_transcripts":        "transcripts",
    "search_transcripts":      "search",
    "get_transcript_status":   "transcript-status",
    "transcribe":              "transcribe",
    "cancel_transcribe":       "transcribe-cancel",
    "get_transcript":          "transcript",
    "list_models":             "models",
    "install_model":           "model-install",
    "model_install_progress":  "model-progress",
    "set_active_model":        "model-use",
    "remove_model":            "model-rm",
    "storage_info":            "du",
}


# ----- branding -------------------------------------------------------

# Block-letter ASCII banner. Printed on `trove serve` (and bare `trove`)
# only — never on scripted subcommands so it can't pollute stdout when
# piping `trove --json list | jq`. Always written to stderr for the same
# reason and only when stderr is a TTY.
_BANNER = r"""
 ████████ ██████   ██████  ██    ██ ███████
    ██    ██   ██ ██    ██ ██    ██ ██
    ██    ██████  ██    ██ ██    ██ █████
    ██    ██   ██ ██    ██  ██  ██  ██
    ██    ██   ██  ██████    ████   ███████
"""


def _print_banner(subtitle: str = "") -> None:
    if not sys.stderr.isatty():
        return
    sys.stderr.write(_BANNER)
    if subtitle:
        sys.stderr.write(f"   {subtitle}\n")
    sys.stderr.write("\n")
    sys.stderr.flush()


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
    """Single-line table row for `trove list` — uses the new server-side
    ``progress_pct`` and ``human.speed`` so we don't duplicate formatting.
    """
    pct = f"{j.get('progress_pct', 0):>3d}%"
    title = (j.get("title") or j["url"])[:48]
    speed = (j.get("human") or {}).get("speed", "—")
    return f"{j['id']:<10}  {j['status']:<11}  {pct}  {speed:>10}  {title}"


def _format_tj_row(t: dict) -> str:
    h = t.get("human") or {}
    return (
        f"{t['id']:<10}  {t['status']:<10}  "
        f"{t['progress_pct']:>3}%  {h.get('elapsed','—'):>6}  "
        f"parent={t['parent_job_id']:<10}  "
        f"model={t.get('model_used') or '—'}"
    )


# ----- subcommands ----------------------------------------------------

def cmd_serve(args) -> int:
    """Start the Flask dev server in-process."""
    os.environ.setdefault("FLASK_ENV", "development")
    from app import create_app
    app = create_app()
    _print_banner(subtitle=f"self-hosted media · serving on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


def cmd_health(args) -> int:
    out = get("/api/v1/health")
    _print_json(out)
    return 0


def cmd_fetch(args) -> int:
    """Submit one or more URLs.

    Single URL  → POST /jobs (rich error mapping, can ``--wait``).
    Multiple URLs → POST /jobs/bulk (per-URL pass/fail array).
    """
    fmt = "audio" if args.mp3 else "video"
    auto_t = bool(args.transcribe)
    json_out = getattr(args, "json", False)

    urls = list(args.url)
    if len(urls) == 1:
        body = {"url": urls[0], "format": fmt, "auto_transcribe": auto_t}
        if args.title:
            body["title"] = args.title
        job = post("/api/v1/jobs", body=body)
        if json_out:
            _print_json(job)
        else:
            print(f"queued {job['id']}: {job.get('title') or job['url']}")
        if args.wait:
            return _wait_for_job(job["id"], json_out=json_out)
        return 0

    # Bulk path. ``--title`` is intentionally ignored for bulk submits
    # because we'd otherwise apply the same title to every URL — surely
    # not what the caller meant.
    if args.title:
        print("trove: --title ignored for bulk submit", file=sys.stderr)
    res = post("/api/v1/jobs/bulk", body={
        "urls": urls, "format": fmt, "auto_transcribe": auto_t,
    })
    if json_out:
        _print_json(res)
        # Bulk wait isn't useful (which job to wait on?). Skip --wait.
        return 0 if res["failed"] == 0 else 2
    print(f"submitted {res['submitted']} ok, {res['failed']} failed")
    for r in res["results"]:
        if "id" in r:
            print(f"  ok    {r['id']:<10}  {r['title']}")
        else:
            print(f"  fail  {r.get('error','?'):<20}  {r['url']}")
    if args.wait:
        ok_ids = [r["id"] for r in res["results"] if "id" in r]
        rc = 0
        for jid in ok_ids:
            sub_rc = _wait_for_job(jid, json_out=False)
            rc = rc or sub_rc
        return rc
    return 0 if res["failed"] == 0 else 2


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


def _list_query(args, *, key_field: str) -> str:
    """Build a ``?status=&limit=&offset=&order=`` query string from
    standard list-flag args."""
    q: list[str] = []
    if getattr(args, "status", None):
        q.append("status=" + urllib.parse.quote(args.status))
    if getattr(args, "limit", None):
        q.append(f"limit={int(args.limit)}")
    if getattr(args, "offset", None):
        q.append(f"offset={int(args.offset)}")
    if getattr(args, "order", None):
        q.append(f"order={args.order}")
    return ("?" + "&".join(q)) if q else ""


def _print_list_table(items: list[dict], header: str, fmt) -> None:
    if not items:
        print("(none)")
        return
    print(header)
    for it in items:
        print(fmt(it))


def cmd_list(args) -> int:
    json_out = getattr(args, "json", False)
    path = "/api/v1/jobs" + _list_query(args, key_field="jobs")

    def _render(data: dict) -> None:
        if json_out:
            _print_json(data)
            return
        _print_list_table(
            data["jobs"],
            f"{'ID':<10}  {'STATUS':<11}     %       SPEED  TITLE",
            _format_job_row,
        )
        if data.get("total", 0) > data.get("returned", 0):
            print(f"  (showing {data['returned']} of {data['total']} — use --offset)")

    if not getattr(args, "watch", False):
        _render(get(path))
        return 0
    return _watch_loop(lambda: get(path), _render)


def _render_job_card(j: dict, *, json_out: bool) -> None:
    if json_out:
        _print_json(j)
        return
    h = j.get("human") or {}
    print(f"{j['id']}  {j['status']}")
    print(f"  url:       {j['url']}")
    print(f"  title:     {j.get('title') or '—'}")
    print(f"  format:    {j.get('format_choice','?')}")
    print(f"  progress:  {h.get('summary','—')}")
    print(f"  elapsed:   {h.get('elapsed','—')}    eta: {h.get('eta','—')}")
    if j.get("filename"):
        print(f"  file:      {j['filename']}")
    if j.get("error_message"):
        print(f"  error:     {j['error_category']} — {j['error_message']}")


def cmd_get(args) -> int:
    """Inspect a single download job — same fields the MCP `get_job`
    tool surfaces (raw + ``human.summary``)."""
    json_out = getattr(args, "json", False)
    fetch = lambda: get(f"/api/v1/jobs/{args.id}")
    render = lambda j: _render_job_card(j, json_out=json_out)
    if not getattr(args, "watch", False):
        render(fetch())
        return 0
    return _watch_loop(fetch, render,
                       terminal_check=lambda j: j["status"]
                       in ("done", "error", "cancelled"))


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
    json_out = getattr(args, "json", False)
    path = "/api/v1/transcripts" + _list_query(args, key_field="transcripts")

    def _render(data: dict) -> None:
        if json_out:
            _print_json(data)
            return
        _print_list_table(
            data["transcripts"],
            f"{'ID':<10}  {'STATUS':<10}    %  ELAPSED  PARENT     MODEL",
            _format_tj_row,
        )
        if data.get("total", 0) > data.get("returned", 0):
            print(f"  (showing {data['returned']} of {data['total']} — use --offset)")

    if not getattr(args, "watch", False):
        _render(get(path))
        return 0
    return _watch_loop(lambda: get(path), _render)


def _render_transcript_card(t: dict, *, json_out: bool) -> None:
    if json_out:
        _print_json(t)
        return
    h = t.get("human") or {}
    print(f"{t['id']}  {t['status']}")
    print(f"  parent:   {t['parent_job_id']}")
    print(f"  model:    {t.get('model_used') or '—'}")
    print(f"  progress: {h.get('summary','—')}")
    print(f"  audio:    {h.get('audio_duration','—')}    elapsed: {h.get('elapsed','—')}")
    if t.get("language_detected"):
        print(f"  lang:     {t['language_detected']}")
    if t.get("error_message"):
        print(f"  error:    {t['error_category']} — {t['error_message']}")


def cmd_transcript_status(args) -> int:
    """Poll a single transcribe job (mirror of MCP `get_transcript_status`)."""
    json_out = getattr(args, "json", False)
    fetch = lambda: get(f"/api/v1/transcripts/{args.id}")
    render = lambda t: _render_transcript_card(t, json_out=json_out)
    if not getattr(args, "watch", False):
        render(fetch())
        return 0
    return _watch_loop(fetch, render,
                       terminal_check=lambda t: t["status"]
                       in ("done", "error", "cancelled"))


# ----- watch loop ----------------------------------------------------

def _watch_loop(fetch, render, *,
                terminal_check=None, interval: float = 1.0) -> int:
    """Common ``--watch`` driver.

    Re-runs ``fetch()`` every *interval* seconds, calls ``render()``
    when the payload actually changes (so a calm queue doesn't redraw
    forever), and exits cleanly on Ctrl-C. If ``terminal_check`` is
    supplied and returns True, the loop exits with rc=0 (or 2 when
    the resource ended in an error state).
    """
    last = object()
    try:
        while True:
            data = fetch()
            payload = json.dumps(data, sort_keys=True, default=str)
            if payload != last:
                # Soft "clear screen" — only when running in a TTY,
                # otherwise we just pile output (useful for piping).
                if sys.stdout.isatty():
                    sys.stdout.write("\x1b[2J\x1b[H")
                render(data)
                sys.stdout.flush()
                last = payload
            if terminal_check and terminal_check(data):
                status = data.get("status")
                return 0 if status == "done" else (2 if status in ("error", "cancelled") else 0)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 130


def cmd_cancel_transcribe(args) -> int:
    out = post(f"/api/v1/transcripts/{args.id}/cancel")
    if out is None:
        print(f"{args.id}: cancel requested")
    else:
        _print_json(out) if getattr(args, "json", False) else print(_format_tj_row(out))
    return 0


def cmd_model_progress(args) -> int:
    p = get("/api/v1/models/install-progress")
    if getattr(args, "json", False):
        _print_json(p)
        return 0
    if not p.get("downloading") and not p.get("done"):
        print("(no install in progress)")
        return 0
    rec, tot = p.get("received", 0), p.get("total", 0) or 1
    print(f"{p.get('name','?')}: {int(rec/tot*100)}% "
          f"({_human_bytes(rec)}/{_human_bytes(tot)}) "
          f"{'done' if p.get('done') else 'downloading'}")
    if p.get("error"):
        print(f"  error: {p['error']}")
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


def cmd_du(args) -> int:
    """Disk-usage report — what's eating space in `downloads/`."""
    rep = get("/api/v1/storage")
    if getattr(args, "json", False):
        _print_json(rep)
        return 0
    print(f"download_dir: {rep['download_dir']}")
    print(f"total: {_human_bytes(rep['total_bytes'])} "
          f"({rep['file_count']} files)")
    if rep["by_job"]:
        print()
        print(f"{'ID':<10}  {'SIZE':>10}  TITLE")
        for row in rep["by_job"]:
            print(f"{row['id']:<10}  {_human_bytes(row['bytes']):>10}  "
                  f"{(row['title'] or '')[:60]}")
    if rep["orphan_files"]:
        print()
        print(f"orphans: {_human_bytes(rep['orphan_bytes'])} "
              f"({len(rep['orphan_files'])} files)")
        for f in rep["orphan_files"][:10]:
            print(f"  {_human_bytes(f['bytes']):>10}  {f['name']}")
    return 0


def cmd_search(args) -> int:
    """Substring-search across completed transcripts."""
    qs = "?q=" + urllib.parse.quote(args.query)
    if args.limit:
        qs += f"&limit={int(args.limit)}"
    if args.context is not None:
        qs += f"&context={int(args.context)}"
    res = get("/api/v1/transcripts/search" + qs)
    if getattr(args, "json", False):
        _print_json(res)
        return 0
    matches = res.get("matches") or []
    if not matches:
        print(f"(no matches for {args.query!r})")
        return 1
    for m in matches:
        ts = _format_seconds(m["start_seconds"])
        print(f"{m['transcript_id']:<10}  {ts}  {(m['title'] or '')[:40]}")
        print(f"  {m['snippet']}")
    print(f"\n{len(matches)} match{'es' if len(matches) != 1 else ''}")
    return 0


def _format_seconds(s: float) -> str:
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def cmd_events(args) -> int:
    """Tail the SSE event stream. Press Ctrl-C to stop."""
    qs = []
    if args.max_events:
        qs.append(f"max_events={int(args.max_events)}")
    if args.interval is not None:
        qs.append(f"interval={float(args.interval)}")
    path = "/api/v1/events" + (("?" + "&".join(qs)) if qs else "")
    url = _base_url() + path
    req = urllib.request.Request(url, headers=_headers())
    json_out = getattr(args, "json", False)
    try:
        with urllib.request.urlopen(req, timeout=None) as resp:
            buf = b""
            for chunk in iter(lambda: resp.read(1024), b""):
                buf += chunk
                # SSE messages are separated by blank lines.
                while b"\n\n" in buf:
                    msg, buf = buf.split(b"\n\n", 1)
                    payload = _parse_sse(msg.decode("utf-8", errors="replace"))
                    if payload is None:
                        continue
                    if json_out:
                        sys.stdout.write(json.dumps(payload) + "\n")
                    else:
                        ts = payload.get("ts", time.time())
                        nj = len(payload.get("jobs") or [])
                        nt = len(payload.get("transcripts") or [])
                        print(f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] "
                              f"jobs={nj} transcripts={nt}")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        return 130
    except urllib.error.URLError as e:
        print(f"trove: events stream closed ({e.reason})", file=sys.stderr)
        return 1
    return 0


def _parse_sse(message: str) -> dict | None:
    """Pull the JSON ``data:`` payload out of one SSE frame."""
    data_lines = []
    for line in message.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except ValueError:
        return None


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

    s = _sub("fetch", help="download one or more media URLs")
    s.add_argument("url", nargs="+",
                   help="one or more URLs (multiple → bulk submit)")
    s.add_argument("--mp3", action="store_true", help="audio-only (mp3) instead of mp4")
    s.add_argument("--transcribe", action="store_true",
                   help="auto-transcribe on success (requires an active model)")
    s.add_argument("--title", default=None,
                   help="override the auto-detected title (single URL only)")
    s.add_argument("--wait", action="store_true", help="block until done/error")
    s.set_defaults(func=cmd_fetch)

    def _add_list_flags(p):
        p.add_argument("--status", default=None,
                       help="comma-separated filter (e.g. done,error)")
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--offset", type=int, default=None)
        p.add_argument("--order", choices=("newest", "oldest"), default=None)
        p.add_argument("--watch", action="store_true",
                       help="redraw on change until Ctrl-C")

    s = _sub("list", help="list download jobs (paginated, filterable)")
    _add_list_flags(s)
    s.set_defaults(func=cmd_list)

    s = _sub("get", help="inspect one download job (rich progress)")
    s.add_argument("id")
    s.add_argument("--watch", action="store_true",
                   help="redraw every second until terminal state")
    s.set_defaults(func=cmd_get)

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

    s = _sub("transcripts", help="list transcripts (paginated, filterable)")
    _add_list_flags(s)
    s.set_defaults(func=cmd_transcripts)

    s = _sub("transcript-status", help="poll one transcribe job")
    s.add_argument("id")
    s.add_argument("--watch", action="store_true",
                   help="redraw every second until terminal state")
    s.set_defaults(func=cmd_transcript_status)

    s = _sub("search", help="substring-search across completed transcripts")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--context", type=int, default=None,
                   help="characters of context around each match")
    s.set_defaults(func=cmd_search)

    s = _sub("du", help="disk-usage report for the download directory")
    s.set_defaults(func=cmd_du)

    s = _sub("events", help="tail the SSE event stream")
    s.add_argument("--max-events", type=int, default=0,
                   help="exit after N events (test hook; 0 = unbounded)")
    s.add_argument("--interval", type=float, default=None,
                   help="server-side poll interval, seconds")
    s.set_defaults(func=cmd_events)

    s = _sub("transcribe-cancel", help="cancel an in-flight transcribe")
    s.add_argument("id")
    s.set_defaults(func=cmd_cancel_transcribe)

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

    s = _sub("model-progress", help="check pending model-install progress")
    s.set_defaults(func=cmd_model_progress)

    s = _sub("model-use", help="set the active model")
    s.add_argument("name")
    s.set_defaults(func=cmd_model_use)

    s = _sub("model-rm", help="delete an installed model")
    s.add_argument("name")
    s.set_defaults(func=cmd_model_remove)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # Bare `trove` (no subcommand) → banner + help instead of an
    # unfriendly argparse error. argparse's `required=True` on the
    # subparsers would otherwise just print "error: the following
    # arguments are required: <command>".
    #
    # Only fire on real bare-shell invocations (argv is None AND the
    # process was launched with no args). Programmatic callers passing
    # ``main([])`` get deterministic argparse behavior, not a surprise
    # banner that depends on the host process's argv.
    if argv is None and len(sys.argv) == 1:
        _print_banner(subtitle="self-hosted media · run `trove --help`")
        parser.print_help()
        return 0
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
