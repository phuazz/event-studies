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

## Two-stage discovery funnel (Norgate)

The catalogue above is the **confirmation** engine (hand-registered events, single-target, Yahoo ETF data). In front of it sits a **discovery** stage that mines the Norgate point-in-time US universe for candidate setups, so the catalogue is fed by evidence rather than only by research emails.

```
DISCOVERY (Norgate, cross-sectional)   →   lead sheet (private/)   →   PM sign-off   →   PROMOTION   →   catalogue (confirmation + Monte Carlo)   →   dashboard
   scripts/discovery_scan.py                private/leads/               (human)          scripts/promote_lead.py        engine/events.js
```

- **Data feed.** Norgate US via the `norgatedata` package with NDU running locally: survivorship-bias-free (US Equities Delisted database), point-in-time index membership, split/dividend adjusted. `scripts/norgate_universe.py` is the data layer; `scripts/norgate_ready.py --wait` is the STEP-0 readiness gate that refuses a stale (mid-download) feed.
- **Universe.** Point-in-time members of the S&P Composite 1500 (S&P 500 + MidCap 400 + SmallCap 600), delisted members included — the investable set at trigger date `t`. Not a whole-market OTC scan (un-investable, no clean membership).
- **Fixed archetype grammar** = the multiple-testing budget (declared up front, no free search): mean-reversion, momentum-thrust, volatility/dislocation (single-stock, cross-sectional) + breadth (index-level, computed point-in-time from constituents, target SPY). Each over a small discrete parameter grid.
- **Guards against being silently wrong:** (1) multiple testing — fixed grammar, pre-2015 discover / 2015→ OOS split, Benjamini-Hochberg FDR, cross-name robustness; (2) pseudo-replication — per-name episode clustering AND independent-market-episode (block-weighted) edge + block bootstrap + random-entry null, with the independent-episode count headlined and `<20` flagged thin; (3) survivorship/look-ahead — delisted database + point-in-time membership, delisting-aware forward returns, causal indicators, trigger-close entry, liquidity-tiered costs.
- **Output.** A ranked, thin-flagged lead sheet with baseline-vs-conditional and the full cells-tested budget, written to `private/leads/` (gitignored). Nothing auto-promotes; the dashboard is untouched.

### Run the discovery funnel (local, needs NDU running)

```
python scripts/norgate_ready.py --wait                          # STEP 0: block until the US feed is fresh
python scripts/discovery_scan.py --build-universe               # first run builds + caches the point-in-time universe
python scripts/discovery_scan.py                                # → private/leads/lead_sheet_<asof>.{md,json}, cells_tested_<asof>.csv
python scripts/promote_lead.py --asof <date> --lead <config>    # Stage 2: draft a catalogue card for a ticked lead
```

`python scripts/discovery_scan.py --selftest` runs the indicator + statistics tests offline (no Norgate needed). The discovery stage is **local and manual** — it is NOT wired into `.github/workflows/refresh.yml` (GitHub runners have no NDU).

_Last updated: 2026-07-04._
