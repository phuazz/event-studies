#!/usr/bin/env python
"""fetch_usprime.py — US bank prime loan rate from Norgate (%USPRIME) into
data/USPRIME.json, the indicator behind the "first policy-rate step of a cycle" card.

WHY PRIME AND NOT FED FUNDS. The card needs a MECHANICAL, causal detector for the
first hike of a tightening cycle. The prime rate steps in discrete increments that
track the fed funds TARGET one business day behind, is publicly observable at the
time, and needs no analyst judgement about what counts as a cycle start.

%FFYE (EFFECTIVE fed funds) was tried first and is unusable: it is a market rate that
wanders daily, giving 1,520 step-ups above 10bp since 1980 and recovering only three
cycle starts. Prime gives 102 step-ups and recovers every one.

STAMPING CONVENTION, verified: the FOMC announced on Wed 2026-03-16 in the 2022 case
and the series prints the new 3.50 level on Thu 2022-03-17. Norgate stamps prime by
its EFFECTIVE date, which already lags the announcement by one session. Entry at the
step-date close is therefore causal — the decision had been public since the previous
afternoon — and no look-ahead is involved.

Not wired into universes.json / fetch_history.js: that pipeline is Yahoo and has no
prime-rate series. This file is Norgate-sourced and refreshed by running this script,
the same arrangement as GSPC.json, NDX.json and AAII.json.

Python datetime months are 1-indexed. Run: python scripts/fetch_usprime.py
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SYM = "%USPRIME"
START = "1978-01-01"


def main():
    import norgatedata as nd

    df = nd.price_timeseries(SYM, start_date=START,
                             timeseriesformat="pandas-dataframe").sort_index()
    c = df["Close"].astype(float).dropna()
    c = c[c > 0]
    if len(c) < 5000:
        raise SystemExit(f"FATAL: {SYM} returned only {len(c)} bars — refusing to write")

    daily = [{"d": i.date().isoformat(), "v": round(float(v), 4)} for i, v in c.items()]

    # Integrity: the detector keys off discrete step-ups, so a series that had been
    # silently interpolated or forward-filled into a continuum would produce garbage
    # triggers. Count them here and fail loudly if the shape is not step-like.
    steps = sum(1 for a, b in zip(daily, daily[1:]) if b["v"] - a["v"] > 0.10)
    flat = sum(1 for a, b in zip(daily, daily[1:]) if b["v"] == a["v"])
    if steps > 500 or flat / max(len(daily) - 1, 1) < 0.90:
        raise SystemExit(f"FATAL: {SYM} does not look step-like "
                         f"({steps} step-ups, {flat/(len(daily)-1):.1%} flat days) — refusing to write")

    out = {"ticker": "USPRIME", "name": "US bank prime loan rate",
           "source": f"norgate:{SYM}",
           "cadence": "daily",
           "stampingRule": "stamped by EFFECTIVE date, one session behind the FOMC announcement — entry at the step-date close is causal",
           "fetchedAt": datetime.now(timezone.utc).isoformat(),
           "start": daily[0]["d"], "lastDate": daily[-1]["d"],
           "n": len(daily), "nStepUps": steps, "daily": daily}
    p = os.path.join(DATA, "USPRIME.json")
    json.dump(out, open(p, "w"), separators=(",", ":"))
    print(f"  USPRIME: {len(daily)} daily bars {daily[0]['d']}..{daily[-1]['d']} "
          f"(latest {daily[-1]['v']:.2f}%, {steps} step-ups >10bp, {flat/(len(daily)-1):.1%} flat)")


if __name__ == "__main__":
    main()
