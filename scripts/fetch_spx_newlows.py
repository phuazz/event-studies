#!/usr/bin/env python
"""fetch_spx_newlows.py — percentage of S&P 500 members at a new 52-week low, daily.

Input for the `spx-newlow-spike` card. Built from four Norgate US Indices series:
  #SPX52WLO                       S&P 500 members at a new 52-week low (count)
  #SPXADV + #SPXDEC + #SPXUNC     members that printed that day (the true denominator)

The denominator is the day's actual member count rather than a fixed 500, because the
index carries 500-505 names and some print no trade on a given day. A day whose member
count falls below 100 is treated as a bad print and dropped, not carried forward.

Written as one precomputed series (data/SPXNL.json, `v` = percent) so the engine's
detector reads a single input rather than joining four.

DEPTH: 1960 onward, thirty years deeper than the NYSE series behind
`nyse-riskoff-divergence`.

Not wired into universes.json / fetch_history.js, which is Yahoo. Same arrangement as the
other Norgate-sourced inputs.

Python datetime months are 1-indexed. Run: python scripts/fetch_spx_newlows.py
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
START = "1959-01-01"
MIN_MEMBERS = 100


def main():
    import norgatedata as nd
    import pandas as pd

    def ser(sym):
        s = nd.price_timeseries(sym, start_date=START,
                                timeseriesformat="pandas-dataframe").sort_index()["Close"]
        return s.astype(float).dropna()

    df = pd.DataFrame({k: ser(s) for k, s in
                       [("lo", "#SPX52WLO"), ("adv", "#SPXADV"),
                        ("dec", "#SPXDEC"), ("unc", "#SPXUNC")]}).dropna()
    df["n"] = df.adv + df.dec + df.unc
    bad = int((df.n < MIN_MEMBERS).sum())
    df = df[df.n >= MIN_MEMBERS]
    df["pct"] = df.lo / df.n * 100.0
    if len(df) < 10000:
        raise SystemExit(f"FATAL: only {len(df)} usable days — refusing to write")
    if (df.pct < 0).any() or (df.pct > 100).any():
        raise SystemExit("FATAL: a percentage outside 0-100 — the join is wrong")

    daily = [{"d": i.date().isoformat(), "v": round(float(r.pct), 4), "n": int(r.n)}
             for i, r in df.iterrows()]
    out = {"ticker": "SPXNL", "name": "S&P 500 % of members at a new 52-week low",
           "source": "norgate:#SPX52WLO / (#SPXADV + #SPXDEC + #SPXUNC)", "unit": "percent",
           "fetchedAt": datetime.now(timezone.utc).isoformat(),
           "start": daily[0]["d"], "lastDate": daily[-1]["d"], "n": len(daily),
           "droppedBadPrints": bad, "daily": daily}
    json.dump(out, open(os.path.join(DATA, "SPXNL.json"), "w"), separators=(",", ":"))
    print(f"  SPXNL: {len(daily)} days {daily[0]['d']}..{daily[-1]['d']}  "
          f"latest {daily[-1]['v']:.2f}% of {daily[-1]['n']} members  "
          f"(dropped {bad} bad prints, median members {int(df.n.median())})")


if __name__ == "__main__":
    main()
