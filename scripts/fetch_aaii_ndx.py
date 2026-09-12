#!/usr/bin/env python
"""fetch_aaii_ndx.py — locally-sourced inputs for the AAII Bull Ratio card.

Neither input comes from the Yahoo pipeline, so both are refreshed here:
  data/AAII.json  weekly AAII Bull Ratio, from C:\\dev\\sentiment-composite
  data/NDX.json   Nasdaq 100 daily, from Norgate ($NDX, 1985+)

AAII is a PUBLIC survey (American Association of Individual Investors), not vendor
IP — it is the vendor NOTE that is licensed, not the underlying series.

EFFECTIVE DATE (register 45, sentiment-composite): a reading is consumed on the date
it became obtainable, not its survey Thursday. The frozen history keeps the
release-Thursday convention; recent rows carry an explicit `available` date. Using
the survey date for recent rows would be look-ahead of 1-4 days.

Python datetime months are 1-indexed. Run: python scripts/fetch_aaii_ndx.py
"""
import json, os
from datetime import datetime, timezone
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SRC = r"C:\dev\sentiment-composite\data\public\aaii.csv"


def aaii():
    a = pd.read_csv(SRC, parse_dates=["date"])
    a = a.dropna(subset=["bulls_ratio"]).sort_values("date")
    a["eff"] = pd.to_datetime(a["available"]).fillna(a["date"])
    rows = [{"d": r.date.date().isoformat(), "eff": r.eff.date().isoformat(),
             "v": round(float(r.bulls_ratio), 4)} for r in a.itertuples()]
    out = {"ticker": "AAII", "name": "AAII Bull Ratio (bulls / (bulls + bears))",
           "source": "AAII weekly sentiment survey (public) via sentiment-composite",
           "cadence": "weekly", "effectiveDateRule": "register 45 — consumed on `eff`, not survey date",
           "fetchedAt": datetime.now(timezone.utc).isoformat(),
           "start": rows[0]["d"], "lastDate": rows[-1]["d"], "n": len(rows), "weekly": rows}
    json.dump(out, open(os.path.join(DATA, "AAII.json"), "w"), separators=(",", ":"))
    print(f"  AAII: {len(rows)} weekly rows {rows[0]['d']}..{rows[-1]['d']} "
          f"(latest ratio {rows[-1]['v']:.1f})")


def ndx():
    import norgatedata as nd
    df = nd.price_timeseries("$NDX", start_date="1985-01-01",
                             timeseriesformat="pandas-dataframe").sort_index()
    daily = [{"d": i.date().isoformat(), "ac": round(float(v), 4)}
             for i, v in df["Close"].items() if v is not None and float(v) > 0]
    last = {}
    for b in daily:
        last[b["d"][:7]] = b
    monthly = [last[k] for k in sorted(last)]
    out = {"ticker": "NDX", "name": "Nasdaq 100", "source": "norgate:$NDX",
           "fetchedAt": datetime.now(timezone.utc).isoformat(),
           "dailyStart": daily[0]["d"], "lastDate": daily[-1]["d"],
           "nDaily": len(daily), "nMonthly": len(monthly), "daily": daily, "monthly": monthly}
    json.dump(out, open(os.path.join(DATA, "NDX.json"), "w"), separators=(",", ":"))
    print(f"  NDX: {len(daily)} daily {daily[0]['d']}..{daily[-1]['d']}")


if __name__ == "__main__":
    aaii()
    ndx()
