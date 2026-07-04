#!/usr/bin/env python
"""breadth_scan.py — the index-level BREADTH archetypes of the discovery grammar.

Breadth is computed POINT-IN-TIME from the S&P 500 constituents: at each date only
names that were actually members and trading that day contribute. Each member's
indicators (above/below 200d SMA, 52-week new high/low, up/down day, up-volume)
are computed CAUSALLY on its OWN contiguous series, then aggregated across the
point-in-time membership — so reindex gaps never contaminate a rolling window.

Forward returns are measured on SPY from the trigger close (the breadth->index
convention of engine/events.js). Significance reuses discovery_scan.analyse_cell
with SPY as the single name, which makes the null the events.js-style random-entry
Monte Carlo on SPY's own overlapping windows.

A calendar day is ONE breadth observation (never N stock-observations), so
pseudo-replication from the cross-section does not arise here; only time-overlap,
handled by episode clustering + the random-entry null.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu  # noqa: E402
import discovery_scan as ds    # noqa: E402

MIN_NAMES = 100          # a breadth reading needs at least this many eligible names
BREADTH_INDEX = nu.BREADTH_INDEX


def _ema(x, span):
    a = 2.0 / (span + 1.0)
    out = np.full(len(x), np.nan)
    prev = np.nan
    for i in range(len(x)):
        v = x[i]
        if not np.isfinite(v):
            out[i] = prev
            continue
        prev = v if not np.isfinite(prev) else a * v + (1 - a) * prev
        out[i] = prev
    return out


# ---- detectors on the aggregate breadth series dict `B` ----

def det_pct200_up(level):
    def f(B):
        return ds.cross_above(B["pct_above_200"], level)
    return f


def det_zweig():
    """Zweig breadth thrust: the 10-day EMA of adv/(adv+dec) rises from below 0.40
    to above 0.615 within 10 trading days. Fire when it first exceeds 0.615 having
    been below 0.40 within the trailing 10 sessions."""
    def f(B):
        ema = _ema(B["adv_ratio"], 10)
        out = np.zeros(len(ema), dtype=bool)
        for i in range(1, len(ema)):
            if not (np.isfinite(ema[i]) and np.isfinite(ema[i - 1])):
                continue
            if ema[i] > 0.615 and ema[i - 1] <= 0.615:
                k0 = max(0, i - 10)
                seg = ema[k0:i + 1]
                if np.any(seg[np.isfinite(seg)] < 0.40):
                    out[i] = True
        return out
    return f


def det_nhnl_high(level):
    def f(B):
        return ds.cross_above(B["net_nhnl"], level)
    return f


def det_nhnl_low(level):
    def f(B):
        return ds.cross_below(B["net_nhnl"], level)
    return f


def det_upvol_cluster():
    """>= 2 of the trailing 5 sessions are 90%-up-volume days. Fire on the 2nd."""
    def f(B):
        up90 = B["upvol_share"] >= 0.90
        out = np.zeros(len(up90), dtype=bool)
        for i in range(4, len(up90)):
            window = up90[i - 4:i + 1]
            if window[-1] and int(np.nansum(window)) >= 2:
                out[i] = True
        return ds.onset(out)
    return f


BREADTH_CONFIGS = [
    {"id": "br_pct200_up15", "family": "breadth", "detect": det_pct200_up(0.15),
     "mechanism": "Participation broadening — %>200d SMA thrusting up through 15% off a washout — has historically preceded durable index advances."},
    {"id": "br_pct200_up20", "family": "breadth", "detect": det_pct200_up(0.20),
     "mechanism": "%>200d SMA reclaiming 20% signals an earlier-stage breadth recovery than the 15% line."},
    {"id": "br_zweig_thrust", "family": "breadth", "detect": det_zweig(),
     "mechanism": "The Zweig breadth thrust (adv/dec 10d EMA 0.40->0.615 in <=10d) is a rare, powerful initiation of a broad advance."},
    {"id": "br_nhnl_high10", "family": "breadth", "detect": det_nhnl_high(0.10),
     "mechanism": "Net new highs surging above +10% of members marks broad demand and momentum continuation."},
    {"id": "br_nhnl_low20", "family": "breadth", "detect": det_nhnl_low(-0.20),
     "mechanism": "Net new lows spiking below -20% is a breadth washout; contrarian mean-reversion of the index tends to follow."},
    {"id": "br_upvol_cluster", "family": "breadth", "detect": det_upvol_cluster(),
     "mechanism": "A cluster of 90%-up-volume days is institutional accumulation — a classic thrust signalling a durable low."},
]


def build_breadth_series(n, members, spy_df):
    """Aggregate point-in-time breadth on SPY's date axis. Returns dict of series."""
    master = spy_df.index
    pos = {d.toordinal(): k for k, d in enumerate(master.date)}
    m = len(master)
    elig = np.zeros(m); above = np.zeros(m)
    adv = np.zeros(m); dec = np.zeros(m)
    nh = np.zeros(m); nl = np.zeros(m)
    upvol = np.zeros(m); totvol = np.zeros(m)

    used = 0
    for s in members:
        try:
            df = nu.load_prices(s, n=n)
        except Exception:  # noqa: BLE001
            continue
        if len(df) < 260:
            continue
        try:
            ms = nu.load_membership(s, BREADTH_INDEX, n=n)
        except Exception:  # noqa: BLE001
            continue
        if ms.size == 0:
            continue
        c = df["Close"].to_numpy(dtype=float)
        v = df["Volume"].to_numpy(dtype=float)
        dords = np.array([d.toordinal() for d in df.index.date])
        member = ms.reindex(df.index).fillna(0).to_numpy(dtype=float) > 0.5

        s200 = ds.sma(c, 200)
        above_i = np.isfinite(s200) & (c > s200)
        hi = ds.rolling_max(c, 252); lo = ds.rolling_min(c, 252)
        is_nh = np.isfinite(hi) & (c >= hi - 1e-9)
        is_nl = np.isfinite(lo) & (c <= lo + 1e-9)
        ret = np.full(len(c), np.nan); ret[1:] = c[1:] / c[:-1] - 1.0
        up = ret > 0; down = ret < 0

        # map to master positions
        idx = np.array([pos.get(d, -1) for d in dords])
        ok = (idx >= 0) & member
        if not ok.any():
            continue
        p = idx[ok]
        np.add.at(elig, p, 1.0)
        np.add.at(above, p, above_i[ok].astype(float))
        np.add.at(adv, p, up[ok].astype(float))
        np.add.at(dec, p, down[ok].astype(float))
        np.add.at(nh, p, is_nh[ok].astype(float))
        np.add.at(nl, p, is_nl[ok].astype(float))
        vok = np.nan_to_num(v[ok])
        np.add.at(totvol, p, vok)
        np.add.at(upvol, p, np.where(up[ok], vok, 0.0))
        used += 1

    enough = elig >= MIN_NAMES
    def safe(numer, denom):
        out = np.full(m, np.nan)
        good = enough & (denom > 0)
        out[good] = numer[good] / denom[good]
        return out

    return {
        "n_members_used": used,
        "elig": elig,
        "pct_above_200": safe(above, elig),
        "adv_ratio": safe(adv, adv + dec),
        "net_nhnl": safe(nh - nl, elig),
        "upvol_share": safe(upvol, totvol),
    }


def collect_breadth(n, mem_map, symbols, sym_index, base_fwd_by_sym):
    """Detect breadth triggers, measure SPY forward returns, and return a coll-style
    dict {config_id: {fwd:{h:[]}, mae:{h:[]}, sym:[], date_ord:[]}}, having
    registered SPY in sym_index / base_fwd_by_sym. Empty dict on any hard failure."""
    members = [s for s in symbols if BREADTH_INDEX in mem_map.get(s, [])]
    if len(members) < MIN_NAMES:
        print(f"[breadth] only {len(members)} {BREADTH_INDEX} members — skipping breadth",
              file=sys.stderr)
        return {}, None

    spy_df = nu.load_prices("SPY", n=n)
    if len(spy_df) < 300:
        print("[breadth] SPY history unavailable — skipping breadth", file=sys.stderr)
        return {}, None
    spy_close = spy_df["Close"].to_numpy(dtype=float)
    spy_dates = list(spy_df.index.date)

    # register SPY as a pseudo-symbol for the null / baseline
    spy_sid = sym_index.setdefault("SPY", max(sym_index.values(), default=-1) + 1)
    base_fwd_by_sym[spy_sid] = ds.build_base_fwd(spy_close)

    B = build_breadth_series(n, members, spy_df)
    print(f"[breadth] aggregated {B['n_members_used']} members on SPY axis "
          f"({len(spy_dates)} sessions)", file=sys.stderr)

    coll = {}
    n_bars = len(spy_close)
    for cfg in BREADTH_CONFIGS:
        trig = cfg["detect"](B)
        idxs = np.flatnonzero(trig)
        if idxs.size == 0:
            continue
        # collapse within CLUSTER_DAYS to name-episodes (single series)
        keep, anchor = [], -10**9
        for i in idxs:
            if i - anchor > ds.CLUSTER_DAYS:
                keep.append(int(i)); anchor = int(i)
        C = {"fwd": {h: [] for h in ds.HORIZONS}, "mae": {h: [] for h in ds.HORIZONS},
             "sym": [], "date_ord": []}
        cost = ds.COST_BPS["spy"] / 1e4
        for i in keep:
            C["sym"].append(spy_sid); C["date_ord"].append(spy_dates[i].toordinal())
            for h in ds.HORIZONS:
                j = min(i + h, n_bars - 1)
                if j <= i:
                    C["fwd"][h].append(np.nan); C["mae"][h].append(np.nan); continue
                seg = spy_close[i:j + 1] / spy_close[i] - 1.0
                C["fwd"][h].append(float(spy_close[j] / spy_close[i] - 1.0 - cost))
                C["mae"][h].append(float(seg.min()))
        coll[cfg["id"]] = C
    meta = {c["id"]: {"family": c["family"], "mechanism": c["mechanism"]} for c in BREADTH_CONFIGS}
    return coll, {"configs": meta, "n_members": len(members), "n_members_used": B["n_members_used"]}
