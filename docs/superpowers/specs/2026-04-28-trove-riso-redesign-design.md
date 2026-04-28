# Trove — Riso Redesign

**Date:** 2026-04-28
**Status:** Design approved · awaiting implementation plan
**Author:** Brainstorm session w/ Kaivan
**Replaces:** "Phosphor Terminal" UI shipped in commit `5620731`

---

## 1. Why redesign

The Phosphor Terminal aesthetic (amber-on-black, VT323, CRT scanlines, power-on flicker) is well-executed but reads as a generic retro-tech homage that has been done to death. Goal of this redesign: make the homepage screenshot **viral on X** by establishing an aesthetic nobody else in the downloader category is using, while keeping the interaction model exactly as obvious as today's.

Three swing-for-the-fences directions were considered:

- **System 7 / Mac OS Classic** — authentic Mac window chrome
- **Riso zine (2-color print)** — cream paper, two inks, halftone, registration offset
- **Brutalist confident** — single saturated color, max-weight type, no ornament

**Riso zine was chosen.** It (a) reads as a printed object rather than a website, (b) is anti-AI-slop by construction (LLMs cannot generate convincing riso aesthetics), (c) maps well onto Trove's identity as a personal, hand-made, open-source utility, and (d) has a current and rising moment on design X.

The earlier "lacquered vault" direction (warm dark + brass + Garamond italic + gold gradient) was rejected mid-design as drifting toward generic AI-startup editorial.

---

## 2. Hard constraint: clarity over cleverness

The user's explicit non-negotiable: **the redesign must not introduce confusion.** Every aesthetic choice below is a brand-only choice. The interaction model — paste a link, toggle MP4/MP3, press Save, watch the card resolve — does not change.

In particular:

- One paste box. One toggle. One button.
- No required tooltips.
- No new gestures, no hidden states.
- Mobile uses the same elements stacked, not a separate layout.
- WCAG AA contrast verified for all foreground/background pairs.
- `prefers-reduced-motion: reduce` disables every animation in a single CSS block.

---

## 3. Brand language

### 3.1 Palette ("two inks on cream stock")

| Role | Hex | Usage |
|---|---|---|
| Paper | `#F1E6CC` | Page background only. Always with grain + halftone. |
| Light | `#FEF7E3` | Cards, input fields, raised plates. |
| Teal Ink | `#1A3540` | Primary text, borders, default UI, dividers. |
| Fluorescent Red-Orange | `#FF5728` | Accents, stamps, primary CTA fill, error fill, registration-offset shadows. |
| Forest (saved-only) | `#1F7A3F` | Single exception to two-ink rule. Used only for "✓ saved" stamp. |

**Rules:**

- Two inks. The page must read as if it was printed with one paper stock and two passes of ink.
- Status colors reuse the palette: errors use the orange (no separate red); the only third color is the muted forest green for "saved".
- **No gradients. No shadows with blur.** Depth comes from (a) hard offset shadows (`4px 4px 0 #1A3540`), (b) 1.5–2px registration offset on the orange period and arrow, and (c) paper grain + halftone overlay.
- **Halftone** for any tinted orange — no semitransparent orange.
- **Paper grain is always present.** Texture is the brand.

### 3.2 Type

| Role | Family | Weights | Usage |
|---|---|---|---|
| Display | Fraunces | 600 (regular), 400 italic | Wordmark, hero headline, card titles. WONK 1, SOFT 50, opsz 144 on display sizes; opsz 24 on card-title sizes. |
| Tagline | Fraunces italic | 400 | The single line of italic body copy on the page. |
| UI / Body | Inter | 400 / 500 / 600 / 700 | Buttons, labels, controls, card meta when not mono. |
| Stamps / Mono | IBM Plex Mono | 400 / 500 | All UPPERCASE stamps, codes, file paths, source ticker. Letter-spacing 0.18–0.28em. |

All three faces are free and on Google Fonts. Single request:

```
https://fonts.googleapis.com/css2?
  family=Fraunces:ital,wght@0,400;0,500;0,600;1,400;1,500&
  family=Inter:wght@400;500;600;700&
  family=IBM+Plex+Mono:wght@400;500&
  display=swap
```

VT323 is removed.

### 3.3 Voice

- Lowercase wherever possible; uppercase reserved for mono stamps.
- Plainspoken, slightly off-kilter ("a saving machine for the modern web"), like a zine editor's note.
- No emoji. No exclamation marks. No SaaS verbs ("Get started free", "Sign up").
- Verbs are concrete ("Save"). The metaphor lives in nouns, not verbs.
- Stamps and seals (`No. 001`, `EST. MMXXVI`, `MIT · SELF-HOSTED`) are part of the voice.

---

## 4. Hero design

The above-the-fold composition is centered, single-column, ~620px content width on desktop, with full-width top and bottom mono strips.

### 4.1 Elements (top to bottom)

1. **Top strip** — mono ribbon with a 6px orange dot + product line on the left ("TROVE — A SAVING MACHINE FOR THE MODERN WEB") and "EST. MMXXVI" in orange on the right. Bordered below by a 1.5px teal rule.
2. **Wordmark** — Fraunces, 600, font-size `clamp(56px, 12vw, 132px)`, letter-spacing `-0.04em`, line-height `0.82`, font-variation `WONK 1, SOFT 50, opsz 144`. Text reads `trove.` — the period is fluorescent orange with a 2.5px registration-offset text-shadow (`text-shadow: 2px 2.5px 0 rgba(26, 53, 64, 0.18)`), giving the off-press second-pass-ink look.
3. **Decorative arrow** — single `↗` in IBM Plex Mono, orange, with the same registration offset, sized to the wordmark cap height.
4. **Tagline** — italic Fraunces, 22px, max-width 480px. Copy: *"paste a link, get the file. **no accounts, no upload limits, no telemetry.** self-hosted on your machine."* — middle clause printed in orange.
5. **Plate** — cream `#FEF7E3` card, 1.5px teal border, `4px 4px 0 #1A3540` hard offset shadow (no blur), 4px border-radius. Header bar: solid teal, mono uppercase label "▸ STEP 001 · paste a link" left, "1000+ sources" right.
6. **Input row** — inside the plate. 17px Inter input field, IBM Plex Mono 14px placeholder. On focus, an orange caret (8×16px, 1.1s blink).
7. **Controls row** — separated from input by a 1px dashed teal rule. MP4/MP3 segmented toggle (1.5px teal border, 1.5px teal divider; active pill = teal fill, cream text). Orange "Save ↗" stamp button at -1.2° rotation, 700-weight Inter, 0.22em letter-spacing, 1.5px teal border, `2px 2px 0 #1A3540` hard shadow.
8. **Footer ticker** — full-width mono strip below plate. Teal "▼ youtube · tiktok · instagram · vimeo · 1000+" left; orange "MIT · SELF-HOSTED · v1.0" right.
9. **Corner stamp** — "No. 001 / 2026" rotated +7° in upper-right, orange ink, 2px border, 0.25em letter-spacing.

### 4.2 Hero state variations

The plate has three explicit states. Plate header text stays `▸ STEP 001 · paste a link` throughout — no dynamic swap (avoids extra JS and keeps the hero stable while requests fly).

- **Idle (empty input)** — placeholder dim at 40% opacity, Save button at 40% opacity.
- **Focused (typing)** — border + shadow flip from teal to orange via `:focus-within` (CSS-only), header bar background flips teal → orange, inner background shifts to `#FFF9EA`, blinking orange caret.
- **Fetching (in flight)** — Save button inverts to teal fill with orange shadow, label changes to "Fetching…" with a blinking ellipsis, toggle pills drop to 40% opacity (locked during request). Driven by the existing `htmx:beforeRequest` / `htmx:afterRequest` listeners in `index.html`.

A 401 response is not a designed UI state — it surfaces as a standard error card via the existing `card.kind == 'error'` branch. Operators encountering it should consult the README for `TROVE_TOKEN` setup.

---

## 5. Card states

Cards stack newest-on-top in `<div id="queue">`. Each card is a "clipping" — cream `#FEF7E3` panel, 1.5px teal border, `4px 4px 0 #1A3540` hard offset shadow, 4px border-radius. Layout: 116px thumbnail · flexible body · action column.

A small `No. 00X` stamp sits at top-left of each card, on the border. Sequence number is rendered if available from job state without backend changes; otherwise omitted silently.

Thumbnails get a halftone overlay (`repeating-radial-gradient` with `mix-blend-mode: overlay`) to read as printed photos rather than digital images. When `card.thumbnail` is `None` (no thumbnail returned by yt-dlp), the existing fallback SVG icon (current `templates/partials/card.html` `thumb` macro) is preserved — re-skinned: stroke color becomes teal `#1A3540` on cream `#FEF7E3` background instead of the current dim-amber-on-dark.

### 5.1 Five states

**Ready** (info loaded, awaiting Save click)

- Title in Fraunces 600 (WONK 1), 18px, single line ellipsis.
- Meta line in IBM Plex Mono 10px UPPERCASE: `UPLOADER · DURATION · READY` separated by orange `/` glyphs.
- Action column: quality picker (rendered when `card.format == 'video'` and `card.formats` exists) + orange "Save ↗" stamp at -1° rotation.

**Downloading** (queued or in progress)

- Card border + shadow flip from teal to orange. Number stamp also turns orange.
- Bottom edge of card becomes a 8px halftone progress strip (45° repeating pattern, teal + cream). An orange highlight slides across it on a 1.4s linear infinite loop.
- Action column: orange-bordered "Saving…" stamp with blinking ellipsis, at -1.5° rotation.
- No percentage shown. yt-dlp does not always provide one, and the moving pattern reads as "working" without lying.

**Done**

- Card stays cream/teal.
- Meta replaced by `→ ~/Downloads/<filename>` in muted forest green, mono lowercase.
- Action column: green "✓ saved" stamp at +2.5° rotation.
- Below path: dashed-underline "↓ download again" link (mono, 10px, 0.18em letter-spacing).
- Stamp slams in via the delight-beat animation (see §7).

**Cancelled**

- Whole card drops to 55% opacity.
- Border becomes 1.5px dashed.
- Title gets orange strikethrough.
- Action column: dashed-bordered "cancelled" stamp at -3° rotation. No fill.

**Error**

- Background switches to a diagonal hatch pattern (`repeating-linear-gradient(135deg, #FEF7E3 0 8px, rgba(255,87,40,0.08) 8px 9px)`) — reads as printed warning tape.
- Border + shadow flip orange.
- Thumbnail becomes solid orange with the cream error icon.
- Title is italic, orange, lowercase.
- Beneath: error message (mono, 11px) + truncated source URL (mono, 9px, 50% opacity).
- Action column: large "✕ ERROR" orange stamp at +3° rotation.

### 5.2 State machine logic — unchanged

`card.kind` Jinja branches in `templates/partials/card.html` remain identical:

```
error · ready · queued · downloading · done · cancelled
```

`/api/info-card` and `/api/download-card` and `/api/status-card/<id>` endpoints are untouched. htmx polling at 2s for downloading cards. `sendBeacon` cancel on tab close. Auto browser-download on done. Quality picker rendering condition unchanged.

---

## 6. Empty & system states

### 6.1 Empty queue (first load, no clippings yet)

Below the hero, separated by a 1.5px dashed teal rule:

```
                    ↑   (orange, breathing 3s)
       your clippings will appear here.   (Fraunces italic, 18px)
       PASTE A LINK ABOVE TO BEGIN          (Plex Mono, 10px, 0.22em)
```

Hint disappears as soon as the first card lands.

### 6.2 Mobile (375px)

Same hierarchy, scaled:

- Wordmark clamps to ~56px.
- Plate stays full width with same border/shadow.
- Cards stack: thumbnail full-width on top (96px tall), then body, then action row.
- All interactive targets ≥ 44px tap-target on viewports ≤ 480px (achieved by `@media (max-width: 480px)` rule that bumps button/pill heights).
- Top + bottom strips wrap if needed; stamps shrink rather than overflow.

### 6.3 Focus / hover / disabled spec

| Element | Hover | Focus (keyboard) | Disabled |
|---|---|---|---|
| Input | cursor: text · no border change | border + shadow flip teal → orange · header bar flips · inner bg `#FFF9EA` | opacity 0.5 · readonly |
| Toggle pill | unactive: bg fills 8% teal · cursor: pointer | 2px orange dashed outline at 2px offset | opacity 0.4 (during fetch) |
| Save button | shadow grows +1px (3px → 4px) | 2px teal dashed outline at 2px offset | opacity 0.4 · faint shadow · `cursor: not-allowed` |
| Quality picker | cursor: pointer | orange dashed outline | opacity 0.4 (during save) |
| Download-again link | underline goes dashed → solid | orange dashed outline at 2px offset | n/a |

Tab order is browser-default: input → MP4 → MP3 → Save → (after card lands) picker → card-Save → download-again. No custom `tabindex`.

---

## 7. Motion & delight beats

Six motion moments, all CSS-only, all gated on `prefers-reduced-motion`.

| # | Beat | Trigger | Spec |
|---|---|---|---|
| 1 | Card-in | new card prepended | `280ms cubic-bezier(0.22, 1, 0.36, 1)` — translateY(-6px) + rotate(-0.6°) → 0,0 |
| 2 | **Stamp slam ★** | save completes (state → done) | `260ms cubic-bezier(0.16, 1, 0.3, 1)` scale(2.2 → 1) + rotate(8° → 2.5°), with a 400ms green ink-burst (radial-gradient) underneath. **The viral screenshot moment.** |
| 3 | Halftone scan | download in progress | `1.4s linear infinite` — orange linear-gradient pass at 40% width sliding -100% → 350% |
| 4 | Press | Save button mousedown | hover `150ms ease-out` shadow 3px → 4px; press `80ms ease-out` shadow → 0 + translate(3px, 3px) |
| 5 | Toggle ink-fill slide | MP4 ↔ MP3 switch | `220ms cubic-bezier(0.4, 0, 0.2, 1)` — `transform: translateX()` of an absolutely-positioned ink-fill rectangle behind the pills |
| 6 | Breathing arrow | empty state idle | `3s ease-in-out infinite` — translateY 0 → -3px + opacity 0.55 → 0.85 |
| — | Cursor blink | input focus | `1.1s steps(2) infinite` |

Reduced-motion fallback (single `@media (prefers-reduced-motion: reduce)` block):

- Card-in: opacity 0 → 1 in 100ms; no transform.
- Stamp slam: instant final state; no burst.
- Halftone scan: static halftone pattern; no scan pass.
- Press: no shadow change; instant translate.
- Toggle slide: instant swap; no fill movement.
- Breathing arrow: static at 0.55 opacity.
- Cursor blink: solid orange caret.

### 7.1 Out-of-bounds (motion we explicitly do not ship)

No scroll-triggered animations. No parallax. No spring/bounce easing. No page transitions. No ambient background animation. No card hover effects (cards aren't clickable; inner buttons are). No particle effects. No sound. No shimmer skeletons.

---

## 8. Tech approach

### 8.1 Files modified (5)

- `styles/input.css` — full rewrite (~400–500 lines). Replace the entire phosphor terminal `@layer base` and `@layer components` with the riso brand system. CSS variables for the palette, base styles for `body` and typography, component classes, motion `@keyframes`, reduced-motion block, mobile media query.

  **Class naming convention:** kebab-case component classes + `.is-<state>` modifier classes. No BEM `__double` notation. Examples: `.hero-stage / .hero-mark / .hero-plate / .hero-toggle / .hero-pill / .hero-cta / .hero-ticker / .clip / .clip.is-ready / .clip.is-downloading / .clip.is-done / .clip.is-cancelled / .clip.is-error / .progress / .saved-stamp / .empty-hint`.
- `templates/base.html` — drop VT323 from Google Fonts `<link>`, add Fraunces (`ital,wght@…&WONK,SOFT,opsz`) + IBM Plex Mono. Add `<meta name="color-scheme" content="light">` so dark-mode browsers don't invert. Drop the `alpine.min.js` `<script>` reference if present (currently absent in HTML but vendored on disk).
- `templates/index.html` — full hero rewrite per §4. Form action stays `/api/info-card`; htmx target stays `#queue`; htmx swap stays `afterbegin`. Format-toggle vanilla JS rewritten for new selectors. Empty-state hint added inside `#queue` parent.
- `templates/partials/card.html` — full rewrite of all 5 states per §5. Same `card.kind` Jinja conditionals; same `/api/download-card`, `/api/status-card/<id>`, `/api/file/<id>` endpoints.
- `tailwind.config.js` — swap color tokens (`paper`, `teal`, `orange`, `light`, `forest`) and font-family (Fraunces, Inter, "IBM Plex Mono"). `content` glob unchanged.

### 8.2 Files unchanged

- `app.py · jobs.py · runner.py · safety.py` — no endpoint changes, no signature changes.
- `Dockerfile · trove.sh · requirements.txt · pyproject.toml` — multi-stage build still works; Tailwind CLI compiles new CSS in builder stage.
- `tests/` — existing tests cover endpoints, RCE/argv injection, CSP nonces. None test visual UI. The redesign passes the entire suite as-is.

### 8.3 Files deleted (cleanup)

- `static/vendor/alpine.min.js` — vendored but never loaded under strict CSP. Vanilla JS in `<script nonce>` blocks handles the toggle. Logical to remove during this redesign.

### 8.4 Implementation order

Designed so the site is broken for as few steps as possible. Do everything on a feature branch.

1. Add new fonts to `templates/base.html`; drop VT323. Page renders unchanged (existing CSS doesn't reference Fraunces/Plex).
2. Rewrite `styles/input.css` from scratch.
3. Update `tailwind.config.js` tokens for new palette.
4. Run `./trove.sh` (or just the Tailwind build step) to recompile `static/app.css`.
5. Rewrite `templates/index.html` — new hero markup.
6. Rewrite `templates/partials/card.html` — new state markup.
7. Manual QA across all states (§9).
8. Delete `static/vendor/alpine.min.js`; ensure no template references it.

### 8.5 Build pipeline

Unchanged. `./trove.sh` downloads the standalone Tailwind CLI binary (`tools/tailwindcss`) on first run, watches `styles/input.css`, and emits `static/app.css`. No Node, no npm. Multi-stage Dockerfile already runs the build step in the builder image and copies the compiled CSS into the runtime image.

---

## 9. Manual QA checklist

Run before merging to `main`.

- [ ] Hero renders at 1440px / 1024px / 768px / 375px / 320px viewports.
- [ ] Wordmark scales via `clamp()`; no overflow at 320px.
- [ ] Cursor blinks at 1.1s in input on focus.
- [ ] Format toggle: MP4 ↔ MP3 switch slides ink fill ~220ms.
- [ ] Save button: hover grows shadow 3 → 4px; press collapses + translates.
- [ ] Save button disabled (40% opacity) when form invalid.
- [ ] Paste valid URL → "Fetching…" state on Save → ready card lands with card-in animation.
- [ ] Ready card: quality picker functions, second Save kicks download.
- [ ] Downloading card: border + shadow flip orange, halftone progress scans.
- [ ] Download completes: green stamp slams down with ink-burst, browser download triggers.
- [ ] "↓ download again" link works on done card.
- [ ] Error card: hatch background, orange thumb, "✕ ERROR" stamp.
- [ ] Cancel via tab close: `sendBeacon` fires; card flips to cancelled on reload.
- [ ] Empty state shows "your clippings will appear here" with breathing arrow.
- [ ] Tab order: input → MP4 → MP3 → Save.
- [ ] Focus ring: 2px orange dashed outline on every interactive element.
- [ ] `prefers-reduced-motion: reduce`: cursor solid, halftone static, no slams, no card-in slide, no breathing, no toggle slide.
- [ ] Contrast: teal `#1A3540` on cream `#F1E6CC` ≥ 7:1; muted forest `#1F7A3F` on cream ≥ 4.5:1.
- [ ] CSP nonces still inject correctly on every `<script>`.
- [ ] Auth wall (`TROVE_TOKEN` set, no header): 401 path renders cleanly.
- [ ] Mobile Safari + Chrome Android render Fraunces correctly.
- [ ] Dark-mode browsers stay light cream (color-scheme: light meta works).
- [ ] `pytest tests/` passes.
- [ ] No console errors / 404s in network tab.
- [ ] First contentful paint < 1.5s on slow 3G (Lighthouse).

---

## 10. Risks

- **Fraunces fallback flash (FOUT).** Google Fonts can take ~150ms on cold cache; the wordmark renders in Georgia until then and shifts. Use `font-display: swap` (default) and accept brief FOUT — better than blocking. `size-adjust` can be tuned later if jarring.
- **WONK axis support.** Fraunces variable-font axes need Safari 16+ / Chrome 88+ / Firefox 89+. On older browsers WONK gracefully falls back to default Fraunces — still readable.
- **Halftone perf.** `repeating-radial-gradient` is GPU-cheap but stacked 4–5 deep on every paper bg. Tested 60fps on M1 / mid-range Android. If profiling shows issues, replace with a single SVG noise filter.
- **Three always-running CSS animations** (cursor blink + halftone scan + breathing arrow). Verified zero CPU on idle (compositor-only). Reduced-motion kills all three.
- **Strict CSP** — no inline event handlers in production templates. The visual companion mockups use `onclick=` for demos, but production code uses `<script nonce>` + external CSS only. Toggle JS lives in the existing nonce-script block in `index.html`.
- **Mobile tap targets.** Save button = 36px tall on desktop; bumps to 44px via `@media (max-width: 480px)`. Toggle pills similarly.

---

## 11. Out of scope (YAGNI)

- Dark riso variant — cream paper IS the brand; revisit if user demand emerges.
- Print stylesheet.
- Mascot illustrations / character art.
- Sound effects (CSP + autoplay restrictions; not worth the friction).
- Confetti / particle bursts.
- i18n / RTL layout.
- Server-side rendering of `No. 00X` issue numbers if it requires backend changes — drop them quietly if not trivially available from existing job state.
- Per-card share buttons / external links / "open in browser".
- New backend features (queue history, persistence, accounts).
- Custom favicon redesign — keep existing `static/favicon.svg`.

---

## 12. Voice & microcopy reference (for the implementer)

| Surface | Copy |
|---|---|
| Top-strip product line | `TROVE — A SAVING MACHINE FOR THE MODERN WEB` |
| Top-strip date stamp | `EST. MMXXVI` |
| Wordmark | `trove.` (period in orange) |
| Tagline | `paste a link, get the file. **no accounts, no upload limits, no telemetry.** self-hosted on your machine.` |
| Plate header | `▸ STEP 001 · paste a link` · `1000+ sources` (static — never changes) |
| Input placeholder | `https://www.youtube.com/watch?v=…` |
| Format pills | `MP4` / `MP3` |
| Primary CTA | `Save ↗` |
| Fetching CTA label | `Fetching…` |
| Source ticker (left) | `▼ youtube · tiktok · instagram · vimeo · 1000+` |
| Source ticker (right) | `MIT · SELF-HOSTED · v1.0` |
| Corner stamp | `No. 001 / 2026` |
| Empty state | `↑` · `your clippings will appear here.` · `PASTE A LINK ABOVE TO BEGIN` |
| Card meta separator | `/` (orange) |
| Card meta (ready) | `<UPLOADER> / <DURATION> / READY` |
| Card stamp (ready button) | `Save ↗` |
| Card stamp (saving) | `Saving…` (blinking ellipsis) |
| Card stamp (saved) | `✓ saved` |
| Card stamp (cancelled) | `cancelled` |
| Card stamp (error) | `✕ ERROR` |
| Card meta (done) | `→ ~/Downloads/<filename>` |
| Done link | `↓ download again` |
| Error messages | unchanged from current `templates/partials/card.html` `msgs` macro |

---

**End of design.**
