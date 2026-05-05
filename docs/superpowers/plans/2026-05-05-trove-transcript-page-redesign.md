# Trove · transcript page v4 redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-stacked-sticky-bars + floating-video layout with a single 60 px sticky topbar plus a permanent 320 px right rail housing video, player, speakers, and bookmarks.

**Architecture:** All-presentation rewrite of `templates/transcript.html` and `styles/input.css`. Two-column grid: `.t-doc-body` left (max 720 px), `.t-sidebar` right (320 px, sticky). Backend, schema, and editor endpoints unchanged.

**Tech Stack:** Jinja2 templates, vanilla CSS in `@layer components`, CSP-nonced inline JS, htmx 2 for endpoint calls, pytest for rendering tests.

**Spec:** `docs/superpowers/specs/2026-05-05-trove-transcript-page-redesign-design.md`

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `templates/transcript.html` | Page markup + inline CSP-nonced `<script>` | Restructure (big diff) |
| `styles/input.css` | Riso component styles, sticky/grid scaffolding, active-state CSS | Replace zones B/C and `.t-video-rail` block; add `.t-topbar`, `.t-sidebar*` rules |
| `static/app.css` | Built Tailwind + component output | Regenerate via `tools/tailwindcss --minify` |
| `tests/test_transcript_view_layout.py` | NEW: structural assertions on the rendered transcript page | Create |
| `tests/test_transcript_extras_endpoints.py` | Existing tests that scrape `.t-tb-*` selectors | Update selectors |
| `tests/conftest.py` | Existing test fixtures | No change |

Backend Python (`app.py`, `routes/transcript_editor.py`, `transcript_io.py`, `transcriber.py`, `diarizer.py`, `transcribe_jobs.py`): **zero changes**.

---

## Conventions

- Every code edit ships with a passing pytest. Each task ends with a `git commit`.
- Test runner: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest`.
- Tailwind rebuild: `/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss -i styles/input.css -o static/app.css --minify`.
- Server smoke: `PORT=8899 HOST=127.0.0.1 TROVE_DIARIZATION=on /Users/kaivan108icloud.com/Downloads/trove/venv/bin/python app.py`.
- Strict CSP: never add a second `<script>` tag — extend the existing one.
- All new CSS goes in the existing `@layer components` block (top scope, NOT inside `@media`).

---

## Task 1: Layout test scaffold

**Files:**
- Create: `tests/test_transcript_view_layout.py`

- [ ] **Step 1: Write the failing structural tests**

Create `tests/test_transcript_view_layout.py`:

```python
"""Structural assertions on the rendered v4 transcript page.

These don't assert visual correctness — that's manual QA — but they
lock down the markup contract so that the layout we ship can't silently
regress to the v3 three-sticky-bars + floating-video shape.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import app as app_mod
import transcribe_jobs
from jobs import Job, JobStatus


@pytest.fixture
def client_with_done_transcript(tmp_path, monkeypatch):
    """Spin up an app pointed at tmp_path, with one DONE parent job and
    one DONE transcribe job whose words.json contains two speakers and
    two bookmarks. Yields (test_client, transcribe_id)."""
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setattr(app_mod, "DOWNLOAD_DIR", tmp_path)
    a = app_mod.create_app()

    media = tmp_path / "src.mp4"
    media.write_bytes(b"fake-media")
    jm = a.extensions["trove.jobs"]
    def _noop(j):
        j.file_path = str(media)
        j.filename = "src.mp4"
    parent_id = jm.submit(target=_noop, title="Test clip", url="https://x")
    while jm.get(parent_id).status not in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED):
        pass

    base = os.path.splitext(media)[0]
    import json
    payload = {
        "schema_version": 2,
        "language": "en",
        "duration": 90.0,
        "edited_at": None,
        "title": None,
        "highlights": [],
        "notes": [],
        "words": [
            {"idx": 0, "w": "Hello", "original_w": "Hello",
             "start": 1.0, "end": 1.5, "edited": False, "deleted": False},
            {"idx": 1, "w": "world", "original_w": "world",
             "start": 1.5, "end": 2.0, "edited": False, "deleted": False},
            {"idx": 2, "w": "Yes", "original_w": "Yes",
             "start": 5.0, "end": 5.5, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 1.0, "end": 2.0, "text": "Hello world",
             "word_idxs": [0, 1], "speaker": "Speaker 1", "reviewed": False},
            {"start": 5.0, "end": 5.5, "text": "Yes",
             "word_idxs": [2], "speaker": "Speaker 2", "reviewed": False},
        ],
        "bookmarks": [
            {"id": "bm_a", "time": 14.0, "note": "setup question"},
            {"id": "bm_b", "time": 68.0, "note": "hours"},
        ],
    }
    Path(base + ".words.json").write_text(json.dumps(payload))

    tm = a.extensions["trove.transcribe"]
    def _target(tj, *, model_path):
        tj.duration_seconds = 90.0
        tj.language_detected = "en"
    tjid = tm.submit(parent_job_id=parent_id, model_path="ignored", target=_target)
    while tm.get(tjid).status not in (
        transcribe_jobs.TranscribeStatus.DONE,
        transcribe_jobs.TranscribeStatus.ERROR,
        transcribe_jobs.TranscribeStatus.CANCELLED,
    ):
        pass

    with a.test_client() as c:
        yield c, tjid


def test_renders_single_topbar(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    rv = c.get(f"/transcript/{tjid}")
    assert rv.status_code == 200
    body = rv.data.decode()
    assert 't-topbar' in body, "v4 topbar must render"
    assert 't-doc-toolbar' not in body, "v3 toolbar zone must be removed"
    assert 't-player-bar' not in body, "v3 player bar zone must be removed"


def test_renders_two_column_grid(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-grid' in body
    assert 't-doc-body' in body
    assert 't-sidebar' in body


def test_renders_sidebar_video_player_panels(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-sidebar-video' in body
    assert 't-sidebar-player' in body
    assert 't-sidebar-panel--speakers' in body
    assert 't-sidebar-panel--bookmarks' in body


def test_no_video_rail_state_machine(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-video-rail' not in body, "v3 floating video rail must be removed"
    assert 'data-state="floating"' not in body
    assert 'data-state="expanded"' not in body
    assert 't-video-show-btn' not in body


def test_speakers_panel_lists_distinct_speakers(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    speakers_block = body.split('t-sidebar-panel--speakers', 1)[1].split('t-sidebar-panel--bookmarks', 1)[0]
    assert 'Speaker 1' in speakers_block
    assert 'Speaker 2' in speakers_block


def test_bookmarks_panel_renders_sorted(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    bookmarks_block = body.split('t-sidebar-panel--bookmarks', 1)[1].split('</aside>', 1)[0]
    assert 'setup question' in bookmarks_block
    assert 'hours' in bookmarks_block
    # First bookmark (14s = 0:14) appears before the second (68s = 1:08)
    pos_a = bookmarks_block.find('setup question')
    pos_b = bookmarks_block.find('hours')
    assert pos_a < pos_b, "bookmarks must render sorted by time ascending"


def test_search_popover_present_no_inline_bars(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-search-popover' in body, "search popover must render"
    assert 't-tb-search-bar' not in body
    assert 't-fr-bar' not in body
```

- [ ] **Step 2: Run tests; expect 7 failures**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py -v
```

Expected: 7 failed (all assertions reference markup that doesn't yet exist).

- [ ] **Step 3: Commit**

```bash
git add tests/test_transcript_view_layout.py
git commit -m "test(transcript): structural assertions for v4 redesign"
```

---

## Task 2: New 2-column grid + empty sidebar shell

**Files:**
- Modify: `templates/transcript.html` (markup only)
- Modify: `styles/input.css` (new rules; old ones still in place)

**Goal:** Wrap the existing `.transcript-body` in a 2-col grid. Add an empty `.t-sidebar` aside on the right. The page should still render fully — old toolbar/player/video rail stay in place. We're just adding the new shell.

- [ ] **Step 1: Edit `templates/transcript.html`**

Find the existing `.t-doc-page` wrapper and replace it. Old block (lines ~103-121):

```html
  {# === ZONE D: document body === #}
  <div class="t-doc-page" id="t-doc-page">
    {% if not is_audio %}
      <aside id="t-video-rail" class="t-video-rail" data-state="floating"
             aria-label="video player">
        <div class="t-video-rail-grab" aria-hidden="true" title="drag">⠿</div>
        <video id="t-player" controls preload="metadata"
               src="{{ media_url }}" playsinline></video>
        <div class="t-video-rail-actions">
          <button type="button" class="t-video-rail-expand"
                  aria-label="expand video to side rail" title="expand">⛶</button>
          <button type="button" class="t-video-rail-close"
                  aria-label="hide video" title="hide">✕</button>
        </div>
      </aside>
    {% endif %}
    <section class="transcript-body" id="t-body">
      {% for seg in data.segments %}{% set seg_idx = loop.index0 %}{% include "partials/transcript_segment.html" %}{% endfor %}
    </section>
  </div>
```

Replace with:

```html
  {# === ZONE D: 2-column grid (doc body + sidebar) === #}
  <div class="t-grid" id="t-grid">
    <section class="t-doc-body transcript-body" id="t-body">
      {% for seg in data.segments %}{% set seg_idx = loop.index0 %}{% include "partials/transcript_segment.html" %}{% endfor %}
    </section>
    <aside class="t-sidebar" id="t-sidebar" aria-label="video and reference panels">
      {# t-sidebar-video, t-sidebar-player, t-sidebar-panel--speakers,
         t-sidebar-panel--bookmarks land here in subsequent tasks. The
         old .t-video-rail and .t-player-bar still render above; this
         empty shell is enough to satisfy the grid + sidebar layout
         tests. #}
    </aside>
  </div>

  {# Legacy .t-video-rail kept temporarily — removed in Task 3. #}
  {% if not is_audio %}
    <aside id="t-video-rail" class="t-video-rail" data-state="floating"
           aria-label="video player">
      <div class="t-video-rail-grab" aria-hidden="true" title="drag">⠿</div>
      <video id="t-player" controls preload="metadata"
             src="{{ media_url }}" playsinline></video>
      <div class="t-video-rail-actions">
        <button type="button" class="t-video-rail-expand"
                aria-label="expand video to side rail" title="expand">⛶</button>
        <button type="button" class="t-video-rail-close"
                aria-label="hide video" title="hide">✕</button>
      </div>
    </aside>
  {% endif %}
```

- [ ] **Step 2: Add new CSS rules in `styles/input.css`**

Find the `.transcript-doc {` block (around line 891) and add this AFTER it inside the same `@layer components`:

```css
    /* --- v4: 2-column grid + sticky right rail --- */
    .t-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 32px;
      align-items: start;
    }
    .t-doc-body {
      max-width: 720px;
      min-width: 0;  /* allow text truncation in flex-grid context */
    }
    .t-sidebar {
      position: sticky;
      top: 76px;
      align-self: start;
      display: flex; flex-direction: column;
      gap: 16px;
      width: 320px;
    }
```

- [ ] **Step 3: Run the layout tests; one test should now pass**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py::test_renders_two_column_grid -v
```

Expected: `test_renders_two_column_grid` PASSES. Other 6 still fail.

- [ ] **Step 4: Run full suite to confirm no regressions**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 583 passed (582 existing + 1 newly green).

- [ ] **Step 5: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 1 — 2-col grid + empty sidebar shell"
```

---

## Task 3: Move `<video>` into sidebar; delete TVideoRail

**Files:**
- Modify: `templates/transcript.html` (markup + JS)
- Modify: `styles/input.css` (add `.t-sidebar-video` rules)

**Goal:** The `<video>` element lives in the sidebar at fixed 280×160. Drag/expand/hide state machine is gone.

- [ ] **Step 1: Add `.t-sidebar-video` block to the sidebar in `templates/transcript.html`**

Inside the `<aside class="t-sidebar">` block created in Task 2, add (replacing the `{# t-sidebar-video... #}` placeholder comment):

```html
      {% if not is_audio %}
        <div class="t-sidebar-video">
          <video id="t-player" controls preload="metadata"
                 src="{{ media_url }}" playsinline></video>
        </div>
      {% else %}
        <div class="t-sidebar-video t-sidebar-video--audio">
          <audio id="t-player" preload="metadata" src="{{ media_url }}"></audio>
        </div>
      {% endif %}
```

- [ ] **Step 2: Delete the legacy `.t-video-rail` markup**

Remove the entire `{% if not is_audio %} <aside id="t-video-rail" …> … </aside> {% endif %}` block that we kept temporarily in Task 2. Also remove the duplicate `<audio id="t-player">` from inside `.t-player-bar` (it's no longer needed — the audio path now lives in the sidebar).

- [ ] **Step 3: Delete the TVideoRail JS module**

Inside the inline `<script>` block in `templates/transcript.html`, find the `const TVideoRail = (function () { … })();` IIFE (search for "TVideoRail") and delete it entirely along with any associated `.t-video-rail-close` / `.t-video-rail-expand` / `t-video-show-btn` event wiring. Keep ONLY the `<video>`/`<audio>` element references — no rail state machine remains.

- [ ] **Step 4: Add `.t-sidebar-video` CSS rules in `styles/input.css`**

Right after the `.t-sidebar` rule from Task 2:

```css
    .t-sidebar-video {
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #000;
      border: 1.5px solid var(--teal);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 6px 24px color-mix(in srgb, black 18%, transparent);
    }
    .t-sidebar-video video,
    .t-sidebar-video audio {
      width: 100%; height: 100%;
      object-fit: contain;
      background: #000;
      display: block;
    }
    .t-sidebar-video--audio {
      aspect-ratio: auto;
      height: 88px;
      display: flex; align-items: center; padding: 0 16px;
    }
    .t-sidebar-video--audio audio { width: 100%; height: 32px; }
```

- [ ] **Step 5: Delete legacy `.t-video-rail*` CSS rules**

Remove every CSS rule that begins with `.t-video-rail` or `.t-video-show-btn` from `styles/input.css` (the block roughly between lines 1145–1224). Also remove the `.t-doc-page.has-expanded-video` rules (just below).

- [ ] **Step 6: Run the layout test**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py::test_no_video_rail_state_machine tests/test_transcript_view_layout.py::test_renders_sidebar_video_player_panels -v
```

Expected: `test_no_video_rail_state_machine` PASSES. `test_renders_sidebar_video_player_panels` still fails (sidebar-player still missing).

- [ ] **Step 7: Run full suite**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 584 passed.

- [ ] **Step 8: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 2 — video into sidebar, delete TVideoRail"
```

---

## Task 4: Sidebar player block (play / scrub / time / speed)

**Files:**
- Modify: `templates/transcript.html` (markup + JS bindings)
- Modify: `styles/input.css`

**Goal:** Move play/scrub/time/speed from the now-old `.t-player-bar` into the sidebar. Same `<video>` is the source of truth.

- [ ] **Step 1: Add `.t-sidebar-player` markup inside the sidebar**

Right after the `.t-sidebar-video` div, before the `</aside>`:

```html
      <div class="t-sidebar-player">
        <button type="button" class="t-pb-play" id="t-pb-play" aria-label="play / pause">▶</button>
        <span class="t-pb-time" id="t-pb-time">0:00 / 0:00</span>
        <input type="range" class="t-pb-scrub" id="t-pb-scrub"
               min="0" max="100" step="0.1" value="0" aria-label="seek">
        <div class="t-pb-speed" role="group" aria-label="playback speed">
          <button type="button" class="t-pb-speed-btn" data-rate="0.5">0.5×</button>
          <button type="button" class="t-pb-speed-btn is-active" data-rate="1">1×</button>
          <button type="button" class="t-pb-speed-btn" data-rate="1.25">1.25×</button>
          <button type="button" class="t-pb-speed-btn" data-rate="1.5">1.5×</button>
          <button type="button" class="t-pb-speed-btn" data-rate="2">2×</button>
        </div>
      </div>
```

- [ ] **Step 2: Delete the legacy `.t-player-bar` block**

Remove the entire `{# === ZONE C: compact sticky player === #}` block from `templates/transcript.html` (lines ~85-100 currently). The IDs (`t-pb-play`, `t-pb-scrub`, `t-pb-time`, `t-pb-speed-btn`, `t-player`) are unchanged — existing JS bindings continue to work.

- [ ] **Step 3: Add `.t-sidebar-player` CSS in `styles/input.css`**

After `.t-sidebar-video--audio`:

```css
    .t-sidebar-player {
      display: grid;
      grid-template-columns: auto 1fr;
      grid-template-areas:
        "play time"
        "scrub scrub"
        "speed speed";
      gap: 8px 12px;
      padding: 12px;
      background: var(--cream);
      border: 1px solid color-mix(in srgb, var(--teal) 14%, transparent);
      border-radius: 8px;
      align-items: center;
    }
    .t-sidebar-player .t-pb-play { grid-area: play; }
    .t-sidebar-player .t-pb-time { grid-area: time; justify-self: end; }
    .t-sidebar-player .t-pb-scrub { grid-area: scrub; width: 100%; }
    .t-sidebar-player .t-pb-speed { grid-area: speed; display: flex; gap: 4px; }
    .t-sidebar-player .t-pb-speed-btn {
      appearance: none; background: transparent;
      border: 1px solid color-mix(in srgb, var(--teal) 22%, transparent);
      padding: 2px 8px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 11px;
      color: var(--teal);
      border-radius: 4px;
      cursor: pointer;
    }
    .t-sidebar-player .t-pb-speed-btn.is-active {
      background: var(--orange); color: white; border-color: var(--orange);
    }
```

- [ ] **Step 4: Delete legacy `.t-player-bar*` CSS**

Remove every rule starting with `.t-player-bar`, `.t-pb-` (only as bare selectors — keep the new `.t-sidebar-player .t-pb-*` rules), `.t-pb-play`, `.t-pb-scrub`, `.t-pb-time`, and `.t-pb-speed`. Bracket: ~lines 1073-1140.

- [ ] **Step 5: Run sidebar tests**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py -v
```

Expected: 4 of 7 passing now (`test_renders_two_column_grid`, `test_no_video_rail_state_machine`, `test_renders_sidebar_video_player_panels` … almost — speakers/bookmarks still TBD).

- [ ] **Step 6: Run full suite**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 584-585 passed.

- [ ] **Step 7: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 3 — sidebar player block"
```

---

## Task 5: Speakers panel

**Files:**
- Modify: `templates/transcript.html`
- Modify: `styles/input.css`

**Goal:** Sidebar panel listing distinct speakers with click-to-rename behavior. Reuses existing `/api/transcribe/<id>/speaker-rename` endpoint via the existing `t-speaker-rename-form` JS handler.

- [ ] **Step 1: Compute distinct speakers in the Jinja template**

Add this Jinja block just BEFORE the `<main>` tag at the very top of `templates/transcript.html` (line 9):

```jinja
{%- set _speakers = [] -%}
{%- for seg in data.segments -%}
  {%- if seg.speaker and seg.speaker not in _speakers -%}
    {%- set _ = _speakers.append(seg.speaker) -%}
  {%- endif -%}
{%- endfor -%}
```

- [ ] **Step 2: Add the speakers panel markup inside `.t-sidebar`**

After the `.t-sidebar-player` div, before `</aside>`:

```html
      <details class="t-sidebar-panel t-sidebar-panel--speakers" open>
        <summary>
          <span class="t-sidebar-panel-h">Speakers</span>
          <span class="t-sidebar-panel-count">{{ _speakers | length }}</span>
        </summary>
        <ul class="t-sidebar-panel-body" data-role="speakers-list">
          {% for spk in _speakers %}
            <li class="t-sidebar-speaker-row" data-speaker="{{ spk }}">
              <span class="t-sidebar-speaker-dot" aria-hidden="true">●</span>
              <button type="button" class="t-sidebar-speaker-name"
                      data-action="rename-speaker" data-speaker="{{ spk }}"
                      title="rename globally">{{ spk }}</button>
            </li>
          {% endfor %}
          {% if not _speakers %}
            <li class="t-sidebar-empty">No speaker labels yet.</li>
          {% endif %}
        </ul>
      </details>
```

- [ ] **Step 3: Add the speakers panel CSS**

```css
    .t-sidebar-panel {
      background: var(--cream);
      border: 1px solid color-mix(in srgb, var(--teal) 14%, transparent);
      border-radius: 8px;
      padding: 0;
    }
    .t-sidebar-panel summary {
      display: flex; align-items: center; justify-content: space-between;
      padding: 10px 14px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 12px;
      text-transform: lowercase;
      color: var(--teal);
      cursor: pointer;
      list-style: none;
    }
    .t-sidebar-panel summary::-webkit-details-marker { display: none; }
    .t-sidebar-panel summary::after {
      content: '▾';
      color: color-mix(in srgb, var(--teal) 60%, transparent);
      transition: transform 120ms ease;
    }
    .t-sidebar-panel:not([open]) summary::after { transform: rotate(-90deg); }
    .t-sidebar-panel-h { font-weight: 600; }
    .t-sidebar-panel-count {
      font-size: 11px;
      color: color-mix(in srgb, var(--teal) 60%, transparent);
      margin-left: auto; padding-right: 12px;
    }
    .t-sidebar-panel-body {
      list-style: none; margin: 0; padding: 4px 14px 12px;
      display: flex; flex-direction: column; gap: 6px;
    }
    .t-sidebar-empty {
      font-size: 11px;
      color: color-mix(in srgb, var(--teal) 50%, transparent);
      font-style: italic;
    }
    .t-sidebar-speaker-row {
      display: flex; align-items: center; gap: 8px;
    }
    .t-sidebar-speaker-dot {
      color: color-mix(in srgb, var(--teal) 30%, transparent);
      font-size: 10px;
    }
    .t-sidebar-speaker-row.is-talking .t-sidebar-speaker-dot {
      color: var(--orange);
    }
    .t-sidebar-speaker-name {
      appearance: none; background: transparent; border: 0;
      padding: 2px 6px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 12px;
      color: var(--teal);
      cursor: pointer;
      border-radius: 4px;
    }
    .t-sidebar-speaker-name:hover {
      background: color-mix(in srgb, var(--orange) 10%, transparent);
      color: var(--orange);
    }
```

- [ ] **Step 4: Wire up rename click handler**

Inside the inline `<script>` block in `templates/transcript.html`, add the click handler near the other rename logic. Search for `'speaker-rename'` or `'rename-speaker'` to locate the existing handler. If a handler already exists for `.t-seg-speaker[data-action="rename-speaker"]`, update its selector to also match `.t-sidebar-speaker-name[data-action="rename-speaker"]`:

```javascript
// Existing handler may match .t-seg-speaker only; widen it:
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action="rename-speaker"]');
  if (!btn) return;
  const oldName = btn.dataset.speaker;
  const newName = window.prompt(`Rename "${oldName}" to:`, oldName);
  if (!newName || newName === oldName) return;
  fetch(`/api/transcribe/${TRANSCRIBE_ID}/speaker-rename`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded',
               ...authHeaders() },
    body: new URLSearchParams({ old: oldName, new: newName }).toString(),
  }).then(r => { if (r.ok) location.reload(); });
});
```

(If the existing handler already does this, don't duplicate it. The sidebar buttons share the `data-action="rename-speaker"` data attribute so a single delegated listener serves both.)

- [ ] **Step 5: Run the speakers panel test**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py::test_speakers_panel_lists_distinct_speakers -v
```

Expected: PASSES.

- [ ] **Step 6: Run full suite**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 585-586 passed.

- [ ] **Step 7: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 4 — speakers sidebar panel"
```

---

## Task 6: Bookmarks panel

**Files:**
- Modify: `templates/transcript.html`
- Modify: `styles/input.css`

**Goal:** Sidebar panel listing all bookmarks sorted by time, with click-to-seek and inline edit. Add button posts to existing `/api/transcribe/<id>/bookmark`.

- [ ] **Step 1: Add the bookmarks panel markup**

After the speakers panel `<details>` in `templates/transcript.html`:

```html
      <details class="t-sidebar-panel t-sidebar-panel--bookmarks" open>
        <summary>
          <span class="t-sidebar-panel-h">Bookmarks</span>
          <span class="t-sidebar-panel-count">{{ data.bookmarks | length }}</span>
        </summary>
        <ul class="t-sidebar-panel-body" data-role="bookmarks-list">
          {% for bm in data.bookmarks %}
            <li class="t-sidebar-bookmark-row" data-bm-id="{{ bm.id }}">
              <button type="button" class="t-sidebar-bookmark-time"
                      data-action="seek" data-time="{{ bm.time }}"
                      title="seek to {{ '%d:%02d' | format(bm.time | int // 60, bm.time | int % 60) }}">
                {{ '%d:%02d' | format(bm.time | int // 60, bm.time | int % 60) }}
              </button>
              <span class="t-sidebar-bookmark-note"
                    contenteditable="plaintext-only" spellcheck="false"
                    data-action="edit-bookmark" data-bm-id="{{ bm.id }}">{{ bm.note }}</span>
              <button type="button" class="t-sidebar-bookmark-delete"
                      data-action="delete-bookmark" data-bm-id="{{ bm.id }}"
                      aria-label="delete bookmark">×</button>
            </li>
          {% endfor %}
          {% if not data.bookmarks %}
            <li class="t-sidebar-empty">No bookmarks yet.</li>
          {% endif %}
        </ul>
        <button type="button" class="t-sidebar-bookmark-add"
                data-action="add-bookmark"
                title="bookmark current playback time">+ add bookmark</button>
      </details>
```

- [ ] **Step 2: Add bookmarks panel CSS**

```css
    .t-sidebar-bookmark-row {
      display: grid;
      grid-template-columns: 56px 1fr auto;
      gap: 8px;
      align-items: baseline;
      padding: 4px 0;
      border-bottom: 1px dashed color-mix(in srgb, var(--teal) 12%, transparent);
    }
    .t-sidebar-bookmark-row:last-child { border-bottom: 0; }
    .t-sidebar-bookmark-time {
      appearance: none; background: transparent; border: 0;
      padding: 2px 4px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 11px;
      color: var(--orange);
      cursor: pointer;
      border-radius: 4px;
      text-align: left;
    }
    .t-sidebar-bookmark-time:hover {
      background: color-mix(in srgb, var(--orange) 10%, transparent);
    }
    .t-sidebar-bookmark-note {
      font-size: 12px;
      color: var(--ink);
      outline: none;
      border-radius: 4px;
      padding: 2px 4px;
      min-width: 0;
    }
    .t-sidebar-bookmark-note:focus-visible {
      background: color-mix(in srgb, var(--orange) 8%, transparent);
      box-shadow: inset 0 -2px 0 var(--orange);
    }
    .t-sidebar-bookmark-delete {
      appearance: none; background: transparent;
      border: 1px solid transparent;
      width: 22px; height: 22px;
      color: color-mix(in srgb, var(--teal) 60%, transparent);
      cursor: pointer;
      border-radius: 4px;
    }
    .t-sidebar-bookmark-delete:hover {
      color: var(--orange);
      border-color: color-mix(in srgb, var(--orange) 30%, transparent);
    }
    .t-sidebar-bookmark-add {
      appearance: none; background: transparent;
      border: 1px dashed color-mix(in srgb, var(--teal) 25%, transparent);
      padding: 6px 10px; margin: 6px 14px 12px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 11px;
      color: var(--teal);
      cursor: pointer;
      border-radius: 4px;
      width: calc(100% - 28px);
      text-align: center;
    }
    .t-sidebar-bookmark-add:hover {
      background: color-mix(in srgb, var(--orange) 8%, transparent);
      border-color: var(--orange);
      color: var(--orange);
    }
```

- [ ] **Step 3: Wire up bookmark add/seek/edit/delete handlers**

In the inline `<script>` block, add (or extend the existing delegated click handler):

```javascript
// Bookmark add
document.querySelector('[data-action="add-bookmark"]')?.addEventListener('click', () => {
  const player = document.getElementById('t-player');
  const t = player ? player.currentTime : 0;
  fetch(`/api/transcribe/${TRANSCRIBE_ID}/bookmark`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...authHeaders() },
    body: new URLSearchParams({ time: String(t), note: '' }).toString(),
  }).then(r => { if (r.ok) location.reload(); });
});

// Bookmark seek (data-action="seek" with data-time)
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.t-sidebar-bookmark-time[data-action="seek"]');
  if (!btn) return;
  const t = parseFloat(btn.dataset.time || '0');
  const player = document.getElementById('t-player');
  if (player) { player.currentTime = t; player.pause(); }
});

// Bookmark inline-note edit (debounced PATCH on blur)
document.addEventListener('blur', (e) => {
  const note = e.target.closest('.t-sidebar-bookmark-note[data-action="edit-bookmark"]');
  if (!note) return;
  const bmId = note.dataset.bmId;
  const text = note.textContent.trim();
  fetch(`/api/transcribe/${TRANSCRIBE_ID}/bookmark/${bmId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...authHeaders() },
    body: new URLSearchParams({ note: text }).toString(),
  });
}, true);  // capture phase — blur doesn't bubble

// Bookmark delete
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action="delete-bookmark"]');
  if (!btn) return;
  const bmId = btn.dataset.bmId;
  fetch(`/api/transcribe/${TRANSCRIBE_ID}/bookmark/${bmId}`, {
    method: 'DELETE', headers: { ...authHeaders() },
  }).then(r => { if (r.ok) btn.closest('.t-sidebar-bookmark-row')?.remove(); });
});
```

`authHeaders()` is the existing helper in the inline JS that adds the `Authorization: Bearer <TROVE_TOKEN>` header when present. Reuse it; do NOT redefine.

- [ ] **Step 4: Run the bookmarks panel test**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py::test_bookmarks_panel_renders_sorted -v
```

Expected: PASSES.

- [ ] **Step 5: Run full suite**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 586-587 passed.

- [ ] **Step 6: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 5 — bookmarks sidebar panel"
```

---

## Task 7: Single topbar — collapse header + toolbar

**Files:**
- Modify: `templates/transcript.html`
- Modify: `styles/input.css`

**Goal:** Replace `.t-doc-header` (with `.t-doc-header-row1`, `.t-doc-meta`) AND the non-search portion of `.t-doc-toolbar` with a single `.t-topbar`. The search-bar / fr-bar slabs become a popover in Task 8.

- [ ] **Step 1: Replace header + toolbar markup**

Replace the existing `<header class="t-doc-header">…</header>` AND the `<div class="t-doc-toolbar">…</div>` blocks (lines ~12-83 currently) with:

```html
  {# === ZONE A+B: single sticky topbar === #}
  <header class="t-topbar" id="t-topbar">
    <a class="t-doc-mark" href="/">trove<span class="period">.</span></a>
    <span class="t-doc-crumb">›</span>
    <h1 class="t-doc-title" id="t-doc-title"
        contenteditable="plaintext-only" spellcheck="false"
        data-current="{{ _eff_title }}">{{ _eff_title }}</h1>
    <p class="t-topbar-meta">
      <span>{% if _dur_h %}{{ '%d:%02d:%02d' | format(_dur_h, _dur_m, _dur_s) }}{% else %}{{ '%d:%02d' | format(_dur_m, _dur_s) }}{% endif %}</span>
      <span class="sep">·</span> <span>{{ (data.language or "—") | upper }}</span>
      {% if was_edited %}<span class="sep">·</span> <span class="t-edited-badge" id="t-edited-badge">edited</span>{% endif %}
    </p>
    <span class="t-doc-saving" id="t-doc-saving" data-state="idle"
          aria-live="polite" title="saving status">
      <span class="t-doc-saving-dot"></span><span class="t-doc-saving-text">✓ saved</span>
    </span>
    <div class="t-topbar-actions">
      <button type="button" class="t-tb-btn" id="t-tb-undo" title="undo (⌘Z)">↶</button>
      <button type="button" class="t-tb-btn" id="t-tb-redo" title="redo (⌘⇧Z)">↷</button>
      <button type="button" class="t-tb-btn" id="t-tb-search-toggle"
              title="find / replace (⌘F)" aria-controls="t-search-popover">⌕</button>
      <details class="t-tb-export">
        <summary class="t-tb-btn" title="export">⤓</summary>
        <div class="t-tb-export-menu">
          {% set _eq = signed_query(tj.id, SCOPE_TRANSCRIPT_EXPORT) %}
          {% set _q = ('?' ~ _eq) if _eq else '' %}
          <a href="/api/transcribe/{{ tj.id }}/export.txt{{ _q }}">.txt</a>
          <a href="/api/transcribe/{{ tj.id }}/export.srt{{ _q }}">.srt</a>
          <a href="/api/transcribe/{{ tj.id }}/export.vtt{{ _q }}">.vtt</a>
        </div>
      </details>
      <details class="t-tb-more">
        <summary class="t-tb-btn" title="more">⋯</summary>
        <div class="t-tb-more-menu">
          <label class="t-tb-toggle"><input type="checkbox" id="t-tb-follow" checked>follow-along</label>
          <label class="t-tb-toggle"><input type="checkbox" id="t-tb-show-speakers" checked>show speakers</label>
          <label class="t-tb-toggle"><input type="checkbox" id="t-tb-show-times" checked>show times</label>
          <button type="button" class="t-tb-btn" id="t-help-btn">how to use</button>
        </div>
      </details>
    </div>
  </header>
```

- [ ] **Step 2: Add `.t-topbar` CSS in `styles/input.css`**

After the `.transcript-doc {` block, BEFORE the legacy `.t-doc-header` rules (which we'll delete in step 4):

```css
    /* --- v4: single sticky topbar --- */
    .t-topbar {
      position: sticky; top: 0; z-index: 20;
      display: flex; align-items: center; gap: 12px;
      padding: 12px 0;
      background: var(--cream);
      border-bottom: 1px solid color-mix(in srgb, var(--teal) 14%, transparent);
    }
    .t-topbar .t-doc-mark { flex: 0 0 auto; }
    .t-topbar .t-doc-crumb {
      flex: 0 0 auto;
      color: color-mix(in srgb, var(--teal) 50%, transparent);
    }
    .t-topbar .t-doc-title {
      flex: 1 1 auto;
      margin: 0;
      font-family: 'Source Serif 4', 'Source Serif Pro', Georgia, serif;
      font-size: 18px;
      font-weight: 600;
      color: var(--ink);
      line-height: 1.2;
      outline: none;
      border-radius: 4px;
      padding: 2px 4px;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .t-topbar .t-doc-title:focus-visible {
      background: color-mix(in srgb, var(--orange) 8%, transparent);
      box-shadow: inset 0 -2px 0 var(--orange);
      white-space: normal;
    }
    .t-topbar-meta {
      flex: 0 0 auto;
      margin: 0;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 11px;
      color: color-mix(in srgb, var(--teal) 70%, transparent);
      display: flex; gap: 6px;
    }
    .t-topbar-meta .sep { opacity: 0.6; }
    .t-topbar .t-doc-saving { flex: 0 0 auto; }
    .t-topbar-actions {
      flex: 0 0 auto;
      display: flex; align-items: center; gap: 4px;
    }
    .t-tb-more { position: relative; }
    .t-tb-more summary { list-style: none; cursor: pointer; }
    .t-tb-more summary::-webkit-details-marker { display: none; }
    .t-tb-more-menu {
      position: absolute; right: 0; top: 100%; margin-top: 4px;
      display: flex; flex-direction: column; gap: 6px;
      background: var(--cream);
      border: 1px solid color-mix(in srgb, var(--teal) 25%, transparent);
      border-radius: 4px;
      padding: 8px 12px;
      min-width: 180px;
      z-index: 30;
    }
```

- [ ] **Step 3: Remove the old `.t-doc-header` and `.t-doc-toolbar` CSS rules**

Delete every rule whose selector starts with `.t-doc-header`, `.t-doc-header-row1`, `.t-doc-meta` (the meta paragraph styles — the new `.t-topbar-meta` replaces them), `.t-doc-toolbar`, `.t-tb-group`, `.t-tb-toggles`, `.t-tb-right`. Roughly lines 902-1071 minus the new `.t-topbar*` rules added in step 2. Keep `.t-tb-btn`, `.t-tb-toggle`, `.t-tb-export*` rules — they're reused inside the topbar.

- [ ] **Step 4: Run the topbar test**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py::test_renders_single_topbar -v
```

Expected: PASSES.

- [ ] **Step 5: Run full suite — note any regressions in extras endpoints tests**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

If `tests/test_transcript_extras_endpoints.py` fails, leave them failing for now — Task 11 fixes them. If anything ELSE fails, investigate before committing.

- [ ] **Step 6: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 6 — single sticky topbar"
```

---

## Task 8: Search popover (replaces inline search-bar + fr-bar)

**Files:**
- Modify: `templates/transcript.html`
- Modify: `styles/input.css`

**Goal:** Single popover under the topbar's ⌕ button with two tabs: "Find" and "Find + replace".

- [ ] **Step 1: Add the popover markup**

Just after the closing `</header>` of `.t-topbar`:

```html
  <div class="t-search-popover" id="t-search-popover" hidden role="dialog" aria-label="search">
    <div class="t-search-tabs" role="tablist">
      <button type="button" class="t-search-tab is-active" data-tab="find" role="tab">find</button>
      <button type="button" class="t-search-tab" data-tab="replace" role="tab">find + replace</button>
    </div>
    <div class="t-search-pane t-search-pane--find" data-pane="find">
      <input id="t-search" type="search" placeholder="search transcript…" autocomplete="off">
      <div class="t-search-pane-row">
        <button type="button" id="t-prev" aria-label="previous">↑</button>
        <button type="button" id="t-next" aria-label="next">↓</button>
        <span id="t-search-count" aria-live="polite"></span>
      </div>
    </div>
    <div class="t-search-pane t-search-pane--replace" data-pane="replace" hidden>
      <input type="text" id="t-fr-find" placeholder="find…" autocomplete="off">
      <input type="text" id="t-fr-replace" placeholder="replace with…" autocomplete="off">
      <div class="t-search-pane-row">
        <label><input type="checkbox" id="t-fr-case"> match case</label>
        <button type="button" id="t-fr-go">replace all</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add popover CSS**

```css
    .t-search-popover {
      position: fixed; top: 60px;
      right: max(24px, calc((100vw - 1180px) / 2 + 24px));
      width: 360px;
      background: var(--cream);
      border: 1px solid color-mix(in srgb, var(--teal) 25%, transparent);
      border-radius: 8px;
      box-shadow: 0 6px 24px color-mix(in srgb, black 18%, transparent);
      padding: 12px;
      z-index: 30;
    }
    .t-search-popover[hidden] { display: none; }
    .t-search-tabs {
      display: flex; gap: 4px; margin-bottom: 8px;
    }
    .t-search-tab {
      appearance: none; background: transparent;
      border: 1px solid transparent;
      padding: 4px 10px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 11px;
      color: var(--teal);
      border-radius: 4px;
      cursor: pointer;
    }
    .t-search-tab.is-active {
      background: color-mix(in srgb, var(--orange) 12%, transparent);
      color: var(--orange);
    }
    .t-search-pane {
      display: flex; flex-direction: column; gap: 8px;
    }
    .t-search-pane[hidden] { display: none; }
    .t-search-pane input[type="search"],
    .t-search-pane input[type="text"] {
      padding: 6px 10px;
      background: color-mix(in srgb, var(--cream) 70%, white);
      border: 1px solid color-mix(in srgb, var(--teal) 22%, transparent);
      border-radius: 4px;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 12px;
      color: var(--ink);
      outline: none;
    }
    .t-search-pane-row {
      display: flex; gap: 6px; align-items: center;
      font-family: 'IBM Plex Mono', ui-monospace, monospace;
      font-size: 11px;
      color: var(--teal);
    }
    .t-search-pane-row button {
      appearance: none; background: transparent;
      border: 1px solid color-mix(in srgb, var(--teal) 22%, transparent);
      padding: 4px 10px;
      font-family: inherit; font-size: 11px;
      color: var(--teal);
      border-radius: 4px;
      cursor: pointer;
    }
    .t-search-pane-row button:hover {
      background: color-mix(in srgb, var(--orange) 8%, transparent);
      color: var(--orange);
    }
```

- [ ] **Step 3: Wire up open/close + tab switching JS**

In the inline `<script>` block:

```javascript
const SEARCH_POPOVER = document.getElementById('t-search-popover');
const SEARCH_TOGGLE = document.getElementById('t-tb-search-toggle');

function openSearch(tab = 'find') {
  SEARCH_POPOVER.hidden = false;
  SEARCH_POPOVER.querySelectorAll('.t-search-tab').forEach(t => {
    t.classList.toggle('is-active', t.dataset.tab === tab);
  });
  SEARCH_POPOVER.querySelectorAll('.t-search-pane').forEach(p => {
    p.hidden = p.dataset.pane !== tab;
  });
  const focusInput = SEARCH_POPOVER.querySelector(
    tab === 'replace' ? '#t-fr-find' : '#t-search');
  focusInput?.focus();
}
function closeSearch() { SEARCH_POPOVER.hidden = true; }

SEARCH_TOGGLE?.addEventListener('click', () => {
  if (SEARCH_POPOVER.hidden) openSearch('find'); else closeSearch();
});

SEARCH_POPOVER.querySelectorAll('.t-search-tab').forEach(tab => {
  tab.addEventListener('click', () => openSearch(tab.dataset.tab));
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !SEARCH_POPOVER.hidden) {
    closeSearch();
    e.preventDefault();
  }
  // Cmd+F / Ctrl+F
  if ((e.metaKey || e.ctrlKey) && e.key === 'f' && !e.shiftKey) {
    e.preventDefault();
    openSearch('find');
  }
  // Cmd+Shift+F
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 'F' || e.key === 'f')) {
    e.preventDefault();
    openSearch('replace');
  }
});

// Click outside closes
document.addEventListener('click', (e) => {
  if (SEARCH_POPOVER.hidden) return;
  if (e.target.closest('#t-search-popover')) return;
  if (e.target.closest('#t-tb-search-toggle')) return;
  closeSearch();
});
```

The existing find / replace logic (events on `#t-search`, `#t-prev`, `#t-next`, `#t-fr-find`, `#t-fr-replace`, `#t-fr-go`, `#t-fr-case`) keeps working — those IDs are unchanged.

- [ ] **Step 4: Run the popover test**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_view_layout.py::test_search_popover_present_no_inline_bars -v
```

Expected: PASSES.

- [ ] **Step 5: Commit**

```bash
git add templates/transcript.html styles/input.css
git commit -m "feat(transcript): v4 step 7 — search popover"
```

---

## Task 9: Active-state restyle (kill the orange line, add talking dot)

**Files:**
- Modify: `styles/input.css`
- Modify: `templates/transcript.html` (inline JS for talking-dot sync)

**Goal:** Replace the buggy 2 px orange focus-within shadow with a teal one that doubles as the playback marker. Replace the orange-block active-word fill with a 2 px underline. Add `is-talking` class sync to the speakers panel rows.

- [ ] **Step 1: Update active-segment + active-word styles in `styles/input.css`**

Find the current `.t-seg-body:focus-within` rule (search for "focus-within" inside the t-seg block) and replace:

```css
    /* OLD — DELETE */
    .t-seg-body:focus-within {
      box-shadow: inset 2px 0 0 var(--orange);
    }
```

with:

```css
    /* v4: teal left rail for cursor focus AND active playback. Both
       use the same indicator so they don't compete. */
    .t-seg-body:focus-within,
    .t-seg.is-active .t-seg-body {
      box-shadow: inset 2px 0 0 var(--teal);
    }
```

Find the `.t-word.is-active` rule (search for ".t-word.is-active" or ".word.is-active") and replace any background-fill style with:

```css
    .t-word.is-active,
    .word.is-active {
      background: transparent;
      text-decoration: underline;
      text-decoration-color: var(--orange);
      text-decoration-thickness: 2px;
      text-underline-offset: 3px;
    }
```

(If the existing rule uses `.word.is-active` only, keep `.word.is-active` — match the existing class name in the partials.)

- [ ] **Step 2: Add `is-talking` sync logic in inline JS**

In the existing `onTimeUpdate` handler (search for "currentTime" near the player bindings), add:

```javascript
// Sync .is-talking on speakers-panel rows to the active segment's speaker.
const activeSeg = /* existing variable from the timeupdate handler */;
const activeSpeaker = activeSeg?.dataset.speaker || null;
document.querySelectorAll('.t-sidebar-speaker-row').forEach(row => {
  row.classList.toggle('is-talking',
    row.dataset.speaker === activeSpeaker);
});
```

Place this immediately after the existing line that sets `is-active` on the new segment, inside the same handler — don't create a new listener.

- [ ] **Step 3: Manual smoke + commit**

Rebuild Tailwind and start the server:

```bash
/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss -i styles/input.css -o static/app.css --minify
PORT=8899 HOST=127.0.0.1 TROVE_DIARIZATION=on \
  /Users/kaivan108icloud.com/Downloads/trove/venv/bin/python app.py &
```

Open `http://127.0.0.1:8899/transcript/<any-done-tj-id>` and verify:
- Click into a paragraph: thin teal left rail appears, no orange.
- Press play: same teal rail follows the active segment; no orange block on the active word, just an orange underline.
- Speakers panel: the currently-talking speaker's `●` dot is filled orange; others are dim.

- [ ] **Step 4: Run full suite to confirm no test broke**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add styles/input.css templates/transcript.html static/app.css
git commit -m "feat(transcript): v4 step 8 — active-state restyle (teal rail, underline word, talking dot)"
```

---

## Task 10: Final cleanup — delete obsolete CSS + JS

**Files:**
- Modify: `styles/input.css`
- Modify: `templates/transcript.html`

**Goal:** Remove every CSS rule and JS hook that targets a class no longer in the markup. Keep the file tight; don't leave dead code.

- [ ] **Step 1: Sweep `styles/input.css`**

Search for and DELETE any remaining rule beginning with:
- `.t-doc-header`, `.t-doc-header-row1`, `.t-doc-meta` (the original meta paragraph rules — `.t-topbar-meta` is the v4 replacement)
- `.t-doc-toolbar`, `.t-tb-group`, `.t-tb-toggles`, `.t-tb-right`, `.t-tb-search-bar`, `.t-tb-fr-bar`
- `.t-player-bar`, and any bare `.t-pb-*` rule that's not nested under `.t-sidebar-player`
- `.t-video-rail`, `.t-video-rail-grab`, `.t-video-rail-actions`, `.t-video-rail-expand`, `.t-video-rail-close`, `.t-video-show-btn`
- `.t-doc-page` and `.t-doc-page.has-expanded-video`

Keep the new v4 selectors: `.t-topbar`, `.t-topbar-meta`, `.t-topbar-actions`, `.t-grid`, `.t-doc-body`, `.t-sidebar`, `.t-sidebar-video`, `.t-sidebar-video--audio`, `.t-sidebar-player`, `.t-sidebar-panel`, `.t-sidebar-panel--*`, `.t-sidebar-speaker-*`, `.t-sidebar-bookmark-*`, `.t-search-popover`, `.t-search-tab*`, `.t-search-pane*`, `.t-tb-more*`.

Also keep shared rules: `.t-tb-btn`, `.t-tb-toggle`, `.t-tb-export*`, `.t-context-menu`, `.t-toast-stack`, `.t-jump-current`, `.modal*`, `.t-seg*`, `.word*`, `.help-section*`, `.t-edited-badge`, `.t-doc-mark`, `.t-doc-crumb`, `.t-doc-title`, `.t-doc-saving*`.

- [ ] **Step 2: Sweep `templates/transcript.html` inline `<script>`**

Search for and remove:
- Any reference to `.t-video-rail`, `t-video-show-btn`, `data-state` (in the video context — NOT the global `data-state` on cards), `TVideoRail`
- Any reference to `.t-tb-search-bar`, `.t-tb-fr-bar` — those slabs no longer exist; the popover has the same input IDs so individual handlers stay
- The `t-tb-search` and `t-tb-find-replace` button click handlers — replaced by the search popover toggle (`t-tb-search-toggle`)

- [ ] **Step 3: Tailwind rebuild**

```bash
/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss \
  -i styles/input.css -o static/app.css --minify
```

- [ ] **Step 4: Run full suite**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 587 passed (582 existing + 7 layout tests; subtract any that test removed legacy selectors and add to Task 11).

- [ ] **Step 5: Commit**

```bash
git add styles/input.css templates/transcript.html static/app.css
git commit -m "refactor(transcript): v4 step 9 — delete obsolete CSS and JS"
```

---

## Task 11: Update existing tests with new selectors

**Files:**
- Modify: `tests/test_transcript_extras_endpoints.py`
- (Possibly) `tests/test_transcribe_endpoints.py`

**Goal:** Any existing test that scrapes rendered HTML for `.t-doc-toolbar`, `.t-tb-search-bar`, `.t-tb-fr-bar`, `.t-player-bar`, or `.t-video-rail` is asserting on layout that no longer exists. Update those selectors or replace with v4-equivalent assertions.

- [ ] **Step 1: Identify failing tests**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_transcript_extras_endpoints.py tests/test_transcribe_endpoints.py -v 2>&1 | grep -E "^FAILED|^PASSED" | head
```

If everything passes, this task is a no-op — skip to step 4.

- [ ] **Step 2: For each failure, update the selector**

Common pattern: a test asserts `'t-doc-toolbar' in body`. Replace with `'t-topbar' in body`. A test asserting `'t-video-rail' in body` for video clips should now assert `'t-sidebar-video' in body`. A test asserting `'t-tb-search-bar' in body` should assert `'t-search-popover' in body`.

- [ ] **Step 3: Re-run suite**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
```

Expected: 587 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(transcript): update selectors for v4 layout"
```

---

## Task 12: Final QA + push

**Goal:** Manual smoke + push the branch.

- [ ] **Step 1: Tailwind build sanity**

```bash
/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss \
  -i styles/input.css -o static/app.css --minify
ls -la static/app.css
```

Expected: file exists, < 200 KB, no errors.

- [ ] **Step 2: Server smoke**

```bash
PORT=8899 HOST=127.0.0.1 TROVE_DIARIZATION=on \
  /Users/kaivan108icloud.com/Downloads/trove/venv/bin/python app.py &
sleep 2
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8899/
```

Expected: HTTP 200.

- [ ] **Step 3: Manual QA checklist**

Open `http://127.0.0.1:8899/transcript/<any-done-tj-id>` in a browser and verify each:

- [ ] **Single sticky bar.** Scrolling the document — only the topbar sticks at the top. No second/third row appears.
- [ ] **Sidebar visible.** Video + player + speakers panel + bookmarks panel all render on the right.
- [ ] **Sidebar sticks.** Sidebar follows the top of the viewport (top:76 px) when scrolled past.
- [ ] **No floating video.** No drag handle, no expand/hide buttons. Native browser PiP / fullscreen still work via the `<video>` controls.
- [ ] **Active state.** Press play. Active word underlines in orange; active segment shows a teal left rail; the talking speaker's `●` dot fills orange.
- [ ] **Search popover.** Click ⌕. Popover opens under the icon. Type in find tab → matches highlighted. Tab to "find + replace" → both inputs work. Press Escape → closes.
- [ ] **Speakers panel.** Click a speaker name → rename prompt → submit → page reloads with new label everywhere.
- [ ] **Bookmarks panel.** Click [+ add] at some playhead time → new bookmark row appears. Click time pill → seeks. Edit note text → blurs and saves. Click × → row removes.
- [ ] **Z-index hygiene.** Open the export ⤓ dropdown — it sits over the document but under any modal. Open the help ⋯ menu. Open a modal (e.g. consent / help) — covers everything. Save indicator toast shows above all of the above.
- [ ] **Audio-only file.** Open an audio transcript (`.mp3`) — sidebar shows the audio cover with the inline audio scrubber, no broken `<video>` element.

- [ ] **Step 4: Push**

```bash
git push origin transcribe
```

- [ ] **Step 5: Mark plan complete**

Done. Hand the branch to the user for review.

---

## Out of scope (explicitly deferred)

- Mobile / responsive layout (user confirmed: desktop-only).
- Per-speaker color rotation (Alice = blue, Bob = green) — v4.1.
- Waveform visualization in the player (Riverside-style).
- Word-timestamp DTW alignment (would require swapping pywhispercpp for faster-whisper).
- Diarization quality tuning beyond current Resemblyzer + silero-vad.

---

## Risks + mitigations

- **Inline `<script>` block grows large.** Search popover + speakers + bookmarks JS adds ~150 LOC. Strict CSP forbids splitting into a second tag. Mitigation: keep the existing single block; if it exceeds ~1500 LOC, propose extracting into a separate `static/transcript-app.js` with the appropriate CSP `script-src` update — but that's out of scope for this plan.
- **Existing test selectors break.** Task 11 fixes them. If new failures show up at any prior task, leave them red and proceed — Task 11 is the catch-all.
- **CSS regressions on adjacent pages.** Some shared selectors (`.t-tb-btn`) are reused on the setup page. Don't delete those. Task 10 explicitly preserves them.
- **CSP nonce.** All `<script>` tags must reference the per-request nonce; we never add new tags so this is automatic.
