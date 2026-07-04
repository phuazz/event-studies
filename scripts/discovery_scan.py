#!/usr/bin/env python
"""discovery_scan.py — Stage 1 of the event-studies funnel: a DISCOVERY scan over
the Norgate point-in-time US universe that mines a FIXED archetype grammar for
extreme/event setups with genuine forward-return edge and good risk-reward, and
writes a ranked, thin-sample-flagged LEAD SHEET to private/leads/ (gitignored).

It does NOT produce a finished strategy. Each lead is a candidate for the PM's
sign-off; promotion into the pre-registered catalogue + Monte Carlo is Stage 2
(scripts/promote_lead.py). Nothing here auto-promotes; docs/ is never touched.

--------------------------------------------------------------------------------
THE THREE WAYS THIS DISCOVERY SCAN IS SILENTLY WRONG — stated before the code
(vault convention), each with its countermeasure:

  1. MULTIPLE TESTING / DATA SNOOPING — the dominant risk in discovery. Guards:
     (a) the archetype grammar below is FIXED and declared up front — it IS the
         testing budget; no free search, no archetype added mid-scan; each is a
         SMALL discrete parameter grid, no continuous optimisation;
     (b) sample split — DISCOVER on pre-2015, VALIDATE out-of-sample on
         2015->present; a lead must survive OOS (sign-consistent AND significant)
         to reach the sheet;
     (c) Benjamini-Hochberg FDR across every (archetype x parameter x horizon)
         cell, plus an explicit false-positive-count note for the budget;
     (d) cross-sectional robustness — an edge must rest on many names (and, where
         available, many sectors), not one ticker.

  2. PSEUDO-REPLICATION (time AND cross-section). Overlapping forward windows AND
     correlated names firing on the same day inflate the effective sample. Guards:
     (a) per-name triggers within clusterDays collapse to one name-episode;
     (b) the EDGE and its significance are measured at the INDEPENDENT MARKET
         EPISODE level — a calendar cluster across the whole cross-section is ONE
         observation, not 400 stock-observations (block-weighted median; a block
         bootstrap CI whose unit is the episode; a random-entry null matched to
         the exact names and episode sizes);
     (c) we HEADLINE the independent-episode count and flag any lead with < 20 as
         thin — never headlined.

  3. SURVIVORSHIP + UNIVERSE LOOK-AHEAD. Guards:
     (a) the universe is Norgate point-in-time index membership INCLUDING the
         delisted database — the name set at trigger date t is what was actually
         investable at t (norgate_universe.hard_check enforces both, HARD STOP if
         either is missing);
     (b) forward returns are delisting-aware — a position is carried to the last
         available bar, so a delisting LOSS is realised, not dropped (the same
         clamp is applied to the unconditional baseline, symmetrically);
     (c) causal indicators only; entry at the trigger close; realistic
         liquidity-tiered stock-level costs are charged before ranking.

Documented limitation of the null: within a market episode the null draws each
name's random-entry return independently, so it does not fully reproduce same-day
cross-sectional correlation; this makes the p-value a mild LOWER bound on
conservativeness. The episode-level (block-weighted) statistic, the episode block
bootstrap CI, the OOS-survival requirement and BH-FDR are the primary defences.

Date handling: horizons are TRADING days (array offsets), which sidesteps all
weekday/holiday arithmetic. The as-of date comes from the NYSE calendar via
norgate_universe. Python datetime months are 1-indexed.

Run (only after the STEP-0 gate is green — this script re-checks it and refuses a
stale feed):
    python scripts/discovery_scan.py --build-universe        # first run
    python scripts/discovery_scan.py                         # subsequent runs
    python scripts/discovery_scan.py --max-symbols 60        # fast smoke slice
    python scripts/discovery_scan.py --selftest              # indicator/stat tests
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LEADS_DIR = ROOT / "private" / "leads"

# Horizons in TRADING days — identical to engine/events.js.
HORIZONS = [5, 10, 21, 42, 63, 126, 252]
HORIZON_LABELS = ["1W", "2W", "1M", "2M", "3M", "6M", "1Y"]

OOS_START = dt.date(2015, 1, 1)      # discover < 2015; validate >= 2015
CLUSTER_DAYS = 21                    # matches the catalogue convention
BOOT_ITERS = 2000
THIN_EPISODES = 20                   # < 20 independent episodes => flagged thin
MIN_EPISODES_EVAL = 6                # below this a window is not evaluated at all
FDR_Q = 0.10                         # Benjamini-Hochberg target

# Liquidity-tiered round-trip cost (bps), charged ONCE to a held forward return.
# A long lead pays its name's cheapest available tier; a short leg would add
# borrow (grammar here is long-natured, so borrow is noted, not charged).
COST_BPS = {"large": 10.0, "mid": 20.0, "small": 40.0, "spy": 5.0}


# =============================================================================
# Indicators — all causal, mirroring engine/events.js exactly.
# =============================================================================

def wilder_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    d = np.diff(close)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        g, l = gain[i - 1], loss[i - 1]      # d[i-1] is close[i]-close[i-1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def sma(x: np.ndarray, period: int) -> np.ndarray:
    """Trailing inclusive SMA: out[i] uses x[i-period+1 .. i]."""
    n = len(x)
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[period - 1:] = (c[period:] - c[:-period]) / period
    return out


def rolling_max(x: np.ndarray, win: int) -> np.ndarray:
    n = len(x); out = np.full(n, np.nan)
    for i in range(win - 1, n):
        out[i] = np.max(x[i - win + 1:i + 1])
    return out


def rolling_min(x: np.ndarray, win: int) -> np.ndarray:
    n = len(x); out = np.full(n, np.nan)
    for i in range(win - 1, n):
        out[i] = np.min(x[i - win + 1:i + 1])
    return out


def rolling_std(x: np.ndarray, win: int) -> np.ndarray:
    """Trailing inclusive population std over `win` bars."""
    n = len(x); out = np.full(n, np.nan)
    if n < win:
        return out
    c1 = np.cumsum(np.insert(x, 0, 0.0))
    c2 = np.cumsum(np.insert(x * x, 0, 0.0))
    s = c1[win:] - c1[:-win]
    ss = c2[win:] - c2[:-win]
    var = ss / win - (s / win) ** 2
    out[win - 1:] = np.sqrt(np.maximum(var, 0.0))
    return out


def roc(close: np.ndarray, k: int) -> np.ndarray:
    n = len(close); out = np.full(n, np.nan)
    if n > k:
        out[k:] = close[k:] / close[:-k] - 1.0
    return out


def consecutive_streak(sign: np.ndarray) -> np.ndarray:
    """Length of the current run of a given boolean condition, inclusive."""
    n = len(sign); out = np.zeros(n, dtype=int)
    run = 0
    for i in range(n):
        run = run + 1 if sign[i] else 0
        out[i] = run
    return out


def onset(cond: np.ndarray) -> np.ndarray:
    """True where cond turns True (True today, not True yesterday)."""
    out = cond.copy()
    out[1:] = cond[1:] & ~cond[:-1]
    out[0] = False
    return out


def cross_below(x: np.ndarray, level: float) -> np.ndarray:
    out = np.zeros(len(x), dtype=bool)
    ok = ~np.isnan(x)
    out[1:] = ok[1:] & ok[:-1] & (x[1:] < level) & (x[:-1] >= level)
    return out


def cross_above(x: np.ndarray, level: float) -> np.ndarray:
    out = np.zeros(len(x), dtype=bool)
    ok = ~np.isnan(x)
    out[1:] = ok[1:] & ok[:-1] & (x[1:] > level) & (x[:-1] <= level)
    return out


# =============================================================================
# Archetype grammar (FIXED). Each config maps a symbol's OHLCV arrays to a boolean
# trigger array. All single-stock archetypes are long-natured hypotheses; a
# negative measured edge simply means the setup precedes declines (a possible
# short), which is flagged, not headlined as a long lead.
# =============================================================================

def _bars(p):
    return (p["open"], p["high"], p["low"], p["close"], p["vol"])


def det_rsi_below(level):
    def f(p):
        return cross_below(wilder_rsi(p["close"], 14), level)
    return f


def det_ndecline(n_days, pct):
    def f(p):
        c = p["close"]
        dec = np.zeros(len(c), dtype=bool)
        dec[n_days:] = c[n_days:] <= c[:-n_days] * (1.0 - pct)
        return onset(dec)
    return f


def det_drawdown_252(pct):
    def f(p):
        c = p["close"]
        hi = rolling_max(c, 252)
        dd = np.where(~np.isnan(hi) & (hi > 0), c / hi - 1.0, np.nan)
        cond = ~np.isnan(dd) & (dd <= -pct)
        return onset(cond)
    return f


def det_below200(pct):
    def f(p):
        c = p["close"]
        s = sma(c, 200)
        cond = ~np.isnan(s) & (c <= s * (1.0 - pct))
        return onset(cond)
    return f


def det_gapdown(pct):
    def f(p):
        o, c = p["open"], p["close"]
        out = np.zeros(len(c), dtype=bool)
        out[1:] = (o[1:] <= c[:-1] * (1.0 - pct)) & np.isfinite(o[1:]) & (c[:-1] > 0)
        return out
    return f


def det_escape_252low(roc_win, thr):
    def f(p):
        c = p["close"]
        r = roc(c, roc_win)
        lo = rolling_min(c, 252)
        is_low = ~np.isnan(lo) & (c <= lo + 1e-9)
        low_recent = np.zeros(len(c), dtype=bool)
        for i in range(len(c)):
            k0 = max(0, i - 21 + 1)
            if is_low[k0:i + 1].any():
                low_recent[i] = True
        cross = np.zeros(len(c), dtype=bool)
        cross[1:] = (r[1:] > thr) & (r[:-1] <= thr) & np.isfinite(r[1:]) & np.isfinite(r[:-1])
        return cross & low_recent
    return f


def det_roc_sigma(k, xsigma):
    def f(p):
        c = p["close"]
        r = roc(c, k)
        sd = rolling_std(r, 252)
        thr = xsigma * sd
        cond = np.isfinite(r) & np.isfinite(thr) & (thr > 0) & (r >= thr)
        return onset(cond)
    return f


def det_breakaway_gap(pct, unfilled_days=10):
    def f(p):
        o, h, l, c, _ = _bars(p)
        n = len(c)
        out = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if not (o[i] >= c[i - 1] * (1.0 + pct)) or not (c[i - 1] > 0):
                continue
            j2 = min(i + unfilled_days, n - 1)
            # unfilled == the gap floor (prior close) is not revisited by any low
            if np.all(l[i + 1:j2 + 1] > c[i - 1]) if j2 > i else True:
                out[i] = True
        return out
    return f


def det_nsigma(direction, nsig):
    def f(p):
        c = p["close"]
        ret = np.full(len(c), np.nan)
        ret[1:] = c[1:] / c[:-1] - 1.0
        sd = rolling_std(ret, 63)
        thr = nsig * sd
        if direction == "down":
            cond = np.isfinite(ret) & np.isfinite(thr) & (thr > 0) & (ret <= -thr)
        else:
            cond = np.isfinite(ret) & np.isfinite(thr) & (thr > 0) & (ret >= thr)
        # single-day dislocation: fire on the day itself (not onset)
        return cond
    return f


def det_range_expansion(mult):
    def f(p):
        o, h, l, c, _ = _bars(p)
        n = len(c)
        tr = np.full(n, np.nan)
        tr[1:] = np.maximum.reduce([
            h[1:] - l[1:],
            np.abs(h[1:] - c[:-1]),
            np.abs(l[1:] - c[:-1]),
        ])
        atr = sma(tr, 20)
        cond = np.isfinite(tr) & np.isfinite(atr) & (atr > 0) & (tr >= mult * atr)
        return onset(cond)
    return f


def det_streak(direction, k):
    def f(p):
        c = p["close"]
        ret = np.zeros(len(c))
        ret[1:] = c[1:] - c[:-1]
        sign = ret < 0 if direction == "down" else ret > 0
        streak = consecutive_streak(sign)
        # fire when the streak first reaches k
        cond = streak == k
        return cond
    return f


# The FIXED grammar. `dir`: 'long' hypothesis for all; `family` groups them.
SINGLE_STOCK_CONFIGS = [
    # --- 1. Mean reversion (long: buy the washout) ---
    {"id": "mr_rsi14_below20", "family": "mean_reversion", "detect": det_rsi_below(20),
     "mechanism": "Acute oversold (RSI14<20) overshoots on forced/again selling; a partial snap-back toward the mean is common over the following weeks."},
    {"id": "mr_rsi14_below30", "family": "mean_reversion", "detect": det_rsi_below(30),
     "mechanism": "Oversold (RSI14<30) names tend to mean-revert; the milder, more frequent cousin of the <20 washout."},
    {"id": "mr_decline5_10pct", "family": "mean_reversion", "detect": det_ndecline(5, 0.10),
     "mechanism": "A sharp 1-week drop (>=10%) is often liquidity-driven overshoot that partially reverses."},
    {"id": "mr_decline5_15pct", "family": "mean_reversion", "detect": det_ndecline(5, 0.15),
     "mechanism": "A violent 1-week drop (>=15%) marks capitulation; deeper washouts bounce harder but noisier."},
    {"id": "mr_decline10_15pct", "family": "mean_reversion", "detect": det_ndecline(10, 0.15),
     "mechanism": "A 2-week decline (>=15%) reflects sustained selling pressure prone to a relief rally."},
    {"id": "mr_decline10_20pct", "family": "mean_reversion", "detect": det_ndecline(10, 0.20),
     "mechanism": "A 2-week collapse (>=20%) is severe dislocation; strong mean-reversion candidate with tail risk."},
    {"id": "mr_ddown252_20", "family": "mean_reversion", "detect": det_drawdown_252(0.20),
     "mechanism": "First cross into a >=20% drawdown from the 1-year high — the shallow-correction reversion zone."},
    {"id": "mr_ddown252_30", "family": "mean_reversion", "detect": det_drawdown_252(0.30),
     "mechanism": "Cross into a >=30% drawdown — bear-market territory where forced deleveraging overshoots."},
    {"id": "mr_ddown252_40", "family": "mean_reversion", "detect": det_drawdown_252(0.40),
     "mechanism": "Cross into a >=40% drawdown — deep distress; large but very tail-heavy snap-backs."},
    {"id": "mr_below200_10", "family": "mean_reversion", "detect": det_below200(0.10),
     "mechanism": "Price stretched >=10% below its 200d SMA — an extended distance a downtrend rarely holds without a bounce."},
    {"id": "mr_below200_20", "family": "mean_reversion", "detect": det_below200(0.20),
     "mechanism": "Price stretched >=20% below its 200d SMA — an extreme stretch that usually mean-reverts."},
    {"id": "mr_gapdown5", "family": "mean_reversion", "detect": det_gapdown(0.05),
     "mechanism": "An overnight gap-down (>=5%) is often an over-reaction to news; part of the gap tends to fill."},
    {"id": "mr_gapdown10", "family": "mean_reversion", "detect": det_gapdown(0.10),
     "mechanism": "A severe gap-down (>=10%) — capitulation on shock news; snap-backs common but event-risk high."},

    # --- 2. Momentum thrust (long: continuation) ---
    {"id": "mo_escape252low_5d15", "family": "momentum", "detect": det_escape_252low(5, 0.15),
     "mechanism": "A 5-day thrust (>+15%) out of a 1-year low can mark a durable trend change as sellers exhaust."},
    {"id": "mo_escape252low_10d25", "family": "momentum", "detect": det_escape_252low(10, 0.25),
     "mechanism": "A 2-week surge (>+25%) escaping a 1-year low — powerful reversal-of-trend momentum."},
    {"id": "mo_roc5_3sig", "family": "momentum", "detect": det_roc_sigma(5, 3),
     "mechanism": "A 5-day return >=3 sigma is a rare momentum impulse; short-horizon continuation is common."},
    {"id": "mo_roc21_2sig", "family": "momentum", "detect": det_roc_sigma(21, 2),
     "mechanism": "A 1-month return >=2 sigma signals an accelerating trend with medium-horizon follow-through."},
    {"id": "mo_roc21_3sig", "family": "momentum", "detect": det_roc_sigma(21, 3),
     "mechanism": "A 1-month return >=3 sigma is an extreme thrust — strong but prone to mean-reversion at the tail."},
    {"id": "mo_breakaway_gap5", "family": "momentum", "detect": det_breakaway_gap(0.05),
     "mechanism": "An unfilled breakaway gap (>=5%) marks a regime shift the market refuses to fill — bullish continuation."},
    {"id": "mo_breakaway_gap10", "family": "momentum", "detect": det_breakaway_gap(0.10),
     "mechanism": "A large unfilled breakaway gap (>=10%) — decisive repricing that tends to trend."},

    # --- 3. Volatility / dislocation ---
    {"id": "vol_nsig_down3", "family": "volatility", "detect": det_nsigma("down", 3),
     "mechanism": "A -3 sigma single-day move is an acute dislocation; short-horizon mean-reversion often follows."},
    {"id": "vol_nsig_down4", "family": "volatility", "detect": det_nsigma("down", 4),
     "mechanism": "A -4 sigma crash day is extreme forced selling; sharp snap-backs are common but tail-heavy."},
    {"id": "vol_nsig_up3", "family": "volatility", "detect": det_nsigma("up", 3),
     "mechanism": "A +3 sigma single-day surge signals a demand shock with short-horizon continuation."},
    {"id": "vol_nsig_up4", "family": "volatility", "detect": det_nsigma("up", 4),
     "mechanism": "A +4 sigma spike is an extreme demand shock; momentum vs exhaustion is the empirical question."},
    {"id": "vol_range_exp2", "family": "volatility", "detect": det_range_expansion(2),
     "mechanism": "A day whose true range >=2x its 20d ATR marks a volatility regime break worth studying forward."},
    {"id": "vol_range_exp3", "family": "volatility", "detect": det_range_expansion(3),
     "mechanism": "True range >=3x ATR — a violent expansion; large information event, direction to be measured."},
    {"id": "vol_downstreak5", "family": "volatility", "detect": det_streak("down", 5),
     "mechanism": "Five consecutive down closes is a rare persistence of selling that tends to exhaust."},
    {"id": "vol_downstreak7", "family": "volatility", "detect": det_streak("down", 7),
     "mechanism": "Seven down closes in a row is deep capitulation; a bounce is statistically overdue."},
    {"id": "vol_upstreak5", "family": "volatility", "detect": det_streak("up", 5),
     "mechanism": "Five consecutive up closes reflects strong demand persistence; continuation vs pullback measured forward."},
    {"id": "vol_upstreak7", "family": "volatility", "detect": det_streak("up", 7),
     "mechanism": "Seven up closes in a row is powerful momentum, prone to a near-term pause."},
]


# =============================================================================
# Per-symbol processing
# =============================================================================

def cost_tier(indices: list) -> str:
    if "S&P 500" in indices:
        return "large"
    if "S&P MidCap 400" in indices:
        return "mid"
    return "small"


def process_symbol(sym, prices, member_any, tier, configs):
    """Return per-config entry records for one symbol.

    entry record fields (parallel arrays are assembled later):
      idx, date_ord (proleptic ordinal), tier_cost (fraction), window ('IS'/'OOS'),
      fwd[h], mae[h], mfe[h]  (long forward return / max adverse / max favourable)
    """
    close = prices["close"]
    n = len(close)
    if n < 260:
        return {}
    dates = prices["dates"]           # list of datetime.date
    date_ord = np.array([d.toordinal() for d in dates])
    cost = COST_BPS[tier] / 1e4
    out = {}
    for cfg in configs:
        trig = cfg["detect"](prices)
        trig = trig & member_any      # point-in-time membership gate
        idxs = np.flatnonzero(trig)
        if idxs.size == 0:
            continue
        # collapse per-name triggers within CLUSTER_DAYS to one name-episode
        keep = []
        anchor = -10**9
        for i in idxs:
            if i - anchor > CLUSTER_DAYS:
                keep.append(i); anchor = i
        keep = np.array(keep)
        recs = []
        for i in keep:
            row = {"idx": int(i), "date": dates[i]}
            fwd, mae, mfe = {}, {}, {}
            for h in HORIZONS:
                j = min(i + h, n - 1)
                if j <= i:
                    fwd[h] = mae[h] = mfe[h] = np.nan
                    continue
                seg = close[i:j + 1] / close[i] - 1.0
                fwd[h] = float(close[j] / close[i] - 1.0 - cost)   # net of cost
                mae[h] = float(seg.min())
                mfe[h] = float(seg.max())
            row["fwd"], row["mae"], row["mfe"] = fwd, mae, mfe
            recs.append(row)
        out[cfg["id"]] = recs
    return out


# =============================================================================
# Statistics — block-weighted edge + episode-level significance
# =============================================================================

def cluster_market_episodes(date_ords: np.ndarray, cluster_days: int) -> np.ndarray:
    """Assign each entry an independent-market-episode id: entries whose (sorted)
    trigger dates fall within cluster_days of the running anchor share an id."""
    order = np.argsort(date_ords, kind="mergesort")
    ep = np.empty(len(date_ords), dtype=int)
    cur = -1; anchor = -10**9
    for pos in order:
        d = date_ords[pos]
        if d - anchor > cluster_days:
            cur += 1; anchor = d
        ep[pos] = cur
    return ep


def _sortino(x: np.ndarray) -> float:
    if x.size == 0:
        return float("nan")
    downside = np.minimum(x, 0.0)
    dd = np.sqrt(np.mean(downside ** 2))
    return float(np.mean(x) / dd) if dd > 0 else float("inf")


def analyse_cell(fwd, mae, sym_ids, episodes, base_fwd_by_sym, horizon, rng):
    """One (config, horizon, window) cell. Inputs are already finite-masked.

    fwd/mae : per-entry net forward return / max adverse excursion (long) arrays
    episodes: per-entry independent-market-episode id (0..n_ind-1)

    Edge + significance are at the INDEPENDENT-EPISODE level (block-weighted):
    mean within episode, then median over episodes, so a same-day cross-section of
    names counts once, not N times. The null is per-name-matched random entry,
    vectorised with np.add.reduceat over contiguous episode blocks. Risk metrics
    (hit, tails, reward-to-MAE, Sortino) are entry-weighted per-trade.
    """
    n_trades = fwd.size
    if n_trades == 0:
        return None

    # sort entries into contiguous episode blocks for reduceat
    order = np.argsort(episodes, kind="mergesort")
    f = fwd[order]; s = sym_ids[order]; ep = episodes[order]
    ep_starts = np.concatenate(([0], np.flatnonzero(np.diff(ep)) + 1))
    sizes = np.diff(np.concatenate((ep_starts, [n_trades]))).astype(float)
    n_ind = ep_starts.size

    # --- block-weighted edge ---
    ep_means = np.add.reduceat(f, ep_starts) / sizes
    cond_median = float(np.median(ep_means))

    # --- entry-weighted per-trade risk profile ---
    hit = float((fwd > 0).mean())
    p05, p95 = float(np.quantile(fwd, 0.05)), float(np.quantile(fwd, 0.95))
    med_mae = float(np.median(mae))
    reward_to_mae = float(cond_median / abs(med_mae)) if med_mae < 0 else float("inf")
    sortino = _sortino(fwd)

    # --- episode block bootstrap CI on the block-weighted edge ---
    pick = rng.integers(0, n_ind, size=(BOOT_ITERS, n_ind))
    boot = np.median(ep_means[pick], axis=1)
    ci_lo, ci_hi = float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95))

    # --- per-name-matched random-entry null, vectorised over episode blocks ---
    # Memory guard: cap iterations so the (B x n_trades) draw stays ~<=10M cells.
    b_eff = int(min(BOOT_ITERS, max(500, 10_000_000 // max(n_trades, 1))))
    vals = np.empty((b_eff, n_trades), dtype=np.float64)
    for su in np.unique(s):
        cols = np.flatnonzero(s == su)
        arr = base_fwd_by_sym[su][horizon]
        if arr.size == 0:
            vals[:, cols] = np.nan
        else:
            vals[:, cols] = arr[rng.integers(0, arr.size, size=(b_eff, cols.size))]
    ep_sum_null = np.add.reduceat(vals, ep_starts, axis=1)
    null_med = np.nanmedian(ep_sum_null / sizes, axis=1)
    ge = int(np.sum(null_med >= cond_median))
    p_two = 2.0 * min(ge, b_eff - ge) / b_eff
    percentile = 1.0 - ge / b_eff

    # --- robustness across names ---
    uniq_syms = np.unique(sym_ids)
    frac_pos = float(np.mean([np.median(fwd[sym_ids == su]) > 0 for su in uniq_syms]))

    return {
        "n_trades": int(n_trades),
        "n_independent_episodes": int(n_ind),
        "cond_median": cond_median,
        "hit_rate": hit,
        "p05": p05, "p95": p95,
        "median_mae": med_mae,
        "reward_to_mae": reward_to_mae,
        "sortino": sortino,
        "ci_lo": ci_lo, "ci_hi": ci_hi,
        "p_value": p_two,
        "null_percentile": percentile,
        "n_names": int(uniq_syms.size),
        "frac_names_positive": frac_pos,
    }


def baseline_cell(base_fwd_by_sym, horizon):
    """Unconditional pooled baseline for a horizon: median/mean/hit over all names'
    (delisting-clamped) forward returns."""
    parts = [base_fwd_by_sym[s][horizon] for s in base_fwd_by_sym
             if base_fwd_by_sym[s][horizon].size]
    if not parts:
        return {"base_median": float("nan"), "base_mean": float("nan"), "base_hit": float("nan"), "base_n": 0}
    allv = np.concatenate(parts)
    return {"base_median": float(np.median(allv)), "base_mean": float(np.mean(allv)),
            "base_hit": float((allv > 0).mean()), "base_n": int(allv.size)}


# =============================================================================
# Benjamini-Hochberg FDR
# =============================================================================

def benjamini_hochberg(pvals: list, q: float):
    """Return (reject_flags, qvalues) aligned to the input order."""
    m = len(pvals)
    if m == 0:
        return [], []
    order = np.argsort(pvals, kind="mergesort")
    ranked = np.array(pvals)[order]
    qvals_sorted = ranked * m / (np.arange(1, m + 1))
    # enforce monotonicity
    qvals_sorted = np.minimum.accumulate(qvals_sorted[::-1])[::-1]
    reject_sorted = ranked <= (np.arange(1, m + 1) / m) * q
    qvals = np.empty(m); reject = np.empty(m, dtype=bool)
    qvals[order] = np.minimum(qvals_sorted, 1.0)
    reject[order] = reject_sorted
    return reject.tolist(), qvals.tolist()


# =============================================================================
# Selftest — indicator + stat sanity, no Norgate needed
# =============================================================================

def selftest():
    # RSI on a strictly rising series -> 100 once defined.
    up = np.arange(1, 40, dtype=float)
    r = wilder_rsi(up, 14)
    assert abs(r[20] - 100.0) < 1e-9, r[20]
    # SMA inclusive trailing.
    x = np.array([1, 2, 3, 4, 5], dtype=float)
    s = sma(x, 3)
    assert np.isnan(s[1]) and abs(s[2] - 2.0) < 1e-12 and abs(s[4] - 4.0) < 1e-12, s
    # rolling std matches numpy population std.
    sd = rolling_std(x, 3)
    assert abs(sd[2] - np.std(x[0:3])) < 1e-9, (sd[2], np.std(x[0:3]))
    # onset / cross helpers.
    c = np.array([0, 0, 1, 1, 0, 1], dtype=bool)
    assert list(onset(c).astype(int)) == [0, 0, 1, 0, 0, 1]
    xr = np.array([40, 35, 25, 22, 31], dtype=float)
    assert list(cross_below(xr, 30).astype(int)) == [0, 0, 1, 0, 0]
    # streak.
    sign = np.array([1, 1, 1, 0, 1], dtype=bool)
    assert list(consecutive_streak(sign)) == [1, 2, 3, 0, 1]
    # BH monotonic + rejects an obvious signal.
    rej, q = benjamini_hochberg([0.001, 0.2, 0.9, 0.04], 0.10)
    assert rej[0] is True and q[0] <= q[3] <= q[1] <= q[2]
    # sortino sign.
    assert _sortino(np.array([0.02, 0.03, -0.01])) > 0
    print("[selftest] discovery_scan indicator + stat tests passed")
    return 0


# =============================================================================
# Orchestration
# =============================================================================

def build_base_fwd(close: np.ndarray):
    """Per-name delisting-clamped unconditional forward returns for each horizon."""
    n = len(close)
    out = {}
    for h in HORIZONS:
        if n < 2:
            out[h] = np.array([])
            continue
        idx = np.arange(0, n - 1)
        j = np.minimum(idx + h, n - 1)
        out[h] = (close[j] / close[idx] - 1.0).astype(np.float32)
    return out


def run_scan(max_symbols=None, rebuild_universe=False, refresh_prices=False, seed=12345):
    rng = np.random.default_rng(seed)
    t0 = time.time()
    n = nu.connect()
    proof = nu.hard_check(n)
    print("[gate] PASS — feed fresh, delisted + membership present", file=sys.stderr)

    uni = nu.resolve_universe(n, rebuild=rebuild_universe)
    symbols = uni["symbols"]
    mem_map = uni["membership_index_map"]
    if max_symbols:
        symbols = symbols[:max_symbols]
    print(f"[universe] {len(symbols)} symbols ({uni['method']})", file=sys.stderr)

    # --- per-symbol pass: load, gate, detect, collect ---
    sym_index = {s: k for k, s in enumerate(symbols)}
    base_fwd_by_sym = {}
    # per config: lists we will vectorise later
    coll = {c["id"]: {"fwd": {h: [] for h in HORIZONS}, "mae": {h: [] for h in HORIZONS},
                      "sym": [], "date_ord": []} for c in SINGLE_STOCK_CONFIGS}
    loaded = skipped = 0
    for k, s in enumerate(symbols, 1):
        try:
            df = nu.load_prices(s, n=n, refresh=refresh_prices)
        except Exception as exc:  # noqa: BLE001
            skipped += 1; continue
        if len(df) < 260:
            skipped += 1; continue
        close = df["Close"].to_numpy(dtype=float)
        prices = {
            "open": df["Open"].to_numpy(dtype=float),
            "high": df["High"].to_numpy(dtype=float),
            "low": df["Low"].to_numpy(dtype=float),
            "close": close,
            "vol": df["Volume"].to_numpy(dtype=float),
            "dates": list(df.index.date),
        }
        # point-in-time membership: member of AT LEAST ONE target index at t
        member_any = np.zeros(len(close), dtype=bool)
        for idx_name in mem_map.get(s, []):
            try:
                ms = nu.load_membership(s, idx_name, n=n)
            except Exception:  # noqa: BLE001
                continue
            if ms.size:
                aligned = ms.reindex(df.index).fillna(0).to_numpy(dtype=float) > 0.5
                member_any |= aligned
        if not member_any.any():
            skipped += 1; continue

        sid = sym_index[s]
        base_fwd_by_sym[sid] = build_base_fwd(close)
        tier = cost_tier(mem_map.get(s, []))
        per_cfg = process_symbol(s, prices, member_any, tier, SINGLE_STOCK_CONFIGS)
        for cid, recs in per_cfg.items():
            C = coll[cid]
            for row in recs:
                do = row["date"].toordinal()
                C["sym"].append(sid); C["date_ord"].append(do)
                for h in HORIZONS:
                    C["fwd"][h].append(row["fwd"][h]); C["mae"][h].append(row["mae"][h])
        loaded += 1
        if k % 100 == 0:
            print(f"  ... {k}/{len(symbols)} symbols, {loaded} loaded, {time.time()-t0:.0f}s",
                  file=sys.stderr)

    # --- breadth archetypes (index-level, point-in-time; target SPY) ---
    config_meta = {c["id"]: {"family": c["family"], "mechanism": c["mechanism"]}
                   for c in SINGLE_STOCK_CONFIGS}
    breadth_info = None
    try:
        import breadth_scan
        b_coll, breadth_info = breadth_scan.collect_breadth(
            n, mem_map, symbols, sym_index, base_fwd_by_sym)
        if b_coll:
            coll.update(b_coll)
            for cid, meta in breadth_info["configs"].items():
                config_meta[cid] = meta
    except Exception as exc:  # noqa: BLE001 - breadth must never kill the core sheet
        print(f"[breadth] skipped ({exc})", file=sys.stderr)

    # --- baselines: pooled single-stock universe, and SPY (for breadth) ---
    baseline = {h: baseline_cell(base_fwd_by_sym, h) for h in HORIZONS}
    spy_sid = sym_index.get("SPY")
    spy_baseline = None
    if spy_sid is not None and spy_sid in base_fwd_by_sym:
        spy_baseline = {}
        for h in HORIZONS:
            arr = base_fwd_by_sym[spy_sid][h]
            spy_baseline[h] = {"base_median": float(np.median(arr)) if arr.size else float("nan"),
                               "base_hit": float((arr > 0).mean()) if arr.size else float("nan")}

    # --- per (config, horizon, window) analysis ---
    cells = []   # flat list of cell dicts (for CSV + FDR)
    for cid, C in coll.items():
        if not C["sym"]:
            continue
        meta = config_meta.get(cid, {"family": "unknown", "mechanism": ""})
        is_breadth = meta["family"] == "breadth"
        sym_ids = np.array(C["sym"]); date_ords = np.array(C["date_ord"])
        is_mask = date_ords < OOS_START.toordinal()
        for h in HORIZONS:
            fwd_all = np.array(C["fwd"][h]); mae_all = np.array(C["mae"][h])
            for win, mask in (("IS", is_mask), ("OOS", ~is_mask), ("ALL", np.ones_like(is_mask))):
                f, mae = fwd_all[mask], mae_all[mask]
                sid, do = sym_ids[mask], date_ords[mask]
                fin = np.isfinite(f)
                if fin.sum() < MIN_EPISODES_EVAL:
                    continue
                episodes = cluster_market_episodes(do[fin], CLUSTER_DAYS)
                res = analyse_cell(f[fin], mae[fin], sid[fin], episodes,
                                   base_fwd_by_sym, h, rng)
                if res is None:
                    continue
                b = (spy_baseline or baseline)[h] if is_breadth else baseline[h]
                res.update({
                    "config": cid, "family": meta["family"], "horizon": h,
                    "horizon_label": HORIZON_LABELS[HORIZONS.index(h)], "window": win,
                    "base_median": b["base_median"], "base_hit": b["base_hit"],
                    "lift_median": res["cond_median"] - b["base_median"],
                    "lift_hit": res["hit_rate"] - b["base_hit"],
                    "mechanism": meta["mechanism"],
                })
                cells.append(res)

    # --- Benjamini-Hochberg across all OOS cells ---
    oos_cells = [c for c in cells if c["window"] == "OOS"]
    rej, qv = benjamini_hochberg([c["p_value"] for c in oos_cells], FDR_Q)
    for c, r, q in zip(oos_cells, rej, qv):
        c["fdr_reject"] = bool(r); c["q_value"] = float(q)

    n_breadth = len(breadth_info["configs"]) if breadth_info else 0
    return {
        "proof": proof, "universe": {k: uni[k] for k in ("index_names", "breadth_index", "method", "counts")},
        "baseline": baseline, "spy_baseline": spy_baseline, "breadth_info": breadth_info,
        "cells": cells, "oos_cells": oos_cells,
        "loaded": loaded, "skipped": skipped, "seconds": round(time.time() - t0, 1),
        "n_configs": len(SINGLE_STOCK_CONFIGS) + n_breadth,
        "n_single_stock_configs": len(SINGLE_STOCK_CONFIGS), "n_breadth_configs": n_breadth,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-universe", action="store_true")
    ap.add_argument("--refresh-prices", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.selftest:
        return selftest()

    out = run_scan(max_symbols=args.max_symbols, rebuild_universe=args.build_universe,
                   refresh_prices=args.refresh_prices)
    from lead_sheet import write_lead_sheet  # local import to keep selftest light
    paths = write_lead_sheet(out)
    print("\n=== discovery scan complete ===")
    print(f"  loaded {out['loaded']} symbols, skipped {out['skipped']}, {out['seconds']}s")
    print(f"  cells tested: {len(out['cells'])} ({out['n_configs']} configs x {len(HORIZONS)} horizons x windows)")
    for p in paths:
        print(f"  wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
