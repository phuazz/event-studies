# Pre-registration — tail-scored gate for tail-truncating exit rules (E1a successor)

**STATUS: PROPOSED 2026-08-06 (Thursday) — committed to timestamp the
registration BEFORE any cell exists. Freezes on ZH sign-off; no cell may
run before sign-off. Amendments after results exist are prohibited; a
blocked path files a STOP, not an edit.**

Successor to `studies/2026-07-17_exit-rule_preregistration.md` (b7dd2cd)
and its results (`studies/2026-07-17_exit-rule_results.md`), which closed
E1a under a median-scored gate the author recorded as structurally blind to
tail truncation, and named this study: *"risk-scored gate (maxDD / tail
CVaR) for tail-truncating exit rules — the median criterion cannot see
them."* The breadth-book variant of this question is ALREADY ANSWERED —
risk-overlay-lab R4 T1 scored the fixed −5% stop on tail bars there and
returned FAIL_GATE_STANDS — so this study scores the EVENT BOOK only.

## Declared priors (known before this registration — cannot serve as evidence)

From the filed 2026-07-17 tables, both known to the drafter and the owner:

| Stratum | Cell | median | worst path maxDD | hit |
|---|---|---:|---:|---:|
| Washout (GLD+SLV, H=63d, 14 ep / 10 clusters) | E0 | +7.50% | −19.30% | 71% |
| Washout | E1a (fixed −5%) | +7.50% | −7.15% | 64% |
| SPX seasonal (H=189d, 15 ep) | E0 | +12.86% | −13.51% | 100% |
| SPX seasonal | E1a | +7.84% | −6.34% | 73% |

Because the maxDD improvements are already known, they are demoted to a
floor check (G2) and CANNOT be the primary bar. The primary (G1) is a
statistic never previously computed for these cells — per-episode CVaR —
and Phase 0 asserts that no tail statistic for any exit cell exists in the
filed results, raw JSON, or ledger rows; if one is found, STOP and
re-draft with that number declared.

**Expected outcomes, pre-committed (§7 convention of the original study):**
T1 (washout) is the live case — median untouched, tail case real. T2 (SPX)
is expected to FAIL: E0's hit rate is 100% at H=189d and E1a cut the median
by 5.02pp; a stop can only hurt a stratum whose every episode ends
positive. Registering T2 anyway prevents outcome-shopping by stratum.

## Registered trials (2 — none may be added after results exist)

- **T1 — E1a (fixed −5% stop) on the washout stratum.**
- **T2 — E1a (fixed −5% stop) on the SPX seasonal stratum.**

Report-only, excluded from the pool, no adoption path: E1b, E2a, E2b
re-scored under the same gate (context for the stop family); per-cell cash-
credit magnitudes. E3 / E4 are not tail-truncating rules and are excluded
entirely.

## Mechanics

- **Sample pinned to the 2026-07-17 snapshot.** The episode set is NOT
  refreshed (the set rolls with the 10y window; re-fetching would change
  the sample after the rule was observed). Reconciliation gate: the engine
  must reproduce the filed E0 and E1a rows above exactly before any new
  scoring; failure ⇒ STOP.
- **Close-only execution unchanged** (a −5% stop realised −7.15%;
  gap-through is preserved, never assumed away).
- **Cash-credit fix (the filed A1.1 limitation).** Exited capital earns the
  SHY daily total-return series from exit to horizon, applied uniformly to
  every exit cell in both registered and report-only sets. E0 is unchanged
  by construction (it never exits). This correction favours challengers and
  is declared as a bias fix, not a knob; per-cell credit magnitude is
  reported (filed estimate: ~2pp at H=189d).

## Gate — ALL bars required per trial, any fail ⇒ FAIL_E0_STANDS

- **G1 (primary, new evidence): CVaR-25% improves.** Mean of the worst
  ⌈N/4⌉ per-episode final H-returns (cash-credited) improves vs E0, with
  bootstrap P(improvement > 0) ≥ 0.90 — resampling INDEPENDENT CLUSTERS
  (washout: the 10 clusters; SPX: episodes as units, declared the weaker
  independence). Same 0.90 bar height as the original gate. CVaR-25%, not
  CVaR-10%: on ≤ 15 units the worst decile is one episode, and a
  one-episode case is the R2/R4 failure mode, not evidence.
- **G2 (floor check, known prior): worst per-episode path maxDD improves
  ≥ 3pp.** Both trials clear this on the filed numbers; it exists to bind
  any re-run drift, not as evidence.
- **G3 (median-harm cap): cash-credited median not worse than E0 by
  > 1.0pp.** The tail gate must not smuggle in a centre-destroyer.
- **G4 (ex-best-cluster): remove the single cluster (washout) / episode
  (SPX) with the largest improvement; G1's sign must hold on the
  remainder** (sign only; the bootstrap is not repeated on the reduced
  sample).
- **G5 (random-exit placebo): G1's improvement exceeds the p95 of 200
  seeded random-exit draws matched per episode on fire frequency and exit
  duration** ("any early exit in a drawdown-prone window would do" killed
  explicitly — the R4 B6 machinery pattern).

**STOP rules:** reconciliation failure; < 8 independent units usable in a
stratum; discovery of a previously filed tail statistic (above).

## Verdict enum and decision linkage

Per trial: **TAIL_CASE_REVIEW** (all bars pass) / **FAIL_E0_STANDS** /
**STOP**. TAIL_CASE_REVIEW adopts NOTHING: E0 (hold to horizon) remains
the event book's only exit until a separate signed decision, made under
entry-point discipline. Explicitly NO read-across to the breadth book:
R4 T1 is that book's answer (FAIL_GATE_STANDS, named observation); any
revisit there requires its own fresh registration and carries the R4
multiplicity caveat. A FAIL here retires the E1a successor question:
tested on the gate it was denied, and still short.

## Three ways this could be silently wrong, and the guards

1. **Design-around** — a gate re-shaped around the cell it is known to
   favour. Guards: the declared-priors table above; known quantities
   demoted to floor checks; the primary is a never-computed statistic with
   a Phase 0 existence assertion; expected outcomes pre-committed
   including an expected T2 FAIL; amendment prohibition.
2. **Tail estimation on ≤ 15 units** — one rescued episode dressed as a
   distributional claim. Guards: CVaR-25% not CVaR-10%; cluster-level
   bootstrap; G4 ex-best-cluster; verdict language capped at "case
   review", never "demonstrated".
3. **Cash-credit distortion** — the fix quietly flattering challengers.
   Guards: uniform application from the actual SHY series across all exit
   cells; per-cell magnitude reported; G3 keeps the median honest; E0
   untouched by construction.

## Sign-off asks (five)

1. Two registered trials only (E1a per stratum); E1b/E2a/E2b report-only.
2. G1 CVaR-25% with cluster bootstrap as the sole primary; G2 demoted to
   a floor check because its value is a known prior.
3. The cash-credit fix applied uniformly, magnitude reported.
4. STOP at < 8 independent units; sample pinned to the filed snapshot.
5. No breadth-book read-across; a pass opens an event-book adoption
   discussion only.

*Prepared 2026-08-06 by Claude (Fable) at ZH's direction, in the same
session that registered risk-overlay-lab SPEC_r5. Freezes on ZH sign-off
(any blind amendment recorded in this file before any cell).*
