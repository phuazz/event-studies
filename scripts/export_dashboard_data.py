#!/usr/bin/env python
"""export_dashboard_data.py — current-state + reference data for the basket dashboard.
Writes private/studies/dashboard_data.json. Reads the point-in-time panel only.
Run: python private/studies/export_dashboard_data.py
"""
import json, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
PRIV = os.path.join(HERE, "..", "private", "studies")
TURN_Q, MIN_PX, N_BASKET = 0.40, 5.0, 50

df = pd.read_parquet(os.path.join(DATA, "_pit_sp1500.parquet"))
df["t"] = pd.PeriodIndex(df.ym, freq="M")
last = df.t.max()
cur = df[df.t == last].dropna(subset=["turnover60", "upx"])

# Norgate suffixes a delisted/removed symbol as TICKER-YYYYMM. Such a name is a
# legitimate index member for that month (and MUST stay in the backtest — that is
# the point of point-in-time data), but it no longer trades, so it cannot appear in
# a "what to hold today" panel. Excluded from the CURRENT view only, and counted.
gone = cur.sym.str.contains(r"-\d{6}$", regex=True)
n_gone = int(gone.sum())
cur = cur[~gone]

thr = cur.turnover60.quantile(TURN_Q)
liq = cur[(cur.turnover60 >= thr) & (cur.upx >= MIN_PX)]
trend = liq[liq.above200 == True]
cand = trend.dropna(subset=["mom12_1", "vol60"]).copy()
cand["score"] = (cand.mom12_1.rank(pct=True) + (-cand.vol60).rank(pct=True)) / 2
cand = cand.sort_values("score", ascending=False)

basket = [{"sym": r.sym, "sub": r.sub, "score": round(float(r.score), 3),
           "mom": round(float(r.mom12_1), 3), "vol": round(float(r.vol60), 3),
           "dv": round(float(r.turnover60) / 1e6, 1)}
          for r in cand.head(N_BASKET).itertuples()]

# sub-industry breadth now (>=5 names)
subs = []
for s, g in liq.groupby("sub"):
    if len(g) < 5: continue
    subs.append({"sub": s, "n": int(len(g)),
                 "breadth": round(float(g.above200.mean()), 3),
                 "mom": round(float(g.mom12_1.median()), 3) if g.mom12_1.notna().any() else None})
subs.sort(key=lambda x: -x["breadth"])

# universe coverage through time (yearly)
cov = []
for y, g in df.groupby(df.t.dt.year):
    lastm = g.t.max()
    gg = g[g.t == lastm]
    cov.append({"y": int(y), "members": int(len(gg)), "subs": int(gg["sub"].nunique())})

# market-wide breadth history (monthly, all liquid names)
hist = []
for t, g in df.groupby("t", sort=True):
    g2 = g.dropna(subset=["turnover60", "upx"])
    if len(g2) < 50: continue
    l2 = g2[(g2.turnover60 >= g2.turnover60.quantile(TURN_Q)) & (g2.upx >= MIN_PX)]
    if len(l2) < 30 or l2.above200.isna().all(): continue
    hist.append({"t": str(t), "b": round(float(l2.above200.mean()), 4), "n": int(len(l2))})

out = {
    "asOf": str(last),
    "universe": {
        "index": "S&P Composite 1500",
        "watchlistSymbols": 4260, "liveToday": 1500,
        "symbolsUsed": int(df.sym.nunique()),
        "records": int(len(df)),
        "months": int(df.t.nunique()),
        "subIndustries": int(df["sub"].nunique()),
        "start": str(df.t.min()), "end": str(last),
        "membersLatest": int(len(cur)),
        "delistedExcluded": n_gone,
        "liquidLatest": int(len(liq)),
        "trendLatest": int(len(trend)),
        "trendPct": round(float(len(trend) / len(liq)), 3),
    },
    "coverage": cov,
    "breadthHistory": hist,
    "basket": basket,
    "subIndustries": subs,
}
json.dump(out, open(os.path.join(PRIV, "dashboard_data.json"), "w"))
print(f"excluded {n_gone} delisted-suffix symbols from the current view")
print(f"as of {last}: members {len(cur)}, liquid {len(liq)}, above-200d {len(trend)} "
      f"({len(trend)/len(liq)*100:.0f}%), basket {len(basket)}, subs {len(subs)}")
print(f"breadth history {len(hist)} months, coverage {len(cov)} years")
print("wrote dashboard_data.json")
