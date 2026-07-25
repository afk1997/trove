# Trove · yt-dlp EJS modernization + one-click macOS launcher — design spec

**Status:** Approved
**Date:** 2026-07-25
**Branch:** `chore/ytdlp-ejs-mac-launcher`
**Base:** `main` at `9653172`

---

## 1 · Goal

Two related problems, one branch:

1. **yt-dlp is installed wrong.** Not out of date — *wrong shape*. The repo pulls the bare
   master tarball with no extras, so `yt-dlp-ejs` never gets installed and no JavaScript
   runtime is present. As of 2026 an external JS runtime is required for full YouTube
   support; without it YouTube extraction is deprecated and formats go missing.
2. **There is no working "just run this" entry point on macOS.** `trove.sh` exists but is
   broken on current Macs and installs an incomplete dependency set.

## 2 · Bugs this fixes (all verified on a real machine, 2026-07-25)

| # | Bug | Evidence |
|---|---|---|
| B1 | `trove.sh` Python probe stops at `3.13`. Homebrew now ships `python@3.14`; the only other interpreter is `/usr/bin/python3` (3.9.6, rejected). Script exits `Missing required tools: python@3.13` on a perfectly good Mac. | `trove.sh:8` |
| B2 | `trove.sh` installs only `flask pytest` + yt-dlp. `psutil`, `pywhispercpp`, `resemblyzer`, `silero-vad`, `scikit-learn`, `mcp` are never installed, so transcription and diarization silently do not work. | `trove.sh:45` vs `requirements.txt` |
| B3 | The failure in B2 is invisible: `machine.py` wraps `import psutil` in `try/except` and sets `psutil = None`. No error is ever surfaced. | `machine.py:13-15` |
| B4 | No `yt-dlp` extras anywhere ⇒ no `yt-dlp-ejs` ⇒ degraded YouTube. | `requirements.txt:4`, `pyproject.toml:14` |
| B5 | Even once Deno is installed into the venv, yt-dlp cannot find it. yt-dlp discovers JS runtimes via `PATH`, and trove's subprocess does not have `venv/bin` on `PATH`. `runner.py` special-cases this for the `yt-dlp` binary but nothing does it for Deno. | `runner.py:13-20` |
| B6 | The master tarball is unversioned, so pip cannot tell builds apart. This forced a `--force-reinstall` on *every single launch* — slow, and a hard network dependency just to start the app. | `trove.sh:44` |
| B7 | `trove.sh` accepts Python 3.10, but `pyproject.toml` requires `>=3.11` and yt-dlp raised its minimum recommended to 3.11 (3.10 is EOL October 2026). | `trove.sh:11` vs `pyproject.toml:5` |

## 3 · Part A — yt-dlp modernization

### Install shape

Move to yt-dlp's own recommended channel for regular users — **nightly, with extras**:

```
pip install -U --pre "yt-dlp[default,curl-cffi,deno]"
```

| Extra | Why it is needed |
|---|---|
| `default` | Pulls `yt-dlp-ejs` (JS challenge solving), plus certifi, brotli, websockets, requests, mutagen, pycryptodomex |
| `curl-cffi` | Enables `--impersonate` for TLS-fingerprint-gated sites |
| `deno` | Ships the Deno binary as a wheel — a real `macosx_11_0_arm64` wheel exists, so no Homebrew step is required |

`--pre` is what selects nightly; the extras are inert without it but still correct.

Because nightly builds carry real version numbers, `-U` is now a cheap no-op when already
current. **The `--force-reinstall` hack is deleted**, and a network failure during the
update step must not block startup — it logs a warning and continues with what is installed.

### Files changed

- `requirements.txt` — `yt-dlp[default,curl-cffi,deno]` replaces the tarball URL
- `pyproject.toml` — same extras on the `yt-dlp` dependency
- `Dockerfile` — `--pre` + extras
- `trove.sh` — the install step above

### `runner.py` — PATH injection (fixes B5)

Add a helper that returns an environment for yt-dlp subprocesses with the venv `bin`
directory prepended to `PATH`, and pass it to both `subprocess.run` and `subprocess.Popen`.

**Explicitly rejected:** passing `--js-runtimes deno:<path>`. That flag hard-errors on
older yt-dlp builds, turning a graceful degradation into a crash. `PATH` injection is
found-or-not, never fatal.

### Impersonation is opt-in

`curl-cffi` is installed but **not** applied by default. A new `TROVE_IMPERSONATE` env var
(unset by default) appends `--impersonate <target>` when set. Forcing impersonation on
every site is a regression risk, not a free win.

## 4 · Part B — the launcher

```
start-trove.command   ← double-click in Finder
      └── exec ./trove.sh "$@"
```

`start-trove.command` is a thin wrapper. Finder launches `.command` files with the working
directory set to `$HOME`, so its one real job is `cd "$(dirname "${BASH_SOURCE[0]}")"`
before delegating. Committed with the executable bit set.

`trove.sh` is rewritten around four stages:

1. **Preflight.** Probe `python3.14 → python3.11` plus bare `python3`, requiring `>=3.11`
   to match `pyproject.toml` (fixes B1, B7). Check ffmpeg and offer `brew install ffmpeg`
   when Homebrew is present. Detect a dead venv by *executing* `venv/bin/python` — a
   dangling interpreter symlink fails the exec and triggers a rebuild. Print a readable
   report, not a stack trace.
2. **Tiered install.** Core by default: `flask`, `yt-dlp` + extras, `psutil`,
   `pywhispercpp` (fixes B2/B3). `--full` additionally installs diarization
   (`resemblyzer`, `silero-vad`, `scikit-learn`), which pulls torch at roughly 1.3 GB.
3. **Stamp file.** `venv/.trove-stamp` stores a hash of the resolved dependency set. On a
   match with a healthy venv, pip is skipped entirely. This delivers the fast-restart
   benefit of a separate `setup.sh` without a second entry point a new user can run in the
   wrong order.
4. **Serve.** Background a poller that waits for the port to actually accept a connection,
   then `open`s the browser — not a blind `sleep`. Then `exec python3 app.py`.

Flags: `--full`, `--no-open`, `--help`. Preflight always prints its report, so no separate
`--doctor` flag is warranted.

### Non-goals

- Windows and Linux launchers. `trove.sh` stays POSIX-ish and keeps working on Linux, but
  only macOS gets the double-click wrapper this round.
- Bundling ffmpeg. Offer to install it; do not vendor it.
- Any change to app runtime behaviour, routes, or the transcript editor.

## 5 · Part C — README

Rewrite the quick start for the double-click flow. Document the Deno/EJS requirement and
keep the existing `TROVE_COOKIES_FROM_BROWSER` guidance, which `README.md:61` already
flags as required for YouTube.

## 6 · Verification

- `pytest` must pass. `tests/test_runner.py:10` asserts `argv[0] == "yt-dlp"` and the PATH
  change touches that code path, so this is a real gate, not a formality.
- A launch from a *deliberately deleted* venv must rebuild and serve — this is the exact
  state the machine is in today, so it is directly testable rather than hypothetical.
- `yt-dlp` must report a JS runtime as available after bootstrap.
- An actual download must succeed end to end.
