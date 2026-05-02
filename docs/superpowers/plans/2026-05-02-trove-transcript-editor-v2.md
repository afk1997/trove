# Trove · transcript editor v2 — "make changes on the go"

> **Branch:** `transcribe` (continuation; this lands on top of the existing transcript-page work)
> **Worktree:** `/Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe`
> **Status:** Plan refined via Ultraplan; ready for implementation.

## Context

`/transcript/<id>` is read-only today: every word is a `<span data-start>` you can click to seek/search/follow. The user can't fix typos, delete junk words, merge "you"+"tube", or label speakers — and they said exactly that ("good and functional but not that intuitive… cannot make the changes on the go").

This plan turns the read-only viewer into an editor while preserving the existing read-only behaviors (click-to-seek moves to dbl-click, search keeps working, follow-along keeps working, exports keep working). All edits are local to the user's transcript JSON; whisper's verbatim output is preserved per-word in `original_w` so any change can be reverted.

User-locked decisions (do **not** revisit):
- **Edit model:** click a word → it becomes an inline input → blur/Enter auto-saves. No edit-mode toggle, no save button. Cmd+Z undoes.
- **Scope:** all four extras — word-level cleanup, find-and-replace, variable playback + keyboard shortcuts, speaker labels + bookmarks.

---

## Approach

```
        ┌─────────────────────────────────────────────────────────────┐
        │  templates/transcript.html  (existing CSP-nonced <script>)  │
        │  ─────────────────────────────────────────────────────────  │
        │  click word → <input>  ── PATCH ─┐    Cmd+Shift+F bar       │
        │  hover ✕/→/+ handles    ── *  ──┐│    speed row, ?, Cmd+B   │
        │  speaker tag click     ── PATCH ┐│  bookmarks sidebar       │
        └────────────────────────────────┼┼┼─────────────────────────┘
                                         ││└──────────────┐
                                         │└────────────┐  │
                                         ▼             ▼  ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  app.py  — new @token_required routes (htmx fragment swaps)  │
        │  PATCH/DELETE/POST /api/transcribe/<id>/word/<idx>/...       │
        │  PATCH            /api/transcribe/<id>/segment/<idx>/speaker │
        │  POST/DELETE/PATCH/api/transcribe/<id>/bookmark[/<bm_id>]    │
        │  POST             /api/transcribe/<id>/find-replace          │
        └──────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  transcript_io.py  (NEW — single source of schema knowledge) │
        │  load(path) → dict          (auto-migrates v1 → v2)          │
        │  apply_word_op(data, idx, op, **kw)                          │
        │  apply_speaker(data, seg_idx, speaker, propagate)            │
        │  add/edit/delete bookmarks                                   │
        │  find_replace(data, find, replace, case_sensitive)           │
        │  regenerate_artifacts(data, base_path)  → .txt/.srt/.vtt     │
        │  save(path, data)           (atomic via tempfile+os.replace) │
        └──────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  downloads/<id>.words.json   schema v2                       │
        │  + .txt / .srt / .vtt        regenerated on every mutation   │
        │  + .words.v1.json            one-shot backup on first edit   │
        └──────────────────────────────────────────────────────────────┘
```

### Schema v2 (additive over v1)

```json
{
  "schema_version": 2,
  "language": "en",
  "duration": 12.0,
  "edited_at": null,
  "words": [
    { "idx": 0, "w": "hello", "original_w": "hello",
      "start": 0.0, "end": 0.42,
      "edited": false, "deleted": false }
  ],
  "segments": [
    { "start": 0.0, "end": 5.2, "text": "hello world …",
      "word_idxs": [0,1,2,3], "speaker": null }
  ],
  "bookmarks": [
    { "id": "bm_abc1", "time": 12.34, "note": "key insight" }
  ]
}
```

**Authority rule:** `data.words[]` is authoritative for word text/timing. `data.segments[i].word_idxs` are authoritative for paragraph membership and order. Segments are **stable** after the v1→v2 migration — edits never re-derive paragraphs (would yank text under the user). Inserts append to the anchor word's segment's `word_idxs`; deletes set `deleted=true` but keep the idx in `word_idxs` (filtered at render).

**v1 → v2 migration** runs lazily on first `load()` of any `.words.json` lacking `schema_version: 2`:
1. Copy raw file → `<base>.words.v1.json` (one-time backup; skip if already exists).
2. For each word in `data["words"]` set `idx` (0..n-1), `original_w = w`, `edited=false`, `deleted=false`. Note: in v1 the segment-word dicts are *the same Python objects* as the flat-array words (see `transcriber.py:111-127`), so this single pass annotates segment views too — the JSON serializes them duplicated, which is fine.
3. For each segment, set `word_idxs = [w["idx"] for w in seg["words"]]`, default `speaker = null`. Drop the redundant `seg["words"]` list (segments now reference by idx only).
4. Add `bookmarks: []`, `edited_at: null`, `schema_version: 2`. Idempotent.

### Word ops

`apply_word_op(data, idx, op, **kw)` supports:
- `set_text(idx, w)` → updates `data.words[idx].w`, sets `edited = (w != original_w)`.
- `delete(idx)` → `deleted = true`. Idx stays in `word_idxs`; renderer skips it.
- `insert_after(idx, w)` → new word, `idx = max(idx)+1`, `original_w = w` (user-authored), inherits `start/end` from the anchor's `end` (zero-duration), inserted into the anchor's segment's `word_idxs` right after the anchor.
- `merge_next(idx)` → idx absorbs idx+1's text and `end`; idx+1 becomes `deleted=true`.

Render rule: a span emits a word when `not data.words[idx].deleted`.

### Auto-save UX

Each edit is one POST/PATCH. Server returns the rendered word fragment (`partials/transcript_word.html`) and htmx swaps it `outerHTML`. A toast (`saved · just now`) renders bottom-right via a CSS keyframe + `htmx:afterRequest` listener; fades in 2s. `409` → orange `couldn't save · reload to refresh` toast.

### Find-replace

One POST returns `{count, fragments: {idx: html, ...}}`. JS iterates and swaps each affected `<span data-idx>` outerHTML. Cmd+Z replays as inverse find-replace using a single stored last-pair on the client (good enough for the common case; matches plan-locked decision).

### Speaker labels

Per-segment tag above each `<p class="t-segment">`. Click → inline input → PATCH segment with `{speaker, propagate: true}`. Server cascades to all subsequent segments whose `speaker is None` until another non-null is found, then returns rendered fragments for every changed segment, htmx swaps each.

### Bookmarks

Right-side collapsible panel at ≥1100px (button+drawer at smaller). `Cmd+B` adds bookmark at `player.currentTime`. Click time → seek; click note → inline edit.

### Variable playback + keyboard shortcuts

Pure DOM, no server work.
- Speed row: `0.5× / 1× / 1.25× / 1.5× / 2×` pills above player; persists in `localStorage["trove.playbackRate"]`.
- Document `keydown` (only when no input focused): `Space/K` play-pause, `J` -5s, `L` +5s, `,`/`.` rate ±0.25, `Cmd+Shift+F` toggle find-replace, `Cmd+B` bookmark, `Esc` close find / cancel edit. `?` opens a riso-styled help modal reusing `.modal-overlay`/`.modal` from `styles/input.css:742`.

---

## Files to modify

All paths relative to the worktree root: `/Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe`.

| File | Change |
|---|---|
| `transcript_io.py` *(NEW)* | `load`, `save`, `_migrate_v1_to_v2`, `apply_word_op`, `apply_speaker`, `add/update/delete_bookmark`, `find_replace`, `regenerate_artifacts`. Atomic save mirrors `transcribe_jobs.py:98-124`. |
| `transcriber.py` | `write_artifacts` (current lines ~159-176 in the post-pywhispercpp-fix version) writes schema v2 directly: emit `idx`/`original_w`/`edited`/`deleted` per word, `word_idxs`/`speaker=null` per segment, `bookmarks=[]`, `edited_at=null`, `schema_version=2`. Extract the .txt/.srt/.vtt blocks into `transcript_io.regenerate_artifacts(data, base_path)` and call it from here. |
| `app.py` | New routes (all `@token_required`, all under `/api/transcribe/<tid>/`): `PATCH word/<idx>`, `DELETE word/<idx>`, `POST word/<idx>/insert-after`, `POST word/<idx>/merge-next`, `PATCH segment/<seg_idx>/speaker`, `POST bookmark`, `PATCH bookmark/<bm_id>`, `DELETE bookmark/<bm_id>`, `POST find-replace`. The `transcript_view` route (search for `def transcript_view(transcribe_id)`) also reads `data["edited_at"]` and passes a `was_edited` flag to the template. |
| `templates/transcript.html` | Adds: speed row above player; find-replace bar (toggle); speaker tag above each `<p class="t-segment">`; bookmarks aside; `?` help button + modal; toast container. Word `<span>`s gain `data-idx` and `hx-*` attrs. JS expansion stays in the existing single `<script nonce>` block, organized by `// === EDIT ===`, `// === FIND/REPLACE ===`, `// === SPEED ===`, `// === KEYBOARD ===`, `// === BOOKMARKS ===` IIFE-style sections. |
| `templates/partials/transcript_word.html` *(NEW)* | One word fragment for PATCH responses. |
| `templates/partials/transcript_segment.html` *(NEW)* | One segment fragment for speaker swaps. |
| `templates/partials/transcript_bookmark.html` *(NEW)* | One bookmark `<li>` for POST/PATCH responses. |
| `styles/input.css` | New selectors after the existing transcript block: `.word.is-editing`, `.word.is-edited`, `.word-handles`, `.t-speed-row`, `.t-find-replace`, `.t-speaker-tag`, `.t-bookmarks`, `.t-toast`, `.t-shortcut-help`. Mirror riso-stamp pill style from `.hero-pill` for speed buttons. **Watch the layer scoping** — past tasks accidentally appended CSS inside `@media (max-width: 480px)`; insert before the mobile media query opens, OR after the file's last `}` at top scope. |
| `tests/test_transcript_io.py` *(NEW)* | Migration round-trip; word ops; speaker propagation; bookmarks CRUD; find-replace count + result; export regeneration after edits; backup file written once, then skipped. |
| `tests/test_transcribe_endpoints.py` | One test per new route × {200, 401-when-token, 404, 400}. End-to-end smoke: load → edit → reload-route → assert text changed. |
| `docs/superpowers/specs/2026-05-01-trove-transcribe-design.md` | Strike "Inline transcript editing" from §3 *Out (deferred to v2+)* and add a §13 note pointing at this plan. |

---

## Reused functions / patterns

- **Atomic JSON write** — copy the tempfile + `os.replace` shape from `transcribe_jobs.py:_persist`. Same pattern as `models_store.py:download` for the `.part`-then-rename safety.
- **htmx outerHTML swap** — already used across `templates/partials/*.html` (cards, dismiss, transcribe action); word edits use the same `hx-swap="outerHTML"`.
- **CSP-nonced script block** — extend the existing one in `templates/transcript.html` (it currently holds the click-to-seek + search + active-highlight JS); never add a second `<script>` tag — the strict CSP from `safety.py` will reject it.
- **Riso-stamp pills** — `.hero-pill` in `styles/input.css` is the visual reference for speed-row buttons and find-replace controls.
- **Modal overlay** — `.modal-overlay` + `.modal` (added in TR-T15 for the consent dialog) for the keyboard-shortcut help modal. `hx-on:click="if (event.target === this) this.remove()"` is the existing dismiss-on-backdrop pattern.
- **`@token_required`** from `safety.py` for all mutation endpoints. **`token_or_sig_required`** (added in TR-T23) for any new route that gets embedded as a media-style `src` attribute.
- **Per-test isolation** — `tests/test_transcribe_endpoints.py` fixture monkeypatches both `app.DOWNLOAD_DIR` and `models_store.MODELS_DIR` per test. New tests must follow the same pattern or `transcribe_jobs.json`/`.words.json` will pollute across runs.

---

## Implementation order (TDD-style; each step ends with green tests + a commit)

1. **TR-E1** — `transcript_io.py` `load`/`save`/`_migrate_v1_to_v2` + tests. Migration is idempotent; v1 backup file is written once.
2. **TR-E2** — `apply_word_op` (set_text/delete/insert_after/merge_next) + tests. Segment `word_idxs` updated on insert; preserved on delete; never re-derived.
3. **TR-E3** — Extract `regenerate_artifacts` from `transcriber.write_artifacts`; have `write_artifacts` call it. Tests: edit text → `.txt` reflects change; `.srt`/`.vtt` timestamps untouched.
4. **TR-E4** — Word endpoints (PATCH/DELETE/insert/merge) + `partials/transcript_word.html` + endpoint tests.
5. **TR-E5** — Click-to-edit + auto-save toast in `transcript.html` + CSS. Move existing click-to-seek to **dbl-click** so single-click is reserved for editing. Tab/Enter/blur commits, Esc reverts.
6. **TR-E6** — Hover handles `✕`/`→`/`+` per word; reduced-motion users get instant reveal.
7. **TR-E7** — Find-replace endpoint (returns rendered fragments keyed by idx) + Cmd+Shift+F bar UI.
8. **TR-E8** — Speed row + `localStorage` persistence (pure JS).
9. **TR-E9** — Document-level keyboard shortcuts + `?` help modal.
10. **TR-E10** — Speaker endpoint + segment partial + propagation cascade + tests.
11. **TR-E11** — Bookmarks endpoints + sidebar UI + `Cmd+B` shortcut + tests.
12. **TR-E12** — Header `· edited` badge wiring; toast polish; `409` orange variant.
13. **TR-E13** — End-to-end test sweep covering one full cycle (load v1 → edit text → delete word → insert → merge → set speaker → bookmark → find-replace → reload route → assert state survived; assert exports regenerated).

---

## Out of scope (explicitly deferred)

- Adjust word timestamps / drag handles for ms tuning.
- Re-transcribe a selected range with a bigger model.
- Audio cut-when-you-cut-text (Descript-style).
- Real-time multi-user collaboration.
- Diff view (`original_w` vs current `w`) — data is preserved, UI is v3.
- AI-suggested cleanups ("'youtube' was split 47 times — fix all?").
- Server-side undo stack. Client stores last find-replace pair only.

---

## Verification

```bash
cd /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe

# Tests
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest -q
# Expect ~200 passed (was 169 at start of this branch's editor work).

# Rebuild Tailwind after CSS edits
/Users/kaivan108icloud.com/Downloads/trove/tools/tailwindcss \
  -i /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/styles/input.css \
  -o /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/static/app.css \
  --minify

# Manual smoke flow:
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python /Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe/app.py
# Open http://localhost:8899
# Save a video → wait done → click ▸ transcribe → wait → ▸ view transcript ↗
# In the new tab:
#   1.  Click a word → fix typo → see toast.
#   2.  Hover word → ✕ deletes; → merges next; + inserts.
#   3.  Cmd+Shift+F → "the" → "THE" → confirm count rendered.
#   4.  Click 1.5× pill → playback speeds up.
#   5.  Cmd+B at 2:34 → bookmark appears in sidebar; click time → seek.
#   6.  Click speaker tag → "Alice" → propagates to following paragraphs.
#   7.  Press ? → shortcut help modal opens.
#   8.  Reload page → all edits + bookmarks survive; header shows "· edited".
#   9.  Click .txt export → contains edited content, not the original.
```

---

## Risk + mitigation

- **Migration corrupts a real user's data.** First migration writes `<base>.words.v1.json` next to the file before saving v2. Documented; recoverable.
- **htmx swap loses focus on the input.** Test deliberately: after a successful PATCH, focus should land on the *next* `.word` so Tab + edit + Tab + edit feels fluid.
- **Find-replace is destructive.** Result toast offers `↩ undo (Cmd+Z)`; undo replays as inverse find-replace using the stored pair. Single-step, bounded scope.
- **JS sprawl.** All edit JS stays in the single CSP-nonced block; sectioned by `// === HEADING ===` IIFE blocks for readability. No second `<script>` tag.
- **CSS layer scoping** (lesson learned the hard way on this branch): when adding new selectors to `styles/input.css`, verify with `grep -n "@media\|^}" styles/input.css | head` that you're inserting at top scope OR inside `@layer components`, NOT inside `@media (max-width: 480px)`. Past tasks accidentally nested all new CSS inside the mobile breakpoint, so nothing applied at desktop.

---

## Pickup notes (when resuming this work)

- Branch: `transcribe`. Base: `93e70a5` (main pre-transcribe-merge) → currently at `5e4b79f` (after pywhispercpp API fix). Push state: `origin/transcribe`.
- 168 tests passing as of pickup time. New work targets ~200.
- Spec at `docs/superpowers/specs/2026-05-01-trove-transcribe-design.md` is the v1 baseline; this plan adds an editor on top of it.
- Per the workflow, dispatch the implementer → spec reviewer → code-quality reviewer per task (subagent-driven-development). Mark each `TR-E<N>` complete in TodoWrite as you go.
- Worktree at `/Users/kaivan108icloud.com/Downloads/trove/.worktrees/transcribe`. The main repo at `/Users/kaivan108icloud.com/Downloads/trove` stays on `main`.
- Whisper model used for testing: `models/ggml-base.bin` (~140MB). Real-world transcribe currently works (verified with the pywhispercpp API fix in `5e4b79f`).
