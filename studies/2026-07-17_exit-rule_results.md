# Results — exit-rule study (event-studies book)

**Run: 2026-07-17. One run through the frozen menu.**
**Spec: `studies/2026-07-17_exit-rule_preregistration.md` (committed `b7dd2cd`, BEFORE any cell was computed).**
**Engine: `scripts/exit_rule_study.js` (10 selftests green pre-run). Raw output: `private/studies/exit-rule-results.json`.**

---

## Verdict

> **NO RULE CLEARS THE §6 GATE. E0 (hold to horizon) STANDS.**

This is the outcome **pre-committed in §7 before the run**: *"I expect no rule to clear… the value is a tested default, not a new rule."* The Overview's "the horizon is the only tested exit" is now an **evidence-backed statement rather than a disclaimer**. That was the point of the exercise.

## The numbers

### Washout book (GLD+SLV) — H=63d, 14 evaluable episodes / **10 independent clusters**

| Cell | Rule | med (1×) | maxDD | hit | boot | sub | flag |
|---|---|---|---|---|---|---|---|
| **E0** | **hold to horizon** | **+7.50%** | −19.30% | 71% | — | — | |
| E1a | fixed stop −5% | +7.50% | **−7.15%** | 64% | 0.00 | 0/3 | |
| E1b | fixed stop −10% | +7.50% | −11.41% | 71% | 0.00 | 0/3 | |
| E2a | trailing stop 5% | +0.21% | −7.15% | 57% | 0.01 | 1/3 | |
| E2b | trailing stop 10% | +5.25% | −9.13% | 64% | 0.05 | 1/3 | |
| E3 | trim above wf p75 | +1.35% | −10.54% | 93% | 0.10 | 1/3 | |
| E4a | time stop 21d | +3.97% | −9.13% | 86% | 0.17 | 1/3 | the only clean E4 test |
| E4b | time stop 63d | +7.50% | −19.30% | 71% | 0.00 | 0/3 | **degenerate ≡ E0** |
| E4c | time stop 126d | +7.50% | −19.30% | 71% | 0.00 | 0/3 | **degenerate ≡ E0** |

### SPX seasonal — H=189d, 15 evaluable episodes

| Cell | Rule | med (1×) | maxDD | hit | boot | sub | flag |
|---|---|---|---|---|---|---|---|
| **E0** | **hold to horizon** | **+12.86%** | −13.51% | 100% | — | — | |
| E1a | fixed stop −5% | +7.84% | −6.34% | 73% | 0.00 | 0/3 | |
| E1b | fixed stop −10% | +12.86% | −11.10% | 93% | 0.00 | 0/3 | |
| E2a | trailing stop 5% | +5.34% | −6.09% | 73% | 0.01 | 0/3 | |
| E2b | trailing stop 10% | +7.77% | −7.48% | 80% | 0.00 | 0/3 | |
| E3 | trim above wf p75 | +2.90% | −7.48% | 100% | 0.00 | 0/3 | |
| E4a/b/c | time stops | +2.69 / +3.92 / +11.25% | — | — | — | — | **BARRED (§5)** |

Every challenger loses to E0 on the median in both strata. No cell reaches the 0.90 bootstrap bar; the best is washout E4a at **0.17**.

## What actually happened — and the one honest complication

**E1a (fixed −5% stop) ties E0's median (+7.50%) while cutting worst drawdown from −19.30% to −7.15%.** Under a do-no-harm-to-return / improve-risk framing that looks attractive. It **fails the gate**, and it fails partly because of a **flaw in my own pre-registration**:

> **A gate scored on the MEDIAN is structurally blind to a rule whose entire purpose is truncating the TAIL.** The medians are identical precisely because the median episode never breached −5%, so the stop never fired on it. A stop-loss can only ever show up in the tail, and §6 does not look there.

The bootstrap independently agrees the median is no better (0.00), and the hit rate falls 71%→64%, so this is not a smuggled win. But the gate could not have detected one either way.

**The disciplined call: E1a is CLOSED.** §6 forbids design-around and neighbouring-cell rescue. Rewriting the gate after seeing which cell it disadvantaged is exactly the sin the pre-registration exists to prevent. Filed instead as a **named candidate requiring a FRESH pre-registration**: *"risk-scored gate (maxDD / tail CVaR) for tail-truncating exit rules — the median criterion cannot see them."* Not adopted; not encoded.

## Other findings

- **A1.3 confirmed by the engine.** E4b **and** E4c both collapsed to E0 exactly at the 63d horizon (`min(126,63)=63`), as predicted pre-run. The degeneracy assert is a live check that the harness measures what it claims to.
- **Close-only execution mattered.** The −5% stop delivered a **−7.15%** worst outcome — a **2.15pp overshoot** from gapping through the stop to the next close. An intraday-stop assumption (which we have no data to support) would have hidden that and flattered every stop cell.
- **E3's trim behaves exactly as trims do**: highest hit rate in the study (93% washout / 100% SPX) and near-worst median (+1.35% / +2.90%). It converts a fat right tail into frequent small wins. That is a preference, not an edge.
- **The sample is thinner than forecast.** §7 predicted ~13 washout clusters and ~16 SPX episodes; after the ≥6-precedent walk-forward filter the reality is **10 clusters and 15 episodes**. Any of these results would move on a handful of new episodes.

## Limitations (stated, not buried)

- **Cash at 0% (A1.1)** biases *against* every early-exit rule; at 189d the un-credited T-bill yield is worth roughly 2%. A losing E4 cell therefore cannot be cleanly separated from "we declined to credit its cash".
- **Costs do not discriminate (A1.2)** — every cell is two trades, so §6 condition 4 was satisfied by construction and did no work.
- **The episode set rolls.** The 10y daily cap means episodes age out (SLV lost its oldest on the 2026-07-16 refresh). This study is a snapshot of a moving window.
- **10 independent clusters** cannot distinguish a modest exit edge from noise. The verdict is "not demonstrated", not "proven absent".

## Actions taken

1. Overview banner upgraded from a disclaimer to a **tested default**: eight rules tested, none cleared.
2. No exit rule encoded. Nothing auto-trades. E0 remains the only exit.
3. Successor candidate named (risk-scored gate) — requires a fresh pre-registration; not started.
