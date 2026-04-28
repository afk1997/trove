# Trove — Tape Deck Redesign

**Date:** 2026-04-28
**Branch:** `redesign/tape-deck`
**Project:** github.com/afk1997/trove
**Status:** Approved (verbal), pending written-spec sign-off
**Previous spec:** `2026-04-28-trove-phase-1-design.md` (rebrand + redesign + hardening — shipped on `main`)

## What this is

A complete frontend redesign that transforms Trove from a generic warm-and-friendly SaaS into a late-1970s home-stereo cassette deck — full-bleed walnut wood, brushed aluminum, amber LED display, mechanical buttons. Built for "I want to screen-record this and post on X" virality.

Phase 1 backend, security work, tests, and JobManager all stay. This is purely a visual + interaction layer overhaul.

## Goals

- Replace the current Tailwind-utility consumer-friendly UI with a single full-bleed tape-deck interface
- Make the core flow (paste URL → see cassette load → press REC → reels spin → eject) something a person would screen-record and share
- Add MP3 mode that flips the deck away to reveal a turntable underneath (vinyl on felt mat, tonearm)
- Add opt-in sound design (button clicks, mechanical clunks, low whir during record, completion chime)
- Keep all 63 existing tests passing — backend untouched
- Drop the page-footer "Originally based on…" line (attribution stays in LICENSE + README)

## Non-goals

- Backend changes (Flask routes, JobManager, runner, safety) — none
- Multi-deck simultaneous downloads (one active job slot at a time, completed jobs go to a horizontal "shelf" below)
- Custom mascot / illustration / character work
- Light mode (dropped — a tape deck is inherently dark; light mode would look wrong)
- Mobile-specific separate layout (responsive within the single design)
- New endpoints or data shapes
- A11y beyond the standard reduced-motion / sound-off / keyboard / aria-live coverage

## Visual direction

### Aesthetic
Late-1970s / early-1980s home stereo component. Walnut wood case, brushed aluminum face plate, matte-black trim, amber 7-segment LED display, mechanical silver buttons with red REC indicator. Single dark aesthetic; no light mode toggle.

### Color tokens (CSS custom properties)
```
--wood-base:    #3d2818
--wood-grain:   #4a2e1a
--aluminum:     #c5c2bb
--aluminum-dim: #8e8b85
--faceplate:    #1a1816
--led-amber:    #ff9a3c
--led-red:      #ff3c3c
--led-glow:     0 0 12px rgba(255,154,60,0.6)
--tape-shell:   #14110f
--tape-label:   #e8dcc4
--felt-green:   #1f3a2a
--vinyl:        #0a0a0a
--scratch:      rgba(255,255,255,0.04)
```

### Typography
| Use | Family | Notes |
|---|---|---|
| Wordmark, button labels | **Anton** (Google Fonts) | Chunky 70s display |
| Tape labels | **Permanent Marker** (Google Fonts) | Handwritten flavor |
| Digital display | **VT323** (Google Fonts) | Pixel/7-segment look |
| Body fallback | Inter (already loaded) | Rare; only for accessibility text |

### Layout
- Single full-bleed deck filling viewport
- Desktop: horizontal stereo component (16:9-ish), centered, with shelf below for completed jobs
- Mobile (≤640px): same deck rotated to portrait — cassette window is taller, controls below
- No top nav, no page footer, no "framework chrome"
- Sound toggle (🔊/🔇) in extreme top-right corner of deck face (small, easily ignored)

### Components on the deck face
| Element | Description |
|---|---|
| Body | Walnut wood (CSS gradient + SVG fractal-noise grain overlay) |
| Face plate | Brushed aluminum (linear gradient + horizontal scratch noise) |
| Wordmark **TROVE** | Embossed top-left in Anton, etched into aluminum |
| Tape window | Smoked-glass viewport, center; shows cassette interior |
| Digital display | Right of window: VT323 amber text, glowing. States: `READY` / `LOAD` / `REC ▶` / counter (`0:00`) / `DONE` / `ERR` |
| VU meters | Two horizontal needle gauges below the display; needles pulse during REC tied to fake "bytes/sec" pulses (since yt-dlp doesn't surface byte-rate progress in our current pipeline) |
| Buttons | Silver mechanical row: ◁◁ REW · ◻ STOP · **● REC** · ▷▷ FF · ▲ EJECT |
| Format toggle | Two physical-looking toggles, MP4 (cassette icon) / MP3 (vinyl icon) |
| URL input | Below the deck on a "label slot": monospace placeholder "PASTE URL ON TAPE LABEL" |
| Sound toggle | Top-right corner, tiny |

### MP3 / vinyl mode
Toggling MP3 triggers a one-shot animation: the cassette deck **rotates and lifts away** (CSS perspective + transform), revealing a turntable underneath — black vinyl on a green felt mat with a chrome tonearm parked on the right. The same flow applies but: vinyl spins, tonearm drops onto track 1 on REC, lifts on DONE. Different mechanical sounds (vinyl click, needle drop).

### Cassette interactions (sequence)
1. **Empty state:** deck door open, empty spools visible, display reads `READY`.
2. **User pastes URL + clicks Fetch:** door slides up with a `clunk` sound, a black-shell cassette materializes inside, label paper types out the video title in Permanent Marker (text-typing animation), door slides closed. Display: `LOAD ✓`.
3. **User clicks REC:** REC button physically depresses (transform translateY), red LED illuminates, both reels start rotating in opposite directions, VU meters bounce, counter ticks `0:00 → 0:01 → …`. Display: `REC ▶`.
4. **Done:** reels decelerate and stop with a `clunk`, REC LED off, door slides up, cassette slides forward toward viewer (translateZ), display: `DONE`. Click cassette → file downloads.
5. **Error:** display flashes `ERR`, REC LED blinks red, brief `buzz` sound. After 2s, door reopens; cassette ejects.

### Multiple downloads — the shelf
Below the main deck, a horizontal **shelf** holds completed cassettes (or vinyls) — small thumbnails with title labels. Click one to re-download. The shelf is hidden until the first job completes; max 12 items shown, older ones scroll horizontally.

Only one job is *active in the deck* at a time. If a user pastes a second URL while one is recording, the new fetch is queued and shown in a small "next up" indicator next to the deck (a small cassette spine peeking from a side slot). When current job ends, next-up auto-loads.

### Animation specifics
- **Reels spin:** CSS `@keyframes rotate` on each reel hub, `animation-play-state` toggled via Alpine state
- **Needle pulsing:** JS sets a CSS variable on the VU needle every ~120ms during REC; pulse is procedural (sine wave with slight random jitter for realism)
- **Counter ticking:** JS interval at 1s during REC; updates `<span data-counter>` text
- **Door slide / cassette transform:** GSAP timeline (smoother than CSS for orchestration)
- **Deck flip to turntable:** GSAP timeline using CSS perspective + rotateX/Y
- **Reduced motion (`prefers-reduced-motion: reduce`):** all rotations, slides, flips replaced with simple `opacity` cross-fades over 200ms

### Sound design
Web Audio API + 6 small WAV samples in `static/sounds/` (~80 KB total):
| File | Trigger | Notes |
|---|---|---|
| `clunk-open.wav` | Tape door opens | Mechanical, ~200ms |
| `clunk-close.wav` | Tape door closes | Heavier than open |
| `whir.wav` | Looped during REC | Very low volume; gain duck on user voice if any |
| `click.wav` | Button press | Crisp, plastic |
| `chime.wav` | Done | Optional, off by default |
| `buzz.wav` | Error | Short razz |

Sound is **off by default** (toggle persists in `localStorage`). Web Audio context is lazy-initialized on first user interaction (browsers require gesture). All sound calls degrade gracefully if Web Audio is unavailable.

## Architecture

### Files
```
trove/
├── templates/
│   ├── base.html               REWRITE — drops Tailwind utility shell, adds deck stylesheet + deck.js, removes footer attribution
│   ├── index.html              REWRITE — deck markup
│   └── partials/
│       ├── card.html           REWRITE — fits the deck cassette/vinyl rather than a generic card
│       └── shelf-item.html     NEW — small completed-cassette thumbnail
├── static/
│   ├── css/
│   │   └── deck.css            NEW — all the deck visuals, animations, reduced-motion
│   ├── js/
│   │   └── deck.js             NEW — Alpine components for deck state, GSAP orchestration, Web Audio playback
│   ├── sounds/                 NEW — 6 WAV files, ~80 KB total (license-free)
│   ├── img/
│   │   ├── deck-grain.svg      NEW — wood grain noise pattern
│   │   ├── deck-scratches.svg  NEW — brushed aluminum scratches
│   │   ├── cassette-shell.svg  NEW — base cassette graphic
│   │   ├── reel.svg            NEW — single reel hub (used twice)
│   │   ├── vinyl.svg           NEW — vinyl record (groove pattern + center label)
│   │   ├── tonearm.svg         NEW — tonearm + cartridge
│   │   └── vu-meter.svg        NEW — VU meter face with needle
│   └── vendor/
│       ├── htmx.min.js         (existing)
│       ├── alpine.min.js       (existing)
│       └── gsap.min.js         NEW — GSAP 3.12.x core (no plugins) ~30 KB
├── styles/input.css            UPDATE — remove most of the consumer palette; deck.css supersedes
└── tailwind.config.js          UPDATE — content paths still scan templates; remove unused color tokens
```

### Why GSAP
The deck uses **orchestrated multi-element timelines** (door slides, then cassette materializes, then label types out, then door closes) that are painful to chain in raw CSS. GSAP's `timeline()` is purpose-built for this. ~30 KB gzipped, vendored locally (no CDN), respects CSP nonce. Pure-CSS alternative was considered and rejected for the deck-flip + label-typing sequences.

### State machine (Alpine)
```js
// in deck.js
{
  mode: 'tape',           // 'tape' | 'vinyl'
  status: 'ready',        // 'ready' | 'load' | 'rec' | 'done' | 'err'
  jobId: null,
  videoTitle: '',
  thumbnail: '',
  errorCategory: null,
  counter: '0:00',
  shelf: [],              // array of completed cassettes
  soundOn: false,
  reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  init() { /* preload audio, restore localStorage */ },
  fetch(url) { /* htmx-driven POST, then transition to load */ },
  rec() { /* GSAP timeline, then htmx download POST */ },
  cancel() { /* sendBeacon */ },
  // ... event handlers for htmx swaps that drive animation triggers
}
```

The Alpine component listens for `htmx:afterSwap` events on the cassette window. When the swap brings a new card status, the component runs the matching GSAP timeline.

### htmx integration
- Existing endpoints unchanged: `/api/info-card`, `/api/download-card`, `/api/status-card/<id>`, `/api/job/<id>/cancel`
- Existing polling pattern unchanged: card has `hx-get="/api/status-card/{job_id}" hx-trigger="every 1s" hx-swap="outerHTML"`
- The fragment now renders inside the deck's cassette window (or vinyl label) — so the partial is a small bundle of `data-` attributes that the Alpine component reads, not a fully styled card
- The `card.html` partial becomes a thin data carrier: `<div data-card data-status="..." data-title="..." data-thumbnail="..." data-job-id="..." data-filename="...">` — Alpine reacts to `data-status` changes and runs animations

### Reduced motion fallback
- All `transform` and rotation animations replaced with `opacity` fades
- Deck still looks like a deck (visual aesthetic preserved); just no spinning reels, no door slides, no flip
- Implementation: `[data-reduced-motion="true"]` class on `<html>` toggled in deck.js, deck.css has reduced-motion overrides under `:where([data-reduced-motion="true"])`

## Endpoints (unchanged)

No backend changes. The 4 HTML-fragment endpoints from Phase 1 are reused. The `card.html` partial is rewritten to emit deck-friendly data attributes instead of a Tailwind card.

## Testing

### Existing tests
All 63 pass unchanged. Verified by running `python -m pytest -v` after the rewrite.

### Updated test
`tests/test_endpoints.py::test_argument_injection_url_rejected_card` currently asserts `b"unsupported" in r.data.lower() or b"not supported" in r.data.lower()`. The new `card.html` will emit something like `<div data-card data-status="error" data-category="unsupported_url">`. The test's substring check still passes (`unsupported_url` contains `unsupported`). Verify after rewrite; if needed, refine to assert on the `data-status="error"` attribute presence.

### New tests (smoke)
- `tests/test_endpoints.py::test_card_partial_emits_data_attributes` — `/api/info-card` with a valid URL returns HTML containing `data-status="ready"`, `data-title=`, `data-job-id=` (or empty title for ready-before-job).
- `tests/test_endpoints.py::test_index_renders_with_deck_assets` — `/` returns HTML referencing `static/css/deck.css` and `static/js/deck.js`.

### Manual / non-automated
- 5-second screen-record on desktop showing: paste URL → cassette loads with title → REC → reels spin → done → eject. Should be visually compelling out of context.
- Same on mobile portrait (devtools 375px) — confirm deck stays usable, buttons ≥ 44px.
- `prefers-reduced-motion: reduce` (devtools setting) — confirm deck renders without spinning reels or door animation.
- Sound on (toggle) → confirm clunk on door open, click on REC, chime on done.

## Acceptance criteria

1. `python -m pytest` is green (existing 63 + 2 new smoke tests).
2. Page at `/` renders the cassette deck full-bleed with no warm-coral / consumer-friendly UI visible.
3. Paste a working URL → cassette loads with title typed in Permanent Marker → REC → reels spin → cassette ejects with "DONE" — entire sequence is **smooth, 60fps, screen-record-worthy** on a modern Mac.
4. MP3 toggle triggers the deck-to-turntable flip animation; vinyl mode works end-to-end.
5. Sound toggle (off by default) gates all audio; persists in localStorage.
6. Footer attribution line is removed from the page (LICENSE + README still credit Avery Gan).
7. `prefers-reduced-motion: reduce` disables all rotation/slide animations; deck still functional.
8. CSP unchanged from Phase 1: `script-src 'self' 'nonce-...'`; no `'unsafe-inline'`. The new `deck.js` is loaded as `<script nonce="..." src="...">`; the GSAP vendor file likewise.
9. Mobile portrait at 375px: deck adapts; tap targets ≥ 44px.
10. Lighthouse mobile Performance ≥ 90 with all the new assets (deck.css ≤ 20 KB minified, deck.js ≤ 15 KB minified, GSAP 30 KB, ~30 KB SVG total, 80 KB sounds — only loaded when sound is toggled on).

## Risks & open questions

- **VU needle realism:** we don't have real bytes/sec from yt-dlp in the current pipeline — meters are procedural / "fake but plausible". Documented; acceptable for the visual effect; could be wired to real progress in Phase 3 if yt-dlp's `--newline --progress-template` is parsed by `runner.run_download`.
- **Sound licensing:** all WAV samples sourced from CC0 / public-domain libraries (freesound.org with CC0 filter), confirmed before commit. If we can't find suitable CC0 samples, fall back to procedural Web Audio (oscillator + noise). Documented as a fallback path.
- **GSAP licensing:** core GSAP 3.x is MIT-equivalent for use, attribution not required for our use case (we're not selling or rebranding GSAP). Confirmed before committing the vendor file.
- **Permanent Marker font visual fidelity:** Permanent Marker is a real Google font that looks "marker-like" but lacks the very-handwritten variation of a true marker. Acceptable for Phase 2; could swap to a more characterful free font (Caveat, Kalam) if desired.
- **Mobile turntable animation:** rotating a turntable on a small screen is busy. Confirm visual on real device before sign-off; might suppress the flip on ≤640px and just do a faster fade.
- **Walkman vs home-stereo decision:** Walkman aesthetic (early-80s portable) is also viable, smaller and "cuter". Going with the home-stereo deck because it has more detail to record (multiple buttons, VU meters, larger surface). Open to reconsidering if first-pass feels too maximalist.

## Out-of-scope clarifications

- We are not adding **Stripe-style hero gradient backgrounds**, **Spline 3D embeds**, or **custom-cursor magnetic effects** — those would dilute the singular "tape deck" identity.
- We are not adding **a download history / library page** beyond the inline shelf.
- We are not adding **PWA + Android APK** in this phase (still deferred to Phase 3 — but the redesign is PWA-friendly, so when we get there, manifest + service worker drop in cleanly).
- We are not changing **routes, JSON shapes, env vars, or test infrastructure**.
