# Pre-registration — exit-rule study (event-studies book)

**Status: FROZEN. Signed off by Zhenghao 2026-07-17. Committed BEFORE any cell was computed.**
**Context: Personal / event-studies.**

*Public by design: this document contains no licensed content — it is our own study design. Committing it before the results run is the freeze. (Supersedes the working draft previously held at `private/studies/exit-rule-prereg.md`.)*

---

## 1. The question

The Overview says the horizon is *the only tested exit* — a disclaimer, not a finding. This study asks:

> **Does any simple, pre-registered exit rule beat hold-to-horizon on the existing episode set? If not, is hold-to-horizon defensible on evidence rather than by default?**

Framed for **falsification**. The default outcome (no rule clears) is a publishable result that converts the disclaimer into a tested default. A "winner" is the suspicious outcome, not the successful one.

## 2. Universe and strata — the sample is thinner than it looks

| Stratum | Members | Raw n | Independent n | Primary horizon |
|---|---|---|---|---|
| Washout book | GLD (12) + SLV (16), shared `oversold_reversion_in_downtrend` mechanism | 28 | **21 trigger clusters** | **63d (3M)** |
| SPX seasonal | `spx-strong-q2-9m-forward` | 22 | 22 (annual, non-overlapping) | **189d (9M)** |

**Measured, not assumed:** GLD and SLV fire on the same date three times (2017-07-07, 2021-08-09, 2026-06-10) and within 21 days another four times — **7 of 21 clusters contain both tickers**. One precious-metals selloff hitting two instruments is not two draws. **All washout resampling is at the CLUSTER level (21), never the episode level (28).**

Strata are **not pooled with each other** — a counter-trend washout and a long-only seasonal are different signal classes; averaging them is the dilution error already filed against the ETF-breadth composite.

Primary horizons are declared **now** to prevent horizon-shopping. Other horizons are context only.

## 3. Pre-registered exit menu — FIXED, no sweeps beyond this grid

| Cell | Rule |
|---|---|
| **E0** | **Baseline: hold to the primary horizon** |
| E1a / E1b | Fixed stop: exit if cumulative return from entry ≤ −5% / −10% |
| E2a / E2b | Trailing stop: exit if drawdown from the running peak ≥ 5% / 10% |
| E3 | Percentile trim: exit when the mark exceeds the **walk-forward** p75 at k |
| E4a / E4b / E4c | Time stop: exit at 21d / 63d / 126d |

**9 cells × 2 strata = 18. Every cell reported — winners and losers.**

Stops evaluate **close-to-close**. We hold no intraday data, so an intraday stop is not testable; close-only is the conservative and honest choice and is stated on any output.

## 4. The three ways this study could be silently wrong

1. **Overfitting the exit on a tiny, non-independent sample — the dominant risk.** 18 cells against ~21 washout clusters and 22 SPX episodes. The best-looking rule is very likely noise. *Countermeasures:* menu frozen before the run; all 18 cells reported; a survivor must clear the §6 gate, not merely rank first; block bootstrap resamples **whole trigger clusters**; n_eff reported beside every n.

2. **Look-ahead in the exit rule.** E3 uses the percentile fan; a fan built from all episodes peeks at the future. *Countermeasure:* the fan is **walk-forward** — episode *i* sees only episodes strictly before it, from its own ticker. E3 needs ≥6 precedents for a meaningful band, so early episodes are not evaluable. **To keep the comparison like-for-like, EVERY cell (including E0) is evaluated on the SAME evaluable subset** — episodes with ≥6 precedents. A no-look-ahead perturbation selftest is required: perturbing a LATER episode's prices must not change an earlier episode's E3 decision.

3. **Costs, and a rolling episode set.** Any stop/trim pays spread and fees. *Countermeasure:* **2 bps one-way, with a 2× (4 bps) conjunction** — see amendment A1 for why this does not discriminate on this menu. Separately, the daily events' Yahoo feed is capped at 10 years, so the episode set **rolls** (SLV moved 17→16 on the 2026-07-16 refresh, losing its oldest episode). A rule tuned on today's window is tuned on a window that will change; roll sensitivity is reported.

## 5. Disclosure — E4 on SPX is NOT a clean test

We have **already inspected** the SPX per-horizon p-values (6M p=0.034 significant; 9M p=0.105). A time stop at 6M would therefore be selected on knowledge we already hold. **E4 is BARRED from clearing the gate on the SPX stratum.** It is run for completeness and reported, but cannot be treated as out-of-sample. Only the washout stratum's E4 is a clean test.

## 6. Pre-declared gate — kill-on-contact

A rule is taken forward **only if it clears every condition**:

1. Beats E0 on **both** median return **and** max drawdown, **in both strata**; and
2. Survives the cluster-level block bootstrap at **≥0.90**; and
3. Holds in **≥2 of 3** chronological sub-periods; and
4. Survives at **2× costs**; and
5. Is not barred by §5.

Otherwise **E0 stands**, the Overview banner becomes an evidence-backed statement, and no exit rule is encoded. No design-around, no neighbouring-cell rescue: a failed rule is closed and any successor requires a fresh pre-registration.

## 7. Expected outcome — stated before the run

**I expect no rule to clear.** With ~13–16 independent evaluable observations, walk-forward bands and a 2× cost conjunction, this is far more likely to confirm hold-to-horizon than to beat it. Pre-committing so that a marginal "winner" is read as noise rather than discovery. The value is a **tested default**, not a new rule.

## 8. Protocol and deliverables

- This pre-registration is **frozen and committed before any computation**. Amendments are appended and timestamped **pre-results** only.
- Engine + selftests committed **before** the results run.
- One run through the frozen menu. Results filed; ledger row added; the Overview banner updated to reflect the verdict either way.
- Only a rule clearing §6 is encoded. Nothing auto-trades.

---

## Amendment A1 — logged 2026-07-17, PRE-RESULTS, before any cell was computed

Found while implementing, not after seeing numbers. Three specification gaps in §3 that must be closed in the open:

**A1.1 — Comparison window and idle capital.** §3 did not say how an early exit is measured against a full-horizon baseline. **Decision: every cell is measured over the SAME 0 → primary-horizon window; a rule that exits early holds CASH at 0% for the remainder.** This makes all cells like-for-like. Cash earns **0%, not the T-bill rate** — a deliberate conservative choice that biases *against* the early-exit rules (at 189d the un-credited yield is worth roughly 2%). This is a known limitation, stated rather than buried: it means a *losing* E4 cell cannot be cleanly separated from "we declined to credit its cash".

**A1.2 — Costs do not discriminate on this menu.** Every cell is exactly two trades (entry + exit), so the 2 bps one-way charge is a **constant across all 9 cells** and cannot change the E0-vs-Ex ranking. §6 condition 4 is therefore **reported but vacuous for this menu**. Disclosing this rather than letting a satisfied-by-construction condition pad the gate. Costs are still applied and reported at 1× and 2×.

**A1.3 — The frozen time stops do not all fit the washout horizon.** With a 63d primary horizon: **E4a (21d) is a valid test; E4b (63d) is degenerate — identical to E0 by construction; E4c (126d) exceeds the horizon and is N/A.** The menu is NOT redesigned to fix this — it is frozen. E4b's identity with E0 is instead used as an **engine sanity assert** (it must match to the cent). Consequence, stated plainly: **the only clean E4 test in the entire study is washout E4a**, since all SPX E4 cells are barred by §5.

No change to the menu, the gate, or the expected outcome.
