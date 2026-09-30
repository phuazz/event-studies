#!/usr/bin/env python
"""norgate_ready.py — readiness gate for the Norgate US data feed.

Purpose: a remote/autonomous session must NOT start the discovery scan while the
Norgate Data Updater (NDU) is mid-download, or it will read a stale / partially
written database and produce a confident-but-wrong lead sheet.

Confirmed behaviour (NDU 4.2.2.65 / norgatedata 1.0.74): while the US Equities
price database is downloading, per-symbol queries return None. Once the edition
completes, last_quoted_date() returns the latest bar date. So readiness =
benchmark symbols return a NON-None date that is >= the last completed NYSE
session, held stable across two reads.

Failure mode observed 2026-07-04 (a market-closed Saturday; Fri 3 Jul was the
Independence Day observance): after a clean update, last_quoted_date() AND
second_last_quoted_date() returned None for EVERY symbol across EVERY database
(US Equities, US Indices, Forex Spot) while price_timeseries() returned the full,
correct series through the last session (2026-07-02) and first_quoted_date()
worked. I.e. the price arrays were present but the "last quoted date" pointer was
unset — NDU has no live current session on a closed day. Keying readiness solely
on last_quoted_date() therefore deadlocks the gate across a long weekend even
though the data is fine. Fix: when last_quoted_date() is None, fall back to the
last bar date read straight from price_timeseries(), and log loudly that NDU's
metadata pointer still needs a rebuild.

Date handling: NYSE session dates and close times come from exchange_calendars
(calendar 'XNYS'). "The last completed session" means the last one that has
CLOSED by the instant of the check, in UTC, not the last one dated on or before
the machine's local date (see expected_last_session). No manual weekday/day-offset
arithmetic. Python datetime months are 1-indexed.

Exit codes (single-check mode): 0 = ready, 2 = not ready, 3 = error.
Usage:
  python scripts/norgate_ready.py            # one check, prints status, sets exit code
  python scripts/norgate_ready.py --wait     # block, poll until ready (or --timeout)
  python scripts/norgate_ready.py --selftest # run date-logic edge-case tests
"""

import argparse
import datetime as dt
import sys
import time

BENCHMARKS = ["AAPL", "SPY", "MSFT"]  # liquid, always-present names
POLL_SECONDS = 120                     # gap between polls in --wait mode
STABLE_CONFIRM_SECONDS = 60            # a ready read must still hold this much later


def expected_last_session(asof=None, cal=None):
    """The last NYSE session that has CLOSED by `asof`. Returns a datetime.date.

    `asof` is one of:
      - None (the default): the instant of the check, now, in UTC;
      - a timezone-aware datetime: that instant (a naive one is refused, because
        the machine's local zone is exactly what went wrong before);
      - a date: an explicit as-of day, read as "after that day's close", so the
        session dated `asof` counts if there is one. Historical re-runs pass this.

    WHY THE INSTANT MATTERS (fixed 2026-09-29). This used to take the machine's
    local date and return the last session dated on or before it, whether or not
    that session had closed. On this machine the local zone is Singapore, where
    that is wrong for every weekday: a US session closes at 04:00 SGT the next day
    (05:00 in US standard time), so by the time its bars can exist the local date
    has already moved on to a session that has not opened. The gate therefore
    demanded a bar that could not exist yet, and could only pass on a day whose SGT
    date was a weekend or a US holiday.
    Observed on 2026-09-29 at 14:26 UTC: NOT-READY, expected 2026-09-29, against a
    feed complete through 2026-09-28 while the 29th was still trading.

    Close times come from exchange_calendars, so holidays, early closes (the day
    after Thanksgiving, Christmas Eve) and daylight saving are handled for us. No
    manual day or weekday arithmetic.
    """
    import exchange_calendars as xcals
    import pandas as pd
    cal = cal or xcals.get_calendar("XNYS")
    if isinstance(asof, dt.datetime):          # checked first: a datetime IS a date
        if asof.tzinfo is None:
            raise ValueError("expected_last_session: a datetime asof must be timezone-aware")
        now = pd.Timestamp(asof).tz_convert("UTC")
    elif isinstance(asof, dt.date):
        now = None
    else:
        now = pd.Timestamp.now(tz="UTC")
    # The last day any candidate session can be dated. For an instant, its UTC date
    # is enough: a session dated later than that cannot have opened, let alone closed.
    end = now.date() if now is not None else asof
    # Look back a generous window to survive long holiday closures.
    start = end - dt.timedelta(days=15)
    sessions = list(cal.sessions_in_range(start.isoformat(), end.isoformat()))
    if now is not None:
        sessions = [s for s in sessions if cal.session_close(s) <= now]
    if not sessions:
        raise RuntimeError("no closed NYSE session found in the lookback window")
    return sessions[-1].date()


def _price_tail_date(symbol, lookback_days=25):
    """Last bar date from the price series itself, as 'YYYY-MM-DD' or None.

    Robust fallback for when last_quoted_date() returns None even though the
    price array is present and current (the market-closed-day pointer bug noted
    above). Reads the array directly rather than the possibly-unset pointer.
    """
    import norgatedata
    start = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    try:
        df = norgatedata.price_timeseries(
            symbol, start_date=start, timeseriesformat="pandas-dataframe")
    except Exception:  # noqa: BLE001
        return None
    if df is None or len(df) == 0:
        return None
    try:
        return df.index[-1].date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def check_once():
    """Return (ready: bool, detail: dict)."""
    import norgatedata

    expected = expected_last_session()
    dates = {}
    method = {}
    for s in BENCHMARKS:
        d = None
        try:
            d = norgatedata.last_quoted_date(s)
        except Exception:  # noqa: BLE001 - NDU throws bare errors mid-write
            d = None
        if d is not None:
            # norgatedata returns 'YYYY-MM-DD' str or a date-like; normalise.
            dates[s] = str(d)[:10]
            method[s] = "meta"
            continue
        # last_quoted_date() is None: either mid-download (data absent) or the
        # market-closed-day pointer bug (data present, pointer unset).
        # Disambiguate by reading the price array directly.
        td = _price_tail_date(s)
        dates[s] = td
        method[s] = "price-tail" if td is not None else "none"

    parsed = []
    for s in BENCHMARKS:
        v = dates[s]
        if v and not v.startswith("ERR:"):
            try:
                parsed.append(dt.date.fromisoformat(v))
            except ValueError:
                pass

    # Ready only if EVERY benchmark returned a real date and the oldest of them
    # is at least the last completed session (i.e. the feed is fully caught up).
    all_present = len(parsed) == len(BENCHMARKS)
    fresh = all_present and min(parsed) >= expected

    # Survivorship advisory (not a hard gate here; the build must hard-check it):
    delisted_n = None
    try:
        syms = norgatedata.database_symbols("US Equities Delisted")
        delisted_n = len(syms) if syms is not None else 0
    except Exception:  # noqa: BLE001
        delisted_n = None

    detail = {
        "expected_last_session": expected.isoformat(),
        "benchmark_dates": dates,
        "method": method,
        "used_fallback": any(m == "price-tail" for m in method.values()),
        "delisted_symbol_count": delisted_n,
    }
    return fresh, detail


def _print(ready, detail, prefix=""):
    tag = "READY" if ready else "NOT-READY"
    fb = ""
    if detail.get("used_fallback"):
        # First seen on a market-closed day (2026-07-04), but not confined to one:
        # on 2026-09-29 and 2026-09-30, both trading days, the field was None for
        # every benchmark while the price arrays were complete.
        fb = ("  [via price-tail fallback: NDU last_quoted_date is None for the "
              "benchmarks; freshness read from the price arrays, which are present]")
    print(f"{prefix}[{tag}] expected>={detail['expected_last_session']} "
          f"benchmarks={detail['benchmark_dates']} "
          f"delisted_symbols={detail['delisted_symbol_count']}{fb}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true", help="poll until ready")
    ap.add_argument("--interval", type=int, default=POLL_SECONDS)
    ap.add_argument("--timeout", type=int, default=0, help="seconds; 0 = no cap")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.wait:
        try:
            ready, detail = check_once()
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] {e}")
            return 3
        _print(ready, detail)
        return 0 if ready else 2

    # --wait: poll, and require a ready read to still hold after a short delay
    # so we never trip on a half-written database that momentarily looks fresh.
    waited = 0
    while True:
        try:
            ready, detail = check_once()
        except Exception as e:  # noqa: BLE001
            ready, detail = False, {"expected_last_session": "?",
                                    "benchmark_dates": {"_": f"ERR:{e}"},
                                    "delisted_symbol_count": None}
        _print(ready, detail, prefix=f"t+{waited}s ")
        if ready:
            time.sleep(STABLE_CONFIRM_SECONDS)
            waited += STABLE_CONFIRM_SECONDS
            confirm, detail2 = check_once()
            _print(confirm, detail2, prefix=f"t+{waited}s confirm ")
            if confirm:
                print("[DONE] Norgate US feed is fresh and stable — proceed.")
                return 0
        if args.timeout and waited >= args.timeout:
            print("[TIMEOUT] gave up waiting for Norgate feed")
            return 2
        time.sleep(args.interval)
        waited += args.interval


def selftest():
    """Edge-case tests for the session helper, on the real XNYS calendar.

    exchange_calendars computes sessions from rules, so this is deterministic and
    offline. Python months are 1-indexed (Jan=1, Dec=12). Every instant is written
    in UTC unless stated; NYSE opens 13:30 UTC and closes 20:00 UTC in US daylight
    time, 14:30 and 21:00 UTC in standard time.
    """
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XNYS", start="2026-01-01", end="2027-12-31")
    utc = dt.timezone.utc
    sgt = dt.timezone(dt.timedelta(hours=8))
    D = dt.date

    cases = [
        # --- explicit as-of DAYS keep their old meaning: after that day's close ---
        ("date: month boundary, Sat 1 Aug 2026 -> Fri 31 Jul",
         D(2026, 8, 1), D(2026, 7, 31)),
        ("date: year boundary, Fri 1 Jan 2027 (holiday) -> Thu 31 Dec 2026",
         D(2027, 1, 1), D(2026, 12, 31)),
        # --- instants: only a session that has CLOSED counts ---
        ("the observed failure: Tue 29 Sep 2026 14:26 UTC, the 29th still trading",
         dt.datetime(2026, 9, 29, 14, 26, tzinfo=utc), D(2026, 9, 28)),
        ("one minute after the 20:00 UTC close counts the day",
         dt.datetime(2026, 9, 29, 20, 1, tzinfo=utc), D(2026, 9, 29)),
        ("one minute before it does not",
         dt.datetime(2026, 9, 29, 19, 59, tzinfo=utc), D(2026, 9, 28)),
        ("Singapore next morning, Wed 30 Sep 06:00 SGT, is the 29th's close",
         dt.datetime(2026, 9, 30, 6, 0, tzinfo=sgt), D(2026, 9, 29)),
        ("month boundary: Thu 1 Oct 2026 14:00 UTC, trading -> Wed 30 Sep",
         dt.datetime(2026, 10, 1, 14, 0, tzinfo=utc), D(2026, 9, 30)),
        ("year boundary: Mon 4 Jan 2027 15:00 UTC, trading, 1 Jan a holiday -> 31 Dec",
         dt.datetime(2027, 1, 4, 15, 0, tzinfo=utc), D(2026, 12, 31)),
        ("early close: Fri 27 Nov 2026 closes 18:00 UTC; 18:30 counts it",
         dt.datetime(2026, 11, 27, 18, 30, tzinfo=utc), D(2026, 11, 27)),
        ("early close: 17:30 does not, and Thanksgiving (26 Nov) is skipped",
         dt.datetime(2026, 11, 27, 17, 30, tzinfo=utc), D(2026, 11, 25)),
        ("standard time: Tue 1 Dec 2026 closes 21:00 UTC; 20:30 is still trading",
         dt.datetime(2026, 12, 1, 20, 30, tzinfo=utc), D(2026, 11, 30)),
        ("daylight time: Mon 9 Mar 2026 closes 20:00 UTC; 20:30 counts it",
         dt.datetime(2026, 3, 9, 20, 30, tzinfo=utc), D(2026, 3, 9)),
    ]
    failed = 0
    for name, asof, want in cases:
        got = expected_last_session(asof=asof, cal=cal)
        ok = got == want
        failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (want {want})"))

    try:
        expected_last_session(asof=dt.datetime(2026, 9, 29, 14, 26), cal=cal)
        print("  FAIL a naive datetime was accepted")
        failed += 1
    except ValueError:
        print("  ok   a naive datetime is refused")

    if failed:
        print(f"[selftest] {failed} FAILED")
        return 1
    print(f"[selftest] {len(cases) + 1} session-date tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
