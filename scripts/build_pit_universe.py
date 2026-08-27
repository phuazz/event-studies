#!/usr/bin/env python
"""build_pit_universe.py — POINT-IN-TIME, survivorship-clean US equity panel.

Supersedes build_sector_breadth.py, which used CURRENT GICS over all US equities
with no index gating. This version gates membership on Norgate's true
point-in-time index constituent series (a daily 0/1 flag back to 1990), so a name
counts in a month ONLY if it was actually in the index that month.

Scale of the survivorship fix: "S&P Composite 1500 Current & Past" carries 4,260
symbols against 1,500 live; Russell 3000 C&P carries 12,367 against ~3,000.

Output (month-end records, members only) -> data/_pit_<tag>.parquet
  ym, sym, sub (GICS L4), px, above200, mom12_1, turnover60 ($ vol), upx, vol60, alive

RESIDUAL LIMIT, carried wherever this is used: GICS classification is
current/at-delisting, NOT point-in-time — a company reclassified mid-life is
mislabelled for its early years. Index membership IS point-in-time. US-listed only.

Run: python scripts/build_pit_universe.py ["S&P Composite 1500" ] [tag] [--limit N]
"""
import os, sys, time
import numpy as np, pandas as pd
import norgatedata as nd

INDEX = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "S&P Composite 1500"
TAG = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "sp1500"
LIMIT = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
WATCHLIST = f"{INDEX} Current & Past"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
START = "1990-01-01"


def main():
    syms = list(nd.watchlist_symbols(WATCHLIST))
    if LIMIT:
        syms = syms[:LIMIT]
    print(f"universe '{WATCHLIST}': {len(syms)} symbols (live + removed/delisted)")

    recs, t0, ok, skip = [], time.time(), 0, 0
    for i, s in enumerate(syms):
        if i and i % 250 == 0:
            print(f"  {i}/{len(syms)}  ok={ok} skip={skip}  {time.time()-t0:.0f}s", flush=True)
        try:
            df = nd.price_timeseries(s, start_date=START,
                                     timeseriesformat="pandas-dataframe")
            if df is None or len(df) < 260:
                skip += 1; continue
            c = df["Close"].astype(float)
            c = c[c > 0]
            if len(c) < 260:
                skip += 1; continue
            # Liquidity + tradability fields. `Turnover` is DOLLAR volume (Norgate
            # supplies it directly) — the correct liquidity measure; raw share
            # Volume is not comparable across price levels. `Unadjusted Close` is
            # needed for a penny-stock floor, because total-return-adjusted prices
            # from the 1990s are scaled far below the price actually traded.
            tno = df.get("Turnover")
            tno = tno.astype(float).reindex(c.index) if tno is not None else pd.Series(np.nan, index=c.index)
            upx = df.get("Unadjusted Close")
            upx = upx.astype(float).reindex(c.index) if upx is not None else c
            tno60 = tno.rolling(60, min_periods=30).median()
            vol60 = c.pct_change().rolling(60, min_periods=40).std() * np.sqrt(252)

            # POINT-IN-TIME membership: daily 0/1, reindexed onto this symbol's bars.
            mem = nd.index_constituent_timeseries(s, INDEX,
                                                  timeseriesformat="pandas-dataframe")
            mflag = mem["Index Constituent"].reindex(c.index).fillna(0).astype(int) \
                if mem is not None and len(mem) else pd.Series(0, index=c.index)
            if mflag.sum() == 0:
                skip += 1; continue

            sub = nd.classification_at_level(s, "GICS", "name", 4)
            if not sub:
                skip += 1; continue

            above200 = (c > c.rolling(200, min_periods=200).mean())
            me = c.resample("ME").last()                    # month-end price
            a200 = above200.resample("ME").last()
            mem_m = mflag.resample("ME").max()               # in index during that month
            t60 = tno60.resample("ME").last()
            u_m = upx.resample("ME").last()
            v60 = vol60.resample("ME").last()
            # 12-1 momentum: t-13 -> t-1 (skip the most recent month)
            mom = me.shift(1) / me.shift(13) - 1

            def _f(sr, ts):
                v = sr.get(ts, np.nan)
                return None if pd.isna(v) else float(v)

            for ts in me.index:
                if mem_m.get(ts, 0) != 1 or pd.isna(me.get(ts)):
                    continue
                recs.append((ts.strftime("%Y-%m"), s, sub, float(me[ts]),
                             bool(a200.get(ts, False)) if not pd.isna(a200.get(ts, np.nan)) else None,
                             _f(mom, ts), _f(t60, ts), _f(u_m, ts), _f(v60, ts)))
            ok += 1
        except Exception:
            skip += 1

    out = pd.DataFrame(recs, columns=["ym", "sym", "sub", "px", "above200", "mom12_1",
                                      "turnover60", "upx", "vol60"])
    p = os.path.join(DATA, f"_pit_{TAG}.parquet")
    out.to_parquet(p, index=False)
    print(f"\nwrote {p}")
    print(f"  symbols used={ok} skipped={skip}  records={len(out):,}")
    print(f"  months {out.ym.min()}..{out.ym.max()}  sub-industries={out['sub'].nunique()}")
    last = out[out.ym == out.ym.max()]
    print(f"  latest month members={len(last)}  subs={last['sub'].nunique()}")
    print(f"  elapsed {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
