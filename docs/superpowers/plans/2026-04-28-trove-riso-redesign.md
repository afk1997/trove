# Trove Riso Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the phosphor-terminal UI with a 2-color riso-zine brand system without touching backend logic, htmx contracts, or response shapes.

**Architecture:** Four files mutate (`templates/base.html`, `styles/input.css`, `tailwind.config.js`, `templates/index.html`, `templates/partials/card.html`); one file deletes (`static/vendor/alpine.min.js`). All Python untouched. CSS is split across five progressive commits inside `styles/input.css` (base → hero → cards → empty → motion). Templates rewrite to consume the new component classes. Build pipeline (`./trove.sh` → standalone Tailwind CLI → `static/app.css`) is unchanged.

**Tech Stack:** Flask · Jinja2 · htmx 2 · Tailwind CSS v4 (standalone, no Node) · Google Fonts (Fraunces variable, Inter, IBM Plex Mono) · vanilla JS in CSP-nonce script blocks.

**Spec:** `docs/superpowers/specs/2026-04-28-trove-riso-redesign-design.md` — read before starting.

---

## Setup notes

- **Branch:** Work on a feature branch (`ui/riso-redesign` recommended). The repo `main` should be green throughout. Each task ends in a discrete commit so you can revert any single step cleanly.
- **Dev loop:** Keep `./trove.sh` running in one terminal during work. The Tailwind CLI watches `styles/input.css` and rebuilds `static/app.css` on save. Hot-reload `localhost:8899` in the browser to verify.
- **Visual baseline:** Before starting, screenshot the current home page at 1440px and 375px so you can A/B compare during QA.
- **Fonts loaded but unused:** From Task 1, the page loads Fraunces + Plex Mono via Google Fonts but the existing CSS doesn't reference them. This is intentional — minor asset weight, zero visual change.
- **Mid-flight breakage:** Between Task 2 (CSS rewrite) and Task 9 (template rewrite), the homepage will look unstyled. Stay on the branch.

---

## File structure

| File | Status | Purpose |
|---|---|---|
| `templates/base.html` | modify | Layout shell: Google Fonts link, htmx, CSP nonce, beforeunload sendBeacon. |
| `styles/input.css` | rewrite | Tailwind v4 source. Riso brand system: tokens, base, components, motion, reduced-motion, mobile. |
| `tailwind.config.js` | modify | Token map (colors, fonts) consumed by Tailwind. |
| `static/app.css` | (built) | Compiled CSS. Never edit by hand. |
| `templates/index.html` | rewrite | Hero block + empty-state hint + format-toggle JS. |
| `templates/partials/card.html` | rewrite | Five card states (error, ready, queued/downloading, done, cancelled). |
| `static/vendor/alpine.min.js` | delete | Vendored but never loaded. |
| `app.py · jobs.py · runner.py · safety.py` | unchanged | No endpoint or signature changes. |
| `tests/` | unchanged | Existing endpoint/safety/CSP tests pass as-is. |
| `Dockerfile · trove.sh · requirements.txt · pyproject.toml` | unchanged | Build pipeline unchanged. |

---

## Task 1: Swap Google Fonts in base.html

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1.1: Read the current base.html**

Run: Read tool on `/Users/kaivan108icloud.com/Downloads/trove/templates/base.html` (full file).

Confirm the current Google Fonts `<link>` line is:

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=VT323&display=swap" rel="stylesheet">
```

- [ ] **Step 1.2: Replace the Google Fonts link**

Use Edit tool to replace exactly:

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=VT323&display=swap" rel="stylesheet">
```

with:

```html
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..600;1,9..144,400..500&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
```

- [ ] **Step 1.3: Add color-scheme meta**

Find the existing `<meta name="description"…>` line. Use Edit tool to replace it with the description line plus the new color-scheme meta:

Old:
```html
  <meta name="description" content="Save things you care about. Self-hosted media downloader.">
```

New:
```html
  <meta name="description" content="Save things you care about. Self-hosted media downloader.">
  <meta name="color-scheme" content="light">
```

- [ ] **Step 1.4: Verify the page still renders**

Start the dev server if not running: `./trove.sh`. Open `http://localhost:8899`. The page should look identical to before — only the font asset URLs changed.

Also verify in DevTools Network tab that Fraunces, Inter, and IBM Plex Mono now load (status 200).

- [ ] **Step 1.5: Commit**

```bash
git add templates/base.html
git commit -m "$(cat <<'EOF'
chore(ui): load Fraunces + IBM Plex Mono fonts

Drop VT323. Add color-scheme: light meta so dark-mode browsers
don't auto-invert the cream paper aesthetic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Rewrite input.css base layer

**Files:**
- Rewrite: `styles/input.css`

- [ ] **Step 2.1: Replace input.css with the new base layer**

Use Write tool to OVERWRITE `/Users/kaivan108icloud.com/Downloads/trove/styles/input.css` with this content:

```css
@import "tailwindcss";
@config "../tailwind.config.js";

/* ============================================================
   TROVE — RISO ZINE BRAND SYSTEM
   See: docs/superpowers/specs/2026-04-28-trove-riso-redesign-design.md
   ============================================================ */

@layer base {
  :root {
    /* Two-ink palette */
    --paper:        #f1e6cc;
    --light:        #fef7e3;
    --teal:         #1a3540;
    --orange:       #ff5728;
    --forest:       #1f7a3f;

    /* Faint orange dot for halftone overlay */
    --halftone:     rgba(255, 87, 40, 0.04);

    /* Registration-offset shadow color (orange period drop) */
    --offset-shadow: rgba(26, 53, 64, 0.18);

    /* Hard offset shadow utilities (no blur) */
    --shadow-card:        4px 4px 0 var(--teal);
    --shadow-card-orange: 4px 4px 0 var(--orange);
    --shadow-stamp:       2px 2px 0 var(--teal);
    --shadow-stamp-3:     3px 3px 0 var(--teal);
  }

  html { color-scheme: light; }

  html, body {
    margin: 0;
    padding: 0;
    background: var(--paper);
    color: var(--teal);
    font-family: 'Inter', ui-sans-serif, system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
  }

  /* Paper grain — multi-layer dot pattern */
  body {
    background-image:
      radial-gradient(circle at 12% 18%, rgba(26, 53, 64, 0.05) 0.5px, transparent 1px),
      radial-gradient(circle at 78% 38%, rgba(26, 53, 64, 0.06) 0.5px, transparent 1px),
      radial-gradient(circle at 32% 76%, rgba(26, 53, 64, 0.05) 0.5px, transparent 1px),
      radial-gradient(circle at 88% 88%, rgba(26, 53, 64, 0.06) 0.5px, transparent 1px),
      radial-gradient(circle at 50% 50%, rgba(26, 53, 64, 0.04) 0.5px, transparent 1px);
    background-size: 4px 4px, 5px 5px, 6px 6px, 4px 4px, 7px 7px;
    background-attachment: fixed;
  }

  /* Halftone overlay — orange "ink" dots, multiplied across page */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      repeating-radial-gradient(circle at 0 0, var(--halftone) 0 0.8px, transparent 0.8px 6px);
    pointer-events: none;
    mix-blend-mode: multiply;
    z-index: 100;
  }

  ::selection { background: var(--orange); color: var(--light); }

  input, textarea, button, select { font-family: inherit; color: inherit; }

  a {
    color: var(--teal);
    text-decoration: underline;
    text-decoration-style: dashed;
    text-underline-offset: 3px;
  }
  a:hover { color: var(--orange); }
}

/* ============================================================
   COMPONENTS — placeholder; tasks 3-5 fill these in
   ============================================================ */

@layer components {
  /* (hero components added in Task 3) */
  /* (card components added in Task 4) */
  /* (empty-state added in Task 5) */
}

/* ============================================================
   MOTION — placeholder; task 6 fills these in
   ============================================================ */

/* (keyframes + reduced-motion + mobile added in Task 6) */
```

- [ ] **Step 2.2: Rebuild static/app.css**

Run:

```bash
./trove.sh
```

If the dev server is already running with watch mode, the CSS rebuilds automatically when you save.

If not, you can rebuild once with:

```bash
./tools/tailwindcss -i styles/input.css -o static/app.css --minify
```

Expected: no errors. `static/app.css` size drops considerably (no components yet).

- [ ] **Step 2.3: Verify page renders with new base**

Reload `http://localhost:8899`. Expected:

- Page background is cream `#F1E6CC` with subtle dot grain
- Fixed halftone overlay barely visible
- Body text font is Inter, not VT323
- Page LOOKS BROKEN — old class names like `.wordmark`, `.panel-input`, `.btn-primary` aren't styled. This is expected mid-flight.

- [ ] **Step 2.4: Commit**

```bash
git add styles/input.css static/app.css
git commit -m "$(cat <<'EOF'
design(ui): rewrite input.css base layer for riso brand

Drop phosphor-terminal palette and CRT effects. Add cream-paper
background with multi-layer dot grain, fluorescent-orange halftone
overlay, two-ink CSS variables, color-scheme: light. Components
follow in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add hero components to input.css

**Files:**
- Modify: `styles/input.css`

- [ ] **Step 3.1: Append hero component block**

Use Edit tool on `styles/input.css`. Replace exactly:

```css
@layer components {
  /* (hero components added in Task 3) */
  /* (card components added in Task 4) */
  /* (empty-state added in Task 5) */
}
```

with:

```css
@layer components {

  /* === HERO ============================================== */

  .hero-stage {
    max-width: 720px;
    margin: 0 auto;
    padding: 30px 28px 36px;
    border-bottom: 1.5px dashed var(--teal);
    position: relative;
  }

  .hero-top {
    display: flex; justify-content: space-between; align-items: center;
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--teal);
    padding-bottom: 12px;
    border-bottom: 1.5px solid var(--teal);
    margin-bottom: 38px;
  }
  .hero-top .left { display: flex; align-items: center; gap: 10px; }
  .hero-top .dot { width: 6px; height: 6px; background: var(--orange); border-radius: 50%; flex-shrink: 0; }
  .hero-top .right { color: var(--orange); }

  .hero-mark-row {
    display: flex; align-items: flex-end; gap: 0;
  }

  .hero-mark {
    font-family: 'Fraunces', Georgia, serif;
    font-size: clamp(56px, 12vw, 132px);
    line-height: 0.82;
    letter-spacing: -0.04em;
    color: var(--teal);
    font-weight: 600;
    font-variation-settings: 'WONK' 1, 'SOFT' 50, 'opsz' 144;
    margin: 0;
  }
  .hero-mark .period {
    color: var(--orange);
    text-shadow: 2px 2.5px 0 var(--offset-shadow);
    margin-left: 0.05em;
  }

  .hero-arrow {
    font-family: 'IBM Plex Mono', monospace;
    font-size: clamp(28px, 6vw, 56px);
    color: var(--orange);
    line-height: 1;
    margin-left: 18px;
    margin-bottom: 12px;
    text-shadow: 2px 2.5px 0 var(--offset-shadow);
    align-self: center;
  }

  .hero-tag {
    font-family: 'Fraunces', Georgia, serif;
    font-style: italic;
    font-size: 22px;
    color: var(--teal);
    font-weight: 400;
    margin: 14px 0 36px;
    max-width: 520px;
    line-height: 1.3;
  }
  .hero-tag .accent { color: var(--orange); font-weight: 500; }

  .hero-plate {
    background: var(--light);
    border: 1.5px solid var(--teal);
    border-radius: 4px;
    box-shadow: var(--shadow-card);
    overflow: hidden;
    transition: box-shadow 150ms ease-out, border-color 150ms ease-out;
  }
  .hero-plate:focus-within {
    border-color: var(--orange);
    box-shadow: 4px 4px 0 var(--orange);
  }
  .hero-plate:focus-within .hero-plate-header {
    background: var(--orange);
  }
  .hero-plate:focus-within .hero-input { background: #fff9ea; }

  .hero-plate-header {
    background: var(--teal);
    color: var(--paper);
    padding: 6px 14px 5px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    display: flex; justify-content: space-between; align-items: center;
    transition: background 150ms ease-out;
  }
  .hero-plate-header .step { color: var(--orange); }

  .hero-input-row { padding: 16px 18px 14px; display: flex; align-items: center; gap: 10px; }

  .hero-input {
    flex: 1;
    font-family: 'Inter', sans-serif;
    font-size: 17px;
    color: var(--teal);
    background: transparent;
    border: none;
    outline: none;
    transition: background 150ms ease-out;
    min-width: 0;
  }
  .hero-input::placeholder {
    color: var(--teal);
    opacity: 0.45;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 14px;
  }
  .hero-input:focus-visible { outline: none; }
  /* Orange caret on focus */
  .hero-input { caret-color: var(--orange); }

  .hero-controls {
    border-top: 1px dashed rgba(26, 53, 64, 0.35);
    padding: 12px 18px;
    display: flex; align-items: center; gap: 10px;
  }

  .hero-toggle {
    display: inline-flex;
    border: 1.5px solid var(--teal);
    border-radius: 0;
    overflow: hidden;
  }
  .hero-pill {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.14em;
    padding: 7px 14px;
    color: var(--teal);
    background: transparent;
    cursor: pointer;
    border: none;
    border-right: 1.5px solid var(--teal);
    transition: background 150ms ease-out, color 150ms ease-out;
    min-height: 36px;
  }
  .hero-pill:last-child { border-right: none; }
  .hero-pill:hover { background: rgba(26, 53, 64, 0.08); }
  .hero-pill.is-active {
    background: var(--teal);
    color: var(--light);
  }
  .hero-pill:focus-visible {
    outline: 2px dashed var(--orange);
    outline-offset: 2px;
  }

  .hero-cta {
    margin-left: auto;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    padding: 9px 18px;
    background: var(--orange);
    color: var(--light);
    border: 1.5px solid var(--teal);
    box-shadow: var(--shadow-stamp-3);
    transform: rotate(-1.2deg);
    cursor: pointer;
    transition: box-shadow 150ms ease-out, transform 80ms ease-out;
    min-height: 38px;
  }
  .hero-cta:hover { box-shadow: 4px 4px 0 var(--teal); }
  .hero-cta:active {
    box-shadow: 0 0 0 var(--teal);
    transform: rotate(-1.2deg) translate(3px, 3px);
  }
  .hero-cta:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    box-shadow: 1px 1px 0 var(--teal);
  }
  .hero-cta:focus-visible {
    outline: 2px dashed var(--teal);
    outline-offset: 2px;
  }
  .hero-cta.is-fetching {
    background: var(--teal);
    color: var(--light);
    box-shadow: 3px 3px 0 var(--orange);
  }
  .hero-cta.is-fetching .ellipsis { animation: blink 0.8s steps(2) infinite; }

  .hero-ticker {
    margin-top: 30px;
    border-top: 1.5px solid var(--teal);
    padding-top: 14px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.22em;
    color: var(--teal);
    text-transform: uppercase;
    display: flex; justify-content: space-between; gap: 12px;
  }
  .hero-ticker .right { color: var(--orange); }

  .hero-corner-stamp {
    position: absolute;
    top: 18px; right: 22px;
    transform: rotate(7deg);
    border: 2px solid var(--orange);
    padding: 4px 10px;
    color: var(--orange);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    background: rgba(255, 87, 40, 0.06);
    z-index: 2;
    pointer-events: none;
  }

  /* === CARDS ============================================== */
  /* (added in Task 4) */

  /* === EMPTY STATE ======================================== */
  /* (added in Task 5) */

}
```

- [ ] **Step 3.2: Rebuild and verify**

Save the file. The watcher rebuilds. Reload `http://localhost:8899`. Expected:

- Site still looks broken (templates haven't been updated yet)
- No CSS errors in DevTools console
- `static/app.css` has grown by ~3-5KB (compiled hero classes)

- [ ] **Step 3.3: Commit**

```bash
git add styles/input.css static/app.css
git commit -m "$(cat <<'EOF'
design(ui): add hero components to riso brand system

Hero stage, top strip, wordmark with offset orange period, italic
tagline, plate with focus-within state flip, segmented toggle,
brass-stamp save button, footer ticker, corner issue stamp.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add card components to input.css

**Files:**
- Modify: `styles/input.css`

- [ ] **Step 4.1: Append card component block**

Use Edit tool. Replace exactly:

```css
  /* === CARDS ============================================== */
  /* (added in Task 4) */
```

with:

```css
  /* === CARDS ============================================== */

  .clip {
    background: var(--light);
    border: 1.5px solid var(--teal);
    border-radius: 4px;
    box-shadow: var(--shadow-card);
    padding: 0;
    overflow: hidden;
    display: grid;
    grid-template-columns: 116px 1fr auto;
    gap: 0;
    position: relative;
    animation: card-in 280ms cubic-bezier(0.22, 1, 0.36, 1);
  }
  .clip-num {
    position: absolute;
    top: -8px; left: 12px;
    background: var(--light);
    padding: 0 6px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    letter-spacing: 0.3em;
    color: var(--teal);
    z-index: 2;
    border: 1.5px solid var(--teal);
    line-height: 14px;
  }
  .clip-thumb {
    width: 116px; height: 80px;
    background: var(--teal);
    overflow: hidden;
    border-right: 1.5px solid var(--teal);
    display: flex; align-items: center; justify-content: center;
    color: var(--paper);
    position: relative;
    flex-shrink: 0;
  }
  .clip-thumb img {
    width: 100%; height: 100%; object-fit: cover;
    filter: saturate(0.85) contrast(1.05);
  }
  .clip-thumb::before {
    content: ''; position: absolute; inset: 0;
    background-image:
      repeating-radial-gradient(circle at 0 0, rgba(254, 247, 227, 0.18) 0 0.8px, transparent 0.8px 4px);
    mix-blend-mode: overlay;
    pointer-events: none;
  }
  .clip-thumb svg { width: 28px; height: 28px; opacity: 0.55; position: relative; z-index: 1; }

  .clip-body {
    padding: 14px 16px;
    display: flex; flex-direction: column; justify-content: center; gap: 4px;
    min-width: 0;
  }
  .clip-title {
    font-family: 'Fraunces', serif;
    font-size: 18px;
    font-weight: 600;
    color: var(--teal);
    line-height: 1.15;
    letter-spacing: -0.01em;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variation-settings: 'WONK' 1, 'opsz' 24;
  }
  .clip-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.14em;
    color: var(--teal);
    opacity: 0.6;
    text-transform: uppercase;
    margin: 2px 0 0;
  }
  .clip-meta .sep { color: var(--orange); opacity: 0.7; margin: 0 4px; }

  .clip-action {
    display: flex; flex-direction: column; align-items: stretch;
    justify-content: center; gap: 8px;
    padding: 14px 16px 14px 4px;
    border-left: 1px dashed rgba(26, 53, 64, 0.25);
  }

  .clip-picker {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    border: 1.5px solid var(--teal);
    background: var(--paper);
    color: var(--teal);
    padding: 4px 8px;
    cursor: pointer;
  }
  .clip-picker:focus-visible { outline: 2px dashed var(--orange); outline-offset: 2px; }

  .clip-save {
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
    transition: box-shadow 150ms ease-out, transform 80ms ease-out;
    min-height: 32px;
  }
  .clip-save:hover { box-shadow: 3px 3px 0 var(--teal); }
  .clip-save:active {
    box-shadow: 0 0 0 var(--teal);
    transform: rotate(-1deg) translate(2px, 2px);
  }
  .clip-save:focus-visible { outline: 2px dashed var(--teal); outline-offset: 2px; }

  /* DOWNLOADING */
  .clip.is-downloading {
    border-color: var(--orange);
    box-shadow: var(--shadow-card-orange);
  }
  .clip.is-downloading .clip-thumb { border-right-color: var(--orange); }
  .clip.is-downloading .clip-num { border-color: var(--orange); color: var(--orange); }
  .clip.is-downloading .clip-action { border-left-color: rgba(255, 87, 40, 0.4); }

  .clip-progress {
    grid-column: 1 / -1;
    height: 8px;
    margin: 0;
    background:
      repeating-linear-gradient(45deg,
        var(--teal) 0, var(--teal) 4px,
        var(--light) 4px, var(--light) 8px);
    border-top: 1.5px solid var(--orange);
    position: relative;
    overflow: hidden;
  }
  .clip-progress::after {
    content: ''; position: absolute; inset: 0;
    background: linear-gradient(90deg, transparent, var(--orange) 50%, transparent);
    animation: scan 1.4s linear infinite;
    width: 40%;
    mix-blend-mode: screen;
  }

  .clip-saving-stamp {
    font-family: 'Inter', sans-serif;
    font-size: 11px; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--orange);
    border: 1.5px solid var(--orange);
    padding: 4px 10px;
    background: rgba(255, 87, 40, 0.08);
    transform: rotate(-1.5deg);
    text-align: center;
  }
  .clip-saving-stamp .ellipsis { animation: blink 1s steps(2) infinite; }

  /* DONE */
  .clip-saved-stamp {
    font-family: 'Inter', sans-serif;
    font-size: 12px; font-weight: 800;
    letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--light);
    background: var(--forest);
    border: 1.5px solid var(--teal);
    padding: 6px 14px;
    box-shadow: var(--shadow-stamp);
    transform: rotate(2.5deg);
    text-align: center;
    animation: stamp-slam 260ms cubic-bezier(0.16, 1, 0.3, 1);
    position: relative;
  }
  .clip-saved-stamp::before {
    content: ''; position: absolute; inset: -10px;
    background: radial-gradient(circle, rgba(31, 122, 63, 0.5) 0%, transparent 60%);
    border-radius: 50%;
    z-index: -1;
    animation: ink-burst 400ms ease-out;
    pointer-events: none;
  }
  .clip.is-done .clip-meta-path {
    color: var(--forest);
    text-transform: none;
    letter-spacing: 0.04em;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    opacity: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .clip-download-again {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--teal);
    text-decoration: underline;
    text-decoration-style: dashed;
    text-underline-offset: 3px;
    cursor: pointer;
    width: fit-content;
    background: none; border: none; padding: 0;
  }
  .clip-download-again:hover { text-decoration-style: solid; color: var(--orange); }
  .clip-download-again:focus-visible { outline: 2px dashed var(--orange); outline-offset: 2px; }

  /* CANCELLED */
  .clip.is-cancelled { opacity: 0.55; border-style: dashed; box-shadow: none; }
  .clip.is-cancelled .clip-title { text-decoration: line-through; text-decoration-color: var(--orange); }
  .clip-cancelled-stamp {
    font-family: 'Inter', sans-serif;
    font-size: 11px; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--teal);
    border: 1.5px dashed var(--teal);
    padding: 5px 11px;
    background: transparent;
    transform: rotate(-3deg);
    text-align: center;
  }

  /* ERROR */
  .clip.is-error {
    background:
      repeating-linear-gradient(135deg,
        var(--light) 0, var(--light) 8px,
        rgba(255, 87, 40, 0.08) 8px, rgba(255, 87, 40, 0.08) 9px);
    border-color: var(--orange);
    box-shadow: var(--shadow-card-orange);
  }
  .clip.is-error .clip-num { border-color: var(--orange); color: var(--orange); }
  .clip.is-error .clip-thumb {
    background: var(--orange);
    border-right-color: var(--orange);
    color: var(--light);
  }
  .clip.is-error .clip-thumb svg { opacity: 1; color: var(--light); }
  .clip.is-error .clip-title {
    color: var(--orange);
    font-style: italic;
    text-transform: lowercase;
  }
  .clip-err-msg {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    letter-spacing: 0.04em;
    color: var(--teal);
    margin: 2px 0 0;
  }
  .clip-err-url {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    letter-spacing: 0.02em;
    color: var(--teal); opacity: 0.5;
    margin-top: 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .clip-error-stamp {
    font-family: 'Inter', sans-serif;
    font-size: 11px; font-weight: 800;
    letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--light);
    background: var(--orange);
    border: 1.5px solid var(--teal);
    padding: 6px 12px;
    box-shadow: var(--shadow-stamp);
    transform: rotate(3deg);
    text-align: center;
  }
```

- [ ] **Step 4.2: Rebuild and verify CSS compiles**

Save. Watcher rebuilds. Reload page. No errors in DevTools.

- [ ] **Step 4.3: Commit**

```bash
git add styles/input.css static/app.css
git commit -m "$(cat <<'EOF'
design(ui): add 5 card states to riso brand system

Base clip card with halftone-overlaid thumbnail. Five states:
ready, downloading (orange border + scanning halftone progress),
done (forest-green stamp slam + ink-burst), cancelled (55% opacity
+ dashed border + strikethrough), error (warning-tape hatch).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add empty-state to input.css

**Files:**
- Modify: `styles/input.css`

- [ ] **Step 5.1: Append empty-state block**

Use Edit tool. Replace exactly:

```css
  /* === EMPTY STATE ======================================== */
  /* (added in Task 5) */

}
```

with:

```css
  /* === EMPTY STATE ======================================== */

  .queue-stack {
    max-width: 720px;
    margin: 0 auto;
    padding: 24px 28px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .empty-hint {
    text-align: center;
    padding: 36px 24px;
    color: var(--teal);
  }
  .empty-hint .arrow-up {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 24px;
    color: var(--orange);
    opacity: 0.7;
    margin-bottom: 8px;
    animation: breathe-up 3s ease-in-out infinite;
    display: inline-block;
  }
  .empty-hint .line-1 {
    font-family: 'Fraunces', serif;
    font-style: italic;
    font-size: 18px;
    color: var(--teal);
    margin: 0;
  }
  .empty-hint .line-2 {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--teal); opacity: 0.55;
    margin: 6px 0 0;
  }

}
```

- [ ] **Step 5.2: Rebuild and verify**

Save. Watcher rebuilds. No errors.

- [ ] **Step 5.3: Commit**

```bash
git add styles/input.css static/app.css
git commit -m "$(cat <<'EOF'
design(ui): add empty-state hint and queue stack styles

Soft "your clippings will appear here" hint shown until first card
lands. Breathing orange arrow animation respects reduced-motion.
Queue stack wrapper provides 720px max-width and 14px gap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add motion keyframes + reduced-motion + mobile to input.css

**Files:**
- Modify: `styles/input.css`

- [ ] **Step 6.1: Append motion + reduced-motion + mobile blocks**

Use Edit tool. Replace exactly:

```css
/* (keyframes + reduced-motion + mobile added in Task 6) */
```

with:

```css
/* ============================================================
   MOTION KEYFRAMES
   ============================================================ */

@keyframes card-in {
  0%   { opacity: 0; transform: translateY(-6px) rotate(-0.6deg); }
  60%  { opacity: 1; }
  100% { opacity: 1; transform: translateY(0) rotate(0deg); }
}

@keyframes scan {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

@keyframes stamp-slam {
  0%   { opacity: 0; transform: rotate(8deg) scale(2.2); }
  60%  { opacity: 1; }
  100% { opacity: 1; transform: rotate(2.5deg) scale(1); }
}

@keyframes ink-burst {
  0%   { opacity: 0; transform: scale(0.5); }
  20%  { opacity: 0.6; }
  100% { opacity: 0; transform: scale(2.2); }
}

@keyframes blink { to { opacity: 0; } }

@keyframes breathe-up {
  0%, 100% { transform: translateY(0); opacity: 0.55; }
  50%      { transform: translateY(-3px); opacity: 0.85; }
}

/* ============================================================
   REDUCED MOTION
   ============================================================ */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .clip { animation: none; }
  .clip-progress::after { display: none; }
  .clip-saved-stamp { animation: none; }
  .clip-saved-stamp::before { display: none; }
  .clip-saving-stamp .ellipsis { animation: none; opacity: 1; }
  .empty-hint .arrow-up { animation: none; opacity: 0.55; }
  .hero-cta.is-fetching .ellipsis { animation: none; opacity: 1; }
}

/* ============================================================
   MOBILE — viewport <= 480px
   ============================================================ */

@media (max-width: 480px) {
  .hero-stage { padding: 20px 16px 28px; }
  .hero-mark { font-size: clamp(48px, 14vw, 72px); }
  .hero-arrow { font-size: 36px; margin-left: 10px; margin-bottom: 8px; }
  .hero-tag { font-size: 17px; margin: 12px 0 24px; }
  .hero-controls {
    flex-wrap: wrap;
    gap: 8px;
  }
  .hero-cta {
    margin-left: 0;
    width: 100%;
    padding: 12px 18px;
    min-height: 44px;
  }
  .hero-pill { padding: 10px 18px; min-height: 44px; }
  .hero-corner-stamp { top: 12px; right: 12px; font-size: 8px; padding: 3px 6px; }
  .hero-ticker { font-size: 9px; flex-direction: column; gap: 6px; align-items: flex-start; }
  .hero-ticker .right { align-self: flex-end; }

  /* Cards stack vertically */
  .clip { grid-template-columns: 1fr; }
  .clip-thumb {
    width: 100%; height: 96px;
    border-right: none;
    border-bottom: 1.5px solid var(--teal);
  }
  .clip.is-downloading .clip-thumb {
    border-bottom-color: var(--orange);
    border-right-color: transparent;
  }
  .clip.is-error .clip-thumb {
    border-right-color: transparent;
    border-bottom-color: var(--orange);
  }
  .clip-action {
    border-left: none;
    border-top: 1px dashed rgba(26, 53, 64, 0.25);
    flex-direction: row;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
  }
  .clip-picker { flex: 1; }
}
```

- [ ] **Step 6.2: Rebuild and verify**

Save. Watcher rebuilds. No errors.

- [ ] **Step 6.3: Commit**

```bash
git add styles/input.css static/app.css
git commit -m "$(cat <<'EOF'
design(ui): add motion keyframes, reduced-motion, mobile media query

Six keyframes (card-in, scan, stamp-slam, ink-burst, blink,
breathe-up). prefers-reduced-motion: reduce disables every keyframe
in a single block. Mobile media query (<= 480px) bumps tap targets
to 44px and stacks card thumbnail above body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update tailwind.config.js tokens

**Files:**
- Modify: `tailwind.config.js`

- [ ] **Step 7.1: Read current config**

Use Read tool on `/Users/kaivan108icloud.com/Downloads/trove/tailwind.config.js` to confirm contents match what's shown below.

- [ ] **Step 7.2: Replace the entire config**

Use Write tool to overwrite `/Users/kaivan108icloud.com/Downloads/trove/tailwind.config.js` with:

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        light: "var(--light)",
        teal: "var(--teal)",
        orange: "var(--orange)",
        forest: "var(--forest)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Fraunces", "Playfair Display", "Georgia", "serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        DEFAULT: "4px",
        lg: "8px",
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 7.3: Rebuild CSS**

Save. The watcher rebuilds. The compiled `static/app.css` size doesn't change much because we don't actually use Tailwind utility classes for the new tokens — they're just available if needed.

- [ ] **Step 7.4: Verify the page still renders**

Reload `http://localhost:8899`. Page still looks broken (templates still old) but no CSS errors.

- [ ] **Step 7.5: Commit**

```bash
git add tailwind.config.js static/app.css
git commit -m "$(cat <<'EOF'
chore(ui): swap Tailwind tokens to riso palette

Replace bg/surface/fg/muted/accent tokens with paper/light/teal/
orange/forest. Add display + mono font-families. Drop card
boxShadow utility (we use hard offset shadows now).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Rewrite templates/index.html (hero + empty state + toggle JS)

**Files:**
- Rewrite: `templates/index.html`

- [ ] **Step 8.1: Read current index.html**

Use Read tool on `/Users/kaivan108icloud.com/Downloads/trove/templates/index.html` to confirm structure.

- [ ] **Step 8.2: Overwrite with riso markup**

Use Write tool to overwrite `/Users/kaivan108icloud.com/Downloads/trove/templates/index.html`:

```html
{% extends "base.html" %}

{% block content %}
<div class="hero-stage">
  <span class="hero-corner-stamp">No. 001 / 2026</span>

  <div class="hero-top">
    <div class="left">
      <span class="dot"></span>
      <span>TROVE — A SAVING MACHINE FOR THE MODERN WEB</span>
    </div>
    <span class="right">EST. MMXXVI</span>
  </div>

  <div class="hero-mark-row">
    <h1 class="hero-mark">trove<span class="period">.</span></h1>
    <span class="hero-arrow" aria-hidden="true">↗</span>
  </div>

  <p class="hero-tag">
    paste a link, get the file.
    <span class="accent">no accounts, no upload limits, no telemetry.</span>
    self-hosted on your machine.
  </p>

  <form
    id="fetch-form"
    class="hero-plate"
    hx-post="/api/info-card"
    hx-target="#queue"
    hx-swap="afterbegin"
  >
    <div class="hero-plate-header">
      <span>▸ <span class="step">STEP 001</span> · paste a link</span>
      <span>1000+ sources</span>
    </div>
    <div class="hero-input-row">
      <label class="sr-only" for="urls">Paste a link</label>
      <input
        id="urls"
        name="url"
        type="url"
        placeholder="https://www.youtube.com/watch?v=…"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        required
        class="hero-input"
      >
    </div>
    <input type="hidden" name="format" id="format-input" value="video">
    <div class="hero-controls">
      <div class="hero-toggle" role="group" aria-label="Format">
        <button type="button" class="hero-pill is-active" data-format="video">MP4</button>
        <button type="button" class="hero-pill" data-format="audio">MP3</button>
      </div>
      <button type="submit" class="hero-cta" id="fetch-btn">Save ↗</button>
    </div>
  </form>

  <div class="hero-ticker">
    <span>▼ youtube · tiktok · instagram · vimeo · 1000+</span>
    <span class="right">MIT · SELF-HOSTED · v1.0</span>
  </div>
</div>

<div class="queue-stack">
  <div id="empty-hint" class="empty-hint">
    <div class="arrow-up" aria-hidden="true">↑</div>
    <p class="line-1">your clippings will appear here.</p>
    <p class="line-2">paste a link above to begin</p>
  </div>
  <div id="queue" aria-live="polite"></div>
</div>

<script nonce="{{ g.csp_nonce }}">
  // Format toggle (vanilla — strict CSP blocks Alpine's eval-based directives)
  document.querySelectorAll('.hero-toggle .hero-pill').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.hero-toggle .hero-pill').forEach(function (c) {
        c.classList.remove('is-active');
      });
      btn.classList.add('is-active');
      document.getElementById('format-input').value = btn.dataset.format;
    });
  });

  // Fetch button label state, reset form, persist format selection across resets,
  // hide empty-state hint as soon as first card lands
  (function () {
    var form = document.getElementById('fetch-form');
    var btn = document.getElementById('fetch-btn');
    var hint = document.getElementById('empty-hint');
    form.addEventListener('htmx:beforeRequest', function () {
      btn.disabled = true;
      btn.classList.add('is-fetching');
      btn.innerHTML = 'Fetching<span class="ellipsis">…</span>';
    });
    form.addEventListener('htmx:afterRequest', function () {
      btn.disabled = false;
      btn.classList.remove('is-fetching');
      btn.textContent = 'Save ↗';
      var keepFormat = document.getElementById('format-input').value;
      form.reset();
      document.getElementById('format-input').value = keepFormat;
      document.querySelectorAll('.hero-toggle .hero-pill').forEach(function (c) {
        c.classList.toggle('is-active', c.dataset.format === keepFormat);
      });
      // Hide empty-state hint once a card has landed
      if (hint && document.querySelectorAll('#queue .clip').length > 0) {
        hint.style.display = 'none';
      }
    });
  })();
</script>
{% endblock %}
```

- [ ] **Step 8.3: Smoke test the hero**

Reload `http://localhost:8899`. Expected:

- Cream paper background with subtle grain
- "TROVE — A SAVING MACHINE FOR THE MODERN WEB" mono ribbon at top with orange dot and "EST. MMXXVI" right-aligned
- Massive "trove." wordmark in italic Fraunces, period in offset orange
- Orange ↗ arrow next to wordmark
- Italic tagline with orange middle clause
- Cream plate with teal header bar, input, toggle, orange "Save ↗" stamp button
- Source ticker below
- Corner "No. 001 / 2026" stamp rotated +7°
- Below: empty-state hint with breathing arrow and italic "your clippings will appear here."

- [ ] **Step 8.4: Smoke test interactions**

- Click MP4 → MP3 → toggle should swap (instant since we don't have the JS-driven slide animation; CSS transition handles bg/color smoothly)
- Click in input → border + shadow flip orange via `:focus-within`
- Type a URL → cursor is orange, color blinks
- Press Save → button label flips to "Fetching…" with blinking ellipsis (cards still render in old card.html style — that's Task 9)

- [ ] **Step 8.5: Commit**

```bash
git add templates/index.html
git commit -m "$(cat <<'EOF'
design(ui): rewrite hero for riso redesign

New hero stage with corner stamp, mono top strip, italic Fraunces
wordmark with offset orange period, decorative arrow, italic
tagline, plate with focus-within state flip, segmented toggle,
brass-stamp Save button, footer ticker. Empty-state hint added
above #queue, hidden via JS once first card lands.

Cards still render with old card.html styling until the next
commit; site is intentionally inconsistent on this branch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Rewrite templates/partials/card.html (5 states)

**Files:**
- Rewrite: `templates/partials/card.html`

- [ ] **Step 9.1: Read current card.html**

Use Read tool on `/Users/kaivan108icloud.com/Downloads/trove/templates/partials/card.html` to confirm Jinja conditionals (`error`, `ready`, `queued`/`downloading`, `done`, `cancelled`).

- [ ] **Step 9.2: Overwrite with riso card markup**

Use Write tool to overwrite `/Users/kaivan108icloud.com/Downloads/trove/templates/partials/card.html`:

```html
{% set msgs = {
  "unsupported_url": "URL not supported",
  "private_or_unavailable": "video private or unavailable",
  "geo_restricted": "not available in your region",
  "rate_limited": "rate limited — try again in a minute",
  "auth_required": "site needs login (set TROVE_COOKIES_FROM_BROWSER)",
  "network": "network problem — check connection",
  "timeout": "request timed out",
  "busy": "server busy — try again",
  "unknown": "something went wrong",
} %}

{% macro thumb(card) %}
<div class="clip-thumb">
  {% if card.thumbnail %}
    <img src="{{ card.thumbnail }}" alt="" loading="lazy">
  {% else %}
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <rect x="2" y="2" width="20" height="20" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>
    </svg>
  {% endif %}
</div>
{% endmacro %}

{% if card.kind == "error" %}
<div class="clip is-error">
  <div class="clip-thumb">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
      <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16" x2="12" y2="16.5"/>
    </svg>
  </div>
  <div class="clip-body">
    <p class="clip-title">unable to fetch</p>
    <p class="clip-err-msg">{{ msgs.get(card.category, msgs["unknown"]) }}</p>
    {% if card.url %}
      <p class="clip-err-url">{{ card.url }}</p>
    {% endif %}
  </div>
  <div class="clip-action">
    <span class="clip-error-stamp">✕ ERROR</span>
  </div>
</div>

{% elif card.kind == "ready" %}
<div class="clip">
  {{ thumb(card) }}
  <div class="clip-body">
    <p class="clip-title">{{ card.title or "untitled" }}</p>
    <p class="clip-meta">
      {{ (card.uploader or "—") | upper }}
      {% if card.duration %}
        <span class="sep">/</span>{{ "%d:%02d"|format(card.duration // 60, card.duration % 60) }}
      {% endif %}
      <span class="sep">/</span>READY
    </p>
  </div>
  <form
    class="clip-action"
    hx-post="/api/download-card"
    hx-swap="outerHTML"
    hx-target="closest .clip"
  >
    <input type="hidden" name="url" value="{{ card.url }}">
    <input type="hidden" name="title" value="{{ card.title or '' }}">
    <input type="hidden" name="thumbnail" value="{{ card.thumbnail or '' }}">
    <input type="hidden" name="format" value="{{ card.format or 'video' }}">
    {% if card.formats and (card.format or 'video') == 'video' %}
      <select name="format_id" class="clip-picker">
        {% for f in card.formats %}
          <option value="{{ f.id }}">{{ f.label }}</option>
        {% endfor %}
      </select>
    {% endif %}
    <button type="submit" class="clip-save">Save ↗</button>
  </form>
</div>

{% elif card.kind in ("queued", "downloading") %}
<div
  class="clip is-downloading"
  data-job-id="{{ card.id }}"
  hx-get="/api/status-card/{{ card.id }}"
  hx-trigger="every 2s"
  hx-swap="outerHTML"
>
  {{ thumb(card) }}
  <div class="clip-body">
    <p class="clip-title">{{ card.title or "untitled" }}</p>
    <p class="clip-meta">SAVING IN PROGRESS</p>
  </div>
  <div class="clip-action">
    <span class="clip-saving-stamp">Saving<span class="ellipsis">…</span></span>
  </div>
  <div class="clip-progress"></div>
</div>

{% elif card.kind == "done" %}
<div class="clip is-done">
  {{ thumb(card) }}
  <div class="clip-body">
    <p class="clip-title">{{ card.title or "untitled" }}</p>
    <p class="clip-meta clip-meta-path">→ ~/Downloads/{{ card.filename or "" }}</p>
    <a
      href="/api/file/{{ card.id }}"
      download="{{ card.filename or '' }}"
      class="clip-download-again"
    >↓ download again</a>
  </div>
  <div class="clip-action">
    <span class="clip-saved-stamp">✓ saved</span>
  </div>
</div>

{% elif card.kind == "cancelled" %}
<div class="clip is-cancelled">
  <div class="clip-thumb">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <rect x="2" y="2" width="20" height="20" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>
    </svg>
  </div>
  <div class="clip-body">
    <p class="clip-title">cancelled</p>
    <p class="clip-meta">CANCELLED BY USER</p>
  </div>
  <div class="clip-action">
    <span class="clip-cancelled-stamp">cancelled</span>
  </div>
</div>

{% else %}
<div class="clip is-error">
  <div class="clip-body">
    <p class="clip-err-msg">{{ msgs.get(card.category, msgs["unknown"]) }}</p>
  </div>
</div>
{% endif %}
```

- [ ] **Step 9.3: Test the full save flow**

In the browser:

1. Reload `http://localhost:8899`. Empty state visible with breathing arrow.
2. Paste a YouTube URL in the input. The cursor should blink orange.
3. Click "Save ↗". Button label flips to "Fetching…" with blinking ellipsis.
4. After ~2s, a Ready card lands at top of `#queue`. Empty-state hint disappears. Title in Fraunces, meta in mono, quality picker if video, "Save ↗" stamp at -1° rotation.
5. Click the card's "Save ↗". Card flips to downloading: orange border + shadow, halftone progress strip scanning, blinking "Saving…" stamp.
6. Wait for download to complete. Card flips to done: green "✓ saved" stamp slams down with a green ink-burst ripple. Path renders in green. "↓ download again" link below. Browser auto-downloads the file.

If this works end-to-end, the redesign is functionally complete.

- [ ] **Step 9.4: Test error path**

Paste an invalid URL like `https://youtube.com/watch?v=invalid_xxx`. Click Save. Expect an error card: hatch background, orange thumbnail, italic orange title "unable to fetch", error message in mono, source URL truncated, "✕ ERROR" stamp at +3°.

- [ ] **Step 9.5: Test cancel path**

Start a download. While downloading (orange border + scanning progress), close the tab. Reopen `http://localhost:8899` — the card should be in cancelled state (55% opacity, dashed border, strikethrough title, "cancelled" stamp).

- [ ] **Step 9.6: Run pytest**

```bash
pytest tests/
```

Expected: all tests pass.

- [ ] **Step 9.7: Commit**

```bash
git add templates/partials/card.html
git commit -m "$(cat <<'EOF'
design(ui): rewrite card.html for riso 5-state design

Five card states (error, ready, queued/downloading, done, cancelled)
re-skinned. Same Jinja conditionals, same htmx polling/swap targets,
same form action endpoints. clip-* class names; thumbnail SVG
fallback preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Delete unused alpine.min.js

**Files:**
- Delete: `static/vendor/alpine.min.js`

- [ ] **Step 10.1: Verify Alpine is not referenced**

Run:

```bash
grep -rn "alpine" templates/ static/ styles/ 2>/dev/null
```

Expected: zero results in templates or styles. Only the file itself in `static/vendor/` if grep includes binaries.

If anything references it, stop and investigate.

- [ ] **Step 10.2: Delete the file**

```bash
rm /Users/kaivan108icloud.com/Downloads/trove/static/vendor/alpine.min.js
```

- [ ] **Step 10.3: Verify the page still works**

Reload `http://localhost:8899`. The full save flow from Task 9.3 should still work end-to-end. No 404 in network tab.

- [ ] **Step 10.4: Commit**

```bash
git add -u static/vendor/
git commit -m "$(cat <<'EOF'
chore: remove unused alpine.min.js

Vendored but never loaded — strict CSP blocks Alpine's eval-based
directives. The format-toggle JS is vanilla JS in a CSP-nonce
script block in index.html.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Manual QA pass

**Files:**
- (none — verification only)

Run through every item in spec §9 (Manual QA Checklist). For each item, file a follow-up commit if a defect is found. The redesign is not ready to merge until every item passes.

- [ ] **Step 11.1: Hero responsiveness**

Resize the browser through 1440px / 1024px / 768px / 375px / 320px. Verify:

- Wordmark scales via `clamp()`; never overflows
- Plate stays within viewport
- Top + bottom mono strips wrap or stack on narrow viewports
- Corner stamp shrinks on mobile; doesn't overlap content

- [ ] **Step 11.2: Cursor + focus**

- Click into the input — cursor should be orange and blink at ~1.1s
- Tab through: input → MP4 → MP3 → Save. Each gets a 2px dashed orange (or teal for Save) outline at 2px offset
- Focused input flips the whole plate orange via `:focus-within`

- [ ] **Step 11.3: Toggle + Save button**

- MP4 ↔ MP3 — active pill fills teal, text flips cream
- Hover Save — shadow grows from 3px to 4px
- Press and hold Save — shadow collapses, button translates +3,+3
- Save with empty input — browser default validation pops; button can't fire

- [ ] **Step 11.4: Card lifecycle**

Run a full save on a working YouTube URL. Verify each transition:

- Fetching → ready (card-in animation: slide + slight rotate)
- Ready → downloading (border + shadow flip orange, halftone progress scans)
- Downloading → done (green stamp slams down with ink-burst, path renders in forest green, browser auto-downloads file)
- "↓ download again" link works

- [ ] **Step 11.5: Error path**

Paste an invalid URL. Verify:

- Hatch background (warning-tape feel)
- Orange thumbnail with cream error icon
- Italic orange lowercase title
- Mono error message + truncated URL
- "✕ ERROR" stamp at +3°

- [ ] **Step 11.6: Cancel path**

Start a download, close the tab mid-flight. Reopen. Verify cancelled card: 55% opacity, dashed border, strikethrough title, dashed "cancelled" stamp at -3°.

- [ ] **Step 11.7: Empty state**

Clear all cards (refresh after TTL sweep, or run `curl -X DELETE …` if applicable, or just open in a fresh incognito window). Verify the empty-state hint with breathing orange arrow renders.

- [ ] **Step 11.8: Reduced motion**

In macOS System Settings → Accessibility → Display → Reduce motion: toggle ON. Reload. Verify:

- Cursor is solid orange (no blink)
- Halftone progress strip is static (no scanning highlight)
- Saved stamp lands instantly with no ink-burst
- Card-in animation suppressed (cards just appear)
- Breathing arrow is static at 0.55 opacity
- "Fetching…" ellipsis is static

Toggle OFF afterward.

- [ ] **Step 11.9: Mobile**

DevTools device emulator → iPhone SE (375×667) and iPhone 14 (390×844). Verify:

- Wordmark clamps to ~56–72px and doesn't overflow
- Hero CTA spans full width; Save button at least 44px tall
- Toggle pills 44px tall
- Cards: thumbnail full-width on top, body below, action row at bottom
- Top + bottom strips wrap if needed

- [ ] **Step 11.10: Contrast**

Use DevTools color picker on:

- Teal `#1A3540` text on cream `#F1E6CC` body — should be ≥ 7:1
- Forest `#1F7A3F` on cream — should be ≥ 4.5:1
- Cream text on orange `#FF5728` (CTA, error stamp) — should be ≥ 4.5:1

If anything fails, raise it before merge.

- [ ] **Step 11.11: CSP nonces**

DevTools Network tab on a page reload. Find the inline `<script>` blocks in the response HTML. Verify each has a `nonce="…"` attribute. Confirm no console errors about blocked inline scripts.

- [ ] **Step 11.12: pytest**

```bash
pytest tests/
```

All tests pass.

- [ ] **Step 11.13: Console + network clean**

DevTools Console tab — no errors, no warnings (other than expected Google Fonts load info).

DevTools Network tab — no 404s, no failed requests.

- [ ] **Step 11.14: Color-scheme: light**

In macOS System Settings → Appearance → Dark, switch to Dark mode. Reload `http://localhost:8899`. Page should stay cream-paper, NOT auto-invert. (Color-scheme meta in base.html does this.)

- [ ] **Step 11.15: Cross-browser quick check**

Open the app in:

- Safari (latest)
- Chrome (latest)
- Firefox (latest)

Verify Fraunces renders with the WONK axis (the wordmark should look slightly off-kilter in italic). On older browsers WONK gracefully falls back to default Fraunces.

- [ ] **Step 11.16: First contentful paint**

DevTools Lighthouse tab → Mobile, Performance only. Run audit.

Expected: First Contentful Paint < 1.5s on simulated slow 3G. If higher, investigate.

If all 16 sub-checks pass, the redesign is ready to merge.

- [ ] **Step 11.17: Optional final polish commit**

If you tweaked anything during QA (e.g. tightened spacing, fixed contrast on a state), commit it now:

```bash
git add styles/input.css static/app.css templates/
git commit -m "$(cat <<'EOF'
fix(ui): QA polish from manual sweep

[describe what you tweaked]

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification matrix

After all tasks complete, the branch produces:

| Surface | Expected |
|---|---|
| `templates/base.html` | Loads Fraunces + Inter + IBM Plex Mono; `color-scheme: light` meta present; VT323 dropped |
| `styles/input.css` | ~500 lines; CSS variables for two-ink palette; all hero, card, empty-state classes; six keyframes; reduced-motion + mobile media queries |
| `tailwind.config.js` | Tokens map to `--paper / --light / --teal / --orange / --forest` plus three font families |
| `static/app.css` | Compiled fresh from input.css |
| `templates/index.html` | Hero stage with corner stamp, top strip, wordmark with offset orange period, italic tagline, plate, segmented toggle, brass CTA, source ticker; empty-state hint above `#queue`; vanilla-JS toggle + htmx fetch listeners in CSP-nonce script |
| `templates/partials/card.html` | Five states: error / ready / queued + downloading / done / cancelled; thumbnail SVG fallback preserved; same Jinja conditions and htmx attributes as today |
| `static/vendor/` | Only `htmx.min.js` remains; alpine.min.js deleted |
| `app.py · jobs.py · runner.py · safety.py` | Unchanged |
| `pytest tests/` | All tests pass |
| Manual QA §11 | All 16 sub-checks pass |
