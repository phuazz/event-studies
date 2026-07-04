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

Date handling: NYSE session dates come from exchange_calendars (calendar 'XNYS').
No manual weekday/day-offset arithmetic. Python datetime months are 1-indexed.

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
    """Last completed NYSE session dated on or before `asof` (a date).

    Uses exchange_calendars, so US market holidays are handled for us.
    Returns a datetime.date.
    """
    import exchange_calendars as xcals
    cal = cal or xcals.get_calendar("XNYS")
    asof = asof or dt.date.today()
    # Look back a generous window to survive long holiday closures.
    start = asof - dt.timedelta(days=15)
    sessions = cal.sessions_in_range(start.isoformat(), asof.isoformat())
    if len(sessions) == 0:
        raise RuntimeError("no NYSE sessions found in lookback window")
    return sessions[-1].date()


def check_once():
    """Return (ready: bool, detail: dict)."""
    import norgatedata

    expected = expected_last_session()
    dates = {}
    for s in BENCHMARKS:
        try:
            d = norgatedata.last_quoted_date(s)
        except Exception as e:  # noqa: BLE001 - NDU throws bare errors mid-write
            d = None
            dates[s] = f"ERR:{e!s}"
            continue
        # norgatedata returns 'YYYY-MM-DD' str or a date-like; normalise to date.
        if d is None:
            dates[s] = None
        else:
            dates[s] = str(d)[:10]

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
        "delisted_symbol_count": delisted_n,
    }
    return fresh, detail


def _print(ready, detail, prefix=""):
    tag = "READY" if ready else "NOT-READY"
    print(f"{prefix}[{tag}] expected>={detail['expected_last_session']} "
          f"benchmarks={detail['benchmark_dates']} "
          f"delisted_symbols={detail['delisted_symbol_count']}")


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
    """Edge-case tests for the date helper: one month boundary, one year boundary.

    We stub the calendar so the test is deterministic and offline. Python months
    are 1-indexed (Jan=1, Dec=12).
    """
    class _StubCal:
        def __init__(self, sessions):
            self._s = [dt.date.fromisoformat(x) for x in sessions]
        def sessions_in_range(self, start, end):
            s = dt.date.fromisoformat(start); e = dt.date.fromisoformat(end)
            class _W:  # mimic .date() on each entry
                def __init__(self, d): self._d = d
                def date(self): return self._d
            return [_W(d) for d in self._s if s <= d <= e]

    # Month boundary: asof Sat 1 Aug 2026; last session should be Fri 31 Jul.
    cal = _StubCal(["2026-07-30", "2026-07-31"])
    got = expected_last_session(asof=dt.date(2026, 8, 1), cal=cal)
    assert got == dt.date(2026, 7, 31), got

    # Year boundary: asof Fri 1 Jan 2027 (holiday); last session Thu 31 Dec 2026.
    cal = _StubCal(["2026-12-30", "2026-12-31"])
    got = expected_last_session(asof=dt.date(2027, 1, 1), cal=cal)
    assert got == dt.date(2026, 12, 31), got

    print("[selftest] date-boundary tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
