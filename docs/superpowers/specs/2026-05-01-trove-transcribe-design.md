# Trove · Transcribe — design spec

**Status:** Draft (awaiting user review)
**Date:** 2026-05-01
**Branch (proposed):** `transcribe`
**Depends on:** `main` at `93e70a5` (post pause-resume merge)

---

## 1 · Goal

Add fully-local transcription to Trove. After a user saves a media file (audio or video), they can click **Transcribe**, see live progress, and end up on a searchable transcript page with word-level timestamps and click-to-seek video. Export `.txt` / `.srt` / `.vtt`.

The model itself is downloaded once from HuggingFace (the only outbound call this feature makes). After that, transcription is 100% local — no APIs, no telemetry, no cloud.

## 2 · Hard constraints (Trove's identity, non-negotiable)

- **Self-hosted.** No accounts. No API keys. No telemetry. No cloud calls during transcription.
- **whisper.cpp only.** Not the OpenAI Whisper API. Distributed via the `pywhispercpp` Python wrapper, which uses whisper.cpp internally and ships pre-built wheels with Metal/CoreML on macOS arm64, CUDA on NVIDIA Linux, AVX/AVX2 fallback on plain CPU.
- **One outbound call allowed:** the initial model download from `huggingface.co/ggerganov/whisper.cpp/resolve/main/<model>.bin`, cached locally and never re-fetched unless the user explicitly redownloads. No call to HF on any subsequent transcription.
- **Trove does the work.** The user never `wget`s a model, never edits a config file, never types a flag. The setup wizard fetches everything for them.

## 3 · v1 scope

### In

- **Card-level action:** new `▸ transcribe` link inside every `is-done` card on the home page (audio or video).
- **First-time consent dialog:** a one-time modal opens when a user clicks Transcribe for the first time, explaining what's about to happen (local processing, one-time model download, where the model comes from). Two buttons: `set it up ↗` and `not now`.
- **Setup page** at `/transcribe/setup`:
  - Detects the user's machine (OS, arch, GPU, CPU cores, RAM, free disk)
  - Shows four model options (tiny / base / small / medium) as cards, each with: filename, file size, expected speed estimate for *this* machine, accuracy stars, and the exact HuggingFace URL it will be fetched from
  - One click → Trove downloads the model with a live progress bar → atomic rename on completion → redirect back to the home page
  - **The same page doubles as transcribe settings.** After setup, returning to it shows the active model highlighted, with `switch to this ↗` controls on the others, plus `redownload` and `remove` on the active model.
- **Transcribe lifecycle on the card** (in-card, not a separate card):
  - `idle` → `▸ transcribe` link
  - `transcribing` → `▸ transcribing… 47% [⏵ cancel]`
  - `done` → `▸ view transcript ↗` (anchor with `target="_blank"` to `/transcript/<job_id>`)
  - `error` → `▸ transcribe failed · retry`
  - Cancellable mid-run.
- **Transcript page** at `/transcript/<job_id>` (opens in a new tab):
  - Two-pane layout: video/audio player on the left (sticky), transcript on the right (scrollable)
  - Each word is a `<span data-start="3.42">…</span>` — click to seek
  - Active word highlights in real time as the player plays (driven by `timeupdate`)
  - Pinned search bar above the transcript: vanilla JS substring match, highlight `.is-match`, up/down to jump between matches
  - Export buttons in the header: `.txt`, `.srt`, `.vtt`
  - Audio-only files swap `<video>` for `<audio controls>`; rest of the layout unchanged
- **Footer link** on the home page: `transcribe settings ↗` next to the existing `MIT · SELF-HOSTED · v1.0` strip — discoverable but out of the way.

### Out (deferred to v2+)

- Speaker diarization (whisper.cpp's quality is poor here)
- Per-job model picker (set globally; change in settings page)
- Manual language override (whisper auto-detects ≥99% of cases)
- Bulk transcribe / queue
- Inline transcript editing
- Pre-loaded model bundling in the Docker image (always download fresh on first run)
- Air-gapped / offline-only mode (no `TROVE_OFFLINE` env var; one path only)
- Transcript-level search across multiple jobs (single-doc search only)

## 4 · User flows

### 4.1 First-time transcribe

1. User clicks `▸ transcribe` on a `is-done` card.
2. Modal opens (htmx-injected overlay):
   ```
   About local transcription

   Trove transcribes audio and video using whisper.cpp,
   running entirely on your machine. Your media never
   leaves your computer.

   The first time you transcribe, Trove downloads a small
   AI model (~140 MB by default) from HuggingFace. This
   happens once — after that, transcription works without
   any internet connection.

   You'll be able to pick the model size, see your machine's
   capability, and review what's downloaded before it starts.

   [ not now ]   [ set it up ↗ ]
   ```
3. User clicks `set it up ↗` → browser navigates to `/transcribe/setup`.
4. Setup page shows machine probe + four model cards. User picks one.
5. Live download progress bar. Atomic rename to final filename on completion.
6. Green stamp, redirect back to the home page (origin URL stored in session).
7. User clicks `▸ transcribe` on the same card again → starts transcription immediately.

### 4.2 Subsequent transcribe (after first setup)

1. User clicks `▸ transcribe` on any `is-done` card.
2. No modal, no setup page. Transcription kicks off immediately.
3. The card's transcribe sub-region cycles through `idle → transcribing → done`.
4. User clicks `▸ view transcript ↗` → opens `/transcript/<id>` in a new tab.

### 4.3 Settings (changing model)

1. User clicks `transcribe settings ↗` in the home page footer.
2. Lands on `/transcribe/setup` (now in "settings" mode because a model is already installed).
3. Page sections:
   - Active model card (highlighted, with `redownload` and `remove` buttons)
   - Three other model cards (each with a `switch to this ↗` button)
   - Machine probe info (collapsed by default — click to expand)
4. Switching: same flow as first-time pick (download progress → rename → done). The previous model file is kept on disk so the user could switch back without re-downloading. (Old models can be removed manually with `remove` on each card.)

### 4.4 Errors

| Failure | Behavior |
|---|---|
| HF unreachable during model download | Clear inline message: *"Couldn't reach huggingface.co. Trove needs to download a transcription model just once — after that, everything runs offline forever. Check your connection and try again."* + retry button |
| Disk too small for the picked model | Setup page rejects the click client-side (the model card is already showing required vs available disk; just refuse to start the download) |
| whisper.cpp / pywhispercpp crashes mid-transcribe | TranscribeJob → `error` state. Card shows `▸ transcribe failed · retry`. Logs the exception. |
| User cancels mid-run | TranscribeJob → `cancelled`. The partially-extracted `.wav` and any in-progress JSON output are deleted. Card returns to `▸ transcribe` (idle). |
| Server restart during transcribe | On startup, any TranscribeJob in `running` state is downgraded to `error` (whisper has no checkpoint mechanism — restart loses progress). User reclicks `retry`. |

## 5 · Architecture (code units)

```
app.py
  + /transcribe/setup                     (GET, returns the wizard/settings page)
  + /api/transcribe/setup-model           (POST, kicks off model download)
  + /api/transcribe/setup-progress        (GET, htmx poll for download progress)
  + /api/transcribe/<parent_job_id>/start (POST, starts transcribe on a saved card)
  + /api/transcribe/<id>/status           (GET, htmx poll for transcribe progress)
  + /api/transcribe/<id>/cancel           (POST)
  + /api/transcribe/<id>/dismiss          (POST, removes the TranscribeJob)
  + /transcript/<id>                      (GET, full HTML viewer page)
  + /api/transcribe/<id>/export.<fmt>     (GET, fmt ∈ {txt, srt, vtt})

transcriber.py                            ← thin pywhispercpp wrapper
                                            run_transcribe(audio_path, model_path,
                                              progress_cb, cancel_check) → TranscriptResult
                                            (analogous to runner.run_download)

transcribe_jobs.py                        ← TranscribeJobManager (separate pool, separate
                                            persistence file, same lock + ThreadPoolExecutor
                                            pattern as JobManager)

machine.py                                ← detect OS, arch, GPU (Metal/CUDA/none),
                                            CPU cores, RAM, free disk on `models/` partition.
                                            No telemetry — values shown in setup UI only.

models_store.py                           ← list installed models, download a model
                                            (chunked, with progress callback), atomic
                                            rename, integrity check (SHA-256 from HF)

templates/
  transcribe_setup.html                   ← wizard / settings page (dual-purpose)
  transcript.html                         ← two-pane viewer
  partials/transcribe_consent.html        ← first-time modal (htmx fragment)
  partials/transcribe_action.html         ← in-card transcribe sub-region
                                            (states: idle / transcribing / done / error)
  partials/transcribe_setup_progress.html ← model-download progress bar fragment
  partials/model_card.html                ← single model card (used 4× in setup)

styles/input.css                          ← new sections:
                                              .modal-overlay (consent dialog)
                                              .setup-* (setup page layout, machine probe,
                                                        model cards)
                                              .clip-transcribe (in-card sub-region)
                                              .transcript-* (viewer page)
                                              .word.is-active / .word.is-match
                                              animations: download-progress, ink-stamp

models/                                   ← NEW. ggml-*.bin model files cached here.
                                              gitignored. NOT inside downloads/.

downloads/                                ← unchanged. Per-media transcript artifacts:
                                              <id>.wav  (extracted, deleted after success)
                                              <id>.txt
                                              <id>.srt
                                              <id>.vtt
                                              <id>.words.json   (for the viewer)

downloads/transcribe_jobs.json            ← new. Lives in downloads/ alongside
                                              the existing jobs.json — see §9.
                                              (App state coexists with media
                                              in the volume-mounted data dir.)

tests/
  test_transcriber.py
  test_transcribe_jobs.py
  test_machine.py
  test_models_store.py
  test_transcribe_endpoints.py
  fixtures/sample-2s.wav                   ← 2-second silent or "hello world" fixture
                                            for the e2e test (skipped if no model)
```

### Why a separate `TranscribeJob` (not extend `Job`)

The original download `Job` stays `DONE` forever once a media file lands. Transcribe is a *new* lifecycle that operates *on* that file — re-runnable (with a different model), independently cancellable, with its own progress + states. Putting it in the same model would force `Job.status` to encode two state machines and would break the rule that "DONE means the file is on disk and ready" (the user could click Transcribe and the card flips to `TRANSCRIBING`, even though the *download* is done).

Separation also keeps `Job` from accumulating sub-states as Trove grows new actions (archive, share, MCP-fetched).

### Why `pywhispercpp` (not bundled binary or system whisper-cli)

| Approach | Pros | Cons |
|---|---|---|
| **`pywhispercpp` (chosen)** | Pre-built wheels for macOS arm64 + Linux x86_64, Python API → structured word-timestamps (no stdout parsing), pip-installable alongside Flask, automatically picks up Metal on Mac and CUDA on Linux | Adds one more pip dep |
| Bundled `whisper-cli` binary in `tools/` | Symmetric with `tools/tailwindcss`, visible to user, easy to upgrade | We'd have to ship per-platform binaries (~5 MB each), parse JSON output ourselves, manage Metal/CUDA build flags |
| `brew install whisper-cpp` requirement | Simplest server code | Pushes install pain to the user — violates "Trove does all the work" |

`pywhispercpp` is added to `requirements.txt`. The Docker base already has Python and the build toolchain via the multi-stage Dockerfile; pywhispercpp's wheel install is a no-op compile.

### Audio extraction (video → wav)

`ffmpeg` is already required by Trove (already in Dockerfile and `trove.sh` checks). Extraction is a single shell-out:

```bash
ffmpeg -y -i downloads/<id>.mp4 -ar 16000 -ac 1 -c:a pcm_s16le downloads/<id>.wav
```

Audio-only files (mp3 / m4a / wav already): pywhispercpp accepts them directly via the same path; we still convert to a normalized 16 kHz mono WAV first for predictable behavior. Total transcription wall-clock includes the extract step (usually <2 seconds for typical lengths).

The `<id>.wav` is deleted after a successful transcribe (we don't need it anymore — the original media stays). Kept on cancel/error so retries don't re-extract.

## 6 · Setup wizard `/transcribe/setup` — page detail

### Header

```
NO. 002 / 2026                                       trove.
─────────────────────────────────────────────────────────────
                  TRANSCRIBE SETUP — STEP 1 OF 2
```

### Section 1 — Your machine (always visible during first-time setup; collapsed by default in settings mode)

```
┌────────────────────────────────────────────────────────────┐
│ ▸ machine probe                                             │
│ ──────────────                                              │
│ OS:        macOS 26.0 · arm64                               │
│ GPU:       Apple Metal · M1 Pro (8-core)                    │
│ CPU:       8 performance cores · 16 GB RAM                  │
│ Free disk: 238 GB on /                                      │
└────────────────────────────────────────────────────────────┘
```

`machine.py` populates this with stdlib `platform`, `psutil`, and (on macOS) `system_profiler SPDisplaysDataType` to find the GPU. Pure read-only inspection — values are rendered into the page and never sent anywhere.

### Section 2 — Pick a model

Four cards rendered via `partials/model_card.html`. Each card shows:

```
┌────────────────────────────────────────────────────────────┐
│ base                                  ggml-base.bin         │
│ ──────────────────                                          │
│ 142 MB   ·   ~3× realtime on your M1 Pro   ·   ★★★☆☆       │
│ multilingual                                                │
│                                                             │
│ source ↗ huggingface.co/ggerganov/whisper.cpp              │
│            /resolve/main/ggml-base.bin                     │
│ sha-256   65147a6...0c82a (verified after download)         │
│                                                             │
│                              [ pick this model ↗ ]          │
└────────────────────────────────────────────────────────────┘
```

The cards (tiny, base, small, medium):

| Model | File | Size | Accuracy | Speed × realtime (M1/M2 Mac) | Speed × realtime (8-core CPU) |
|---|---|---|---|---|---|
| tiny | ggml-tiny.bin | 39 MB | ★★☆☆☆ | ~10× | ~3× |
| base | ggml-base.bin | 142 MB | ★★★☆☆ | ~5× | ~1.5× |
| small | ggml-small.bin | 466 MB | ★★★★☆ | ~2× | ~0.6× |
| medium | ggml-medium.bin | 1.5 GB | ★★★★★ | ~0.8× | ~0.2× |

Speed columns are interpolated from the machine probe — the page picks the relevant column and shows that one number per card (no two-column table on the user side).

`base` is highlighted as the default recommendation. The "↗" indicates an outbound action.

### Section 3 — Download progress (after a card is picked)

The picked card swaps in-place (htmx) with a live download view:

```
┌────────────────────────────────────────────────────────────┐
│ ▸ downloading ggml-base.bin                                 │
│ ──────────────                                              │
│ ████████████████████░░░░░░░░░░░  64% · 91 MB / 142 MB       │
│ 7.4 MB/s · ~6s remaining                                    │
└────────────────────────────────────────────────────────────┘
```

When complete, the card flips to "active model" state with a riso `✓ INSTALLED` stamp, the header advances to `STEP 2 OF 2 — DONE`, and a small `← back to trove` button appears. The page also auto-redirects to the origin URL after 4 seconds.

### Settings mode (page revisits after a model is installed)

Same page, different rendering rules:
- Header reads `TRANSCRIBE SETTINGS` instead of `STEP 1 OF 2`
- Active model card is at the top, has a `✓ ACTIVE` stamp, and shows two extra controls: `redownload` (re-fetches and verifies SHA) and `remove` (deletes the .bin from `models/`)
- Other model cards still show `pick this model ↗` (which means "download and switch")
- Machine probe is collapsed by default; click to expand

## 7 · Card UX (in-card transcribe sub-region)

The DONE card grows a single new line in its body, between `→ ~/Downloads/...` and `↓ download again`:

```
┌──────────────────────────────────────────────────────────────────┐
│ ▣  How a Whisper hears the world.                  ✓ SAVED   ✕ │
│    → ~/Downloads/how-a-whisper-hears-the-world.mp4              │
│    ↓ download again                                              │
│    ▸ transcribe                                                  │
└──────────────────────────────────────────────────────────────────┘
```

Templates: `partials/transcribe_action.html`, with a top-level `{% if transcribe_state == "..." %}` switch.

| State | Renders |
|---|---|
| `idle` | `<a class="clip-transcribe" hx-post="/api/transcribe/<parent>/start" hx-target="closest .clip-transcribe-row" hx-swap="outerHTML">▸ transcribe</a>` |
| `transcribing` | `▸ transcribing… <pct>%   <button class="clip-transcribe-cancel">⏵ cancel</button>` — polls `/api/transcribe/<id>/status` every 2s |
| `done` | `<a class="clip-transcribe-view" href="/transcript/<id>" target="_blank">▸ view transcript ↗</a>   <button class="clip-transcribe-redo">↻</button>` |
| `error` | `<span class="clip-transcribe-err">▸ transcribe failed</span>   <button>retry</button>` |

The `▸` in front is consistent with the existing `▸ STEP 001` glyph in the hero plate — visual breadcrumb that this is a "trove action."

The first-time consent modal is injected at this layer too: when the user clicks `▸ transcribe` and the manager reports "no model installed," the response is the consent-modal HTML fragment, which targets `body` with `hx-swap="beforeend"` to inject the overlay.

## 8 · Transcript page `/transcript/<id>` — detailed layout

```
┌───────────────────────────────────────────────────────────────────────┐
│ trove.   transcript                                  [.txt][.srt][.vtt]│
│ ─────────────────────────────────────────────────────────────────────  │
│ NO. 002 / 2026   how a whisper hears the world.   12:00 · EN · base    │
│                                                                         │
│ ┌─────────────────────┐   [⚲ search transcript…]    [↑] [↓]           │
│ │                     │   ───────────────────────────────────────       │
│ │                     │                                                 │
│ │   ▶ video           │   Lorem ipsum dolor sit amet,                   │
│ │                     │   consectetur adipiscing elit. Sed do           │
│ │                     │   eiusmod [tempor] incididunt ut labore         │
│ │   1:42  /  12:00    │   et dolore magna aliqua. Ut enim ad            │
│ │                     │   minim veniam, quis nostrud exercitation       │
│ │  ━━━━━●─────────    │   ullamco laboris nisi ut aliquip ex ea         │
│ │                     │   commodo consequat.                            │
│ └─────────────────────┘                                                 │
│                                                                         │
│  trove. · self-hosted · MIT                              local · v1.0   │
└───────────────────────────────────────────────────────────────────────┘
```

### Layout

- Page is a single-column doc on small screens (mobile, ≤768px): video on top, transcript below
- Two-pane on ≥769px: video pinned to the left at ~40% width, transcript scrolls on the right at ~60%
- Video player is `<video controls preload="metadata">` for video; `<audio controls>` for audio-only
- Scroll the transcript independently; video stays in place

### Word spans

Server renders the transcript from `<id>.words.json` (an array of `{w, start, end}` objects):

```html
<p class="t-segment" data-seg-start="0.00">
  <span class="word" data-start="0.00" data-end="0.42">Lorem</span>
  <span class="word" data-start="0.42" data-end="0.96">ipsum</span>
  <span class="word" data-start="0.96" data-end="1.30">dolor</span>
  ...
</p>
```

Segments come from whisper's natural pauses — they read like paragraphs.

### Click-to-seek + active highlight

Inline JS (under the page's CSP nonce):

```js
const video = document.querySelector('video, audio');
const words = Array.from(document.querySelectorAll('.word'));

words.forEach((w) => {
  w.addEventListener('click', () => {
    video.currentTime = parseFloat(w.dataset.start);
    video.play();
  });
});

video.addEventListener('timeupdate', () => {
  const t = video.currentTime;
  // binary search over words by data-start
  let lo = 0, hi = words.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const start = parseFloat(words[mid].dataset.start);
    if (start <= t) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  document.querySelectorAll('.word.is-active').forEach((el) => el.classList.remove('is-active'));
  if (found >= 0) {
    words[found].classList.add('is-active');
    if (auto_scroll_enabled) words[found].scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
});
```

`.word.is-active` styling: orange dashed underline + slight `transform: translateY(-1px)`.

### Search

Vanilla JS over `words[]`, case-insensitive substring match. Matched spans get `.is-match` (cream background, dashed orange border). Up/Down arrow buttons jump the video timestamp to the next/prev match (`video.currentTime = parseFloat(matches[currentIdx].dataset.start)`).

### Export

Three buttons in the page header. Each is an `<a download href="/api/transcribe/<id>/export.<fmt>">`. Server reads `<id>.txt` / `<id>.srt` / `<id>.vtt` directly off disk and returns it with the right Content-Type. No on-the-fly generation — the files are written at transcription time.

### Audio-only fallback

Detection in the route handler: if the parent media file extension is in `{mp3, m4a, ogg, wav, flac}`, the template uses `<audio>` instead of `<video>`. The left pane gets a fixed-height block instead of a flex-grow video; everything else is identical.

## 9 · Data model

```python
# transcribe_jobs.py

class TranscribeStatus(str, enum.Enum):
    QUEUED      = "queued"
    RUNNING     = "running"
    DONE        = "done"
    ERROR       = "error"
    CANCELLED   = "cancelled"

@dataclass
class TranscribeJob:
    id: str                          # 10-char hex
    parent_job_id: str               # the original Job.id
    status: TranscribeStatus = QUEUED
    progress_pct: int = 0
    started_at: float = 0.0          # time.monotonic
    duration_seconds: float = 0.0    # source media duration (set on start)
    model_used: str = ""             # e.g. "ggml-base.bin"
    language_detected: str = ""      # iso code, set on completion
    error_category: str | None = None
    error_message: str | None = None
    process_handle: object | None = None  # for cancel; not persisted
```

`TranscribeJobManager` mirrors `JobManager`:

- `submit(parent_job_id, model_path, target) -> str` — registers job, fires worker into the executor.
- `cancel(transcribe_id) -> bool` — flips status, sets a flag the worker checks via `cancel_check`, persists.
- `get(id)`, `snapshot_jobs()`, `dismiss(id)` — same shapes as `JobManager`.
- Persists to `downloads/transcribe_jobs.json` alongside the existing `jobs.json`.

### Why two different locations (downloads/ vs models/)

The existing `JobManager` already persists `downloads/jobs.json`. Trove's data dir holds:

| What | Location | Why |
|---|---|---|
| Media files | `downloads/<id>.<ext>` | User's content |
| Transcript artifacts | `downloads/<id>.{txt,srt,vtt,words.json,wav}` | Tied to the media file, lives with it |
| App state | `downloads/jobs.json`, `downloads/transcribe_jobs.json` | Per-installation bookkeeping; volume-mounted with downloads |
| Model binaries | `models/<name>.bin` | Large redistributable binaries, separate concern from user content |

The user-facing distinction matters: media and transcripts are "things the user produced," models are "tools the app uses." Mixing them under `downloads/` would make `downloads/` confusing to explore. Models go to a sibling `models/` dir.

### `models/` directory

```
models/
  ggml-base.bin               (active, 142 MB)
  ggml-base.bin.sha256        (verified hash, written at install)
  ggml-tiny.bin               (kept around if user previously switched)
  ggml-tiny.bin.sha256
  ACTIVE                       (single-line file: "ggml-base.bin")
```

The `ACTIVE` file is the single source of truth for which model is current. Switching models = atomic rewrite of `ACTIVE`. Removing a model = delete the .bin + .sha256, and if it was active, clear `ACTIVE` (next transcribe re-prompts setup).

`models/` is gitignored.

### Persistence on restart

`TranscribeJobManager._load_from_store()`:
- Any job in `RUNNING` → downgrade to `ERROR` with `error_category="server_restart"`. (whisper has no resume; user must retry.)
- `QUEUED` → also downgrade to `ERROR` (worker thread is gone).
- `DONE`, `ERROR`, `CANCELLED` → keep as-is.

The card-side template renders the `error` state with a friendly retry button, so the user doesn't need to know the difference between "crashed during" and "server was restarted during."

## 10 · Network policy (constraint compliance recap)

| Outbound call | When | Frequency |
|---|---|---|
| yt-dlp fetching the original media | Existing download flow | Per save |
| HuggingFace model download | Setup wizard / settings — user clicks `pick this model` or `redownload` | Once per model swap |
| **Transcription itself** | — | **Never. Pure local pywhispercpp.** |

No telemetry. No analytics. No "phone home" check on app start. No automatic model auto-update. No background license check. Trove makes outbound HTTP calls only when the user pushes a button that explicitly says "this will fetch something from the internet."

## 11 · Distribution / dependencies

### Python deps (added to `requirements.txt`)

```
pywhispercpp>=1.2.0  # whisper.cpp Python wrapper, prebuilt wheels for macOS arm64 + linux_x86_64
psutil>=5.9          # for machine probe
```

### System deps (already required)

- `ffmpeg` — for audio extraction. Trove already requires this.

### Docker

`Dockerfile` adds:

```dockerfile
# Build stage already has python:3.12 + Tailwind etc.
RUN pip install --no-cache-dir pywhispercpp psutil

# Persist downloaded models across container restarts
VOLUME /app/models
```

The `VOLUME` declaration means Docker auto-creates a persistent named volume backing `/app/models` on the first `docker run`. Users who want explicit control can add `-v ./models:/app/models` to their run command. The README documents both options.

### Non-Docker

`pip install -r requirements.txt` picks up `pywhispercpp` and `psutil`. `models/` is created as needed inside the trove repo dir. No additional setup.

### Platform support

| Platform | whisper.cpp backend | Tested in CI |
|---|---|---|
| macOS arm64 (M-series) | Metal + Core ML | yes |
| macOS x86_64 (Intel) | AVX2 (no GPU) | yes |
| Linux x86_64 (generic) | AVX2 | yes |
| Linux x86_64 + NVIDIA | CUDA via pywhispercpp's CUDA wheel | manual |
| Windows | not supported in v1 | — |

Windows path: defer. pywhispercpp does ship Windows wheels, but the Trove install scripts (`trove.sh`) are bash-only. v2.

## 12 · Testing

### Unit tests

| File | Coverage |
|---|---|
| `tests/test_machine.py` | machine.probe() returns expected fields, handles missing GPU gracefully, monkey-patches platform/psutil |
| `tests/test_models_store.py` | list_installed_models, set_active, remove, atomic download via mocked HTTP + tempfile, SHA-256 verification |
| `tests/test_transcriber.py` | run_transcribe with a fake pywhispercpp (returns canned word array), respects cancel_check, calls progress_cb, returns expected dict shape |
| `tests/test_transcribe_jobs.py` | TranscribeJobManager lifecycle: submit/cancel/dismiss/snapshot/persist/restart-recovery |
| `tests/test_transcribe_endpoints.py` | All new routes: setup-page render (first-time vs settings), /start (with + without model installed), /cancel, /status htmx fragment, /export.{txt,srt,vtt} content-types |

### One end-to-end test (skipped unless model present)

`tests/test_transcribe_e2e.py` runs the full extract → transcribe → export pipeline against `tests/fixtures/sample-2s.wav` (a 2-second "this is a test" clip checked into the repo). Skips with `pytest.skip` if `models/ggml-tiny.bin` isn't present (CI doesn't auto-download models). Locally, devs can `pip install pywhispercpp && python scripts/fetch_test_model.py` to enable the test.

### Target

- **Unit tests:** ~30 new
- **End-to-end:** 1 (skipped in CI)
- **Total goal:** Trove suite goes from 109 → ~140 passing (+ 1 skipped)

### Reduced-motion + a11y

- All animations (download progress bar, ✓ INSTALLED stamp slam, model card hover lifts) wrapped in `@media (prefers-reduced-motion: no-preference)` opt-ins. With `reduce` set, transitions go to 0.01ms (existing pattern in `styles/input.css`).
- Modal focus trap on the consent dialog. Esc closes.
- Word spans on the transcript page: `<span class="word" tabindex="0" role="button" aria-label="word at 3.42 seconds">Lorem</span>` — keyboard-clickable and screen-reader-friendly.
- Search input has `<label for="search" class="sr-only">Search transcript</label>`.

## 13 · Out of scope (explicitly named)

- **Speaker diarization.** whisper.cpp's quality is poor here; specialized models exist but add complexity. v2.
- **Manual language override.** Default to whisper's auto-detect. Edge cases (mixed-language, mumbled speech) can re-transcribe with a different model size as a workaround. v2 may add a language picker on the card or in settings.
- **Re-transcribe with a different model from inside the transcript page.** v1 only allows: (a) cancel/dismiss the existing TranscribeJob from the home card, then click `▸ transcribe` again. The viewer is read-only.
- **Inline edit / correction of the transcript.** v2 maybe.
- **Cross-transcript search** (search across all transcripts at once, in a library view). v2.
- **Air-gapped install** — no `TROVE_OFFLINE` env var. The setup wizard's HF download is the only path. If a user truly can't reach HF, they'll need to manually drop a `.bin` into `models/` themselves and write `ACTIVE` — but this is unsupported and not documented.
- **Pre-bundled model in the Docker image.** Image stays small; model fetched at first setup.
- **Bulk transcribe multiple cards at once.** v1 is one-at-a-time. The job pool can already serialize; a "transcribe all" button is a v2 UX add.
- **Streaming live transcription** (microphone input). Different feature entirely.

---

## 14 · Open questions to resolve during implementation (low-risk)

1. **Model speed estimate table** — the speed × realtime numbers in §6 are based on public whisper.cpp benchmarks, but Trove should verify on the user's actual machine after first transcribe and persist a measured `realtime_factor` in `transcribe_jobs.json`. v1 ships the lookup table; future runs refine.
2. **Auto-scroll on active word** — should the transcript auto-scroll to keep the active word visible? Default: ON, with a small toggle in the header (`☑ follow along`). Saves a v2 question.
3. **Word span density** — long transcripts could be 5,000+ word spans. Render performance check needed; if poor, fall back to segment-level click-to-seek (per-paragraph) for very long files (>15 min audio).

These don't block the design but should be flagged in the implementation plan.

---

## Verification (how we'll know it works)

1. Run `pytest -q` → 140 passing, 1 skipped (the e2e test in CI).
2. Manual smoke on macOS arm64:
   - Save a YouTube video (existing flow). Card lands `is-done`.
   - Click `▸ transcribe` → first-time consent modal appears. Click `set it up ↗`.
   - On `/transcribe/setup`, machine probe shows correct values. Click `pick this model ↗` on `base`.
   - Live progress bar reaches 100%. ✓ INSTALLED stamp. Auto-redirect to home.
   - Click `▸ transcribe` again → polls progress 0% → 100%.
   - Click `▸ view transcript ↗` → opens `/transcript/<id>` in new tab.
   - Click any word → video seeks. Search "lorem" → matches highlight.
   - Export `.srt` → file downloads. Open it — it's a valid SRT.
   - Footer link `transcribe settings ↗` → returns to setup page in settings mode. Active model highlighted. Click `switch to this ↗` on `tiny` → swap completes. `ACTIVE` file updated.
3. Restart the app mid-transcribe (kill -9). Reload home — card shows `▸ transcribe failed · retry`. Click retry → completes.

End of spec.
