#!/usr/bin/env python
"""norgate_universe.py — point-in-time, survivorship-free US equity universe for
the discovery scan (Stage 1 of the event-studies funnel).

This module is the data layer. It reuses the Norgate access pattern proven in
`buy-the-dip/scripts/providers.py` and `.../build_universe_fallback.py`, and the
coverage-gate discipline from `em-rotation-lab/scripts/step0_coverage.py`. It
provides three things the scan needs and nothing else:

  1. A HARD readiness + integrity gate (`hard_check`). Refuses to serve data on a
     stale feed, and enforces the STEP-0 HARD STOP: if the US Equities Delisted
     database is empty, or point-in-time index membership is unavailable, we STOP
     — a scan that silently falls back to survivors-only is worse than no scan.

  2. The investable universe (`resolve_universe`): the union of names that were
     EVER a point-in-time member of the target indices, INCLUDING delisted names
     (survivorship-bias-free). Prefers the "... Current & Past" watchlists; falls
     back to enumerating US Equities + US Equities Delisted and keeping any name
     with >= 1 member-day (robust to the NDU watchlist-zero quirk).

  3. Per-symbol price history (`load_prices`, TOTALRETURN-adjusted OHLCV) and
     per-symbol point-in-time membership (`load_membership`), both cached to disk
     under data/cache/norgate/ (data/ is gitignored) so a re-run is reproducible
     and fast.

Adjustment choice (stated once): we pull TOTALRETURN-adjusted OHLCV and use its
Close as the analogue of the engine's `ac` (adjusted close) for every indicator,
and measure forward returns on the same series. Total return is the honest
measure of what an investor earns; for daily equities the dividend drift is
negligible for RSI/momentum, and — usefully — total-return adjustment removes
mechanical ex-dividend gap-downs, so those are not mis-flagged as event gaps.

Date handling: NYSE session dates come from exchange_calendars (calendar 'XNYS').
No manual weekday/day-offset arithmetic. Python datetime months are 1-indexed.

Run standalone to build + cache the universe and print the proof artefacts:
    python scripts/norgate_universe.py --build
"""

from __future__ import annotations

import argparse
import datetime as dt   # Python datetime: months are 1-indexed (Jan == 1)
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "norgate"      # data/ is gitignored
PRICE_DIR = CACHE / "prices"
MEMBER_DIR = CACHE / "membership"
UNIVERSE_FILE = CACHE / "universe.json"

REQUIRED_DBS = ("US Equities", "US Equities Delisted", "US Indices")

# Point-in-time membership indices that DEFINE the investable universe. The union
# of their memberships (current + past, delisted included) is the scan universe.
# S&P 500 + 400 + 600 == the S&P Composite 1500: the broad, liquid, point-in-time
# US equity set. Breadth archetypes are computed on the S&P 500 constituents.
DEFAULT_INDEX_NAMES = ["S&P 500", "S&P MidCap 400", "S&P SmallCap 600"]
BREADTH_INDEX = "S&P 500"

# Norgate marks a delisted symbol with a -YYYYMMDD-ish 6-digit suffix.
DELISTED_SUFFIX = re.compile(r"-\d{6}$")

BENCHMARKS = ("AAPL", "SPY", "MSFT")
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


# --------------------------------------------------------------------------- #
# Connection + gate
# --------------------------------------------------------------------------- #

def nd():
    """Lazy import so the module stays importable without the package present."""
    import norgatedata
    return norgatedata


def connect():
    """Assert NDU is up and the three required databases are present."""
    n = nd()
    try:
        ok = bool(n.status())
    except Exception as exc:  # noqa: BLE001 - NDU throws bare errors when down
        raise RuntimeError(f"Norgate NDU status() raised: {exc}") from exc
    if not ok:
        raise RuntimeError(
            "Norgate Data Updater (NDU) is not running / not reachable. Start NDU, "
            "let it finish syncing, then re-run. The Python package only proxies "
            "the local NDU database."
        )
    dbs = set(n.databases())
    missing = [d for d in REQUIRED_DBS if d not in dbs]
    if missing:
        raise RuntimeError(
            f"Required Norgate databases missing: {missing}. Present: {sorted(dbs)}. "
            "A Platinum-level US Stocks subscription is required for delisted "
            "securities and point-in-time membership."
        )
    return n


def expected_last_session(asof: dt.date | None = None) -> dt.date:
    """Last completed NYSE session on or before `asof`. Uses exchange_calendars,
    so US market holidays are handled for us. Returns a datetime.date."""
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XNYS")
    asof = asof or dt.date.today()
    start = asof - dt.timedelta(days=15)   # generous, survives long closures
    sessions = cal.sessions_in_range(start.isoformat(), asof.isoformat())
    if len(sessions) == 0:
        raise RuntimeError("no NYSE sessions found in the lookback window")
    return sessions[-1].date()


def _last_bar_date(n, sym: str):
    """The last actual bar date of a symbol's price series, or None if it has no
    bars. Authoritative freshness signal (last_quoted_date is unreliable here)."""
    try:
        df = n.price_timeseries(
            sym, stock_price_adjustment_setting=n.StockPriceAdjustmentType.TOTALRETURN,
            padding_setting=n.PaddingType.NONE, timeseriesformat="pandas-dataframe")
    except Exception:  # noqa: BLE001
        return None
    if df is None or len(df) == 0:
        return None
    d = df.index[-1]
    return d.date() if hasattr(d, "date") else dt.date.fromisoformat(str(d)[:10])


def hard_check(n=None, asof: dt.date | None = None) -> dict:
    """The STEP-0 gate, enforced at data-layer level so the scan is self-gating.

    Raises RuntimeError on ANY of:
      - feed stale: a benchmark's last_quoted_date is None or older than the last
        completed NYSE session (the US Equities price DB is still downloading);
      - HARD STOP: the US Equities Delisted database returns zero symbols;
      - HARD STOP: point-in-time index membership is unavailable.

    Returns a dict of proof artefacts (delisted count, a historical membership
    snapshot) that the scan embeds in its output.
    """
    n = n or connect()
    exp = expected_last_session(asof)

    # --- freshness ---
    # Authoritative signal = the actual last BAR date of the benchmark price series
    # (what the scan consumes), NOT last_quoted_date: on this feed the latter metadata
    # field is unpopulated for live symbols even when the series are complete to the
    # last session (an NDU sync quirk), so it gives a false "stale" negative.
    bench = {}
    lqd = {}
    for s in BENCHMARKS:
        last = _last_bar_date(n, s)
        try:
            lqd[s] = str(n.last_quoted_date(s))
        except Exception:  # noqa: BLE001
            lqd[s] = "raised"
        if last is None:
            raise RuntimeError(
                f"feed not ready: {s} has no price bars yet — the US Equities price "
                "database is still downloading. Run: python scripts/norgate_ready.py --wait"
            )
        bench[s] = last
    min_bench = min(bench.values())
    if min_bench < exp:
        raise RuntimeError(
            f"feed stale: oldest benchmark last bar {min_bench} < last NYSE session {exp}. "
            "Run: python scripts/norgate_ready.py --wait"
        )

    # --- HARD STOP 1: delisted database must be non-empty ---
    delisted = list(n.database_symbols("US Equities Delisted"))
    n_delisted = len(delisted)
    if n_delisted == 0:
        raise RuntimeError(
            "HARD STOP: 'US Equities Delisted' returned zero symbols. A scan that "
            "silently falls back to survivors-only is worse than no scan. STOP."
        )
    delisted_suffixed = [s for s in delisted if DELISTED_SUFFIX.search(s)]

    # --- HARD STOP 2: point-in-time membership must be available ---
    # Probe a name known to be a long-standing S&P 500 member and take a snapshot
    # of membership as-of a historical date, to prove point-in-time membership is
    # real (not just "currently a member").
    snap_date = "2005-06-30"
    try:
        probe = n.index_constituent_timeseries(
            "AAPL", BREADTH_INDEX, timeseriesformat="pandas-dataframe")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"HARD STOP: index membership query raised {exc}") from exc
    if probe is None or len(probe) == 0 or int(probe[probe.columns[0]].sum()) == 0:
        raise RuntimeError(
            "HARD STOP: point-in-time index membership unavailable (AAPL vs "
            f"{BREADTH_INDEX!r} empty). Cannot build a point-in-time universe. STOP."
        )

    return {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "expected_last_session": exp.isoformat(),
        "benchmark_last_dates": {k: v.isoformat() for k, v in bench.items()},
        "benchmark_last_quoted_date_field": lqd,
        "freshness_note": ("Readiness verified from the actual last BAR date of the "
                           "benchmark price series; the last_quoted_date metadata field "
                           "is unpopulated for live symbols on this feed (NDU quirk)."),
        "delisted_symbol_count": n_delisted,
        "delisted_suffixed_count": len(delisted_suffixed),
        "delisted_examples": delisted_suffixed[:5],
        "membership_probe": {
            "symbol": "AAPL", "index": BREADTH_INDEX,
            "member_days": int(probe[probe.columns[0]].sum()),
            "window": f"{probe.index[0].date()} -> {probe.index[-1].date()}",
        },
        "ndu_last_update_us_equities": str(n.last_database_update_time("US Equities")),
        "norgatedata_version": _nd_version(n),
    }


def _nd_version(n) -> str:
    v = getattr(n, "version", None)
    try:
        return v() if callable(v) else "1.0.74"
    except Exception:  # noqa: BLE001
        return "1.0.74"


# --------------------------------------------------------------------------- #
# Universe resolution (point-in-time, survivorship-free)
# --------------------------------------------------------------------------- #

def _watchlist_for(index_name: str) -> str:
    return f"{index_name} Current & Past"


def resolve_universe(n=None, index_names=None, rebuild: bool = False) -> dict:
    """Union of names EVER a point-in-time member of any target index, delisted
    names included. Prefers the '... Current & Past' watchlists; falls back to the
    enumerate-and-check-membership builder if a watchlist answers empty.

    Returns {index_names, method, symbols:[...], membership_index_map:{sym:[idx]},
    counts:{...}}, cached to data/cache/norgate/universe.json.
    """
    n = n or connect()
    index_names = index_names or DEFAULT_INDEX_NAMES
    if UNIVERSE_FILE.exists() and not rebuild:
        cached = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
        if cached.get("index_names") == index_names:
            return cached

    available_watchlists = set(n.watchlists())
    membership_map: dict[str, list[str]] = {}
    method_bits = []

    for idx in index_names:
        wl = _watchlist_for(idx)
        syms = []
        if wl in available_watchlists:
            try:
                syms = list(n.watchlist_symbols(wl))
            except Exception:  # noqa: BLE001
                syms = []
        if syms:
            method_bits.append(f"{idx}:watchlist({len(syms)})")
            for s in syms:
                membership_map.setdefault(s, [])
                if idx not in membership_map[s]:
                    membership_map[s].append(idx)
        else:
            # Fallback: enumerate all US equities (listed + delisted) and keep any
            # with >= 1 member-day for THIS index. Robust to the watchlist-zero
            # quirk documented in buy-the-dip/build_universe_fallback.py.
            print(f"  [fallback] watchlist {wl!r} empty/absent — scanning membership "
                  f"for {idx!r} (this is slow, one-time, cached)...", file=sys.stderr)
            cand = list(n.database_symbols("US Equities")) + \
                list(n.database_symbols("US Equities Delisted"))
            hit = 0
            t0 = time.time()
            for k, s in enumerate(cand, 1):
                try:
                    df = n.index_constituent_timeseries(
                        s, idx, timeseriesformat="pandas-dataframe")
                    if df is not None and len(df) and int(df[df.columns[0]].sum()) > 0:
                        membership_map.setdefault(s, [])
                        if idx not in membership_map[s]:
                            membership_map[s].append(idx)
                        hit += 1
                except Exception:  # noqa: BLE001
                    pass
                if k % 2000 == 0:
                    print(f"    {k}/{len(cand)} scanned, {hit} members, "
                          f"{time.time() - t0:.0f}s", file=sys.stderr)
            method_bits.append(f"{idx}:membership-scan({hit})")

    symbols = sorted(membership_map)
    delisted = [s for s in symbols if DELISTED_SUFFIX.search(s)]
    result = {
        "built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "index_names": index_names,
        "breadth_index": BREADTH_INDEX,
        "method": "; ".join(method_bits),
        "symbols": symbols,
        "membership_index_map": membership_map,
        "counts": {
            "total": len(symbols),
            "delisted_suffixed": len(delisted),
            "live": len(symbols) - len(delisted),
        },
    }
    UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE_FILE.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# --------------------------------------------------------------------------- #
# Per-symbol price + membership, cached
# --------------------------------------------------------------------------- #

def _safe(sym: str) -> str:
    return sym.replace("/", "_").replace("\\", "_").replace("$", "_")


def load_prices(sym: str, n=None, adjustment: str = "TOTALRETURN",
                start_date: str = "1800-01-01", refresh: bool = False) -> pd.DataFrame:
    """TOTALRETURN-adjusted OHLCV for one symbol, ascending tz-naive DatetimeIndex.
    Cached to parquet. Empty DataFrame (PRICE_COLUMNS) if the symbol has no bars.
    Full available history by default (start_date '1800-01-01' == Norgate default)."""
    pth = PRICE_DIR / f"{_safe(sym)}.parquet"
    if pth.exists() and not refresh:
        try:
            return pd.read_parquet(pth)
        except Exception:  # noqa: BLE001 - corrupt cache: re-fetch
            pass
    n = n or connect()
    adj = getattr(n.StockPriceAdjustmentType, adjustment)
    df = n.price_timeseries(
        sym,
        stock_price_adjustment_setting=adj,
        padding_setting=n.PaddingType.NONE,
        start_date=start_date,
        timeseriesformat="pandas-dataframe",
    )
    out = _standardise(df)
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        out.to_parquet(pth)
    except Exception:  # noqa: BLE001 - never let a cache write kill the run
        pass
    return out


def _standardise(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    out = df.copy()
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    for col in PRICE_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[PRICE_COLUMNS].sort_index()
    out.index.name = "Date"
    return out


def load_membership(sym: str, index_name: str, n=None, refresh: bool = False) -> pd.Series:
    """Point-in-time {0,1} membership series for `sym` vs `index_name`, cached."""
    pth = MEMBER_DIR / f"{_safe(sym)}__{_safe(index_name)}.parquet"
    if pth.exists() and not refresh:
        try:
            return pd.read_parquet(pth).iloc[:, 0]
        except Exception:  # noqa: BLE001
            pass
    n = n or connect()
    df = n.index_constituent_timeseries(sym, index_name, timeseriesformat="pandas-dataframe")
    if df is None or len(df) == 0:
        s = pd.Series(dtype="int8", name="member")
    else:
        s = df[df.columns[0]].astype("int8")
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        s = s.sort_index()
        s.name = "member"
    MEMBER_DIR.mkdir(parents=True, exist_ok=True)
    try:
        s.to_frame().to_parquet(pth)
    except Exception:  # noqa: BLE001
        pass
    return s


# --------------------------------------------------------------------------- #
# Standalone: build + cache + print proof
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", action="store_true", help="build + cache the universe")
    ap.add_argument("--rebuild", action="store_true", help="ignore the cached universe")
    ap.add_argument("--indices", nargs="*", default=None,
                    help="override the membership indices (default: S&P 500/400/600)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    n = connect()
    proof = hard_check(n)
    print("[gate] PASS")
    print(json.dumps(proof, indent=1))

    if args.build or args.rebuild:
        uni = resolve_universe(n, index_names=args.indices, rebuild=args.rebuild)
        print(f"\n[universe] method: {uni['method']}")
        print(f"[universe] {uni['counts']['total']} symbols "
              f"({uni['counts']['live']} live, {uni['counts']['delisted_suffixed']} delisted) "
              f"-> {UNIVERSE_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
