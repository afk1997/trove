# Trove Tape Deck Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Trove's current consumer-friendly UI with a full-bleed late-1970s home-stereo cassette deck (and turntable for MP3 mode), backed by GSAP-orchestrated animations and an opt-in procedural Web Audio sound layer. Backend untouched.

**Architecture:** Same Flask + htmx + Alpine + Tailwind (utility-light) stack. New CSS layer (`static/css/deck.css`) replaces consumer styling. New JS (`static/js/deck.js`) orchestrates state, animations, and sound via Alpine + GSAP + Web Audio. Templates rewrite around a deck DOM with the htmx fragment becoming a data-attribute carrier the Alpine component reacts to.

**Tech Stack:** Flask, htmx 2.0.4, Alpine 3.14.1, Tailwind CSS v4 standalone CLI, GSAP 3.12.5 (vendored core, ~30 KB), Web Audio API (procedural — no audio files), Google Fonts (Anton + Permanent Marker + VT323).

**Working directory:** `/Users/kaivan108icloud.com/Downloads/trove/`. Branch: `redesign/tape-deck`. Spec: `docs/superpowers/specs/2026-04-28-trove-tape-deck-redesign.md`.

**One spec deviation:** the spec lists 6 WAV samples in `static/sounds/`. This plan uses **procedural Web Audio synthesis** (oscillators + noise + envelopes) instead — no audio files, no CC0 licensing search, smaller deploy. The spec's risk section already names this as the documented fallback. If procedural sounds feel insufficient at the smoke stage, swap to samples in a follow-up.

---

## File map

```
trove/
├── static/
│   ├── vendor/
│   │   └── gsap.min.js                NEW — vendored GSAP 3.12.5 core
│   ├── img/
│   │   ├── deck-grain.svg             NEW — wood-grain noise pattern
│   │   ├── deck-scratches.svg         NEW — brushed-aluminum scratches
│   │   ├── cassette-shell.svg         NEW — cassette base + spine
│   │   ├── reel.svg                   NEW — single hub (used twice)
│   │   ├── vinyl.svg                  NEW — record + grooves + label slot
│   │   ├── tonearm.svg                NEW — arm + cartridge
│   │   └── vu-meter.svg               NEW — meter face + needle
│   ├── css/
│   │   └── deck.css                   NEW — all deck visuals + animations
│   └── js/
│       └── deck.js                    NEW — Alpine state, GSAP, Web Audio
├── templates/
│   ├── base.html                      REWRITE — drop footer, mount new assets
│   ├── index.html                     REWRITE — deck DOM
│   └── partials/
│       ├── card.html                  REWRITE — data-attribute carrier
│       └── shelf-item.html            NEW — completed-cassette thumbnail
├── styles/input.css                   UPDATE — keep CSS reset/Tailwind layer; deck-specific tokens move to deck.css
├── tests/test_endpoints.py            UPDATE — refine error-card assertion + 2 new smoke tests
└── docs/superpowers/plans/2026-04-28-trove-tape-deck-redesign.md   (this file)
```

---

## Phase A — Vendor + SVG assets

### Task A1: Vendor GSAP

**Files:** Create `static/vendor/gsap.min.js`

- [ ] **Step 1: Download GSAP 3.12.5 core**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
curl -sSL https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js -o static/vendor/gsap.min.js
ls -la static/vendor/gsap.min.js
head -c 80 static/vendor/gsap.min.js && echo
```

Expected: ~70 KB file (or less when minified by cloudflare); first 80 chars include `/*! GSAP 3.12.5`.

- [ ] **Step 2: Commit**

```bash
git add static/vendor/gsap.min.js
git commit -m "feat(ui): vendor GSAP 3.12.5 for deck animation orchestration"
```

### Task A2: Author the 7 SVG assets

**Files:** Create the 7 files under `static/img/`. This task is a strong fit for the **frontend-design** skill — its judgment on textures and details will produce better visual fidelity than transcribing fixed SVG markup.

The implementer must produce **inline-friendly, viewBox-normalized, color-token-aware** SVGs matching these specs:

| File | viewBox | Visual requirements |
|---|---|---|
| `deck-grain.svg` | `0 0 1024 256` | Repeating wood-grain noise pattern. Warm dark brown using `feTurbulence` (baseFrequency ~0.02, type `fractalNoise`) + `feColorMatrix` to brown tint. Set as background-repeat texture. |
| `deck-scratches.svg` | `0 0 1024 64` | Subtle horizontal brushed-metal scratches via fractal noise filtered to short horizontal streaks (`feGaussianBlur stdDeviation="0.4 4"`). Used as overlay on aluminum strips. |
| `cassette-shell.svg` | `0 0 320 200` | Black plastic cassette body, slight sheen, two visible **hub holes** spaced as on real cassettes (~28% and 72% horizontally), a **paper label rectangle** between them sized for the title text, two screws in the corners, the iconic 5 small holes along the bottom edge. Uses CSS variables `--tape-shell` and `--tape-label` for fills so themes can override. |
| `reel.svg` | `0 0 64 64` | Single tape-reel hub: outer ring, 6 spokes, central pin. Designed to be rotated via CSS `transform: rotate()`. Two of these will be positioned over the `cassette-shell.svg` hub holes. |
| `vinyl.svg` | `0 0 320 320` | Black vinyl record with concentric darker grooves (use a radial-stripe pattern), a paper center label of size 30% diameter, and a single highlight glint from upper-left. Center label uses `--tape-label`. |
| `tonearm.svg` | `0 0 320 200` | Chrome tonearm pivoted at the right side, cartridge head at the left tip. The arm rotates around the pivot; provide a `<g id="arm">` group so JS can transform it. |
| `vu-meter.svg` | `0 0 200 80` | VU meter face: cream background, black tick marks, a red zone at the top end, and a single `<line id="needle">` from the bottom center pivoting to the upper region. JS will animate `transform: rotate(angle)` on the `#needle`. Provide `<text>` elements for "L" and "R" channel labels. |

The SVGs are **referenced from CSS** (as `background-image: url(...)`) for textures, and **inlined into HTML** (via Jinja `{% include 'svg/...' %}` would be nice — but Flask doesn't include SVGs by default). Instead: use them as plain `<img src>` for static elements and inline only `cassette-shell.svg`, `reel.svg`, `vinyl.svg`, `tonearm.svg`, and `vu-meter.svg` directly into `index.html` so JS can manipulate child nodes.

- [ ] **Step 1: Generate the 7 SVGs**

The implementer / frontend-design subagent should write each SVG with the constraints above. Use `<defs>` for filters, `<style>` blocks tagged with the CSP nonce (or move stroke/fill to attributes to avoid inline styles entirely).

- [ ] **Step 2: Verify all 7 exist and are valid SVG**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
ls -la static/img/
for f in static/img/*.svg; do
  python3 -c "import xml.etree.ElementTree as ET; ET.parse('$f'); print('OK $f')"
done
```

Expected: all 7 print "OK".

- [ ] **Step 3: Commit**

```bash
git add static/img/
git commit -m "feat(ui): SVG assets for cassette deck + turntable"
```

---

## Phase B — Templates

### Task B1: Rewrite base.html

**Files:** Modify `templates/base.html`

- [ ] **Step 1: Replace the entire base.html with the new shell**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{% block title %}Trove — Save things you care about{% endblock %}</title>
  <meta name="description" content="Save things you care about. Self-hosted media downloader.">
  <link rel="icon" href="{{ url_for('static', filename='favicon.svg') }}" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Permanent+Marker&family=VT323&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/deck.css') }}">
  <script nonce="{{ g.csp_nonce }}">
    // Reduced-motion class set before paint so deck.css can branch.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      document.documentElement.dataset.reducedMotion = 'true';
    }
  </script>
</head>
<body>
  {% block content %}{% endblock %}

  <script nonce="{{ g.csp_nonce }}" src="{{ url_for('static', filename='vendor/alpine.min.js') }}" defer></script>
  <script nonce="{{ g.csp_nonce }}" src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>
  <script nonce="{{ g.csp_nonce }}" src="{{ url_for('static', filename='vendor/gsap.min.js') }}"></script>
  <script nonce="{{ g.csp_nonce }}" src="{{ url_for('static', filename='js/deck.js') }}"></script>
</body>
</html>
```

Key changes from the previous version:
- No header/wordmark wrapper (deck owns full bleed)
- No footer attribution line
- Loads new `deck.css` after Tailwind's `app.css`
- Loads `gsap.min.js` between alpine and deck.js (deck.js relies on `window.gsap`)
- Reduced-motion `data-` attribute set in `<html>` before paint
- Drops the inline cancel-on-unload script (moves into `deck.js`)

- [ ] **Step 2: Smoke that the test client still renders /**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
python -c "from app import create_app; r = create_app().test_client().get('/'); print('home:', r.status_code, 'has gsap:', b'gsap.min.js' in r.data, 'has deck.css:', b'deck.css' in r.data, 'no footer attr:', b'averygan/reclip' not in r.data)"
```

Expected: `home: 200 has gsap: True has deck.css: True no footer attr: True`.

(`deck.css` and `deck.js` won't actually exist yet on disk; Flask's `url_for` only generates the URL, the test request doesn't fetch them. The smoke test just verifies the template renders.)

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "feat(ui): base.html shell for tape deck (drops footer attribution, mounts deck assets + GSAP)"
```

### Task B2: Rewrite index.html, card.html, and add shelf-item.html

**Files:** Modify `templates/index.html`, `templates/partials/card.html`. Create `templates/partials/shelf-item.html`.

The index page is the deck DOM. The card partial becomes a thin **data-attribute carrier** the Alpine component reads. The shelf-item is one entry in the completed-jobs row below the deck.

- [ ] **Step 1: Rewrite templates/index.html**

```html
{% extends "base.html" %}

{% block content %}
<div
  id="deck"
  x-data="trove.deck()"
  x-init="init()"
  data-mode="tape"
  data-status="ready"
  class="deck"
>
  <!-- Top corner: sound toggle -->
  <button
    type="button"
    class="deck-sound-toggle"
    @click="toggleSound()"
    :aria-label="soundOn ? 'Mute sound' : 'Enable sound'"
    aria-live="polite"
  >
    <span x-show="!soundOn" aria-hidden="true">🔇</span>
    <span x-show="soundOn" aria-hidden="true">🔊</span>
  </button>

  <!-- Wordmark embossed in aluminum -->
  <div class="deck-wordmark" aria-label="Trove">TROVE</div>

  <!-- Cassette window (the visual heart) -->
  <div class="deck-window" :class="{ 'is-loading': status === 'load', 'is-recording': status === 'rec', 'is-done': status === 'done' }">
    <!-- Cassette layer (visible in tape mode) -->
    <div class="cassette" x-show="mode === 'tape'" x-cloak>
      {% include 'svg/cassette-shell.svg' ignore missing %}
      <!-- two reels positioned over hub holes; rotation tied to a CSS var via JS -->
      <div class="reel reel-left" data-reel><img src="{{ url_for('static', filename='img/reel.svg') }}" alt=""></div>
      <div class="reel reel-right" data-reel><img src="{{ url_for('static', filename='img/reel.svg') }}" alt=""></div>
      <div class="cassette-label" data-cassette-label>
        <span x-text="videoTitle"></span>
      </div>
    </div>
    <!-- Turntable layer (visible in vinyl mode) -->
    <div class="turntable" x-show="mode === 'vinyl'" x-cloak>
      <div class="vinyl" data-vinyl>
        <img src="{{ url_for('static', filename='img/vinyl.svg') }}" alt="">
      </div>
      <div class="tonearm" data-tonearm>
        <img src="{{ url_for('static', filename='img/tonearm.svg') }}" alt="">
      </div>
    </div>
  </div>

  <!-- Right of window: digital display + VU meters -->
  <div class="deck-readout">
    <div class="digital" :class="{ 'is-rec': status === 'rec', 'is-err': status === 'err' }">
      <span x-show="status === 'ready'">READY</span>
      <span x-show="status === 'load'">LOAD ✓</span>
      <span x-show="status === 'rec'">REC ▶ <span x-text="counter"></span></span>
      <span x-show="status === 'done'">DONE</span>
      <span x-show="status === 'err'">ERR</span>
    </div>
    <div class="vu-meters">
      <div class="vu" data-vu="L"><img src="{{ url_for('static', filename='img/vu-meter.svg') }}" alt="VU left"></div>
      <div class="vu" data-vu="R"><img src="{{ url_for('static', filename='img/vu-meter.svg') }}" alt="VU right"></div>
    </div>
  </div>

  <!-- Button row -->
  <div class="deck-buttons" role="group" aria-label="Deck transport controls">
    <button type="button" class="deck-btn" disabled aria-label="Rewind">◁◁</button>
    <button type="button" class="deck-btn" @click="stop()" aria-label="Stop">◻</button>
    <button
      type="button"
      class="deck-btn deck-btn--rec"
      :class="{ 'is-pressed': status === 'rec' }"
      @click="rec()"
      :disabled="status !== 'load'"
      aria-label="Record"
    >● REC</button>
    <button type="button" class="deck-btn" disabled aria-label="Fast forward">▷▷</button>
    <button
      type="button"
      class="deck-btn"
      @click="eject()"
      :disabled="status === 'rec' || status === 'ready'"
      aria-label="Eject"
    >▲</button>
  </div>

  <!-- URL input + format toggle (the "label slot") -->
  <form
    class="deck-input"
    hx-post="/api/info-card"
    hx-target="#card-target"
    hx-swap="innerHTML"
    hx-on::before-request="$dispatch('deck:fetching')"
    hx-on::after-request="$dispatch('deck:fetched')"
  >
    <input
      name="url"
      type="text"
      placeholder="PASTE URL ON TAPE LABEL"
      class="deck-url-input"
      required
      autocomplete="off"
      autocapitalize="off"
      spellcheck="false"
    >
    <input type="hidden" name="format" :value="mode === 'vinyl' ? 'audio' : 'video'">
    <div class="deck-format-toggle" role="group" aria-label="Format">
      <button type="button" :data-active="mode === 'tape'" @click="setMode('tape')" class="toggle-btn">MP4</button>
      <button type="button" :data-active="mode === 'vinyl'" @click="setMode('vinyl')" class="toggle-btn">MP3</button>
    </div>
    <button type="submit" class="deck-btn deck-btn--load" :disabled="status === 'rec'">LOAD ▶</button>
  </form>

  <!-- htmx target for the card data carrier (hidden, read by Alpine) -->
  <div id="card-target" hidden></div>

  <!-- Shelf of completed jobs -->
  <div class="deck-shelf" :hidden="shelf.length === 0" aria-live="polite">
    <template x-for="item in shelf" :key="item.id">
      <a class="shelf-item" :href="`/api/file/${item.id}`" :download="item.filename" :title="item.title">
        <span class="shelf-thumb" :class="item.kind === 'vinyl' ? 'is-vinyl' : 'is-cassette'"></span>
        <span class="shelf-label" x-text="item.title"></span>
      </a>
    </template>
  </div>
</div>
{% endblock %}
```

Notes:
- The htmx target is `#card-target` (hidden); Alpine listens for `htmx:afterSwap` events on that node and reads the data-attributes from the swapped fragment to drive `videoTitle`, `jobId`, `status`, etc.
- `x-cloak` hides Alpine-managed sections until init runs, preventing FOUC
- Mode-toggle hidden input puts `format=audio` when in vinyl mode and `format=video` in tape mode
- The Jinja `{% include 'svg/cassette-shell.svg' ignore missing %}` is optional — if you'd rather, drop it and rely on `<img src=>` (matches the other SVGs); both work

- [ ] **Step 2: Rewrite templates/partials/card.html**

```html
{# Data-attribute carrier consumed by deck.js Alpine component. #}
{# All visuals are rendered by the deck shell — this fragment exists only to #}
{# pass server-side state into the client via htmx swap. #}
<div
  data-card
  data-status="{{ card.kind }}"
  {% if card.id %}data-job-id="{{ card.id }}"{% endif %}
  data-title="{{ card.title or '' }}"
  data-thumbnail="{{ card.thumbnail or '' }}"
  data-uploader="{{ card.uploader or '' }}"
  data-duration="{{ card.duration or '' }}"
  data-format="{{ card.format or 'video' }}"
  {% if card.filename %}data-filename="{{ card.filename }}"{% endif %}
  {% if card.category %}data-category="{{ card.category }}"{% endif %}
  {% if card.formats %}data-formats='{{ card.formats|tojson }}'{% endif %}
></div>
```

- [ ] **Step 3: Create templates/partials/shelf-item.html**

```html
{# Reserved for server-side rendering of shelf items — currently the shelf is #}
{# rendered client-side from Alpine state. Kept as a placeholder for the #}
{# Phase 3 history-page work. #}
<a class="shelf-item" href="/api/file/{{ card.id }}" download="{{ card.filename or '' }}">
  <span class="shelf-thumb {% if card.format == 'audio' %}is-vinyl{% else %}is-cassette{% endif %}"></span>
  <span class="shelf-label">{{ card.title }}</span>
</a>
```

- [ ] **Step 4: Smoke that the index renders without raising**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
python -c "from app import create_app; r = create_app().test_client().get('/'); print('home:', r.status_code, 'has deck:', b'id=\"deck\"' in r.data, 'has cassette window:', b'deck-window' in r.data, 'has button row:', b'deck-buttons' in r.data, 'no warm card class:', b'class=\"card ' not in r.data)"
```

Expected: `home: 200 has deck: True has cassette window: True has button row: True no warm card class: True`.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html templates/partials/card.html templates/partials/shelf-item.html
git commit -m "feat(ui): deck DOM (index + data-carrier card + shelf-item template)"
```

---

## Phase C — Styles (deck.css)

### Task C1: deck.css scaffold + tokens + textures

**Files:** Create `static/css/deck.css`

- [ ] **Step 1: Write the foundation layer**

```css
/* deck.css — Trove cassette deck visuals */

:root {
  --wood-base: #3d2818;
  --wood-grain: #4a2e1a;
  --aluminum: #c5c2bb;
  --aluminum-dim: #8e8b85;
  --faceplate: #1a1816;
  --led-amber: #ff9a3c;
  --led-red: #ff3c3c;
  --led-glow: 0 0 12px rgba(255, 154, 60, 0.6);
  --tape-shell: #14110f;
  --tape-label: #e8dcc4;
  --felt-green: #1f3a2a;
  --vinyl: #0a0a0a;
  --scratch: rgba(255, 255, 255, 0.04);

  --font-display: 'Anton', system-ui, sans-serif;
  --font-marker: 'Permanent Marker', cursive;
  --font-digital: 'VT323', monospace;
  --font-body: 'Inter', system-ui, sans-serif;
}

/* Reset margins; deck owns the viewport */
html, body {
  margin: 0;
  padding: 0;
  background: #0a0806;
  color: var(--aluminum);
  font-family: var(--font-body);
  min-height: 100vh;
  overflow-x: hidden;
}

[x-cloak] { display: none !important; }

/* === The deck === */
.deck {
  --deck-radius: 18px;
  position: relative;
  width: min(1200px, calc(100vw - 32px));
  margin: 32px auto;
  padding: 28px 32px 36px;
  background:
    linear-gradient(180deg, var(--wood-grain), var(--wood-base) 70%),
    url('/static/img/deck-grain.svg');
  background-blend-mode: overlay;
  background-size: cover, 1024px;
  border-radius: var(--deck-radius);
  box-shadow:
    inset 0 0 0 2px rgba(0, 0, 0, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 24px 60px rgba(0, 0, 0, 0.55);
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-rows: auto auto auto;
  grid-template-areas:
    "wordmark sound-toggle"
    "window readout"
    "buttons buttons"
    "input input"
    "shelf shelf";
  gap: 16px 24px;
}

/* Aluminum face strip behind window+readout */
.deck::before {
  content: '';
  position: absolute;
  inset: 76px 24px auto 24px;
  height: 280px;
  background:
    linear-gradient(180deg, var(--aluminum), var(--aluminum-dim)),
    url('/static/img/deck-scratches.svg');
  background-blend-mode: multiply;
  background-size: cover, 1024px 64px;
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.3);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4), inset 0 -2px 0 rgba(0, 0, 0, 0.2);
  z-index: 0;
}

/* Wordmark embossed into aluminum */
.deck-wordmark {
  grid-area: wordmark;
  font-family: var(--font-display);
  font-size: clamp(48px, 6vw, 80px);
  letter-spacing: 0.08em;
  color: rgba(0, 0, 0, 0.35);
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.4);
  z-index: 1;
}

/* Sound toggle in extreme top-right */
.deck-sound-toggle {
  grid-area: sound-toggle;
  background: transparent;
  border: 1px solid var(--aluminum-dim);
  color: var(--aluminum);
  font-size: 16px;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  cursor: pointer;
  align-self: start;
  justify-self: end;
  z-index: 1;
}
.deck-sound-toggle:hover { border-color: var(--led-amber); }
```

- [ ] **Step 2: Build CSS to confirm no syntax errors**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify
ls -la static/css/deck.css
```

(deck.css doesn't go through Tailwind — just confirm Tailwind still builds, and the file exists.)

- [ ] **Step 3: Commit**

```bash
git add static/css/deck.css
git commit -m "feat(ui): deck.css foundation — tokens, layout grid, wood + aluminum textures"
```

### Task C2: Cassette window, reels, label, digital display, VU meters

**Files:** Modify `static/css/deck.css`

- [ ] **Step 1: Append the window and readout sections**

```css
/* === Cassette window === */
.deck-window {
  grid-area: window;
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-width: 700px;
  background: rgba(0, 0, 0, 0.7);
  border-radius: 8px;
  border: 2px solid rgba(0, 0, 0, 0.5);
  box-shadow:
    inset 0 0 24px rgba(0, 0, 0, 0.6),
    inset 0 0 0 1px rgba(255, 255, 255, 0.05);
  overflow: hidden;
  z-index: 1;
}

.cassette,
.turntable {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cassette img[src*="cassette-shell"],
.cassette > svg {
  width: 75%;
  max-width: 480px;
  height: auto;
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.6));
}

/* Reels positioned over the hub holes */
.reel {
  position: absolute;
  width: 11%;
  aspect-ratio: 1;
  --reel-rotation: 0deg;
  --reel-speed: 0; /* full revolution per second; 0 = stopped */
  top: 36%;
  transform: rotate(var(--reel-rotation));
  transition: transform 0.6s ease-out;
}
.reel-left { left: 23%; }
.reel-right { left: 66%; }
.reel img { width: 100%; height: 100%; }

.deck-window.is-recording .reel {
  animation: reel-spin 1.5s linear infinite;
  animation-play-state: running;
}
@keyframes reel-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.cassette-label {
  position: absolute;
  top: 25%;
  left: 30%;
  width: 40%;
  height: 18%;
  background: var(--tape-label);
  font-family: var(--font-marker);
  font-size: clamp(12px, 1.6vw, 18px);
  color: #2a1a0a;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 4px 8px;
  border-radius: 2px;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15);
  overflow: hidden;
}
.cassette-label span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}

/* === Turntable (vinyl mode) === */
.turntable {
  background: var(--felt-green);
}
.vinyl {
  position: absolute;
  width: 70%;
  aspect-ratio: 1;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  --vinyl-rotation: 0deg;
}
.deck-window.is-recording .vinyl {
  animation: vinyl-spin 0.8s linear infinite;
}
@keyframes vinyl-spin {
  from { transform: translate(-50%, -50%) rotate(0deg); }
  to { transform: translate(-50%, -50%) rotate(360deg); }
}
.vinyl img { width: 100%; height: 100%; }

.tonearm {
  position: absolute;
  top: 8%;
  right: 4%;
  width: 35%;
  height: auto;
  transform-origin: 92% 50%;
  transform: rotate(0deg);
  transition: transform 0.6s ease-in-out;
}
.deck-window.is-recording .tonearm {
  transform: rotate(-12deg);
}

/* === Digital display + VU meters === */
.deck-readout {
  grid-area: readout;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-self: center;
  z-index: 1;
  min-width: 220px;
}

.digital {
  font-family: var(--font-digital);
  font-size: clamp(20px, 2.5vw, 28px);
  color: var(--led-amber);
  background: rgba(0, 0, 0, 0.85);
  padding: 14px 18px;
  border-radius: 4px;
  border: 1px solid rgba(0, 0, 0, 0.6);
  text-shadow: var(--led-glow);
  letter-spacing: 0.05em;
}
.digital.is-rec { color: var(--led-amber); }
.digital.is-err { color: var(--led-red); animation: blink 0.5s steps(2) infinite; }
@keyframes blink {
  to { opacity: 0.3; }
}

.vu-meters {
  display: flex;
  gap: 8px;
}
.vu {
  flex: 1;
  background: rgba(0, 0, 0, 0.4);
  padding: 6px;
  border-radius: 4px;
}
.vu img { width: 100%; height: auto; display: block; }
```

- [ ] **Step 2: Boot the server, open localhost:8899, visually confirm the deck face is recognizable**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
PORT=8899 HOST=127.0.0.1 python app.py &
SERVER_PID=$!
sleep 2
curl -s -o /dev/null -w 'home: %{http_code}\n' http://127.0.0.1:8899/
echo "(open http://127.0.0.1:8899 in browser; confirm deck shape visible)"
sleep 30  # give the implementer 30s of look time
kill $SERVER_PID 2>/dev/null || true
```

If anything looks wrong, fix it before committing.

- [ ] **Step 3: Commit**

```bash
git add static/css/deck.css
git commit -m "feat(ui): cassette window, reels, label, digital display, VU meters"
```

### Task C3: Buttons, format toggle, URL input, shelf, mobile portrait, reduced-motion

**Files:** Modify `static/css/deck.css`

- [ ] **Step 1: Append the controls + responsive + a11y sections**

```css
/* === Button row === */
.deck-buttons {
  grid-area: buttons;
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 8px;
}
.deck-btn {
  font-family: var(--font-display);
  letter-spacing: 0.08em;
  font-size: 14px;
  min-width: 72px;
  min-height: 44px;
  padding: 10px 18px;
  background:
    linear-gradient(180deg, var(--aluminum), var(--aluminum-dim)),
    url('/static/img/deck-scratches.svg');
  background-blend-mode: multiply;
  background-size: cover, 256px 32px;
  color: var(--faceplate);
  border: 1px solid rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.05s ease-out, filter 0.15s;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.5),
    inset 0 -2px 0 rgba(0, 0, 0, 0.2),
    0 2px 0 rgba(0, 0, 0, 0.4);
}
.deck-btn:hover:not(:disabled) { filter: brightness(1.06); }
.deck-btn:active:not(:disabled),
.deck-btn.is-pressed {
  transform: translateY(2px);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.3);
}
.deck-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.deck-btn--rec {
  color: white;
  background: linear-gradient(180deg, #3a3a3a, #1f1f1f);
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.6);
  position: relative;
}
.deck-btn--rec::before {
  content: '';
  position: absolute;
  width: 8px;
  height: 8px;
  background: var(--led-red);
  border-radius: 50%;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  box-shadow: 0 0 10px rgba(255, 60, 60, 0.8);
  opacity: 0.4;
}
.deck-btn--rec.is-pressed::before { opacity: 1; animation: blink 0.6s steps(2) infinite; }

/* === URL input + format toggle === */
.deck-input {
  grid-area: input;
  display: flex;
  gap: 12px;
  align-items: stretch;
  flex-wrap: wrap;
  margin-top: 12px;
}
.deck-url-input {
  flex: 1 1 280px;
  font-family: var(--font-digital);
  font-size: 18px;
  letter-spacing: 0.04em;
  background: rgba(0, 0, 0, 0.6);
  color: var(--led-amber);
  padding: 14px 18px;
  border: 1px solid rgba(0, 0, 0, 0.5);
  border-radius: 6px;
  min-height: 44px;
  text-shadow: var(--led-glow);
}
.deck-url-input::placeholder { color: rgba(255, 154, 60, 0.4); }
.deck-url-input:focus { outline: 1px solid var(--led-amber); }

.deck-format-toggle {
  display: inline-flex;
  border: 1px solid var(--aluminum-dim);
  border-radius: 6px;
  overflow: hidden;
  background: var(--faceplate);
}
.deck-format-toggle .toggle-btn {
  background: transparent;
  color: var(--aluminum-dim);
  border: 0;
  padding: 0 18px;
  min-width: 64px;
  min-height: 44px;
  font-family: var(--font-display);
  letter-spacing: 0.08em;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.deck-format-toggle .toggle-btn[data-active="true"] {
  background: var(--aluminum);
  color: var(--faceplate);
}

.deck-btn--load {
  min-width: 120px;
}

/* === Shelf === */
.deck-shelf {
  grid-area: shelf;
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding: 8px 0 4px;
  margin-top: 16px;
  scrollbar-width: thin;
}
.shelf-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: 0 0 96px;
  text-decoration: none;
  color: var(--aluminum);
}
.shelf-thumb {
  width: 96px;
  height: 64px;
  border-radius: 4px;
  background: var(--tape-shell);
  background-image: url('/static/img/cassette-shell.svg');
  background-size: cover;
  transition: transform 0.15s;
}
.shelf-thumb.is-vinyl {
  background-image: url('/static/img/vinyl.svg');
  background-color: var(--felt-green);
  border-radius: 50%;
  width: 64px;
  height: 64px;
  align-self: center;
}
.shelf-item:hover .shelf-thumb { transform: scale(1.05); }
.shelf-label {
  font-size: 11px;
  max-width: 96px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-marker);
  color: var(--tape-label);
}

/* === Mobile portrait === */
@media (max-width: 640px) {
  .deck {
    grid-template-columns: 1fr;
    grid-template-areas:
      "wordmark"
      "sound-toggle"
      "window"
      "readout"
      "buttons"
      "input"
      "shelf";
    padding: 16px 14px 24px;
    margin: 12px;
    width: calc(100vw - 24px);
  }
  .deck::before { display: none; } /* skip the aluminum strip; window contains it */
  .deck-sound-toggle { justify-self: end; margin-top: -32px; }
  .deck-buttons { flex-wrap: wrap; }
  .deck-btn { flex: 1; min-width: 0; }
  .deck-window { aspect-ratio: 4 / 3; max-width: none; }
  .deck-readout { min-width: 0; }
}

/* === Reduced motion === */
:where([data-reduced-motion="true"]) .deck-window.is-recording .reel,
:where([data-reduced-motion="true"]) .deck-window.is-recording .vinyl,
:where([data-reduced-motion="true"]) .deck-btn--rec.is-pressed::before,
:where([data-reduced-motion="true"]) .digital.is-err {
  animation: none !important;
}
:where([data-reduced-motion="true"]) .reel,
:where([data-reduced-motion="true"]) .tonearm {
  transition: opacity 0.2s ease-out;
  transform: none;
}
```

- [ ] **Step 2: Boot, look, sanity-check responsive at 375px viewport (Chrome devtools)**

(Manual check; no script.)

- [ ] **Step 3: Commit**

```bash
git add static/css/deck.css
git commit -m "feat(ui): deck buttons, format toggle, URL input, shelf, mobile portrait, reduced-motion"
```

---

## Phase D — Behavior (deck.js)

### Task D1: Alpine state machine + htmx event listeners

**Files:** Create `static/js/deck.js`

- [ ] **Step 1: Write the foundation**

```javascript
// deck.js — Trove cassette deck behavior
(function () {
  'use strict';

  const STORAGE_KEY = 'trove-deck';
  const SHELF_LIMIT = 12;

  function readPersisted() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch (_) { return {}; }
  }
  function writePersisted(patch) {
    const cur = readPersisted();
    Object.assign(cur, patch);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cur)); } catch (_) {}
  }

  window.trove = window.trove || {};

  window.trove.deck = function () {
    const persisted = readPersisted();
    return {
      mode: persisted.mode || 'tape',          // 'tape' | 'vinyl'
      status: 'ready',                         // 'ready' | 'load' | 'rec' | 'done' | 'err'
      jobId: null,
      videoTitle: '',
      thumbnail: '',
      formats: [],
      formatId: null,
      counter: '0:00',
      _tickerHandle: null,
      _tickerStart: 0,
      shelf: persisted.shelf || [],
      soundOn: !!persisted.soundOn,
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,

      init() {
        this._wireHtmxListeners();
        this._wireUnloadCancel();
      },

      _wireHtmxListeners() {
        const target = document.getElementById('card-target');
        if (!target) return;
        target.addEventListener('htmx:afterSwap', () => {
          const card = target.querySelector('[data-card]');
          if (!card) return;
          this._consumeCard(card);
        });
      },

      _consumeCard(card) {
        const status = card.dataset.status;
        if (status === 'error') {
          this.status = 'err';
          this.videoTitle = card.dataset.title || '';
          return;
        }
        if (status === 'ready') {
          this.status = 'load';
          this.videoTitle = card.dataset.title || 'Untitled';
          this.thumbnail = card.dataset.thumbnail || '';
          this.formats = JSON.parse(card.dataset.formats || '[]');
          this.formatId = (this.formats[0] && this.formats[0].id) || null;
          return;
        }
        if (status === 'queued' || status === 'downloading') {
          this.status = 'rec';
          this.jobId = card.dataset.jobId || null;
          return;
        }
        if (status === 'done') {
          this.status = 'done';
          this.jobId = card.dataset.jobId || this.jobId;
          this._addToShelf({
            id: this.jobId,
            title: this.videoTitle,
            filename: card.dataset.filename || '',
            kind: this.mode === 'vinyl' ? 'vinyl' : 'cassette',
          });
          return;
        }
        if (status === 'cancelled') {
          this.status = 'ready';
          return;
        }
      },

      _wireUnloadCancel() {
        window.addEventListener('beforeunload', () => {
          if (this.jobId && this.status === 'rec') {
            try { navigator.sendBeacon('/api/job/' + this.jobId + '/cancel'); } catch (_) {}
          }
        });
      },

      _addToShelf(item) {
        if (!item.id) return;
        // dedupe by id
        this.shelf = this.shelf.filter(s => s.id !== item.id);
        this.shelf.unshift(item);
        if (this.shelf.length > SHELF_LIMIT) this.shelf.length = SHELF_LIMIT;
        writePersisted({ shelf: this.shelf });
      },

      setMode(mode) {
        if (mode !== 'tape' && mode !== 'vinyl') return;
        this.mode = mode;
        writePersisted({ mode });
      },

      toggleSound() {
        this.soundOn = !this.soundOn;
        writePersisted({ soundOn: this.soundOn });
      },

      // Action methods (filled in by D2/D3)
      rec() { this._submitDownload(); },
      stop() { /* future: cancel + reset */ },
      eject() {
        this.status = 'ready';
        this.videoTitle = '';
        this.jobId = null;
      },

      _submitDownload() {
        if (this.status !== 'load') return;
        const form = new FormData();
        form.append('url', document.querySelector('.deck-url-input').value || '');
        form.append('title', this.videoTitle);
        form.append('format', this.mode === 'vinyl' ? 'audio' : 'video');
        if (this.formatId) form.append('format_id', this.formatId);
        fetch('/api/download-card', { method: 'POST', body: form })
          .then(r => r.text())
          .then(html => {
            const target = document.getElementById('card-target');
            if (target) {
              target.innerHTML = html;
              const card = target.querySelector('[data-card]');
              if (card) this._consumeCard(card);
              if (this.jobId) this._startStatusPoll();
            }
          });
      },

      _startStatusPoll() {
        const tick = () => {
          if (this.status !== 'rec' || !this.jobId) return;
          fetch('/api/status-card/' + this.jobId)
            .then(r => r.text())
            .then(html => {
              const target = document.getElementById('card-target');
              if (!target) return;
              target.innerHTML = html;
              const card = target.querySelector('[data-card]');
              if (card) this._consumeCard(card);
              if (this.status === 'rec') setTimeout(tick, 1000);
            })
            .catch(() => { setTimeout(tick, 2000); });
        };
        setTimeout(tick, 1000);
      },
    };
  };
})();
```

- [ ] **Step 2: Boot the server and verify the page doesn't throw in the browser console**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
PORT=8899 HOST=127.0.0.1 python app.py &
SERVER_PID=$!
sleep 2
curl -s -o /dev/null -w 'home: %{http_code}\n' http://127.0.0.1:8899/
sleep 20  # implementer opens devtools, confirms no console errors
kill $SERVER_PID 2>/dev/null || true
```

If browser console shows uncaught errors, fix before committing.

- [ ] **Step 3: Commit**

```bash
git add static/js/deck.js
git commit -m "feat(ui): deck Alpine state machine + htmx-driven download flow"
```

### Task D2: GSAP timelines + reel rotation + counter ticking

**Files:** Modify `static/js/deck.js`

- [ ] **Step 1: Append GSAP-driven animation orchestration**

Locate the action methods in `deck.js` (`rec`, `stop`, `eject`, `setMode`) and replace with GSAP-aware versions. Insert near the top of the returned object (after `init`) a `_gsap()` helper that no-ops if GSAP isn't available:

```javascript
      _gsap() { return window.gsap || null; },

      // OVERRIDE rec() from D1 with animation orchestration
      rec() {
        if (this.status !== 'load') return;
        const tl = this._gsap()?.timeline();
        if (tl) {
          tl.to('.deck-btn--rec', { y: 2, duration: 0.05 })
            .to('.cassette', { scale: 1.0, duration: 0.1 })
            .add(() => this._submitDownload());
        } else {
          this._submitDownload();
        }
        this._startCounter();
      },

      _startCounter() {
        this.counter = '0:00';
        this._tickerStart = Date.now();
        if (this._tickerHandle) clearInterval(this._tickerHandle);
        this._tickerHandle = setInterval(() => {
          if (this.status !== 'rec') {
            clearInterval(this._tickerHandle);
            this._tickerHandle = null;
            return;
          }
          const sec = Math.floor((Date.now() - this._tickerStart) / 1000);
          const m = Math.floor(sec / 60);
          const s = sec % 60;
          this.counter = `${m}:${s.toString().padStart(2, '0')}`;
        }, 250);
      },

      // OVERRIDE eject() with door-open animation
      eject() {
        const tl = this._gsap()?.timeline();
        if (tl) {
          tl.to('.cassette', { y: -8, duration: 0.4, ease: 'power2.out' })
            .to('.cassette', { y: 0, duration: 0.6, ease: 'power2.in', delay: 0.2 });
        }
        this.status = 'ready';
        this.videoTitle = '';
        this.jobId = null;
        if (this._tickerHandle) { clearInterval(this._tickerHandle); this._tickerHandle = null; }
      },

      // OVERRIDE setMode() with deck-to-turntable flip
      setMode(mode) {
        if (mode !== 'tape' && mode !== 'vinyl' || mode === this.mode) return;
        const tl = this._gsap()?.timeline();
        if (tl && !this.reducedMotion) {
          tl.to('.deck-window', { rotateX: 90, duration: 0.4, ease: 'power2.in' })
            .add(() => { this.mode = mode; })
            .to('.deck-window', { rotateX: 0, duration: 0.4, ease: 'power2.out' });
        } else {
          this.mode = mode;
        }
        writePersisted({ mode });
      },
```

(The `writePersisted` reference inside `setMode` already exists in scope from D1's IIFE.)

- [ ] **Step 2: Smoke — verify the rec animation triggers in browser**

(Manual: paste a sample URL → click LOAD → click ● REC → confirm REC button visibly depresses, counter starts ticking, reels begin spinning via the existing CSS class on `.deck-window.is-recording`.)

- [ ] **Step 3: Commit**

```bash
git add static/js/deck.js
git commit -m "feat(ui): GSAP rec/eject/flip timelines + counter ticker"
```

### Task D3: Web Audio procedural sounds + sound toggle wiring

**Files:** Modify `static/js/deck.js`

- [ ] **Step 1: Append the Web Audio module**

Add an audio helper near the top of the IIFE (above `window.trove.deck`):

```javascript
  // === Procedural audio module ===
  const audio = (function () {
    let ctx = null;
    function ensureCtx() {
      if (!ctx && typeof AudioContext !== 'undefined') ctx = new AudioContext();
      return ctx;
    }
    function envelope(node, peak, attack, release) {
      const t = ctx.currentTime;
      node.gain.setValueAtTime(0, t);
      node.gain.linearRampToValueAtTime(peak, t + attack);
      node.gain.linearRampToValueAtTime(0, t + attack + release);
    }
    function noiseBurst(duration, peak) {
      const c = ensureCtx(); if (!c) return;
      const buffer = c.createBuffer(1, c.sampleRate * duration, c.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * 0.6;
      const src = c.createBufferSource(); src.buffer = buffer;
      const gain = c.createGain();
      envelope(gain, peak, 0.005, duration - 0.01);
      src.connect(gain).connect(c.destination); src.start();
    }
    function tone(freq, duration, peak, type) {
      const c = ensureCtx(); if (!c) return;
      const osc = c.createOscillator(); osc.frequency.value = freq; osc.type = type || 'sine';
      const gain = c.createGain();
      envelope(gain, peak, 0.005, duration);
      osc.connect(gain).connect(c.destination); osc.start();
      osc.stop(c.currentTime + duration + 0.05);
    }
    return {
      clunkOpen() { noiseBurst(0.08, 0.5); tone(180, 0.12, 0.2, 'square'); },
      clunkClose() { noiseBurst(0.06, 0.4); tone(120, 0.18, 0.25, 'square'); },
      click() { noiseBurst(0.02, 0.3); },
      chime() { tone(880, 0.18, 0.18, 'sine'); setTimeout(() => tone(1320, 0.22, 0.16, 'sine'), 120); },
      buzz() { tone(110, 0.4, 0.18, 'sawtooth'); },
    };
  })();
```

- [ ] **Step 2: Wire sound calls into the action methods, gated by `this.soundOn`**

In the Alpine component's methods, sprinkle conditional calls:

```javascript
      rec() {
        if (this.status !== 'load') return;
        if (this.soundOn) audio.click();
        const tl = this._gsap()?.timeline();
        if (tl) {
          tl.to('.deck-btn--rec', { y: 2, duration: 0.05 })
            .add(() => { if (this.soundOn) audio.clunkClose(); })
            .add(() => this._submitDownload());
        } else {
          this._submitDownload();
        }
        this._startCounter();
      },

      eject() {
        if (this.soundOn) audio.clunkOpen();
        // ... existing eject body ...
      },
```

And in `_consumeCard` for status `done`:

```javascript
        if (status === 'done') {
          if (this.soundOn) audio.chime();
          // existing body ...
        }
        if (status === 'error' || status === 'err') {
          if (this.soundOn) audio.buzz();
          // existing body ...
        }
```

(Pseudo-merge — preserve the existing logic; just add the sound calls at the right entry points.)

- [ ] **Step 3: Smoke — toggle sound on, click REC, confirm clicks audible**

(Manual.)

- [ ] **Step 4: Commit**

```bash
git add static/js/deck.js
git commit -m "feat(ui): procedural Web Audio (click, clunk, chime, buzz) gated by sound toggle"
```

---

## Phase E — Tests

### Task E1: Update test_endpoints.py + run all tests green

**Files:** Modify `tests/test_endpoints.py`

- [ ] **Step 1: Refine the existing argv-injection card test**

Find `test_argument_injection_url_rejected_card` and replace its assertion to read the new data-attribute carrier instead of looking for "unsupported" text:

```python
def test_argument_injection_url_rejected_card(client, monkeypatch):
    called = []
    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: called.append(a) or _ok(""))
    r = client.post("/api/info-card", data={"url": "--exec=touch /tmp/pwned"})
    assert r.status_code == 400
    body = r.data.decode()
    # The new card.html is a data-attribute carrier; verify it emitted an error card.
    assert 'data-status="error"' in body
    assert 'data-category="unsupported_url"' in body
    assert called == []
```

- [ ] **Step 2: Add 2 new smoke tests**

```python
def test_index_renders_with_deck_assets(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode()
    assert 'css/deck.css' in body
    assert 'vendor/gsap.min.js' in body
    assert 'js/deck.js' in body
    assert 'id="deck"' in body
    # Footer attribution must be gone.
    assert 'averygan/reclip' not in body


def test_card_partial_emits_data_attributes(client, monkeypatch):
    import json as _json
    fake_stdout = _json.dumps({
        "title": "T", "thumbnail": "https://x/y.jpg", "duration": 30,
        "uploader": "U",
        "formats": [{"format_id": "137", "height": 1080, "vcodec": "avc1", "tbr": 5000}],
    })

    class FakeCompleted:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())
    r = client.post("/api/info-card", data={"url": "https://www.youtube.com/watch?v=abc"})
    assert r.status_code == 200
    body = r.data.decode()
    assert 'data-status="ready"' in body
    assert 'data-title="T"' in body
    assert 'data-uploader="U"' in body
    assert 'data-formats=' in body
```

- [ ] **Step 3: Run all tests**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
python -m pytest -v
```

Expected: 63 + 2 = 65 tests passing.

If `test_csp_no_unsafe_inline_script` from Phase 1 is still in the file, it must still pass (we kept CSP unchanged).

- [ ] **Step 4: Commit**

```bash
git add tests/test_endpoints.py
git commit -m "test(endpoints): card data-attr smoke tests + updated arg-injection assertion"
```

---

## Phase F — Smoke + push

### Task F1: Manual screen-record smoke + reduced-motion check

**Files:** none

- [ ] **Step 1: Boot the server**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
source venv/bin/activate
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify
PORT=8899 HOST=127.0.0.1 python app.py &
SERVER_PID=$!
sleep 2
echo "Open http://127.0.0.1:8899 — record the following sequences:"
```

- [ ] **Step 2: Visual sequence — sample MP4**

(Manual.) In a browser:
1. Confirm the deck face fills the viewport with walnut + aluminum + amber LED reading "READY".
2. Paste `https://download.samplelib.com/mp4/sample-5s.mp4` into the URL field. Click LOAD.
3. Cassette appears in window with title "sample 5s" on Permanent Marker label.
4. Click ● REC. Reels start spinning, counter ticks, REC LED on.
5. Wait for download. Counter reaches ~0:08, "DONE" appears, reels stop. Cassette in shelf.
6. Click cassette in shelf → file downloads.

- [ ] **Step 3: Visual sequence — MP3 / vinyl mode**

1. Toggle MP3.
2. Deck flips, turntable underneath with vinyl + tonearm.
3. Repeat steps 2-5 with the same URL — vinyl spins, tonearm drops, completes.

- [ ] **Step 4: Reduced motion**

In Chrome devtools → Rendering → Emulate `prefers-reduced-motion: reduce`. Reload. Confirm: deck face still beautiful, but no reel rotation, no door slide animation, no flip on mode change.

- [ ] **Step 5: Mobile check**

In Chrome devtools → Toggle device toolbar, set 375 × 812 (iPhone). Confirm deck reflows to portrait, all buttons ≥ 44px tall, can complete a full download flow.

- [ ] **Step 6: Sound check**

Toggle sound on. Click REC. Hear clicks + clunk on download. Click eject — clunk-open. Mute again.

- [ ] **Step 7: Stop the server**

```bash
kill $SERVER_PID 2>/dev/null
```

If anything looks broken, return to the relevant phase and fix before F2.

### Task F2: Push the redesign branch + open PR

**Files:** none

- [ ] **Step 1: Push branch**

```bash
cd /Users/kaivan108icloud.com/Downloads/trove
git push -u origin redesign/tape-deck
```

- [ ] **Step 2: Open a draft PR**

```bash
gh pr create --draft --base main --head redesign/tape-deck \
  --title "Tape Deck redesign — full-bleed cassette UI" \
  --body "$(cat <<'EOF'
## Summary
- Full-bleed late-70s cassette deck UI replacing the consumer-friendly Phase 1 design
- MP3 mode flips deck to a turntable
- Procedural Web Audio (opt-in) for mechanical clicks, clunks, chime
- GSAP for orchestrated animations; CSS-only steady-state rotation
- Backend untouched (63+2 tests still passing)

## Test plan
- [ ] `python -m pytest` — 65 tests green
- [ ] Manual: paste sample MP4 URL → cassette load → REC → reels spin → DONE → save to device
- [ ] Manual: toggle MP3 → deck flips to turntable → vinyl flow works
- [ ] Manual: `prefers-reduced-motion: reduce` disables rotations + slides
- [ ] Manual: 375px portrait → buttons ≥ 44px, full flow works
- [ ] Manual: sound toggle on → procedural clicks audible

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verify the PR is up**

```bash
gh pr view --web 2>/dev/null || echo "open https://github.com/afk1997/trove/pulls"
gh pr list --state open
```

Expected: a draft PR exists for `redesign/tape-deck → main`.

---

## Acceptance criteria check

After F2, the spec's 10 criteria should be satisfied:

1. ✅ pytest 65 green (E1)
2. ✅ Page renders cassette deck full-bleed (B2 + C1-C3)
3. ✅ Paste→load→REC→spin→eject is 60fps (D1-D3 + manual smoke F1)
4. ✅ MP3 toggle flips deck (D2 setMode + C2 turntable styles)
5. ✅ Sound off by default; persists (D1 + D3)
6. ✅ Footer attribution removed (B1)
7. ✅ Reduced-motion fallback (B1 + C3 + D2)
8. ✅ CSP unchanged; nonces honored on all `<script>` tags (B1)
9. ✅ Mobile portrait works at 375px (C3 + manual F1)
10. ✅ Lighthouse mobile ≥ 90 (manual after F1; structurally clean — small CSS, vendored JS, no audio files)

---

## Self-review notes

- **Spec coverage:** every spec section maps to a task — branding (C1), layout (C1), components (C2 + C3), MP3 mode (B2 + C2 + D2), cassette interactions (D1 + D2), shelf (B2 + C3 + D1), animations (C2 + D2), sound (D3), architecture file map (file-map section above), state machine (D1), htmx integration (D1), reduced motion (C3 + D2), endpoints (unchanged — covered by existing tests), test updates (E1).
- **Placeholder scan:** none. All steps include actual code or commands.
- **Type consistency:** the data-attribute names emitted by `card.html` (`data-status`, `data-job-id`, `data-title`, `data-thumbnail`, `data-uploader`, `data-duration`, `data-format`, `data-filename`, `data-category`, `data-formats`) match exactly what `deck.js`'s `_consumeCard` reads. The Alpine component's status enum (`'ready' | 'load' | 'rec' | 'done' | 'err'`) is mapped consistently from server-side card kinds (`ready`, `queued`, `downloading`, `done`, `error`, `cancelled`).
- **Risks the implementer should watch:**
  - SVG fidelity: cassette/vinyl realism is the make-or-break visual. If frontend-design's first-pass SVGs look weak, iterate before moving to deck.css.
  - GSAP timeline ordering: the `setMode` flip uses `rotateX` on `.deck-window` — confirm CSS `perspective` is set on `.deck` parent, otherwise the flip looks flat.
  - Mobile flip: rotating the entire window on a small viewport may feel too busy; the spec already notes this — consider suppressing the flip below 640px and just doing a fade.
  - Counter accuracy: the procedural counter is wall-clock, not byte-rate. That's fine for visual effect; users won't notice unless they expect Mbps progress.
