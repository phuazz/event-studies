# Results: first close below the 200-day after a long run → S&P 500

Run 2026-11-20 against `studies/2026-11-19_sma200-run-break_preregistration.md`.
Nothing in the pre-registration was changed. All numbers below are ours.

## Data (deviation, disclosed)

The pre-registration names Norgate `$SPX`. This run used **TradingView
`SP:SPX`** (S&P 500 price index, daily, 1948-01-02 → 2026-11-19, 19,878
bars), because the cloud session had no Norgate access. The pages were
merged with zero disagreements where they overlapped and no gap longer than
six calendar days. History starts in 1948 only to warm up the 200-day SMA
and the run count. No trigger falls before 1950.

The reconciliation below matches the source date-for-date, so the data
substitution does not move the trigger set. A Norgate re-run is a
confirmation, not a precondition. The vendor series is not committed
(`data/` is gitignored).

## Reconciliation gate: PASSED

N = 150: **36 triggers against the source's 36. Every date matches exactly**
(0 missing, 0 extra, 0 shifted), including 1987-10-15, 2020-02-27,
2025-03-10, 2026-03-19 and the live 2026-11-17. Our 3M median (+4.3%) and
3M hit rate (77.1%) reproduce the source's summary row. The live episode has
no forward window and is excluded from every statistic (n = 35, or 34 at 1Y).

## Primary result (declared before results)

**3M hit-rate edge against the matched uptrend baseline, N = 150:
+11.2pp (77.1% vs 65.9%), Monte Carlo p = 0.24.**

Verdict mapping, applied verbatim: matched edge > 0 with p ≥ 0.10 →
**"no-panic" gauge only.** The break is not a sell signal, but the hit-rate
evidence does not support it as a buy tilt.

## Full table, N = 150 (n = 35; 1Y n = 34)

Edges are in pp. *p* is the two-sided random-entry Monte Carlo value
(2,000 draws).

| | 1W | 2W | 1M | 2M | **3M** | 6M | 1Y |
|---|---:|---:|---:|---:|---:|---:|---:|
| Signal median | 0.3% | 0.7% | 1.8% | 2.4% | **4.3%** | 7.3% | 9.4% |
| Signal % higher | 62.9 | 65.7 | 68.6 | 74.3 | **77.1** | 68.6 | 73.5 |
| All-days median / % higher | 0.3 / 56.8 | 0.6 / 59.0 | 1.1 / 61.7 | 1.9 / 64.3 | 2.7 / 66.6 | 5.2 / 70.5 | 10.7 / 74.6 |
| Edge vs all days: hit (p) | +6.1 (0.64) | +6.7 (0.52) | +6.9 (0.50) | +10.0 (0.28) | +10.5 (0.25) | −1.9 (0.62) | −1.0 (0.70) |
| Edge vs all days: median (p) | 0.0 (0.98) | +0.1 (0.82) | +0.7 (0.32) | +0.5 (0.69) | +1.5 (0.22) | +2.2 (0.22) | −1.3 (0.68) |
| Matched median / % higher | 0.2 / 56.1 | 0.4 / 57.9 | 0.7 / 58.5 | 1.3 / 61.7 | 2.1 / 65.9 | 4.5 / 71.5 | 8.2 / 72.2 |
| **Edge vs matched: hit (p)** | +6.7 (0.51) | +7.8 (0.46) | +10.1 (0.27) | +12.6 (0.15) | **+11.2 (0.24)** | −2.9 (0.56) | +1.4 (0.95) |
| Edge vs matched: median (p) | +0.1 (0.79) | +0.2 (0.64) | +1.1 (0.10) | +1.1 (0.18) | +2.2 (0.03) | +2.9 (0.03) | +1.1 (0.70) |
| Median worst interim drawdown | −1.0% | −1.2% | −2.0% | −2.6% | −2.6% | −4.0% | −5.8% |

## Robustness cells (report-only)

| 3M | N = 100 (n = 45) | **N = 150 (n = 35)** | N = 200 (n = 31) |
|---|---:|---:|---:|
| Signal median / % higher | 5.3% / 75.6 | 4.3% / 77.1 | 5.3% / 77.4 |
| Edge vs matched: hit (p) | +7.0 (0.40) | +11.2 (0.24) | +12.2 (0.20) |
| Edge vs matched: median (p) | +2.9 (0.001) | +2.2 (0.03) | +3.3 (0.004) |

The direction is the same at all three thresholds, so the result is not an
artefact of the 150 choice.

## Tail

Over 3 months, 8 of 35 episodes ended lower. Two fell more than 10%:
1962-04-04 (−17.1%) and 1987-10-15 (−15.4%). The worst interim drawdown
reached **−10% or worse in 5 of 35** (1962, 1987, 2011, 2020, 2025), and
−5% or worse in 9. The average worst drawdown was −4.9%. Since 2007: 7 of
10 were higher at 3M, with a median of +5.3%, but the drawdowns on the way
were larger (2011, 2020, 2025).

## Reading it

- **What the source got right:** the dates and the summary numbers reproduce
  exactly. Over the following quarter the S&P has more often been higher
  than lower after this break.
- **What the uptrend baseline changes:** a random day deep inside a 150+ day
  run has a *weaker* forward quarter than an average day (3M median 2.1% vs
  2.7%). Mature uptrends do not drift faster. So the uptrend baseline does
  not erase the signal's advantage; it leaves it slightly larger.
- **Why the verdict is still "gauge only":** the pre-registered statistic is
  the hit rate, and a +11pp hit-rate edge on 35 episodes is p = 0.24, well
  within noise.
- **The median finding:** the 3M median edge against the matched baseline
  is p = 0.03, and it holds at N = 100 and 200. That is the most interesting
  number here, but it was the secondary statistic. After 42 screened cells it
  does not clear a Bonferroni bar (0.05 / 42 ≈ 0.001; only the N = 100 cell
  touches it, and that cell is report-only). It is recorded as a lead for a
  future pre-registration scored on the median, not as evidence now.
- **Beyond 3M the effect fades:** 6M and 1Y hit-rate edges are ≈ 0 or
  negative.

## Live instance

Triggered 2026-11-17 (close 7,340.53, after a 155-session run above the
200-day). On 2026-11-19 the index was at 7,175.83, −2.2% from the trigger.
That is within the historical median 3M drawdown band (about −2.6%), and
well short of the −10% that 5 of 35 episodes reached. The 3M mark falls
around mid-February 2027.

## Proposed card text (for sign-off; not yet in the catalogue)

**summary:** "When the S&P 500 first closes below its 200-day average after
150+ sessions above it, the next quarter has more often been up than down:
77% of 35 episodes since 1950, median +4.3%. Measured against a random day in
an equally mature uptrend, the hit-rate edge (+11pp) is not significant
(p = 0.24), so this is a 'don't panic' gauge, not a buy signal. The median
edge (+2.2pp, p = 0.03) is a lead, not a finding. One in seven episodes saw a
10%+ drawdown inside the quarter."

**rationale:** "VERDICT. NO-PANIC GAUGE. The first break of a long run above
the 200-day has more often been a pause in the uptrend than its end. Over 35
episodes since 1950 the S&P 500 was higher three months later 77% of the
time, against 66% for a random day in an equally mature uptrend: +11pp,
p = 0.24 on the pre-registered hit-rate test. That is not enough to trade as
a tilt. THE BASELINE. The rule only fires inside long uptrends, so it is
scored against random days that are themselves 150+ sessions into a run
above the 200-day, not against all days. Those days have a weaker forward
quarter than average (3M median 2.1% vs 2.7%), so the comparison does not
flatter the signal. THE SOURCE REPRODUCES. A public strategist post listed 36
signal dates since 1950; our rule recovers all 36 on the same days and
matches the published 3M median and hit rate. The post's claim that forward
returns beat the average holds at 1 to 3 months and fails at 12: the 1Y
median is below base. WHAT IS NOT YET EVIDENCE. The 3M median edge against
the matched baseline (+2.2pp, p = 0.03) holds at N = 100 and 200. It was the
secondary statistic, among 42 screened cells, and is recorded as a lead for a
future median-scored pre-registration. TAIL. Five of 35 episodes (1962, 1987,
2011, 2020, 2025) fell 10% or more inside the quarter; two ended it down more
than 15%. HOW TO USE IT. When the break fires, do not de-risk on the break
alone. Any adds should be scaled in, because the interim drawdown has
reached 10%+ about one time in seven. DATA. TradingView SP:SPX price index
1948 onward; a Norgate $SPX re-run is pending as confirmation."

Card parameters as in the pre-registration draft (`direction: "up"`,
`scoreOn: "hitrate"`, `thesisHorizonDays: 63`).
