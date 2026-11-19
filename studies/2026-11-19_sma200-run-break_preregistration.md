# Pre-registration: first close below the 200-day after a long run → S&P 500

**STATUS: DRAFT, awaiting sign-off.** Registered 2026-11-19, before any number
was computed on our data. Once countersigned, the choices below are frozen.
Amendments after results exist are prohibited. A blocked path files a STOP,
not an edit.

## Source and IP status

The lead is a public social-media post by a sell-side strategist, reposted
widely (2026-11-18). It is **not** licensed research-email content, so the
IP firewall does not apply to the rule itself. The source's figures are
quoted below only as **declared priors** (summary rows, not the per-signal
table) so that they cannot later be presented as our evidence.

## The rule (mechanical)

- Target: S&P 500 price index (`GSPC`, Norgate `$SPX`, daily, 1950→). Price
  index, not total return, to match the source.
- Count consecutive daily closes **above** the 200-day simple moving average
  (SMA of closes through the same day: causal).
- **Trigger** on the first close at or below the SMA when the run that ended
  the day before was **≥ 150 closes**.
- Entry: trigger-day close (engine convention). Forward horizons: the engine
  standard 1W, 2W, 1M, 2M, 3M, 6M, 1Y in trading days.
- De-clustering: 63 sessions. It changes nothing in practice, because a new
  trigger needs a fresh 150-day run.
- Engine kind: `first_close_below_sma_after_run` (`engine/events.js`), tested
  by `tests/test_sma_run_break.js` (single trigger, threshold, no look-ahead).

## Three ways this could be silently wrong

1. **Wrong baseline.** The rule only fires inside a mature uptrend, so
   "all days since 1950" credits the signal with the uptrend's own drift.
   → A second Monte Carlo draws random days that themselves sit at the end of
   a ≥150-day run above the 200-day (`matchedBaseline*` fields). This is the
   comparison that decides whether there is a tilt.
2. **Threshold fishing.** "150 days" was chosen by the source, possibly
   after looking. → 150 is primary because it is the source's number, not
   ours. 100 and 200 are report-only robustness cells. If the result
   exists only at 150, that counts against it.
3. **Pseudo-replication / small n.** About 35 episodes over 75 years, with
   overlapping forward windows in the baseline. → Random-entry Monte Carlo
   with matching n. The independent-episode count is headlined. Bootstrap CI
   on the median.

Look-ahead is covered by the causal SMA and run count, and asserted in the
test by truncating the history.

## Declared statistic (chosen before results)

- **Direction:** up. **Scored on:** hit rate (`scoreOn: "hitrate"`).
  Median is secondary.
- **Primary cell:** 3M (63 sessions), N = 150. The thesis is a modest
  positive tilt over a quarter, not a short-term bounce.
- **Primary test:** the 3M hit-rate edge against the **matched (uptrend)
  baseline**, two-sided Monte Carlo p-value (`matchedPValueHit`).
- **Also reported:** the unconditional-baseline edge (what the source
  measured), all seven horizons, median MAE (worst interim drawdown), and
  the N = 100 / 200 cells.
- **Cells screened:** 7 horizons × 3 thresholds × 2 baselines = 42. One is
  primary. Everything else is context.

## Declared priors (known before registration; not evidence)

Source summary, n = 35 (12M n = 34), 1950→2026:

| | 1W | 1M | 3M | 6M | 12M |
|---|---:|---:|---:|---:|---:|
| Signal avg | −0.3% | 0.9% | 4.0% | 7.2% | 10.3% |
| Signal median | 0.3% | 1.8% | 4.3% | 7.3% | 9.5% |
| Signal % higher | 62.9% | 68.6% | 77.1% | 68.6% | 70.6% |
| All-days % higher | 56.8% | 61.8% | 66.9% | 70.8% | 74.7% |

Source-reported average max drawdown: −4.9% within 3M, −8.0% within 12M.

## Pre-committed expectations

- **Reconciliation gate:** our triggers should match the source's signal dates
  to within one session, including 1987-10-15, 2020-02-27, 2025-03-10,
  2026-03-19 and the live 2026-11-17. A count far from 35, or missing
  dates, means STOP and explain before scoring.
- **Unconditional 3M hit edge:** expected about +10pp with p around
  0.1–0.2. It should not clear 0.05.
- **Matched 3M hit edge:** expected near zero. The main risk to the thesis
  is that the "edge" is simply the uptrend.
- **Verdict mapping:**
  - Matched 3M hit edge > 0 with p < 0.10 → **MONITOR as a tilt.** Lean in,
    scaled in rather than all at once (the source's own tail: ~1 in 7 fell
    10%+ before the 3M mark).
  - Matched edge > 0 with p ≥ 0.10 → **"no-panic" gauge only.** The break
    is not a sell signal, but it is not a buy either.
  - Matched edge ≤ 0 → **IGNORE as a tilt.** Note it on the card and keep
    it only if the drawdown profile is useful.
- The live 2026-11-17 episode is excluded from the evidence and tracked
  forward by the live monitor.

## Draft catalogue card (pasted into `catalogue/catalogue.json` only after results + sign-off)

```json
{
  "id": "spx-sma200-run-break",
  "name": "S&P 500 first close below its 200-day after 150+ days above → S&P 500",
  "kind": "first_close_below_sma_after_run",
  "target": "GSPC",
  "smaPeriod": 200,
  "minRunDays": 150,
  "direction": "up",
  "scoreOn": "hitrate",
  "clusterDays": 63,
  "thesisHorizonDays": 63,
  "definition": "Trigger on the first S&P 500 close at or below its 200-day simple moving average after a run of at least 150 consecutive closes above it. The SMA and the run count use closes through the same day. Entry is the trigger-day close. Episodes are de-clustered at 63 sessions.",
  "summary": "TO BE WRITTEN FROM OUR NUMBERS.",
  "rationale": "TO BE WRITTEN FROM OUR NUMBERS (verdict against the matched uptrend baseline first)."
}
```

## Run (local; GSPC is Norgate-only and never in CI)

```
python scripts/fetch_gspc_norgate.py
# add the draft card to a scratch catalogue with a placeholder rationale, then:
EVENTS_CATALOGUE=<scratch catalogue> EVENTS_OUT=<scratch out> node engine/events.js
```
Then run it again with `minRunDays` 100 and 200 for the robustness cells.
Write up in `studies/2026-11-19_sma200-run-break_results.md`.
