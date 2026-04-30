# Trove — Speed flags + Pause / Resume

**Date:** 2026-04-29
**Status:** Design approved · awaiting implementation plan
**Author:** Brainstorm session w/ Kaivan
**Inspired by:** [PBhadoo/QDM](https://github.com/PBhadoo/QDM) (Tauri/Rust IDM-class downloader); reimagined using yt-dlp's built-in flags rather than a custom Rust segmenting engine

---

## 1. Why

Trove currently runs yt-dlp single-stream with default settings. YouTube/HLS downloads at one fragment at a time, partial downloads are deleted on cancel, and there's no way to pause a job — it's run-to-completion or discard. QDM ships an IDM-class engine: parallel segments, full pause/resume, persistence across restarts. We want that user-facing capability in Trove without hand-rolling a Rust engine, by leaning on yt-dlp's `--concurrent-fragments` flag and its built-in `--continue` resume behavior.

The promise of the redesign tagline ("save things you care about") is undermined when an interrupted download throws away the bytes. Pause/resume turns the queue into a place where work is preserved across the crashes and restarts and tab-closes that real users hit.

User decisions (from brainstorm):

- **Pause and Cancel are distinct actions** (Q1·A). Pause keeps `.part` files; cancel deletes them.
- **Persist job state to disk** (Q2·A) so paused jobs survive restarts.
- **Stay paused after restart** (Q3·A) — no auto-resume; user explicitly clicks resume.
- **Tab-close auto-pauses active downloads** (Q4·A) instead of cancelling them.

---

## 2. Speed flags

Two existing yt-dlp flags wired into `runner.build_download_argv`:

```python
"--concurrent-fragments", str(CONCURRENT_FRAGMENTS),  # default 4
"--retries", "5",
"--fragment-retries", "10",
```

`CONCURRENT_FRAGMENTS` reads `os.environ.get("TROVE_CONCURRENT_FRAGMENTS", "4")` once at app start and is clamped to `[1, 32]`. yt-dlp's flag parallelizes only HLS/DASH downloads (the protocol used by YouTube, TikTok, Instagram Reels, Vimeo) — it has no effect on direct HTTP files. That covers the dominant trove use case. Direct-HTTP multi-segment via `--downloader aria2c` is **explicitly out of scope** for v1 (see §10).

Default of 4 is conservative: enough to triple typical YouTube speed without making CDNs angry. Users on big pipes can crank to 8 or 16 via the env var.

`--retries 5 --fragment-retries 10` are also new defaults — yt-dlp's defaults are higher (10/10), but with concurrent fragments a stuck connection should fail faster.

## 3. Job state model

`JobStatus` gains one new value:

```python
class JobStatus(str, enum.Enum):
    QUEUED       = "queued"
    DOWNLOADING  = "downloading"
    PAUSED       = "paused"        # NEW
    DONE         = "done"
    ERROR        = "error"
    CANCELLED    = "cancelled"
```

Allowed transitions:

| From | Action | To | Side effects |
|---|---|---|---|
| `QUEUED` | start (worker pulls) | `DOWNLOADING` | spawn yt-dlp Popen |
| `QUEUED` / `DOWNLOADING` | pause | `PAUSED` | `proc.kill()`; `.part` files **preserved**; persist state |
| `QUEUED` / `DOWNLOADING` / `PAUSED` | cancel | `CANCELLED` | `proc.kill()` if running; `_cleanup_glob()` removes `.part`; persist state |
| `PAUSED` | resume | `DOWNLOADING` (re-queues) | re-submit `_work` to executor; yt-dlp picks up `.part` via `--continue` (default-on) |
| `DOWNLOADING` | (yt-dlp returncode 0) | `DONE` | sanitize filename, persist |
| `DOWNLOADING` | (yt-dlp returncode != 0 and not killed by pause) | `ERROR` | classify error, `_cleanup_glob()` |
| `DONE` / `ERROR` / `CANCELLED` | TTL sweep | (removed) | delete file if any |

Cancel-from-paused removes the partial bytes so users have a clean way to discard work-in-progress.

The pause/cancel difference is whether `_cleanup_glob(out_template)` runs. Pause skips it; cancel calls it.

## 4. Persistence — `JobStore`

New module `jobs_store.py` (~80 lines). Persists the JobManager's in-memory dict to a single atomic JSON file at `downloads/jobs.json`. Format:

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "80b8006af2",
      "url": "https://www.youtube.com/watch?v=…",
      "title": "Rick Astley — Never Gonna Give You Up",
      "thumbnail": "https://i.ytimg.com/vi/…/maxresdefault.jpg",
      "format_choice": "video",
      "format_id": "137",
      "status": "paused",
      "downloaded_bytes": 8421376,
      "total_bytes": 38453200,
      "speed": 0.0,
      "eta": 0,
      "fragment_index": 12,
      "fragment_count": 38,
      "out_template": "downloads/80b8006af2.%(ext)s",
      "filename": null,
      "file_path": null,
      "error_category": null,
      "error_message": null,
      "created_at": 1714400000.0,
      "last_accessed": 1714400000.0
    }
  ]
}
```

### 4.1 Atomic write

```python
def persist(jobs: dict[str, Job], path: Path) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_serialize(jobs), indent=2))
    os.replace(tmp, path)  # atomic rename
```

Called by `JobManager` after every state mutation. Read once at startup. Single-writer model — only the Flask process writes; if multiple processes ever run, last-writer-wins (acceptable for a self-hosted single-user tool).

### 4.2 Startup recovery

In `app.create_app()`, after `JobManager` instantiation:

```python
job_manager.load(DOWNLOAD_DIR / "jobs.json")
```

Behavior:

- `DOWNLOADING` jobs found at startup are **downgraded to `PAUSED`** — they were interrupted by the restart; resuming requires user action.
- `QUEUED` jobs are also downgraded to `PAUSED` (their `_work` thunk is gone; treat as paused so the user can re-queue them by clicking resume).
- `PAUSED`, `DONE`, `ERROR` keep their status as-is.
- `CANCELLED` jobs are dropped from the load (no point keeping them post-restart).

### 4.3 What's NOT in JobStore

- The `process` field (the live `Popen` handle) is in-memory only.
- The `_work` callable closure (which holds the URL/format/title) is in-memory only — but **its inputs are stored** in the JSON so we can rebuild it on resume.

The Job dataclass needs a `resume_args` field (or inline url/format_choice/format_id/title/thumbnail/out_template) so the work closure can be reconstructed without the original `_enqueue_download` context. This is just plumbing — store the kwargs, recreate the thunk on resume.

## 5. New API endpoints

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/job/<id>/pause` | Mark job PAUSED, kill subprocess if running, preserve `.part`. Returns 200 with paused card HTML. Idempotent: if already PAUSED, just returns the card. |
| `POST` | `/api/job/<id>/resume` | Mark DOWNLOADING, re-submit work thunk to JobManager pool. Returns 200 with downloading card HTML. Idempotent: if already DOWNLOADING, returns the card. |

Existing `POST /api/job/<id>/cancel` stays. Cancel from PAUSED additionally calls `_cleanup_glob()`.

All three endpoints token-protected via existing `@token_required` decorator.

## 6. Runner changes

`run_download(...)` is unchanged in signature. Internally:

- The progress callback continues to update Job fields under the lock.
- The `register_process(popen)` callback is what JobManager uses to kill the process for both pause and cancel.
- A new boolean — `_was_paused: bool` — is set on the Job by the pause endpoint **before** killing the process. The streaming loop in `run_download` checks this flag in the cleanup branch: if true, skip `_cleanup_glob()` (preserve `.part`); if false (real error or cancel), run cleanup as before.

This avoids passing a new kwarg through several layers; the Job already round-trips through every callback.

`build_download_argv` adds the three new flags listed in §2.

## 7. UI changes

### 7.1 `.clip.is-downloading` (existing, augmented)

Action column gains a pause button above the existing implicit cancel:

```html
<div class="clip-action">
  <button class="clip-pause" formaction="/api/job/{{ card.id }}/pause">⏸</button>
  <span class="clip-saving-stamp">Saving<span class="ellipsis">…</span></span>
  <button class="clip-cancel" formaction="/api/job/{{ card.id }}/cancel">✕</button>
</div>
```

(Buttons are htmx forms with `hx-post` + `hx-target="closest .clip"` + `hx-swap="outerHTML transition:true"` so they swap the card with the response from the endpoint. Concrete markup in the implementation plan.)

### 7.2 `.clip.is-paused` (new)

```html
<div class="clip is-paused" data-job-id="{{ card.id }}" data-status="paused">
  {{ thumb(card) }}
  <div class="clip-body">
    <p class="clip-title">{{ card.title or "untitled" }}</p>
    <p class="clip-meta">
      {{ "%.1f"|format(card.downloaded_bytes / 1048576) }} MB
      {% if card.total_bytes %}
        <span class="sep">/</span>{{ "%.1f"|format(card.total_bytes / 1048576) }} MB
        <span class="sep">·</span>{{ card.percent }}%
      {% elif card.fragment_count %}
        <span class="sep">·</span>FRAG {{ card.fragment_index }}/{{ card.fragment_count }}
      {% endif %}
      <span class="sep">·</span>PAUSED
    </p>
  </div>
  <div class="clip-action">
    <button class="clip-resume" hx-post="/api/job/{{ card.id }}/resume" …>▶ resume</button>
    <button class="clip-cancel" hx-post="/api/job/{{ card.id }}/cancel" …>✕</button>
  </div>
  <div class="clip-progress">
    <div class="clip-progress-fill" style="width: {{ card.percent or 0 }}%"></div>
  </div>
</div>
```

### 7.3 CSS for paused state

```css
.clip.is-paused {
  border-color: var(--teal);          /* not orange like downloading */
  border-style: dashed;                /* signals "interrupted" */
  box-shadow: 2px 2px 0 var(--teal);   /* smaller shadow */
  filter: saturate(0.6);               /* desaturate the whole card */
}
.clip.is-paused .clip-thumb { filter: grayscale(0.3); }
.clip.is-paused .clip-progress-fill { opacity: 0.6; }

.clip-resume {
  font-family: 'Inter', sans-serif;
  font-size: 11px; font-weight: 700;
  letter-spacing: 0.22em; text-transform: uppercase;
  background: var(--orange);
  color: var(--light);
  border: 1.5px solid var(--teal);
  padding: 7px 16px;
  box-shadow: var(--shadow-stamp);
  transform: rotate(-1deg);
  cursor: pointer;
}
.clip-pause, .clip-cancel {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  background: transparent;
  color: var(--teal);
  border: 1.5px solid var(--teal);
  padding: 4px 8px;
  cursor: pointer;
}
.clip-pause:hover { color: var(--orange); border-color: var(--orange); }
.clip-cancel:hover { color: var(--orange); border-color: var(--orange); }
```

### 7.4 Tab-close behavior (`base.html`)

```js
window.addEventListener('beforeunload', function () {
  for (var id of window.__troveActiveJobs) {
    try { navigator.sendBeacon('/api/job/' + id + '/pause'); } catch (_) {}
  }
});

function refreshActiveJobs() {
  var active = new Set();
  document
    .querySelectorAll('[data-job-id][data-status="downloading"], [data-job-id][data-status="paused"]')
    .forEach(function (el) { active.add(el.dataset.jobId); });
  window.__troveActiveJobs = active;
}
```

Tab close pauses any in-flight downloads. Reopen restores the queue from `jobs.json` with those jobs in the `paused` state.

## 8. Tests

- `test_jobs_store.py` — round-trip serialize/deserialize, atomic write, malformed JSON tolerance, version-mismatch handling.
- `test_jobs.py` — pause/resume/cancel state transitions, pause from each starting state, cancel-from-paused removes `.part` (mock), startup `DOWNLOADING → PAUSED` downgrade.
- `test_endpoints.py` — `/api/job/<id>/pause`, `/api/job/<id>/resume` happy path + idempotency + 404 for unknown id + 401 with token.
- `test_runner.py` — existing tests pass unchanged (no signature changes).

Existing 63 tests stay green.

## 9. Files modified / created

| File | Change |
|---|---|
| `runner.py` | +3 lines for new flags; check `Job._was_paused` in cleanup branch |
| `jobs.py` | +`PAUSED` status; +`pause()` / `resume()` methods on `JobManager`; `Job` gains `resume_args` dict and `_was_paused` flag |
| `jobs_store.py` | NEW (~80 lines) — atomic JSON read/write |
| `app.py` | +`/api/job/<id>/pause`; +`/api/job/<id>/resume`; load store on startup; persist hook |
| `templates/base.html` | beforeunload sendBeacon → `/pause`; refreshActiveJobs selector |
| `templates/partials/card.html` | new `.clip.is-paused` branch; pause+cancel buttons inside `.is-downloading` |
| `styles/input.css` | `.clip.is-paused` + `.clip-pause` + `.clip-resume` + `.clip-cancel` styles |
| `tests/test_jobs.py` | +pause/resume tests, startup recovery test |
| `tests/test_endpoints.py` | +endpoint tests |
| `tests/test_jobs_store.py` | NEW |

Total: ~250–300 lines of code change + ~120 lines of tests.

## 10. Out of scope (YAGNI)

- **aria2c integration.** Direct-HTTP multi-segment via `--downloader aria2c --downloader-args "aria2c:-x16 -k1M"` would speed up direct file URLs (Cloudflare CDN, S3, raw mp4). Costs: extra dep (`brew install aria2`), separate progress format to parse, larger code surface. Most trove URLs are HLS sources where `--concurrent-fragments` already covers the win. Revisit if real users hit direct-HTTP throughput limits.
- **Per-segment progress visualization.** QDM shows N mini progress bars per active download. yt-dlp doesn't expose per-fragment progress in a useful way; would need intercepting `--progress-template` for each fragment. Single bar covers it.
- **Resume across machines / cloud sync of `jobs.json`.** Out of scope; trove is local-first.
- **Auto-resume on startup.** Q3 was an explicit no.
- **Pausing the *queue itself* (not individual jobs).** All-pause / all-resume buttons. Reasonable v2 feature but not needed for v1.

## 11. Risks

- **Concurrent fragments + slow servers.** Some HLS origins throttle hard at >4 concurrent. Default 4 mitigates; users who set 16 may see 429 errors. yt-dlp's retry handles transient 429s with `--retries 5` and `--fragment-retries 10`.
- **`.part` files orphaning.** If a paused job is dropped from `jobs.json` (e.g., user manually edits the file), the `.part` files in `downloads/` orphan. The existing TTL sweep will eventually clean by glob, but until then they take disk space. Acceptable.
- **Race condition on resume.** Between marking DOWNLOADING and actually spawning the process, a second user request could trigger another resume. Idempotency via state check at the top of `resume()`: if status is already `DOWNLOADING`, return the current card.
- **Persistence timing.** Writing JSON on every progress update would thrash the disk. **Only persist on status change**, not on progress tick. Progress fields update in-memory; the JSON snapshot is only written when state transitions occur.
- **CSP nonces on new htmx forms.** Cards are server-rendered; htmx attributes are inert until JS runs. The `<script nonce="…">` block in `index.html` already runs htmx; new card buttons inherit. No new inline event handlers.

## 12. Microcopy

| Surface | Copy |
|---|---|
| Pause button (downloading card) | `⏸` (icon-only, 12px Plex Mono char) |
| Cancel button (downloading & paused cards) | `✕` (icon-only) |
| Resume button (paused card) | `▶ resume` |
| Saving stamp on downloading card | `Saving…` (unchanged) |
| Card meta on paused card | `<MB> / <total MB> · NN% · PAUSED` or `<MB> · FRAG i/n · PAUSED` |
| Tooltip on pause | `Pause download (keeps partial bytes)` |
| Tooltip on cancel | `Cancel download (deletes partial bytes)` |

## 13. Implementation note

The brainstorm scoped this as "single high-leverage commit." Realistically it's 2–3 commits:

1. Speed flags (4 lines) — ship it independently, immediate win.
2. Pause/Resume backend (state model + endpoints + JobStore + UI) — bulk of the work.
3. Tests + polish.

The implementation plan (next document) will lay out task-by-task ordering.

---

**End of design.**
