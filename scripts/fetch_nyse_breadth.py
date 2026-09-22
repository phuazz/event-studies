#!/usr/bin/env python
"""fetch_nyse_breadth.py — NYSE breadth inputs for the risk-off divergence card.

Three Norgate US Indices series, none of which the Yahoo pipeline can supply:
  data/NYHIGH.json   #NYA52WHI   NYSE Composite 52-week new highs (count)
  data/NYLOW.json    #NYA52WLO   NYSE Composite 52-week new lows  (count)
  data/NYA200.json   #NYA%MA200  NYSE Composite % of stocks above their 200-day MA

UNIVERSE CAVEAT, and it is the main reconstruction risk on this card. Norgate's series
are NYSE COMPOSITE, which includes issues that are not operating companies — closed-end
funds, bond funds, ADRs and preferreds have historically been a large share of NYSE
listings. The vendor note specifies "NYSE Common Stocks" for the above-200-day condition.
If their universe is common-only and ours is all-issues, the two series differ in level
and the signal dates can differ with them. Recorded on the card rather than assumed away.

DEPTH: these begin 1990-01-02. The note charts 1973-74, so it has deeper history and this
is a PARTIAL reproduction covering 1990 onward.

Not wired into universes.json / fetch_history.js — that pipeline is Yahoo. Same
arrangement as GSPC.json, NDX.json, AAII.json and USPRIME.json.

Python datetime months are 1-indexed. Run: python scripts/fetch_nyse_breadth.py
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SERIES = [
    ("NYHIGH", "#NYA52WHI", "NYSE Composite 52-week new highs (count)", "count"),
    ("NYLOW", "#NYA52WLO", "NYSE Composite 52-week new lows (count)", "count"),
    ("NYA200", "#NYA%MA200", "NYSE Composite % of stocks above their 200-day MA", "percent"),
]
START = "1985-01-01"


def main():
    import norgatedata as nd

    written = []
    for tag, sym, name, unit in SERIES:
        df = nd.price_timeseries(sym, start_date=START,
                                 timeseriesformat="pandas-dataframe").sort_index()
        s = df["Close"].astype(float).dropna()
        if unit == "percent":
            s = s[(s >= 0) & (s <= 100)]
        else:
            s = s[s >= 0]
        if len(s) < 4000:
            raise SystemExit(f"FATAL: {sym} returned only {len(s)} bars — refusing to write")
        daily = [{"d": i.date().isoformat(), "v": round(float(v), 4)} for i, v in s.items()]
        out = {"ticker": tag, "name": name, "source": f"norgate:{sym}", "unit": unit,
               "universeCaveat": ("NYSE COMPOSITE — includes closed-end funds, bond funds, "
                                  "ADRs and preferreds. The vendor note specifies common "
                                  "stocks for the 200-day condition; if their universe is "
                                  "common-only, levels and signal dates can differ."),
               "fetchedAt": datetime.now(timezone.utc).isoformat(),
               "start": daily[0]["d"], "lastDate": daily[-1]["d"], "n": len(daily),
               "daily": daily}
        json.dump(out, open(os.path.join(DATA, f"{tag}.json"), "w"), separators=(",", ":"))
        written.append((tag, sym, daily[0]["d"], daily[-1]["d"], len(daily), daily[-1]["v"]))

    # Cross-series integrity: all three must share a calendar, or the detector silently
    # drops the days they disagree on and the signal set shrinks without saying so.
    sets = []
    for tag, *_ in SERIES:
        d = json.load(open(os.path.join(DATA, f"{tag}.json")))
        sets.append({b["d"] for b in d["daily"]})
    common = set.intersection(*sets)
    union = set.union(*sets)
    for tag, sym, a, b, n, last in written:
        print(f"  {tag:7} {sym:11} {a}..{b}  n={n:5}  last={last:.2f}")
    print(f"  calendar overlap: {len(common)} of {len(union)} dates shared "
          f"({len(common)/len(union)*100:.1f}%)")
    if len(common) / len(union) < 0.98:
        raise SystemExit("FATAL: the three breadth series disagree on more than 2% of "
                         "dates — the detector would drop those days silently")


if __name__ == "__main__":
    main()
