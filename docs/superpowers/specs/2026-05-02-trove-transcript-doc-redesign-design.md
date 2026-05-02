# Trove · transcript page — document-editor redesign (v3)

**Status:** Draft (awaiting user review)
**Date:** 2026-05-02
**Branch:** `transcribe`
**Depends on:** v2 editor work currently merged on `transcribe` (commits `0769f60` → `4ec7d9c`)
**Replaces:** the per-word hover-handle UX shipped in v2

---

## 1 · Context

The v2 editor (just merged) made the transcript editable but kept the page shaped like a debugging panel: word-level hover handles (`✕`/`→`/`+` floating above each word), click-to-edit on a single span swapping to an `<input>`, two-pane video-left layout. The user reaction was: *"feels too much like a technical transcription UI… should feel closer to Google Docs, Notion, or a polished article editor."*

This redesign replaces the word-level affordances with a **document-first** layout: contenteditable paragraphs, a centered max-width body, sticky header + toolbar + compact player at the top, and selection-based interactions instead of hover-based. The text-editing primitives (PATCH/DELETE/insert/merge per word) stay; the UI on top of them changes radically.

User-locked decisions:
- **Player placement:** sticky compact bar at the top of the page, just under the toolbar. Always visible.
- **Editing model:** paragraph-level `contenteditable="plaintext-only"`, browser-native cursor + native undo, JS-side diff against word state to fire existing word-op endpoints.
- **No hover handles.** Word-level interactions are invisible — they happen via cursor placement and selection.
- **Single click** = place cursor (edit). **Double click** on a word = seek media. **Click timestamp** = seek to segment start. **Click speaker name** = rename globally.
- **Selection toolbar** appears only after text is selected. Right-click adds an "Export selection" item.
- All four extras from the user's brief are in v1: highlights, bookmarks (already shipped), notes, reviewed-status.

---

## 2 · v1 scope

### In

- **Four-zone layout:** header (title + meta + saving indicator) → toolbar → sticky compact player → centered document body. Top three zones sticky; only the body scrolls.
- **Editable title** in the header (rename the transcript document).
- **Doc-style segments:** `[hh:mm:ss]  Speaker N` over each paragraph block, paragraph as a single `contenteditable` element with word spans inside.
- **Inline editing** via contenteditable + word-diff. PATCH `set_text` / `insert_after` / `merge_next` / `delete` flows through the existing word endpoints. Native browser undo (Cmd+Z) just works because the source of truth is the DOM text, and the diff replays whatever the post-undo state implies.
- **Enter splits a paragraph** at the cursor's word position. **Backspace at the start of a paragraph merges** with the previous one. Two new backend ops + endpoints.
- **Speaker rename global:** click a speaker name → inline edit → all segments with that previous name update. New backend op + endpoint.
- **Selection toolbar:** appears on text selection inside `.transcript-body`. Actions: Copy, Highlight, Bookmark, Add note.
- **Right-click context menu** on selected text: Copy, Highlight, Bookmark, Add note, Export selection.
- **Highlights** persist (yellow by default). Stored in `.words.json` as `[{id, word_idx_start, word_idx_end}]`.
- **Notes** anchored to a word. Render as a `[1]` superscript that opens an inline note editor.
- **Reviewed-status** per segment. Subtle checkbox in the left gutter. Reviewed segments get a faint forest-green left border.
- **Follow-along mode** scrolls the active segment into view during playback. Toggle in toolbar.
- **"Return to current position"** floating button appears when the user scrolls away from the active segment during playback.
- **Active segment highlight** = soft cream wash on the current paragraph. Active word = subtle dashed orange underline.
- **Saving indicator** in the header: `✓ saved` / `saving…` / `✕ couldn't save · retry`. Replaces the bottom-right toast for edit mutations.
- **Search transcript** (existing) repositioned into the toolbar.
- **Find/replace** (existing) repositioned into the toolbar.
- **Undo / redo** browser-native (contenteditable). Toolbar buttons mirror the keyboard shortcuts.
- **Timestamp display toggle** — show/hide the `[hh:mm:ss]` gutter labels.
- **Speaker display toggle** — show/hide the `Speaker N` headers (when content is single-speaker, this declutters).
- **Variable playback speed pills** (existing) embedded in the sticky player.
- **Keyboard shortcuts** (existing): Space play/pause unless typing; Cmd+F search; Cmd+Shift+F find/replace; Cmd+B bookmark; Cmd+Z undo; Cmd+Shift+Z redo; Esc close menu / clear selection.

### Out (deferred to v3+)

- **Word-timestamp adjustment** (drag handles, ms-precision tuning).
- **Multi-color highlights.** Yellow only in v1.
- **Comment threads on highlights** (replies). Notes are single-author single-message.
- **Speaker color assignment** (Alice → blue, Bob → green). All speaker labels render in teal in v1.
- **Per-paragraph "regenerate this" via a different model.**
- **Track-changes / version history.** Edits are direct.
- **Hover handles ✕/→/+** — explicitly removed.
- **Two-pane layout** — explicitly removed.
- **Bottom-right toast for edits** — replaced by header saving indicator. Toast stays for non-edit events (find-replace count, model-download progress).

---

## 3 · The four zones

### Zone A · Document header (sticky, top)

```
trove. · transcript                                              [⌂ home]
─────────────────────────────────────────────────────────────────────────
┃ How a Whisper hears the world ┃                                ✓ saved
12 min · EN · 2 speakers · whisper-base
```

- **Title row:** editable text. Click to rename. Persists to `data.title` (new field) — falls back to `parent_job.title` (the source media's title) if `data.title` is empty.
- **Meta row:** duration, detected language, count of distinct speakers (computed from `data.segments[*].speaker`), model used.
- **Saving status** lives at the right edge of the title row. Animates between states. Click on `✕ couldn't save · retry` resends the last failed mutation.
- The whole zone collapses into a thin top bar on scroll (~56px) — title only, meta hides — but stays sticky.

### Zone B · Toolbar (sticky, below header)

```
[⚲ search] [⇄ find/replace] [↶ undo] [↷ redo]   [✎ speakers ▾] [⌚ times ▾]
[▼ follow along]                          [⬇ export ▾]              [⋯]
```

Two visual rows on wider viewports, single row with overflow on narrower. All buttons are riso-pill style (border + dashed underline on hover, matching `.hero-pill`).

- **Search** opens an inline search bar in place of the toolbar (esc to close). Behavior unchanged from existing.
- **Find/Replace** (Cmd+Shift+F) — existing.
- **Undo/Redo** call `document.execCommand('undo'/'redo')` on the focused contenteditable — browser-native; the input listener picks up the resulting state and PATCHes the diff. Toolbar buttons mirror keyboard.
- **Speakers ▾** — dropdown: `show speaker labels` checkbox (default on); `rename all "Alice" → …` quick action per speaker.
- **Times ▾** — dropdown: `show timestamps in gutter` (default on), `inline timestamps before paragraph` (alt), `none`.
- **Follow along** — toggle button; persists per-transcript in `localStorage`.
- **Export ▾** — dropdown: `.txt` / `.srt` / `.vtt`. (Same endpoints as today.)
- **⋯** — overflow: `print transcript`, `copy permalink`, `revert all edits` (with confirm).

### Zone C · Sticky compact player (sticky, below toolbar)

```
▶  ━━━━━━━━━━━●━━━━━━━━━━  1:42 / 12:00       [0.5×|1×|1.5×|2×]   [♀ ⌑]
```

- 48px tall. Play/pause + scrubber + time + speed pills.
- The actual `<video>` / `<audio>` element is rendered hidden in the DOM and the visible bar is a custom UI bound to it (`player.play()`, `player.currentTime`, `player.playbackRate`). Lets us style without browser chrome.
- For video files, a small `[♀]` button at the right reveals a popover with the actual video frame (180×100, lazy-loaded). Clicking the popover toggles fullscreen video. Audio files just hide this button.
- Scrubber click = seek. Pressing-and-dragging = scrub.

### Zone D · Document body (scrolls)

Centered, max-width 720px (the document feel). Soft cream paper continues from the body background — no card / no border. Generous line-height (1.7) and paragraph spacing.

```
        How a Whisper hears the world.
        ─────────────────────────────────────
                                                            ← title repeats
                                                              for "document
                                                              feel"; small
                                                              and subdued

  ☐  [00:07]   Speaker 1                                    ← reviewed checkbox
                                                              + timestamp gutter
        Okay, we've got a founder right here. What's
        your company?

  ☑  [00:14]   Speaker 2
        We make software for the cannabis industry.

  ☐  [00:18]   Speaker 1   ← active, soft cream wash on whole paragraph
        What level of software?
```

**Per-segment block:**
- Reviewed checkbox in left gutter (small, mono, click to toggle). When checked, the gutter side of the paragraph gets a faint `1.5px solid var(--forest)` border-left.
- Timestamp `[00:07]` — mono, smaller than body, click to seek to `segment.start`.
- Speaker label — Fraunces italic, small, click to rename **globally**.
- Body text — Fraunces 18px, line-height 1.7, in a `<p contenteditable="plaintext-only">`. Words are `<span data-idx data-start>` children; their text is what users edit.

**No per-word borders.** Active word gets `text-decoration: underline dashed var(--orange); text-underline-offset: 4px`. Active paragraph gets `background: rgba(254, 247, 227, 0.6)` (light cream wash).

---

## 4 · Editing model

### Source of truth

`data.words[]` in `<id>.words.json` (schema v2 from prior work) stays the canonical store. Each word has a stable `idx`, a `start` / `end` time, an `original_w` (whisper's verbatim), the current `w` (possibly edited), `edited`, `deleted`. **None of this changes.**

### DOM ↔ data binding

Each segment renders as:

```html
<p class="t-segment" data-seg-idx="3"
   contenteditable="plaintext-only"
   spellcheck="false">
  <span class="word" data-idx="42" data-start="14.2">We</span>
  <span class="word" data-idx="43" data-start="14.4">make</span>
  …
</p>
```

The browser handles cursor, selection, native undo, double-click word selection, etc.

### Diff loop

JS holds a per-segment cache: `lastKnown[seg_idx] = [{idx, w}, {idx, w}, …]` — synced from server on initial load and after every successful PATCH.

On every `input` event (debounced 500ms):
1. Walk the `<p>`'s `<span data-idx>` children, gather `current = [{idx, w}, …]`.
2. Diff `current` vs `lastKnown[seg_idx]`:
   - Same idx, different `w` → `PATCH /api/transcribe/<id>/word/<idx>` with `{w}`.
   - Idx in lastKnown but missing from current → `DELETE /api/transcribe/<id>/word/<idx>`.
   - New text not anchored to a known idx → `POST /api/transcribe/<id>/word/<anchor_idx>/insert-after` with `{w}`.
3. After all PATCHes succeed, update `lastKnown[seg_idx]` to current.

The header `✓ saved` indicator flips to `saving…` while requests are in flight and back to `✓ saved` when the queue empties. `✕ couldn't save · retry` on any non-2xx; click retry to re-send the failed batch.

### Native undo (free)

Browser undo (Cmd+Z) reverts the contenteditable text to a prior state. The next `input` event fires, the diff sees the old state again, and the appropriate PATCH/POST/DELETE replays. We get undo for free without a custom undo stack on the server. Redo (Cmd+Shift+Z) is the same in reverse.

The single edge case: if a network PATCH succeeded but Cmd+Z reverts past it on the client, the client's `lastKnown` is stale (post-PATCH state) but DOM is pre-PATCH. The diff catches this — sees the DOM "regressed" and PATCHes back. Self-healing.

### Enter / Backspace at paragraph boundaries

These don't fit the "diff word array" model — they restructure segments. We listen for `keydown` on `.t-segment` and intercept:

- **Enter** (no shift):
  1. `e.preventDefault()`.
  2. Find the word index where the cursor is (find the last `<span data-idx>` before the cursor, or the next one if the cursor is on a space).
  3. `POST /api/transcribe/<id>/segment/<seg_idx>/split` with body `{after_word_idx}`.
  4. Server splits the segment, returns rendered fragments for both halves; client swaps the original `<p>` with the two new ones via htmx-style outerHTML.
  5. Place cursor at the start of the second new paragraph.

- **Backspace** at offset 0 of `.t-segment`:
  1. `e.preventDefault()`.
  2. `POST /api/transcribe/<id>/segment/<seg_idx>/merge-prev`.
  3. Server merges words[] of seg-1 + seg, drops seg, returns rendered fragment for the merged paragraph.
  4. Client swaps two `<p>`s for one. Place cursor at the join.

Implementation note: the segments are stable after migration (per v2 contract — never re-derived). Split/merge are the *only* ways segments mutate.

### Speaker rename global

Click on `Speaker 1` label → swap to inline `<input value="Speaker 1">`. Type new name. Blur/Enter:
- `PATCH /api/transcribe/<id>/speaker-rename` body `{old: "Speaker 1", new: "Alice"}`.
- Server walks `data.segments[]`, replaces every occurrence, persists, returns the count of segments updated.
- Client gets back rendered fragments for all updated segments (or a `{updated_seg_idxs: [...], html: {...}}` map) and swaps each `<p>`.

This is **distinct** from the existing per-segment speaker patch endpoint (which sets one segment's speaker, with optional propagation forward). Both endpoints stay; the global rename uses a value-replace approach not an idx-based one.

---

## 5 · Selection toolbar + right-click + highlights / notes

### Selection toolbar

Appears on `selectionchange` when the selection is non-empty AND inside `.transcript-body`. Floats above the selection range, ~32px tall, four icons: `Copy`, `Highlight`, `Bookmark`, `Add note`. Disappears on selection clear, click outside, or Esc.

- **Copy** copies the selected text (no markup, no timestamps).
- **Highlight** wraps the selection in `<mark class="is-highlight" data-h-id="...">`. The action computes the word-idx range covered by the selection (find first / last `<span data-idx>` intersected) and posts to `POST /api/transcribe/<id>/highlight` body `{word_idx_start, word_idx_end}`. Server appends to `data.highlights[]` and persists. Client wraps the relevant DOM range in the mark element.
- **Bookmark** anchors to the first word's start time. Reuses existing bookmark endpoint.
- **Add note** opens a small inline note editor anchored to the first word in the selection. Submitting POSTs to `POST /api/transcribe/<id>/note` body `{word_idx, text}`. Server appends to `data.notes[]`. Client renders a `[N]` superscript next to the word.

### Right-click context menu

On contextmenu over a non-empty selection in `.transcript-body`: `e.preventDefault()`, render a small popover at the mouse position. Items:
- Copy
- Highlight
- Bookmark
- Add note
- Export selection — generates a `.txt` of just the selected range with `[hh:mm:ss]` prefixes per segment-break. Uses a new endpoint `POST /api/transcribe/<id>/export-selection` body `{word_idx_start, word_idx_end}` returning a downloadable text blob with proper Content-Disposition.

When there's no selection, the right-click does *nothing custom* — the browser's default menu shows. (We don't override the right-click globally; only when the user has selected text inside the transcript body.)

### Highlights / notes / reviewed in `.words.json` (v2.1, additive)

The schema bumped to v2 in the prior work. We add three optional arrays; the v2-loader treats missing arrays as empty (graceful):

```json
{
  "schema_version": 2,
  "title": "How a Whisper hears the world",   // NEW (optional, falls back to parent.title)
  ...
  "segments": [
    {
      ...,
      "speaker": "Alice",
      "reviewed": false                        // NEW (defaults to false)
    }
  ],
  "highlights": [                              // NEW
    {"id": "h_abc1", "word_idx_start": 12, "word_idx_end": 18}
  ],
  "notes": [                                   // NEW
    {"id": "n_xyz9", "word_idx": 42, "text": "key insight here"}
  ]
}
```

`transcript_io._migrate_v1_to_v2` extends to populate these defaults if missing. No new schema_version bump — v2 stays compatible.

---

## 6 · Active highlight + follow-along + return-to-position

### Active segment + active word

A `timeupdate` listener on the player runs ~4× per second:
1. Binary-search `data.words[]` for the word whose `start ≤ currentTime < end`. Mark that span `.is-active`.
2. Walk up to the parent `.t-segment`. Mark it `.is-active-segment`.
3. Remove `.is-active*` from the previously-active word/segment.

`.is-active-segment` styling: `background: rgba(254, 247, 227, 0.6); transition: background 200ms ease-out`. Visible but not jarring.

### Follow-along

When toggle is on (default): every active-segment change calls `activeSegmentEl.scrollIntoView({block: 'center', behavior: 'smooth'})`.

When the user scrolls manually (we listen for `scroll` events with a ~150ms throttle): if the scroll is user-initiated (we set a flag during programmatic scrolls and clear it 600ms after), we set `followingPaused = true` for that playback session. The toggle button visually de-emphasizes (`opacity: 0.5`).

### Return-to-position button

When `followingPaused === true` and the active segment is offscreen: render a small floating pill at the bottom-center: `↓ jump to current`. Click → smooth-scroll active segment into view AND set `followingPaused = false` (re-enable following). Disappears when the active segment scrolls back into view naturally OR on click.

Reduced-motion users: scroll behavior `auto` instead of `smooth`. Active-segment background transition becomes 0ms.

---

## 7 · Visual / typography direction

The page reads as a document, not a tool. Riso-zine palette stays — it's the brand — but:

- **No card borders** around the document body. Just the cream paper background continuing from the body.
- **Centered max-width** 720px. Generous left/right margins on wide screens.
- **Body text:** Fraunces, 18px, line-height 1.7, color teal. Italic `Speaker N` labels (Fraunces italic, 14px). Mono `[00:07]` timestamps (IBM Plex Mono, 11px, color teal at 0.55 opacity).
- **Active states:** soft cream wash on segment, dashed orange underline on word. No hard borders.
- **Selection toolbar:** small floating riso-stamp (cream paper, dashed teal border, 2px offset shadow), 4 icons in a row.
- **Sticky zones:** subtle `box-shadow: 0 1px 0 rgba(26,53,64,0.08)` underneath each so they read as floating layers without being heavy.
- **Highlights:** `mark.is-highlight` gets `background: rgba(255, 230, 138, 0.55); border-bottom: 2px solid rgba(217, 158, 0, 0.55)`. Yellow-ish, not jarring against cream paper.
- **Notes superscript:** small mono `[1]` colored orange, no underline.
- **Reviewed border:** 1.5px solid forest-green on the gutter side of the segment.

CSS layer: all new selectors go in `@layer components` AT TOP-LEVEL. Lesson learned from the previous mobile-media-nesting bug.

---

## 8 · Files to modify

| File | Change |
|---|---|
| `templates/transcript.html` | Major rewrite — four-zone layout, contenteditable paragraphs, sticky player UI, toolbar with all the buttons, JS expansion (still in single CSP-nonced script) for diff loop / split-merge / selection toolbar / right-click menu / follow-along / saving indicator. |
| `templates/partials/transcript_segment.html` | Now the unit of swap for split/merge/speaker-rename. Renders the contenteditable `<p>` + gutter (timestamp, reviewed checkbox, speaker tag). |
| `templates/partials/transcript_word.html` | Existing, keeps role for word-PATCH responses. Updated to remove any leftover handles (already clean if v2 was correct). |
| `templates/partials/transcript_selection_toolbar.html` *(NEW)* | Static fragment for the floating selection toolbar; rendered once and shown/hidden via JS. |
| `templates/partials/transcript_note.html` *(NEW)* | The inline note editor + the rendered note popover. |
| `transcript_io.py` | Extend: `split_segment_at_word(data, seg_idx, after_word_idx)`, `merge_segment_with_prev(data, seg_idx)`, `rename_speaker(data, old, new) → list[int]`, `add_highlight(data, word_idx_start, word_idx_end) → highlight_id`, `delete_highlight(data, highlight_id)`, `add_note(data, word_idx, text) → note_id`, `update_note(data, note_id, text)`, `delete_note(data, note_id)`, `set_segment_reviewed(data, seg_idx, reviewed)`, `set_title(data, title)`. The v1-to-v2 migration adds defaults for the new optional fields. `regenerate_artifacts` unchanged (highlights/notes/reviewed don't affect .txt/.srt/.vtt). |
| `app.py` | New routes: `POST /api/transcribe/<id>/segment/<seg_idx>/split`, `POST /api/transcribe/<id>/segment/<seg_idx>/merge-prev`, `PATCH /api/transcribe/<id>/speaker-rename`, `POST /api/transcribe/<id>/highlight`, `DELETE /api/transcribe/<id>/highlight/<h_id>`, `POST /api/transcribe/<id>/note`, `PATCH /api/transcribe/<id>/note/<n_id>`, `DELETE /api/transcribe/<id>/note/<n_id>`, `PATCH /api/transcribe/<id>/segment/<seg_idx>/reviewed`, `PATCH /api/transcribe/<id>/title`, `POST /api/transcribe/<id>/export-selection`. All `@token_required`. |
| `styles/input.css` | New section `/* === TRANSCRIPT DOCUMENT v3 === */` with the four-zone layout, contenteditable styling, selection toolbar, highlights, notes superscript, reviewed border, sticky bars, follow-along return button. **Insert at top scope or inside `@layer components` — never inside the mobile media query.** Old `.transcript-grid` / `.transcript-media` / `.word-handles` rules from v2 get removed (they're dead under the new layout). |
| `tests/test_transcript_io_segment_ops.py` *(NEW)* | split/merge/rename-speaker/highlight/note/reviewed tests. Round-trip persistence. |
| `tests/test_transcript_doc_endpoints.py` *(NEW)* | Endpoint smokes for each new route × {200, 401-when-token, 404, 400}. |
| `tests/test_transcribe_endpoints.py` | Update `test_transcript_page_renders` to assert new structure (four zones present, contenteditable on segment paragraphs, etc.). |

---

## 9 · Reused functions / patterns

- **Atomic JSON write** — keep using `transcript_io.save` (tempfile + `os.replace`).
- **htmx outerHTML swap** — segment partials swap the same way word partials do today.
- **CSP-nonced inline script** — extend the existing block in `transcript.html`. **Never add a second `<script>` tag.**
- **Riso-pill button** — `.hero-pill` is the visual reference for toolbar buttons.
- **Modal overlay** — `.modal-overlay` from the consent dialog for the keyboard-shortcut help and `revert all edits` confirm.
- **Word-op endpoints** — PATCH/DELETE/insert/merge per word stay verbatim; the JS diff loop just uses them.
- **Per-transcript lock** — the `_txn_locks` mechanism in `app.py` already serializes mutations per transcript; new segment/highlight/note endpoints reuse it.

---

## 10 · Testing

- Unit tests on `transcript_io` for every new op (split/merge/rename-speaker/highlight/note/reviewed/title). Round-trip save → load → assert.
- Endpoint tests via Flask test client for each new route.
- A focused JS diff test: simulate `current[]` vs `lastKnown[]` permutations (set_text only, single insert, single delete, mixed) and assert the right requests fire. Vanilla JS is hard to unit-test from pytest; this test stays at the Python level by **not** testing JS — instead we test the endpoints exhaustively and trust the diff to be a thin layer.
- One end-to-end test: load a fixture `.words.json`, hit `POST split` at word_idx N, hit `PATCH speaker-rename`, hit `POST highlight`, save, reload route, assert the rendered HTML reflects each change.

Goal: existing 241 → ~280 passing.

---

## 11 · Out of scope (explicit)

- Word-timestamp adjustment / drag handles.
- Multi-color highlights (yellow only).
- Comment threads on highlights / notes (single-author single-message).
- Speaker color assignment.
- Per-paragraph regenerate-with-different-model.
- Track-changes / edit history beyond browser-native undo.
- Two-pane / video-left layout (replaced by sticky compact player).
- Bottom-right toast for *edit* events (replaced by header indicator). Toast stays for find-replace count and model download progress.
- Hover handles `✕ → +` per word (explicitly removed).
- The CSP `frame-ancestors *` change in commit `0769f60` should be audited separately — not part of this redesign.

---

## 12 · Verification

```bash
cd /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe

# Tests — ~280 expected after this work
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q

# Rebuild Tailwind
/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss \
  -i /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/styles/input.css \
  -o /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/static/app.css \
  --minify

# Manual smoke flow:
PORT=8899 HOST=127.0.0.1 \
  /Users/kaivan108icloud.com/Downloads/trove/venv/bin/python \
  /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/app.py
# Browse to http://localhost:8899/transcript/<id> on a finished transcribe.
```

Smoke checklist:
1. **Layout:** four zones visible; document body centered; player sticky at top; no two-pane.
2. **Click word once:** cursor lands inside word; nothing else happens.
3. **Type a fix:** header flips to `saving…`, then `✓ saved`. Reload page → edit persists.
4. **Double-click word:** media seeks to that word.
5. **Click `[00:14]`:** media seeks to segment start.
6. **Click `Speaker 1`:** input opens; type `Alice`, blur; ALL paragraphs by Speaker 1 rebadge to Alice. Reload → persists.
7. **Place cursor mid-paragraph + Enter:** paragraph splits at the cursor word; cursor lands at start of second.
8. **Backspace at start of paragraph:** merges with previous; cursor lands at the join.
9. **Select 3 words → selection toolbar appears:** Highlight click yellow-marks them; reload → highlight persists.
10. **Right-click on the selection:** custom menu shows; Export selection downloads a `.txt` with `[hh:mm:ss]` prefixes.
11. **Toggle follow-along OFF, scroll up during playback:** `↓ jump to current` button appears; click → re-enables.
12. **Reviewed checkbox click on a paragraph:** gutter gets a forest-green border; reload → persists.
13. **Press `?`** (existing): help modal lists all shortcuts.
14. **Toggle Speakers off** in toolbar: speaker labels hide; data unchanged.
15. **CSS layer audit:** `grep "@media\|^}" styles/input.css | head` — verify new selectors are NOT inside the mobile media query (lesson learned).

---

## 13 · Risk + mitigation

- **Contenteditable edge cases:** browsers normalize whitespace differently (Chrome inserts `&nbsp;`, Firefox inserts space, Safari occasionally inserts `<br>`). Spec the diff to: (a) coerce non-breaking spaces back to regular spaces before diff, (b) strip stray `<br>` and `<div>` wrappers on input. Test on macOS Chrome, Safari, Firefox.
- **Cursor placement after htmx swap** (split/merge/speaker-rename returns new HTML): record the intended cursor position before the request, find the corresponding word span by `data-idx` after the swap, restore.
- **PATCH storms during fast typing:** 500ms debounce on the input listener. While debouncing, the saving indicator stays in `saving…` (not `✓ saved`).
- **Network failure on a PATCH:** queue the PATCH and retry on next mutation OR on the user clicking `✕ couldn't save · retry`. If the user keeps typing, queue grows; flush in idx order.
- **Layout-break on tiny viewports:** below 640px, the toolbar collapses to single-row + `⋯` overflow. Player stays sticky, smaller. Document body has 16px side padding.
- **CSS layer scoping:** explicitly checked in §12 verification step 15.
- **Old transcripts (no `title` / `highlights` / `notes` / `reviewed`):** migration in `transcript_io._migrate_v1_to_v2` populates defaults. Test covers v1 → v2.1-loaded round-trip.

---

## 14 · Pickup notes

- The v2 editor (per-word handles) is the immediate predecessor on this branch. After v3 ships, the `.word-handles` CSS, the JS hover-show logic, and the old grid layout in `templates/transcript.html` should all be **deleted** (not just unused — actually removed) to keep the codebase clean. List them in the implementation plan as a final cleanup step.
- The current transcript page lives at `templates/transcript.html` (~390 lines) and `styles/input.css` lines 880–1408 (≈530 lines of `.transcript-*` rules). After the redesign, expect the template to grow but the CSS to net-decrease (no two-pane grid, no hover handles).
- The implementation plan should split the work into ~12–14 tasks (TR-D1 through TR-D14) — bigger than v2 because the layout change is a full rewrite of the template.

---

End of spec.
