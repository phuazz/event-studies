#!/usr/bin/env python
"""fetch_ratio_data.py — data for the copper/gold ratio-extreme studies.

Writes two engine-shape files (data/ is gitignored — regenerable):
  - data/CUGC.json : Norgate #CUGC (copper/gold ratio), full daily + month-end.
                     The TRIGGER series for both copper and macro cards. 1993+.
  - data/CPER.json : Yahoo CPER (US Copper Index Fund ETF), full daily. The
                     copper TARGET for card (A). 2011+.

Card (B) targets the S&P 500 via data/GSPC.json (already produced by
fetch_gspc_norgate.py). Copper futures HG=F are avoided (continuous-futures roll
artefacts); CPER is the clean investable copper return, COPX the miners alt.

Python months are 1-indexed. Run: python scripts/fetch_ratio_data.py
"""
import calendar
import json
import os
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")


def _monthly(daily):
    last = {}
    for b in daily:
        last[b["d"][:7]] = b
    return [last[k] for k in sorted(last)]


def from_norgate_cugc():
    import norgatedata as nd
    df = nd.price_timeseries("#CUGC", start_date="1990-01-01",
                             timeseriesformat="pandas-dataframe").sort_index()
    daily = [{"d": i.date().isoformat(), "ac": round(float(v), 6)}
             for i, v in df["Close"].items() if v is not None and float(v) > 0]
    return daily


def from_yahoo_full(sym, start=(2010, 1, 1)):
    p1 = calendar.timegm(start + (0, 0, 0))
    p2 = int(datetime.now(timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.load(urllib.request.urlopen(req, timeout=40))["chart"]["result"][0]
    ts, adj = r["timestamp"], r["indicators"]["adjclose"][0]["adjclose"]
    return [{"d": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
             "ac": round(float(a), 4)}
            for t, a in zip(ts, adj) if a is not None and a > 0]


def write(ticker, name, source, daily):
    monthly = _monthly(daily)
    out = {"ticker": ticker, "name": name, "source": source,
           "fetchedAt": datetime.now(timezone.utc).isoformat(),
           "dailyStart": daily[0]["d"], "lastDate": daily[-1]["d"],
           "nDaily": len(daily), "nMonthly": len(monthly),
           "daily": daily, "monthly": monthly}
    with open(os.path.join(DATA, f"{ticker}.json"), "w") as f:
        json.dump(out, f)
    return out


def main():
    cugc = write("CUGC", "Copper/Gold ratio (Norgate #CUGC)", "norgate:#CUGC",
                 from_norgate_cugc())
    print(f"CUGC: {cugc['nDaily']} daily, {cugc['nMonthly']} monthly, "
          f"{cugc['dailyStart']}..{cugc['lastDate']}")
    # sanity: ratio should be LOW at known growth-pessimism bottoms, high at 2011 peak
    m = {b["d"][:7]: b["ac"] for b in cugc["monthly"]}
    for k in ["2008-12", "2011-04", "2016-07", "2020-01", "2024-10", cugc["lastDate"][:7]]:
        print(f"    {k}: {m.get(k)}")

    cper = write("CPER", "United States Copper Index Fund (CPER)", "yahoo:CPER",
                 from_yahoo_full("CPER", (2010, 1, 1)))
    print(f"CPER: {cper['nDaily']} daily, {cper['dailyStart']}..{cper['lastDate']}")


if __name__ == "__main__":
    main()
