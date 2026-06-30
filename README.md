# event-studies

Pre-registered, daily event-study engine + dashboard for systematic forward-return analysis, fed by a private research-email intake pipeline.

**Status:** Phase 0 scaffold (2026-06-30). Spun out of `Global-ETF-Trend-Scanner` so the event catalogue can grow its own instrument universe beyond the scanner's fixed 56-ETF cross-asset set.

## What this is

```
research intake (private)  →  event catalogue  →  daily event engine  →  dashboard + live monitor
```

- **Event engine** finds historical triggers, collapses clustered triggers into independent episodes, and tests forward-return distributions vs an unconditional baseline with a random-entry Monte Carlo + regime split. Every catalogue event REQUIRES a written rationale before admission.
- **Multi-universe.** Instruments are config-driven (`universes.json`); each event names the universe it needs. Starts focused (SPY, EEM, TLT, GLD, SLV) and grows as events require.
- **Private intake.** Research emails (SentimenTrader, etc.) are licensed IP; they are digested in `private/` (gitignored) and NEVER published. Only mechanical event definitions, my own rationale, and OUR computed numbers ever reach the public dashboard.

## Layout

```
event-studies/
├── universes.json         # instrument universes (config-driven)
├── catalogue/catalogue.json
├── engine/                # events.js, events_live.js, indicators.js  (Phase 1)
├── scripts/               # fetch_history.js (universe-driven), pipeline.py  (Phase 1)
├── data/                  # daily history per ticker (gitignored, regenerable)
├── private/               # IP firewall: email pipeline, digests, candidates, tickets (gitignored)
├── docs/index.html        # GitHub Pages output  (Phase 3)
└── template.html          # dashboard source  (Phase 3)
```

## Build (once Phase 1 lands)

```
node scripts/fetch_history.js     # fetch the union of tickers the catalogue references
node engine/events.js             # → events_results.json
python scripts/pipeline.py        # inject results → docs/index.html
```

See `private/NEW-REPO-PLAN.md` (carried over from the scanner) for the full migration plan.

_Last updated: 2026-06-30._
