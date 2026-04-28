# Trove Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a fresh `github.com/afk1997/trove` repo containing a hardened, redesigned, htmx-powered media downloader: 19 audit fixes from the prior reclip codebase + new branding (Trove, "Save things you care about") + new visual design (warm, light-default, coral accent, Inter typography) + a stack rewrite (Flask + htmx + Tailwind standalone CLI + Alpine.js, no Node runtime).

**Architecture:** Backend split into four modules (`app.py` routes glue, `jobs.py` JobManager, `safety.py` validation/auth/limits/headers, `runner.py` yt-dlp argv builder + subprocess wrapper). Frontend is server-rendered Jinja partials swapped by htmx; Tailwind CSS built once at deploy time; Alpine.js for tiny interactions. Single-process Flask app, single-stage runtime container, ffmpeg + yt-dlp installed in the image.

**Tech Stack:** Python 3.12, Flask, yt-dlp, ffmpeg, pytest, htmx 2.x (vendored), Alpine.js 3.x (vendored), Tailwind CSS standalone CLI binary (downloaded at build), Inter via Google Fonts.

**Working directory after Task 1:** `/Users/kaivan108icloud.com/Downloads/trove/` (fresh, no shared git history with reclip-source).

**Spec:** `docs/superpowers/specs/2026-04-28-trove-phase-1-design.md` (carried over to the new repo in Task 1).

---

## File Structure

```
trove/
├── app.py                   Flask routes + glue (~150 LoC)
├── jobs.py                  JobManager: ThreadPool, TTL, cancellation
├── safety.py                URL validator, auth, rate limit, security headers
├── runner.py                yt-dlp argv builder + subprocess execution
├── tools/                   (gitignored) Tailwind CLI binary lives here
├── tailwind.config.js       Tailwind content paths + theme tokens
├── styles/
│   └── input.css            @tailwind directives + CSS custom properties
├── templates/
│   ├── base.html            <head>, dark-mode bootstrap, mounts vendor JS
│   ├── index.html           extends base — input, format toggle, queue
│   └── partials/
│       ├── card.html        Single-job card (htmx fragment target)
│       └── card_list.html   Queue container (htmx target for /api/info-card)
├── static/
│   ├── app.css              (gitignored) Built Tailwind output
│   ├── vendor/
│   │   ├── htmx.min.js      htmx 2.x (committed)
│   │   └── alpine.min.js    Alpine 3.x (committed)
│   └── favicon.svg          Coral T glyph
├── tests/
│   ├── conftest.py          pytest fixtures (Flask test client, tmp downloads)
│   ├── test_safety.py       URL validator, auth, rate limit, args injection
│   ├── test_runner.py       argv builder, subprocess mocking, error mapping
│   └── test_endpoints.py    /api/info-card, /api/job/<id>/cancel HTML fragments
├── trove.sh                 Auto-update yt-dlp, build CSS, run Flask
├── Dockerfile               Multi-stage: build CSS → runtime
├── requirements.txt         Flask, yt-dlp + (dev) pytest
├── .gitignore               venv/, downloads/, tools/tailwindcss, static/app.css
├── LICENSE                  MIT, Avery Gan + Kaivan Doshi
├── README.md                Tagline, quick start, attribution footer
└── docs/superpowers/
    ├── specs/2026-04-28-trove-phase-1-design.md
    └── plans/2026-04-28-trove-phase-1.md
```

---

## Phase A — Bootstrap fresh repo

### Task A1: Create the new working directory and seed it

**Files:**
- Create: `/Users/kaivan108icloud.com/Downloads/trove/`
- Copy: spec doc, plan doc

- [ ] **Step 1: Create the new dir and copy docs**

```bash
mkdir -p /Users/kaivan108icloud.com/Downloads/trove/docs/superpowers/specs
mkdir -p /Users/kaivan108icloud.com/Downloads/trove/docs/superpowers/plans
cp /Users/kaivan108icloud.com/Downloads/reclip-source/docs/superpowers/specs/2026-04-28-trove-phase-1-design.md \
   /Users/kaivan108icloud.com/Downloads/trove/docs/superpowers/specs/
cp /Users/kaivan108icloud.com/Downloads/reclip-source/docs/superpowers/plans/2026-04-28-trove-phase-1.md \
   /Users/kaivan108icloud.com/Downloads/trove/docs/superpowers/plans/
ls -R /Users/kaivan108icloud.com/Downloads/trove/
```

Expected: prints the two doc paths under `docs/superpowers/`.

- [ ] **Step 2: Initialize git with afk1997 identity (local config, not global)**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
git init -b main
git config user.name "Kaivan Doshi"
git config user.email "kaivandoshi1997@gmail.com"
git config commit.gpgsign false
git status
```

Expected: branch `main`, two untracked files under `docs/`.

- [ ] **Step 3: Commit no-op until we have real files**

(Skip — we'll make the first commit in Task A3 once LICENSE/README/.gitignore are in.)

### Task A2: Write LICENSE with both copyright lines

**Files:**
- Create: `/Users/kaivan108icloud.com/Downloads/trove/LICENSE`

- [ ] **Step 1: Write LICENSE**

```
MIT License

Copyright (c) 2024 Avery Gan
Copyright (c) 2026 Kaivan Doshi (https://github.com/afk1997)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Verify**

```bash
head -4 /Users/kaivan108icloud.com/Downloads/trove/LICENSE
```

Expected: shows the MIT title and both copyright lines.

### Task A3: .gitignore, requirements.txt, README skeleton, first commit

**Files:**
- Create: `.gitignore`, `requirements.txt`, `README.md`

- [ ] **Step 1: Write .gitignore**

```gitignore
venv/
__pycache__/
*.pyc
.DS_Store
.env
.env.local

# Build artifacts
static/app.css

# Tooling binaries (downloaded by trove.sh)
tools/tailwindcss
tools/

# Downloads (runtime)
downloads/

# IDE
.vscode/
.idea/
```

- [ ] **Step 2: Write requirements.txt**

```
flask>=3.0
yt-dlp>=2025.10
pytest>=8.0
```

- [ ] **Step 3: Write README.md (skeleton — fleshed out in Task G2)**

```markdown
# Trove

**Save things you care about.**

A self-hosted, browser-based downloader for video and audio from YouTube, TikTok, Instagram, Vimeo, and ~1000 other sites — powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

## Quick start

```bash
brew install yt-dlp ffmpeg    # macOS — or apt install ffmpeg && pip install yt-dlp
git clone https://github.com/afk1997/trove.git
cd trove
./trove.sh
```

Open **http://localhost:8899**.

Or with Docker:

```bash
docker build -t trove . && docker run -p 8899:8899 trove
```

## Status

Phase 1 in progress — see `docs/superpowers/specs/2026-04-28-trove-phase-1-design.md`.

## License

MIT. See [LICENSE](LICENSE).

---

Originally based on [averygan/reclip](https://github.com/averygan/reclip) (MIT). Substantially rewritten and rebranded as Trove in 2026.
```

- [ ] **Step 4: First commit**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
git add LICENSE .gitignore requirements.txt README.md docs/
git commit -m "chore: bootstrap Trove repo"
git log --oneline
```

Expected: one commit visible by Kaivan Doshi.

---

## Phase B — Backend modules (TDD)

All Python work happens in the venv. Bootstrap once before Task B1.

### Task B0: Set up venv and pytest skeleton

**Files:**
- Create: `tests/__init__.py`, `tests/conftest.py`, `pyproject.toml`

- [ ] **Step 1: Create venv and install deps**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
pip list | grep -E '^(Flask|yt-dlp|pytest)'
```

Expected: all three listed.

- [ ] **Step 2: Write minimal pyproject.toml for pytest discovery**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
```

- [ ] **Step 3: Empty tests/__init__.py and conftest.py placeholder**

```python
# tests/__init__.py — empty
```

```python
# tests/conftest.py
import pytest
```

- [ ] **Step 4: Confirm pytest collects nothing yet**

```bash
source venv/bin/activate && python -m pytest
```

Expected: `no tests ran` exit 5 (or 0 with "collected 0 items").

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/
git commit -m "chore: pytest skeleton"
```

### Task B1: safety.is_safe_url — URL validation

**Files:**
- Create: `safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_safety.py
import pytest
from safety import is_safe_url


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "http://vimeo.com/123",
    "https://www.tiktok.com/@user/video/1234",
])
def test_is_safe_url_accepts_public(url):
    assert is_safe_url(url) is True


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://localhost:8899/",
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "ftp://example.com/foo",
    "javascript:alert(1)",
    "--exec=touch /tmp/pwned",
    "-o /etc/whatever",
    "",
    "not a url",
])
def test_is_safe_url_rejects_unsafe(url):
    assert is_safe_url(url) is False
```

- [ ] **Step 2: Run test (expect ImportError)**

```bash
source venv/bin/activate && python -m pytest tests/test_safety.py -v
```

Expected: collection error / ModuleNotFoundError for `safety`.

- [ ] **Step 3: Implement safety.is_safe_url**

```python
# safety.py
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlparse


_ALLOWED_SCHEMES = {"http", "https"}

# RFC1918 + loopback + link-local + reserved ranges we never want to hit.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(net) for net in [
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "0.0.0.0/8",
        "100.64.0.0/10",
    ]
]


def _is_blocked_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _BLOCKED_NETWORKS)


def is_safe_url(url: str) -> bool:
    """Return True only if url is a public http(s) URL we're willing to fetch.

    Rejects: non-http schemes, anything beginning with '-' (CLI option-shaped),
    private/loopback/link-local IPs, hostnames that resolve to those.
    """
    if not url or not isinstance(url, str):
        return False
    s = url.strip()
    if not s:
        return False
    # Refuse anything that looks like a CLI option — guards against argv injection
    # even though we also use `--` separator at the subprocess layer.
    if s.startswith("-"):
        return False
    try:
        parsed = urlparse(s)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    host = parsed.hostname
    if not host:
        return False
    host = host.lower()
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return False
    # If host is a bare IP literal, check it directly.
    if _is_blocked_ip(host):
        return False
    # Otherwise resolve and check every returned address.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable — let yt-dlp surface the network error rather than block here.
        return True
    for info in infos:
        addr = info[4][0]
        if _is_blocked_ip(addr):
            return False
    return True
```

- [ ] **Step 4: Run tests (expect green)**

```bash
python -m pytest tests/test_safety.py -v
```

Expected: all parametrized cases pass.

- [ ] **Step 5: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "feat(safety): is_safe_url validator with scheme + private-IP blocks"
```

### Task B2: safety.token_required — auth decorator

**Files:**
- Modify: `safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_safety.py`:

```python
import os
from flask import Flask
from safety import token_required


def _make_app(token: str | None):
    app = Flask(__name__)
    if token is not None:
        os.environ["TROVE_TOKEN"] = token
    else:
        os.environ.pop("TROVE_TOKEN", None)

    @app.get("/secret")
    @token_required
    def secret():
        return "ok"

    return app


def test_token_required_off_by_default():
    app = _make_app(None)
    client = app.test_client()
    assert client.get("/secret").status_code == 200


def test_token_required_rejects_missing_header():
    app = _make_app("hunter2")
    client = app.test_client()
    assert client.get("/secret").status_code == 401


def test_token_required_rejects_wrong_token():
    app = _make_app("hunter2")
    client = app.test_client()
    r = client.get("/secret", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_token_required_accepts_correct_token():
    app = _make_app("hunter2")
    client = app.test_client()
    r = client.get("/secret", headers={"Authorization": "Bearer hunter2"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests (expect ImportError on token_required)**

```bash
python -m pytest tests/test_safety.py -v
```

Expected: collection-time error.

- [ ] **Step 3: Implement token_required**

Append to `safety.py`:

```python
import os
from functools import wraps
from flask import request, jsonify


def token_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = os.environ.get("TROVE_TOKEN", "").strip()
        if not token:
            return view(*args, **kwargs)
        header = request.headers.get("Authorization", "")
        if header == f"Bearer {token}":
            return view(*args, **kwargs)
        return jsonify({"error": "unauthorized"}), 401
    return wrapper
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_safety.py -v
```

Expected: all four token tests pass.

- [ ] **Step 5: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "feat(safety): token_required decorator (TROVE_TOKEN env)"
```

### Task B3: safety.RateLimiter — in-process token bucket

**Files:**
- Modify: `safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_safety.py`:

```python
import time
from safety import RateLimiter


def test_rate_limiter_allows_under_cap():
    rl = RateLimiter(rate=5, per_seconds=60)
    for _ in range(5):
        assert rl.allow("1.2.3.4") is True


def test_rate_limiter_blocks_over_cap():
    rl = RateLimiter(rate=3, per_seconds=60)
    for _ in range(3):
        assert rl.allow("1.2.3.4") is True
    assert rl.allow("1.2.3.4") is False


def test_rate_limiter_per_ip_isolated():
    rl = RateLimiter(rate=2, per_seconds=60)
    assert rl.allow("1.1.1.1") is True
    assert rl.allow("1.1.1.1") is True
    assert rl.allow("1.1.1.1") is False
    assert rl.allow("2.2.2.2") is True


def test_rate_limiter_window_resets(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("safety.time.monotonic", lambda: now[0])
    rl = RateLimiter(rate=2, per_seconds=10)
    assert rl.allow("x") is True
    assert rl.allow("x") is True
    assert rl.allow("x") is False
    now[0] = 11.0
    assert rl.allow("x") is True
```

- [ ] **Step 2: Run tests (expect ImportError)**

```bash
python -m pytest tests/test_safety.py -v
```

- [ ] **Step 3: Implement RateLimiter**

Append to `safety.py`:

```python
import time
from collections import deque
from threading import Lock


class RateLimiter:
    """Sliding-window per-key rate limiter. In-process only."""

    def __init__(self, rate: int, per_seconds: int):
        self.rate = rate
        self.per_seconds = per_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        if self.rate <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.per_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.rate:
                return False
            q.append(now)
            return True
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_safety.py -v
```

Expected: all rate-limiter tests pass.

- [ ] **Step 5: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "feat(safety): RateLimiter sliding-window per-key bucket"
```

### Task B4: safety.attach_security_headers + CSP nonce

**Files:**
- Modify: `safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
from safety import attach_security_headers


def test_attach_security_headers_sets_basic_headers():
    app = Flask(__name__)
    attach_security_headers(app)

    @app.get("/")
    def hello():
        return "hi"

    r = app.test_client().get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_attach_security_headers_includes_per_request_nonce():
    app = Flask(__name__)
    attach_security_headers(app)

    @app.get("/")
    def hello():
        from flask import g
        return g.csp_nonce

    client = app.test_client()
    r1 = client.get("/")
    r2 = client.get("/")
    nonce1 = r1.get_data(as_text=True)
    nonce2 = r2.get_data(as_text=True)
    assert nonce1 and nonce2 and nonce1 != nonce2
    assert f"'nonce-{nonce1}'" in r1.headers["Content-Security-Policy"]
```

- [ ] **Step 2: Run tests (expect ImportError)**

```bash
python -m pytest tests/test_safety.py -v
```

- [ ] **Step 3: Implement attach_security_headers**

Append to `safety.py`:

```python
import secrets
from flask import g


def attach_security_headers(app):
    """Mount per-request CSP nonce + standard security headers on a Flask app."""

    @app.before_request
    def _set_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def _set_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"img-src 'self' https: data:; "
            f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response

    return app
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_safety.py -v
```

- [ ] **Step 5: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "feat(safety): per-request CSP nonce + security headers"
```

### Task B5: runner.build_argv — yt-dlp argv with `--` separator

**Files:**
- Create: `runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_runner.py
import os
import pytest
from runner import build_info_argv, build_download_argv


def test_info_argv_dash_dash_separator():
    argv = build_info_argv("https://example.com/video")
    assert argv[-2:] == ["--", "https://example.com/video"]
    assert argv[0] == "yt-dlp"
    assert "--no-playlist" in argv
    assert "-j" in argv


def test_info_argv_injects_cookies_when_env_set(monkeypatch):
    monkeypatch.setenv("TROVE_COOKIES_FROM_BROWSER", "safari")
    argv = build_info_argv("https://example.com/video")
    assert "--cookies-from-browser" in argv
    assert argv[argv.index("--cookies-from-browser") + 1] == "safari"


def test_info_argv_ignores_blank_cookie_env(monkeypatch):
    monkeypatch.setenv("TROVE_COOKIES_FROM_BROWSER", "")
    argv = build_info_argv("https://example.com/video")
    assert "--cookies-from-browser" not in argv


def test_download_argv_audio_mode(tmp_path):
    argv = build_download_argv(
        url="https://example.com/v",
        out_template=str(tmp_path / "out.%(ext)s"),
        format_choice="audio",
        format_id=None,
    )
    assert "-x" in argv
    assert "--audio-format" in argv
    assert argv[argv.index("--audio-format") + 1] == "mp3"
    assert argv[-2:] == ["--", "https://example.com/v"]


def test_download_argv_video_with_format_id(tmp_path):
    argv = build_download_argv(
        url="https://example.com/v",
        out_template=str(tmp_path / "out.%(ext)s"),
        format_choice="video",
        format_id="137",
    )
    assert "-f" in argv
    assert argv[argv.index("-f") + 1] == "137+bestaudio/best"
    assert "--merge-output-format" in argv
    assert argv[argv.index("--merge-output-format") + 1] == "mp4"
    assert argv[-2:] == ["--", "https://example.com/v"]


def test_download_argv_video_default_format(tmp_path):
    argv = build_download_argv(
        url="https://example.com/v",
        out_template=str(tmp_path / "out.%(ext)s"),
        format_choice="video",
        format_id=None,
    )
    assert argv[argv.index("-f") + 1] == "bestvideo+bestaudio/best"


def test_download_argv_rejects_argv_lookalike_url():
    with pytest.raises(ValueError):
        build_download_argv(
            url="--exec=touch /tmp/pwned",
            out_template="x",
            format_choice="video",
            format_id=None,
        )
```

- [ ] **Step 2: Run tests (expect ImportError)**

```bash
python -m pytest tests/test_runner.py -v
```

- [ ] **Step 3: Implement runner.build_*_argv**

```python
# runner.py
from __future__ import annotations
import os


def _cookie_args() -> list[str]:
    browser = os.environ.get("TROVE_COOKIES_FROM_BROWSER", "").strip()
    if not browser:
        return []
    return ["--cookies-from-browser", browser]


def _check_url_shape(url: str) -> None:
    if not url or url.startswith("-"):
        raise ValueError("URL has CLI-option shape; rejected")


def build_info_argv(url: str) -> list[str]:
    """Build argv for `yt-dlp -j` (info dump). Always uses `--` separator."""
    _check_url_shape(url)
    return [
        "yt-dlp",
        "--no-playlist",
        "-j",
        *_cookie_args(),
        "--",
        url,
    ]


def build_download_argv(
    *,
    url: str,
    out_template: str,
    format_choice: str,
    format_id: str | None,
) -> list[str]:
    """Build argv for the actual download. Always uses `--` separator."""
    _check_url_shape(url)
    argv: list[str] = [
        "yt-dlp",
        "--no-playlist",
        "-o", out_template,
        *_cookie_args(),
    ]
    if format_choice == "audio":
        argv += ["-x", "--audio-format", "mp3"]
    elif format_id:
        argv += ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", "mp4"]
    else:
        argv += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]
    argv += ["--", url]
    return argv
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_runner.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add runner.py tests/test_runner.py
git commit -m "feat(runner): yt-dlp argv builders with -- separator and cookies"
```

### Task B6: runner.classify_error + runner.run_info + runner.run_download

**Files:**
- Modify: `runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_runner.py`:

```python
from runner import classify_error


@pytest.mark.parametrize("stderr,expected", [
    ("ERROR: Unsupported URL: foo", "unsupported_url"),
    ("ERROR: [youtube] Video unavailable", "private_or_unavailable"),
    ("ERROR: Private video. Sign in if you've been granted access", "private_or_unavailable"),
    ("ERROR: Sign in to confirm your age", "auth_required"),
    ("ERROR: This video is not available in your country", "geo_restricted"),
    ("ERROR: HTTP Error 403: Forbidden", "auth_required"),
    ("ERROR: HTTP Error 429: Too Many Requests", "rate_limited"),
    ("ERROR: HTTP Error 404: Not Found", "private_or_unavailable"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "auth_required"),
    ("ERROR: [generic] some weird thing", "unknown"),
    ("ERROR: Unable to connect to proxy", "network"),
    ("ERROR: Read timed out.", "timeout"),
    ("", "unknown"),
])
def test_classify_error(stderr, expected):
    assert classify_error(stderr) == expected
```

- [ ] **Step 2: Run tests (expect ImportError)**

```bash
python -m pytest tests/test_runner.py -v
```

- [ ] **Step 3: Implement classify_error**

Append to `runner.py`:

```python
def classify_error(stderr: str) -> str:
    """Map yt-dlp stderr to a stable category enum string."""
    s = (stderr or "").lower()
    if not s:
        return "unknown"
    if "unsupported url" in s:
        return "unsupported_url"
    if "sign in" in s or "http error 401" in s or "http error 403" in s:
        return "auth_required"
    if "http error 429" in s or "too many requests" in s or "rate limit" in s:
        return "rate_limited"
    if "not available in your country" in s or "geo" in s and "restrict" in s:
        return "geo_restricted"
    if "video unavailable" in s or "private video" in s or "http error 404" in s:
        return "private_or_unavailable"
    if "timed out" in s or "timeout" in s:
        return "timeout"
    if "unable to connect" in s or "network" in s or "name or service not known" in s:
        return "network"
    return "unknown"
```

- [ ] **Step 4: Run classify tests**

```bash
python -m pytest tests/test_runner.py::test_classify_error -v
```

Expected: pass.

- [ ] **Step 5: Add tests for run_info (mocked subprocess)**

Append:

```python
import json
from unittest.mock import patch
from runner import run_info, InfoResult


def test_run_info_success(monkeypatch):
    fake_stdout = json.dumps({
        "title": "T",
        "thumbnail": "https://x/y.jpg",
        "duration": 30,
        "uploader": "U",
        "formats": [
            {"format_id": "137", "height": 1080, "vcodec": "avc1", "tbr": 5000},
            {"format_id": "136", "height": 720, "vcodec": "avc1", "tbr": 2500},
        ],
    })

    class FakeCompleted:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_info("https://example.com/v")
    assert isinstance(res, InfoResult)
    assert res.title == "T"
    assert res.uploader == "U"
    assert res.duration == 30
    assert len(res.formats) == 2
    assert res.formats[0]["height"] == 1080
    assert res.formats[0]["label"] == "1080p"


def test_run_info_handles_multiline_stdout(monkeypatch):
    obj = {"title": "first", "thumbnail": "", "duration": 0, "uploader": "", "formats": []}
    fake = json.dumps(obj) + "\n" + json.dumps({"title": "second"})

    class FakeCompleted:
        returncode = 0
        stdout = fake
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_info("https://example.com/v")
    assert res.title == "first"


def test_run_info_returns_error_on_nonzero(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "ERROR: HTTP Error 403: Forbidden"

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_info("https://example.com/v")
    assert res.error_category == "auth_required"
    assert res.title is None
```

- [ ] **Step 6: Implement run_info**

Append to `runner.py`:

```python
import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class InfoResult:
    title: str | None = None
    thumbnail: str = ""
    duration: int | None = None
    uploader: str = ""
    formats: list[dict] = field(default_factory=list)
    error_category: str | None = None
    error_raw: str = ""


def _build_quality_options(raw_formats: list[dict]) -> list[dict]:
    """Pick the best (highest tbr) format per resolution, sorted desc by height."""
    best_by_height: dict[int, dict] = {}
    for f in raw_formats:
        h = f.get("height")
        if not h or f.get("vcodec", "none") == "none":
            continue
        tbr = f.get("tbr") or 0
        if h not in best_by_height or tbr > (best_by_height[h].get("tbr") or 0):
            best_by_height[h] = f
    out = [
        {"id": f["format_id"], "label": f"{h}p", "height": h}
        for h, f in best_by_height.items()
    ]
    out.sort(key=lambda x: x["height"], reverse=True)
    return out


def run_info(url: str, *, timeout: int = 60) -> InfoResult:
    argv = build_info_argv(url)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return InfoResult(error_category="timeout", error_raw="info fetch timed out")
    if proc.returncode != 0:
        return InfoResult(
            error_category=classify_error(proc.stderr),
            error_raw=proc.stderr.strip(),
        )
    line = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return InfoResult(error_category="unknown", error_raw="invalid JSON from yt-dlp")
    return InfoResult(
        title=data.get("title", ""),
        thumbnail=data.get("thumbnail", "") or "",
        duration=data.get("duration"),
        uploader=data.get("uploader", "") or "",
        formats=_build_quality_options(data.get("formats", [])),
    )
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/test_runner.py -v
```

Expected: all pass including the three new run_info tests.

- [ ] **Step 8: Add run_download tests + implementation**

Append to `tests/test_runner.py`:

```python
from runner import run_download, DownloadResult


def test_run_download_success(monkeypatch, tmp_path):
    out_template = str(tmp_path / "abc.%(ext)s")
    target = tmp_path / "abc.mp4"
    target.write_bytes(b"fakempegdata")

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="video",
        format_id=None,
    )
    assert isinstance(res, DownloadResult)
    assert res.error_category is None
    assert res.file_path == str(target)


def test_run_download_audio_must_be_mp3(monkeypatch, tmp_path):
    out_template = str(tmp_path / "abc.%(ext)s")
    leftover = tmp_path / "abc.webm"
    leftover.write_bytes(b"x")

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="audio",
        format_id=None,
    )
    assert res.error_category == "unknown"
    assert "mp3" in (res.error_raw or "").lower()


def test_run_download_cleans_orphans_on_timeout(monkeypatch, tmp_path):
    out_template = str(tmp_path / "abc.%(ext)s")
    (tmp_path / "abc.part").write_bytes(b"x")
    (tmp_path / "abc.webm").write_bytes(b"x")

    def _raise(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1)

    monkeypatch.setattr("runner.subprocess.run", _raise)

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="video",
        format_id=None,
    )
    assert res.error_category == "timeout"
    assert not (tmp_path / "abc.part").exists()
    assert not (tmp_path / "abc.webm").exists()
```

Then append the implementation to `runner.py`:

```python
import glob


@dataclass
class DownloadResult:
    file_path: str | None = None
    error_category: str | None = None
    error_raw: str = ""


def _cleanup_glob(out_template: str) -> None:
    base = out_template.replace("%(ext)s", "*")
    for f in glob.glob(base):
        try:
            os.remove(f)
        except OSError:
            pass


def run_download(
    *,
    url: str,
    out_template: str,
    format_choice: str,
    format_id: str | None,
    timeout: int = 300,
) -> DownloadResult:
    argv = build_download_argv(
        url=url,
        out_template=out_template,
        format_choice=format_choice,
        format_id=format_id,
    )
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        _cleanup_glob(out_template)
        return DownloadResult(error_category="timeout", error_raw="download timed out")
    if proc.returncode != 0:
        _cleanup_glob(out_template)
        stripped = (proc.stderr or "").strip()
        return DownloadResult(
            error_category=classify_error(proc.stderr),
            error_raw=stripped.splitlines()[-1] if stripped else "",
        )

    base_glob = out_template.replace("%(ext)s", "*")
    files = sorted(glob.glob(base_glob))
    if not files:
        return DownloadResult(error_category="unknown", error_raw="no output file found")

    if format_choice == "audio":
        mp3s = [f for f in files if f.endswith(".mp3")]
        if not mp3s:
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass
            return DownloadResult(
                error_category="unknown",
                error_raw="audio conversion did not produce mp3",
            )
        chosen = mp3s[0]
        leftovers = [f for f in files if f != chosen]
    else:
        mp4s = [f for f in files if f.endswith(".mp4")]
        chosen = mp4s[0] if mp4s else files[0]
        leftovers = [f for f in files if f != chosen]

    for f in leftovers:
        try:
            os.remove(f)
        except OSError:
            pass

    return DownloadResult(file_path=chosen)
```

- [ ] **Step 9: Run all runner tests**

```bash
python -m pytest tests/test_runner.py -v
```

Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add runner.py tests/test_runner.py
git commit -m "feat(runner): run_info / run_download with classify_error and orphan cleanup"
```

### Task B7: jobs.JobManager — bounded pool + TTL + cancellation

**Files:**
- Create: `jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_jobs.py
import os
import time
import pytest
from jobs import JobManager, Job, JobStatus


def test_submit_returns_job_id_and_marks_queued():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: None, title="hi", url="https://x")
    assert isinstance(jid, str) and len(jid) == 10
    j = jm.get(jid)
    assert j.title == "hi"
    assert j.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING}
    jm.shutdown()


def test_submit_runs_target_and_marks_done(tmp_path):
    jm = JobManager(max_workers=1, ttl_seconds=60)
    flag = tmp_path / "done.txt"

    def work(job: Job):
        flag.write_text("ok")

    jid = jm.submit(target=work, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    assert flag.read_text() == "ok"
    assert jm.get(jid).status == JobStatus.DONE
    jm.shutdown()


def test_submit_marks_error_when_target_raises():
    jm = JobManager(max_workers=1, ttl_seconds=60)

    def boom(job: Job):
        raise RuntimeError("nope")

    jid = jm.submit(target=boom, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.ERROR:
            break
        time.sleep(0.05)
    assert jm.get(jid).status == JobStatus.ERROR
    jm.shutdown()


def test_cancel_marks_cancelled_for_done_job():
    jm = JobManager(max_workers=1, ttl_seconds=60)

    def work(job: Job):
        pass

    jid = jm.submit(target=work, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    cancelled = jm.cancel(jid)
    assert cancelled is True
    assert jm.get(jid).status == JobStatus.CANCELLED
    jm.shutdown()


def test_pool_full_returns_overflow():
    jm = JobManager(max_workers=1, ttl_seconds=60, queue_size=0)
    started = []

    def slow(job: Job):
        started.append(job.id)
        time.sleep(0.5)

    j1 = jm.submit(target=slow, title="a", url="https://x")
    with pytest.raises(RuntimeError):
        jm.submit(target=slow, title="b", url="https://y")
    jm.shutdown(wait=True)


def test_ttl_sweep_removes_old_done_jobs(tmp_path):
    jm = JobManager(max_workers=1, ttl_seconds=0)  # zero = sweep immediately

    def work(job: Job):
        f = tmp_path / "out.bin"
        f.write_bytes(b"x")
        job.file_path = str(f)

    jid = jm.submit(target=work, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    jm.sweep()
    assert jm.get(jid) is None
    assert not (tmp_path / "out.bin").exists()
    jm.shutdown()
```

- [ ] **Step 2: Run tests (expect ImportError)**

```bash
python -m pytest tests/test_jobs.py -v
```

- [ ] **Step 3: Implement jobs.JobManager**

```python
# jobs.py
from __future__ import annotations
import enum
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from queue import Full
from typing import Callable


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    url: str
    title: str
    status: JobStatus = JobStatus.QUEUED
    file_path: str | None = None
    filename: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    process: object | None = None  # subprocess.Popen, set by runner if it wants kill support
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)


class JobManager:
    def __init__(self, *, max_workers: int = 4, ttl_seconds: int = 3600, queue_size: int | None = None):
        self.max_workers = max_workers
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._inflight = 0
        self._queue_size = queue_size  # None = unlimited; 0 = no queue, must be free worker

    def submit(self, *, target: Callable[[Job], None], title: str, url: str) -> str:
        job_id = uuid.uuid4().hex[:10]
        job = Job(id=job_id, url=url, title=title, status=JobStatus.QUEUED)
        with self._lock:
            if self._queue_size == 0 and self._inflight >= self.max_workers:
                raise RuntimeError("pool full")
            self._jobs[job_id] = job
            self._inflight += 1

        def _run():
            try:
                with self._lock:
                    job.status = JobStatus.DOWNLOADING
                target(job)
                with self._lock:
                    if job.status not in {JobStatus.ERROR, JobStatus.CANCELLED}:
                        job.status = JobStatus.DONE
            except Exception as e:
                with self._lock:
                    job.status = JobStatus.ERROR
                    job.error_category = job.error_category or "unknown"
                    job.error_message = job.error_message or str(e)
            finally:
                with self._lock:
                    self._inflight -= 1

        self._executor.submit(_run)
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is not None:
                j.last_accessed = time.monotonic()
            return j

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            proc = job.process
            if job.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                # If finished, treat cancel as cleanup.
                if job.file_path and os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except OSError:
                        pass
                job.status = JobStatus.CANCELLED
                return True
            job.status = JobStatus.CANCELLED
        # Outside lock: kill the subprocess if any.
        if proc is not None and hasattr(proc, "kill"):
            try:
                proc.kill()
            except Exception:
                pass
        return True

    def sweep(self) -> int:
        """Drop done/errored/cancelled jobs older than ttl_seconds. Returns count removed."""
        cutoff = time.monotonic() - self.ttl_seconds
        removed = 0
        with self._lock:
            to_remove = [
                jid for jid, j in self._jobs.items()
                if j.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}
                and j.last_accessed <= cutoff
            ]
            for jid in to_remove:
                job = self._jobs.pop(jid)
                if job.file_path and os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except OSError:
                        pass
                removed += 1
        return removed

    def start_sweeper(self, interval_seconds: int = 300) -> None:
        def loop():
            while True:
                time.sleep(interval_seconds)
                try:
                    self.sweep()
                except Exception:
                    pass
        t = threading.Thread(target=loop, daemon=True, name="trove-sweeper")
        t.start()

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_jobs.py -v
```

Expected: all six pass.

- [ ] **Step 5: Commit**

```bash
git add jobs.py tests/test_jobs.py
git commit -m "feat(jobs): JobManager with bounded pool, TTL sweep, cancel"
```

---

## Phase C — Flask app

### Task C1: app.py routes (HTML page + JSON API)

**Files:**
- Create: `app.py`

- [ ] **Step 1: Write app.py**

```python
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
    job_manager = JobManager(max_workers=MAX_WORKERS, ttl_seconds=JOB_TTL)
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
        return render_template("index.html")

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
        if not is_safe_url(url):
            return render_template("partials/card.html", card={
                "kind": "error", "url": url, "category": "unsupported_url",
            }), 400
        try:
            job_id = _enqueue_download(url, format_choice, format_id, title)
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

    # --- helpers -----------------------------------------------------------

    def _enqueue_download(url: str, format_choice: str, format_id, title: str) -> str:
        def _work(job: Job):
            out_template = str(DOWNLOAD_DIR / f"{job.id}.%(ext)s")
            result = run_download(
                url=url,
                out_template=out_template,
                format_choice=format_choice,
                format_id=format_id,
            )
            if result.error_category:
                job.status = JobStatus.ERROR
                job.error_category = result.error_category
                job.error_message = result.error_raw
                return
            ext = os.path.splitext(result.file_path)[1] if result.file_path else ""
            job.file_path = result.file_path
            job.filename = sanitize_filename(title, ext)

        return job_manager.submit(target=_work, title=title, url=url)

    def _card_view(job: Job) -> dict:
        return {
            "kind": job.status.value,
            "id": job.id,
            "title": job.title or "Untitled",
            "url": job.url,
            "filename": job.filename,
            "category": job.error_category,
        }

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app = create_app()
    app.run(host=host, port=port)
```

- [ ] **Step 2: Smoke check that the app boots**

```bash
source venv/bin/activate
python -c "from app import create_app; a = create_app(); print('routes:', [r.rule for r in a.url_map.iter_rules()])"
```

Expected: prints the route list including `/api/info`, `/api/info-card`, `/api/job/<job_id>/cancel`.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(app): Flask routes wired to safety/runner/jobs"
```

### Task C2: tests/test_endpoints.py — htmx fragment + RCE regression

**Files:**
- Create: `tests/test_endpoints.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write test_endpoints + minimal templates so they exist (real templates land in Phase D)**

`tests/test_endpoints.py`:

```python
import os
import pathlib
import subprocess
import pytest
from app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_JOB_TTL_SECONDS", "60")
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    app = create_app()
    return app.test_client()


def test_argument_injection_url_rejected_json(client, monkeypatch):
    called = []
    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: called.append(a) or _ok(""))
    r = client.post("/api/info", json={"url": "--exec=touch /tmp/pwned"})
    assert r.status_code == 400
    assert called == []


def test_argument_injection_url_rejected_card(client, monkeypatch):
    called = []
    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: called.append(a) or _ok(""))
    r = client.post("/api/info-card", data={"url": "--exec=touch /tmp/pwned"})
    assert r.status_code == 400
    assert b"not supported" in r.data.lower() or b"unsupported" in r.data.lower()
    assert called == []


def test_request_json_none_returns_400(client):
    r = client.post("/api/info", data="not json", content_type="text/plain")
    assert r.status_code == 400


def test_token_required_blocks_when_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TROVE_TOKEN", "secret")
    app = create_app()
    client = app.test_client()
    assert client.post("/api/info", json={"url": "https://www.youtube.com/"}).status_code == 401
    r = client.post(
        "/api/info",
        json={"url": "https://www.youtube.com/"},
        headers={"Authorization": "Bearer secret"},
    )
    # Will hit network; we accept any non-401 (200 or 400).
    assert r.status_code != 401


def test_csp_no_unsafe_inline_script(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    script = csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script
    assert "'nonce-" in script


# ----- helpers ---------------------------------------------------------------


class _Completed:
    def __init__(self, stderr=""):
        self.returncode = 1 if stderr else 0
        self.stdout = ""
        self.stderr = stderr


def _ok(stderr=""):
    return _Completed(stderr=stderr)
```

- [ ] **Step 2: Stub partials/card.html and templates/index.html so render_template doesn't crash**

(Phase D rewrites these properly — for now just enough to pass tests.)

```bash
mkdir -p /Users/kaivan108icloud.com/Downloads/trove/templates/partials
```

`templates/index.html`:

```html
<!doctype html>
<html><head><title>Trove</title></head><body><h1>Trove</h1></body></html>
```

`templates/partials/card.html`:

```html
{% if card.kind == "error" %}
  <div class="card-error" data-category="{{ card.category }}">URL not supported: {{ card.url }}</div>
{% else %}
  <div class="card" data-status="{{ card.kind }}" data-job-id="{{ card.id or '' }}">
    {{ card.title or 'Untitled' }}
  </div>
{% endif %}
```

- [ ] **Step 3: Run all tests**

```bash
source venv/bin/activate && python -m pytest -v
```

Expected: every test green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_endpoints.py templates/
git commit -m "test(endpoints): RCE/argv-injection regression + CSP/auth checks"
```

---

## Phase D — Frontend (Tailwind + htmx + Alpine + Jinja partials)

### Task D1: Download Tailwind standalone CLI + tailwind.config.js + input.css

**Files:**
- Create: `tools/tailwindcss` (gitignored), `tailwind.config.js`, `styles/input.css`

- [ ] **Step 1: Download the Tailwind binary for the host**

```bash
mkdir -p /Users/kaivan108icloud.com/Downloads/trove/tools
cd /Users/kaivan108icloud.com/Downloads/trove/tools
ARCH=$(uname -m)
case "$ARCH" in
  arm64|aarch64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 ;;
  x86_64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-x64 ;;
  *) echo "unsupported arch: $ARCH"; exit 1 ;;
esac
curl -sSL "$URL" -o tailwindcss
chmod +x tailwindcss
./tailwindcss --help | head -3
```

Expected: prints the binary's help text.

- [ ] **Step 2: Write tailwind.config.js**

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        fg: "var(--fg)",
        muted: "var(--muted)",
        border: "var(--border)",
        accent: "var(--accent)",
        "accent-hover": "var(--accent-hover)",
        success: "var(--success)",
        error: "var(--error)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "14px",
        lg: "18px",
      },
      boxShadow: {
        card: "0 2px 8px rgba(0,0,0,0.04)",
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 3: Write styles/input.css with the design tokens**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --bg: #fbf9f6;
    --surface: #ffffff;
    --fg: #23211e;
    --muted: #8e8a83;
    --border: #e9e5dd;
    --accent: #FF6A4D;
    --accent-hover: #e95938;
    --success: #2d8a4e;
    --error: #c43d3d;
  }
  html.dark {
    --bg: #17181b;
    --surface: #1f2024;
    --fg: #f4f1eb;
    --muted: #9b9890;
    --border: #2c2d31;
    --accent: #FF6A4D;
    --accent-hover: #ff7e63;
    --success: #42b06a;
    --error: #e25e5e;
  }
  body {
    background-color: var(--bg);
    color: var(--fg);
    font-family: Inter, ui-sans-serif, system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
}

@layer components {
  .btn-primary {
    @apply inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-base font-medium text-white shadow-card transition active:scale-[0.98];
    background-color: var(--accent);
  }
  .btn-primary:hover { background-color: var(--accent-hover); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

  .btn-secondary {
    @apply inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition;
    color: var(--fg);
    background-color: var(--surface);
    border: 1px solid var(--border);
  }
  .btn-secondary:hover { border-color: var(--accent); }

  .card {
    @apply flex gap-4 rounded p-4 shadow-card;
    background-color: var(--surface);
    border: 1px solid var(--border);
  }
  .chip {
    @apply px-3 py-1 rounded-full text-xs;
    border: 1px solid var(--border);
    color: var(--muted);
  }
  .chip[data-active="true"] {
    color: var(--fg);
    border-color: var(--fg);
  }
}
```

- [ ] **Step 4: Build the CSS once to confirm it works**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
mkdir -p static
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify
ls -la static/app.css
```

Expected: file exists, non-zero size.

- [ ] **Step 5: Commit (without the binary or built CSS)**

```bash
git add tailwind.config.js styles/
git commit -m "feat(ui): Tailwind config with Trove tokens"
```

### Task D2: Vendor htmx + Alpine

**Files:**
- Create: `static/vendor/htmx.min.js`, `static/vendor/alpine.min.js`

- [ ] **Step 1: Download both**

```bash
mkdir -p /Users/kaivan108icloud.com/Downloads/trove/static/vendor
cd /Users/kaivan108icloud.com/Downloads/trove/static/vendor
curl -sSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js -o htmx.min.js
curl -sSL https://unpkg.com/alpinejs@3.14.1/dist/cdn.min.js -o alpine.min.js
ls -la htmx.min.js alpine.min.js
head -c 80 htmx.min.js && echo
```

Expected: both files exist; htmx file starts with the htmx prelude.

- [ ] **Step 2: Commit**

```bash
git add static/vendor/
git commit -m "feat(ui): vendor htmx 2.0.4 + alpine 3.14.1"
```

### Task D3: templates/base.html + favicon

**Files:**
- Create: `templates/base.html`, `static/favicon.svg`

- [ ] **Step 1: Write base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Trove — Save things you care about{% endblock %}</title>
  <meta name="description" content="Save things you care about. Self-hosted media downloader.">
  <link rel="icon" href="{{ url_for('static', filename='favicon.svg') }}" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
  <script nonce="{{ g.csp_nonce }}">
    // Dark-mode bootstrap before paint
    (function() {
      var saved = localStorage.getItem('trove-theme');
      var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (saved === 'dark' || (!saved && prefersDark)) {
        document.documentElement.classList.add('dark');
      }
    })();
  </script>
</head>
<body class="min-h-screen">
  <div class="max-w-2xl mx-auto px-5 py-10 sm:py-16">
    <header class="flex items-center justify-between mb-10">
      <div>
        <h1 class="text-3xl sm:text-4xl font-semibold tracking-tight">
          Tr<span style="color: var(--accent)">o</span>ve
        </h1>
        <p class="text-sm" style="color: var(--muted)">Save things you care about</p>
      </div>
      <button
        type="button"
        x-data
        @click="document.documentElement.classList.toggle('dark'); localStorage.setItem('trove-theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light')"
        aria-label="Toggle dark mode"
        class="btn-secondary !p-2 !rounded-full"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4"/>
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
        </svg>
      </button>
    </header>

    {% block content %}{% endblock %}

    <footer class="mt-16 text-center text-xs" style="color: var(--muted)">
      Originally based on
      <a href="https://github.com/averygan/reclip" class="underline">averygan/reclip</a>
      (MIT) · Rewritten as Trove
    </footer>
  </div>

  <script nonce="{{ g.csp_nonce }}" src="{{ url_for('static', filename='vendor/alpine.min.js') }}" defer></script>
  <script nonce="{{ g.csp_nonce }}" src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>
  <script nonce="{{ g.csp_nonce }}">
    // Cancel-on-tab-close: htmx isn't built for unload semantics, so we use sendBeacon.
    window.__troveActiveJobs = new Set();
    window.addEventListener('beforeunload', function() {
      for (var id of window.__troveActiveJobs) {
        try { navigator.sendBeacon('/api/job/' + id + '/cancel'); } catch (_) {}
      }
    });
    document.addEventListener('htmx:afterSwap', function(evt) {
      // Track active job IDs from data-job-id attributes still in the DOM.
      var active = new Set();
      document.querySelectorAll('[data-job-id][data-status="downloading"]').forEach(function(el) {
        active.add(el.dataset.jobId);
      });
      window.__troveActiveJobs = active;
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Write favicon.svg**

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" rx="14" fill="#FF6A4D"/>
  <text x="32" y="46" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-weight="600" font-size="38" fill="#fbf9f6">T</text>
</svg>
```

- [ ] **Step 3: Commit**

```bash
git add templates/base.html static/favicon.svg
git commit -m "feat(ui): base layout, dark-mode toggle, favicon"
```

### Task D4: templates/index.html with htmx-driven input + queue

**Files:**
- Modify: `templates/index.html` (replace the stub)

- [ ] **Step 1: Rewrite index.html**

```html
{% extends "base.html" %}

{% block content %}
<form
  id="fetch-form"
  hx-post="/api/info-card"
  hx-target="#queue"
  hx-swap="beforeend"
  hx-on::before-request="this.querySelector('[name=fetch-btn]').disabled = true"
  hx-on::after-request="this.querySelector('[name=fetch-btn]').disabled = false; this.reset()"
  class="space-y-4"
>
  <div>
    <label for="urls" class="sr-only">Paste a link</label>
    <textarea
      id="urls"
      name="url"
      rows="2"
      placeholder="Paste a link to get started…"
      class="w-full px-5 py-4 text-base bg-surface border rounded shadow-card focus:outline-none focus:border-accent"
      style="background-color: var(--surface); border-color: var(--border)"
    ></textarea>
    <p class="text-xs mt-2" style="color: var(--muted)">
      YouTube · TikTok · Instagram · Vimeo · 1000+ more
    </p>
  </div>

  <div class="flex gap-3 items-center" x-data="{ format: 'video' }">
    <div class="inline-flex p-1 rounded-lg" style="background-color: var(--surface); border: 1px solid var(--border)">
      <button
        type="button"
        @click="format = 'video'"
        :class="format === 'video' ? 'bg-fg text-bg' : ''"
        :style="format === 'video' ? 'background-color: var(--fg); color: var(--bg)' : ''"
        class="px-4 py-2 rounded-md text-sm font-medium transition"
      >MP4</button>
      <button
        type="button"
        @click="format = 'audio'"
        :class="format === 'audio' ? 'bg-fg text-bg' : ''"
        :style="format === 'audio' ? 'background-color: var(--fg); color: var(--bg)' : ''"
        class="px-4 py-2 rounded-md text-sm font-medium transition"
      >MP3</button>
    </div>
    <input type="hidden" name="format" :value="format">
    <button
      name="fetch-btn"
      type="submit"
      class="btn-primary flex-1 min-h-[44px]"
    >Fetch</button>
  </div>
</form>

<div id="queue" aria-live="polite" class="space-y-3 mt-8"></div>
{% endblock %}
```

- [ ] **Step 2: Build CSS again so the new classes are picked up**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify
```

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): home page with htmx form + Alpine format toggle"
```

### Task D5: templates/partials/card.html — full state machine

**Files:**
- Modify: `templates/partials/card.html` (replace stub with full version)

- [ ] **Step 1: Rewrite card.html**

```html
{% set msgs = {
  "unsupported_url": "This URL isn't supported.",
  "private_or_unavailable": "This video is private or unavailable.",
  "geo_restricted": "Not available in your region.",
  "rate_limited": "Hit a rate limit — try again in a minute.",
  "auth_required": "The site needs login. Set TROVE_COOKIES_FROM_BROWSER and restart.",
  "network": "Network problem — check your connection.",
  "timeout": "Request timed out. Try again.",
  "busy": "Server is busy. Try again in a moment.",
  "unknown": "Something went wrong.",
} %}

{% if card.kind == "error" %}
<div class="card border-error" style="border-color: var(--error)" data-status="error">
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium" style="color: var(--error)">
      {{ msgs.get(card.category, msgs.unknown) }}
    </p>
    {% if card.url %}
      <p class="text-xs mt-1 break-all" style="color: var(--muted)">{{ card.url }}</p>
    {% endif %}
  </div>
</div>

{% elif card.kind == "ready" %}
<div class="card" data-status="ready">
  <div class="w-28 h-20 sm:w-32 sm:h-20 rounded-md overflow-hidden flex-shrink-0" style="background-color: var(--border)">
    {% if card.thumbnail %}
      <img src="{{ card.thumbnail }}" alt="" class="w-full h-full object-cover" loading="lazy">
    {% endif %}
  </div>
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium truncate">{{ card.title or "Untitled" }}</p>
    <p class="text-xs mt-1" style="color: var(--muted)">
      {{ card.uploader or "" }}
      {% if card.duration %} · {{ "%d:%02d"|format(card.duration // 60, card.duration % 60) }}{% endif %}
    </p>
    <form
      hx-post="/api/download-card"
      hx-swap="outerHTML"
      hx-target="closest .card"
      class="mt-3 flex flex-wrap gap-2 items-center"
    >
      <input type="hidden" name="url" value="{{ card.url }}">
      <input type="hidden" name="title" value="{{ card.title or '' }}">
      <input type="hidden" name="format" value="{{ card.format or 'video' }}">
      {% if card.formats and (card.format or 'video') == 'video' %}
        <select name="format_id" class="chip">
          {% for f in card.formats %}
            <option value="{{ f.id }}">{{ f.label }}</option>
          {% endfor %}
        </select>
      {% endif %}
      <button type="submit" class="btn-primary !min-h-[44px] !py-2 !px-4 text-sm">Save</button>
    </form>
  </div>
</div>

{% elif card.kind in ("queued", "downloading") %}
<div
  class="card"
  data-status="downloading"
  data-job-id="{{ card.id }}"
  hx-get="/api/status-card/{{ card.id }}"
  hx-trigger="every 1s"
  hx-swap="outerHTML"
>
  <div class="w-28 h-20 rounded-md flex-shrink-0 animate-pulse" style="background-color: var(--border)"></div>
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium truncate">{{ card.title }}</p>
    <p class="text-xs mt-1" style="color: var(--accent)">Saving…</p>
  </div>
</div>

{% elif card.kind == "done" %}
<div class="card" data-status="done">
  <div class="w-28 h-20 rounded-md flex-shrink-0 flex items-center justify-center" style="background-color: var(--success); color: white">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  </div>
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium truncate">{{ card.title }}</p>
    <p class="text-xs mt-1" style="color: var(--muted)">{{ card.filename or "" }}</p>
    <a
      href="/api/file/{{ card.id }}"
      download="{{ card.filename or '' }}"
      class="btn-primary !min-h-[40px] !py-2 !px-4 text-sm mt-3 inline-flex"
    >Save to device</a>
  </div>
</div>

{% elif card.kind == "cancelled" %}
<div class="card" data-status="cancelled">
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium" style="color: var(--muted)">Cancelled.</p>
  </div>
</div>

{% else %}
<div class="card border-error" style="border-color: var(--error)" data-status="error">
  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium" style="color: var(--error)">
      {{ msgs.get(card.category, msgs.unknown) }}
    </p>
  </div>
</div>
{% endif %}
```

- [ ] **Step 2: Re-build CSS**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify
```

- [ ] **Step 3: Run all tests to make sure templates still load**

```bash
source venv/bin/activate && python -m pytest -v
```

Expected: still green.

- [ ] **Step 4: Commit**

```bash
git add templates/partials/card.html
git commit -m "feat(ui): full card state machine (error/ready/downloading/done/cancelled)"
```

### Task D6: Manual end-to-end smoke test

**Files:** none

- [ ] **Step 1: Boot the server**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify
PORT=8899 HOST=127.0.0.1 python app.py &
sleep 2
curl -s -o /dev/null -w 'home: %{http_code}\n' http://127.0.0.1:8899/
```

Expected: home: 200.

- [ ] **Step 2: Smoke a download against a known direct .mp4 URL**

```bash
JOB=$(curl -s -X POST http://127.0.0.1:8899/api/download \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://download.samplelib.com/mp4/sample-5s.mp4","format":"video","title":"sample 5s"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
echo "job: $JOB"
until curl -s "http://127.0.0.1:8899/api/status/$JOB" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("status:",d["status"]);sys.exit(0 if d["status"] in ("done","error") else 1)'; do sleep 1; done
curl -sI "http://127.0.0.1:8899/api/file/$JOB" | head -8
ls -la downloads/
```

Expected: status: done; file headers show 200 + Content-Type video/mp4.

- [ ] **Step 3: Smoke the RCE-rejection path**

```bash
curl -s -o /dev/null -w 'argv-injection: %{http_code}\n' \
  -X POST http://127.0.0.1:8899/api/info \
  -H 'Content-Type: application/json' \
  -d '{"url":"--exec=touch /tmp/trove-pwn-test"}'
test ! -e /tmp/trove-pwn-test && echo "no /tmp/trove-pwn-test created — good"
```

Expected: 400, then "no /tmp/trove-pwn-test created — good".

- [ ] **Step 4: Open the page in a browser and click through**

(Manual.) Open http://127.0.0.1:8899 in Safari/Chrome. Verify:
- Light mode by default.
- Toggle works; persists on refresh.
- Paste the same sample-5s.mp4 URL; click Fetch; card shows; click Save; downloading; done; click "Save to device"; file downloads.
- Submit garbage URL; error card appears with friendly text.
- At 375px viewport (devtools), buttons are ≥ 44px tall.

- [ ] **Step 5: Stop the server**

```bash
pkill -f 'python app.py'
```

- [ ] **Step 6: Commit nothing here — just record acceptance.**

(No files changed.)

---

## Phase E — Scripts and container

### Task E1: trove.sh

**Files:**
- Create: `trove.sh`

- [ ] **Step 1: Write trove.sh**

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

# Check prerequisites
missing=""
command -v python3 >/dev/null 2>&1 || missing="$missing python3"
command -v ffmpeg  >/dev/null 2>&1 || missing="$missing ffmpeg"

if [ -n "$missing" ]; then
  echo "Missing required tools:$missing"
  if command -v brew >/dev/null 2>&1; then echo "Install with:  brew install$missing"
  elif command -v apt >/dev/null 2>&1; then echo "Install with:  sudo apt install$missing"
  else echo "Please install:$missing"; fi
  exit 1
fi

# Python venv
if [ ! -d "venv" ]; then
  echo "Setting up virtual environment..."
  python3 -m venv venv
fi
# shellcheck source=/dev/null
source venv/bin/activate
pip install -q -U pip wheel >/dev/null
pip install -q -r requirements.txt >/dev/null
# Always update yt-dlp — its extractors break weekly.
pip install -q -U yt-dlp >/dev/null

# Tailwind binary
if [ ! -x tools/tailwindcss ]; then
  echo "Downloading Tailwind CSS standalone CLI..."
  mkdir -p tools
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m)
  case "$OS-$ARCH" in
    darwin-arm64)  URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 ;;
    darwin-x86_64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-x64 ;;
    linux-x86_64)  URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 ;;
    linux-aarch64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-arm64 ;;
    *) echo "Unsupported platform: $OS-$ARCH"; exit 1 ;;
  esac
  curl -sSL "$URL" -o tools/tailwindcss
  chmod +x tools/tailwindcss
fi

# Build CSS
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify >/dev/null

PORT="${PORT:-8899}"
HOST="${HOST:-127.0.0.1}"
export PORT HOST
echo ""
echo "  Trove is running at http://$HOST:$PORT"
echo ""
exec python3 app.py
```

- [ ] **Step 2: Make executable + smoke**

```bash
chmod +x /Users/kaivan108icloud.com/Downloads/trove/trove.sh
/Users/kaivan108icloud.com/Downloads/trove/trove.sh &
SH_PID=$!
sleep 5
curl -s -o /dev/null -w 'home: %{http_code}\n' http://127.0.0.1:8899/
kill $SH_PID 2>/dev/null || true
```

Expected: home: 200.

- [ ] **Step 3: Commit**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
git add trove.sh
git commit -m "feat: trove.sh installs deps, downloads Tailwind, builds CSS, runs app"
```

### Task E2: Dockerfile (multi-stage)

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1

# Stage 1: build CSS with Tailwind standalone CLI
FROM debian:bookworm-slim AS builder
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY tailwind.config.js ./
COPY styles/ ./styles/
COPY templates/ ./templates/
RUN set -eux; \
    case "$TARGETARCH" in \
      arm64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-arm64 ;; \
      amd64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 ;; \
      *) echo "unsupported arch: $TARGETARCH"; exit 1 ;; \
    esac; \
    curl -sSL "$URL" -o /usr/local/bin/tailwindcss && chmod +x /usr/local/bin/tailwindcss
RUN mkdir -p static && \
    /usr/local/bin/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify

# Stage 2: runtime
FROM python:3.12-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 trove
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -U yt-dlp
COPY app.py jobs.py runner.py safety.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY --from=builder /build/static/app.css ./static/app.css
RUN mkdir -p downloads && chown -R trove:trove /app
USER trove
EXPOSE 8899
ENV HOST=127.0.0.1
ENV PORT=8899
CMD ["python", "app.py"]
```

- [ ] **Step 2: Build the image and smoke it**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
docker build -t trove:dev . 2>&1 | tail -20
docker run --rm -d --name trove-smoke -p 18899:8899 trove:dev
sleep 2
curl -s -o /dev/null -w 'docker home: %{http_code}\n' http://127.0.0.1:18899/
docker logs trove-smoke 2>&1 | tail -5
docker rm -f trove-smoke
```

Expected: home: 200; logs show Flask startup.

- [ ] **Step 3: Confirm container's HOST default is 127.0.0.1**

```bash
docker inspect trove:dev --format '{{range .Config.Env}}{{println .}}{{end}}' | grep HOST
```

Expected: HOST=127.0.0.1.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: multi-stage Dockerfile (Tailwind build → Python runtime)"
```

---

## Phase F — Polish, README, push

### Task F1: README expansion

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README with full content**

```markdown
# Trove

**Save things you care about.**

A self-hosted, browser-based downloader for video and audio from YouTube, TikTok, Instagram, Vimeo, and ~1000 other sites — powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

- One paste box, one click — videos save to your device.
- Bulk paste, MP4/MP3 toggle, quality picker.
- Mobile-friendly, dark mode included.
- Single Python process, single Docker container, no Node.js.

## Quick start

```bash
brew install yt-dlp ffmpeg     # macOS — or apt install ffmpeg && pip install yt-dlp
git clone https://github.com/afk1997/trove.git
cd trove
./trove.sh
```

Open **http://localhost:8899**.

Or with Docker:

```bash
docker build -t trove . && docker run -p 8899:8899 trove
```

## Configuration (env vars)

| Variable | Default | What it does |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address. Set to `0.0.0.0` only with a token. |
| `PORT` | `8899` | TCP port. |
| `TROVE_TOKEN` | *(unset)* | When set, every `/api/*` request must send `Authorization: Bearer <token>`. |
| `TROVE_COOKIES_FROM_BROWSER` | *(unset)* | One of `safari\|chrome\|firefox\|brave\|edge`. Required for YouTube right now (Google blocks cookieless yt-dlp). |
| `TROVE_JOB_TTL_SECONDS` | `3600` | How long completed jobs (and their files) linger before being swept. |
| `TROVE_MAX_WORKERS` | `4` | Concurrent downloads. Excess returns HTTP 503. |
| `TROVE_RATE_LIMIT` | `30` | Requests per minute per IP. Set to `0` to disable. |

## Exposing to LAN or the internet

The defaults assume **localhost only**. To expose Trove safely:

1. Set a token: `export TROVE_TOKEN=$(openssl rand -hex 32)`
2. Set host: `export HOST=0.0.0.0`
3. Run behind a reverse proxy that adds HTTPS (Caddy, nginx, fly.io, etc.).

Without `TROVE_TOKEN`, anyone who can reach the port can download.

## YouTube and cookies

YouTube currently blocks `yt-dlp` connections that don't carry a real browser cookie. To download from YouTube, set:

```bash
export TROVE_COOKIES_FROM_BROWSER=safari   # or chrome / firefox / brave / edge
./trove.sh
```

The browser must be installed on the host and have an active YouTube session.

## Stack

- **Backend:** Python 3.12 + Flask
- **Frontend:** htmx 2 + Alpine.js 3 + Tailwind CSS (standalone CLI, no Node at runtime)
- **Engine:** yt-dlp + ffmpeg

## Disclaimer

This tool is for personal use. Respect copyright laws and the terms of service of platforms you download from.

## License

MIT. See [LICENSE](LICENSE).

---

Originally based on [averygan/reclip](https://github.com/averygan/reclip) (MIT). Substantially rewritten and rebranded as Trove in 2026.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
git add README.md
git commit -m "docs: expand README with config, deploy, attribution"
```

### Task F2: Final test sweep + lint

**Files:** none

- [ ] **Step 1: Run all tests once more**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
python -m pytest -v
```

Expected: every test green. Count printed.

- [ ] **Step 2: Verify acceptance criteria #2 (RCE blocked at runtime)**

```bash
PORT=8899 HOST=127.0.0.1 python app.py &
sleep 2
curl -s -o /dev/null -w 'argv: %{http_code}\n' \
  -X POST http://127.0.0.1:8899/api/info \
  -H 'Content-Type: application/json' \
  -d '{"url":"--exec=touch /tmp/trove-pwn-final"}'
test ! -e /tmp/trove-pwn-final && echo "OK"
pkill -f 'python app.py'
```

Expected: argv: 400, OK.

- [ ] **Step 3: Verify acceptance criteria #4 (Docker default HOST)**

```bash
docker inspect trove:dev --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^HOST='
```

Expected: HOST=127.0.0.1.

- [ ] **Step 4: Verify acceptance criteria #8 (CSP no unsafe-inline)**

```bash
PORT=8899 HOST=127.0.0.1 python app.py &
sleep 2
curl -sI http://127.0.0.1:8899/ | grep -i content-security-policy
pkill -f 'python app.py'
```

Expected: header present; the `script-src` segment contains `'self'` and `'nonce-...'` but not `'unsafe-inline'`.

### Task F3: Create the public GitHub repo and push

**Files:** none (network ops)

- [ ] **Step 1: Confirm gh auth + identity**

```bash
gh auth status
gh api user --jq .login
```

Expected: prints `afk1997`.

- [ ] **Step 2: Verify the local commit history is clean and authored by you**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
git log --pretty='%h %an <%ae> %s'
```

Expected: every line shows `Kaivan Doshi <kaivandoshi1997@gmail.com>`.

- [ ] **Step 3: Create the public repo and push**

```bash
gh repo create afk1997/trove \
  --public \
  --description "Save things you care about. Self-hosted media downloader." \
  --source . \
  --remote origin \
  --push
```

Expected: prints the repo URL and the push summary.

- [ ] **Step 4: Verify on GitHub**

```bash
gh repo view afk1997/trove --web 2>/dev/null || echo "open https://github.com/afk1997/trove"
gh api repos/afk1997/trove --jq '{name, visibility, license: .license.spdx_id}'
```

Expected: `{name: trove, visibility: public, license: MIT}`.

- [ ] **Step 5: Final acceptance check on the live repo**

```bash
gh api repos/afk1997/trove/contributors --jq '.[].login'
```

Expected: only `afk1997`.

---

## Acceptance criteria check (running tally)

After Task F3, all 11 spec criteria should be met:

1. ✅ `python -m pytest` green (Task F2 step 1)
2. ✅ argv-injection blocked at runtime (Task F2 step 2)
3. ✅ TTL sweeper drops old jobs (covered by `tests/test_jobs.py::test_ttl_sweep_removes_old_done_jobs`)
4. ✅ Docker `HOST=127.0.0.1` (Task F2 step 3)
5. ✅ Cookies env path works — manual: re-run with `TROVE_COOKIES_FROM_BROWSER=safari`
6. ✅ Token auth — covered by `tests/test_safety.py` + `tests/test_endpoints.py::test_token_required_blocks_when_set`
7. ✅ Cancel-on-tab-close — verified manually in Task D6 step 4
8. ✅ CSP no unsafe-inline (Task F2 step 4)
9. ✅ 44px touch targets — Task D6 step 4 visual check
10. ✅ Lighthouse — manual after Task F3 (open in Chrome devtools, run Lighthouse mobile)
11. ✅ Public repo, MIT, sole contributor afk1997 (Task F3 step 5)

---

## Self-review notes

- All 19 audit items from the spec are mapped to specific tasks: argv injection (B5–B6), DOM XSS (eliminated by Jinja in D5), SSRF (B1), Docker HOST + token (B2 + E2), security headers (B4), TTL (B7), timeout cleanup (B6), filename truncation (C1 `sanitize_filename`), audio honesty (B6 `run_download`), `request.json` None (C1 `silent=True` + tests), multi-line stdout (B6 `run_info`), stderr leak → category (B6), friendlyError tightening (D5 `msgs` map), yt-dlp auto-update (E1), cookies (B5), rate limit (B3), cancellation (B7 + D3 + C1), bounded pool (B7), smoke tests (B1, C2, F2).
- Endpoints in the spec: every JSON endpoint and every HTML-fragment endpoint is implemented in C1.
- The Tailwind binary is the only host-specific dependency; `trove.sh` and the Dockerfile both download the right one for the target platform.
- The first git commit is in Task A3, all subsequent commits inherit `Kaivan Doshi` identity from `git config user.email kaivandoshi1997@gmail.com` set in Task A1.
