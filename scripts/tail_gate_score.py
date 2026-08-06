"""Tail-gate scorer (E1a successor) — G1..G5 on the pinned episode set.

Spec: studies/2026-08-06_tail-gate_preregistration.md (FROZEN, countersigned).
Input: private/studies/tail-gate-episodes.json (emitted by tail_gate_study.js
after the reconciliation gate PASSED against the filed 2026-07-17 tables).

Conventions, per the spec:
- Cash credit: exited capital earns SHY (adjusted close ratio) from exit date
  to horizon date, every exit cell, both strata. E0 is unchanged (k = H).
  Episodes whose exit predates SHY's first bar (2002) keep the ORIGINAL 0%
  convention — declared, counted, and reported; conservative against E1a.
- Costs are constant across cells (A1.2: 2 trades x 2 bps for every cell) and
  cancel in every E1a-minus-E0 difference; scoring uses gross + credit.
- CVaR-25% = mean of the worst ceil(n/4) credited final returns.
- G1 bootstrap resamples INDEPENDENT CLUSTERS (washout: 10; SPX: singleton
  episodes), 2000 draws, seeded.
- G5 placebo: same number of early exits, E1a's exit-day multiset randomly
  assigned to a random episode subset, 200 seeded draws — location null.

Run: python scripts/tail_gate_score.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EPIS = ROOT / "private" / "studies" / "tail-gate-episodes.json"
SHYF = ROOT / "private" / "studies" / "tail-gate-shy.json"
OUT = ROOT / "private" / "studies" / "tail-gate-results.json"

SEED = 20260806
BOOT = 2000
N_PLACEBO = 200
CELLS = ["E0", "E1a", "E1b", "E2a", "E2b"]
REGISTERED = {"washout (GLD+SLV)": "T1", "SPX seasonal": "T2"}


def load_shy() -> pd.Series:
    if SHYF.exists():
        d = json.loads(SHYF.read_text(encoding="utf-8"))
        s = pd.Series({pd.Timestamp(k): v for k, v in d.items()}).sort_index()
        return s
    import yfinance as yf
    px = yf.download("SHY", start="2002-01-01", auto_adjust=True,
                     progress=False)["Close"]
    if isinstance(px, pd.DataFrame):
        px = px.iloc[:, 0]
    px = px.dropna()
    SHYF.write_text(json.dumps(
        {str(k.date()): round(float(v), 6) for k, v in px.items()}),
        encoding="utf-8")
    return pd.Series({pd.Timestamp(str(k.date())): float(v)
                      for k, v in px.items()}).sort_index()


class Credit:
    def __init__(self, shy: pd.Series):
        self.shy = shy
        self.start = shy.index[0]
        self.pre_shy_exits = 0

    def factor(self, exit_d: str, horizon_d: str) -> float:
        if exit_d == horizon_d:
            return 1.0
        e, h = pd.Timestamp(exit_d), pd.Timestamp(horizon_d)
        if e < self.start:
            self.pre_shy_exits += 1
            return 1.0                    # original 0% convention, declared
        pe = float(self.shy.asof(e))
        ph = float(self.shy.asof(min(h, self.shy.index[-1])))
        return ph / pe


def cvar25(xs: np.ndarray) -> float:
    k = math.ceil(len(xs) / 4)
    return float(np.sort(xs)[:k].mean())


def score_stratum(st: dict, credit: Credit, rng: np.random.Generator) -> dict:
    eps = st["episodes"]
    H = st["horizon"]
    n = len(eps)
    clusters = sorted(set(e["cluster"] for e in eps))
    by_cluster = {c: [i for i, e in enumerate(eps) if e["cluster"] == c]
                  for c in clusters}

    credited = {}
    credit_bps = {}
    for cell in CELLS:
        vals, bps = [], []
        for e in eps:
            c = e["cells"][cell]
            f = credit.factor(c["exitDate"], c["horizonDate"])
            cr = (1.0 + c["ret"]) * f - 1.0
            vals.append(cr)
            bps.append((cr - c["ret"]) * 1e4)
        credited[cell] = np.array(vals)
        credit_bps[cell] = float(np.mean(bps))

    e0, e1a = credited["E0"], credited["E1a"]
    imp = e1a - e0
    dd = {cell: min(e["cells"][cell]["heldDD"] for e in eps)
          for cell in CELLS}

    # G1 — CVaR-25 improvement with cluster bootstrap
    d_cvar = cvar25(e1a) - cvar25(e0)
    wins = 0
    for _ in range(BOOT):
        sel = np.concatenate([by_cluster[clusters[j]] for j in
                              rng.integers(0, len(clusters), len(clusters))])
        if cvar25(e1a[sel]) - cvar25(e0[sel]) > 0:
            wins += 1
    g1_p = wins / BOOT
    g1 = d_cvar > 0 and g1_p >= 0.90

    # G2 — worst held-path DD improvement >= 3pp (known prior, floor check)
    g2 = (dd["E1a"] - dd["E0"]) >= 0.03

    # G3 — credited median harm cap 1pp
    g3 = float(np.median(e1a)) >= float(np.median(e0)) - 0.01

    # G4 — ex-best-cluster sign
    best_cluster = eps[int(np.argmax(imp))]["cluster"]
    keep = [i for i, e in enumerate(eps) if e["cluster"] != best_cluster]
    g4_d = cvar25(e1a[keep]) - cvar25(e0[keep])
    g4 = g4_d > 0

    # G5 — duration-matched random-exit placebo (location null)
    early = [i for i, e in enumerate(eps) if e["cells"]["E1a"]["k"] < H]
    ks = [eps[i]["cells"]["E1a"]["k"] for i in early]
    pl_deltas = []
    for _ in range(N_PLACEBO):
        subset = rng.choice(n, size=len(early), replace=False)
        kperm = rng.permutation(ks)
        vals = e0.copy()
        for j, kk in zip(subset, kperm):
            e = eps[int(j)]
            kk = int(min(kk, H))
            f = credit.factor(e["dates"][kk], e["dates"][H])
            vals[int(j)] = (1.0 + e["r"][kk]) * f - 1.0
        pl_deltas.append(cvar25(vals) - cvar25(e0))
    g5_p95 = float(np.quantile(pl_deltas, 0.95))
    g5 = d_cvar > g5_p95

    bars = {"G1_cvar25": g1, "G2_worstDD_floor": g2, "G3_median_cap": g3,
            "G4_ex_best_cluster": g4, "G5_random_exit_placebo": g5}
    verdict = "TAIL_CASE_REVIEW" if all(bars.values()) else "FAIL_E0_STANDS"
    if len(clusters) < 8:
        verdict = "STOP_TOO_FEW_UNITS"

    report_only = {}
    for cell in ["E1b", "E2a", "E2b"]:
        report_only[cell] = {
            "cvar25_delta": round(cvar25(credited[cell]) - cvar25(e0), 6),
            "credited_median": round(float(np.median(credited[cell])), 6),
            "worst_heldDD": round(dd[cell], 6),
            "mean_credit_bps": round(credit_bps[cell], 2),
        }

    return {
        "n_episodes": n, "n_units": len(clusters), "horizon": H,
        "cvar25_E0": round(cvar25(e0), 6), "cvar25_E1a": round(cvar25(e1a), 6),
        "d_cvar25": round(d_cvar, 6), "g1_boot_p": round(g1_p, 4),
        "worst_heldDD_E0": round(dd["E0"], 6),
        "worst_heldDD_E1a": round(dd["E1a"], 6),
        "credited_median_E0": round(float(np.median(e0)), 6),
        "credited_median_E1a": round(float(np.median(e1a)), 6),
        "mean_credit_bps_E1a": round(credit_bps["E1a"], 2),
        "g4_ex_best_cluster_delta": round(g4_d, 6),
        "g5_p95_placebo_delta": round(g5_p95, 6),
        "g5_p50_placebo_delta": round(float(np.quantile(pl_deltas, 0.50)), 6),
        "n_early_exits_E1a": len(early),
        "bars": bars, "verdict": verdict,
        "report_only": report_only,
    }


def main() -> int:
    data = json.loads(EPIS.read_text(encoding="utf-8"))
    # Phase 0 — no previously filed tail statistic (existence assertion)
    filed = json.loads((ROOT / "private" / "studies" /
                        "exit-rule-results.json").read_text(encoding="utf-8"))
    for stx in filed["strata"]:
        for c in stx["cells"]:
            assert not any("cvar" in k.lower() or "tail" in k.lower()
                           for k in c), "prior tail statistic found -> STOP"

    shy = load_shy()
    rng = np.random.default_rng(SEED)
    out = {"generatedAt": pd.Timestamp.utcnow().isoformat(),
           "spec": data["spec"], "pin": data["pin"],
           "shy": {"first": str(shy.index[0].date()),
                   "last": str(shy.index[-1].date())},
           "trials": {}}
    credit = Credit(shy)
    for st in data["strata"]:
        tid = REGISTERED[st["name"]]
        res = score_stratum(st, credit, rng)
        out["trials"][tid] = {"stratum": st["name"], **res}
        print(f"{tid} {st['name']}: dCVaR25 {res['d_cvar25']:+.4f} "
              f"(boot p {res['g1_boot_p']:.3f}) "
              f"medians {res['credited_median_E0']:+.4f} -> "
              f"{res['credited_median_E1a']:+.4f}  -> {res['verdict']}")
        for b, ok in res["bars"].items():
            if not ok:
                print(f"    fail {b}")
    out["pre_shy_exits_zero_credited"] = credit.pre_shy_exits
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"pre-SHY exits credited at 0% (declared): {credit.pre_shy_exits}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
