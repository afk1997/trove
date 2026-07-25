# trove.

*a saving machine for the modern web.*

paste a link, get the file. transcribe it. edit the transcript like a doc. all local, no accounts, no upload limits, no telemetry. self-hosted on your machine, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org/), and [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — works on YouTube, TikTok, Instagram, Vimeo, and ~1000 other sites.

![trove hero](docs/screenshots/hero.png)

---

## what's inside

- **save** — one paste box, MP4/MP3 toggle, quality picker. live progress with %, MB, fragment count, ETA.
- **bulk paste** — drop a wall of URLs, batch them all at once.
- **pause / resume** — pause a download mid-flight; closing the tab auto-pauses (resumes on next visit).
- **transcribe** — local whisper.cpp on every saved file. word-level timestamps. exports `.txt` / `.srt` / `.vtt`.
- **edit the transcript like a doc** — contenteditable paragraphs, click-to-edit words, autosave, paragraph split/merge, find + replace, undo/redo, bookmarks, highlights, notes.
- **speakers** — optional automatic speaker labels via local diarization (no HuggingFace login). rename inline; the rename propagates everywhere.
- **video stays in view** — side-rail with the video, compact player (play/scrub/speed), speakers list, bookmarks. single sticky topbar.
- **CLI + MCP** *(both alpha — see notes below)* — drive everything from your terminal, or expose Trove as MCP tools to Claude Desktop / Cursor / Replit Agent.
- **single Python process, single Docker container, no Node.** mobile-friendly. light only — riso paper is the brand.

| ![download in progress](docs/screenshots/download.png) | ![download complete](docs/screenshots/done.png) |
|---|---|
| **mid-download** | **saved** |

---

## quick start

**macOS — no terminal required.**

```bash
brew install python@3.14 ffmpeg      # the only two prerequisites
git clone https://github.com/afk1997/trove.git
```

then open the `trove` folder in Finder and **double-click `start-trove.command`**.

that's it. the first launch builds a virtualenv, installs everything, and opens
your browser at **http://localhost:8899** once the server is actually listening.
it takes a couple of minutes. every launch after that is near-instant, because
the dependency set is fingerprinted and skipped when nothing changed.

prefer a terminal, or on Linux? the wrapper just calls `./trove.sh`, so use that
directly:

```bash
cd trove
./trove.sh              # core: downloader + transcription
./trove.sh --full       # also install speaker diarization (pulls torch, ~1.3GB)
./trove.sh --no-open    # don't open a browser
./trove.sh --help
```

it checks your machine before doing anything and tells you exactly what to fix
if something is missing — Python ≥3.11, ffmpeg, and a virtualenv that still
points at an interpreter that exists. a venv orphaned by a Homebrew Python
upgrade is detected and rebuilt automatically rather than failing with a
`bad interpreter` error.

> **YouTube needs a JavaScript runtime.** yt-dlp now requires an external JS
> runtime to solve YouTube's challenges; without one, extraction is deprecated
> and formats go missing. trove installs [Deno](https://deno.com/) into its own
> virtualenv as a wheel, so there is nothing for you to install system-wide and
> nothing on your `PATH` to conflict with. you will also want
> `TROVE_COOKIES_FROM_BROWSER=safari` (or `chrome`, `firefox`, …) — Google
> blocks cookieless yt-dlp. see the env var table below.

*if macOS refuses to open `start-trove.command` because it "cannot be verified",
you downloaded the repo as a zip rather than cloning it. either `git clone`
instead, or run `xattr -d com.apple.quarantine start-trove.command` once.*

or with Docker:

```bash
docker build -t trove .
docker run -p 8899:8899 -e HOST=0.0.0.0 -e TROVE_ALLOW_UNAUTH_PUBLIC=1 trove
```

*the `-e HOST=0.0.0.0` is required for Docker port-forwarding. trove refuses to start on a non-loopback bind without auth — `TROVE_ALLOW_UNAUTH_PUBLIC=1` is the explicit "I know, I'm only exposing this to my host" opt-in. **for LAN/internet exposure, drop the opt-in and set `TROVE_TOKEN` instead — see below.***

<p align="center">
  <img src="docs/screenshots/mobile.png" alt="trove on mobile" width="320">
</p>

## configuration (env vars)

| variable | default | what it does |
|---|---|---|
| `HOST` | `127.0.0.1` | bind address. set to `0.0.0.0` only with a token. |
| `PORT` | `8899` | TCP port. |
| `TROVE_TOKEN` | *(unset)* | when set, every `/api/*` request must send `Authorization: Bearer <token>`. |
| `TROVE_ALLOW_UNAUTH_PUBLIC` | *(unset)* | set to `1` to allow `HOST=0.0.0.0` with no token (Docker port-forward, trusted LAN). without this opt-in, trove refuses to start on a non-loopback bind unless `TROVE_TOKEN` is set. |
| `TROVE_COOKIES_FROM_BROWSER` | *(unset)* | one of `safari\|chrome\|firefox\|brave\|edge`. required for YouTube right now (Google blocks cookieless yt-dlp). |
| `TROVE_IMPERSONATE` | *(unset)* | a yt-dlp impersonate target such as `chrome` or `safari`. makes yt-dlp mimic a real browser's TLS fingerprint for sites that block on it. off by default — impersonating everywhere is a regression risk on sites that don't need it. run `venv/bin/yt-dlp --list-impersonate-targets` to see what's available. |
| `TROVE_CONCURRENT_FRAGMENTS` | `4` | parallel fragment downloads for HLS streams (YouTube etc.). clamped 1–32. |
| `TROVE_JOB_TTL_SECONDS` | `3600` | how long completed jobs (and their files) linger before being swept. |
| `TROVE_MAX_WORKERS` | `4` | concurrent downloads. excess returns HTTP 503. |
| `TROVE_RATE_LIMIT` | `30` | requests per minute per IP. set to `0` to disable. |
| `TROVE_BATCH_MAX_URLS` | `50` | hard cap on URLs accepted per `/api/batch-download` request. |
| `TROVE_DIARIZATION` | `off` | `on` enables speaker labelling on transcribe (requires extra deps — see below). |
| `TROVE_EXTRACT_AUDIO_TIMEOUT` | `14400` | max seconds for the ffmpeg audio extract step (4 h covers any practical input). |

> **Note on `TROVE_TOKEN` + tab-close auto-pause:** when a token is set, the browser's `navigator.sendBeacon` cannot attach the `Authorization` header, so closing the tab mid-download will not POST to `/api/job/<id>/pause`. The download continues running on the server until it finishes naturally — or, if you stop the server first, it is downgraded to `paused` on next restart and reappears in the queue. No work is lost either way; only the live "pause indicator" UX is deferred. Local (`HOST=127.0.0.1`, no token) deployments are unaffected.

## exposing to LAN or the internet

the defaults assume **localhost only**. to expose trove safely:

1. set a token: `export TROVE_TOKEN=$(openssl rand -hex 32)`
2. set host: `export HOST=0.0.0.0`
3. run behind a reverse proxy that adds HTTPS (Caddy, nginx, fly.io, etc.).

without `TROVE_TOKEN`, anyone who can reach the port can download.

## YouTube and cookies

cookies are **recommended** for YouTube. short, public, non-monetized videos often work without them, but YouTube will eventually serve a sign-in wall for age-restricted content, certain regions, or longer/monetized uploads. to use cookies from your browser:

```bash
export TROVE_COOKIES_FROM_BROWSER=safari   # or chrome / firefox / brave / edge
./trove.sh
```

the browser must be installed on the host and have an active YouTube session.

## transcription

trove transcribes any saved audio or video locally using whisper.cpp. no api keys, no cloud, no telemetry.

**first time:**
1. save a media file (the existing flow)
2. on the saved card, click `▸ transcribe` — you'll see a one-time consent dialog
3. click `set it up ↗` — you'll land on `/transcribe/setup`
4. trove auto-detects your machine (Metal on M-series Mac, CUDA on NVIDIA Linux, AVX/CPU otherwise) and shows four model options with realistic speed estimates for *your* machine
5. pick one. trove downloads it from `huggingface.co/ggerganov/whisper.cpp` (one-time, ~140 MB for `base`)
6. you're done. transcription works offline forever after.

**after first setup:**
- click `▸ transcribe` on any saved card → progress bar → `▸ view transcript ↗` opens the transcript editor in a new tab
- check `auto-transcribe` on the paste form to start transcription automatically when each download finishes

**model storage:**
models live at `<trove>/models/ggml-*.bin`. swap or remove via the same setup page in settings mode (footer link `transcribe settings ↗`).

**Docker:** the model directory is auto-persisted via a Docker volume. To make it visible/mountable on the host, run:
```bash
docker run -v ./models:/app/models -v ./downloads:/app/downloads -p 8899:8899 trove
```

**network policy:** the only outbound calls trove makes are (1) yt-dlp fetching the original media, and (2) the model download from huggingface during the setup wizard. transcription itself is 100% local.

## transcript editor

the transcript page is a real document editor, not a passive viewer.

**layout** — single sticky topbar (title, saving indicator, undo / redo, search, export, more). document on the left (max 720 px). right rail with video, compact player (play / scrub / time / speed), speakers panel, bookmarks panel.

**editing**

- click any word → place your cursor and type to fix it. all edits autosave.
- `Enter` inside a paragraph splits it at the cursor. `Backspace` at the start of a paragraph merges it with the one above.
- `Cmd+Z` / `Cmd+Shift+Z` undo and redo.
- right-click a selection for: copy · highlight · bookmark · note · export selection · revert paragraph.

**playback + sync**

- double-click a word → seek the video to that timestamp.
- click a `[00:14]` time pill on a paragraph → seek to that paragraph's start (paused).
- `Alt + click` a word → seek without moving the cursor.
- the active word underlines as audio plays. the active paragraph gets a faint highlight. a `↓ jump to current` pill appears bottom-center if the active paragraph scrolls offscreen.
- `Space` play/pause, `J/L` skip ±5 s, `,/.` adjust speed, `Cmd+B` bookmark current time.

**word-timestamp realignment** — whisper.cpp without DTW places the first word after each silence ~300-500 ms early, and the error compounds. trove uses silero-vad's speech regions as ground truth and snaps drifted single-word timestamps forward to the next speech region's start. word durations are also clamped at 1.5 s so the active-word highlight never lingers across silences. (run `TROVE_DIARIZATION=on` to enable; the realignment piggy-backs on the same vad pass that diarization uses.)

**speakers**

- with `TROVE_DIARIZATION=on`, segments come back already labeled `Speaker 1`, `Speaker 2`, etc. (see next section).
- click any speaker label to rename — the new name propagates to every occurrence.
- the speakers panel in the side rail lights up the currently-talking row with an orange dot.
- without diarization, segments are split on speech pauses and speakers stay unlabeled; you can apply names manually from the rail.

**bookmarks · highlights · notes**

- bookmarks panel: `+ add bookmark` captures the current playback time. click a time pill to seek. edit the note inline.
- select any text and right-click → highlight to mark a passage; → add note to attach a comment to a word.
- highlights and notes persist in `.words.json` and survive transcribe-page reloads.

**find + replace**

- `Cmd+F` opens the search popover (find tab). `Cmd+Shift+F` opens find + replace.
- replace operates on every visible word; deleted words are skipped. the `case` toggle controls case-sensitivity.

**export**

- `.txt` / `.srt` / `.vtt` from the export menu. all three are regenerated from the current edits — your fixes ship.
- the `export selection` action on a right-click writes a stand-alone `.txt` of just the selection with timestamp markers.

**autosave detail** — every word edit, segment op, speaker rename, bookmark CRUD, etc. goes through a per-transcript txn lock on the server, writes the `.words.json` atomically (tempfile + `os.replace`), and regenerates the `.txt` / `.srt` / `.vtt` exports. you can close the tab any time; the document is the source of truth.

## speaker diarization

trove can auto-label speakers without any HuggingFace login or API key. The pipeline runs entirely on your machine:

1. **silero-vad** finds speech regions in the audio.
2. **resemblyzer** computes a 256-d voice embedding for overlapping 1.6 s windows inside each region.
3. **sklearn agglomerative clustering** (Ward + Euclidean) groups embeddings into speakers.
4. a 9-window median filter smooths single-window flips so a brief interjection doesn't create a phantom speaker.
5. each whisper word is assigned the speaker of the cluster covering its timestamp; consecutive same-speaker words become one paragraph.

Realistic accuracy on clean two-person audio is ~70 %. Sub-1.6 s turns (say one-word interjections) are below resemblyzer's resolution floor and get absorbed into the longer neighbour's chunk — rename or split the resulting paragraph by hand if it matters.

To enable:

```bash
pip install resemblyzer silero-vad scikit-learn   # ~800 MB (PyTorch is the bulk)
export TROVE_DIARIZATION=on
```

Without those deps installed, or with `TROVE_DIARIZATION=off` (the default), transcription behaves exactly as before — segments split on speech pauses and speakers stay unlabeled.

## CLI (alpha)

> **Status: unstable alpha.** `trove` (the CLI) and `trove-mcp` (the MCP server below) ship as functional but largely untested. Surfaces and command names may change before they're promoted to stable. Local use only — don't script around them in production yet.

`trove` talks to a running Trove server through the stable `/api/v1` JSON API. Stdlib-only — no extra deps.

```bash
# in the trove directory, with the venv activated
python cli.py serve                   # boot the server (alias for ./trove.sh)
python cli.py fetch URL [URL...]      # queue one or many downloads
python cli.py list                    # show jobs (id, status, %, title)
python cli.py get <id>                # full job detail
python cli.py wait <id>               # block until job is done / error / cancelled
python cli.py transcribe <id>         # kick off a transcribe
python cli.py transcript <tid>        # fetch transcript (.txt by default)
python cli.py export <tid> txt|srt|vtt
python cli.py search <tid> "query"    # find inside a transcript
python cli.py replace <tid> "old" "new"
python cli.py models list             # whisper models on disk
python cli.py models pull <name>      # download a model
```

Configure with env vars:

```bash
export TROVE_URL=http://127.0.0.1:8899   # server base URL
export TROVE_TOKEN=...                   # bearer token if the server has one
```

Run `python cli.py --help` for the full command list.

## MCP server (alpha)

> **Status: unstable alpha.** Same caveats as the CLI. Tested only against the contract; not yet exercised in real agent workflows.

`trove-mcp` exposes Trove's HTTP surface as [Model Context Protocol](https://modelcontextprotocol.io) tools so a coding agent (Claude Desktop, Cursor, Replit Agent, etc.) can drive Trove end-to-end — queue downloads, poll status, transcribe, edit transcripts, search, replace, manage models. Transport: stdio.

Wire it into your MCP client config:

```json
{
  "mcpServers": {
    "trove": {
      "command": "python",
      "args": ["/abs/path/to/trove/mcp_server.py"],
      "env": {
        "TROVE_URL": "http://127.0.0.1:8899",
        "TROVE_TOKEN": ""
      }
    }
  }
}
```

The Trove server itself must already be running on the URL the MCP client points at. Each tool returns a clear error if the server is unreachable so the agent knows to prompt the user to start it (`python cli.py serve`).

Tool surface mirrors the CLI 1:1 (intentional — there's a parity check in the test suite that fails if either side adds a tool the other doesn't have).

## stack

- **backend:** Python 3.12 + Flask
- **frontend:** htmx 2 + vanilla JS + Tailwind CSS (standalone CLI, no Node at runtime)
- **engine:** yt-dlp + ffmpeg + whisper.cpp (via pywhispercpp)
- **diarization (optional):** silero-vad + resemblyzer + scikit-learn
- **typography:** [Fraunces](https://fonts.google.com/specimen/Fraunces) (display, with the WONK + opsz variable axes), [Inter](https://fonts.google.com/specimen/Inter) (UI), [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono) (stamps), [Source Serif 4](https://fonts.google.com/specimen/Source+Serif+4) (transcript body)

## disclaimer

this tool is for personal use. respect copyright laws and the terms of service of platforms you download from.

## license

MIT. see [LICENSE](LICENSE).

---

inspired by [averygan/reclip](https://github.com/averygan/reclip) (MIT).
