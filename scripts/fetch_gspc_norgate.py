#!/usr/bin/env python
"""fetch_gspc_norgate.py — pull the S&P 500 PRICE index from Norgate ($SPX) and
write data/GSPC.json in the event-engine's shape.

This feeds the "strong 2nd quarter" seasonal event study, which is a PRICE-index
study (no dividend adjustment), so we use $SPX (price) and NOT $SPXTR (total
return). The series is month-end resampled for the seasonal signal, plus a ~10y
daily tail for the sanity check.

Design notes:
  - Do NOT gate on norgatedata's last_quoted_date. It returns None today (a
    documented market-closed-day / metadata-pointer quirk); the price series is
    complete regardless. We read the series directly and sanity-check that its
    last DAILY bar is within a few sessions of today.
  - Do NOT wire GSPC into universes.json / fetch_history.js — that pipeline is
    Yahoo and would fail on a caret-less "GSPC". This file is Norgate-sourced and
    refreshed independently by running this script.
  - The last month is dropped if it has not yet closed (an incomplete current
    month would otherwise be written as a future-dated "month-end" bar). The
    seasonal signal fires at the June month-end close, so the last CLOSED month
    is the correct terminal bar.
  - Fallback: if Norgate is unreachable/stale, pull Yahoo ^GSPC monthly (1985+;
    Yahoo hard-caps ^GSPC at 1985) into the same shape and flag the shorter
    history.

Python dates are 1-indexed for months (June == 6). We use pandas offsets and
datetime for all date arithmetic — never hand-rolled day counting.

Run: python scripts/fetch_gspc_norgate.py
"""

import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA_DIR, "GSPC.json")

DAILY_TAIL_YEARS = 10
SANITY_MAX_STALE_DAYS = 7  # last daily bar must be within a week of "today"


def _round2(x):
    return round(float(x), 2)


def _build_payload(daily_df, monthly_series, source, name):
    """Assemble the engine-shape dict from a daily OHLC frame (needs a 'Close'
    column, DatetimeIndex) and a month-end Close series."""
    # Monthly bars: {d: ISO month-end, ac: price close}.
    monthly = [
        {"d": ts.strftime("%Y-%m-%d"), "ac": _round2(v)}
        for ts, v in monthly_series.items()
        if pd.notna(v)
    ]

    # ~10y daily tail for the sanity check / any future daily use.
    last_daily = daily_df.index[-1]
    cutoff = last_daily - pd.DateOffset(years=DAILY_TAIL_YEARS)
    tail = daily_df.loc[daily_df.index >= cutoff]
    daily = [
        {"d": ts.strftime("%Y-%m-%d"), "ac": _round2(row["Close"])}
        for ts, row in tail.iterrows()
        if pd.notna(row["Close"])
    ]

    return {
        "ticker": "GSPC",
        "name": name,
        "source": source,
        "monthly": monthly,
        "daily": daily,
        "dailyStart": daily[0]["d"] if daily else None,
        "lastDate": daily[-1]["d"] if daily else None,
        "nMonthly": len(monthly),
        "nDaily": len(daily),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


def _drop_incomplete_month(daily_df, monthly_series):
    """Drop the trailing monthly bar if its calendar month has not yet closed.
    resample('ME').last() dates a partial current month to its future month-end;
    an incomplete month must not be written as a closed month-end bar."""
    if monthly_series.empty:
        return monthly_series
    last_daily = daily_df.index[-1]
    # Month-end of the last daily bar's month (pandas MonthEnd(0) is 1-indexed-safe).
    month_end_of_last = last_daily + pd.offsets.MonthEnd(0)
    if last_daily < month_end_of_last:
        # Current month is not closed yet — drop its (future-dated) month-end bar.
        return monthly_series.iloc[:-1]
    return monthly_series


def fetch_norgate():
    import norgatedata as nd

    df = nd.price_timeseries(
        "$SPX", start_date="1949-01-01", timeseriesformat="pandas-dataframe"
    )
    if df is None or df.empty or "Close" not in df.columns:
        raise RuntimeError("Norgate $SPX returned no usable data")

    df = df[~df.index.duplicated(keep="last")].sort_index()

    # Sanity: last daily bar must be recent (do NOT use last_quoted_date — it is
    # None today, the documented quirk). Anchor on "now".
    last_daily = df.index[-1]
    stale_days = (datetime.now() - last_daily.to_pydatetime()).days
    if stale_days > SANITY_MAX_STALE_DAYS:
        raise RuntimeError(
            f"Norgate $SPX last bar {last_daily.date()} is {stale_days} days stale "
            f"(> {SANITY_MAX_STALE_DAYS}) — treating as stale, falling back"
        )

    monthly = df["Close"].resample("ME").last()
    monthly = _drop_incomplete_month(df, monthly)

    print(
        f"[norgate] $SPX daily {df.index[0].date()}..{last_daily.date()} "
        f"({len(df)} bars); monthly {monthly.index[0].date()}..{monthly.index[-1].date()} "
        f"({len(monthly)} closed months)"
    )
    return _build_payload(
        df, monthly, "norgate:$SPX", "S&P 500 (price index, Norgate $SPX)"
    )


def fetch_yahoo_fallback():
    """Yahoo ^GSPC monthly (1985+; Yahoo hard-caps ^GSPC at 1985). URL-encode the
    caret as %5E."""
    import urllib.request

    end = int(datetime.now(timezone.utc).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
        f"?period1=0&period2={end}&interval=1mo&events=div"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    rows = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc)
        rows.append((pd.Timestamp(d.date()), c))
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame({"Close": [r[1] for r in rows]}, index=idx).sort_index()
    monthly = df["Close"].resample("ME").last()
    monthly = _drop_incomplete_month(df, monthly)
    print(
        f"[yahoo-fallback] ^GSPC monthly {monthly.index[0].date()}.."
        f"{monthly.index[-1].date()} ({len(monthly)} closed months) — SHORT HISTORY (1985+)"
    )
    payload = _build_payload(
        df, monthly, "yahoo:^GSPC", "S&P 500 (price index, Yahoo ^GSPC, 1985+)"
    )
    payload["historyNote"] = "SHORT HISTORY — Yahoo fallback caps ^GSPC at 1985."
    return payload


def main():
    # Optional: log norgate_ready.py's verdict but do NOT deadlock on it (the
    # last_quoted_date pointer is None today by design).
    try:
        import subprocess

        rp = os.path.join(HERE, "norgate_ready.py")
        if os.path.exists(rp):
            out = subprocess.run(
                [sys.executable, rp], capture_output=True, text=True, timeout=60
            )
            tail = (out.stdout or out.stderr or "").strip().splitlines()
            print("[norgate_ready] " + (tail[-1] if tail else "(no output)"))
    except Exception as e:  # noqa: BLE001 — advisory only
        print(f"[norgate_ready] skipped: {e}")

    try:
        payload = fetch_norgate()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Norgate path failed ({e}); falling back to Yahoo ^GSPC 1985+")
        payload = fetch_yahoo_fallback()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(
        f"Wrote {OUT}: {payload['nMonthly']} monthly + {payload['nDaily']} daily bars, "
        f"source={payload['source']}, last={payload['lastDate']}"
    )


if __name__ == "__main__":
    main()
