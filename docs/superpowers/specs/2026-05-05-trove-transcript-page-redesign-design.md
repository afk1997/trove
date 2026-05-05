# Trove · transcript page UX redesign (v4)

> **Branch:** `transcribe`
> **Worktree:** `/Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe`
> **Status:** Design approved by user. Ready for implementation plan.
> **Scope:** Presentation only. No backend, schema, or endpoint changes.

## Context

The v3 transcript page (commits `dfffe34` … `cc4b981`) shipped a working
contenteditable document editor with diarization, but manual QA on
real-content surfaced two recurring complaints:

1. **Three stacked sticky bars** (header, toolbar, player) eat ~160 px of
   vertical space before any content is visible. On a 1080 px laptop screen
   that's ~15 % of the viewport gone to chrome before scrolling.
2. **The floating video** (current `.t-video-rail` PiP) is intrusive — it
   covers content while reading, the floating/expanded/hidden state machine
   is fiddly, and z-index conflicts with the dropdowns and toast stack
   ("z-index issues still" per user manual QA).

Industry references (`Descript`, `Riverside.fm`, `Otter.ai` via Refero
lookup) all converge on a common pattern:

  - Single thin top bar.
  - Document on the left.
  - Small video in a dedicated **right rail** that lives next to the
    transcript, never overlaps it.
  - Player controls grouped with the video, not stacked across the page.

Trove is desktop-only for now (user confirmed: "no one using it on phones
so don't worry about it"). The redesign locks this in: a single sticky
top bar plus a permanent right rail, no responsive collapse.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  trove. / Job Interview ESL · 1:45 · en   ● saved  [↶][↷] ⌕⤓⋯  │  60 px sticky topbar (z:20)
├──────────────────────────────────────────────┬──────────────────┤
│                                              │  ┌────────────┐  │
│   Speaker 1 · 00:01                          │  │   video     │  │  rail (320 px,
│   Mary? Hi. Hello. I'm Susan Thompson,       │  │   280×160   │  │  sticky top:76)
│   Resource Manager.                          │  └────────────┘  │
│                                              │  ▶ 00:14 / 01:45 │
│   Speaker 2 · 00:09                          │  ▭━━●━━━━━━━━━━ │
│   I'm Mary Hansen and I'm applying           │  speed  1× 1.25× │
│   for one of your kitchen jobs.              │                  │
│                                              │  Speakers     ▾  │
│   Speaker 1 · 00:16  ◀ active                │  ● Speaker 1     │
│   ╎ Great. Have a seat, Mary. Thank you.     │    Speaker 2     │
│                                              │                  │
│   ...                                        │  Bookmarks (2)▾  │
│                                              │  00:14  setup    │
│   (max-width 720 px, document column)        │  01:08  hours    │
└──────────────────────────────────────────────┴──────────────────┘
                       Page: max-width 1180 px, centered.
```

CSS scaffolding:

```css
.t-page         { max-width: 1180px; margin: 0 auto; padding: 0 24px 120px; }
.t-topbar       { position: sticky; top: 0; z-index: 20; height: 60px; … }
.t-grid         { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 32px; }
.t-doc-body     { max-width: 720px; }
.t-sidebar      { position: sticky; top: 76px; align-self: start; }  /* 60 + 16 gap */
```

### Z-index ladder

Six layers, monotonic:

| Layer | z |
|---|---|
| document body, sidebar (in-flow) | (default) |
| topbar | 20 |
| selection toolbar | 30 |
| context menu | 40 |
| toast stack | 50 |
| modal overlay | 100 |

The current 8+ layers (header 30, toolbar 28, player 27, dropdowns 40,
floating video 40, jump-to-current 45, context menu 60, toast 80, modal
1000) collapses to six because the floating video is gone and the toolbar
bars merge into the topbar.

---

## Components

### 1 · Top bar (`.t-topbar`)

```
trove.   ›  Job Interview ESL          ● saved   [↶][↷]  ⌕  ⤓  ⋯
```

- **Mark + crumb** — `trove.` (orange period) + `›` separator.
- **Title** — inline-editable `<h1>` (existing `.t-doc-title`, hoisted from row 2).
- **Saved indicator** — existing `.t-doc-saving` component (saved / saving… / retry).
- **History** — `[↶ undo] [↷ redo]` buttons (existing).
- **Search ⌕** — opens a slim popover under the icon. Combined find / find+replace tabs in one panel; replaces the existing two-row search-bar + find-replace slabs that pushed the toolbar to two rows.
- **Export ⤓** — same dropdown as today (.txt / .srt / .vtt / "selection" when there's an active selection).
- **More ⋯** — overflow menu for less-frequent actions: follow-along toggle, help (?), regenerate-artifacts.

The current `.t-doc-toolbar` and `.t-player-bar` are deleted entirely.
Their items move to (a) the topbar, (b) the rail's player strip, or (c) the More menu.

### 2 · Right rail (`.t-sidebar`)

Three stacked components inside one sticky aside.

#### 2a · Video block (`.t-sidebar-video`)

- Always visible, fixed 280×160 (16:9-ish).
- Uses the same `<video id="t-player">` element as today, signed media URL.
- For audio-only files: same element, `poster` attribute set to a placeholder image (`static/audio-cover.svg`).
- Native browser fullscreen / Picture-in-Picture controls work via the default `controls` attribute.

#### 2b · Player strip (`.t-sidebar-player`)

```
▶ 00:14 / 01:45
▭━━●━━━━━━━━━━━━
speed  1× 1.25× 1.5× 2×
```

- Play/pause button + scrubber + time display + speed pills, all in one
  three-line block.
- Driven by the same JS bindings that drove `.t-player-bar`. The `<video>`
  element is the source of truth; both this strip and the native browser
  controls update it.

#### 2c · Speakers panel (`.t-sidebar-panel--speakers`)

```
Speakers  ▾
● Speaker 1
  Speaker 2
```

- A `<details open>` with a chevron summary.
- Lists distinct values of `data.segments[].speaker`, plus "(unlabeled)"
  if any segment has `speaker == None`.
- The currently-talking speaker (i.e. the one whose label is on the
  active segment) gets a filled `●` orange dot; others get `○` outlined.
- Click any label → opens an inline rename input (existing
  `/api/transcribe/<id>/speaker-rename` endpoint).
- Open/closed state persists in localStorage (`trove.transcript.<id>.speakers-open`).

#### 2d · Bookmarks panel (`.t-sidebar-panel--bookmarks`)

```
Bookmarks (2)  ▾
00:14  setup question
01:08  hours
[+ add bookmark]
```

- Same `<details open>` pattern.
- One row per bookmark, sorted by time (matches `transcript_io.add_bookmark`'s sorted insert).
- Time pill click → `<video>.currentTime = bm.time`, paused.
- Note text click → inline-edit (existing `/api/transcribe/<id>/bookmark/<bm_id>` PATCH).
- `[+ add]` button captures `<video>.currentTime` and POSTs to `/api/transcribe/<id>/bookmark`.

### 3 · Document column (`.t-doc-body`)

Largely unchanged structurally — same `<section data-segment-idx>` and `<span class="word" data-word-idx>` elements with all the same data hooks. Three style updates:

- **Active segment marker.** Replace the buggy `.t-seg-body:focus-within { box-shadow: inset 2px 0 0 var(--orange); }` (the "huge orange line" the user complained about earlier — it was leaking visually because the inset side caused a vertical bar) with `.t-seg-body:focus-within, .t-seg.is-active { box-shadow: inset 2px 0 0 var(--teal); }`. Teal not orange, and reused for both cursor-focus and playback-active so they don't compete.
- **Active word style.** Drop the orange-block fill. Use `.t-word.is-active { text-decoration: underline; text-decoration-color: var(--orange); text-decoration-thickness: 2px; text-underline-offset: 3px; }`. Keeps reading legibility.
- **Speaker labels.** Existing `.t-seg-speaker` button — no visual change, but a new `.is-talking` modifier class flips on at the same time as the active-segment marker so the speakers-panel dot can sync with the document.

### 4 · Existing components — unchanged

- Selection toolbar, context menu, toast stack, modal overlay, help dialog, jump-to-current button, autosave debounce, follow-along auto-scroll algorithm. All keep their existing classes, JS, and behavior. Only their z-index values get tightened to fit the six-level ladder.

---

## Interactions

### Active state (per `<video>.timeupdate`)

A single existing handler updates three things on each tick (~250 ms):

```
T = video.currentTime

active_segment   = first seg where seg.start <= T < seg.end
active_word      = first word where word.start <= T < word.end
active_speaker   = active_segment.speaker  (or None)

→ apply class is-active to that segment and that word
→ apply class is-talking to the matching speakers-panel row
→ remove from previous markers
```

This logic exists today; only the selectors update.

### Click-to-seek (existing, no change)

- **Single-click word** → place text cursor (edit mode).
- **Double-click word** → `<video>.currentTime = word.start; <video>.play()`.
- **Alt + click word** → seek without moving the cursor.
- **Click time pill** (`· 00:14` next to speaker) → `<video>.currentTime = segment.start; <video>.pause()`.

### Follow-along auto-scroll (existing algorithm, trigger moved)

- Toggle in the More menu, default ON, persisted in localStorage.
- When ON, playback active, and active segment is outside viewport: smooth-scroll the segment to ~30 % from the top of the viewport.
- Suspended automatically while user is editing or has a non-empty selection — re-enables 5 s after idle.
- `prefers-reduced-motion: reduce` switches to instant scroll.

### Search popover

- ⌕ in the topbar opens a popover, anchored under the icon, ~360 px wide.
- Two tabs: **Find** and **Find + replace**.
- Same input + button DOM structure as today's `.t-tb-search-bar` and `.t-tb-fr-bar`, just inside a popover instead of a row.
- ESC closes; Cmd+F opens find tab; Cmd+Shift+F opens replace tab.

### Reduced motion

- Active-segment fade-in: removed.
- Auto-scroll: `behavior: 'auto'`.
- All other transitions: kept ≤200 ms (already conformant).

---

## Files modified

| File | Change | Approx LOC delta |
|---|---|---|
| `templates/transcript.html` | Restructure markup: single `.t-topbar`, 2-col `.t-grid`, `.t-doc-body` + `.t-sidebar` with video / player / speakers / bookmarks panels. | -300 / +500 |
| `styles/input.css` | Replace zones B and C (`.t-doc-toolbar`, `.t-player-bar`) and the entire `.t-video-rail` state machine. New rules for `.t-topbar`, `.t-grid`, `.t-sidebar*`, `.t-sidebar-panel`. Tighten z-index ladder. | -400 / +600 |
| Inline JS in `transcript.html` | Delete TVideoRail (drag, floating/expanded/hidden, localStorage persistence). Add search-popover toggle. Update active-state selectors. | -200 / +100 |

**Net:** ~+300 LOC across 1 template + 1 CSS file. No backend or schema changes.

### Deleted

- `.t-video-rail[data-state="floating"|"expanded"|"hidden"]` rules.
- `TVideoRail` JS module (drag handler, state persistence, expand/hide buttons).
- `.t-doc-page.has-expanded-video` grid mode + body max-width swap.
- `.t-doc-toolbar`, `.t-tb-group`, `.t-tb-toggle`, `.t-tb-export` (rules — buttons themselves move to topbar).
- `.t-tb-search-bar`, `.t-tb-fr-bar` (replaced by search popover).
- `.t-video-show-btn` ("▸ show video" pill — no longer needed since rail is permanent).
- `.t-player-bar` (relocated content moves to `.t-sidebar-player`).

### Preserved

Backend / schema / endpoints — zero changes.

UI components / behaviors — kept (relocated only):

- Title inline edit + save indicator
- Undo / redo stack
- Find / replace endpoints + logic (UI moves into popover)
- Word ops, segment split/merge, speaker rename, bookmark CRUD, highlights, notes, reviewed-flag, export-selection
- Selection toolbar
- Context menu (right-click)
- Toast pattern, modal pattern, help dialog
- Auto-save debounce
- Follow-along auto-scroll algorithm
- Jump-to-current button
- Click-to-seek (single/double/alt)

---

## Tests

Backend test suite (582 currently green) stays green — no endpoint changes.

New / updated tests:

- **`tests/test_transcript_view_layout.py`** *(NEW)*
  - `test_renders_single_topbar` — page contains exactly one `.t-topbar`, no `.t-doc-toolbar`, no `.t-player-bar`.
  - `test_renders_sidebar_video_player_speakers_bookmarks` — `.t-sidebar` exists with `.t-sidebar-video`, `.t-sidebar-player`, `.t-sidebar-panel--speakers`, `.t-sidebar-panel--bookmarks` children.
  - `test_no_video_rail_state_machine` — page does NOT contain `.t-video-rail` or `data-state="floating|expanded|hidden"` markers.
  - `test_speakers_panel_lists_distinct_speakers` — given a fixture with Speaker 1 and Speaker 2, both labels appear in `.t-sidebar-panel--speakers`.
  - `test_bookmarks_panel_renders_sorted` — given two bookmarks at different times, both render and are sorted ascending.

- **`tests/test_transcript_extras_endpoints.py`** *(existing, may need selector updates)*
  - Existing tests that scrape rendered HTML for `.t-tb-search-bar` etc. need their selectors updated.

---

## Verification

```bash
cd /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe

/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
# Expect: 582 + ~5 new = ~587 passing.

/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss \
  -i styles/input.css -o static/app.css --minify

PORT=8899 HOST=127.0.0.1 TROVE_DIARIZATION=on \
  /Users/kaivan108icloud.com/Downloads/trove/venv/bin/python app.py
# http://127.0.0.1:8899/transcript/<id>
```

Smoke checklist:

1. **Single sticky bar.** Scroll the document — only the topbar sticks at the top. No second or third row appears.
2. **Sidebar.** Video + player + speakers + bookmarks all visible on the right. Sidebar sticks below the topbar when scrolled.
3. **Active state.** Press play. Active word underlines orange; active segment shows a teal left rail; the talking speaker's dot fills in the rail.
4. **Search popover.** Click ⌕. Popover appears under the icon. Type → matches highlighted; tab to "Find + replace"; both inputs work.
5. **Speakers panel.** Click a speaker name → inline rename input. Save → all matching segment labels in the document update.
6. **Bookmarks panel.** Click `[+ add]` → new bookmark at current time appears. Click time pill → seeks. Click note → edits.
7. **No floating video.** No drag handle, no expand/hide buttons. Native browser PiP / fullscreen still work via the `<video>` controls.
8. **Z-index hygiene.** Open the export dropdown — it sits over the document but under any modal. Open the help modal — it covers everything. Toast on save shows above all of the above.

---

## Out of scope

- Mobile / responsive layout (user confirmed: desktop-only).
- Speaker color rotation (inline color dots use a single orange/cream pair for now; per-speaker colors can come in a v4.1).
- Waveform visualization in the player (Riverside-style). The compact scrubber stays; waveform is a separate feature.
- Diarization quality improvements (out of scope here; tracked separately).
- Word-timestamp DTW alignment (would require swapping pywhispercpp for faster-whisper; explicit user decision was to keep pywhispercpp for speed).

---

## Pickup notes

- All interactivity is in the existing CSP-nonced inline `<script>` block in `templates/transcript.html`. Do NOT add a second `<script>` tag; strict CSP rejects it.
- The riso aesthetic (cream paper, teal, orange, halftone overlay) stays. Only the layout changes.
- The redesign is intentionally a single PR — staging it leaves the page with a half-removed toolbar that's worse than either the old or the new state.
- After implementation, the existing v3 spec (`docs/superpowers/specs/2026-05-02-trove-transcript-doc-redesign-design.md`) becomes historical; this v4 spec supersedes its layout sections (the editor model and word-ops behavior remain authoritative from v3).
