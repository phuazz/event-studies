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
DISCOVER ─→ lead sheet ─→ VALIDATE ─→ PROMOTE ─→ CONFIRM ─→ PM sign-off ─→ catalogue ─→ dashboard
discovery_scan   private/   validate_leads  promote_lead  confirm_lead   (human)      (human paste)   engine/events.js
(drift-α gated)             (deployability) (draft card)  (cross-sectional,
                                                          pre-registered)
```

- **Data feed.** Norgate US via the `norgatedata` package with NDU running locally: survivorship-bias-free (US Equities Delisted database), point-in-time index membership, split/dividend adjusted. `scripts/norgate_universe.py` is the data layer; `scripts/norgate_ready.py --wait` is the STEP-0 readiness gate that refuses a stale feed (it reads the actual last **bar** date, not `last_quoted_date`, which NDU leaves unset on a market-closed day).
- **Universe.** Point-in-time members of the S&P Composite 1500 (S&P 500 + MidCap 400 + SmallCap 600), delisted members included — the investable set at trigger date `t`. Not a whole-market OTC scan (un-investable, no clean membership).
- **Fixed archetype grammar** = the multiple-testing budget (declared up front, no free search): mean-reversion, momentum-thrust, volatility/dislocation (single-stock, cross-sectional) + breadth (index-level, computed point-in-time from constituents, target SPY). Each over a small discrete parameter grid.
- **Edge measure = drift-adjusted alpha.** Leads are GATED and ranked on each entry's forward return minus that name's own mean forward return (episode-weighted mean CAR), NOT the raw edge or lift-vs-pooled-baseline — at long horizons the raw edge is largely market/size beta, and archetypes that select high-drift names show a fake lift. This is why an apparently strong "mean-reversion" cluster (huge raw edge) is correctly excluded: its drift-adjusted alpha is ≤ 0.
- **Guards against being silently wrong:** (1) multiple testing — fixed grammar, pre-2015 discover / 2015→ OOS split, Benjamini-Hochberg FDR, cross-name robustness; (2) pseudo-replication — per-name episode clustering AND independent-market-episode (block-weighted) edge + block bootstrap + drift-aware random-entry null, independent-episode count headlined, `<20` flagged thin; (3) survivorship/look-ahead — delisted database + point-in-time membership, delisting-aware forward returns, causal indicators, trigger-close entry, liquidity-tiered costs.
- **Stages.** *Discover* → ranked lead sheet + full cells-tested budget. *Validate* (`validate_leads.py`) → a deployability stress-test (era stability, size/sector concentration, cost headroom, selection haircut) → SIGN-OFF / WATCH / GRAVEYARD. *Promote* (`promote_lead.py`) → a catalogue-schema card + private candidate (rationale stub, `signOff.approved=false`). *Confirm* (`confirm_lead.py`) → a rigorous single-pre-registered-hypothesis re-test on the full cross-section (drift-adjusted alpha + drift-aware Monte Carlo + SPY-200d regime split + horizon decay curve + episodes-since-registration accrual) → CONFIRMED / CONFIRMED-THIN / NOT-CONFIRMED. All output lands in `private/leads/` (gitignored); nothing auto-promotes; the catalogue and dashboard are untouched until you paste an approved card yourself.

### Run the funnel (local, needs NDU running)

```
python scripts/norgate_ready.py --wait                          # STEP 0: block until the US feed is fresh
python scripts/discovery_scan.py --build-universe               # first run builds + caches the point-in-time universe
python scripts/discovery_scan.py                                # → private/leads/lead_sheet_<asof>.{md,json}, cells_tested_<asof>.csv
python scripts/validate_leads.py --asof <date>                  # deployability stress-test → private/leads/validation_<date>.{md,json}
python scripts/promote_lead.py --asof <date> --lead <config>    # draft a catalogue card for a ticked lead
python scripts/confirm_lead.py --card <config>                  # cross-sectional, pre-registered confirmation → private/leads/confirmations/
```

`python scripts/discovery_scan.py --selftest` runs the indicator + statistics tests offline (no Norgate needed). The whole funnel is **local and manual** — it is NOT wired into `.github/workflows/refresh.yml` (GitHub runners have no NDU).

## Global-ETF breadth studies (on-book, SentimenTrader-style)

A separate, on-book strand: cross-sectional breadth studies over the `global_etf` universe (single-country / regional ETFs, Norgate-fed, survivorship-free incl. delisted ETFs). `scripts/etf_breadth_engine.py` builds a five-signal breadth library + an equal-weight composite; `scripts/etf_breadth_confirm.py` pre-registers and confirms the composite-thrust hypothesis as a single test (drift-matched Monte Carlo, sub-period + regime cuts). First result (as-of 2026-07-02): a composite breadth thrust precedes emerging-market / world outperformance over 3–6 months (EEM 6M +5.97% excess, p=0.028; EFA +3.8%, p=0.022; US weakest) — full-sample significant but **era-concentrated** (strong pre-2009, dead 2010–2017, back post-2018), so CONFIRMED-WEAK / conditional on the EM secular regime. Records under `private/etf_breadth/` (gitignored). Nothing admitted to the catalogue/dashboard without sign-off.

_Last updated: 2026-07-04._
