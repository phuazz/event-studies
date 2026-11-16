"""Tests for scripts/fetch_gspc_norgate.py — _drop_incomplete_month, the rule that
decides whether the trailing month-end bar of data/GSPC.json is a CLOSED month.

The bug these guard: October 2026 ends on Saturday the 31st, so its last session
(Friday the 30th) sits before the calendar month-end, and the old bar-only rule
dropped a closed October until a November bar arrived. That hid the live entry of
the midterm October card on 2026-11-01.

Every weekday below was checked with Python datetime, not written from memory. Per
the house rule the cases include a month boundary and a year boundary. Python and
pandas months are 1-indexed (October == 10).

No CI test run in this repo; run by hand after touching the fetcher:

    python -m pytest tests/test_gspc_month_close.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_gspc_norgate as f  # noqa: E402


def _series(first: str, last: str):
    idx = pd.bdate_range(first, last)
    daily = pd.DataFrame({"Close": range(1, len(idx) + 1)}, index=idx, dtype=float)
    monthly = daily["Close"].resample("ME").last()
    return daily, monthly


def _last_month(first, last, today):
    daily, monthly = _series(first, last)
    out = f._drop_incomplete_month(daily, monthly, today=today)
    return out.index[-1].date()


def test_fixture_weekdays():
    assert date(2026, 10, 30).strftime("%A") == "Friday"
    assert date(2026, 10, 31).strftime("%A") == "Saturday"
    assert date(2028, 12, 29).strftime("%A") == "Friday"
    assert date(2028, 12, 31).strftime("%A") == "Sunday"
    assert date(2026, 12, 31).strftime("%A") == "Thursday"


def test_month_boundary_weekend_month_end():
    # Last session Fri 2026-10-30; the calendar month ends Sat 2026-10-31.
    assert _last_month("2026-09-01", "2026-10-30", date(2026, 10, 31)) == date(2026, 9, 30)
    assert _last_month("2026-09-01", "2026-10-30", date(2026, 11, 1)) == date(2026, 10, 31)


def test_year_boundary_weekend_month_end():
    # Last session Fri 2028-12-29; the year ends Sun 2028-12-31.
    assert _last_month("2028-11-01", "2028-12-29", date(2028, 12, 31)) == date(2028, 11, 30)
    assert _last_month("2028-11-01", "2028-12-29", date(2029, 1, 1)) == date(2028, 12, 31)


def test_bar_on_month_end_is_kept_the_same_day():
    # Thu 2026-12-31 is itself the month-end; Norgate publishes closed bars only.
    assert _last_month("2026-11-02", "2026-12-31", date(2026, 12, 31)) == date(2026, 12, 31)


def test_feed_stopped_mid_week_is_not_a_month_end():
    # Last bar Wed 2026-10-28: Thu 29 and Fri 30 are missing, so October stays open.
    assert _last_month("2026-09-01", "2026-10-28", date(2026, 11, 1)) == date(2026, 9, 30)


def test_mid_month_is_dropped():
    assert _last_month("2026-09-01", "2026-10-15", date(2026, 10, 16)) == date(2026, 9, 30)


# Added 2026-11-16 after the independent review found three untested paths.

def test_review_fixture_weekdays():
    assert date(2026, 10, 29).strftime("%A") == "Thursday"
    assert date(2027, 5, 28).strftime("%A") == "Friday"
    assert date(2027, 5, 31).strftime("%A") == "Monday"  # Memorial Day 2027
    assert date(2026, 11, 1).strftime("%A") == "Sunday"


def test_single_missing_final_session_is_not_a_month_end():
    # Last bar Thu 2026-10-29; Fri 2026-10-30 is a weekday still to come, so October stays open.
    assert _last_month("2026-09-01", "2026-10-29", date(2026, 11, 1)) == date(2026, 9, 30)


def test_month_end_holiday_falls_back_to_waiting():
    # Memorial Day falls on Mon 2027-05-31. The last session is Fri 2027-05-28, and the rule
    # cannot tell a holiday from a missing bar, so May waits for a June bar (the docstring's claim).
    assert _last_month("2027-04-01", "2027-05-28", date(2027, 6, 1)) == date(2027, 4, 30)
    # Once a June bar exists, May is closed by the bar rule.
    assert _last_month("2027-04-01", "2027-06-01", date(2027, 6, 2)) == date(2027, 5, 31)


class _Clock:
    """Stand-in for datetime in the fetcher: UTC 2026-10-31 23:30 (Saturday, October not yet
    past) and a local Singapore reading of 2026-11-01 07:30 when called without a tz."""

    @staticmethod
    def now(tz=None):
        from datetime import datetime as real
        if tz is None:
            return real(2026, 11, 1, 7, 30)
        return real(2026, 10, 31, 23, 30, tzinfo=tz)


def test_default_today_is_the_utc_date(monkeypatch):
    # With today omitted, the rule must read the UTC date (still 31 October), not the local
    # Singapore date (already 1 November), so October is not yet treated as closed.
    monkeypatch.setattr(f, "datetime", _Clock)
    daily, monthly = _series("2026-09-01", "2026-10-30")
    out = f._drop_incomplete_month(daily, monthly)
    assert out.index[-1].date() == date(2026, 9, 30)
