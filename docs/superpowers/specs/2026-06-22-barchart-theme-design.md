# Barchart-Style Theme for FinAgent Report

**Date:** 2026-06-22
**Status:** Approved pending user spec review
**Scope:** Visual theme only — `templates/report.html.j2` `<style>` block + masthead markup.

## Goal

Give the FinAgent report the overall *vibe* of Barchart.com's research/news pages:
a corporate-financial newsroom feel — clean white surfaces, an institutional
(deeper, less vivid) blue accent, neutral cool grays, Barchart's Roboto
typography, and a faithful white masthead with a slim top utility strip.

The report's structure (tabs, cards, tables, dark mode, all JS behavior) is
already close to this aesthetic, so the work is a **theme retune**, not a
rebuild.

## Decisions (from brainstorming)

- **Overall vibe** match, implementer's judgment on specifics.
- **Font:** Load **Roboto** via Google Fonts, falling back to the existing
  system stack if the network request fails.
- **Strength:** Stronger match — restyle the masthead to mirror Barchart's
  actual chrome.
- **Correction applied:** Barchart's real masthead is *white*, not a navy bar.
  A faithful "stronger match" mirrors that white chrome (slim utility strip +
  white logo/nav row, blue used only as an accent), rather than adding a
  colored block.

## Non-Goals

- No change to template logic, Jinja variables, data flow, or JS.
- No new sections or components.
- No restructuring of tables/cards beyond color/spacing/typographic tuning.

## Design

All changes live in the single `<style>` block of `templates/report.html.j2`
plus a small markup tweak to the header region. Reversible in one commit.

### 1. Fonts

In `<head>`, add (before the existing `<style>`):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap" rel="stylesheet">
```

Update `body` font-family to:
`'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
(`display=swap` + the system fallback means no blocking / graceful offline.)

### 2. Light palette retune (`:root`)

| Variable | From | To | Rationale |
|---|---|---|---|
| `--accent` | `#2563eb` | `#0b5cab` | Barchart institutional blue |
| `--accent-light` | `#eff6ff` | `#eef4fb` | cooler blue tint |
| `--accent-border` | `#bfdbfe` | `#bcd6ef` | matches new accent |
| `--text` | `#111827` | `#1a2330` | warmer charcoal |
| `--text-secondary` | `#6b7280` | `#566072` | slightly cooler |
| `--bg` | `#f8f9fb` | `#f4f6f8` | Barchart cool page gray |
| `--border` | `#e5e7eb` | `#dfe3e8` | cooler hairline |
| `--green` | `#16a34a` | `#16864d` | finance up, slightly deeper |
| `--red` | `#dc2626` | `#cc1f1f` | finance down |

`.btn-primary:hover` accent-dark `#1d4ed8` → `#08487f`.
Semantics for buy/sell/hold pills, risk levels, etc. are preserved (they key
off these variables).

### 3. Dark mode retune (`[data-theme="dark"]`)

- `--accent`: `#60a5fa` → `#5fa3e0` (lighter version of new blue, stays readable).
- `--accent-border`: align to `#0b5cab`.
- Other dark vars unchanged.

### 4. Masthead (Barchart-faithful, white chrome)

Current header is one white `.header` containing title/meta + controls, then
the `.tab-bar`. Restyle to a Barchart-like masthead:

- **Top utility strip** (`.topbar`): full-width, very light (`--surface` with a
  bottom hairline), compact (`~28px`), holding the small "Updated …" meta on the
  left and the language/theme/history/admin controls on the right.
- **Brand row** (existing `.header-top`, restyled): white background, the
  **FinAgent** wordmark in the institutional blue, heavier weight (Roboto 900),
  slightly larger; Add Stock / Refresh primary actions remain right-aligned.
- **Nav row** (`.tab-bar`, mostly unchanged): white, dark-text tabs, blue active
  underline — already matches Barchart's nav. Tighten padding to sit under the
  brand row cleanly.

This is a CSS + light markup reflow of the existing header elements — no control
is removed; the toggle/admin/history buttons move from the brand row into the
top utility strip.

### 5. Typographic touches

- `.section-title`: 20px → 21px, tracking `-0.4px`, weight 700 (editorial headline feel).
- `.ticker-symbol`: weight 800 → 900 (Roboto Black), tracking `-0.6px`.
- `.header-title` (wordmark): Roboto 900, blue, ~17px, letter-spacing `-0.3px`.
- Body stays 13px (dense-data legibility preserved).

## Verification

- Regenerate / open `output/index.html` and visually compare before/after.
- Confirm: light mode looks Barchart-like; dark-mode toggle still works and is
  legible; tabs, drag, modals, admin mode, sparklines unaffected.
- Confirm Roboto loads and the system fallback renders if fonts are blocked.
- No Jinja/JS changes → existing tests unaffected.

## Risk / Rollback

Single-file, presentation-only change. Revert the commit to fully restore the
prior theme.

## Addendum (2026-06-22) — Barchart layout components

Follow-up: adopt Barchart's story-page *structure/components* while keeping the
tabbed dashboard (user chose "keep tabs + Barchart chrome" + all components).
All in `templates/report.html.j2`:

- **Announcement bar** — thin full-width disclaimer strip at the very top.
- **Nav bar** — brand + nav links (Watchlist / News / Macro & Geo) + ticker
  **search box** + admin actions + **Log In** (the relocated admin key). Search
  jumps to a tracked tab or opens Add-Stock prefilled; nav links scroll/switch.
- **Article hero + byline** — per ticker: eyebrow symbol, large company-name
  headline, byline row ("FinAgent Research · Updated <date> · Auto-generated").
- **Inline quote box** — symbol, price, latest-session change % (computed
  client-side from `priceHistory`), sparkline.
- **News story cards** — source-initial thumbnail tiles + hover, Barchart
  "Most Popular" feel. (No image thumbnails — no asset source; initials used.)
- **Multi-column footer** — brand blurb / Data Sources / Resources + a bottom
  disclaimer & generated-date bar, full-width outside `.page`.

New strings are static English (no new i18n keys) to avoid breaking the language
toggle. Verified by full mock render + light/dark screenshots.
