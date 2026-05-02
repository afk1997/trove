# Trove · transcript page v3.1 — bug fixes + floating video + diarization + help

> **Branch:** `transcribe`
> **Worktree:** `/Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe`
> **Status:** Plan ready (awaiting ExitPlanMode + user approval).

## Context

Manual QA on the v3 transcript page surfaced two visual bugs and two missing capabilities the user wants in this iteration:

1. **Orange vertical line bleeds into the active paragraph** when the cursor lands inside it. Root cause: `styles/input.css:1233` — `.t-seg-body:focus-within { box-shadow: inset 2px 0 0 var(--orange); }` — a 2px left inset shadow that visually reads as a thick orange border running the full paragraph height.

2. **Sticky toolbar / player bar bleed-through** when the document scrolls. Root cause: `styles/input.css:1068` — `.t-player-bar { background: color-mix(in srgb, var(--cream) 85%, white); }` — the 85% alpha means content scrolls VISIBLY through the sticky bar.

3. **No real diarization.** Whisper alone cannot identify who is speaking; segments split on natural pauses, not speaker changes. Manual labeling is the current workflow but the user wants automatic speaker detection. **Constraint locked:** no HuggingFace login, no auth tokens, no cloud APIs. WhisperX/pyannote are out (both gated). Path: **Resemblyzer + silero-vad** — fully MIT/BSD-licensed, models bundled, ~150MB pip deps, no external auth.

4. **Video player is too restrictive.** Currently a small toggle reveals a panel; the user wants a **floating window on the left** (PiP-style), with three states: floating / hidden / expanded-to-fixed-left-pane. User can close (`✕`), re-open via a "show video" button, and toggle expand to take a fixed-width column with the document reflowing to the right.

5. **No proper help/instructions.** Current `?` modal lists keyboard shortcuts only. The user wants a richer help panel covering all controls (editing, seeking, selection toolbar, right-click, speaker labels, bookmarks, find/replace, video modes, the full spec).

---

## Approach (high level)

Four work areas. Each lands as its own commit so the user can stage them independently.

```
A.  Bug fixes (CSS only, ~10 lines)        → 1 commit, 5-min change
B.  Floating video window (left rail PiP)  → 1 commit, ~120 lines JS+CSS+template
C.  Diarization pipeline (resemblyzer)     → 1 commit, new module + integration, ~300 lines
D.  Comprehensive help panel               → 1 commit, ~80 lines markup + CSS
```

All four can ship together in the same PR; splitting commits keeps the diff readable.

---

## Section A · Bug fixes (immediate)

### A1 · Kill the orange-line-on-focus

`styles/input.css:1233`. Replace:

```css
.t-seg-body:focus-within { box-shadow: inset 2px 0 0 var(--orange); }
```

with:

```css
.t-seg-body:focus-within { box-shadow: inset 0 -1px 0 color-mix(in srgb, var(--orange) 35%, transparent); }
```

The new style:
- Removes the left-side inset (no more vertical orange bar).
- Adds a faint bottom edge to indicate "cursor is here" without dominating the paragraph.
- 35% alpha keeps it subtle (was 100% solid orange).

If the user prefers no indicator at all, drop the rule entirely; the active-segment background wash already conveys focus.

### A2 · Fix the sticky-bar bleed-through

`styles/input.css:1068`. Replace:

```css
background: color-mix(in srgb, var(--cream) 85%, white);
```

with:

```css
background: var(--cream);
```

Solid background occludes the document scrolling beneath. While here, audit the other sticky zones:

- `.t-doc-header` (input.css:892–896) — already `background: var(--cream)`, OK.
- `.t-doc-toolbar` (input.css:962–967) — already `background: var(--cream)`, OK.
- `.t-player-bar` (input.css:1068) — the only offender.

Confirm z-index ordering (header 30, toolbar 28, player 27) — header on top, then toolbar, then player. That ordering is correct; the problem was purely the alpha. No z-index changes needed.

---

## Section B · Floating video window (left rail, PiP-style)

### States

| State | Description | How to enter |
|---|---|---|
| **floating** (default for video transcripts) | Small draggable window pinned to bottom-left of viewport, ~280×160px, video + small play overlay, ✕ close button, ⛶ expand button, no chrome beyond that. | Default on page load for video. |
| **hidden** | No video visible. A small `▸ show video` button parks at the top of the toolbar. | User clicked ✕ on the floating window OR `▸ show video` on a previously-hidden state. |
| **expanded** | Fixed left column ~440px wide; video fills it; document column reflows to the right of it (max-width drops to ~620px). | User clicked ⛶ on the floating window. |

For audio-only transcripts: there's no video frame, so this all collapses to "no video panel; the audio scrubber lives in the sticky player bar at the top" — same as today. Only video transcripts get the floating-rail treatment.

### Layout mechanics

- **floating:** `position: fixed; bottom: 24px; left: 24px; z-index: 40;` — above the document, below modals (modals are 1000+). User can drag via a small grab handle in the top-left corner of the window.
- **hidden:** `display: none` on the floating window. The `▸ show video` button in the toolbar is rendered conditionally on `videoState === 'hidden'`.
- **expanded:** the floating window's `position` switches to `absolute` inside a left rail, and the document grid swaps from `grid-template-columns: 1fr` to `grid-template-columns: 440px 1fr` with a 32px gap. Document body's `max-width: 720px` drops to `max-width: 620px` to keep line length comfortable.

### Persistence

State persists per-transcript in `localStorage`:

```js
localStorage.setItem(`trove.video.${transcribeId}`, JSON.stringify({
  state: 'floating' | 'hidden' | 'expanded',
  // floating only:
  pos: {x: 24, y: 24}
}));
```

On page load, restore the last state. If never set, default `floating` for video / unused for audio.

### Markup

The single `<video>` element (currently in the sticky player bar) moves out into a new container:

```html
<aside id="t-video-rail" class="t-video-rail" data-state="floating">
  <div class="t-video-rail-grab" aria-hidden="true">⠿</div>
  <video id="t-player-video" controls preload="metadata" src="..."></video>
  <div class="t-video-rail-actions">
    <button class="t-video-rail-expand" aria-label="Expand video">⛶</button>
    <button class="t-video-rail-close" aria-label="Hide video">✕</button>
  </div>
</aside>
```

The sticky player bar at the top stays — it remains the audio scrubber + speed pills + time display (small, always-on, doesn't depend on video state). When video is in floating/expanded mode, the player bar's transport (play/pause/scrub) controls the same `<video>` element via the existing JS bindings.

### CSS

New rules in `styles/input.css` `@layer components` (top scope, NOT inside the mobile media query — past pitfall):

```css
.t-video-rail {
  background: #000;
  border: 1.5px solid var(--teal);
  box-shadow: var(--shadow-card);
  z-index: 40;
}
.t-video-rail[data-state="floating"] {
  position: fixed; bottom: 24px; left: 24px;
  width: 280px; height: 160px;
  cursor: grab;
}
.t-video-rail[data-state="hidden"] { display: none; }
.t-video-rail[data-state="expanded"] {
  position: relative;
  width: 100%; height: auto; max-height: 70vh;
  cursor: default;
}
.t-video-rail video {
  width: 100%; height: 100%;
  object-fit: contain;
  background: #000;
}
.t-video-rail-grab { /* tiny corner handle for dragging */ }
.t-video-rail-actions { position: absolute; top: 6px; right: 6px; display: flex; gap: 4px; }
.t-video-rail-expand,
.t-video-rail-close {
  background: rgba(0,0,0,0.55); color: var(--cream);
  border: 1px solid rgba(255,255,255,0.25);
  width: 28px; height: 28px;
  cursor: pointer;
  border-radius: 4px;
}
.t-video-rail-expand:hover,
.t-video-rail-close:hover { background: var(--orange); }

/* Document grid reflows when video is expanded */
.t-doc-page {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
  transition: grid-template-columns 200ms ease-out;
}
.t-doc-page.has-expanded-video {
  grid-template-columns: 440px 1fr;
  gap: 32px;
}
.t-doc-page.has-expanded-video .t-doc-body { max-width: 620px; }
.t-doc-page.has-expanded-video .t-video-rail { grid-column: 1; position: sticky; top: 120px; }
```

Mobile (≤768px) collapses to floating-only or hidden — no expanded mode (not enough horizontal real estate). Reduced-motion users get instant grid transition.

### JS

A small state machine in the existing CSP-nonced inline `<script>` block in `templates/transcript.html`:

```js
const TVideoRail = (function () {
  const rail = document.getElementById('t-video-rail');
  if (!rail) return null;
  const KEY = `trove.video.${TRANSCRIBE_ID}`;
  let state = JSON.parse(localStorage.getItem(KEY) || 'null') || { state: 'floating', pos: {x: 24, y: 24} };

  function apply() {
    rail.dataset.state = state.state;
    if (state.state === 'floating') {
      rail.style.left = state.pos.x + 'px';
      rail.style.bottom = state.pos.y + 'px';
    }
    document.querySelector('.t-doc-page')
      .classList.toggle('has-expanded-video', state.state === 'expanded');
    const showBtn = document.getElementById('t-video-show-btn');
    if (showBtn) showBtn.hidden = state.state !== 'hidden';
    persist();
  }
  function persist() { localStorage.setItem(KEY, JSON.stringify(state)); }

  rail.querySelector('.t-video-rail-close')
    ?.addEventListener('click', () => { state.state = 'hidden'; apply(); });
  rail.querySelector('.t-video-rail-expand')
    ?.addEventListener('click', () => {
      state.state = state.state === 'expanded' ? 'floating' : 'expanded';
      apply();
    });
  document.getElementById('t-video-show-btn')
    ?.addEventListener('click', () => { state.state = 'floating'; apply(); });

  // Drag (floating only)
  initDrag(rail, state, apply);

  apply();
  return { state, apply };
})();
```

Drag implementation: standard pointerdown → record offset → pointermove → set `state.pos.x/y` → pointerup → persist. ~30 lines.

For audio transcripts: `t-video-rail` is NOT rendered (template `{% if not is_audio %}`), the rail JS no-ops, the `▸ show video` button never appears.

---

## Section C · Diarization (Resemblyzer + silero-vad, no auth)

### Pipeline

```
audio.wav (16k mono PCM, already produced by transcriber.extract_audio)
  ↓
silero-vad → list of speech chunks: [{start, end}, ...]
  ↓
Resemblyzer → speaker embedding (256-d) per chunk
  ↓
sklearn AgglomerativeClustering (linkage="average", auto-K via gap statistic, capped at 1..6)
  ↓
chunk → cluster_id (Speaker 1, 2, ...)
  ↓
align with whisper word timings: each word gets the speaker_id of the chunk it falls in
  ↓
write back into data.segments[i].speaker
```

### New module: `diarizer.py`

```python
"""Local speaker diarization. No HF auth, no API keys.

Pipeline: silero-vad → speech chunks → Resemblyzer embeddings →
sklearn AgglomerativeClustering. ~70-80% accurate on clean audio.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SpeakerChunk:
    start: float    # seconds
    end: float
    speaker: str    # "Speaker 1", "Speaker 2", ...

def diarize(*, audio_path: str, expected_speakers: int | None = None) -> list[SpeakerChunk]:
    """Run VAD + embedding + clustering on a 16k mono WAV.
    
    expected_speakers: int 1-6, or None for auto-detect via gap statistic.
    Returns chunks sorted by start time.
    """
    chunks = _vad_speech_chunks(audio_path)
    if not chunks:
        return []
    embeddings = _embed_chunks(audio_path, chunks)
    n_speakers = expected_speakers or _auto_k(embeddings)
    labels = _cluster(embeddings, n_speakers)
    return [
        SpeakerChunk(start=c["start"], end=c["end"],
                     speaker=f"Speaker {labels[i] + 1}")
        for i, c in enumerate(chunks)
    ]

def _vad_speech_chunks(audio_path):
    """silero-vad to find speech regions."""
    # Lazy-import keeps test suite fast when diarization isn't exercised
    import torch
    model, utils = torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)
    # ... existing pattern from silero-vad README
    return [{"start": 0.0, "end": 5.2}, ...]

def _embed_chunks(audio_path, chunks):
    """Resemblyzer voice encoder produces a 256-d embedding per chunk."""
    from resemblyzer import VoiceEncoder, preprocess_wav
    import numpy as np
    encoder = VoiceEncoder()
    wav = preprocess_wav(audio_path)
    sr = 16000
    embeddings = []
    for c in chunks:
        seg = wav[int(c["start"] * sr):int(c["end"] * sr)]
        if len(seg) < sr * 0.5:  # skip < 0.5s chunks
            continue
        embeddings.append(encoder.embed_utterance(seg))
    return np.array(embeddings)

def _cluster(embeddings, k):
    from sklearn.cluster import AgglomerativeClustering
    if len(embeddings) < 2:
        return [0] * len(embeddings)
    clf = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
    return clf.fit_predict(embeddings)

def _auto_k(embeddings, max_k=6):
    """Gap statistic to choose k between 1 and max_k. Falls back to 1 if too few chunks."""
    # ... standard gap-statistic implementation, ~30 lines
    return 1  # placeholder
```

Total: ~150 lines including auto-K + tests. Fully self-contained module.

### Integration into transcribe lifecycle

In `app.py`'s `_work` closure (the transcribe worker), after `run_transcribe` succeeds and BEFORE `write_artifacts`:

```python
# 3.5: Diarize (best-effort; failure must not kill the transcribe)
try:
    chunks = diarizer.diarize(audio_path=wav_path)
    # Map each whisper word to a speaker via timestamp lookup
    for w in result.words:
        for c in chunks:
            if c.start <= w["start"] < c.end:
                w["speaker"] = c.speaker
                break
    # Build segments grouped by (consecutive same-speaker) instead of just speech-pause
    result.segments = _group_segments_by_speaker(result.words)
    # Populate segments[i].speaker
    for seg in result.segments:
        seg["speaker"] = seg["words"][0].get("speaker", "")
except Exception as e:
    # Log and continue. User can manually label speakers.
    app.logger.warning("diarization failed: %s", e)
```

`_group_segments_by_speaker` replaces the existing `_PARAGRAPH_GAP_SECONDS` grouping in `transcriber.run_transcribe` — when a speaker change happens, that's a new segment regardless of pause length. Pauses still split within a single speaker's run.

The `result.segments` shape doesn't change (`{start, end, text, words, speaker}`); only the grouping logic changes.

### Schema additions

`.words.json` (schema v2 — already in place):

- `data.segments[i].speaker` already exists. Diarization just populates it on initial transcribe instead of leaving it null.
- The user can still rename globally via the existing `/api/transcribe/<id>/speaker-rename` endpoint.

No schema bump needed.

### Setup wizard / first-run

`pip install resemblyzer silero-vad-fork scikit-learn` adds:
- `resemblyzer` ~5MB pip + ~100MB pretrained encoder bundled
- `silero-vad` ~10MB pip + bundled model
- `scikit-learn` is likely already a transitive dep
- `torch` is the heaviest — Resemblyzer requires it. ~700MB CPU-only wheel. **This is the real cost.**

Document in README: "Diarization adds ~800MB of dependencies to the install (PyTorch + voice encoder). Set `TROVE_DIARIZATION=off` to skip."

Env-var feature flag: `TROVE_DIARIZATION=off` makes the whole thing a no-op (segments are populated as before, all speakers null). Default `TROVE_DIARIZATION=on`.

If the import fails on startup (e.g., `import resemblyzer` ModuleNotFoundError), set the flag to off automatically and log "diarization unavailable — install with `pip install resemblyzer silero-vad-fork`."

### Tests

`tests/test_diarizer.py` (NEW):
- Fake-VAD chunks + fake encoder embeddings → exercise `_cluster` and `_auto_k` correctness.
- Lazy-import boundary: assert `diarize()` raises `RuntimeError("diarization unavailable")` when `resemblyzer` is not installed (mocked via `sys.modules`).
- Smoke test with the existing `tests/fixtures/sample-2s.wav` (only runs if `TROVE_DIARIZATION_E2E=1` — defaults skipped because it loads ~800MB of models).

---

## Section D · Comprehensive help panel

The current `?` keyboard-shortcuts modal becomes a richer help panel. Same trigger key, broader content.

### Sections

```
┌─────────────────────────────────────────────────────────┐
│  ✕                                          how to use  │
│ ──────────────────────────────────────────────────────  │
│                                                          │
│  ▸ Editing                                               │
│      Click anywhere in the document to place your cursor.│
│      Type to fix a transcript. Edits autosave.           │
│      Cmd+Z / Cmd+Shift+Z   undo / redo                   │
│      Enter inside a paragraph splits it at the cursor.  │
│      Backspace at the start of a paragraph merges it    │
│      with the one above.                                 │
│                                                          │
│  ▸ Playback                                              │
│      Space            play / pause                       │
│      J / L            seek -5s / +5s                     │
│      , / .            speed -0.25× / +0.25×              │
│      Click a word     normal text-edit (cursor)          │
│      Double-click     seek to that word                  │
│      Alt + click      seek without word-select           │
│      Click [00:14]    seek to segment start              │
│                                                          │
│  ▸ Find + Replace                                        │
│      Cmd+F            search transcript                  │
│      Cmd+Shift+F      find / replace (bulk)              │
│      Enter / Shift+Enter   next / previous match         │
│                                                          │
│  ▸ Speakers                                              │
│      Speakers are detected automatically (best-effort)   │
│      and labeled "Speaker 1, Speaker 2, ...". Click any  │
│      label to rename — the new name propagates to every  │
│      occurrence of that speaker.                         │
│                                                          │
│  ▸ Selection actions                                     │
│      Select any text to reveal a small toolbar:          │
│      Copy · Highlight · Bookmark · Add note              │
│      Right-click a selection adds "Export selection".    │
│                                                          │
│  ▸ Bookmarks                                             │
│      Cmd+B            bookmark current playback time     │
│      Click in sidebar to seek; click note to edit.       │
│                                                          │
│  ▸ Reviewed                                              │
│      Tick the checkbox in the gutter to mark a paragraph │
│      reviewed. Reviewed paragraphs get a faint green     │
│      left edge.                                          │
│                                                          │
│  ▸ Video controls                                        │
│      Floating window:  drag to reposition; ✕ to close;   │
│                        ⛶ to expand to a fixed left rail. │
│      Show video:       toolbar button when hidden.       │
│      Layout adapts so the document body always stays     │
│      readable.                                           │
│                                                          │
│  ▸ Export                                                │
│      .txt / .srt / .vtt buttons in the export menu.      │
│      Includes any edits.                                 │
│                                                          │
│  ▸ Tips                                                  │
│      • Press Esc to close menus or clear a selection.    │
│      • Toggle Follow-along to auto-scroll with playback. │
│      • The little "↓ jump to current" button appears    │
│        when you scroll away from the active paragraph.  │
│                                                          │
│                                          [ done — got it ]│
└─────────────────────────────────────────────────────────┘
```

### Implementation

Replace the existing `<dialog>` content for `t-shortcut-help` with the structured layout above. Sections are `<section class="help-section">` with an `<h3 class="help-section-h">` and a `<dl>` of `<dt>shortcut</dt><dd>description</dd>` pairs. Plain HTML, riso-styled, scrollable if it overflows the viewport.

### Discovery affordance

Add a small **"first-visit hint"** that appears once per browser:

```js
if (!localStorage.getItem('trove.transcript.seen-help')) {
  showToast('Press ? for help · click any word to edit · double-click to seek',
            { duration: 8000, kind: 'info' });
  localStorage.setItem('trove.transcript.seen-help', '1');
}
```

The toast disappears after 8 seconds OR on any user interaction. Doesn't repeat on subsequent visits.

---

## Files to modify

| File | Section | Change |
|---|---|---|
| `styles/input.css` | A1 | Replace `:focus-within` inset shadow (line 1233) — fix orange line |
| `styles/input.css` | A2 | Replace `.t-player-bar` background (line 1068) — solid cream |
| `styles/input.css` | B  | Add `.t-video-rail` + states + `.t-doc-page.has-expanded-video` |
| `styles/input.css` | D  | `.help-section` styles + scrollable `<dialog>` overflow |
| `templates/transcript.html` | B | New `<aside id="t-video-rail">` markup; `▸ show video` button in toolbar; remove the embedded `<video>` from the player bar |
| `templates/transcript.html` | B | Inline JS state machine (`TVideoRail`) + drag handler |
| `templates/transcript.html` | D | Replace shortcut-help dialog content with the structured help layout |
| `templates/transcript.html` | D | First-visit toast trigger (one-time) |
| `transcriber.py` | C | Replace `_PARAGRAPH_GAP_SECONDS` grouping with `_group_segments_by_speaker` (when a speaker change is provided) |
| `app.py` | C | In `_work` closure: call `diarizer.diarize` after `run_transcribe`, map words → speakers, populate segment speakers. Wrap in try/except so diarization failure never kills transcribe. |
| `diarizer.py` *(NEW)* | C | The pipeline |
| `requirements.txt` | C | Add `resemblyzer>=0.1.4`, `silero-vad-fork>=0.4.0`, `scikit-learn>=1.3` (Resemblyzer pulls torch as transitive) |
| `Dockerfile` | C | `RUN pip install --no-cache-dir resemblyzer silero-vad-fork scikit-learn` |
| `README.md` | C | Diarization section: how it works, how to disable (`TROVE_DIARIZATION=off`), install size warning |
| `tests/test_diarizer.py` *(NEW)* | C | Cluster + auto-K + lazy-import absence path |
| `tests/test_transcribe_endpoints.py` | C | Existing tests stay green (diarization is an additive layer, falls back gracefully) |

---

## Implementation order (TDD-style; each ends with green tests + a commit)

1. **A1 + A2 — bug fixes.** CSS only. No tests, but rebuild Tailwind + visual check. **Commit:** `fix(transcript): kill orange focus line + solid sticky player bar`
2. **B — floating video rail.** Template + CSS + JS. Manual smoke. **Commit:** `feat(transcript): floating left video rail (PiP / expand / hide states)`
3. **C1 — `diarizer.py` module + tests** with mocked deps. Lazy-imports + auto-K + cluster. **Commit:** `feat(diarizer): resemblyzer + silero-vad pipeline (no auth required)`
4. **C2 — wire into transcribe lifecycle.** `app.py` `_work` calls diarize; `transcriber.py` groups segments by speaker. Existing tests still pass. **Commit:** `feat(transcribe): populate speakers automatically via resemblyzer`
5. **C3 — feature flag + Dockerfile + README.** `TROVE_DIARIZATION=off` short-circuit; install size note. **Commit:** `feat(diarizer): TROVE_DIARIZATION env flag + setup docs`
6. **D — comprehensive help panel** + first-visit toast. **Commit:** `feat(transcript): full how-to-use help panel + first-visit hint`
7. **Manual QA pass** — see Verification.

---

## Out of scope (deferred)

- pyannote.audio / WhisperX integration (gated, requires HF auth — explicitly ruled out by user)
- Cloud diarization APIs (breaks self-hosted)
- Speaker color coding (Alice = blue, Bob = green) — v2.1
- Diarization quality tuning beyond default k auto-detect
- Per-speaker speed / volume controls in the floating rail
- Drag the floating window between display monitors / multi-window picture-in-picture (browser PiP API)
- Touch-friendly drag gestures for mobile (mobile collapses to fixed-position floating only)
- Persist video rail position to server (local only — browser-bound)

---

## Reused functions / patterns

- **Atomic JSON write** for any state changes: `transcript_io.save` (already in place).
- **htmx outerHTML swap** for any new endpoint responses.
- **CSP-nonced inline script** — extend the existing block in `transcript.html`. **Never add a second `<script>` tag** (strict CSP rejects it).
- **Riso-pill styling** — `.hero-pill` is the visual reference for the `▸ show video` button.
- **Modal overlay** — `.modal-overlay` + `.modal` (already in place for consent dialog) — reuse for the help panel.
- **Toast pattern** — `showToast()` already exists in the inline JS for save indicator + 409 errors. Reuse for first-visit hint.
- **`@token_required` from `safety.py`** — none of the new work adds an endpoint, so this is mostly N/A here.

---

## Verification

```bash
cd /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe

# Tests
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
# Expect 315 → ~325 (only +10; diarizer adds ~10 unit tests, others unchanged)

# Rebuild CSS
/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss \
  -i /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/styles/input.css \
  -o /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/static/app.css \
  --minify

# Manual smoke
PORT=8899 HOST=127.0.0.1 \
  /Users/kaivan108icloud.com/Downloads/trove/venv/bin/python \
  /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/app.py
# http://localhost:8899
```

Smoke checklist:
1. **Bug fixes:** click into a paragraph → no orange line on the left edge. Scroll the doc → toolbar/player are solid; nothing bleeds through.
2. **Floating video:** open a video transcript → small video window appears bottom-left. Drag it. Click ✕ → it hides and `▸ show video` appears in the toolbar. Click that → it's back. Click ⛶ → it expands to fill the left rail; document reflows to the right.
3. **Diarization (with model installed):** transcribe a podcast with 2+ speakers → segments come back already labeled `Speaker 1` / `Speaker 2`. User can rename either; rename propagates.
4. **Diarization off:** set `TROVE_DIARIZATION=off`, restart, transcribe → segments come back unlabeled (current behavior).
5. **Help panel:** press `?` → full how-to opens with all controls. First-time visitors see a hint toast that disappears after 8s.
6. **CSS layer audit:** `grep -nE "@layer|@media|^}" styles/input.css | head -30` — verify all new selectors are at top scope or inside `@layer components`, not nested in `@media (max-width: 480px)`.

---

## Risk + mitigation

- **PyTorch install size.** ~700MB on top of the existing image. Mitigation: feature-flag with `TROVE_DIARIZATION=off`; document the install size; consider a "no-diarization" Docker tag for users who don't need it.
- **Resemblyzer accuracy on noisy audio.** ~70% — worse than pyannote. Mitigation: user can manually correct via the existing speaker-rename UX. Document the accuracy expectation in the README.
- **Auto-K (gap statistic) over-counts speakers.** A monologue might show as 2 speakers due to noise. Mitigation: cap at 1..6, plus surface a manual "n speakers" override on the setup page (defer to v3.2 if not in v3.1).
- **Floating window drag-to-overlap with the document text.** Set `pointer-events: none` on the document while dragging. The drag handler already gets pointer capture; document text remains readable but not selectable mid-drag. Restore on pointer-up.
- **Mobile / narrow viewports.** Below 768px, expanded mode disables (no left-rail real estate); floating mode auto-collapses to a fixed thumbnail at the top of the page.
- **Help-panel info overload.** Group by section; collapsible sections if needed. Or use plain `<details>` so users can expand only what they need.

---

## Pickup notes

- All four sections (A/B/C/D) can ship independently. If time-constrained, A is the highest immediate value (visible bugs).
- C is the heaviest by far (PyTorch dep). Treat it as its own mini-PR if reviewing in pieces.
- D is mostly markup; the discovery toast is the only behavioral change.
- Existing v3 work (`dfffe34`/`c3e1cb9`) on the branch stays as-is. This plan adds onto it.
