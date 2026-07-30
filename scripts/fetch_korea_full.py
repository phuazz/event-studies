#!/usr/bin/env python
"""fetch_korea_full.py — full-daily Yahoo history for the KOSPI panic-breadth study.

The main Yahoo fetch (scripts/fetch_history.js) caps daily at 10 years. On a
2016+ window the rare KOSPI panic-breadth signal (>=80% of the basket at a fresh
12-week low) fires just once (COVID). This pulls FULL daily history (2005+) for
EWY (the target) and the `korea` basket, so the study also sees the 2008 / 2011 /
2015 / 2018 / 2022 crashes.

SURVIVORSHIP: the basket is EWY's CURRENT holdings (see universes.json `korea`
_doc). Extending back to 2005 makes the survivorship bias WORSE — more names have
dropped out over 20 years than over 10 — so the card's caveat stands doubly.

PIPELINE NOTE: run this AFTER scripts/fetch_history.js. fetch_history will
overwrite these .KS / EWY files with 10-year versions, so re-run this to restore
full history for the Korea study. A proper fix wires a per-universe full-history
flag into fetch_history — a follow-up.

Run: python scripts/fetch_korea_full.py
"""
import calendar
import json
import os
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
UNI = json.load(open(os.path.join(HERE, "..", "universes.json")))
TICKERS = ["EWY"] + [t["t"] for t in UNI["universes"]["korea"]["tickers"]]
P1 = calendar.timegm((2005, 1, 1, 0, 0, 0))
P2 = int(datetime.now(timezone.utc).timestamp())


def fetch(sym):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={P1}&period2={P2}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    j = json.load(urllib.request.urlopen(req, timeout=40))
    r = j["chart"]["result"][0]
    ts = r["timestamp"]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    return [{"d": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
             "ac": round(float(a), 4)}
            for t, a in zip(ts, adj) if a is not None and a > 0]


def main():
    ok = 0
    for sym in TICKERS:
        try:
            daily = fetch(sym)
            if len(daily) < 200:
                print(f"  {sym}: only {len(daily)} bars — skip")
                continue
            out = {"ticker": sym, "source": "yahoo-full-daily-2005",
                   "fetchedAt": datetime.now(timezone.utc).isoformat(),
                   "dailyStart": daily[0]["d"], "lastDate": daily[-1]["d"],
                   "nDaily": len(daily), "daily": daily}
            with open(os.path.join(DATA, f"{sym}.json"), "w") as f:
                json.dump(out, f)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {sym}: ERR {type(e).__name__}: {e}")
    print(f"wrote {ok}/{len(TICKERS)} full-daily files (2005+), source=yahoo")


if __name__ == "__main__":
    main()
