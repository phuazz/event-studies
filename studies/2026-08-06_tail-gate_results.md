# Results — tail-gate study (E1a successor): FAIL_E0_STANDS, both strata

**Run: 2026-08-06. One run through the frozen gate.**
**Spec: `studies/2026-08-06_tail-gate_preregistration.md` (committed `1c57f34`
PROPOSED, frozen `ba4179d` on countersign, BEFORE any cell).**
**Engine: `scripts/tail_gate_study.js` (emitter) + `scripts/tail_gate_score.py`
(scorer), committed before scoring (`d970c72`). Raw output:
`private/studies/tail-gate-results.json` (gitignored, regenerable).**

## Verdict

> **FAIL_E0_STANDS in both strata. The E1a successor question is retired:
> scored on the tail-risk gate it was denied in 2026-07-17, the fixed −5%
> stop is not merely undetected — it is measurably harmful to the tail it
> was credited with protecting.**

## Reconciliation and pinning

The 2026-07-17 sample was reproduced EXACTLY (E0/E1a/E1b/E2a/E2b:
medianGross, meanGross, hit, maxDD, episode and cluster counts, both strata,
tolerance 1e-12) from `events_results.json` pinned at commit `8e9e775` —
the last change before the filed run — plus the current `data/GSPC.json`
(matured paths; equivalence proven by the reconciliation gate itself).
Phase 0 asserted no previously filed tail statistic exists. Washout: 14
episodes 2021-08 → 2025-04, 10 independent clusters. SPX seasonal: 15
episodes 1980 → 2025.

## The numbers (credited final returns; costs constant across cells, cancel)

| | T1 washout (H=63d) | T2 SPX seasonal (H=189d) |
|---|---:|---:|
| CVaR-25% E0 | −4.46% | +5.82% |
| CVaR-25% E1a | −6.57% | −4.85% |
| **ΔCVaR-25 (G1 primary)** | **−2.11pp** | **−10.67pp** |
| Cluster-bootstrap P(Δ>0) | 0.23 | 0.00 |
| Credited median E0 → E1a | +7.54% → +7.54% | +12.90% → +7.88% |
| Worst held-path DD E0 → E1a (G2) | −19.30% → −7.15% | −13.51% → −6.34% |
| G4 ex-best-cluster Δ | −5.60pp | −10.67pp |
| G5 placebo p95 / p50 Δ | +1.85pp / −0.09pp | −0.40pp / −2.48pp |
| Bars | G2, G3 pass; **G1, G4, G5 fail** | G2 passes; **G1, G3, G4, G5 fail** |

Mean SHY credit on E1a exits: **−6.1 bps** (washout — the five early exits
sit in 2021-2022, where SHY itself lost money; the credit convention is
honest, not generous) and **+23.5 bps** (SPX). Two of T2's four early exits
(1988, 1996) predate SHY's first bar and keep the original 0% convention —
declared, conservative in direction, and irrelevant to the verdict at these
margins.

## What the tail gate actually found

1. **The stop's celebrated tail cut is a PATH statistic, not an OUTCOME
   statistic.** E1a still cuts the worst held-path drawdown by 12.1pp /
   7.2pp (G2, the known prior). But on credited FINAL returns its
   CVaR-25% is 2.1pp worse than holding on the washout book and 10.7pp
   worse on SPX. The episodes that breach −5% are the ones that rebound
   by the horizon; the stop converts recoverable paths into locked losses.
2. **Anti-selection, not merely noise.** The G5 placebo assigns E1a's own
   exit durations to RANDOM episodes: its median draw (−0.09pp) beats the
   real stop (−2.11pp) on the washout book. Exiting the episodes a −5%
   breach selects is WORSE than exiting episodes at random — on a book
   whose entry signal is capitulation, the breach marks the best rebound
   candidates. This is the R2 ladder's buy-the-washout collision,
   reproduced at per-episode resolution on the event book itself.
3. **The 2026-07-17 study's self-criticism is answered.** The original
   author recorded that a median-scored gate "could not have detected" a
   tail win. Now scored on CVaR-25 with a cluster bootstrap: there is no
   tail win to detect. The honest complication is resolved against the
   stop.
4. **T2 failed exactly as pre-committed** in the registration (E0's hit
   rate is 100% at H=189; a stop can only destroy value there) — recorded
   to prevent outcome-shopping by stratum, and it played out as written.

## Report-only cells (context, no adoption path)

Every stop variant worsens credited CVaR-25 in both strata: washout E1b
−1.87pp, E2a −0.16pp, E2b −1.78pp; SPX E1b −3.88pp, E2a −9.72pp, E2b
−8.02pp. The family is uniform; E1a was not an unlucky pick.

## Limitations (stated, not buried)

- 10 / 15 independent units; the bootstrap is honest about it (T1's p of
  0.23 is not a near-miss, but the sample could not certify a marginal
  effect either way). Verdict language stays at the registered enum.
- The episode set is pinned to 2026-07-17; episodes that matured since are
  out of scope by design.
- SHY credit uses adjusted closes (distribution-adjusted); the washout
  credit is negative because 2022 was a rising-rate year — the destination
  asset's true return, not a modelling choice.

## Decision linkage (per the frozen spec)

E0 (hold to horizon) remains the event book's only exit. No read-across to
the breadth book: risk-overlay-lab R4 T1 is that book's answer
(FAIL_GATE_STANDS). Any revisit of any stop, on any book, requires a fresh
pre-registration.
