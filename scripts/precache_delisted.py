#!/usr/bin/env python
"""precache_delisted.py — warm the price/membership cache for the DELISTED half of
the universe while the current-listed US Equities feed is still downloading.

Delisted names already carry full history on a fresh Platinum feed, so their bars
are stable now. Pre-pulling them in parallel with the wait roughly halves the
eventual full-scan pull time. Safe to interrupt and re-run: load_prices skips any
symbol already cached to parquet. Writes only to data/cache/ (gitignored).

    python scripts/precache_delisted.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    n = nu.connect()
    uni = nu.resolve_universe(n)
    mem_map = uni["membership_index_map"]
    delisted = [s for s in uni["symbols"] if s[-6:].isdigit() and "-" in s]
    print(f"pre-caching {len(delisted)} delisted names ...", flush=True)
    t0 = time.time()
    ok = empty = 0
    for k, s in enumerate(delisted, 1):
        try:
            df = nu.load_prices(s, n=n)
            for idx in mem_map.get(s, []):
                nu.load_membership(s, idx, n=n)
            if len(df) >= 260:
                ok += 1
            else:
                empty += 1
        except Exception:  # noqa: BLE001 - keep warming; report at the end
            empty += 1
        if k % 200 == 0:
            print(f"  {k}/{len(delisted)}  usable={ok}  {time.time()-t0:.0f}s", flush=True)
    print(f"DONE pre-cache: {ok} usable, {empty} short/failed, {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
