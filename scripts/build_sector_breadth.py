#!/usr/bin/env python
"""build_sector_breadth.py — SURVIVORSHIP-CLEAN US sector breadth from Norgate.

Infrastructure, not a one-off: sweeps Norgate's US Equities AND US Equities Delisted
databases, classifies every symbol by GICS level-4 sub-industry, and builds a daily
breadth panel for a chosen sub-industry — bankrupt and acquired names INCLUDED.

Why this matters: every constituent-breadth lead this project bounced was bounced for
lack of survivorship-clean membership. For US-LISTED sectors that blocker is gone.

TWO HONEST LIMITS, carried wherever this is used:
  1. Classification is CURRENT / at-delisting, not point-in-time. A company
     reclassified mid-life is mislabelled for its early years. Listing dates ARE
     point-in-time (a name only counts on days it actually traded), so the
     survivorship fix is real; the sector-membership fix is partial.
  2. US-listed only. Does NOT unblock KOSPI / Hang Seng / Ibovespa.

Writes data/_breadth_<sub>.json : {d, pct200, pct50, pct10, pctAll, n}
Run: python private/studies/build_sector_breadth.py [SubIndustry] [outname]
"""
import json, os, sys
import numpy as np, pandas as pd
import norgatedata as nd

SUB = sys.argv[1] if len(sys.argv) > 1 else "Gold"
OUT = sys.argv[2] if len(sys.argv) > 2 else SUB.lower().replace(" ", "_")
MIN_NAMES = 20                     # below this a breadth reading is not meaningful
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data")


def classify_sweep():
    live = list(nd.database_symbols("US Equities"))
    dead = list(nd.database_symbols("US Equities Delisted"))
    print(f"  universe: {len(live)} live + {len(dead)} delisted = {len(live)+len(dead)}")
    hits = {"live": [], "delisted": []}
    for tag, syms in (("live", live), ("delisted", dead)):
        for s in syms:
            try:
                if nd.classification_at_level(s, "GICS", "name", 4) == SUB:
                    hits[tag].append(s)
            except Exception:
                pass
        print(f"  {tag}: {len(hits[tag])} classified '{SUB}'")
    return hits


def fetch_panel(syms):
    ser, failed = {}, 0
    for s in syms:
        try:
            df = nd.price_timeseries(s, start_date="1985-01-01",
                                     timeseriesformat="pandas-dataframe")
            if df is None or len(df) < 250:
                continue
            c = df["Close"].astype(float)
            c = c[c > 0]
            if len(c) >= 250:
                ser[s] = c
        except Exception:
            failed += 1
    print(f"  price series ok={len(ser)} failed/short={failed}")
    return pd.DataFrame(ser).sort_index()


if __name__ == "__main__":
    print(f"[1/3] classifying GICS sub-industry '{SUB}' across live + delisted ...")
    hits = classify_sweep()
    syms = hits["live"] + hits["delisted"]
    if not syms:
        sys.exit(f"no symbols classified '{SUB}'")

    print(f"[2/3] fetching {len(syms)} price series (incl. delisted) ...")
    panel = fetch_panel(syms)
    if panel.empty:
        sys.exit("empty panel")

    print("[3/3] building breadth ...")
    # A name counts on a day ONLY if it actually traded that day and its MA exists.
    valid = panel.notna()
    out = {}
    for per in (10, 50, 200):
        ma = panel.rolling(per, min_periods=per).mean()
        ok = valid & ma.notna()
        out[per] = ((panel > ma) & ok).sum(axis=1), ok.sum(axis=1)

    n = out[200][1]
    # "universal uptrend": above ALL THREE averages simultaneously
    ma10, ma50, ma200 = (panel.rolling(p, min_periods=p).mean() for p in (10, 50, 200))
    okall = valid & ma10.notna() & ma50.notna() & ma200.notna()
    allup = ((panel > ma10) & (panel > ma50) & (panel > ma200) & okall).sum(axis=1)
    n_all = okall.sum(axis=1)

    rows = []
    for d in panel.index:
        if n.get(d, 0) < MIN_NAMES:
            continue
        rows.append({
            "d": d.date().isoformat(),
            "pct10": round(float(out[10][0][d] / out[10][1][d]), 4) if out[10][1][d] >= MIN_NAMES else None,
            "pct50": round(float(out[50][0][d] / out[50][1][d]), 4) if out[50][1][d] >= MIN_NAMES else None,
            "pct200": round(float(out[200][0][d] / n[d]), 4),
            "pctAll": round(float(allup[d] / n_all[d]), 4) if n_all[d] >= MIN_NAMES else None,
            "n": int(n[d]),
        })
    payload = {
        "subIndustry": SUB, "source": "norgate:US Equities + US Equities Delisted, GICS L4",
        "minNames": MIN_NAMES, "nSymbolsLive": len(hits["live"]),
        "nSymbolsDelisted": len(hits["delisted"]), "nSeriesUsed": panel.shape[1],
        "start": rows[0]["d"] if rows else None, "end": rows[-1]["d"] if rows else None,
        "nDays": len(rows),
        "caveats": ["GICS classification is current/at-delisting, NOT point-in-time",
                    "US-listed only", f"days with fewer than {MIN_NAMES} valid names dropped"],
        "series": rows,
    }
    p = os.path.join(DATA, f"_breadth_{OUT}.json")
    json.dump(payload, open(p, "w"), separators=(",", ":"))
    print(f"  wrote {p}")
    print(f"  {payload['nDays']} days {payload['start']}..{payload['end']}  "
          f"symbols live={payload['nSymbolsLive']} delisted={payload['nSymbolsDelisted']} used={payload['nSeriesUsed']}")
    if rows:
        last = rows[-1]
        print(f"  latest {last['d']}: >200d {last['pct200']*100:.0f}%  >50d {last['pct50']*100:.0f}%  "
              f">10d {last['pct10']*100:.0f}%  all-three {last['pctAll']*100 if last['pctAll'] is not None else float('nan'):.0f}%  (n={last['n']})")
