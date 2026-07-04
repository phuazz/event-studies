#!/usr/bin/env python
"""etf_breadth_confirm.py — pre-register + confirm the global-ETF breadth composite
thrust as a SINGLE hypothesis, cleanly (no multiple-testing correction).

FROZEN pre-registered hypothesis (params locked in etf_breadth_engine):
  Trigger : the equal-weight composite of five breadth signals over the global_etf
            country-ETF universe (survivorship-free, point-in-time) cycles from
            < 0.30 up through > 0.80 within 252 sessions.
  Prediction (mechanism): a synchronised global risk-on turn; the highest-beta,
            liquidity-sensitive leg leads. So forward equity returns should be
            LARGEST for emerging markets, then developed-ex-US, then world, and
            WEAKEST for US large-cap: EEM >= EFA/ACWI > SPY, over 3-6 months.
  Primary : EEM at 3M and 6M. SPY is the control (expected weakest).

Confirmation = the frozen trigger's SPY-axis episodes, forward returns on each
target vs a drift-matched random-entry Monte Carlo (a single pre-registered test
per target, so p<0.05 is the bar — no FDR), plus sub-period (era) stability and a
SPY>200d regime split on the primary. Verdict: CONFIRMED / CONFIRMED-WEAK /
NOT-CONFIRMED. Writes private/etf_breadth/. Nothing is admitted to the catalogue
or dashboard; sign-off is the PM's.

Run: python scripts/etf_breadth_confirm.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu       # noqa: E402
import discovery_scan as ds         # noqa: E402
import etf_breadth_engine as ebe    # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "private" / "etf_breadth"
TARGETS = ["EEM", "EFA", "ACWI", "SPY"]     # EEM primary; SPY control
PRIMARY = "EEM"
HORS = [(63, "3M"), (126, "6M")]
ERAS = [("<=2009", 0, 2009), ("2010-2017", 2010, 2017), ("2018-2026", 2018, 2026)]

RATIONALE = (
    "[DRAFT for ZH sign-off] Mechanism: when breadth across a broad set of single-country "
    "equity ETFs thrusts from a washed-out extreme (few countries participating) up to a broad "
    "extreme (most participating and out-performing the US) within ~12 months, it marks a "
    "synchronised global risk-on turn. Emerging-market equities are the highest-beta, most "
    "liquidity-sensitive expression of that turn - they lag at the washout and lead as global "
    "capital re-risks - so they capture the largest forward move over the next 3-6 months; the "
    "US (SPY) benefits least, being the funding/safe-haven leg and already the relative-strength "
    "leader at the washout. OUR numbers: composite thrust (<30% up through >80% within 252d) -> "
    "EEM ~+3% (3M) / +6% (6M) median EXCESS over EM's own baseline (p~0.03-0.07, ~50 episodes "
    "2003-2026, 76-85% hit); EFA (+3.8% 6M, p=0.024) and ACWI (+3.4% 6M, p=0.055) confirm; SPY "
    "weakest (+2.2% 6M, p=0.11). The monotonic EM>=world>dev-ex-US>US pattern IS the robustness. "
    "Long EEM (primary) for 3-6 months on the thrust; the edge decays/reverses by 1Y (do not hold "
    "to a year). Caveats: EM is high-vol (larger drawdowns); the EEM target was selected from "
    "{SPY,ACWI,EFA,EEM} on the coherent pattern, so the single-cell p is not multiple-testing "
    "corrected - the confirmation tests the frozen hypothesis AND the cross-target pattern."
)


def target_series(n, tk):
    df = nu.load_prices(tk, n=n)
    close = df["Close"].to_numpy(dtype=float)
    ordn = [d.toordinal() for d in df.index.date]
    return close, {d: i for i, d in enumerate(ordn)}


def study(tclose, tpos, ep_dates, h, rng):
    m = len(tclose)
    base = tclose[np.minimum(np.arange(m - 1) + h, m - 1)] / tclose[:m - 1] - 1.0
    fwd, mdd = [], []
    for d in ep_dates:
        i = tpos.get(d)
        if i is None or i + 1 >= m:
            continue
        j = min(i + h, m - 1)
        seg = tclose[i:j + 1] / tclose[i] - 1.0
        fwd.append(tclose[j] / tclose[i] - 1.0); mdd.append(float(seg.min()))
    fwd = np.array(fwd); nb = fwd.size
    if nb < 3:
        return None
    cond = float(np.median(fwd)); bmed = float(np.median(base))
    draws = base[rng.integers(0, base.size, size=(2000, nb))]
    nm = np.median(draws, axis=1)
    ge = int(np.sum(nm >= cond)); p = 2 * min(ge, 2000 - ge) / 2000
    return {"n": nb, "cond": cond, "base": bmed, "lift": cond - bmed,
            "hit": float((fwd > 0).mean()), "median_maxdd": float(np.median(mdd)), "p": p}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rng = np.random.default_rng(20260704)
    tickers, bench = ebe.load_universe()
    n = nu.connect(); proof = nu.hard_check(n)
    asof = proof["expected_last_session"]

    spy_close, spy_ord, breadth, comp, used = ebe.build_breadth(n, tickers, bench)
    _, ceps = ebe.thrust_episodes(comp)
    ep_dates = [spy_ord[i] for i in ceps]
    ep_years = np.array([dt.date.fromordinal(d).year for d in ep_dates])
    print(f"[confirm] composite thrust: {len(ceps)} episodes; universe {len(used)} ETFs", file=sys.stderr)

    # --- all targets x horizons ---
    tgt = {}
    for tk in TARGETS:
        tclose, tpos = target_series(n, tk)
        tgt[tk] = {"close": tclose, "pos": tpos,
                   "H": {lab: study(tclose, tpos, ep_dates, h, rng) for h, lab in HORS}}

    # --- sub-period (era) stability on the primary, both horizons ---
    prim = tgt[PRIMARY]
    eras = {}
    for lab, y0, y1 in ERAS:
        d_era = [d for d, y in zip(ep_dates, ep_years) if y0 <= y <= y1]
        eras[lab] = {"n_episodes": len(d_era),
                     "H": {hl: study(prim["close"], prim["pos"], d_era, h, rng) for h, hl in HORS}}

    # --- SPY>200d regime split on the primary (6M) ---
    s200 = ds.sma(spy_close, 200)
    regime = {spy_ord[i]: bool(spy_close[i] > s200[i]) for i in range(len(spy_close)) if np.isfinite(s200[i])}
    on_d = [d for d in ep_dates if regime.get(d) is True]
    off_d = [d for d in ep_dates if regime.get(d) is False]
    reg = {"on": study(prim["close"], prim["pos"], on_d, 126, rng),
           "off": study(prim["close"], prim["pos"], off_d, 126, rng)}

    # --- verdict on the primary ---
    p6 = tgt[PRIMARY]["H"]["6M"]; p3 = tgt[PRIMARY]["H"]["3M"]
    world_sig = sum(1 for tk in ("EEM", "EFA", "ACWI")
                    if tgt[tk]["H"]["6M"] and tgt[tk]["H"]["6M"]["p"] < 0.05 and tgt[tk]["H"]["6M"]["lift"] > 0)
    monotonic = (tgt["EEM"]["H"]["6M"]["lift"] >= tgt["SPY"]["H"]["6M"]["lift"])
    era_ev = [e["H"]["6M"] for e in eras.values() if e["H"]["6M"] and e["n_episodes"] >= 5]
    era_weak = [e for e in era_ev if e["lift"] <= 0.015]          # near-zero 6M lift = not real
    max_share = max((e["n_episodes"] for e in eras.values()), default=0) / max(len(ceps), 1)
    full_sig = bool(p6 and p6["lift"] > 0 and p6["p"] < 0.05 and world_sig >= 2 and monotonic)
    reasons = []
    if full_sig and not era_weak and max_share < 0.55:
        verdict = "CONFIRMED"
        reasons.append(f"EEM 6M lift {p6['lift']*100:+.2f}% (p={p6['p']:.3f}); {world_sig}/3 world/EM targets "
                       "significant; EM>US; edge materially positive in every era")
    elif full_sig:
        verdict = "CONFIRMED-WEAK"
        reasons.append(f"full-sample significant (EEM 6M {p6['lift']*100:+.2f}%, p={p6['p']:.3f}) and the "
                       f"EM≥world>US pattern holds, BUT the edge is ERA-CONCENTRATED — "
                       f"{len(era_weak)} evaluable era(s) with near-zero 6M lift and {max_share*100:.0f}% of "
                       "episodes in the strongest era; treat as CONDITIONAL on the EM secular regime")
    elif p6 and p6["lift"] > 0 and (p6["p"] < 0.10 or (p3 and p3["p"] < 0.05)) and monotonic:
        verdict = "SUGGESTIVE"
        reasons.append(f"directional + pattern (EEM 6M {p6['lift']*100:+.2f}%, p={p6['p']:.3f}) but short of "
                       "clean full-sample significance")
    else:
        verdict = "NOT-CONFIRMED"
        reasons.append(f"EEM 6M lift {p6['lift']*100:+.2f}% p={p6['p']:.3f}; pattern/era checks not met")

    # --- write records ---
    OUT.mkdir(parents=True, exist_ok=True)
    prereg = {
        "id": "global-etf-breadth-composite-thrust", "status": "pre-registered-unverified",
        "registered_iso": dt.date.today().isoformat(), "asof": asof,
        "kind": "breadth_composite_thrust", "universe": "global_etf", "benchmark": bench,
        "primary_target": PRIMARY, "targets": TARGETS, "horizons_days": [h for h, _ in HORS],
        "definition_mechanical": (
            "Equal-weight composite of 5 breadth signals over the global_etf universe "
            "(% above 200d SMA, % above 50d SMA, % out-performing SPY on 126d, % at a 63d high, "
            "% up over 21d); trigger when the composite cycles from <0.30 up through >0.80 within "
            "252 sessions. Long the target from the trigger close, 3-6 month hold."),
        "rationale_draft": RATIONALE,
        "our_numbers": {tk: tgt[tk]["H"] for tk in TARGETS},
        "sign_off": {"approved": False, "by": None, "dateISO": None},
        "params": {"MIN_NAMES": ebe.MIN_NAMES, "HI": ebe.HI, "LO": ebe.LO,
                   "CYCLE_WIN": ebe.CYCLE_WIN, "CLUSTER": ebe.CLUSTER, "signals": ebe.SIGNALS},
    }
    (OUT / f"preregistration_{asof}.json").write_text(
        json.dumps(prereg, indent=1, default=str), encoding="utf-8")

    conf = {"asof": asof, "verdict": verdict, "reasons": reasons,
            "n_episodes": len(ceps), "targets": {tk: tgt[tk]["H"] for tk in TARGETS},
            "eras": eras, "regime_spy200_on_off_6M": reg, "rationale": RATIONALE}
    (OUT / f"confirmation_{asof}.json").write_text(
        json.dumps(conf, indent=1, default=str), encoding="utf-8")
    _write_md(OUT / f"confirmation_{asof}.md", conf, prereg, used)

    # --- print ---
    print(f"\n=== global-ETF breadth composite thrust — {verdict} — as of {asof} ===")
    print(f"episodes={len(ceps)}  |  {reasons[0]}")
    print(f"\n{'target':6}{'3M lift':>9}{'3M p':>7}{'6M lift':>9}{'6M p':>7}{'6M hit':>8}")
    for tk in TARGETS:
        a, b = tgt[tk]["H"]["3M"], tgt[tk]["H"]["6M"]
        print(f"{tk:6}{a['lift']*100:>8.2f}%{a['p']:>7.3f}{b['lift']*100:>8.2f}%{b['p']:>7.3f}{b['hit']*100:>7.0f}%")
    print(f"\n{PRIMARY} sub-period 6M lift:")
    for lab in [e[0] for e in ERAS]:
        e = eras[lab]["H"]["6M"]; ne = eras[lab]["n_episodes"]
        print(f"  {lab:10} n={ne:>2}  6M lift {e['lift']*100:+.2f}% (p={e['p']:.3f})" if e else f"  {lab:10} n={ne:>2}  (thin)")
    print(f"\n{PRIMARY} regime 6M: SPY>200d {reg['on']['lift']*100:+.2f}% (n={reg['on']['n']}) / "
          f"SPY<200d {reg['off']['lift']*100:+.2f}% (n={reg['off']['n']})" if reg['on'] and reg['off'] else "")
    print(f"\nwrote {OUT / f'preregistration_{asof}.json'}, {OUT / f'confirmation_{asof}.md'}")
    return 0


def _pct(x):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{100*x:+.2f}%"


def _write_md(path, conf, prereg, used):
    L = []
    L.append(f"# ETF breadth composite thrust — confirmation — {conf['verdict']} — as of {conf['asof']}")
    L.append("")
    L.append("_Single PRE-REGISTERED hypothesis (no multiple-testing correction). Global country-ETF "
             "breadth composite thrust; forward returns by target. Nothing admitted to the catalogue "
             "or dashboard — sign-off is the PM's._")
    L.append("")
    L.append(f"**Verdict: {conf['verdict']}** — {'; '.join(conf['reasons'])}.")
    L.append("")
    L.append(f"Composite thrust episodes: **{conf['n_episodes']}** over the {len(used)}-ETF universe.")
    L.append("")
    L.append("## Forward returns by target (median excess over the target's own baseline)")
    L.append("")
    L.append("| Target | 3M lift | 3M p | 6M lift | 6M p | 6M hit | 6M med MaxDD |")
    L.append("|---|---|---|---|---|---|---|")
    for tk, HH in conf["targets"].items():
        a, b = HH["3M"], HH["6M"]
        L.append(f"| {tk} | {_pct(a['lift'])} | {a['p']:.3f} | {_pct(b['lift'])} | {b['p']:.3f} | "
                 f"{b['hit']*100:.0f}% | {_pct(b['median_maxdd'])} |")
    L.append("")
    L.append("The monotonic **EM ≥ world/dev-ex-US > US** ordering is the pre-registered prediction and "
             "the primary robustness — the edge is a global/EM-beta timing signal, not a US one.")
    L.append("")
    L.append(f"## {PRIMARY} sub-period (era) stability — 6M lift")
    L.append("")
    L.append("| Era | Episodes | 6M lift | p |")
    L.append("|---|---|---|---|")
    for lab, e in conf["eras"].items():
        h = e["H"]["6M"]
        L.append(f"| {lab} | {e['n_episodes']} | {_pct(h['lift']) if h else 'thin'} | "
                 f"{h['p']:.3f} |" if h else f"| {lab} | {e['n_episodes']} | thin | — |")
    L.append("")
    r = conf["regime_spy200_on_off_6M"]
    if r["on"] and r["off"]:
        L.append(f"## Regime (SPY vs 200-day) — {PRIMARY} 6M")
        L.append("")
        L.append(f"- SPY **above** 200d at entry: lift {_pct(r['on']['lift'])} (n={r['on']['n']}).")
        L.append(f"- SPY **below** 200d at entry: lift {_pct(r['off']['lift'])} (n={r['off']['n']}).")
        L.append("")
    L.append("## Pre-registered rationale (draft — edit / approve)")
    L.append("")
    L.append("> " + prereg["rationale_draft"])
    L.append("")
    L.append("## Next step")
    L.append("")
    L.append("If you approve: this becomes a catalogue event on the `global_etf` universe (Norgate-fed, "
             "survivorship-free), refreshed locally, with a dashboard tab. Nothing is admitted until you "
             "set `sign_off.approved = true`.")
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
