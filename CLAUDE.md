# CLAUDE.md — event-studies

Project rules for the event-studies repo. Layers on top of the vault master `C:\dev\CLAUDE.md` (read that first); this file overrides where it conflicts.

## What this project is

A pre-registered, daily event-study engine + dashboard fed by a private research-email intake pipeline. Distinct from `Global-ETF-Trend-Scanner` (a trend-following tool): this is event-driven forward-return analysis with its own, growing instrument universe.

## IP firewall (hard rule)

- Research emails (SentimenTrader / Sundial Capital Research, The Market Ear, SemiAnalysis) are **paid, licensed IP** ("do not distribute / all rights reserved").
- ALL email-derived content lives under **`private/`**, which is gitignored. This repo is PUBLIC (GitHub Pages). Verify with `git check-ignore -v private/` before writing anything email-derived.
- Only a **mechanical event definition + my own written rationale + OUR computed numbers** may reach the public catalogue/dashboard. Never their prose, printed figures, or charts.
- Re-test every extracted study on our own data before it informs anything. Their numbers are leads, not facts. Human-in-the-loop: nothing enters `catalogue/catalogue.json` without my sign-off. Nothing auto-trades.

## Multi-universe data model

- Instruments are declared in `universes.json`. Each catalogue event names the universe(s) it needs (`"universe"` / `"breadthUniverse"`).
- `scripts/fetch_history.js` fetches the **union** of tickers the active catalogue references, via Yahoo v8 (Tokyo `.T` tickers supported). Output: `data/<TICKER>.json` (daily, ~10y).
- **Futures are data-gated:** continuous futures need a Norgate feed; Yahoo is unreliable. Flag and defer, do not fake.
- Current `core` universe: SPY, EEM, TLT, GLD, SLV. Grow as events require.

## Engine

- `engine/events.js` is copied from the scanner and evolves here independently (no shared module for now).
- Causal indicators only (no look-ahead). Forward returns from the trigger-day close (event-study convention).
- State the three ways the study could be silently wrong before writing detector code (vault prompting convention): pseudo-replication from overlapping windows (→ episode clustering + random-entry Monte Carlo), look-ahead in indicators (→ causal compute), multiple testing (→ record cells screened; rationale gate).

## Dashboard

- White / light theme, maximally readable, sans-serif, high contrast (vault default).
- Work on `template.html`; build to `docs/index.html` via `scripts/pipeline.py`. Never open a built file > 500KB — patch the template.

## Build

```
node scripts/fetch_history.js
node engine/events.js
python scripts/pipeline.py
npx serve docs        # local preview
```

_Last updated: 2026-06-30._
