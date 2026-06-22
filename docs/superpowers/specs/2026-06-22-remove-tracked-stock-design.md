# Remove a tracked stock from the report page

**Date:** 2026-06-22
**Status:** Approved

## Problem

The report page's tab "x" button (`closeTab`) only writes to `localStorage` — it
hides a stock's tab in the current browser but leaves the ticker in
`config/stocks.json`, so the backend keeps generating a full report for it on
every run. There is a full **add** path (HTML modal → GitHub `workflow_dispatch`
`new_ticker` → `main.py --add-ticker` → commit config) but **no remove** path.

## Goal

Let the user permanently stop tracking a stock from the report page itself —
editing `config/stocks.json` and rebuilding the page — without a full,
API-spending report run.

## Design decisions (agreed)

- **Remove UX:** self-service from the report page (mirror the Add flow).
- **"x" stays cosmetic:** the existing per-browser `localStorage` hide is
  unchanged. A *separate*, deliberate "Stop tracking" action does the real
  removal (so a stray click can't silently drop a stock).
- **Lightweight rebuild:** removal re-renders the page from the last cached
  report context minus the removed stock — no Anthropic/data API calls.
- **Persist the cache (Option 1):** the cached context is gitignored today, so a
  fresh CI runner has nothing to render from. Commit `output/.last_context.pkl`
  so removal runs always have render data. (The same market data is already
  published openly in the HTML report, so committing it exposes nothing new.)

## Components

### 1. `main.py --remove-ticker SYM`

New early-return branch (like `--refresh-supply-chain`), no API calls:

1. Load config. If `SYM` not in `tickers[]` → log and exit 0 (idempotent).
2. Drop the `{symbol: SYM}` entry from `tickers[]`; delete
   `supply_chain_detail[SYM]`.
3. Leave `SYM` where it appears in other stocks' `upstream`/`downstream` lists
   (factual supply-chain references, not tracking decisions).
4. Save config.
5. Lightweight re-render: load `output/.last_context.pkl`, run
   `_filter_context(context, SYM)`, re-render HTML + archive (same two-pass
   archive logic as the main flow), and re-pickle the filtered context. If the
   pickle is missing, log a warning and skip render (config still updated; page
   catches up on next full run).

### 2. `_filter_context(context, symbol)` — pure helper

Returns the context with `symbol` stripped from the per-ticker collections:
`watchlist_symbols`, `ratings`, `financials`, `earnings_events`,
`insider_transactions`, `short_data`, `price_history`, `peer_table`,
`product_analysis`, `supply_chain_detail`. Leaves cross-cutting sections
(`news`, `geopolitical_themes`, `themes`) untouched. Pure and unit-testable.

### 3. Persist context cache

- Remove `output/.last_context.pkl` from `.gitignore`.
- Broaden the workflow commit step to
  `git add config/stocks.json output/.last_context.pkl`.

### 4. Workflow — `generate_report.yml`

- Add `remove_ticker` input to `workflow_dispatch`.
- Generate step: if `remove_ticker` set → `python main.py --remove-ticker SYM`
  (lightweight); else current add/section behavior.
- Existing `peaceiris` deploy publishes `./output` → `gh-pages` as usual.

### 5. Frontend — `templates/report.html.j2`

- "x" (`closeTab`) unchanged — instant `localStorage` hide.
- Per-tab "Stop tracking" affordance (small caret/kebab on the tab → one-item
  menu "Stop tracking {SYM}") → confirm modal → reuse the Add-Stock PAT +
  `workflow_dispatch` + 4-step progress machinery with a `remove_ticker`
  payload. On success, reuse `window.location.reload()`.

## Testing

No test framework exists today; add stdlib `unittest` tests:

1. `_filter_context` removes the symbol from every per-ticker collection while
   keeping another symbol intact.
2. `--remove-ticker` on a temp config + pickle drops the ticker, deletes its
   `supply_chain_detail`, and re-renders HTML with no tab for it.
3. Removing an absent symbol exits cleanly (idempotent).

## Out of scope

- Stripping the removed symbol from other stocks' upstream/downstream lists.
- Re-fetching fresh data for remaining stocks (that's the next full run's job).
