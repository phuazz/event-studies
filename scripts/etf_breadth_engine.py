#!/usr/bin/env python
"""etf_breadth_engine.py — SentimenTrader-style cross-sectional ETF-breadth study.

Over the `global_etf` universe (single-country/regional ETFs, Norgate,
survivorship-free: delisted names included, point-in-time — a name counts only on
sessions it traded), compute a small LIBRARY of breadth signals and an equal-weight
COMPOSITE, then study SPY forward returns at their extremes. The composite fires
far more often than any single rare breadth signal, which is where both the edge
and the statistical power live (a single signal is thin — see etf_breadth_triage).

Signal library (each a 0..1 "how broad is global equity strength" reading, causal,
on SPY's date axis; denominator = ETFs actually trading that session):
  1. above_200   — % of ETFs above their own 200-day SMA          (trend breadth)
  2. above_50    — % above their own 50-day SMA                   (faster trend)
  3. outperf_spy — % whose 126-day total return beats SPY's       (relative strength)
  4. high_63     — % at a 63-day (quarter) high                   (momentum breadth)
  5. up_21       — % with a positive 21-day return                (short-term breadth)
Composite = mean of the five.

Studies:
  A. Composite THRUST — composite cycles from < 0.30 up through > 0.80 within 252
     sessions; SPY forward returns at 21/63/126/252d vs a random-entry Monte Carlo
     (drift-matched, so a clean timing test), episodes clustered within 21 days.
  B. Composite LEVEL — median SPY forward return by composite quintile (the
     "current reading -> outlook" contingency; descriptive, heavy overlap).
  C. Per-signal thrust attribution.

OUR computed numbers only, on public ETF prices. Their printed figures are leads,
never reproduced. Writes private/etf_breadth/ (gitignored). Run:
    python scripts/etf_breadth_engine.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu   # noqa: E402
import discovery_scan as ds     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "private" / "etf_breadth"
UNIVERSES = ROOT / "universes.json"

BENCH = "SPY"
HOR = [21, 63, 126, 252]
HLAB = ["1M", "3M", "6M", "1Y"]
MIN_NAMES = 10
CLUSTER = 21
HI, LO, CYCLE_WIN = 0.80, 0.30, 252
SIGNALS = ["above_200", "above_50", "outperf_spy", "high_63", "up_21"]


def load_universe():
    cfg = json.loads(UNIVERSES.read_text(encoding="utf-8"))
    u = cfg["universes"]["global_etf"]
    return [t["t"] for t in u["tickers"]], u.get("_benchmark", BENCH)


def per_etf_signals(close, spy_ret126_on_etf):
    """Return dict signal -> (valid_mask, true_mask) on the ETF's own bar index."""
    s200 = ds.sma(close, 200); s50 = ds.sma(close, 50)
    hi63 = ds.rolling_max(close, 63)
    n = len(close)
    ret126 = np.full(n, np.nan); ret126[126:] = close[126:] / close[:-126] - 1.0
    ret21 = np.full(n, np.nan); ret21[21:] = close[21:] / close[:-21] - 1.0
    out = {}
    out["above_200"] = (np.isfinite(s200), close > s200)
    out["above_50"] = (np.isfinite(s50), close > s50)
    out["outperf_spy"] = (np.isfinite(ret126) & np.isfinite(spy_ret126_on_etf),
                          ret126 > spy_ret126_on_etf)
    out["high_63"] = (np.isfinite(hi63), close >= hi63 - 1e-9)
    out["up_21"] = (np.isfinite(ret21), ret21 > 0)
    return out


def build_breadth(n_conn, tickers, bench):
    spy = nu.load_prices(bench, n=n_conn)
    spy_close = spy["Close"].to_numpy(dtype=float)
    spy_ord = [d.toordinal() for d in spy.index.date]
    pos = {d: i for i, d in enumerate(spy_ord)}
    m = len(spy_close)
    spy_ret126 = np.full(m, np.nan); spy_ret126[126:] = spy_close[126:] / spy_close[:-126] - 1.0

    valid = {s: np.zeros(m) for s in SIGNALS}
    true = {s: np.zeros(m) for s in SIGNALS}
    used = []
    for tk in tickers:
        if tk == bench:
            continue
        df = nu.load_prices(tk, n=n_conn)
        if len(df) < 260:
            continue
        close = df["Close"].to_numpy(dtype=float)
        dords = np.array([d.toordinal() for d in df.index.date])
        idx = np.array([pos.get(d, -1) for d in dords])
        onax = idx >= 0
        spy126_on_etf = np.full(len(close), np.nan)
        spy126_on_etf[onax] = spy_ret126[idx[onax]]
        sig = per_etf_signals(close, spy126_on_etf)
        for s in SIGNALS:
            vmask, tmask = sig[s]
            ok = onax & vmask
            p = idx[ok]
            np.add.at(valid[s], p, 1.0)
            np.add.at(true[s], p, tmask[ok].astype(float))
        used.append(tk)

    breadth = {}
    for s in SIGNALS:
        b = np.where(valid[s] >= MIN_NAMES, true[s] / np.maximum(valid[s], 1), np.nan)
        breadth[s] = b
    stack = np.vstack([breadth[s] for s in SIGNALS])
    defined = np.sum(np.isfinite(stack), axis=0)
    # equal-weight mean of the defined signals (avoids nanmean's empty-slice warning)
    colsum = np.nansum(np.where(np.isfinite(stack), stack, 0.0), axis=0)
    comp = np.where(defined >= 4, colsum / np.maximum(defined, 1), np.nan)
    return spy_close, spy_ord, breadth, comp, used


def _fwd_study(spy_close, eps, rng):
    m = len(spy_close)
    base = {h: (spy_close[np.minimum(np.arange(m - 1) + h, m - 1)] / spy_close[:m - 1] - 1.0) for h in HOR}
    rows = []
    for h, lab in zip(HOR, HLAB):
        fwd, mdd = [], []
        for i in eps:
            j = min(i + h, m - 1)
            if j <= i:
                continue
            seg = spy_close[i:j + 1] / spy_close[i] - 1.0
            fwd.append(spy_close[j] / spy_close[i] - 1.0); mdd.append(float(seg.min()))
        fwd = np.array(fwd); nb = fwd.size
        if nb == 0:
            continue
        cond = float(np.median(fwd)); bmed = float(np.median(base[h]))
        draws = base[h][rng.integers(0, base[h].size, size=(2000, nb))]
        nullmed = np.median(draws, axis=1)
        ge = int(np.sum(nullmed >= cond)); p = 2 * min(ge, 2000 - ge) / 2000
        rows.append({"horizon": lab, "n": nb, "cond_median": cond, "base_median": bmed,
                     "lift": cond - bmed, "hit": float((fwd > 0).mean()),
                     "median_maxdd": float(np.median(mdd)), "p_value": p})
    return rows


def thrust_episodes(series):
    m = len(series); fin = np.isfinite(series)
    was_low = ds.rolling_any(np.where(fin, series, 1.0) < LO, CYCLE_WIN)
    cross = np.zeros(m, dtype=bool)
    cross[1:] = fin[1:] & fin[:-1] & (series[1:] > HI) & (series[:-1] <= HI)
    trig = np.flatnonzero(cross & was_low)
    eps, anchor = [], -10**9
    for i in trig:
        if i - anchor > CLUSTER:
            eps.append(int(i)); anchor = int(i)
    return trig, eps


def level_contingency(spy_close, comp):
    """Median SPY forward return by composite quintile (descriptive)."""
    m = len(spy_close); fin = np.isfinite(comp)
    qs = np.quantile(comp[fin], [0.2, 0.4, 0.6, 0.8])
    out = {}
    for h, lab in zip(HOR, HLAB):
        fwd = np.full(m, np.nan)
        idx = np.arange(m - h)
        fwd[idx] = spy_close[idx + h] / spy_close[idx] - 1.0
        buckets = []
        for qi in range(5):
            lo = -np.inf if qi == 0 else qs[qi - 1]
            hival = np.inf if qi == 4 else qs[qi]
            mask = fin & (comp > lo) & (comp <= hival) & np.isfinite(fwd)
            buckets.append({"quintile": qi + 1, "n": int(mask.sum()),
                            "median_fwd": float(np.median(fwd[mask])) if mask.any() else None})
        out[lab] = buckets
    return out, [float(x) for x in qs]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rng = np.random.default_rng(7)
    tickers, bench = load_universe()
    n = nu.connect(); proof = nu.hard_check(n)
    asof = proof["expected_last_session"]

    spy_close, spy_ord, breadth, comp, used = build_breadth(n, tickers, bench)
    fin = np.isfinite(comp); fidx = np.flatnonzero(fin)
    span = f"{dt.date.fromordinal(spy_ord[fidx[0]])} -> {dt.date.fromordinal(spy_ord[fidx[-1]])}"
    print(f"[etf-breadth] {len(used)} ETFs, composite defined on {int(fin.sum())} sessions ({span})")

    # A. composite thrust
    ctrig, ceps = thrust_episodes(comp)
    comp_rows = _fwd_study(spy_close, ceps, rng)
    print(f"\n=== A. COMPOSITE thrust (<{LO:.0%} then up through {HI:.0%}): "
          f"{len(ctrig)} raw -> {len(ceps)} episodes ===")
    print(f"{'Hor':>4}{'n':>4}{'cond':>9}{'base':>9}{'lift':>8}{'hit':>6}{'MaxDD':>8}{'p':>7}")
    for r in comp_rows:
        print(f"{r['horizon']:>4}{r['n']:>4}{r['cond_median']*100:>8.2f}%{r['base_median']*100:>8.2f}%"
              f"{r['lift']*100:>7.2f}%{r['hit']*100:>5.0f}%{r['median_maxdd']*100:>7.2f}%{r['p_value']:>7.3f}")

    # B. level contingency
    cont, qs = level_contingency(spy_close, comp)
    print(f"\n=== B. COMPOSITE level -> SPY 3M forward (quintile medians; descriptive) ===")
    print("  quintile boundaries:", [round(x, 3) for x in qs])
    for b in cont["3M"]:
        mv = f"{b['median_fwd']*100:+.2f}%" if b['median_fwd'] is not None else "n/a"
        print(f"  Q{b['quintile']} (n={b['n']:>5}): 3M median {mv}")

    # C. per-signal thrust attribution
    print(f"\n=== C. per-signal thrust attribution (SPY 3M) ===")
    comp_stats = {}
    for s in SIGNALS:
        _, seps = thrust_episodes(breadth[s])
        rows = _fwd_study(spy_close, seps, rng)
        r3 = next((r for r in rows if r["horizon"] == "3M"), None)
        comp_stats[s] = {"episodes": len(seps), "rows": rows}
        if r3:
            print(f"  {s:12s}: {len(seps):>2} eps, 3M lift {r3['lift']*100:+.2f}% "
                  f"(cond {r3['cond_median']*100:+.2f}%, p {r3['p_value']:.3f})")
        else:
            print(f"  {s:12s}: {len(seps):>2} eps (too few)")

    OUT.mkdir(parents=True, exist_ok=True)
    rec = {"asof": asof, "universe": used, "benchmark": bench,
           "composite_thrust": {"n_raw": len(ctrig), "n_episodes": len(ceps), "rows": comp_rows},
           "composite_level_contingency": cont, "quintile_boundaries": qs,
           "per_signal": comp_stats,
           "params": {"MIN_NAMES": MIN_NAMES, "HI": HI, "LO": LO, "CYCLE_WIN": CYCLE_WIN,
                      "CLUSTER": CLUSTER, "horizons": HOR}}
    (OUT / f"etf_breadth_{asof}.json").write_text(
        json.dumps(rec, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else str(o)),
        encoding="utf-8")
    print(f"\nwrote {OUT / f'etf_breadth_{asof}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
